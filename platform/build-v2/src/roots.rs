//! Durable retention roots and build sessions (B4). See DESIGN section 8.
//!
//! A root records which results a build used, as a map from the unit's scheduling label to
//! that unit's last result key. Each entry keeps the provenance of the session that wrote it.
//! Roots never participate in cache identity, and nothing here deletes payloads, result
//! records or leases; B5 owns traversal and object cleanup.
use crate::leases::{LeaseRecord, LeaseStore, Liveness, ProcessIdentity, directory, sync_dir};
use crate::results::ResultEnvelope;
use crate::schema::{Declaration, Provenance};
use crate::store::ObjectDigest;
use serde::{Deserialize, Serialize};
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

/// Every unit of one complete declaration. Only a full-declaration caller can build it, so a
/// partial build cannot ask a commit to prune results for units it never saw.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeclaredRoster {
    units: BTreeSet<String>,
}

impl DeclaredRoster {
    pub fn from_declaration(declaration: &Declaration) -> Self {
        Self {
            units: declaration
                .units
                .iter()
                .map(|unit| unit.id.clone())
                .collect(),
        }
    }
    pub fn contains(&self, unit: &str) -> bool {
        self.units.contains(unit)
    }
    pub fn units(&self) -> &BTreeSet<String> {
        &self.units
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
        (RootKind::Release { sequence: left, .. }, RootKind::Release { sequence: right, .. }) => {
            left == right
        }
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
        return Err(invalid("unit label must be non-empty without control characters"));
    }
    if !valid_key(key) {
        return Err(invalid("result key must be 64 lowercase SHA-256 hex characters"));
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

fn write_record(
    path: &Path,
    record: &RootRecord,
    observe: &mut impl FnMut(CommitStep) -> io::Result<()>,
) -> Result<(), RootError> {
    let serial = NEXT.fetch_add(1, Ordering::Relaxed);
    let temporary = path.with_extension(format!("{}-{serial}.tmp", std::process::id()));
    let bytes = serde_json::to_vec(record).map_err(|error| invalid(error.to_string()))?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temporary)?;
    let prepared = (|| -> Result<(), RootError> {
        file.write_all(&bytes)?;
        file.sync_all()?;
        Ok(())
    })();
    drop(file);
    if let Err(error) = prepared {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
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

fn read_journal(path: &Path, project: &str, kind: &RootKind) -> Result<Vec<SessionEntry>, RootError> {
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
    if header.version != SESSION_VERSION || header.project != project || &header.kind != kind {
        return Err(damaged("session header does not match this store or target"));
    }
    let mut entries = vec![];
    for (index, line) in parts.iter().enumerate().skip(1) {
        if line.is_empty() {
            return Err(damaged(format!("blank session record at line {}", index + 1)));
        }
        let entry: SessionEntry = serde_json::from_str(line)
            .map_err(|error| damaged(format!("session record {}: {error}", index + 1)))?;
        checked_entry(&entry.unit, &entry.key).map_err(|error| damaged(error.to_string()))?;
        entries.push(entry);
    }
    Ok(entries)
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
    /// Roots MUST live under an explicit project namespace in the trusted canonical store and
    /// MUST use the store-root `metadata.lock` inode as their only mutation mutex. Opening MUST
    /// refuse a missing store root and invalid project names. See tests/roots.rs.
    pub fn open(store_root: impl AsRef<Path>, project: impl Into<String>) -> Result<Self, RootError> {
        let project = project.into();
        if !valid_segment(&project) {
            return Err(invalid("project name must be a safe single path segment"));
        }
        let root = store_root.as_ref();
        fs::create_dir_all(root)?;
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
        let base = store.project_dir();
        fs::create_dir_all(store.root.join("roots"))?;
        directory(&base)?;
        for kind in ["worktree", "release", "pin", "session"] {
            directory(&base.join(kind))?;
        }
        sync_dir(&base)?;
        Ok(store)
    }

    pub fn project(&self) -> &str {
        &self.project
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
            RootKind::Release { sequence, .. } => base.join("release").join(format!("{sequence}.json")),
            RootKind::Pin { id } => base.join("pin").join(format!("{id}.json")),
        })
    }

    fn read_root_locked(&self, kind: &RootKind) -> Result<Option<RootRecord>, RootError> {
        let path = self.path(kind)?;
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
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
        let _guard = self.leases.lock()?;
        self.read_root_locked(kind)
    }

    /// @cc [owner:fontanierh,label:correctness] build-v2-release-retention
    /// A release commit MUST durably publish its frozen snapshot before trimming, MUST refuse a
    /// different record for an existing sequence without replacing it, and MUST keep the three
    /// greatest sequences. Trimming deletes root records only. See tests/roots.rs.
    pub fn roots(&self) -> Result<Vec<RootRecord>, RootError> {
        let _guard = self.leases.lock()?;
        let mut records = vec![];
        let base = self.project_dir();
        let mut paths = vec![base.join("main.json")];
        for folder in ["worktree", "release", "pin"] {
            for entry in fs::read_dir(base.join(folder))? {
                let entry = entry?;
                if !entry.file_type()?.is_file() {
                    return Err(damaged(format!("unexpected root entry {}", entry.path().display())));
                }
                paths.push(entry.path());
            }
        }
        for path in paths {
            if fs::symlink_metadata(&path).is_err() {
                continue;
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
    ) -> Result<BuildSession, RootError> {
        checked(&kind)?;
        let _guard = self.leases.lock()?;
        let directory = self.project_dir().join("session");
        loop {
            let serial = NEXT.fetch_add(1, Ordering::Relaxed);
            let id = format!("{}-{serial}", std::process::id());
            let path = directory.join(format!("{id}.jsonl"));
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(mut file) => {
                    let header = SessionHeader {
                        version: SESSION_VERSION,
                        project: self.project.clone(),
                        kind: kind.clone(),
                        provenance: provenance.clone(),
                    };
                    let bytes =
                        serde_json::to_vec(&header).map_err(|error| invalid(error.to_string()))?;
                    file.write_all(&bytes)?;
                    file.write_all(b"\n")?;
                    file.sync_all()?;
                    drop(file);
                    sync_dir(&directory)?;
                    return Ok(BuildSession {
                        store: self.clone(),
                        kind,
                        provenance,
                        id,
                        journal: path,
                    });
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error.into()),
            }
        }
    }

    pub fn drop_root(&self, kind: &RootKind) -> Result<Option<RootRecord>, RootError> {
        let _guard = self.leases.lock()?;
        let record = self.read_root_locked(kind)?;
        if record.is_some() {
            fs::remove_file(self.path(kind)?)?;
            sync_dir(self.path(kind)?.parent().expect("root has a parent"))?;
        }
        Ok(record)
    }

    /// Freeze an explicitly chosen root into a release or pin. Entries keep their own
    /// provenance; the new record's provenance names the snapshot call only.
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
        let _guard = self.leases.lock()?;
        let source_record = self
            .read_root_locked(source)?
            .ok_or_else(|| invalid("source root is missing"))?;
        let record = RootRecord {
            version: ROOT_VERSION,
            project: self.project.clone(),
            kind: target.clone(),
            entries: source_record.entries,
            provenance,
        };
        let path = self.path(&target)?;
        if let Some(existing) = self.read_root_locked(&target)? {
            if existing != record {
                return Err(RootError::Conflict(
                    "snapshot target already exists".into(),
                ));
            }
        } else {
            write_record(&path, &record, &mut |_| Ok(()))?;
        }
        if matches!(&target, RootKind::Release { .. }) {
            self.trim_releases_locked()?;
        }
        Ok(record)
    }

    /// @cc [owner:fontanierh,label:correctness] build-v2-root-retention-read
    /// Retention MUST count every key named by a readable root or session and MUST report any
    /// unreadable record instead of guessing. A non-empty damaged list obliges GC to retain.
    /// See tests/roots.rs.
    pub fn retention(&self) -> Result<RetentionView, RootError> {
        let _guard = self.leases.lock()?;
        let mut view = RetentionView::default();
        let roots = self.root.join("roots");
        if fs::symlink_metadata(&roots).is_err() {
            return Ok(view);
        }
        for project in fs::read_dir(&roots)? {
            let project = project?;
            if !project.file_type()?.is_dir() {
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
                            for entry in record.entries.values() {
                                if valid_key(&entry.key) {
                                    view.keys.insert(entry.key.clone());
                                } else {
                                    view.damaged.push(path.display().to_string());
                                }
                            }
                        }
                        _ => view.damaged.push(path.display().to_string()),
                    }
                }
            }
            let main = base.join("main.json");
            if fs::symlink_metadata(&main).is_ok() {
                match fs::read(&main).map_err(|error| error.to_string()).and_then(|bytes| {
                    serde_json::from_slice::<RootRecord>(&bytes).map_err(|e| e.to_string())
                }) {
                    Ok(record) if record.version == ROOT_VERSION && record.project == project_name => {
                        for entry in record.entries.values() {
                            if valid_key(&entry.key) {
                                view.keys.insert(entry.key.clone());
                            } else {
                                view.damaged.push(main.display().to_string());
                            }
                        }
                    }
                    _ => view.damaged.push(main.display().to_string()),
                }
            }
            for entry in fs::read_dir(&base)? {
                let entry = entry?;
                let name = entry.file_name();
                let name = name.to_string_lossy();
                if !["worktree", "release", "pin", "session", "main.json"].contains(&name.as_ref()) {
                    view.damaged.push(entry.path().display().to_string());
                }
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
            if let Ok(sequence) = stem.parse::<u64>() {
                sequences.push(sequence);
            }
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
}

fn sort_key(kind: &RootKind) -> (u8, String) {
    match kind {
        RootKind::Main => (0, String::new()),
        RootKind::Worktree { id } => (1, id.clone()),
        RootKind::Release { sequence, .. } => (2, format!("{sequence:020}")),
        RootKind::Pin { id } => (3, id.clone()),
    }
}

/// C5c's durable custodian registry: which worker identity is a session custodian, if any.
pub trait SessionCustodians {
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
    IdentityAlive,
    IdentityUnknown,
    /// A dead session custodian whose guard cleanup is not yet durably confirmed.
    CleanupUnconfirmed(String),
    CustodianRecordUnreadable(String),
}

/// @cc [owner:fontanierh,label:correctness] gc-retains-until-session-cleanup-confirmed
/// A lease MUST be reclaimable only when every owner and worker identity is positively dead and
/// every registered session custodian's guard cleanup is durably confirmed. A dead custodian whose
/// cleanup is unconfirmed or unreadable MUST count as unknown liveness and retain the lease, and a
/// dead monitor process alone MUST NOT prove cleanup. Unknown liveness, live identities and
/// unreadable correlation records always retain. See tests/roots.rs.
pub fn may_reclaim(
    lease: &LeaseRecord,
    mut probe: impl FnMut(&ProcessIdentity) -> Liveness,
    custodians: &impl SessionCustodians,
    cleanup: &impl CustodianCleanup,
) -> Reclaim {
    for identity in std::iter::once(&lease.owner).chain(lease.workers.iter()) {
        match probe(identity) {
            Liveness::Dead => {}
            Liveness::Alive => return Reclaim::Retained(RetainReason::IdentityAlive),
            Liveness::Unknown => return Reclaim::Retained(RetainReason::IdentityUnknown),
        }
    }
    for worker in &lease.workers {
        match custodians.correlation(worker) {
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

/// The target a record file must hold, derived from its location.
fn kind_at(path: &Path) -> Result<RootKind, RootError> {
    let name = path.file_name().and_then(|value| value.to_str()).unwrap_or_default();
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
        "release" => Ok(RootKind::Release {
            sequence: stem
                .parse()
                .map_err(|_| damaged(format!("{} is not a release sequence", path.display())))?,
            label: String::new(),
        }),
        "pin" => Ok(RootKind::Pin { id: stem.into() }),
        _ => Err(damaged(format!("{} is not in a root folder", path.display()))),
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
    /// result is retained before B2 clears its claims. A damaged or unterminated record MUST fail
    /// the commit, leave the previous root and the journal untouched, and be reported. A commit
    /// removes only its own journal. See tests/roots.rs.
    pub fn use_result(&mut self, unit: &str, key: &str) -> Result<(), RootError> {
        checked_entry(unit, key)?;
        let _guard = self.store.leases.lock()?;
        let line = serde_json::to_vec(&SessionEntry {
            unit: unit.to_string(),
            key: key.to_string(),
        })
        .map_err(|error| invalid(error.to_string()))?;
        let mut file = OpenOptions::new().append(true).open(&self.journal)?;
        file.write_all(&line)?;
        file.write_all(b"\n")?;
        file.sync_all()?;
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
        observe(CommitStep::JournalRead)?;
        let _guard = self.store.leases.lock()?;
        let entries = read_journal(&self.journal, &self.store.project, &self.kind)?;
        let mut latest: BTreeMap<String, String> = BTreeMap::new();
        for entry in entries {
            latest.insert(entry.unit, entry.key);
        }
        let merged = match self.kind {
            RootKind::Main | RootKind::Worktree { .. } => {
                let mut current = self
                    .store
                    .read_root_locked(&self.kind)?
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
        let path = self.store.path(&self.kind)?;
        let existing = self.store.read_root_locked(&self.kind)?;
        if matches!(&self.kind, RootKind::Release { .. }) {
            if let Some(existing) = &existing {
                if existing != &record {
                    return Err(RootError::Conflict(
                        "release sequence already exists with different content".into(),
                    ));
                }
            }
        }
        if matches!(&self.kind, RootKind::Pin { .. }) {
            if let Some(existing) = &existing {
                if existing != &record {
                    return Err(RootError::Conflict(
                        "pin already exists with different content".into(),
                    ));
                }
            }
        }
        if existing.as_ref() != Some(&record) {
            write_record(&path, &record, &mut observe)?;
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

