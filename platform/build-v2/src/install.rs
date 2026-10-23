//! Exact-owned-set checkout installs. Store/root/worker lifecycle policy remains separate.
//! Checkpoint: planning/receipt readers only; journal commit/recovery and acceptance tests
//! are still under implementation. No production caller uses this draft module.
use crate::checkout_locks::{BuildGuard, CheckoutLocks, INSTALL_METADATA, LockError};
use crate::graph::BuildGraph;
pub use crate::install_fs::FileObservation;
use crate::install_fs::{CreatedDirectory, RootFs};
use crate::keys::{PreparedUnit, canonical_bytes};
use crate::leases::ProcessIdentity;
use crate::paths::{Claims, claim, conflict, folded, logical_path, relative_path};
use crate::results::{ResultEnvelope, ResultError, ResultStore, WriteTransaction};
use crate::schema::{ContentSource, Destination, Input, Item, Provenance, StoredFile};
use crate::source_hashes::sha256;
use crate::store::{ObjectDigest, ObjectStore, StoreError};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::io;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

pub const RECEIPT_VERSION: u32 = 1;
pub const JOURNAL_VERSION: u32 = 1;
const INDEX: &str = "build/build-v2/install/index.json";
const JOURNAL: &str = "build/build-v2/install/journal.json";
static NEXT: AtomicU64 = AtomicU64::new(0);

#[derive(Debug)]
pub enum InstallError {
    Invalid(String),
    RecoveryRequired(String),
    Lock(LockError),
    Cache(ResultError),
    Store(StoreError),
    Io(io::Error),
}
impl fmt::Display for InstallError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(reason) => write!(formatter, "invalid install: {reason}"),
            Self::RecoveryRequired(reason) => {
                write!(formatter, "install recovery required: {reason}")
            }
            Self::Lock(error) => error.fmt(formatter),
            Self::Cache(error) => error.fmt(formatter),
            Self::Store(error) => error.fmt(formatter),
            Self::Io(error) => error.fmt(formatter),
        }
    }
}
impl std::error::Error for InstallError {}
impl From<io::Error> for InstallError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}
impl From<LockError> for InstallError {
    fn from(error: LockError) -> Self {
        Self::Lock(error)
    }
}
impl From<ResultError> for InstallError {
    fn from(error: ResultError) -> Self {
        Self::Cache(error)
    }
}
impl From<StoreError> for InstallError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}
fn invalid(reason: impl Into<String>) -> InstallError {
    InstallError::Invalid(reason.into())
}
fn recovery(reason: impl Into<String>) -> InstallError {
    InstallError::RecoveryRequired(reason.into())
}
fn bytes(value: &impl Serialize) -> Result<Vec<u8>, InstallError> {
    canonical_bytes(value).map_err(invalid)
}
fn digest(value: &str) -> Result<(), InstallError> {
    ObjectDigest::from_hex(value)?;
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ProjectNamespace(String);
impl ProjectNamespace {
    pub fn new(value: &str) -> Result<Self, InstallError> {
        if value.is_empty()
            || value == "."
            || value == ".."
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_.:-".contains(&byte))
        {
            return Err(invalid(
                "project namespace must be a stable explicit opaque identifier",
            ));
        }
        Ok(Self(value.into()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Namespace is explicit project identity, never selected roots/targets or a unit label.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OwnerId {
    pub project: ProjectNamespace,
    pub logical_path: String,
}
impl OwnerId {
    pub fn new(project: ProjectNamespace, path: &str) -> Result<Self, InstallError> {
        logical_path(path).map_err(invalid)?;
        Ok(Self {
            project,
            logical_path: folded(path),
        })
    }
    fn fingerprint(&self) -> Result<String, InstallError> {
        Ok(sha256(&bytes(self)?))
    }
}

#[derive(Clone, Debug)]
pub struct InstallPolicy {
    pub project: ProjectNamespace,
    pub allowed_install_roots: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReceiptFile {
    pub output_path: String,
    pub install_path: String,
    pub digest: String,
    pub size: u64,
    pub mode: u32,
    pub observation: FileObservation,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ItemReceipt {
    pub version: u32,
    pub owner: OwnerId,
    pub logical_path: String,
    pub class: String,
    pub result_key: String,
    pub files: Vec<ReceiptFile>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReceiptIndex {
    version: u32,
    /// Owner fingerprint -> immutable item receipt ID.
    receipts: BTreeMap<String, String>,
    /// Normalized checkout-relative file path -> owner fingerprint, across ALL projects.
    paths: BTreeMap<String, String>,
}
impl Default for ReceiptIndex {
    fn default() -> Self {
        Self {
            version: RECEIPT_VERSION,
            receipts: BTreeMap::new(),
            paths: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug)]
struct DeclaredOwner {
    class: String,
    files: BTreeMap<String, (String, bool)>,
}

/// Pure complete declared ownership/reference/source view, not just selected targets.
/// The caller supplies every project declaration relevant to this checkout.
#[derive(Clone, Debug)]
pub struct OwnershipSnapshot {
    projects: BTreeSet<ProjectNamespace>,
    owners: BTreeMap<OwnerId, DeclaredOwner>,
    paths: Claims,
    sources: Claims,
    references: BTreeSet<OwnerId>,
}
impl OwnershipSnapshot {
    pub fn from_projects<'a>(
        projects: impl IntoIterator<Item = (ProjectNamespace, &'a BuildGraph)>,
    ) -> Result<Self, InstallError> {
        let mut view = Self {
            projects: BTreeSet::new(),
            owners: BTreeMap::new(),
            paths: Claims::new(),
            sources: Claims::new(),
            references: BTreeSet::new(),
        };
        for (namespace, graph) in projects {
            if !view.projects.insert(namespace.clone()) {
                return Err(invalid("duplicate project ownership view"));
            }
            for unit in &graph.declaration().units {
                for path in &unit.code {
                    claim_source(&mut view.sources, path)?;
                }
                for input in &unit.inputs {
                    match input {
                        Input::Content {
                            source: ContentSource::File { path, .. },
                            ..
                        } => claim_source(&mut view.sources, path)?,
                        Input::Reference { logical_path, .. } => {
                            view.references
                                .insert(OwnerId::new(namespace.clone(), logical_path)?);
                        }
                        _ => {}
                    }
                }
                for item in &unit.outputs {
                    if item.destination != Destination::Checkout {
                        continue;
                    }
                    let owner = OwnerId::new(namespace.clone(), &item.logical_path)?;
                    let fingerprint = owner.fingerprint()?;
                    let mut files = BTreeMap::new();
                    for file in &item.files {
                        let path = file
                            .install_path
                            .as_ref()
                            .ok_or_else(|| invalid("checkout output lacks install mapping"))?;
                        relative_path(path, true).map_err(invalid)?;
                        claim(&mut view.paths, path, &fingerprint).map_err(invalid)?;
                        files.insert(file.path.clone(), (path.clone(), file.required));
                    }
                    if view
                        .owners
                        .insert(
                            owner,
                            DeclaredOwner {
                                class: item.class.clone(),
                                files,
                            },
                        )
                        .is_some()
                    {
                        return Err(invalid("duplicate logical owner"));
                    }
                }
            }
        }
        for (path, _) in view.paths.values() {
            if conflict(&view.sources, path).is_some() {
                return Err(invalid("checkout output overlaps current source/code"));
            }
        }
        Ok(view)
    }
}
fn claim_source(claims: &mut Claims, path: &str) -> Result<(), InstallError> {
    relative_path(path, false).map_err(invalid)?;
    // Sources may share/overlap declarations. Retain every normalized claim so a
    // later wider source cannot disappear behind an earlier narrower claim.
    claims
        .entry(folded(path))
        .or_insert((path.into(), "declared source/code".into()));
    Ok(())
}

#[derive(Clone, Debug)]
pub struct RemovalIntent {
    pub owner: OwnerId,
    pub expected_receipt_id: String,
    pub exact_paths: BTreeSet<String>,
}

pub struct LeaseIdentity {
    pub provenance: Provenance,
    pub owner: ProcessIdentity,
    pub workers: Vec<ProcessIdentity>,
    pub upstream_result_keys: BTreeSet<String>,
}

#[derive(Clone, Debug)]
pub enum CurrentStatus {
    Current(Vec<ItemReceipt>),
    Dirty,
    NotMaterialized,
}

#[derive(Clone)]
pub struct CheckoutInstaller {
    locks: CheckoutLocks,
    fs: Arc<RootFs>,
    objects: ObjectStore,
    results: ResultStore,
    policy: InstallPolicy,
    reserved: Claims,
}

#[derive(Clone, Debug)]
struct DesiredFile {
    owner: OwnerId,
    output_path: String,
    install_path: String,
    stored: StoredFile,
}

/// Only prepare_restore constructs this pinned plan. Retrying Busy keeps the plan.
pub struct RestorePlan {
    installer: CheckoutInstaller,
    transaction: Option<WriteTransaction>,
    result: ResultEnvelope,
    view: OwnershipSnapshot,
    removals: Vec<RemovalIntent>,
    desired: BTreeMap<String, DesiredFile>,
    items: BTreeMap<OwnerId, Item>,
}

impl CheckoutInstaller {
    pub fn open(
        checkout: impl AsRef<Path>,
        store: impl AsRef<Path>,
        policy: InstallPolicy,
    ) -> Result<Self, InstallError> {
        ProjectNamespace::new(policy.project.as_str())?;
        let locks = CheckoutLocks::open(checkout)?;
        let fs = Arc::new(RootFs::open(locks.root())?);
        let objects = ObjectStore::open(store)?;
        let results = ResultStore::open(objects.root())?;
        let mut reserved = Claims::new();
        claim(&mut reserved, ".git", "git metadata").map_err(invalid)?;
        claim(&mut reserved, INSTALL_METADATA, "install metadata/locks").map_err(invalid)?;
        if let Ok(relative) = objects.root().strip_prefix(locks.root()) {
            let relative = relative
                .to_str()
                .ok_or_else(|| invalid("in-checkout store path is not UTF-8"))?;
            relative_path(relative, true).map_err(invalid)?;
            reserved.insert(folded(relative), (relative.into(), "object store".into()));
        }
        if policy.allowed_install_roots.is_empty() {
            return Err(invalid("no install roots supplied"));
        }
        for root in &policy.allowed_install_roots {
            relative_path(root, true).map_err(invalid)?;
        }
        fs.mkdirs(&format!("{INSTALL_METADATA}/receipts"), 0o700)?;
        fs.mkdirs(&format!("{INSTALL_METADATA}/transactions"), 0o700)?;
        Ok(Self {
            locks,
            fs,
            objects,
            results,
            policy,
            reserved,
        })
    }
    pub fn locks(&self) -> &CheckoutLocks {
        &self.locks
    }
    fn guard(&self, guard: &BuildGuard) -> Result<(), InstallError> {
        if guard.root() != self.locks.root() {
            return Err(invalid("build guard belongs to another checkout"));
        }
        Ok(())
    }
    fn output_path(&self, path: &str) -> Result<(), InstallError> {
        relative_path(path, true).map_err(invalid)?;
        if conflict(&self.reserved, path).is_some()
            || !self
                .policy
                .allowed_install_roots
                .iter()
                .any(|root| path.starts_with(&(root.clone() + "/")))
        {
            return Err(invalid(
                "install path is outside allowed roots or overlaps protected metadata",
            ));
        }
        Ok(())
    }
    fn index(&self) -> Result<ReceiptIndex, InstallError> {
        let bytes = match self.fs.read(INDEX) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Ok(ReceiptIndex::default());
            }
            Err(error) => return Err(error.into()),
        };
        let index: ReceiptIndex = decode(&bytes)?;
        if index.version != RECEIPT_VERSION {
            return Err(recovery("unsupported receipt index"));
        }
        for (owner, receipt) in &index.receipts {
            digest(owner)?;
            digest(receipt)?;
        }
        let mut claims = self.reserved.clone();
        for (path, owner) in &index.paths {
            relative_path(path, true).map_err(invalid)?;
            if path != &folded(path) || !index.receipts.contains_key(owner) {
                return Err(recovery("invalid receipt path owner"));
            }
            claim(&mut claims, path, owner).map_err(recovery)?;
        }
        Ok(index)
    }
    fn receipt(&self, id: &str) -> Result<ItemReceipt, InstallError> {
        digest(id)?;
        let path = format!("{INSTALL_METADATA}/receipts/{id}.json");
        let data = self.fs.read(&path)?;
        if sha256(&data) != id {
            return Err(recovery("receipt content does not match its identity"));
        }
        let receipt: ItemReceipt = decode(&data)?;
        ProjectNamespace::new(receipt.owner.project.as_str())?;
        if receipt.version != RECEIPT_VERSION
            || OwnerId::new(receipt.owner.project.clone(), &receipt.logical_path)? != receipt.owner
            || receipt.class.is_empty()
        {
            return Err(recovery("invalid receipt owner/version/class"));
        }
        digest(&receipt.result_key)?;
        let mut claims = Claims::new();
        for file in &receipt.files {
            relative_path(&file.output_path, true).map_err(invalid)?;
            relative_path(&file.install_path, true).map_err(invalid)?;
            if conflict(&self.reserved, &file.install_path).is_some() {
                return Err(recovery("receipt overlaps protected metadata"));
            }
            claim(&mut claims, &file.install_path, "receipt output").map_err(recovery)?;
            digest(&file.digest)?;
            if ![0o644, 0o755].contains(&file.mode)
                || file.size != file.observation.size
                || file.mode != file.observation.mode
            {
                return Err(recovery("invalid receipt file mode/size"));
            }
        }
        Ok(receipt)
    }

    pub fn receipt_status(
        &self,
        guard: &BuildGuard,
        unit: &PreparedUnit,
    ) -> Result<CurrentStatus, InstallError> {
        self.guard(guard)?;
        let items: Vec<_> = unit
            .ingredients()
            .logical_outputs
            .iter()
            .filter(|item| item.destination == Destination::Checkout)
            .collect();
        if items.is_empty() {
            return Ok(CurrentStatus::NotMaterialized);
        }
        let _reader = self.locks.try_read_content()?;
        let index = self.index()?;
        let mut receipts = vec![];
        for item in items {
            let owner = OwnerId::new(self.policy.project.clone(), &item.logical_path)?;
            let Some(id) = index.receipts.get(&owner.fingerprint()?) else {
                return Ok(CurrentStatus::Dirty);
            };
            let receipt = self.receipt(id)?;
            if receipt.owner != owner
                || receipt.result_key != unit.key()
                || receipt.class != item.class
            {
                return Ok(CurrentStatus::Dirty);
            }
            let mut found = BTreeSet::new();
            for file in &receipt.files {
                if !item.files.iter().any(|expected| {
                    expected.path == file.output_path
                        && expected.install_path.as_ref() == Some(&file.install_path)
                }) || index.paths.get(&folded(&file.install_path)) != Some(&owner.fingerprint()?)
                    || self.fs.observe(&file.install_path)? != Some(file.observation.clone())
                {
                    return Ok(CurrentStatus::Dirty);
                }
                found.insert(file.output_path.clone());
            }
            if item
                .files
                .iter()
                .any(|file| file.required && !found.contains(&file.path))
            {
                return Ok(CurrentStatus::Dirty);
            }
            receipts.push(receipt);
        }
        Ok(CurrentStatus::Current(receipts))
    }

    pub fn prepare_restore(
        &self,
        guard: &BuildGuard,
        unit: &PreparedUnit,
        identity: LeaseIdentity,
        view: &OwnershipSnapshot,
        removals: Vec<RemovalIntent>,
    ) -> Result<Option<RestorePlan>, InstallError> {
        self.guard(guard)?;
        if !view.projects.contains(&self.policy.project) {
            return Err(invalid("missing complete project ownership view"));
        }
        let mut transaction = self.results.begin(
            unit,
            identity.provenance,
            identity.owner,
            identity.workers,
            identity.upstream_result_keys,
        )?;
        let Some(result) = transaction.lookup()? else {
            return Ok(None);
        };
        let mut desired = BTreeMap::new();
        let mut items = BTreeMap::new();
        for stored in &result.result.outputs {
            if stored.item.destination != Destination::Checkout {
                continue;
            }
            let owner = OwnerId::new(self.policy.project.clone(), &stored.item.logical_path)?;
            let definition = view.owners.get(&owner).ok_or_else(|| {
                invalid("result logical owner is absent from current declaration")
            })?;
            if definition.class != stored.item.class {
                return Err(invalid("result class differs from declared owner"));
            }
            for file in &stored.files {
                let declared = stored
                    .item
                    .files
                    .iter()
                    .find(|expected| expected.path == file.path)
                    .ok_or_else(|| invalid("unknown saved output"))?;
                let path = declared
                    .install_path
                    .clone()
                    .ok_or_else(|| invalid("missing output install mapping"))?;
                if definition.files.get(&file.path) != Some(&(path.clone(), declared.required)) {
                    return Err(invalid("result mapping differs from current declaration"));
                }
                self.output_path(&path)?;
                if conflict(&view.sources, &path).is_some() {
                    return Err(invalid(
                        "install would overwrite a declared source/code path",
                    ));
                }
                if desired
                    .insert(
                        folded(&path),
                        DesiredFile {
                            owner: owner.clone(),
                            output_path: file.path.clone(),
                            install_path: path,
                            stored: file.clone(),
                        },
                    )
                    .is_some()
                {
                    return Err(invalid("duplicate desired output"));
                }
            }
            items.insert(owner, stored.item.clone());
        }
        for removal in &removals {
            if removal.owner.project != self.policy.project
                || view.owners.contains_key(&removal.owner)
                || view.references.contains(&removal.owner)
            {
                return Err(invalid(
                    "removal belongs to another project or a live owner/reference",
                ));
            }
            digest(&removal.expected_receipt_id)?;
            for path in &removal.exact_paths {
                self.output_path(path)?;
                if conflict(&view.sources, path).is_some() {
                    return Err(invalid("removal would delete a declared source/code path"));
                }
            }
        }
        Ok(Some(RestorePlan {
            installer: self.clone(),
            transaction: Some(transaction),
            result,
            view: view.clone(),
            removals,
            desired,
            items,
        }))
    }
}

fn decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, InstallError> {
    if bytes.iter().find(|byte| !byte.is_ascii_whitespace()) != Some(&b'{') {
        return Err(recovery("install metadata must be an object"));
    }
    serde_json::from_slice(bytes).map_err(|error| recovery(error.to_string()))
}
