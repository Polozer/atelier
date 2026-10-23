//! Narrow anchored filesystem operations for checkout journals and owned file moves.
//! Output paths never traverse a symlink parent. Payload cloning remains B1's job.
use crate::paths::relative_path;
use serde::{Deserialize, Serialize};
use std::ffi::CString;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileObservation {
    pub device: u64,
    pub inode: u64,
    pub size: u64,
    pub modified_seconds: i64,
    pub modified_nanos: i64,
    pub changed_seconds: i64,
    pub changed_nanos: i64,
    pub mode: u32,
}
impl FileObservation {
    pub fn from_metadata(metadata: &fs::Metadata) -> Self {
        Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            size: metadata.len(),
            modified_seconds: metadata.mtime(),
            modified_nanos: metadata.mtime_nsec(),
            changed_seconds: metadata.ctime(),
            changed_nanos: metadata.ctime_nsec(),
            mode: metadata.permissions().mode() & 0o777,
        }
    }
    pub fn same_inode(&self, other: &Self) -> bool {
        self.device == other.device && self.inode == other.inode
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CreatedDirectory {
    pub path: String,
    pub device: u64,
    pub inode: u64,
}

pub(crate) struct RootFs {
    directory: File,
    path: PathBuf,
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}
fn name(value: &str) -> io::Result<CString> {
    CString::new(value).map_err(|_| invalid("path contains NUL"))
}
fn opened(directory: &File, value: &str, flags: i32, mode: u32) -> io::Result<File> {
    let value = name(value)?;
    let descriptor = unsafe {
        libc::openat(
            directory.as_raw_fd(),
            value.as_ptr(),
            flags | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            mode as libc::mode_t,
        )
    };
    if descriptor < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { File::from_raw_fd(descriptor) })
}

impl RootFs {
    pub fn open(root: &Path) -> io::Result<Self> {
        use std::os::unix::fs::OpenOptionsExt;
        let directory = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW)
            .open(root)?;
        Ok(Self {
            directory,
            path: root.canonicalize()?,
        })
    }
    pub fn absolute(&self, relative: &str) -> PathBuf {
        self.path.join(relative)
    }

    fn parent(&self, path: &str) -> io::Result<(File, String)> {
        relative_path(path, true).map_err(invalid)?;
        let mut parts: Vec<_> = path.split('/').collect();
        let leaf = parts.pop().unwrap().to_string();
        let mut directory = self.directory.try_clone()?;
        for part in parts {
            directory = opened(&directory, part, libc::O_RDONLY | libc::O_DIRECTORY, 0)?;
        }
        Ok((directory, leaf))
    }

    pub fn mkdirs(&self, path: &str, mode: u32) -> io::Result<Vec<CreatedDirectory>> {
        relative_path(path, true).map_err(invalid)?;
        let mut directory = self.directory.try_clone()?;
        let mut prefix = String::new();
        let mut created = vec![];
        for component in path.split('/') {
            if !prefix.is_empty() {
                prefix.push('/');
            }
            prefix.push_str(component);
            let mut own = false;
            let next = match opened(&directory, component, libc::O_RDONLY | libc::O_DIRECTORY, 0) {
                Ok(next) => next,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    let component_name = name(component)?;
                    if unsafe {
                        libc::mkdirat(
                            directory.as_raw_fd(),
                            component_name.as_ptr(),
                            mode as libc::mode_t,
                        )
                    } != 0
                    {
                        let error = io::Error::last_os_error();
                        if error.kind() != io::ErrorKind::AlreadyExists {
                            return Err(error);
                        }
                    } else {
                        own = true;
                    }
                    let next =
                        opened(&directory, component, libc::O_RDONLY | libc::O_DIRECTORY, 0)?;
                    directory.sync_all()?;
                    next
                }
                Err(error) => return Err(error),
            };
            if own {
                let metadata = next.metadata()?;
                created.push(CreatedDirectory {
                    path: prefix.clone(),
                    device: metadata.dev(),
                    inode: metadata.ino(),
                });
            }
            directory = next;
        }
        Ok(created)
    }

    pub fn file(&self, path: &str) -> io::Result<File> {
        let (parent, leaf) = self.parent(path)?;
        let file = opened(&parent, &leaf, libc::O_RDONLY | libc::O_NONBLOCK, 0)?;
        if !file.metadata()?.is_file() {
            return Err(invalid("owned leaf is not a regular file"));
        }
        Ok(file)
    }
    pub fn observe(&self, path: &str) -> io::Result<Option<FileObservation>> {
        match self.file(path) {
            Ok(file) => Ok(Some(FileObservation::from_metadata(&file.metadata()?))),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error),
        }
    }
    pub fn read(&self, path: &str) -> io::Result<Vec<u8>> {
        let mut bytes = vec![];
        self.file(path)?
            .take(64 * 1024 * 1024 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > 64 * 1024 * 1024 {
            return Err(invalid("install metadata exceeds 64 MiB"));
        }
        Ok(bytes)
    }

    pub fn rename_exclusive(&self, from: &str, to: &str) -> io::Result<()> {
        let (source, source_leaf) = self.parent(from)?;
        let (destination, destination_leaf) = self.parent(to)?;
        let source_leaf = name(&source_leaf)?;
        let destination_leaf = name(&destination_leaf)?;
        #[cfg(target_os = "macos")]
        let result = unsafe {
            libc::renameatx_np(
                source.as_raw_fd(),
                source_leaf.as_ptr(),
                destination.as_raw_fd(),
                destination_leaf.as_ptr(),
                libc::RENAME_EXCL,
            )
        };
        #[cfg(target_os = "linux")]
        let result = unsafe {
            libc::renameat2(
                source.as_raw_fd(),
                source_leaf.as_ptr(),
                destination.as_raw_fd(),
                destination_leaf.as_ptr(),
                libc::RENAME_NOREPLACE,
            )
        };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        source.sync_all()?;
        destination.sync_all()
    }

    pub fn remove_owned(&self, path: &str, expected: &FileObservation) -> io::Result<()> {
        let actual = self
            .observe(path)?
            .ok_or_else(|| invalid("owned cleanup file disappeared"))?;
        if !actual.same_inode(expected) {
            return Err(invalid("owned cleanup leaf was replaced"));
        }
        let (parent, leaf) = self.parent(path)?;
        if unsafe { libc::unlinkat(parent.as_raw_fd(), name(&leaf)?.as_ptr(), 0) } != 0 {
            return Err(io::Error::last_os_error());
        }
        parent.sync_all()
    }

    pub fn remove_empty_directory(&self, entry: &CreatedDirectory) -> io::Result<()> {
        let (parent, leaf) = self.parent(&entry.path)?;
        let directory = match opened(&parent, &leaf, libc::O_RDONLY | libc::O_DIRECTORY, 0) {
            Ok(directory) => directory,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(error),
        };
        let metadata = directory.metadata()?;
        if metadata.dev() != entry.device || metadata.ino() != entry.inode {
            return Err(invalid("cleanup directory was replaced"));
        }
        if unsafe {
            libc::unlinkat(
                parent.as_raw_fd(),
                name(&leaf)?.as_ptr(),
                libc::AT_REMOVEDIR,
            )
        } != 0
        {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::DirectoryNotEmpty {
                return Ok(());
            }
            return Err(error);
        }
        parent.sync_all()
    }

    fn temporary(&self, path: &str, bytes: &[u8], mode: u32) -> io::Result<(File, String)> {
        let (parent, leaf) = self.parent(path)?;
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let temporary = format!(".{leaf}.{}-{serial}.tmp", std::process::id());
        let mut file = opened(
            &parent,
            &temporary,
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
            0o600,
        )?;
        let result = (|| {
            file.write_all(bytes)?;
            file.set_permissions(fs::Permissions::from_mode(mode))?;
            file.sync_all()
        })();
        if result.is_err() {
            unsafe {
                libc::unlinkat(parent.as_raw_fd(), name(&temporary)?.as_ptr(), 0);
            }
        }
        result?;
        Ok((parent, temporary))
    }

    pub fn replace_metadata(&self, path: &str, bytes: &[u8]) -> io::Result<()> {
        let (parent, temporary) = self.temporary(path, bytes, 0o600)?;
        let leaf = path.rsplit('/').next().unwrap();
        let result = unsafe {
            libc::renameat(
                parent.as_raw_fd(),
                name(&temporary)?.as_ptr(),
                parent.as_raw_fd(),
                name(leaf)?.as_ptr(),
            )
        };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        parent.sync_all()
    }

    pub fn publish_metadata(&self, path: &str, bytes: &[u8]) -> io::Result<()> {
        let (parent, temporary) = self.temporary(path, bytes, 0o444)?;
        let leaf = path.rsplit('/').next().unwrap();
        let result = unsafe {
            libc::linkat(
                parent.as_raw_fd(),
                name(&temporary)?.as_ptr(),
                parent.as_raw_fd(),
                name(leaf)?.as_ptr(),
                0,
            )
        };
        let publication = if result == 0 {
            parent.sync_all()
        } else {
            Err(io::Error::last_os_error())
        };
        let removal = unsafe { libc::unlinkat(parent.as_raw_fd(), name(&temporary)?.as_ptr(), 0) };
        publication?;
        if removal != 0 {
            return Err(io::Error::last_os_error());
        }
        parent.sync_all()
    }
}
