//! Per-unit immutable result publication. B3 installs and B4 root policy are separate.
use crate::keys::{PreparedUnit, canonical_bytes, normalized_mode};
use crate::leases::{LeaseRecord, LeaseStore, ProcessIdentity, directory, sync_dir};
use crate::schema::{
    Destination, Item, Provenance, RESULT_SCHEMA_VERSION, ResultRecord, StoredFile, StoredItem,
};
use crate::store::{ObjectDigest, ObjectStore, PreparedObject, StoreError};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const ENVELOPE_VERSION: u32 = 1;
pub type OutputSources = BTreeMap<(String, String), PathBuf>;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResultEnvelope {
    pub version: u32,
    pub result: ResultRecord,
    /// Retention links, never semantic inputs or winner-comparison ingredients.
    /// First-winner lineage remains immutable alongside its original provenance.
    pub upstream_result_keys: BTreeSet<String>,
}

#[derive(Debug)]
pub enum ResultError {
    Invalid(String),
    Validation(String),
    Root(String),
    Nondeterminism(String),
    Io(io::Error),
    Store(StoreError),
}
impl fmt::Display for ResultError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(reason) => write!(formatter, "invalid result: {reason}"),
            Self::Validation(reason) => write!(formatter, "output validation: {reason}"),
            Self::Root(reason) => write!(formatter, "root publication: {reason}"),
            Self::Nondeterminism(key) => {
                write!(formatter, "different outputs for result key {key}")
            }
            Self::Io(error) => error.fmt(formatter),
            Self::Store(error) => error.fmt(formatter),
        }
    }
}
impl std::error::Error for ResultError {}
impl From<io::Error> for ResultError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}
impl From<StoreError> for ResultError {
    fn from(value: StoreError) -> Self {
        Self::Store(value)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PublicationStep {
    Prepared,
    Claimed,
    ObjectPublished,
    RecordPublished,
    Rooted,
    Released,
}

#[derive(Clone, Debug)]
pub struct ResultStore {
    objects: ObjectStore,
    leases: LeaseStore,
}

/// Dropping a transaction preserves its durable claims. Recovery/GC may reclaim
/// only under the shared mutex and positive death evidence for owner AND workers.
pub struct WriteTransaction {
    store: ResultStore,
    lease: LeaseRecord,
    unit: PreparedUnit,
    provenance: Provenance,
    upstream: BTreeSet<String>,
}

pub struct FrozenOutput<'a> {
    pub item: &'a Item,
    pub path: &'a str,
    pub object: &'a PreparedObject,
}

/// Only stage() constructs this token, after schema and caller format validation
/// of the exact frozen snapshots which are subsequently published.
pub struct StagedResult {
    transaction: WriteTransaction,
    envelope: ResultEnvelope,
    objects: Vec<PreparedObject>,
}

fn invalid(reason: impl Into<String>) -> ResultError {
    ResultError::Invalid(reason.into())
}
fn digest(value: &str) -> Result<(), ResultError> {
    ObjectDigest::from_hex(value)?;
    Ok(())
}

impl ResultStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, ResultError> {
        let objects = ObjectStore::open(root)?;
        directory(&objects.root().join("results"))?;
        let leases = LeaseStore::open(objects.root())?;
        sync_dir(objects.root())?;
        Ok(Self { objects, leases })
    }
    pub fn leases(&self) -> &LeaseStore {
        &self.leases
    }

    pub fn begin(
        &self,
        unit: &PreparedUnit,
        provenance: Provenance,
        owner: ProcessIdentity,
        workers: Vec<ProcessIdentity>,
        upstream_result_keys: BTreeSet<String>,
    ) -> Result<WriteTransaction, ResultError> {
        digest(unit.key())?;
        for key in &upstream_result_keys {
            digest(key)?;
        }
        for identity in std::iter::once(&owner).chain(workers.iter()) {
            if identity.pid == 0 || identity.boot.is_empty() || identity.started.is_empty() {
                return Err(invalid("complete process identity is required"));
            }
        }
        // The incomplete consumer record cannot yet retain its producers by traversal.
        // Protect upstream records before work starts, not just after record publication.
        let mut claimed_results = upstream_result_keys.clone();
        claimed_results.insert(unit.key().into());
        let lease = self.leases.begin(claimed_results, owner, workers)?;
        Ok(WriteTransaction {
            store: self.clone(),
            lease,
            unit: unit.clone(),
            provenance,
            upstream: upstream_result_keys,
        })
    }

    fn record_path(&self, key: &str) -> PathBuf {
        self.objects
            .root()
            .join("results")
            .join(format!("{key}.json"))
    }

    // Caller holds the metadata lock. Direct record/object lookups only; no output walk/hash.
    fn read(&self, unit: &PreparedUnit) -> Result<Option<ResultEnvelope>, ResultError> {
        let path = self.record_path(unit.key());
        match fs::symlink_metadata(&path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
            Ok(metadata) if !metadata.is_file() || !metadata.permissions().readonly() => {
                return Err(invalid("stored result must be regular and read-only"));
            }
            _ => {}
        }
        let envelope: ResultEnvelope =
            serde_json::from_slice(&fs::read(path)?).map_err(|error| invalid(error.to_string()))?;
        if envelope.version != ENVELOPE_VERSION
            || envelope.result.schema_version != RESULT_SCHEMA_VERSION
            || envelope.result.key != unit.key()
            || &envelope.result.ingredients != unit.ingredients()
        {
            return Err(invalid("stored result version/key/ingredients differ"));
        }
        check_manifest(unit, &envelope.result.outputs)?;
        for key in &envelope.upstream_result_keys {
            digest(key)?;
        }
        for file in envelope.result.outputs.iter().flat_map(|item| &item.files) {
            self.objects
                .check_recorded(&ObjectDigest::from_hex(&file.digest)?, file.size)?;
        }
        Ok(Some(envelope))
    }
}

fn check_manifest(unit: &PreparedUnit, outputs: &[StoredItem]) -> Result<(), ResultError> {
    let expected = &unit.ingredients().logical_outputs;
    if outputs.len() != expected.len() {
        return Err(invalid("wrong output item count"));
    }
    for (item, stored) in expected.iter().zip(outputs) {
        if item != &stored.item
            || stored.external_locator.is_some()
            || item.destination == Destination::External
        {
            return Err(invalid(
                "output declaration differs or requires external adapter",
            ));
        }
        let mut seen = BTreeSet::new();
        for file in &stored.files {
            digest(&file.digest)?;
            if !seen.insert(file.path.clone())
                || !item.files.iter().any(|expected| expected.path == file.path)
                || ![0o644, 0o755].contains(&file.mode)
            {
                return Err(invalid("undeclared/duplicate output or invalid mode"));
            }
        }
        if item
            .files
            .iter()
            .any(|file| file.required && !seen.contains(&file.path))
        {
            return Err(invalid("missing required output"));
        }
    }
    Ok(())
}

impl WriteTransaction {
    pub fn lease(&self) -> &LeaseRecord {
        &self.lease
    }

    /// A lifecycle adapter must persist a newly launched worker's full identity
    /// before allowing that worker to write. Startup barriers/process probing are C5b/C7.
    pub fn add_worker(&mut self, worker: ProcessIdentity) -> Result<(), ResultError> {
        if worker.pid == 0 || worker.boot.is_empty() || worker.started.is_empty() {
            return Err(invalid("complete worker identity is required"));
        }
        if !self.lease.workers.contains(&worker) {
            let guard = self.store.leases.lock()?;
            let mut updated = self.lease.clone();
            updated.workers.push(worker);
            guard.save(&updated)?;
            self.lease = updated;
        }
        Ok(())
    }

    /// Pin every named object under the GC mutex before returning a hit.
    /// Complete with retain_hit(); dropping this handle conservatively retains claims.
    pub fn lookup(&mut self) -> Result<Option<ResultEnvelope>, ResultError> {
        let guard = self.store.leases.lock()?;
        let result = self.store.read(&self.unit)?;
        if let Some(envelope) = &result {
            self.lease.object_digests.extend(
                envelope
                    .result
                    .outputs
                    .iter()
                    .flat_map(|item| &item.files)
                    .map(|file| file.digest.clone()),
            );
            guard.save(&self.lease)?;
        }
        Ok(result)
    }

    /// Validates exact output membership, freezes each file once, then asks the op
    /// validator to inspect those same bytes. No publication happens on validation failure.
    pub fn stage(
        self,
        mut sources: OutputSources,
        validator: impl FnOnce(&[FrozenOutput<'_>]) -> Result<(), String>,
    ) -> Result<StagedResult, ResultError> {
        let mut outputs = vec![];
        let mut objects = vec![];
        let mut labels = vec![];
        for item in &self.unit.ingredients().logical_outputs {
            if item.destination == Destination::External {
                return Err(invalid("external result needs its adapter"));
            }
            let mut files = vec![];
            for file in &item.files {
                let key = (item.id.clone(), file.path.clone());
                let Some(source) = sources.remove(&key) else {
                    if file.required {
                        return Err(invalid(format!("missing output {}", file.path)));
                    }
                    continue;
                };
                let object = self.store.objects.prepare_in(
                    &source,
                    &self.store.objects.root().join(&self.lease.staging),
                )?;
                files.push(StoredFile {
                    path: file.path.clone(),
                    digest: object.digest().to_string(),
                    size: object.size(),
                    mode: normalized_mode(object.source_mode()),
                });
                labels.push((item, file.path.as_str()));
                objects.push(object);
            }
            outputs.push(StoredItem {
                item: item.clone(),
                files,
                external_locator: None,
            });
        }
        if !sources.is_empty() {
            return Err(invalid("undeclared output sources"));
        }
        let frozen: Vec<_> = labels
            .iter()
            .zip(&objects)
            .map(|((item, path), object)| FrozenOutput { item, path, object })
            .collect();
        validator(&frozen).map_err(ResultError::Validation)?;
        let envelope = ResultEnvelope {
            version: ENVELOPE_VERSION,
            result: ResultRecord {
                schema_version: RESULT_SCHEMA_VERSION,
                unit: self.unit.request("", "").unit,
                key: self.unit.key().into(),
                ingredients: self.unit.ingredients().clone(),
                outputs,
                provenance: self.provenance.clone(),
            },
            upstream_result_keys: self.upstream.clone(),
        };
        check_manifest(&self.unit, &envelope.result.outputs)?;
        Ok(StagedResult {
            transaction: self,
            envelope,
            objects,
        })
    }

    pub fn retain_hit(
        mut self,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> Result<ResultEnvelope, ResultError> {
        let winner = self
            .lookup()?
            .ok_or_else(|| invalid("result is not a hit"))?;
        root(&winner).map_err(ResultError::Root)?;
        self.release()?;
        Ok(winner)
    }

    fn release(&mut self) -> Result<(), ResultError> {
        let guard = self.store.leases.lock()?;
        self.lease.result_keys.clear();
        self.lease.object_digests.clear();
        self.lease.rooted = true;
        guard.save(&self.lease)?;
        Ok(())
    }
}

impl StagedResult {
    pub fn envelope(&self) -> &ResultEnvelope {
        &self.envelope
    }

    pub fn publish(
        self,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> Result<ResultEnvelope, ResultError> {
        self.publish_observed(root, |_| Ok(()))
    }

    /// @cc [owner:fontanierh,label:correctness] leased-result-publication
    /// Publication MUST durably claim object names under the shared GC mutex before
    /// publishing objects, then publish the immutable first-winner record, call the
    /// required durable root callback, and only then release per-unit claims. Faults
    /// before durable rooting MUST preserve claims; no fault may erase earlier results.
    /// Equality MUST ignore unit
    /// labels, provenance and upstream retention links. See tests/results.rs.
    pub fn publish_observed(
        mut self,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
        mut observe: impl FnMut(PublicationStep) -> io::Result<()>,
    ) -> Result<ResultEnvelope, ResultError> {
        observe(PublicationStep::Prepared)?;
        {
            let guard = self.transaction.store.leases.lock()?;
            self.transaction.lease.object_digests.extend(
                self.objects
                    .iter()
                    .map(|object| object.digest().to_string()),
            );
            guard.save(&self.transaction.lease)?;
        }
        observe(PublicationStep::Claimed)?;
        for object in self.objects.drain(..) {
            {
                let _guard = self.transaction.store.leases.lock()?;
                self.transaction.store.objects.publish(object)?;
            }
            observe(PublicationStep::ObjectPublished)?;
        }
        let winner = {
            let _guard = self.transaction.store.leases.lock()?;
            match self.transaction.store.read(&self.transaction.unit)? {
                Some(winner) => {
                    // The producing input key is equal; compare full semantic output view.
                    if winner.result.outputs != self.envelope.result.outputs {
                        return Err(ResultError::Nondeterminism(
                            self.envelope.result.key.clone(),
                        ));
                    }
                    winner
                }
                None => {
                    self.save_record()?;
                    self.envelope.clone()
                }
            }
        };
        observe(PublicationStep::RecordPublished)?;
        root(&winner).map_err(ResultError::Root)?;
        observe(PublicationStep::Rooted)?;
        self.transaction.release()?;
        observe(PublicationStep::Released)?;
        Ok(winner)
    }

    fn save_record(&self) -> Result<(), ResultError> {
        let scope = self
            .transaction
            .store
            .objects
            .root()
            .join(&self.transaction.lease.staging);
        let path = scope.join("result.json");
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        file.write_all(&canonical_bytes(&self.envelope).map_err(invalid)?)?;
        let mut permissions = file.metadata()?.permissions();
        permissions.set_readonly(true);
        file.set_permissions(permissions)?;
        file.sync_all()?;
        let destination = self
            .transaction
            .store
            .record_path(&self.envelope.result.key);
        // Same filesystem, atomic no-replace link. Unlike rename, existing names never
        // change. This links immutable metadata only, never mutable payload/output files.
        fs::hard_link(&path, &destination)?;
        sync_dir(destination.parent().unwrap())?;
        fs::remove_file(&path)?;
        sync_dir(&scope)?;
        Ok(())
    }
}
