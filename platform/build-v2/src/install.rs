//! Exact-owned-set checkout installs. Store/root/worker lifecycle policy remains separate.
//! Checkpoint: journal commit/recovery is drafted; acceptance tests and hosted compilation
//! are still pending. No production caller uses this draft module.
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

/// Fault boundaries are after durable journal/publication steps, never successful stamps.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InstallEvent {
    JournalCreated,
    FileStaged(usize),
    Ready,
    OldMoved(usize),
    NewMoved(usize),
    ReceiptsReady,
    IndexCommitted,
    CleanupComplete,
}

#[derive(Debug)]
pub enum InstallOutcome {
    Installed,
    /// Checkout receipts are committed. B2 keeps its lease when rooting fails.
    InstalledWithRootPending(String),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalEntry {
    old_path: Option<String>,
    old: Option<FileObservation>,
    destination: String,
    stage: String,
    trash: String,
    new: Option<StoredFile>,
    staged: Option<FileObservation>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct InstallJournal {
    version: u32,
    project: ProjectNamespace,
    scope: String,
    old_index: ReceiptIndex,
    after_index: Option<ReceiptIndex>,
    ready: bool,
    entries: Vec<JournalEntry>,
    directories: Vec<CreatedDirectory>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalRecord {
    digest: String,
    journal: InstallJournal,
}

impl CheckoutInstaller {
    fn journal_present(&self) -> Result<bool, InstallError> {
        match fs::symlink_metadata(self.fs.absolute(JOURNAL)) {
            Ok(_) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error.into()),
        }
    }
    fn save_journal(&self, journal: &InstallJournal) -> Result<(), InstallError> {
        let record = JournalRecord {
            digest: sha256(&bytes(journal)?),
            journal: journal.clone(),
        };
        self.fs.replace_metadata(JOURNAL, &bytes(&record)?)?;
        Ok(())
    }
    fn load_journal(&self, view: &OwnershipSnapshot) -> Result<InstallJournal, InstallError> {
        let record: JournalRecord = decode(&self.fs.read(JOURNAL)?)?;
        let journal = record.journal;
        if record.digest != sha256(&bytes(&journal)?)
            || journal.version != JOURNAL_VERSION
            || journal.project != self.policy.project
            || !view.projects.contains(&journal.project)
        {
            return Err(recovery("journal identity/version/project mismatch"));
        }
        for index in std::iter::once(&journal.old_index).chain(journal.after_index.iter()) {
            if index.version != RECEIPT_VERSION {
                return Err(recovery("unsupported journal receipt index"));
            }
            let mut claims = self.reserved.clone();
            for (owner, receipt) in &index.receipts {
                digest(owner)?;
                digest(receipt)?;
            }
            for (path, owner) in &index.paths {
                relative_path(path, true).map_err(recovery)?;
                if folded(path) != *path || !index.receipts.contains_key(owner) {
                    return Err(recovery("invalid journal receipt ownership"));
                }
                claim(&mut claims, path, owner).map_err(recovery)?;
            }
        }
        if journal.after_index.is_some() && !journal.ready {
            return Err(recovery("unready journal has committed receipts"));
        }
        let prefix = format!("{INSTALL_METADATA}/transactions/");
        let serial = journal
            .scope
            .strip_prefix(&prefix)
            .ok_or_else(|| recovery("foreign journal scope"))?;
        if serial.is_empty()
            || serial.contains('/')
            || !serial.bytes().all(|b| b.is_ascii_digit() || b == b'-')
        {
            return Err(recovery("invalid transaction scope"));
        }
        let mut claims = Claims::new();
        for (i, entry) in journal.entries.iter().enumerate() {
            self.output_path(&entry.destination)?;
            if conflict(&view.sources, &entry.destination).is_some() {
                return Err(recovery("journal destination is now source/code"));
            }
            claim(&mut claims, &entry.destination, "journal output").map_err(recovery)?;
            if let Some(old) = &entry.old_path {
                self.output_path(old)?;
                if folded(old) != folded(&entry.destination)
                    || conflict(&view.sources, old).is_some()
                {
                    return Err(recovery("journal old output is foreign or now source/code"));
                }
            }
            if entry.old.is_some() && entry.old_path.is_none()
                || entry.stage != format!("{}/new/{i}", journal.scope)
                || entry.trash != format!("{}/trash/{i}", journal.scope)
                || entry.staged.is_some() && entry.new.is_none()
                || journal.ready && entry.new.is_some() && entry.staged.is_none()
            {
                return Err(recovery("invalid journal entry"));
            }
            if let Some(file) = &entry.new {
                digest(&file.digest)?;
                if ![0o644, 0o755].contains(&file.mode) {
                    return Err(recovery("invalid staged mode"));
                }
                if let Some(staged) = &entry.staged {
                    if staged.size != file.size || staged.mode != file.mode {
                        return Err(recovery("invalid staged observation"));
                    }
                }
            }
        }
        for directory in &journal.directories {
            relative_path(&directory.path, true).map_err(recovery)?;
            let private = directory.path == journal.scope
                || directory.path.starts_with(&(journal.scope.clone() + "/"));
            let output_parent = journal
                .entries
                .iter()
                .any(|e| e.destination.starts_with(&(directory.path.clone() + "/")));
            if !private && !output_parent {
                return Err(recovery("foreign directory cleanup intent"));
            }
        }
        Ok(journal)
    }

    fn consistent_receipt(
        &self,
        index: &ReceiptIndex,
        owner: &OwnerId,
    ) -> Result<Option<(String, ItemReceipt)>, InstallError> {
        let key = owner.fingerprint()?;
        let Some(id) = index.receipts.get(&key) else {
            return Ok(None);
        };
        let receipt = self.receipt(id)?;
        if &receipt.owner != owner {
            return Err(recovery("receipt index owner mismatch"));
        }
        let recorded: BTreeSet<_> = receipt
            .files
            .iter()
            .map(|f| folded(&f.install_path))
            .collect();
        let indexed: BTreeSet<_> = index
            .paths
            .iter()
            .filter(|(_, v)| *v == &key)
            .map(|(p, _)| p.clone())
            .collect();
        if recorded != indexed {
            return Err(recovery("receipt/index file membership mismatch"));
        }
        Ok(Some((id.clone(), receipt)))
    }

    /// @cc [owner:fontanierh,label:correctness;safety] recover-owned-checkout-install
    /// Recovery MUST hold build and exclusive content custody. Before the receipt-index commit
    /// it MUST restore the prior owned bytes; after commit it MUST finish only exact owned cleanup.
    /// Unknown/replaced leaves and newly declared source paths MUST preserve the journal and refuse.
    /// No output-directory discovery, payload hashing, cache mutation or process launch is permitted.
    pub fn recover(
        &self,
        guard: &BuildGuard,
        view: &OwnershipSnapshot,
    ) -> Result<(), InstallError> {
        self.guard(guard)?;
        let _writer = guard.try_write_content()?;
        if !self.journal_present()? {
            return Ok(());
        }
        let journal = self.load_journal(view)?;
        let index = self.index()?;
        let committed = journal.after_index.as_ref() == Some(&index);
        if !committed && index != journal.old_index {
            return Err(recovery("receipt index changed outside journal"));
        }
        if !committed {
            self.rollback(&journal)?;
        }
        self.cleanup_journal(&journal, committed)
    }

    fn rollback(&self, journal: &InstallJournal) -> Result<(), InstallError> {
        // Reverse the exact leaf moves. File contents are never read or copied.
        for entry in journal.entries.iter().rev() {
            let destination = self.fs.observe(&entry.destination)?;
            if let Some(actual) = destination {
                if entry
                    .staged
                    .as_ref()
                    .is_some_and(|new| actual.same_payload(new))
                {
                    self.fs.remove_owned(&entry.destination, &actual)?;
                } else if !entry
                    .old
                    .as_ref()
                    .is_some_and(|old| actual.same_payload(old))
                {
                    return Err(recovery("rollback destination replaced by unknown file"));
                }
            }
            if let (Some(old), Some(path)) = (&entry.old, &entry.old_path) {
                if let Some(trash) = self.fs.observe(&entry.trash)? {
                    if !trash.same_payload(old) {
                        return Err(recovery("rollback trash was replaced"));
                    }
                    if self.fs.observe(path)?.is_some() {
                        return Err(recovery("rollback old name is occupied"));
                    }
                    self.fs.rename_exclusive(&entry.trash, path)?;
                } else if !self
                    .fs
                    .observe(path)?
                    .is_some_and(|actual| actual.same_payload(old))
                {
                    return Err(recovery("rollback prior bytes missing"));
                }
            }
        }
        Ok(())
    }

    fn cleanup_journal(
        &self,
        journal: &InstallJournal,
        committed: bool,
    ) -> Result<(), InstallError> {
        for entry in &journal.entries {
            for (path, expected) in [
                (&entry.stage, entry.staged.as_ref()),
                (&entry.trash, entry.old.as_ref()),
            ] {
                if let Some(actual) = self.fs.observe(path)? {
                    let expected = expected.ok_or_else(|| {
                        recovery("unrecorded staging leaf; preserve for investigation")
                    })?;
                    if !actual.same_payload(expected) {
                        return Err(recovery("cleanup leaf replaced"));
                    }
                    self.fs.remove_owned(path, expected)?;
                }
            }
            if committed {
                match (
                    &entry.new,
                    &entry.staged,
                    self.fs.observe(&entry.destination)?,
                ) {
                    (Some(_), Some(expected), Some(actual)) if actual.same_payload(expected) => {}
                    (None, _, None) => {}
                    _ => return Err(recovery("committed output disappeared or changed identity")),
                }
            }
        }
        for directory in journal.directories.iter().rev() {
            self.fs.remove_empty_directory(directory)?;
        }
        let observation = self
            .fs
            .observe(JOURNAL)?
            .ok_or_else(|| recovery("journal disappeared"))?;
        self.fs.remove_owned(JOURNAL, &observation)?;
        Ok(())
    }
}

impl RestorePlan {
    pub fn result(&self) -> &ResultEnvelope {
        &self.result
    }

    pub fn commit(
        &mut self,
        guard: &BuildGuard,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> Result<InstallOutcome, InstallError> {
        self.commit_with(guard, |_| Ok(()), root)
    }

    /// @cc [owner:fontanierh,label:correctness;safety] checkout-install-transaction
    /// Install MUST pin cache objects, acquire build/exclusive content custody and durably journal
    /// exact old/new leaf ownership before staging or mutation. It MUST clone named CAS objects,
    /// apply recorded normalized modes and publish complete per-project receipts before cleanup.
    /// Existing foreign files, other projects and declared code/sources MUST never be overwritten.
    /// Faults preserve recovery evidence and cache leases; successful later rooting releases claims.
    /// No fallback copy, payload rehash, tree walk or inferred prefix ownership is permitted.
    pub fn commit_with(
        &mut self,
        guard: &BuildGuard,
        mut event: impl FnMut(InstallEvent) -> io::Result<()>,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> Result<InstallOutcome, InstallError> {
        let installer = &self.installer;
        installer.guard(guard)?;
        if self.transaction.is_none() {
            return Err(invalid("restore plan already consumed"));
        }
        let _writer = guard.try_write_content()?;
        if installer.journal_present()? {
            return Err(recovery("prior journal requires recovery"));
        }
        if self.items.is_empty() && self.removals.is_empty() {
            return Ok(self.finish_root(root));
        }
        let before = installer.index()?;
        let (mut journal, affected) = self.plan_journal(before)?;
        installer.save_journal(&journal)?;
        event(InstallEvent::JournalCreated)?;
        for i in 0..journal.entries.len() {
            let entry = &mut journal.entries[i];
            if let Some(stored) = &entry.new {
                installer.objects.clone_to(
                    &ObjectDigest::from_hex(&stored.digest)?,
                    installer.fs.absolute(&entry.stage),
                )?;
                let file = installer.fs.file(&entry.stage)?;
                file.set_permissions(fs::Permissions::from_mode(stored.mode))?;
                file.sync_all()?;
                entry.staged = Some(FileObservation::from_metadata(&file.metadata()?));
                if entry.staged.as_ref().unwrap().size != stored.size {
                    return Err(recovery("staged object size changed"));
                }
                installer.save_journal(&journal)?;
                event(InstallEvent::FileStaged(i))?;
            }
        }
        journal.ready = true;
        installer.save_journal(&journal)?;
        event(InstallEvent::Ready)?;
        for i in 0..journal.entries.len() {
            let entry = journal.entries[i].clone();
            if let Some(path) = &entry.old_path {
                if let Some(expected) = &entry.old {
                    let actual = installer
                        .fs
                        .observe(path)?
                        .ok_or_else(|| recovery("old output disappeared"))?;
                    if actual != *expected {
                        return Err(recovery("old output changed after preflight"));
                    }
                    installer.fs.rename_exclusive(path, &entry.trash)?;
                    event(InstallEvent::OldMoved(i))?;
                }
            }
            if entry.new.is_some() {
                if let Some((parent, _)) = entry.destination.rsplit_once('/') {
                    journal
                        .directories
                        .extend(installer.fs.mkdirs(parent, 0o755)?);
                    installer.save_journal(&journal)?;
                }
                installer
                    .fs
                    .rename_exclusive(&entry.stage, &entry.destination)?;
                event(InstallEvent::NewMoved(i))?;
            }
        }
        let after = self.receipt_index(&journal, &affected)?;
        journal.after_index = Some(after.clone());
        installer.save_journal(&journal)?;
        event(InstallEvent::ReceiptsReady)?;
        installer.fs.replace_metadata(INDEX, &bytes(&after)?)?;
        event(InstallEvent::IndexCommitted)?;
        installer.cleanup_journal(&journal, true)?;
        event(InstallEvent::CleanupComplete)?;
        Ok(self.finish_root(root))
    }

    fn finish_root(
        &mut self,
        root: impl FnOnce(&ResultEnvelope) -> Result<(), String>,
    ) -> InstallOutcome {
        match self.transaction.take().unwrap().retain_hit(root) {
            Ok(_) => InstallOutcome::Installed,
            Err(error) => InstallOutcome::InstalledWithRootPending(error.to_string()),
        }
    }

    fn plan_journal(
        &self,
        before: ReceiptIndex,
    ) -> Result<(InstallJournal, BTreeSet<OwnerId>), InstallError> {
        let installer = &self.installer;
        let mut affected: BTreeSet<_> = self.items.keys().cloned().collect();
        let mut prior = BTreeMap::new();
        for removal in &self.removals {
            if !affected.insert(removal.owner.clone()) {
                return Err(invalid("duplicate removal or live replacement owner"));
            }
            let Some((id, receipt)) = installer.consistent_receipt(&before, &removal.owner)? else {
                return Err(invalid("removal has no owned receipt"));
            };
            if id != removal.expected_receipt_id
                || receipt
                    .files
                    .iter()
                    .map(|f| f.install_path.clone())
                    .collect::<BTreeSet<_>>()
                    != removal.exact_paths
            {
                return Err(invalid("stale or incomplete removal intent"));
            }
            prior.insert(removal.owner.clone(), receipt);
        }
        for owner in self.items.keys() {
            if let Some((_, receipt)) = installer.consistent_receipt(&before, owner)? {
                prior.insert(owner.clone(), receipt);
            }
        }
        let mut old_files = BTreeMap::new();
        for receipt in prior.values() {
            for file in &receipt.files {
                installer.output_path(&file.install_path)?;
                if conflict(&self.view.sources, &file.install_path).is_some() {
                    return Err(invalid("prior output became declared source/code"));
                }
                if let Some((_, current_owner)) = conflict(&self.view.paths, &file.install_path) {
                    let desired_owner = self
                        .desired
                        .get(&folded(&file.install_path))
                        .map(|desired| desired.owner.fingerprint())
                        .transpose()?;
                    if current_owner != &receipt.owner.fingerprint()?
                        && desired_owner.as_ref() != Some(current_owner)
                    {
                        return Err(invalid(
                            "prior output path is now assigned to another current owner",
                        ));
                    }
                }
                if old_files
                    .insert(folded(&file.install_path), file.clone())
                    .is_some()
                {
                    return Err(recovery("duplicate prior file"));
                }
            }
        }
        for (path, new) in &self.desired {
            if let Some(owner) = before.paths.get(path) {
                if !affected
                    .iter()
                    .any(|affected| affected.fingerprint().ok().as_ref() == Some(owner))
                {
                    return Err(invalid("output owned by another logical item/project"));
                }
            }
            if let Some((_, owner)) = conflict(&self.view.paths, &new.install_path) {
                if owner != &new.owner.fingerprint()? {
                    return Err(invalid(
                        "current declaration assigns output to another owner",
                    ));
                }
            }
        }
        let paths: BTreeSet<_> = old_files
            .keys()
            .chain(self.desired.keys())
            .cloned()
            .collect();
        let mut entries = vec![];
        for path in paths {
            let old_file = old_files.get(&path);
            let desired = self.desired.get(&path);
            let destination = desired
                .map(|f| f.install_path.clone())
                .unwrap_or_else(|| old_file.unwrap().install_path.clone());
            let old_path = old_file.map(|f| f.install_path.clone());
            let old = old_path
                .as_ref()
                .map(|p| installer.fs.observe(p))
                .transpose()?
                .flatten();
            if let Some(existing) = installer.fs.observe(&destination)? {
                if !old.as_ref().is_some_and(|old| old.same_inode(&existing)) {
                    return Err(invalid("unmanaged or foreign destination file"));
                }
            }
            entries.push(JournalEntry {
                old_path,
                old,
                destination,
                stage: String::new(),
                trash: String::new(),
                new: desired.map(|d| d.stored.clone()),
                staged: None,
            });
        }
        // Scope creation owns only a fresh private directory. No payload precedes the journal.
        let (scope, root_directory) = loop {
            let serial = NEXT.fetch_add(1, Ordering::Relaxed);
            let scope = format!(
                "{INSTALL_METADATA}/transactions/{}-{serial}",
                std::process::id()
            );
            match installer.fs.create_directory(&scope, 0o700) {
                Ok(directory) => break (scope, directory),
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error.into()),
            }
        };
        let mut directories = vec![root_directory];
        directories.extend(installer.fs.mkdirs(&format!("{scope}/new"), 0o700)?);
        directories.extend(installer.fs.mkdirs(&format!("{scope}/trash"), 0o700)?);
        for (i, entry) in entries.iter_mut().enumerate() {
            entry.stage = format!("{scope}/new/{i}");
            entry.trash = format!("{scope}/trash/{i}");
        }
        Ok((
            InstallJournal {
                version: JOURNAL_VERSION,
                project: installer.policy.project.clone(),
                scope,
                old_index: before,
                after_index: None,
                ready: false,
                entries,
                directories,
            },
            affected,
        ))
    }

    fn receipt_index(
        &self,
        journal: &InstallJournal,
        affected: &BTreeSet<OwnerId>,
    ) -> Result<ReceiptIndex, InstallError> {
        let installer = &self.installer;
        let mut after = journal.old_index.clone();
        let fingerprints: BTreeSet<_> = affected
            .iter()
            .map(OwnerId::fingerprint)
            .collect::<Result<_, _>>()?;
        after
            .receipts
            .retain(|owner, _| !fingerprints.contains(owner));
        after.paths.retain(|_, owner| !fingerprints.contains(owner));
        for (owner, item) in &self.items {
            let fingerprint = owner.fingerprint()?;
            let mut files = vec![];
            for desired in self.desired.values().filter(|file| &file.owner == owner) {
                let observation = installer
                    .fs
                    .observe(&desired.install_path)?
                    .ok_or_else(|| recovery("installed file missing before receipt publication"))?;
                let entry = journal
                    .entries
                    .iter()
                    .find(|e| e.destination == desired.install_path)
                    .unwrap();
                if !entry
                    .staged
                    .as_ref()
                    .is_some_and(|expected| expected.same_payload(&observation))
                    || observation.size != desired.stored.size
                    || observation.mode != desired.stored.mode
                {
                    return Err(recovery(
                        "installed file changed before receipt publication",
                    ));
                }
                files.push(ReceiptFile {
                    output_path: desired.output_path.clone(),
                    install_path: desired.install_path.clone(),
                    digest: desired.stored.digest.clone(),
                    size: desired.stored.size,
                    mode: desired.stored.mode,
                    observation,
                });
                if after
                    .paths
                    .insert(folded(&desired.install_path), fingerprint.clone())
                    .is_some()
                {
                    return Err(recovery("receipt path ownership collision"));
                }
            }
            let receipt = ItemReceipt {
                version: RECEIPT_VERSION,
                owner: owner.clone(),
                logical_path: item.logical_path.clone(),
                class: item.class.clone(),
                result_key: self.result.result.key.clone(),
                files,
            };
            let payload = bytes(&receipt)?;
            let id = sha256(&payload);
            let path = format!("{INSTALL_METADATA}/receipts/{id}.json");
            match installer.fs.publish_metadata(&path, &payload) {
                Ok(()) => {}
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    if installer.fs.read(&path)? != payload {
                        return Err(recovery("immutable receipt winner differs"));
                    }
                }
                Err(error) => return Err(error.into()),
            }
            after.receipts.insert(fingerprint, id);
        }
        Ok(after)
    }
}

fn decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, InstallError> {
    if bytes.iter().find(|byte| !byte.is_ascii_whitespace()) != Some(&b'{') {
        return Err(recovery("install metadata must be an object"));
    }
    serde_json::from_slice(bytes).map_err(|error| recovery(error.to_string()))
}
