//! Per-unit demand decisions. Scheduling, worker staging and root policy are separate.
use crate::checkout_locks::BuildGuard;
use crate::groups::ValidatedGroup;
use crate::install::{
    CheckoutInstaller, CurrentStatus, InstallError, ItemReceipt, LeaseIdentity, OwnershipSnapshot,
    ReceiptReader, RemovalIntent, RestoreLookup, RestorePlan,
};
use crate::integrity::{LookupDecision, NonHitReason, classify_lookup_result};
use crate::keys::PreparedUnit;
use crate::results::{ResultEnvelope, ResultError, ResultStore, WriteTransaction};
use std::collections::BTreeMap;

/// A miss is not permission to write without a lease. When available, dispatch must
/// reuse this original transaction. An unavailable cache may require B7/A9's separate
/// local-completion policy; this layer never manufactures a cached result.
pub struct CacheMiss {
    pub reason: NonHitReason,
    pub transaction: Option<WriteTransaction>,
    pub failure: Option<ResultError>,
}

pub enum CheckoutResolution {
    Current(Vec<ItemReceipt>),
    Hit(RestorePlan),
    Miss(CacheMiss),
}

pub enum StoredResolution {
    Hit(StoredHit),
    Miss(CacheMiss),
}

/// Constructed only by a checked, durably pinned B2 lookup. A cached result says
/// nothing about checkout materialization; Current receipts say nothing about cache.
pub struct StoredHit {
    transaction: WriteTransaction,
    envelope: ResultEnvelope,
    groups: BTreeMap<String, ValidatedGroup>,
}

impl StoredHit {
    pub fn result(&self) -> &ResultEnvelope {
        &self.envelope
    }

    pub fn groups(&self) -> &BTreeMap<String, ValidatedGroup> {
        &self.groups
    }

    /// Claims release only after the caller's required durable root succeeds.
    /// On error, B2 preserves the original claims.
    pub fn retain(
        self,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> Result<ResultEnvelope, ResultError> {
        self.transaction.retain_hit(root)
    }
}

fn failure(error: ResultError, transaction: Option<WriteTransaction>) -> CacheMiss {
    let result: Result<Option<()>, _> = Err(error);
    let LookupDecision::Miss(reason) = classify_lookup_result(&result) else {
        unreachable!("an error cannot certify a hit")
    };
    CacheMiss {
        reason,
        transaction,
        failure: result.err(),
    }
}

fn absent(transaction: WriteTransaction) -> CacheMiss {
    CacheMiss {
        reason: NonHitReason::MissingRecord,
        transaction: Some(transaction),
        failure: None,
    }
}

/// @cc [owner:fontanierh,label:correctness] demand-current-before-cache
/// Checkout demand MUST check B3 receipts before invoking the lazy cache opener.
/// Current MUST return without opening cache, cloning files, rewriting receipts or
/// demanding ancestors. Cache availability MUST NOT invalidate a Current checkout.
/// A B3 lock, recovery or ownership refusal MUST remain a hard error, never a miss.
/// See tests/demand.rs; production scheduler integration remains A9 pending.
pub fn checkout(
    reader: &ReceiptReader,
    guard: &BuildGuard,
    unit: &PreparedUnit,
    open_cache: impl FnOnce() -> Result<CheckoutInstaller, InstallError>,
    identity: LeaseIdentity,
    ownership: &OwnershipSnapshot,
    removals: Vec<RemovalIntent>,
) -> Result<CheckoutResolution, InstallError> {
    // Retirement authority is checkout input, never a cache-health observation.
    // Validate it through B3 before even opening a potentially unavailable cache.
    reader.preflight_removals(guard, ownership, &removals)?;
    if let CurrentStatus::Current(receipts) = reader.receipt_status(guard, unit)? {
        // Explicit retirements are work even when the surviving unit is current.
        if removals.is_empty() {
            return Ok(CheckoutResolution::Current(receipts));
        }
    }
    let installer = match open_cache() {
        Ok(installer) => installer,
        Err(InstallError::Cache(error)) => {
            return Ok(CheckoutResolution::Miss(failure(error, None)));
        }
        Err(error) => return Err(error),
    };
    match installer.lookup_restore(guard, unit, identity, ownership, removals) {
        Ok(RestoreLookup::Hit(plan)) => Ok(CheckoutResolution::Hit(plan)),
        Ok(RestoreLookup::Miss(transaction)) => Ok(CheckoutResolution::Miss(absent(transaction))),
        Err(InstallError::Cache(error)) => Ok(CheckoutResolution::Miss(failure(error, None))),
        Err(error) => Err(error),
    }
}

/// @cc [owner:fontanierh,label:correctness] demand-stored-without-install
/// Stored demand MUST perform one B2 begin/lookup, return private checked/pinned
/// group tokens only for a hit, and preserve the original transaction on a miss.
/// It MUST NOT install checkout outputs, request ancestor materialization, rehash
/// payload bytes or invoke the offline verifier. See tests/demand.rs.
pub fn stored(
    unit: &PreparedUnit,
    open_cache: impl FnOnce() -> Result<ResultStore, ResultError>,
    identity: LeaseIdentity,
) -> StoredResolution {
    let store = match open_cache() {
        Ok(store) => store,
        Err(error) => return StoredResolution::Miss(failure(error, None)),
    };
    let mut transaction = match store.begin(
        unit,
        identity.provenance,
        identity.owner,
        identity.workers,
        identity.upstream_result_keys,
    ) {
        Ok(transaction) => transaction,
        Err(error) => return StoredResolution::Miss(failure(error, None)),
    };
    match transaction.lookup_groups() {
        Ok(Some((envelope, groups))) => StoredResolution::Hit(StoredHit {
            transaction,
            envelope,
            groups,
        }),
        Ok(None) => StoredResolution::Miss(absent(transaction)),
        Err(error) => StoredResolution::Miss(failure(error, Some(transaction))),
    }
}
