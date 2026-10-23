//! Pure integrity and store-error classification decisions for B7/A5/A9.
//! Not yet wired into production or the A5/B3/A9 execution loop.
use crate::results::ResultError;
use crate::store::StoreError;
use crate::verify::{ObjectOutcome, RecordOutcome};
use std::io;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NonHitReason {
    MissingRecord,
    MissingObject,
    CorruptRecord,
    CorruptObject,
    MalformedRecord,
    MalformedObject,
    IncompleteManifest,
    UnsupportedRecord,
    ExternalUnverified,
    UnverifiedSample,
    StoreFailure,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LookupDecision {
    Hit,
    Miss(NonHitReason),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RestoreDecision {
    Restored,
    /// APFS clone failed or is unsupported; callers must report this explicitly and never copy bytes.
    UnsupportedClone,
    Miss(NonHitReason),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LocalOutputStatus {
    Valid,
    Invalid(String),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoreFailureKind {
    Io,
    CloneUnsupported,
    StoreMetadata,
    RootCallback,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UnitFailureReason {
    InvalidOutput(String),
    Nondeterminism(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CompletionDecision {
    Cached,
    CompletedNotCached(StoreFailureKind),
    FailUnit(UnitFailureReason),
}

pub fn classify_record_outcome(outcome: &RecordOutcome) -> LookupDecision {
    match outcome {
        RecordOutcome::Verified { .. } => LookupDecision::Hit,
        RecordOutcome::Missing { .. } => LookupDecision::Miss(NonHitReason::MissingRecord),
        RecordOutcome::MissingObjects { .. } => LookupDecision::Miss(NonHitReason::MissingObject),
        RecordOutcome::Corrupt { .. } => LookupDecision::Miss(NonHitReason::CorruptRecord),
        RecordOutcome::Malformed { .. } => LookupDecision::Miss(NonHitReason::MalformedRecord),
        RecordOutcome::IncompleteManifest { .. } => {
            LookupDecision::Miss(NonHitReason::IncompleteManifest)
        }
        RecordOutcome::Unsupported { .. } => LookupDecision::Miss(NonHitReason::UnsupportedRecord),
        RecordOutcome::External { .. } => LookupDecision::Miss(NonHitReason::ExternalUnverified),
        RecordOutcome::Unverified { .. } => LookupDecision::Miss(NonHitReason::UnverifiedSample),
    }
}

pub fn classify_object_outcome(outcome: &ObjectOutcome) -> LookupDecision {
    match outcome {
        ObjectOutcome::Verified { .. } => LookupDecision::Hit,
        ObjectOutcome::Missing { .. } => LookupDecision::Miss(NonHitReason::MissingObject),
        ObjectOutcome::Corrupt { .. } => LookupDecision::Miss(NonHitReason::CorruptObject),
        ObjectOutcome::Malformed { .. } => LookupDecision::Miss(NonHitReason::MalformedObject),
        ObjectOutcome::Unverified { .. } => LookupDecision::Miss(NonHitReason::UnverifiedSample),
    }
}

/// @cc [owner:fontanierh,label:correctness] build-v2-normal-hit-no-rehash
/// Normal result lookup and object clone restoration MUST check only record and object metadata
/// and clone via APFS without rehashing stored payload bytes or scanning output folders. Explicit
/// verification is opt-in and separate from normal lookup and restore. See tests/verify.rs.
pub fn classify_lookup_result<T>(result: &Result<Option<T>, ResultError>) -> LookupDecision {
    match result {
        Ok(Some(_)) => LookupDecision::Hit,
        Ok(None) => LookupDecision::Miss(NonHitReason::MissingRecord),
        Err(ResultError::Store(StoreError::InvalidDigest)) => {
            LookupDecision::Miss(NonHitReason::MalformedObject)
        }
        Err(ResultError::Store(StoreError::InvalidFile(_))) => {
            LookupDecision::Miss(NonHitReason::CorruptObject)
        }
        Err(ResultError::Store(StoreError::Io(err))) if err.kind() == io::ErrorKind::NotFound => {
            LookupDecision::Miss(NonHitReason::MissingObject)
        }
        Err(ResultError::Invalid(_)) => LookupDecision::Miss(NonHitReason::CorruptRecord),
        Err(
            ResultError::Io(_)
            | ResultError::Store(_)
            | ResultError::Validation(_)
            | ResultError::Root(_)
            | ResultError::Nondeterminism(_),
        ) => LookupDecision::Miss(NonHitReason::StoreFailure),
    }
}

pub fn classify_restore_result(result: &Result<(), StoreError>) -> RestoreDecision {
    match result {
        Ok(()) => RestoreDecision::Restored,
        Err(StoreError::Clone(_)) => RestoreDecision::UnsupportedClone,
        Err(StoreError::InvalidDigest) => RestoreDecision::Miss(NonHitReason::MalformedObject),
        Err(StoreError::InvalidFile(_)) => RestoreDecision::Miss(NonHitReason::CorruptObject),
        Err(StoreError::Io(err)) if err.kind() == io::ErrorKind::NotFound => {
            RestoreDecision::Miss(NonHitReason::MissingObject)
        }
        Err(StoreError::Io(_) | StoreError::WrongStore) => {
            RestoreDecision::Miss(NonHitReason::StoreFailure)
        }
    }
}

/// @cc [owner:fontanierh,label:correctness] build-v2-cache-failure-preserves-valid-work
/// Store, lease, clone or root publication failures after local output validation MUST keep
/// valid locally completed work as CompletedNotCached rather than failing the unit. Invalid
/// producer output, output validation failure and same-key output nondeterminism MUST fail the
/// unit and MUST NEVER become Cached or CompletedNotCached. Unsupported clone operations MUST be
/// reported explicitly without byte-copy fallback.
pub fn classify_completion<T>(
    local: LocalOutputStatus,
    store_result: Result<T, ResultError>,
) -> CompletionDecision {
    if let LocalOutputStatus::Invalid(reason) = local {
        return CompletionDecision::FailUnit(UnitFailureReason::InvalidOutput(reason));
    }
    match store_result {
        Ok(_) => CompletionDecision::Cached,
        Err(ResultError::Validation(reason)) => {
            CompletionDecision::FailUnit(UnitFailureReason::InvalidOutput(reason))
        }
        Err(ResultError::Nondeterminism(key)) => {
            CompletionDecision::FailUnit(UnitFailureReason::Nondeterminism(key))
        }
        Err(ResultError::Store(StoreError::Clone(_))) => {
            CompletionDecision::CompletedNotCached(StoreFailureKind::CloneUnsupported)
        }
        Err(ResultError::Store(StoreError::Io(_)) | ResultError::Io(_)) => {
            CompletionDecision::CompletedNotCached(StoreFailureKind::Io)
        }
        Err(ResultError::Root(_)) => {
            CompletionDecision::CompletedNotCached(StoreFailureKind::RootCallback)
        }
        Err(ResultError::Invalid(_) | ResultError::Store(_)) => {
            CompletionDecision::CompletedNotCached(StoreFailureKind::StoreMetadata)
        }
    }
}
