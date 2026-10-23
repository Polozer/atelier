//! Durable retention roots and build sessions (B4). See DESIGN section 8.
//!
//! A root records which results a build used, as a map from the unit's scheduling label to
//! that unit's last result key. Each entry keeps the provenance of the session that wrote it.
//! Roots never participate in cache identity, and nothing here deletes payloads, result
//! records or leases; B5 owns traversal and object cleanup.
use crate::leases::{
    LEASE_VERSION, LeaseRecord, LeaseStore, Liveness, MetadataGuard, ProcessIdentity, sync_dir,
};
use crate::results::ResultEnvelope;
use crate::schema::{Declaration, Provenance};
use crate::store::ObjectDigest;
use crate::validate::ValidatedDeclaration;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

pub const ROOT_VERSION: u32 = 1;
pub const SESSION_VERSION: u32 = 1;
/// DESIGN section 8 keeps the three most recent releases.
pub const RELEASES_KEPT: usize = 3;
static NEXT: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RootKind {
    Main,
    Worktree { id: String },
    Release { sequence: u64, label: String },
    Pin { id: String },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootEntry {
    pub key: String,
    /// The session that last wrote this unit, never the latest session of the whole root.
    pub provenance: Provenance,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootRecord {
    pub version: u32,
    pub project: String,
    pub kind: RootKind,
    pub entries: BTreeMap<String, RootEntry>,
    /// Describes the session that last replaced or merged this root, not every entry.
    pub provenance: Provenance,
}

/// Every unit of one validated declaration. Only the full validation output can construct it, and
/// its dependency order must cover the declaration's units exactly, so a filtered or partial view
/// cannot ask a commit to prune results for units it never saw.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeclaredRoster {
    units: BTreeSet<String>,
    digest: String,
}

impl DeclaredRoster {
    pub fn from_validated(
        declaration: &Declaration,
        validated: &ValidatedDeclaration,
    ) -> Result<Self, RootError> {
        let declared: BTreeSet<String> = declaration
            .units
            .iter()
            .map(|unit| unit.id.clone())
            .collect();
        let ordered: BTreeSet<String> = validated.order.iter().cloned().collect();
        if declared.is_empty() || declared != ordered {
            return Err(invalid(
                "validated order must cover exactly the declaration's units",
            ));
        }
        let mut hasher = Sha256::new();
        for unit in &validated.order {
            hasher.update(unit.as_bytes());
            hasher.update([0u8]);
        }
        Ok(Self {
            units: declared,
            digest: format!("{:x}", hasher.finalize()),
        })
    }
    pub fn contains(&self, unit: &str) -> bool {
        self.units.contains(unit)
    }
    pub fn units(&self) -> &BTreeSet<String> {
        &self.units
    }
    /// Identity of the validated unit roster this commit pruned against.
    pub fn digest(&self) -> &str {
        &self.digest
    }
}

#[derive(Debug)]
pub enum RootError {
    Invalid(String),
    /// A root or session journal could not be read completely; callers must retain, never delete.
    Damaged(String),
    Conflict(String),
    Io(io::Error),
}
impl fmt::Display for RootError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(reason) => write!(formatter, "invalid root metadata: {reason}"),
            Self::Damaged(reason) => write!(formatter, "damaged root metadata: {reason}"),
            Self::Conflict(reason) => write!(formatter, "root conflict: {reason}"),
            Self::Io(error) => error.fmt(formatter),
        }
    }
}
impl std::error::Error for RootError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            _ => None,
        }
    }
}
impl From<io::Error> for RootError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

/// Result keys still referenced by any readable root or session, plus every record that could
/// not be read. A non-empty damage list means GC must retain, never delete.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RetentionView {
    pub keys: BTreeSet<String>,
    pub damaged: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SessionInfo {
    pub id: String,
    pub kind: RootKind,
    pub provenance: Provenance,
    pub owner: ProcessIdentity,
    pub entries: Vec<(String, String)>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommitStep {
    JournalRead,
    RootTemporary,
    RootReplaced,
    DirectorySynced,
    SessionRemoved,
}

#[derive(Clone, Debug)]
pub struct RootStore {
    root: PathBuf,
    project: String,
    leases: LeaseStore,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SessionHeader {
    version: u32,
    project: String,
    kind: RootKind,
    provenance: Provenance,
    owner: ProcessIdentity,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SessionEntry {
    unit: String,
    key: String,
}

/// One build's durable retention. Dropping it without commit or abandon keeps the journal, and
/// with it every key used so far, until an explicit release.
#[derive(Debug)]
pub struct BuildSession {
    store: RootStore,
    kind: RootKind,
    provenance: Provenance,
    id: String,
    journal: PathBuf,
}

fn invalid(message: impl Into<String>) -> RootError {
    RootError::Invalid(message.into())
}
fn damaged(message: impl Into<String>) -> RootError {
    RootError::Damaged(message.into())
}

fn valid_segment(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && !value.starts_with('.')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn valid_label(value: &str) -> bool {
    !value.is_empty() && value.len() <= 512 && !value.chars().any(char::is_control)
}

fn valid_key(value: &str) -> bool {
    ObjectDigest::from_hex(value).is_ok()
}

fn valid_kind(kind: &RootKind) -> bool {
    match kind {
        RootKind::Main => true,
        RootKind::Worktree { id } | RootKind::Pin { id } => valid_segment(id),
        RootKind::Release { label, .. } => valid_label(label),
    }
}

/// Identity inside one project: a release is its sequence, never its human label.
fn same_target(stored: &RootKind, requested: &RootKind) -> bool {
    match (stored, requested) {
        (RootKind::Main, RootKind::Main) => true,
        (RootKind::Worktree { id: left }, RootKind::Worktree { id: right }) => left == right,
        (
            RootKind::Release { sequence: left, .. },
            RootKind::Release {
                sequence: right, ..
            },
        ) => left == right,
        (RootKind::Pin { id: left }, RootKind::Pin { id: right }) => left == right,
        _ => false,
    }
}

fn checked(kind: &RootKind) -> Result<(), RootError> {
    if valid_kind(kind) {
        Ok(())
    } else {
        Err(invalid("invalid target name or label"))
    }
}

fn checked_entry(unit: &str, key: &str) -> Result<(), RootError> {
    if !valid_label(unit) {
        return Err(invalid(
            "unit label must be non-empty without control characters",
        ));
    }
    if !valid_key(key) {
        return Err(invalid(
            "result key must be 64 lowercase SHA-256 hex characters",
        ));
    }
    Ok(())
}

fn validate_record(record: &RootRecord, project: &str) -> Result<(), String> {
    if record.version != ROOT_VERSION || record.project != project {
        return Err("unsupported or foreign root record".into());
    }
    checked(&record.kind).map_err(|error| error.to_string())?;
    for (unit, entry) in &record.entries {
        checked_entry(unit, &entry.key).map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Frozen-root identity: the unit-to-key map, never the provenance of the retry.
fn entry_keys(entries: &BTreeMap<String, RootEntry>) -> BTreeMap<&str, &str> {
    entries
        .iter()
        .map(|(unit, entry)| (unit.as_str(), entry.key.as_str()))
        .collect()
}

fn sort_key(kind: &RootKind) -> (u8, String) {
    match kind {
        RootKind::Main => (0, String::new()),
        RootKind::Worktree { id } => (1, id.clone()),
        RootKind::Release { sequence, .. } => (2, format!("{sequence:020}")),
        RootKind::Pin { id } => (3, id.clone()),
    }
}

/// The target a record file must hold, derived from its location.
fn kind_at(path: &Path) -> Result<RootKind, RootError> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    let folder = path
        .parent()
        .and_then(|value| value.file_name())
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if name == "main.json" {
        return Ok(RootKind::Main);
    }
    let stem = name
        .strip_suffix(".json")
        .filter(|stem| !stem.is_empty())
        .ok_or_else(|| damaged(format!("{} is not a root record name", path.display())))?;
    match folder {
        "worktree" => Ok(RootKind::Worktree { id: stem.into() }),
        "pin" => Ok(RootKind::Pin { id: stem.into() }),
        "release" => {
            let sequence: u64 = stem
                .parse()
                .map_err(|_| damaged(format!("{} is not a release sequence", path.display())))?;
            if stem != sequence.to_string() {
                return Err(damaged(format!(
                    "{} is not a canonical release sequence",
                    path.display()
                )));
            }
            Ok(RootKind::Release {
                sequence,
                label: String::new(),
            })
        }
        _ => Err(damaged(format!(
            "{} is not in a root folder",
            path.display()
        ))),
    }
}

fn write_temp(directory: &Path, bytes: &[u8], suffix: &str) -> io::Result<PathBuf> {
    loop {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = directory.join(format!("{}-{serial}.{suffix}", std::process::id()));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&path) {
            Ok(mut file) => {
                file.write_all(bytes)?;
                file.sync_all()?;
                return Ok(path);
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
}

fn write_record(
    path: &Path,
    temporary_directory: &Path,
    record: &RootRecord,
    observe: &mut impl FnMut(CommitStep) -> io::Result<()>,
) -> Result<(), RootError> {
    let bytes = serde_json::to_vec(record).map_err(|error| invalid(error.to_string()))?;
    let temporary = write_temp(temporary_directory, &bytes, "tmp")?;
    if let Err(error) = observe(CommitStep::RootTemporary) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    if let Err(error) = fs::rename(&temporary, path) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    observe(CommitStep::RootReplaced)?;
    sync_dir(path.parent().expect("root record has a parent"))?;
    observe(CommitStep::DirectorySynced)?;
    Ok(())
}

fn parse_journal(
    path: &Path,
    project: &str,
    kind: Option<&RootKind>,
) -> Result<(SessionHeader, Vec<SessionEntry>), RootError> {
    let text = String::from_utf8(fs::read(path)?)
        .map_err(|error| damaged(format!("session is not UTF-8: {error}")))?;
    let mut parts: Vec<&str> = text.split('\n').collect();
    if parts.last() != Some(&"") {
        return Err(damaged("session journal has an unterminated last record"));
    }
    parts.pop();
    let Some(header) = parts.first() else {
        return Err(damaged("session journal is empty"));
    };
    let header: SessionHeader = serde_json::from_str(header)
        .map_err(|error| damaged(format!("session header: {error}")))?;
    if header.version != SESSION_VERSION || header.project != project {
        return Err(damaged("session header does not match this store"));
    }
    if let Some(kind) = kind {
        if !same_target(&header.kind, kind) {
            return Err(damaged("session header does not match its target"));
        }
    }
    let mut entries = vec![];
    for (index, line) in parts.iter().enumerate().skip(1) {
        if line.is_empty() {
            return Err(damaged(format!(
                "blank session record at line {}",
                index + 1
            )));
        }
        let entry: SessionEntry = serde_json::from_str(line)
            .map_err(|error| damaged(format!("session record {}: {error}", index + 1)))?;
        checked_entry(&entry.unit, &entry.key).map_err(|error| damaged(error.to_string()))?;
        entries.push(entry);
    }
    Ok((header, entries))
}

fn retention_of_session(path: &Path, keys: &mut BTreeSet<String>) -> bool {
    let Ok(bytes) = fs::read(path) else {
        return true;
    };
    let Ok(text) = String::from_utf8(bytes) else {
        return true;
    };
    let mut parts: Vec<&str> = text.split('\n').collect();
    let mut damaged = false;
    if parts.last() == Some(&"") {
        parts.pop();
    } else {
        damaged = true;
    }
    let header = parts.first().copied().unwrap_or_default();
    if serde_json::from_str::<SessionHeader>(header).is_err() {
        damaged = true;
    }
    for line in parts.iter().skip(1) {
        match serde_json::from_str::<SessionEntry>(line) {
            Ok(entry) if valid_key(&entry.key) => {
                keys.insert(entry.key);
            }
            _ => damaged = true,
        }
    }
    damaged
}

impl RootStore {
    /// @cc [owner:fontanierh,label:correctness] build-v2-root-store
    /// Opening MUST require an existing trusted store root, refuse a missing one, and name one
    /// explicit project. Initialization MUST run under the shared metadata mutex and MUST fsync
    /// every created ancestor before any publication can root a result. Reopening an initialized
    /// project MUST NOT recreate missing metadata: a vanished directory is damage. Readers MUST be
    /// callable with the caller's already-held guard so GC can read retention, leases and decide
    /// deletions under one lock hold. See tests/roots.rs `missing_store_root_is_refused`,
    /// `reopening_a_project_with_missing_metadata_is_damage`,
    /// `retention_is_readable_under_the_callers_guard` and
    /// `a_hit_release_is_visible_to_a_guarded_gc_read`.
    pub fn open(
        store_root: impl AsRef<Path>,
        project: impl Into<String>,
    ) -> Result<Self, RootError> {
        let project = project.into();
        if !valid_segment(&project) {
            return Err(invalid("project name must be a safe single path segment"));
        }
        let root = store_root.as_ref();
        if !root.is_dir() {
            return Err(invalid("store root does not exist"));
        }
        let root = root.canonicalize()?;
        if !fs::symlink_metadata(&root)?.is_dir() {
            return Err(invalid("store root is not a real directory"));
        }
        let leases = LeaseStore::open(&root)?;
        let store = Self {
            root,
            project,
            leases,
        };
        // Initialization and reopen observation share the metadata mutex with every reader.
        let _guard = store.leases.lock()?;
        let roots = store.root.join("roots");
        let base = store.project_dir();
        match fs::symlink_metadata(&base) {
            Ok(metadata) if metadata.is_dir() => {
                for kind in ["worktree", "release", "pin", "session", "tmp"] {
                    let path = base.join(kind);
                    match fs::symlink_metadata(&path) {
                        Ok(metadata) if metadata.is_dir() => {}
                        _ => {
                            return Err(damaged(format!(
                                "missing metadata directory {}",
                                path.display()
                            )));
                        }
                    }
                }
            }
            Ok(_) => return Err(invalid("project metadata is not a directory")),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                match fs::symlink_metadata(&roots) {
                    Ok(metadata) if metadata.is_dir() => {}
                    Ok(_) => return Err(invalid("roots metadata is not a directory")),
                    Err(error) if error.kind() == io::ErrorKind::NotFound => {
                        fs::create_dir(&roots)?;
                        sync_dir(&store.root)?;
                    }
                    Err(error) => return Err(error.into()),
                }
                fs::create_dir(&base)?;
                sync_dir(&roots)?;
                for kind in ["worktree", "release", "pin", "session", "tmp"] {
                    fs::create_dir(base.join(kind))?;
                }
                sync_dir(&base)?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(store)
    }

    pub fn project(&self) -> &str {
        &self.project
    }

    /// The same store-root mutex B2 and B5 must hold.
    pub fn leases(&self) -> &LeaseStore {
        &self.leases
    }

    fn project_dir(&self) -> PathBuf {
        self.root.join("roots").join(&self.project)
    }

    fn path(&self, kind: &RootKind) -> Result<PathBuf, RootError> {
        checked(kind)?;
        let base = self.project_dir();
        Ok(match kind {
            RootKind::Main => base.join("main.json"),
            RootKind::Worktree { id } => base.join("worktree").join(format!("{id}.json")),
            RootKind::Release { sequence, .. } => {
                base.join("release").join(format!("{sequence}.json"))
            }
            RootKind::Pin { id } => base.join("pin").join(format!("{id}.json")),
        })
    }

    fn root_locked(
        &self,
        _guard: &MetadataGuard,
        kind: &RootKind,
    ) -> Result<Option<RootRecord>, RootError> {
        let path = self.path(kind)?;
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => {
                return Err(damaged(format!(
                    "{} could not be inspected: {error}",
                    path.display()
                )));
            }
        };
        if !metadata.is_file() {
            return Err(damaged(format!("{} is not a regular file", path.display())));
        }
        let bytes = fs::read(&path)?;
        let record: RootRecord = serde_json::from_slice(&bytes)
            .map_err(|error| damaged(format!("{}: {error}", path.display())))?;
        validate_record(&record, &self.project).map_err(damaged)?;
        if !same_target(&record.kind, kind) {
            return Err(damaged("root record kind differs from its location"));
        }
        Ok(Some(record))
    }

    pub fn root(&self, kind: &RootKind) -> Result<Option<RootRecord>, RootError> {
        let guard = self.leases.lock()?;
        self.root_locked(&guard, kind)
    }

    pub fn roots(&self) -> Result<Vec<RootRecord>, RootError> {
        let guard = self.leases.lock()?;
        self.roots_locked(&guard)
    }

    pub fn roots_locked(&self, _guard: &MetadataGuard) -> Result<Vec<RootRecord>, RootError> {
        self.check_guard(_guard)?;
        let mut records = vec![];
        let base = self.project_dir();
        let mut paths = vec![base.join("main.json")];
        for folder in ["worktree", "release", "pin"] {
            for entry in fs::read_dir(base.join(folder))? {
                let entry = entry?;
                if !entry.file_type()?.is_file() {
                    return Err(damaged(format!(
                        "unexpected root entry {}",
                        entry.path().display()
                    )));
                }
                paths.push(entry.path());
            }
        }
        for path in paths {
            match fs::symlink_metadata(&path) {
                Ok(_) => {}
                Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
                Err(error) => {
                    return Err(damaged(format!(
                        "{} could not be inspected: {error}",
                        path.display()
                    )));
                }
            }
            let bytes = fs::read(&path)?;
            let record: RootRecord = serde_json::from_slice(&bytes)
                .map_err(|error| damaged(format!("{}: {error}", path.display())))?;
            validate_record(&record, &self.project).map_err(damaged)?;
            if !same_target(&record.kind, &kind_at(&path)?) {
                return Err(damaged(format!(
                    "{} holds a record for another target",
                    path.display()
                )));
            }
            records.push(record);
        }
        records.sort_by(|left, right| sort_key(&left.kind).cmp(&sort_key(&right.kind)));
        Ok(records)
    }

    pub fn begin_session(
        &self,
        kind: RootKind,
        provenance: Provenance,
        owner: ProcessIdentity,
    ) -> Result<BuildSession, RootError> {
        checked(&kind)?;
        if owner.pid == 0 || owner.boot.is_empty() || owner.started.is_empty() {
            return Err(invalid("complete session owner identity is required"));
        }
        let _guard = self.leases.lock()?;
        let base = self.project_dir();
        let session_directory = base.join("session");
        let temporary_directory = base.join("tmp");
        loop {
            let serial = NEXT.fetch_add(1, Ordering::Relaxed);
            let id = format!("{}-{serial}", std::process::id());
            let journal = session_directory.join(format!("{id}.jsonl"));
            if fs::symlink_metadata(&journal).is_ok() {
                continue;
            }
            let header = SessionHeader {
                version: SESSION_VERSION,
                project: self.project.clone(),
                kind: kind.clone(),
                provenance: provenance.clone(),
                owner: owner.clone(),
            };
            let bytes = serde_json::to_vec(&header).map_err(|error| invalid(error.to_string()))?;
            let mut line = bytes;
            line.push(b'\n');
            let temporary = write_temp(&temporary_directory, &line, "jsonl")?;
            match fs::rename(&temporary, &journal) {
                Ok(()) => {}
                Err(error) => {
                    let _ = fs::remove_file(&temporary);
                    if error.kind() == io::ErrorKind::AlreadyExists {
                        continue;
                    }
                    return Err(error.into());
                }
            }
            sync_dir(&session_directory)?;
            return Ok(BuildSession {
                store: self.clone(),
                kind,
                provenance,
                id,
                journal,
            });
        }
    }

    /// Enumerate session headers under the metadata lock. A damaged journal fails closed.
    pub fn sessions(&self) -> Result<Vec<SessionInfo>, RootError> {
        let _guard = self.leases.lock()?;
        self.sessions_locked()
    }

    fn sessions_locked(&self) -> Result<Vec<SessionInfo>, RootError> {
        let mut sessions = vec![];
        for entry in fs::read_dir(self.project_dir().join("session"))? {
            let entry = entry?;
            let path = entry.path();
            if !entry.file_type()?.is_file()
                || path.extension().is_none_or(|value| value != "jsonl")
            {
                return Err(damaged(format!(
                    "unexpected session entry {}",
                    path.display()
                )));
            }
            let (header, entries) = parse_journal(&path, &self.project, None)?;
            sessions.push(SessionInfo {
                id: path
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
                    .to_string(),
                kind: header.kind,
                provenance: header.provenance,
                owner: header.owner,
                entries: entries
                    .into_iter()
                    .map(|entry| (entry.unit, entry.key))
                    .collect(),
            });
        }
        sessions.sort_by(|left, right| left.id.cmp(&right.id));
        Ok(sessions)
    }

    /// @cc [owner:fontanierh,label:correctness] gc-retains-until-session-cleanup-confirmed
    /// A lease or session MUST be reclaimable only when every owner and worker identity is
    /// positively dead and every registered session custodian's guard cleanup is durably
    /// confirmed. A dead custodian whose cleanup is unconfirmed or unreadable MUST count as
    /// unknown liveness and retain it; a dead monitor process alone MUST NOT prove cleanup.
    /// Unreadable correlation records and unknown liveness always retain, and a correlation answer
    /// of Ok(None) MUST mean authoritatively not a custodian: missing, unreadable or ambiguous
    /// evidence MUST be an error that retains, and no fallback adapter may guess "ordinary".
    /// See tests/roots.rs
    /// `a_dead_custodian_with_unconfirmed_cleanup_is_retained`,
    /// `an_owner_custodian_with_unconfirmed_cleanup_is_retained`,
    /// `a_dead_custodian_with_confirmed_cleanup_is_reclaimable`,
    /// `an_unreadable_custodian_or_cleanup_record_is_retained` and
    /// `alive_or_unknown_identities_still_retain_the_lease`.
    pub fn release_dead_session(
        &self,
        id: &str,
        probe: impl FnMut(&ProcessIdentity) -> Liveness,
        custodians: &impl SessionCustodians,
        cleanup: &impl CustodianCleanup,
    ) -> Result<Reclaim, RootError> {
        if !valid_segment(id) {
            return Err(invalid("invalid session id"));
        }
        let _guard = self.leases.lock()?;
        let path = self
            .project_dir()
            .join("session")
            .join(format!("{id}.jsonl"));
        let (header, _) = parse_journal(&path, &self.project, None)?;
        let lease = LeaseRecord {
            version: LEASE_VERSION,
            id: format!("session-{id}"),
            staging: format!("staging/session-{id}"),
            owner: header.owner,
            workers: vec![],
            result_keys: BTreeSet::new(),
            object_digests: BTreeSet::new(),
            rooted: false,
        };
        let verdict = may_reclaim(&lease, probe, custodians, cleanup);
        if verdict == Reclaim::Reclaimable {
            fs::remove_file(&path)?;
            sync_dir(path.parent().expect("journal has a parent"))?;
        }
        Ok(verdict)
    }

    pub fn drop_root(&self, kind: &RootKind) -> Result<Option<RootRecord>, RootError> {
        let guard = self.leases.lock()?;
        let record = self.root_locked(&guard, kind)?;
        if record.is_some() {
            let path = self.path(kind)?;
            fs::remove_file(&path)?;
            sync_dir(path.parent().expect("root has a parent"))?;
        }
        Ok(record)
    }

    /// @cc [owner:fontanierh,label:correctness] build-v2-frozen-roots
    /// Release and pin roots MUST be frozen snapshots written whole, never merged. A release is
    /// identified by an explicit sequence; an existing sequence with different entries is a
    /// conflict and MUST NOT be replaced, and only the three greatest sequences survive. A
    /// snapshot target MUST be a release or pin. See tests/roots.rs
    /// `a_release_is_a_frozen_snapshot_and_never_merges`,
    /// `releases_keep_the_three_greatest_sequences_and_refuse_a_different_duplicate`,
    /// `a_sequence_below_the_retained_window_is_refused`,
    /// `an_identical_release_retry_keeps_the_first_record` and
    /// `a_root_can_be_snapshotted_into_a_pin_but_not_into_a_mutable_root`.
    pub fn snapshot(
        &self,
        source: &RootKind,
        target: RootKind,
        provenance: Provenance,
    ) -> Result<RootRecord, RootError> {
        checked(&target)?;
        match &target {
            RootKind::Main | RootKind::Worktree { .. } => {
                return Err(invalid("a snapshot target must be a release or a pin"));
            }
            _ => {}
        }
        let guard = self.leases.lock()?;
        self.sweep_tmp_locked(&guard)?;
        let source_record = self
            .root_locked(&guard, source)?
            .ok_or_else(|| invalid("source root is missing"))?;
        let record = RootRecord {
            version: ROOT_VERSION,
            project: self.project.clone(),
            kind: target.clone(),
            entries: source_record.entries,
            provenance,
        };
        if let Some(existing) = self.root_locked(&guard, &target)? {
            if entry_keys(&existing.entries) != entry_keys(&record.entries) {
                return Err(RootError::Conflict(
                    "snapshot target already exists with different entries".into(),
                ));
            }
        } else {
            self.check_release_window_locked(&target)?;
            let path = self.path(&target)?;
            write_record(&path, &self.project_dir().join("tmp"), &record, &mut |_| {
                Ok(())
            })?;
        }
        if matches!(&target, RootKind::Release { .. }) {
            self.trim_releases_locked()?;
        }
        Ok(record)
    }

    pub fn retention(&self) -> Result<RetentionView, RootError> {
        let guard = self.leases.lock()?;
        self.retention_locked(&guard)
    }

    /// @cc [owner:fontanierh,label:correctness] build-v2-root-retention-read
    /// Retention MUST count every key named by a readable root or session and report every record
    /// it cannot read instead of guessing; a non-empty damage list obliges GC to retain. A missing
    /// metadata directory is damage, not an empty view. This reader MUST be callable under a
    /// caller-held guard so GC reads retention, leases and deletes under one lock hold. See
    /// tests/roots.rs `retention_counts_root_and_open_session_keys`,
    /// `retention_is_readable_under_the_callers_guard`,
    /// `malformed_root_metadata_fails_reads_and_retention_reports_damage` and
    /// `missing_or_unreadable_metadata_is_damage`, including the selected project's own directory
    /// (`retention_reports_a_missing_selected_project`). A wrong-store guard never certifies a
    /// GC snapshot: `retention_locked` and `roots_locked` MUST refuse it,
    /// see `a_guard_from_another_store_is_refused`.
    pub fn retention_locked(&self, _guard: &MetadataGuard) -> Result<RetentionView, RootError> {
        self.check_guard(_guard)?;
        let mut view = RetentionView::default();
        let roots = self.root.join("roots");
        match fs::symlink_metadata(&roots) {
            Ok(_) => {}
            Err(_) => {
                view.damaged.push(roots.display().to_string());
                return Ok(view);
            }
        }
        let selected = self.project_dir();
        match fs::symlink_metadata(&selected) {
            Ok(metadata) if metadata.is_dir() => {}
            _ => view.damaged.push(selected.display().to_string()),
        }
        for project in fs::read_dir(&roots)? {
            let project = match project {
                Ok(project) => project,
                Err(error) => {
                    view.damaged
                        .push(format!("unreadable project entry: {error}"));
                    continue;
                }
            };
            let directory = match project.file_type() {
                Ok(file_type) => file_type.is_dir(),
                Err(_) => {
                    view.damaged.push(project.path().display().to_string());
                    continue;
                }
            };
            if !directory {
                view.damaged.push(project.path().display().to_string());
                continue;
            }
            let project_name = project.file_name().to_string_lossy().to_string();
            let base = project.path();
            for (folder, extension) in [
                ("worktree", "json"),
                ("release", "json"),
                ("pin", "json"),
                ("session", "jsonl"),
            ] {
                let Ok(entries) = fs::read_dir(base.join(folder)) else {
                    view.damaged.push(base.join(folder).display().to_string());
                    continue;
                };
                for entry in entries {
                    let entry = entry?;
                    let path = entry.path();
                    if !entry.file_type()?.is_file()
                        || path.extension().is_none_or(|value| value != extension)
                    {
                        view.damaged.push(path.display().to_string());
                        continue;
                    }
                    if folder == "session" {
                        if retention_of_session(&path, &mut view.keys) {
                            view.damaged.push(path.display().to_string());
                        }
                        continue;
                    }
                    match fs::read(&path)
                        .map_err(|error| error.to_string())
                        .and_then(|bytes| {
                            serde_json::from_slice::<RootRecord>(&bytes).map_err(|e| e.to_string())
                        }) {
                        Ok(record)
                            if record.version == ROOT_VERSION && record.project == project_name =>
                        {
                            let mut invalid = false;
                            for entry in record.entries.values() {
                                if valid_key(&entry.key) {
                                    view.keys.insert(entry.key.clone());
                                } else {
                                    invalid = true;
                                }
                            }
                            if invalid {
                                view.damaged.push(path.display().to_string());
                            }
                        }
                        _ => view.damaged.push(path.display().to_string()),
                    }
                }
            }
            let main = base.join("main.json");
            match fs::symlink_metadata(&main) {
                Ok(_) => {
                    match fs::read(&main)
                        .map_err(|error| error.to_string())
                        .and_then(|bytes| {
                            serde_json::from_slice::<RootRecord>(&bytes).map_err(|e| e.to_string())
                        }) {
                        Ok(record)
                            if record.version == ROOT_VERSION && record.project == project_name =>
                        {
                            let mut invalid = false;
                            for entry in record.entries.values() {
                                if valid_key(&entry.key) {
                                    view.keys.insert(entry.key.clone());
                                } else {
                                    invalid = true;
                                }
                            }
                            if invalid {
                                view.damaged.push(main.display().to_string());
                            }
                        }
                        _ => view.damaged.push(main.display().to_string()),
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(_) => view.damaged.push(main.display().to_string()),
            }
            match fs::read_dir(&base) {
                Ok(entries) => {
                    for entry in entries {
                        let Ok(entry) = entry else {
                            view.damaged.push(base.display().to_string());
                            continue;
                        };
                        let name = entry.file_name();
                        let name = name.to_string_lossy();
                        if !["worktree", "release", "pin", "session", "tmp", "main.json"]
                            .contains(&name.as_ref())
                        {
                            view.damaged.push(entry.path().display().to_string());
                        }
                    }
                }
                Err(_) => view.damaged.push(base.display().to_string()),
            }
        }
        Ok(view)
    }

    fn trim_releases_locked(&self) -> Result<Vec<u64>, RootError> {
        let folder = self.project_dir().join("release");
        let mut sequences = vec![];
        for entry in fs::read_dir(&folder)? {
            let entry = entry?;
            if !entry.file_type()?.is_file() {
                continue;
            }
            let name = entry.file_name();
            let name = name.to_string_lossy();
            let Some(stem) = name.strip_suffix(".json") else {
                continue;
            };
            let sequence: u64 = stem.parse().map_err(|_| {
                damaged(format!(
                    "{} is not a release sequence",
                    entry.path().display()
                ))
            })?;
            if stem != sequence.to_string() {
                return Err(damaged(format!(
                    "{} is not a canonical release sequence",
                    entry.path().display()
                )));
            }
            sequences.push(sequence);
        }
        sequences.sort_unstable();
        let mut removed = vec![];
        while sequences.len() > RELEASES_KEPT {
            let oldest = sequences.remove(0);
            fs::remove_file(folder.join(format!("{oldest}.json")))?;
            removed.push(oldest);
        }
        if !removed.is_empty() {
            sync_dir(&folder)?;
        }
        Ok(removed)
    }

    pub fn trim_releases(&self) -> Result<Vec<u64>, RootError> {
        let _guard = self.leases.lock()?;
        self.trim_releases_locked()
    }

    fn check_release_window_locked(&self, kind: &RootKind) -> Result<(), RootError> {
        let RootKind::Release { sequence, .. } = kind else {
            return Ok(());
        };
        let mut sequences = vec![];
        for entry in fs::read_dir(self.project_dir().join("release"))? {
            let entry = entry?;
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if let Some(stem) = name.strip_suffix(".json") {
                if let Ok(value) = stem.parse::<u64>() {
                    sequences.push(value);
                }
            }
        }
        sequences.sort_unstable();
        if sequences.len() >= RELEASES_KEPT && *sequence < sequences[0] {
            return Err(RootError::Conflict(
                "release sequence is outside the retained window".into(),
            ));
        }
        Ok(())
    }

    fn sweep_tmp_locked(&self, _guard: &MetadataGuard) -> Result<(), RootError> {
        let folder = self.project_dir().join("tmp");
        for entry in fs::read_dir(&folder)? {
            let entry = entry?;
            fs::remove_file(entry.path())?;
        }
        sync_dir(&folder)?;
        Ok(())
    }

    /// A guard only certifies metadata of the store whose mutex it holds.
    fn check_guard(&self, guard: &MetadataGuard) -> Result<(), RootError> {
        if guard.store_root() != self.root {
            return Err(invalid("guard belongs to another store"));
        }
        Ok(())
    }
}

impl BuildSession {
    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn target(&self) -> &RootKind {
        &self.kind
    }

    /// @cc [owner:fontanierh,label:correctness] build-v2-session-journal
    /// Every used key MUST be appended and fsynced before a publication callback returns Ok, so a
    /// result is retained before B2 clears its claims. A failed append MUST NOT leave a torn tail.
    /// A damaged or unterminated record MUST fail the commit, leave the previous root and the
    /// journal untouched, and be reported, and a commit MUST remove only its own journal.
    /// See tests/roots.rs `a_torn_journal_tail_fails_the_commit_and_preserves_root_and_journal`,
    /// `a_corrupt_middle_record_fails_closed_and_retention_counts_parseable_keys`,
    /// `a_commit_removes_only_its_own_session_journal`,
    /// `the_session_journal_keeps_every_key_and_the_root_takes_the_last_per_unit`,
    /// `b2_publication_and_hit_callbacks_record_the_caller_unit_binding` and
    /// `a_failed_append_leaves_the_journal_unchanged`.
    pub fn use_result(&mut self, unit: &str, key: &str) -> Result<(), RootError> {
        checked_entry(unit, key)?;
        let _guard = self.store.leases.lock()?;
        let line = serde_json::to_vec(&SessionEntry {
            unit: unit.to_string(),
            key: key.to_string(),
        })
        .map_err(|error| invalid(error.to_string()))?;
        let mut file = OpenOptions::new().append(true).open(&self.journal)?;
        let before = file.metadata()?.len();
        let appended = (|| -> io::Result<()> {
            file.write_all(&line)?;
            file.write_all(b"\n")?;
            file.sync_all()
        })();
        if let Err(error) = appended {
            let _ = file.set_len(before);
            let _ = file.sync_all();
            return Err(error.into());
        }
        Ok(())
    }

    /// The exact callback B2's publish and retain_hit accept. The caller names the unit; the
    /// winning envelope's own unit is diagnostic and may belong to an earlier equivalent producer.
    pub fn root_callback<'a>(
        &'a mut self,
        unit: &str,
    ) -> impl FnOnce(&ResultEnvelope) -> Result<(), String> + 'a {
        let unit = unit.to_string();
        move |envelope| {
            self.use_result(&unit, &envelope.result.key)
                .map_err(|error| error.to_string())
        }
    }

    pub fn commit(self, declared: Option<&DeclaredRoster>) -> Result<RootRecord, RootError> {
        self.commit_observed(declared, |_| Ok(()))
    }

    /// Commit folds the journal into the root. A main or worktree root merges with the current
    /// root inside one lock hold; a release or pin writes its frozen snapshot whole.
    pub fn commit_observed(
        self,
        declared: Option<&DeclaredRoster>,
        mut observe: impl FnMut(CommitStep) -> io::Result<()>,
    ) -> Result<RootRecord, RootError> {
        let guard = self.store.leases.lock()?;
        observe(CommitStep::JournalRead)?;
        self.store.sweep_tmp_locked(&guard)?;
        let entries = parse_journal(&self.journal, &self.store.project, Some(&self.kind))?.1;
        let mut latest: BTreeMap<String, String> = BTreeMap::new();
        for entry in entries {
            latest.insert(entry.unit, entry.key);
        }
        let merged = match self.kind {
            RootKind::Main | RootKind::Worktree { .. } => {
                let mut current = self
                    .store
                    .root_locked(&guard, &self.kind)?
                    .map(|record| record.entries)
                    .unwrap_or_default();
                for (unit, key) in latest {
                    current.insert(
                        unit,
                        RootEntry {
                            key,
                            provenance: self.provenance.clone(),
                        },
                    );
                }
                if let Some(roster) = declared {
                    current.retain(|unit, _| roster.contains(unit));
                }
                current
            }
            RootKind::Release { .. } | RootKind::Pin { .. } => latest
                .into_iter()
                .map(|(unit, key)| {
                    (
                        unit,
                        RootEntry {
                            key,
                            provenance: self.provenance.clone(),
                        },
                    )
                })
                .collect(),
        };
        let record = RootRecord {
            version: ROOT_VERSION,
            project: self.store.project.clone(),
            kind: self.kind.clone(),
            entries: merged,
            provenance: self.provenance.clone(),
        };
        validate_record(&record, &self.store.project).map_err(damaged)?;
        let existing = self.store.root_locked(&guard, &self.kind)?;
        let frozen = matches!(&self.kind, RootKind::Release { .. } | RootKind::Pin { .. });
        if frozen {
            if let Some(existing) = &existing {
                if entry_keys(&existing.entries) != entry_keys(&record.entries) {
                    return Err(RootError::Conflict(
                        "frozen root already exists with different entries".into(),
                    ));
                }
            }
        }
        let write = match &existing {
            None => true,
            Some(existing) if frozen => false,
            Some(existing) => existing != &record,
        };
        if write {
            self.store.check_release_window_locked(&self.kind)?;
            let path = self.store.path(&self.kind)?;
            write_record(
                &path,
                &self.store.project_dir().join("tmp"),
                &record,
                &mut observe,
            )?;
        }
        if matches!(&self.kind, RootKind::Release { .. }) {
            self.store.trim_releases_locked()?;
        }
        fs::remove_file(&self.journal)?;
        sync_dir(self.journal.parent().expect("journal has a parent"))?;
        observe(CommitStep::SessionRemoved)?;
        Ok(record)
    }

    /// Release this session's retention without touching any root. Only this journal is removed.
    pub fn abandon(self) -> Result<(), RootError> {
        let _guard = self.store.leases.lock()?;
        fs::remove_file(&self.journal)?;
        sync_dir(self.journal.parent().expect("journal has a parent"))?;
        Ok(())
    }
}

/// C5c's durable custodian registry: which identity is a session custodian, if any.
pub trait SessionCustodians {
    /// Ok(None) MUST mean authoritatively not a custodian. Missing, unreadable or ambiguous
    /// evidence MUST be Err, which retains the lease; never return Ok(None) for missing evidence.
    fn correlation(&self, identity: &ProcessIdentity) -> Result<Option<String>, String>;
}

/// C5c's durable guard-cleanup confirmation for one custodian correlation.
pub trait CustodianCleanup {
    fn cleanup_confirmed(&self, correlation: &str) -> Result<bool, String>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Reclaim {
    Reclaimable,
    Retained(RetainReason),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RetainReason {
    IdentityNotConfirmedDead,
    /// A dead session custodian whose guard cleanup is not yet durably confirmed.
    CleanupUnconfirmed(String),
    CustodianRecordUnreadable(String),
}

/// The only public reclaim decision. LeaseRecord::identities_all_dead states the base identity
/// rule; this adds the custodian cleanup rule for the owner and every registered worker.
pub fn may_reclaim(
    lease: &LeaseRecord,
    mut probe: impl FnMut(&ProcessIdentity) -> Liveness,
    custodians: &impl SessionCustodians,
    cleanup: &impl CustodianCleanup,
) -> Reclaim {
    if !lease.identities_all_dead(&mut probe) {
        return Reclaim::Retained(RetainReason::IdentityNotConfirmedDead);
    }
    for identity in std::iter::once(&lease.owner).chain(lease.workers.iter()) {
        match custodians.correlation(identity) {
            Ok(None) => {}
            Ok(Some(correlation)) => match cleanup.cleanup_confirmed(&correlation) {
                Ok(true) => {}
                Ok(false) => {
                    return Reclaim::Retained(RetainReason::CleanupUnconfirmed(correlation));
                }
                Err(message) => {
                    return Reclaim::Retained(RetainReason::CustodianRecordUnreadable(message));
                }
            },
            Err(message) => {
                return Reclaim::Retained(RetainReason::CustodianRecordUnreadable(message));
            }
        }
    }
    Reclaim::Reclaimable
}
