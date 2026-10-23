//! Harness-owned unit, plan and saved-result descriptions.
use crate::support::work::{ProducedItem, UnitIdentity};
use std::collections::{BTreeMap, BTreeSet};

pub type ItemKey = (String, String);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessConfig {
    pub cache_version: String,
    pub worker_version: String,
    pub validator_version: String,
}

impl Default for HarnessConfig {
    fn default() -> Self {
        Self {
            cache_version: "harness-cache-1".into(),
            worker_version: "harness-worker-1".into(),
            validator_version: "harness-validator-1".into(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnitSpec {
    pub id: String,
    pub op_kind: String,
    pub op_version: String,
    pub code: String,
    pub params: String,
    pub inputs: Vec<InputSpec>,
    pub outputs: Vec<OutputSpec>,
}

impl UnitSpec {
    pub fn new(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            op_kind: "py_data".into(),
            op_version: "1".into(),
            code: "code-1".into(),
            params: String::new(),
            inputs: Vec::new(),
            outputs: Vec::new(),
        }
    }

    pub fn file_input(mut self, name: impl Into<String>, path: impl Into<String>) -> Self {
        self.inputs.push(InputSpec::file(name, path));
        self
    }

    pub fn optional_file_input(mut self, name: impl Into<String>, path: impl Into<String>) -> Self {
        self.inputs.push(InputSpec::optional_file(name, path));
        self
    }

    pub fn item_input(
        mut self,
        name: impl Into<String>,
        unit: impl Into<String>,
        item: impl Into<String>,
    ) -> Self {
        self.inputs.push(InputSpec::item(name, unit, item));
        self
    }

    pub fn reference_from(
        mut self,
        name: impl Into<String>,
        logical_path: impl Into<String>,
        class: impl Into<String>,
        unit: impl Into<String>,
        item: impl Into<String>,
    ) -> Self {
        self.inputs.push(InputSpec::reference_from(
            name,
            logical_path,
            class,
            unit,
            item,
        ));
        self
    }

    pub fn output(mut self, spec: OutputSpec) -> Self {
        self.outputs.push(spec);
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InputSpec {
    File {
        name: String,
        path: String,
        optional: bool,
        staged: String,
    },
    Item {
        name: String,
        staged: String,
        unit: String,
        item: String,
    },
    Reference {
        name: String,
        staged: String,
        logical_path: String,
        class: String,
        producer: Option<ItemKey>,
    },
}

impl InputSpec {
    pub fn file(name: impl Into<String>, path: impl Into<String>) -> Self {
        let name = name.into();
        Self::File {
            staged: format!("in/{name}"),
            name,
            path: path.into(),
            optional: false,
        }
    }

    pub fn optional_file(name: impl Into<String>, path: impl Into<String>) -> Self {
        let name = name.into();
        Self::File {
            staged: format!("in/{name}"),
            name,
            path: path.into(),
            optional: true,
        }
    }

    pub fn item(name: impl Into<String>, unit: impl Into<String>, item: impl Into<String>) -> Self {
        let name = name.into();
        Self::Item {
            staged: format!("in/{name}"),
            name,
            unit: unit.into(),
            item: item.into(),
        }
    }

    pub fn reference_from(
        name: impl Into<String>,
        logical_path: impl Into<String>,
        class: impl Into<String>,
        unit: impl Into<String>,
        item: impl Into<String>,
    ) -> Self {
        let name = name.into();
        Self::Reference {
            staged: format!("in/{name}"),
            name,
            logical_path: logical_path.into(),
            class: class.into(),
            producer: Some((unit.into(), item.into())),
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Self::File { name, .. } | Self::Item { name, .. } | Self::Reference { name, .. } => {
                name
            }
        }
    }

    pub fn staged_path(&self) -> String {
        match self {
            Self::File { staged, .. } => staged.clone(),
            Self::Item { staged, .. } | Self::Reference { staged, .. } => staged.clone(),
        }
    }

    pub fn staged_as(mut self, staged: impl Into<String>) -> Self {
        match &mut self {
            Self::File { staged: slot, .. }
            | Self::Item { staged: slot, .. }
            | Self::Reference { staged: slot, .. } => *slot = staged.into(),
        }
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputSpec {
    pub item: String,
    pub logical_path: String,
    pub class: String,
    pub files: Vec<OutputFileSpec>,
}

impl OutputSpec {
    pub fn new(item: impl Into<String>, logical_path: impl Into<String>) -> Self {
        Self {
            item: item.into(),
            logical_path: logical_path.into(),
            class: "Asset".into(),
            files: Vec::new(),
        }
    }

    pub fn file(mut self, path: impl Into<String>) -> Self {
        self.files.push(OutputFileSpec::required(path));
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputFileSpec {
    pub path: String,
    pub mode: u32,
    pub required: bool,
}

impl OutputFileSpec {
    pub fn required(path: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            mode: 0o644,
            required: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SavedUnit {
    pub identity: UnitIdentity,
    pub outputs: BTreeMap<String, ProducedItem>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SavedResults {
    pub units: BTreeMap<String, SavedUnit>,
}

impl SavedResults {
    pub fn get(&self, unit: &str) -> Option<&SavedUnit> {
        self.units.get(unit)
    }

    pub fn insert(&mut self, unit: impl Into<String>, saved: SavedUnit) {
        self.units.insert(unit.into(), saved);
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Plan {
    units: BTreeSet<String>,
}

impl Plan {
    pub fn new(units: impl IntoIterator<Item = impl Into<String>>) -> Self {
        Self {
            units: units.into_iter().map(Into::into).collect(),
        }
    }

    pub fn all(units: &[UnitSpec]) -> Self {
        Self::new(units.iter().map(|unit| unit.id.clone()))
    }

    pub fn contains(&self, unit: &str) -> bool {
        self.units.contains(unit)
    }

    pub fn insert(&mut self, unit: impl Into<String>) {
        self.units.insert(unit.into());
    }

    pub fn remove(&mut self, unit: &str) {
        self.units.remove(unit);
    }

    pub fn units(&self) -> &BTreeSet<String> {
        &self.units
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Target {
    Unit(String),
    All,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoreHealth {
    Available,
    Failing,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum EdgeRole {
    Content,
    Reference,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Edge {
    pub producer: String,
    pub consumer: String,
    pub item: String,
    pub input: String,
    pub role: EdgeRole,
}
