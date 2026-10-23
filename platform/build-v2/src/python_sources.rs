//! Explicit source-file capture for the unused static Python backend.
//! This freezes named bytes before A3 preparation; A6 owns later live-edit fencing.
use crate::keys::SourceVersions;
use crate::paths::relative_path;
use crate::source_hashes::FileVersion;
use crate::validate::{SnapshotEntry, SourceSnapshot};
use std::ffi::CString;
use std::fs::{File, Metadata, OpenOptions};
use std::io::{self, Read};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;

#[derive(Default)]
pub struct CapturedSources {
    pub snapshot: SourceSnapshot,
    pub versions: SourceVersions,
    pub files_read: usize,
    pub bytes_read: u64,
}

fn version(metadata: &Metadata) -> Result<FileVersion, String> {
    let time = |seconds: i64, nanos: i64| {
        seconds
            .checked_mul(1_000_000_000)
            .and_then(|value| value.checked_add(nanos))
            .ok_or_else(|| "source timestamp outside supported nanosecond range".to_string())
    };
    Ok(FileVersion {
        device: metadata.dev(),
        inode: metadata.ino(),
        size: metadata.len(),
        mtime_ns: time(metadata.mtime(), metadata.mtime_nsec())?,
        ctime_ns: time(metadata.ctime(), metadata.ctime_nsec())?,
    })
}

fn open_named(root: &File, path: &str) -> io::Result<File> {
    let mut directory = root.try_clone()?;
    let mut parts = path.split('/').peekable();
    while let Some(part) = parts.next() {
        let name = CString::new(part).map_err(|_| io::ErrorKind::InvalidInput)?;
        let flags = libc::O_RDONLY
            | libc::O_CLOEXEC
            | libc::O_NOFOLLOW
            | if parts.peek().is_some() {
                libc::O_DIRECTORY
            } else {
                libc::O_NONBLOCK
            };
        let descriptor = unsafe { libc::openat(directory.as_raw_fd(), name.as_ptr(), flags) };
        if descriptor < 0 {
            return Err(io::Error::last_os_error());
        }
        directory = unsafe { File::from_raw_fd(descriptor) };
    }
    Ok(directory)
}

/// @cc [owner:fontanierh,label:correctness] named-python-source-snapshot
/// Capture MUST read only explicit safe project-relative names through an anchored no-follow
/// descriptor chain. FileVersion MUST describe the same complete regular bytes observed before
/// and after reading; changed files MUST refuse rather than mint a reusable stat hint. Absence,
/// links, directories and unreadable inputs MUST remain distinct observations for A4 selection.
/// No output walk, Git state, installed dependency identity or later live-edit proof is implied.
/// See tests/python_sources.rs; A6 mid-build fencing remains separate.
pub fn capture_sources<'a>(
    root: &Path,
    names: impl IntoIterator<Item = &'a str>,
) -> Result<CapturedSources, String> {
    let root = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(root)
        .map_err(|error| format!("cannot anchor source root: {error}"))?;
    let mut captured = CapturedSources::default();
    for name in names {
        relative_path(name, false)?;
        if captured.snapshot.contains_key(name) || captured.versions.contains_key(name) {
            continue;
        }
        let mut file = match open_named(&root, name) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => {
                let entry = if error.raw_os_error() == Some(libc::ELOOP) {
                    SnapshotEntry::Symlink
                } else {
                    SnapshotEntry::Unreadable
                };
                captured.snapshot.insert(name.into(), entry);
                continue;
            }
        };
        let metadata = file.metadata().map_err(|error| error.to_string())?;
        if !metadata.is_file() {
            captured.snapshot.insert(
                name.into(),
                if metadata.is_dir() {
                    SnapshotEntry::Directory
                } else {
                    SnapshotEntry::Unreadable
                },
            );
            continue;
        }
        let before = version(&metadata)?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)
            .map_err(|error| format!("cannot read declared source {name}: {error}"))?;
        let after = version(&file.metadata().map_err(|error| error.to_string())?)?;
        if before != after || after.size != bytes.len() as u64 {
            return Err(format!("declared source changed during capture: {name}"));
        }
        captured.files_read += 1;
        captured.bytes_read += bytes.len() as u64;
        captured.versions.insert(name.into(), after);
        captured
            .snapshot
            .insert(name.into(), SnapshotEntry::File(bytes));
    }
    Ok(captured)
}
