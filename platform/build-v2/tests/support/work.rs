//! Harness presentation of unit identity and deterministic fixture work.
//!
//! Identity is compared structurally: the model names the ingredients that matter rather than
//! reproducing a byte encoding. Work payloads are only the fixture's deterministic outputs.
use crate::support::snapshot::FrozenSnapshot;
use crate::support::spec::{HarnessConfig, InputSpec, ItemKey, UnitSpec};
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FileValue {
    Absent,
    /// Raw project sources are staged read-only and keyed by bytes only; ambient mode is not
    /// identity. Projected item files keep their semantic mode below.
    Present {
        bytes: Vec<u8>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemberFile {
    pub path: String,
    pub mode: u32,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProducedItem {
    pub logical_path: String,
    pub class: String,
    pub files: Vec<MemberFile>,
}

pub type ProducedItems = BTreeMap<ItemKey, ProducedItem>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InputIdentity {
    File {
        name: String,
        staged: String,
        value: FileValue,
    },
    Item {
        name: String,
        staged: String,
        logical_path: String,
        class: String,
        files: Vec<MemberFile>,
    },
    Reference {
        name: String,
        staged: String,
        logical_path: String,
        class: String,
    },
}

impl InputIdentity {
    pub fn name(&self) -> &str {
        match self {
            Self::File { name, .. } | Self::Item { name, .. } | Self::Reference { name, .. } => {
                name
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputFileDecl {
    pub path: String,
    pub mode: u32,
    pub required: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputDecl {
    pub item: String,
    pub logical_path: String,
    pub class: String,
    pub files: Vec<OutputFileDecl>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnitIdentity {
    pub cache_version: String,
    pub op: String,
    pub code: String,
    pub params: String,
    pub worker_version: String,
    pub validator_version: String,
    pub outputs: Vec<OutputDecl>,
    pub inputs: Vec<InputIdentity>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ResolvedValue {
    File(FileValue),
    Item {
        logical_path: String,
        class: String,
        files: Vec<MemberFile>,
    },
    Reference {
        logical_path: String,
        class: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedInput {
    pub spec: InputSpec,
    pub value: ResolvedValue,
}

pub fn resolve_input(
    spec: &InputSpec,
    snapshot: &FrozenSnapshot,
    produced: &ProducedItems,
) -> Result<ResolvedInput, String> {
    let value = match spec {
        InputSpec::File { path, optional, .. } => match snapshot.get(path) {
            Some(file) => ResolvedValue::File(FileValue::Present {
                bytes: file.bytes.clone(),
            }),
            None if *optional => ResolvedValue::File(FileValue::Absent),
            None => return Err(format!("missing required file input {path}")),
        },
        InputSpec::Item { unit, item, .. } => {
            let produced_item = produced
                .get(&(unit.clone(), item.clone()))
                .ok_or_else(|| format!("missing producer item {unit}/{item}"))?;
            ResolvedValue::Item {
                logical_path: produced_item.logical_path.clone(),
                class: produced_item.class.clone(),
                files: produced_item.files.clone(),
            }
        }
        InputSpec::Reference {
            logical_path,
            class,
            ..
        } => ResolvedValue::Reference {
            logical_path: logical_path.clone(),
            class: class.clone(),
        },
    };
    Ok(ResolvedInput {
        spec: spec.clone(),
        value,
    })
}

pub fn unit_identity(
    config: &HarnessConfig,
    unit: &UnitSpec,
    resolved: &[ResolvedInput],
) -> UnitIdentity {
    let mut inputs: Vec<_> = resolved
        .iter()
        .map(|input| match &input.value {
            ResolvedValue::File(value) => InputIdentity::File {
                name: input.spec.name().into(),
                staged: input.spec.staged_path(),
                value: value.clone(),
            },
            ResolvedValue::Item {
                logical_path,
                class,
                files,
            } => InputIdentity::Item {
                name: input.spec.name().into(),
                staged: input.spec.staged_path(),
                logical_path: logical_path.clone(),
                class: class.clone(),
                files: files.clone(),
            },
            ResolvedValue::Reference {
                logical_path,
                class,
            } => InputIdentity::Reference {
                name: input.spec.name().into(),
                staged: input.spec.staged_path(),
                logical_path: logical_path.clone(),
                class: class.clone(),
            },
        })
        .collect();
    inputs.sort_by(|a, b| a.name().cmp(b.name()));

    let mut outputs: Vec<_> = unit
        .outputs
        .iter()
        .map(|output| {
            let mut files: Vec<_> = output
                .files
                .iter()
                .map(|file| OutputFileDecl {
                    path: file.path.clone(),
                    mode: file.mode,
                    required: file.required,
                })
                .collect();
            files.sort_by(|a, b| a.path.cmp(&b.path));
            OutputDecl {
                item: output.item.clone(),
                logical_path: output.logical_path.clone(),
                class: output.class.clone(),
                files,
            }
        })
        .collect();
    outputs.sort_by(|a, b| a.item.cmp(&b.item));

    UnitIdentity {
        cache_version: config.cache_version.clone(),
        op: format!("{}/{}", unit.op_kind, unit.op_version),
        code: unit.code.clone(),
        params: unit.params.clone(),
        worker_version: config.worker_version.clone(),
        validator_version: config.validator_version.clone(),
        outputs,
        inputs,
    }
}

fn push_bytes(buffer: &mut Vec<u8>, bytes: &[u8]) {
    buffer.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    buffer.extend_from_slice(bytes);
}

fn push_str(buffer: &mut Vec<u8>, value: &str) {
    push_bytes(buffer, value.as_bytes());
}

/// Deterministic fixture work. It depends on params and content values, never on code,
/// item labels or modes; those are identity ingredients instead.
pub fn work_payload(unit: &UnitSpec, resolved: &[ResolvedInput]) -> Vec<u8> {
    let mut buffer = Vec::new();
    push_str(&mut buffer, "atelier-harness-work/1");
    push_str(&mut buffer, &unit.params);
    let mut inputs: Vec<_> = resolved.iter().collect();
    inputs.sort_by(|a, b| a.spec.name().cmp(b.spec.name()));
    for input in inputs {
        push_str(&mut buffer, input.spec.name());
        match &input.value {
            ResolvedValue::File(FileValue::Absent) => push_str(&mut buffer, "absent"),
            ResolvedValue::File(FileValue::Present { bytes }) => {
                push_str(&mut buffer, "present");
                push_bytes(&mut buffer, bytes);
            }
            ResolvedValue::Item { files, .. } => {
                push_str(&mut buffer, "item");
                let mut files = files.clone();
                files.sort_by(|a, b| a.path.cmp(&b.path));
                for file in files {
                    push_bytes(&mut buffer, &file.bytes);
                }
            }
            ResolvedValue::Reference {
                logical_path,
                class,
            } => {
                push_str(&mut buffer, "reference");
                push_str(&mut buffer, logical_path);
                push_str(&mut buffer, class);
            }
        }
    }
    buffer
}

pub fn output_payloads(
    unit: &UnitSpec,
    resolved: &[ResolvedInput],
) -> BTreeMap<String, ProducedItem> {
    let base = work_payload(unit, resolved);
    unit.outputs
        .iter()
        .map(|output| {
            let files = output
                .files
                .iter()
                .map(|file| {
                    let mut buffer = base.clone();
                    push_str(&mut buffer, &output.logical_path);
                    push_str(&mut buffer, &output.class);
                    push_str(&mut buffer, &file.path);
                    MemberFile {
                        path: file.path.clone(),
                        mode: file.mode,
                        bytes: buffer,
                    }
                })
                .collect();
            (
                output.item.clone(),
                ProducedItem {
                    logical_path: output.logical_path.clone(),
                    class: output.class.clone(),
                    files,
                },
            )
        })
        .collect()
}

/// A saved entry is usable only if it still names every required file of the declaration.
pub fn saved_outputs_valid(unit: &UnitSpec, outputs: &BTreeMap<String, ProducedItem>) -> bool {
    for output in &unit.outputs {
        let Some(item) = outputs.get(&output.item) else {
            return false;
        };
        if item.logical_path != output.logical_path || item.class != output.class {
            return false;
        }
        let declared: std::collections::BTreeSet<_> =
            output.files.iter().map(|file| file.path.as_str()).collect();
        let mut seen = std::collections::BTreeSet::new();
        for file in &item.files {
            if !declared.contains(file.path.as_str()) || !seen.insert(file.path.as_str()) {
                return false;
            }
        }
        if output
            .files
            .iter()
            .any(|file| file.required && !seen.contains(file.path.as_str()))
        {
            return false;
        }
    }
    true
}
