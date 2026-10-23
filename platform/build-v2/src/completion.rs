//! Validated local outputs remain independent of cache publication availability.
use crate::groups::{OutputGroupContract, PlanRoster};
use crate::install::LeaseIdentity;
use crate::keys::PreparedUnit;
use crate::leases::{LeaseRecord, LeaseStore, ProcessIdentity, sync_dir};
use crate::results::{
    ActualOutput, ENVELOPE_VERSION, FrozenOutput, ResultEnvelope, ResultError, ResultStore,
    freeze_partitioned, partition_outputs,
};
use crate::schema::{RESULT_SCHEMA_VERSION, ResultRecord};
use crate::store::{ObjectDigest, PreparedObject, StoreError};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

/// Durable local work custody created before the job or unknown-digest snapshots write.
/// Drop preserves the scope and its real owner/worker identities; no clock-only cleanup.
pub struct CompletionWork {
    pub(crate) root: PathBuf,
    pub(crate) leases: LeaseStore,
    pub(crate) lease: LeaseRecord,
    unit: PreparedUnit,
    identity: LeaseIdentity,
}

/// Private verified byte snapshots and complete validated manifest, never a StoredHit.
/// Dropping it retains local evidence and its lease; it cannot certify cache availability.
pub struct FrozenCompletion {
    pub(crate) work: CompletionWork,
    pub(crate) envelope: ResultEnvelope,
    pub(crate) objects: Vec<PreparedObject>,
    pub(crate) refused: bool,
}

impl CompletionWork {
    pub(crate) fn begin(
        root: &Path,
        unit: &PreparedUnit,
        identity: LeaseIdentity,
    ) -> Result<Self, ResultError> {
        for process in std::iter::once(&identity.owner).chain(&identity.workers) {
            if process.pid == 0 || process.boot.is_empty() || process.started.is_empty() {
                return Err(ResultError::Invalid(
                    "complete local process identity required".into(),
                ));
            }
        }
        let root = root.canonicalize()?;
        let leases = LeaseStore::open(&root)?;
        let mut keys = identity.upstream_result_keys.clone();
        keys.insert(unit.key().into());
        for key in &keys {
            ObjectDigest::from_hex(key)?;
        }
        let lease = leases.begin(keys, identity.owner.clone(), identity.workers.clone())?;
        Ok(Self {
            root,
            leases,
            lease,
            unit: unit.clone(),
            identity,
        })
    }
    pub fn lease(&self) -> &LeaseRecord {
        &self.lease
    }
    pub fn job_dir(&self) -> PathBuf {
        self.root.join(&self.lease.staging).join("job")
    }
    pub fn add_worker(&mut self, worker: ProcessIdentity) -> Result<(), ResultError> {
        if worker.pid == 0 || worker.boot.is_empty() || worker.started.is_empty() {
            return Err(ResultError::Invalid(
                "complete local worker identity required".into(),
            ));
        }
        if !self.lease.workers.contains(&worker) {
            let mut updated = self.lease.clone();
            updated.workers.push(worker);
            self.leases.lock()?.save(&updated)?;
            self.lease = updated;
        }
        Ok(())
    }
    /// @cc [owner:fontanierh,label:correctness;safety] local-completion-freeze-once
    /// The complete authoritative worker manifest MUST pass the same fixed/group validators as B2.
    /// Validators MUST read the exact independent snapshots hashed once here; no live reread or
    /// unchecked digest may certify local install or subsequent cache publication. The durable
    /// local lease precedes every snapshot; failure/drop MUST preserve local evidence and ownership.
    pub fn freeze(
        self,
        actual: Vec<ActualOutput>,
        fixed: impl FnOnce(&[FrozenOutput<'_>]) -> Result<(), String>,
        groups: impl FnMut(
            &OutputGroupContract,
            &PlanRoster,
            &BTreeMap<String, &PreparedObject>,
        ) -> Result<(), String>,
    ) -> Result<FrozenCompletion, ResultError> {
        let (fixed_sources, group_sources) = partition_outputs(&self.unit, actual)?;
        let scope = self.root.join(&self.lease.staging);
        let (outputs, output_groups, objects) = freeze_partitioned(
            &self.unit,
            fixed_sources,
            group_sources,
            fixed,
            groups,
            |source| PreparedObject::freeze_local(source, &scope).map_err(ResultError::Store),
        )?;
        let envelope = ResultEnvelope {
            version: ENVELOPE_VERSION,
            result: ResultRecord {
                schema_version: RESULT_SCHEMA_VERSION,
                unit: self.unit.request("", "").unit,
                key: self.unit.key().into(),
                ingredients: self.unit.ingredients().clone(),
                outputs,
                output_groups,
                provenance: self.identity.provenance.clone(),
            },
            upstream_result_keys: self.identity.upstream_result_keys.clone(),
        };
        // Persist a complete evidence record before allowing the job folder to be retired.
        let path = scope.join("completion.json");
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        use std::io::Write;
        let members: Vec<_> = objects.iter().map(|object| Ok(serde_json::json!({"path": object.local_path(&scope)?, "digest":object.digest().as_hex(), "size":object.size(), "source_mode":object.source_mode()}))).collect::<Result<_, StoreError>>()?;
        let record = serde_json::json!({"version":1, "envelope":envelope, "objects":members});
        file.write_all(&crate::keys::canonical_bytes(&record).map_err(ResultError::Invalid)?)?;
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(fs::Permissions::from_mode(0o444))?;
        file.sync_all()?;
        sync_dir(&scope)?;
        Ok(FrozenCompletion {
            work: self,
            envelope,
            objects,
            refused: false,
        })
    }
}
impl FrozenCompletion {
    pub fn result(&self) -> &ResultEnvelope {
        &self.envelope
    }
    pub fn lease(&self) -> &LeaseRecord {
        &self.work.lease
    }
    /// Cache admission/publication consumes independent clones of verified snapshots, never this proof.
    /// Validation and nondeterminism errors stay hard; the caller may retain locally on cache I/O failure.
    pub fn publish(
        &mut self,
        store: &ResultStore,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> Result<ResultEnvelope, ResultError> {
        if self.refused {
            return Err(ResultError::Invalid(
                "completion already refused a semantic publication conflict".into(),
            ));
        }
        let outcome = (|| {
            store
                .begin(
                    &self.work.unit,
                    self.work.identity.provenance.clone(),
                    self.work.lease.owner.clone(),
                    self.work.lease.workers.clone(),
                    self.envelope.upstream_result_keys.clone(),
                )?
                .stage_completion(self)?
                .publish(root)
        })();
        if matches!(
            &outcome,
            Err(ResultError::Validation(_) | ResultError::Nondeterminism(_))
        ) {
            self.refused = true;
        }
        outcome
    }
    pub(crate) fn clone_to(
        &self,
        digest: &ObjectDigest,
        destination: &Path,
    ) -> Result<(), StoreError> {
        self.objects
            .iter()
            .find(|object| object.digest() == digest)
            .ok_or(StoreError::InvalidFile("uncertified local digest"))?
            .clone_to(destination)
    }
}
