//! Frozen fixture inputs owned by the harness.
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum FileOrigin {
    Tracked,
    Untracked,
    Ignored,
}

pub fn normalized_mode(mode: u32) -> u32 {
    if mode & 0o111 != 0 { 0o755 } else { 0o644 }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FrozenFile {
    pub bytes: Vec<u8>,
    pub mode: u32,
    pub origin: FileOrigin,
}

impl FrozenFile {
    pub fn new(bytes: impl Into<Vec<u8>>) -> Self {
        Self {
            bytes: bytes.into(),
            mode: 0o644,
            origin: FileOrigin::Tracked,
        }
    }

    pub fn executable(bytes: impl Into<Vec<u8>>) -> Self {
        Self::new(bytes).with_mode(0o755)
    }

    pub fn with_mode(mut self, mode: u32) -> Self {
        self.mode = normalized_mode(mode);
        self
    }

    pub fn untracked(mut self) -> Self {
        self.origin = FileOrigin::Untracked;
        self
    }

    pub fn ignored(mut self) -> Self {
        self.origin = FileOrigin::Ignored;
        self
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FrozenSnapshot {
    entries: BTreeMap<String, FrozenFile>,
}

impl FrozenSnapshot {
    pub fn builder() -> FrozenSnapshotBuilder {
        FrozenSnapshotBuilder::default()
    }

    pub fn get(&self, path: &str) -> Option<&FrozenFile> {
        self.entries.get(path)
    }

    pub fn contains(&self, path: &str) -> bool {
        self.entries.contains_key(path)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// A copy with one tracked file replaced or added.
    pub fn with_file(&self, path: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Self {
        self.with_entry(path, FrozenFile::new(bytes))
    }

    pub fn with_entry(&self, path: impl Into<String>, file: FrozenFile) -> Self {
        let mut next = self.clone();
        next.entries.insert(path.into(), file);
        next
    }

    /// A copy without the path; absence is distinct from an empty file.
    pub fn without(&self, path: &str) -> Self {
        let mut next = self.clone();
        next.entries.remove(path);
        next
    }
}

#[derive(Clone, Debug, Default)]
pub struct FrozenSnapshotBuilder {
    entries: BTreeMap<String, FrozenFile>,
}

impl FrozenSnapshotBuilder {
    pub fn file(mut self, path: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Self {
        self.entries.insert(path.into(), FrozenFile::new(bytes));
        self
    }

    pub fn executable(mut self, path: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Self {
        self.entries
            .insert(path.into(), FrozenFile::executable(bytes));
        self
    }

    pub fn untracked(mut self, path: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Self {
        self.entries
            .insert(path.into(), FrozenFile::new(bytes).untracked());
        self
    }

    pub fn ignored(mut self, path: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Self {
        self.entries
            .insert(path.into(), FrozenFile::new(bytes).ignored());
        self
    }

    pub fn build(self) -> FrozenSnapshot {
        FrozenSnapshot {
            entries: self.entries,
        }
    }
}
