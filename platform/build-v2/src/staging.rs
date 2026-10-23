//! Frozen-input staging and output collection for one worker job (C1b).
//!
//! [`stage`] turns an A3 [`PreparedUnit`] into a fresh, owned job folder holding exactly the
//! declared code and inputs at their declared job-relative paths, read-only, plus an empty writable
//! `output/`. Code bytes come from the frozen snapshot that was keyed, checked against the keyed
//! digests; live sources are never reread. Item inputs are cloned from the object store, never
//! copied. [`collect_outputs`] turns a finished job's `output/` tree into the complete manifest
//! that B2's `WriteTransaction::stage` consumes.
use crate::keys::{InputPayload, PreparedUnit};
use crate::protocol::JobRequest;
use crate::results::{OutputSources, WriteTransaction};
use crate::schema::{InputKind, StoredFile};
use crate::source_hashes::sha256;
use crate::store::{ObjectDigest, ObjectStore};
use crate::validate::{SnapshotEntry, SourceSnapshot};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Component, Path, PathBuf};

/// Where staging gets stored object bytes. Implementations clone, never copy.
pub trait ObjectSource {
    /// Create `destination` (which must not exist) as a read-only clone of the object `digest`.
    fn clone_object(&self, digest: &ObjectDigest, destination: &Path) -> Result<(), String>;
}

/// Store objects read while a live B2 write transaction pins them. The transaction's lease claims
/// the consumer key and every upstream result key, so producer objects stay protected from GC for
/// as long as this borrow lives. Restores are B1 clone-only and hash nothing.
pub struct PinnedObjects<'a> {
    objects: &'a ObjectStore,
    _pin: &'a WriteTransaction,
}

impl<'a> PinnedObjects<'a> {
    pub fn new(objects: &'a ObjectStore, pin: &'a WriteTransaction) -> Self {
        Self { objects, _pin: pin }
    }
}

impl ObjectSource for PinnedObjects<'_> {
    fn clone_object(&self, digest: &ObjectDigest, destination: &Path) -> Result<(), String> {
        self.objects
            .clone_to(digest, destination)
            .map_err(|error| format!("cannot clone object {digest}: {error}"))
    }
}

/// A staged job folder and the request that names it. Only [`stage`] builds one.
#[derive(Debug)]
pub struct StagedJob {
    job_dir: PathBuf,
    request: JobRequest,
}

impl StagedJob {
    pub fn job_dir(&self) -> &Path {
        &self.job_dir
    }
    pub fn output_dir(&self) -> PathBuf {
        self.job_dir.join("output")
    }
    /// The worker request: control metadata (job ID and folder) plus declared names only.
    pub fn request(&self) -> &JobRequest {
        &self.request
    }
}

fn io_error(path: &Path, error: io::Error) -> String {
    format!("{}: {error}", path.display())
}

/// Lexically safe, still-relative join; `relative` was validated by A2/A3 and is checked again.
fn inside(root: &Path, relative: &str) -> Result<PathBuf, String> {
    let path = Path::new(relative);
    let safe = !relative.is_empty()
        && !relative.contains(['\\', '\0'])
        && path
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
        && relative.split('/').all(|part| !part.is_empty());
    if !safe {
        return Err(format!("unsafe job-relative path: {relative:?}"));
    }
    Ok(root.join(path))
}

/// Create every missing parent of `path` below `root` as a real directory; refuse links.
fn parents(root: &Path, path: &Path) -> Result<(), String> {
    let parent = path.parent().ok_or("staged path has no parent")?;
    let relative = parent
        .strip_prefix(root)
        .map_err(|_| "staged path escapes the job folder")?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        current.push(component);
        match fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.is_dir() => {}
            Ok(_) => return Err(format!("{} is not a real directory", current.display())),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                fs::create_dir(&current).map_err(|error| io_error(&current, error))?
            }
            Err(error) => return Err(io_error(&current, error)),
        }
    }
    Ok(())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o444)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| io_error(path, error))?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|error| io_error(path, error))
}

fn set_mode(path: &Path, mode: u32) -> Result<(), String> {
    fs::set_permissions(path, fs::Permissions::from_mode(mode))
        .map_err(|error| io_error(path, error))
}

fn stage_item(
    root: &Path,
    directory: &Path,
    files: &[StoredFile],
    objects: &dyn ObjectSource,
) -> Result<(), String> {
    let mut seen = BTreeSet::new();
    for file in files {
        if !seen.insert(file.path.as_str()) {
            return Err(format!("duplicate item member {}", file.path));
        }
        let mode = match file.mode {
            0o644 => 0o444,
            0o755 => 0o555,
            other => return Err(format!("item member {} has mode {other:o}", file.path)),
        };
        let destination = inside(directory, &file.path)?;
        parents(root, &destination)?;
        let digest = ObjectDigest::from_hex(&file.digest).map_err(|error| error.to_string())?;
        objects.clone_object(&digest, &destination)?;
        let metadata =
            fs::symlink_metadata(&destination).map_err(|error| io_error(&destination, error))?;
        if !metadata.is_file() || metadata.len() != file.size {
            return Err(format!(
                "item member {} is not the recorded {}-byte file",
                file.path, file.size
            ));
        }
        set_mode(&destination, mode)?;
    }
    Ok(())
}

/// Every directory below `root` except `output/`, deepest first.
fn staged_directories(root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut found = vec![];
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory).map_err(|error| io_error(&directory, error))? {
            let entry = entry.map_err(|error| io_error(&directory, error))?;
            let path = entry.path();
            if path != root.join("output")
                && entry
                    .file_type()
                    .map_err(|error| io_error(&path, error))?
                    .is_dir()
            {
                pending.push(path);
            }
        }
        found.push(directory);
    }
    found.reverse();
    Ok(found)
}

/// @cc [owner:fontanierh,label:correctness] staged-frozen-inputs
/// Staging MUST create a fresh job folder holding only the unit's declared code and inputs at their
/// exact declared job-relative paths, plus an empty writable `output/`. Code bytes MUST come from the
/// keyed frozen snapshot and match the keyed digests; live sources are never reread. `Bytes` inputs
/// are files and `Item` inputs directories of exactly their recorded members, cloned (never copied)
/// from pinned store objects with their recorded size and executable bit; absent optional inputs
/// create nothing. Every staged file and directory except `output/` MUST be read-only. Unsafe
/// paths, links, shape mismatches and incomplete items MUST fail the staging. The request MUST carry
/// no install path, locator or source path. See tests/staging.rs.
pub fn stage(
    prepared: &PreparedUnit,
    frozen_code: &SourceSnapshot,
    objects: &dyn ObjectSource,
    job_dir: &Path,
    job_id: &str,
) -> Result<StagedJob, String> {
    if !job_dir.is_absolute() {
        return Err("the job folder must be an absolute path".into());
    }
    let parent = job_dir.parent().ok_or("the job folder has no parent")?;
    let parent = parent
        .canonicalize()
        .map_err(|error| io_error(parent, error))?;
    let job_dir = parent.join(job_dir.file_name().ok_or("the job folder has no name")?);
    fs::create_dir(&job_dir).map_err(|error| io_error(&job_dir, error))?;
    let staged = stage_into(prepared, frozen_code, objects, &job_dir, job_id);
    if staged.is_err() {
        // Only this call's own fresh folder is removed; nothing else is touched.
        let _ = remove_job(&job_dir);
    }
    staged
}

fn stage_into(
    prepared: &PreparedUnit,
    frozen_code: &SourceSnapshot,
    objects: &dyn ObjectSource,
    job_dir: &Path,
    job_id: &str,
) -> Result<StagedJob, String> {
    let ingredients = prepared.ingredients();
    for (path, digest) in &ingredients.code {
        let Some(SnapshotEntry::File(bytes)) = frozen_code.get(path) else {
            return Err(format!("declared code {path} is not a frozen regular file"));
        };
        if &sha256(bytes) != digest {
            return Err(format!("declared code {path} changed after keying"));
        }
        let destination = inside(job_dir, path)?;
        parents(job_dir, &destination)?;
        write_new(&destination, bytes)?;
    }
    for input in prepared.inputs() {
        let name = &input.wire.name;
        let destination = inside(job_dir, &input.wire.path)?;
        let kind = ingredients.input_kinds.get(name);
        match (&input.payload, kind) {
            (InputPayload::Absent, Some(InputKind::File)) => {}
            (InputPayload::Bytes(bytes), Some(InputKind::File)) => {
                parents(job_dir, &destination)?;
                write_new(&destination, bytes)?;
            }
            (InputPayload::Item { files, .. }, Some(InputKind::Item)) => {
                parents(job_dir, &destination)?;
                fs::create_dir(&destination).map_err(|error| io_error(&destination, error))?;
                stage_item(job_dir, &destination, files, objects)?;
            }
            _ => {
                return Err(format!(
                    "input {name} payload does not match its keyed shape"
                ));
            }
        }
    }
    let output = job_dir.join("output");
    fs::create_dir(&output).map_err(|error| io_error(&output, error))?;
    for directory in staged_directories(job_dir)? {
        set_mode(&directory, 0o555)?;
    }
    let folder = job_dir.to_str().ok_or("the job folder is not UTF-8")?;
    let mut request = prepared.request(job_id, folder);
    // Install paths are checkout locators for B3; the worker never needs them.
    for output in &mut request.outputs {
        output.install_path = None;
    }
    Ok(StagedJob {
        job_dir: job_dir.to_path_buf(),
        request,
    })
}

/// @cc [owner:fontanierh,label:correctness] collected-output-manifest
/// Collection MUST walk the job's `output/` tree without following links, refuse anything but
/// regular files and directories, and require the worker's reported file list to equal the files
/// found. Every found file is mapped to its declaring item; an undeclared file fails collection. It
/// never hashes: B2 freezes and hashes the returned sources once. See tests/staging.rs.
pub fn collect_outputs(
    staged: &StagedJob,
    prepared: &PreparedUnit,
    reported: &[String],
) -> Result<OutputSources, String> {
    let root = staged.output_dir();
    let mut found = BTreeMap::new();
    let mut pending = vec![root.clone()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory).map_err(|error| io_error(&directory, error))? {
            let entry = entry.map_err(|error| io_error(&directory, error))?;
            let path = entry.path();
            let kind = fs::symlink_metadata(&path)
                .map_err(|error| io_error(&path, error))?
                .file_type();
            let relative = path
                .strip_prefix(&root)
                .map_err(|_| "output escapes output/")?
                .to_str()
                .ok_or("output name is not UTF-8")?
                .to_string();
            if kind.is_dir() {
                pending.push(path);
            } else if kind.is_file() {
                found.insert(relative, path);
            } else {
                return Err(format!("output {relative} is not a regular file"));
            }
        }
    }
    let reported_set: BTreeSet<_> = reported.iter().map(String::as_str).collect();
    if reported_set.len() != reported.len()
        || !reported_set
            .iter()
            .copied()
            .eq(found.keys().map(String::as_str))
    {
        return Err("the worker's reported outputs differ from the files in output/".into());
    }
    let mut sources = OutputSources::new();
    for (relative, path) in found {
        let item = prepared
            .ingredients()
            .logical_outputs
            .iter()
            .find(|item| item.files.iter().any(|file| file.path == relative))
            .ok_or_else(|| format!("output {relative} is not declared"))?;
        sources.insert((item.id.clone(), relative), path);
    }
    Ok(sources)
}

/// Remove a job folder that staging created, restoring write permission on the way. Call it only
/// after B2 has staged or refused the outputs: completed results live in the store, not here.
pub fn remove_job(job_dir: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(job_dir).map_err(|error| io_error(job_dir, error))?;
    if !metadata.is_dir() {
        return Err(format!("{} is not a job folder", job_dir.display()));
    }
    let mut pending = vec![job_dir.to_path_buf()];
    while let Some(directory) = pending.pop() {
        set_mode(&directory, 0o755)?;
        for entry in fs::read_dir(&directory).map_err(|error| io_error(&directory, error))? {
            let entry = entry.map_err(|error| io_error(&directory, error))?;
            if entry
                .file_type()
                .map_err(|error| io_error(&entry.path(), error))?
                .is_dir()
            {
                pending.push(entry.path());
            }
        }
    }
    fs::remove_dir_all(job_dir).map_err(|error| io_error(job_dir, error))
}
