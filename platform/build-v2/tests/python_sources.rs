use atelier_build_v2::python_sources::capture_sources;
use atelier_build_v2::validate::SnapshotEntry;
use std::fs;
use std::os::unix::fs::symlink;
use std::sync::atomic::{AtomicU64, Ordering};
static NEXT: AtomicU64 = AtomicU64::new(0);

struct Space(std::path::PathBuf);
impl Space {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "atelier-v2-python-source-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Space {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn capture_reads_only_explicit_named_regular_files_and_keeps_frozen_bytes() {
    let space = Space::new();
    fs::create_dir(space.0.join("data")).unwrap();
    fs::write(space.0.join("data/source"), [0, 255, 1]).unwrap();
    fs::write(space.0.join("unselected"), b"not observed").unwrap();
    let first =
        capture_sources(&space.0, ["data/source", "data/source", "missing", "data"]).unwrap();
    assert_eq!(first.files_read, 1);
    assert_eq!(first.bytes_read, 3);
    assert!(!first.snapshot.contains_key("unselected"));
    assert!(!first.snapshot.contains_key("missing"));
    assert!(matches!(first.snapshot["data"], SnapshotEntry::Directory));
    assert_eq!(first.versions["data/source"].size, 3);
    fs::write(space.0.join("data/source"), b"new").unwrap();
    let second = capture_sources(&space.0, ["data/source"]).unwrap();
    assert!(
        matches!(&first.snapshot["data/source"], SnapshotEntry::File(bytes) if bytes == &[0,255,1])
    );
    assert!(
        matches!(&second.snapshot["data/source"], SnapshotEntry::File(bytes) if bytes == b"new")
    );
}

#[test]
fn capture_refuses_traversal_and_never_follows_a_named_or_ancestor_link() {
    let space = Space::new();
    let outside = Space::new();
    fs::write(outside.0.join("secret"), b"outside").unwrap();
    symlink(outside.0.join("secret"), space.0.join("leaf")).unwrap();
    symlink(&outside.0, space.0.join("parent")).unwrap();
    let observed = capture_sources(&space.0, ["leaf", "parent/secret"]).unwrap();
    assert_eq!(observed.files_read, 0);
    assert_eq!(observed.bytes_read, 0);
    assert!(observed.versions.is_empty());
    assert!(matches!(observed.snapshot["leaf"], SnapshotEntry::Symlink));
    assert!(matches!(
        observed.snapshot["parent/secret"],
        SnapshotEntry::Unreadable | SnapshotEntry::Symlink
    ));
    for invalid in ["../secret", "/secret", "a//b", "a/./b", "a\\b"] {
        assert!(capture_sources(&space.0, [invalid]).is_err(), "{invalid}");
    }
    assert_eq!(fs::read(outside.0.join("secret")).unwrap(), b"outside");
}

#[test]
fn same_size_and_mtime_replacement_has_a_new_source_version_and_digest() {
    use atelier_build_v2::source_hashes::SourceHashCache;
    let space = Space::new();
    let source = space.0.join("source");
    fs::write(&source, b"before").unwrap();
    let old_time = fs::metadata(&source).unwrap().modified().unwrap();
    let before = capture_sources(&space.0, ["source"]).unwrap();
    // Both inodes coexist before replacement, so inode inequality is deterministic.
    let replacement = space.0.join("replacement");
    fs::write(&replacement, b"after!").unwrap();
    fs::File::options()
        .write(true)
        .open(&replacement)
        .unwrap()
        .set_times(fs::FileTimes::new().set_modified(old_time))
        .unwrap();
    fs::rename(&replacement, &source).unwrap();
    let after = capture_sources(&space.0, ["source"]).unwrap();
    assert_eq!(
        before.versions["source"].size,
        after.versions["source"].size
    );
    assert_eq!(
        before.versions["source"].mtime_ns,
        after.versions["source"].mtime_ns
    );
    assert_ne!(
        before.versions["source"].inode,
        after.versions["source"].inode
    );
    let bytes = |captured: &atelier_build_v2::python_sources::CapturedSources| {
        let SnapshotEntry::File(bytes) = &captured.snapshot["source"] else {
            panic!()
        };
        bytes.clone()
    };
    let mut hashes = SourceHashCache::default();
    let first = hashes
        .digest(before.versions.get("source"), &bytes(&before))
        .unwrap();
    let second = hashes
        .digest(after.versions.get("source"), &bytes(&after))
        .unwrap();
    assert_ne!(first, second);
    assert_eq!(hashes.stats.versions_hashed, 2);
    assert_eq!(hashes.stats.memo_hits, 0);
}
