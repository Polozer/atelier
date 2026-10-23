//! Adapter seam for the future A5/A9 scheduler, plus today's fake adapters.
//!
//! The fake adapter drives the current fixture worker interface. It proves the harness, not a
//! production scheduler; real-engine integration remains pending.
use crate::support::snapshot::FrozenSnapshot;
use crate::support::spec::{
    Edge, EdgeRole, HarnessConfig, InputSpec, ItemKey, Plan, SavedResults, SavedUnit, StoreHealth,
    Target, UnitSpec,
};
use crate::support::work::{
    ProducedItem, ProducedItems, ResolvedInput, output_payloads, resolve_input,
    saved_outputs_valid, unit_identity,
};
use atelier_build_v2::fixture::{FixtureFile, MockStep, MockWorker, Worker};
use atelier_build_v2::protocol::{JobRequest, StagedInput};
use atelier_build_v2::schema::{ContentIdentity, Op, OutputFile};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

pub struct BuildRequest<'a> {
    pub config: &'a HarnessConfig,
    pub units: &'a [UnitSpec],
    pub snapshot: &'a FrozenSnapshot,
    pub targets: &'a [Target],
    pub plan: &'a Plan,
    pub saved: &'a SavedResults,
    pub store: StoreHealth,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Observation {
    pub roots: Vec<String>,
    pub order: Vec<String>,
    pub edges: Vec<Edge>,
    pub runs: Vec<String>,
    pub current: Vec<String>,
    pub requested: BTreeMap<ItemKey, ProducedItem>,
    pub outputs: BTreeMap<ItemKey, ProducedItem>,
    pub removal_intent: BTreeMap<ItemKey, ProducedItem>,
    pub worker_events: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BuildOutcome {
    pub observation: Observation,
    pub saved_after: SavedResults,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdapterError {
    pub message: String,
}

impl fmt::Display for AdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for AdapterError {}

pub trait BuildAdapter {
    fn execute(&mut self, request: &BuildRequest<'_>) -> Result<BuildOutcome, AdapterError>;
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum AdapterFault {
    #[default]
    None,
    StaleHit,
    OverRebuild,
    ReferenceBytes,
    MissingTarget,
}

#[derive(Default)]
pub struct FakeAdapter {
    fault: AdapterFault,
    next_job: usize,
}

impl FakeAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_fault(fault: AdapterFault) -> Self {
        Self { fault, next_job: 0 }
    }

    fn job_request(&mut self, unit: &UnitSpec, resolved: &[ResolvedInput]) -> JobRequest {
        self.next_job += 1;
        let job = self.next_job;
        let inputs = resolved
            .iter()
            .enumerate()
            .map(|(index, input)| StagedInput {
                name: input.spec.name().into(),
                path: input.spec.staged_path(),
                identity: ContentIdentity::Digest {
                    digest: format!("harness-input-{index}"),
                },
            })
            .collect();
        let outputs = unit
            .outputs
            .iter()
            .flat_map(|output| output.files.iter())
            .map(|file| OutputFile {
                path: file.path.clone(),
                install_path: None,
                required: file.required,
            })
            .collect();
        JobRequest {
            job_id: format!("job-{job}"),
            unit: unit.id.clone(),
            op: Op {
                kind: unit.op_kind.clone(),
                version: unit.op_version.clone(),
            },
            job_dir: format!("jobs/{job}"),
            script: "unit.py".into(),
            code: vec!["unit.py".into()],
            inputs,
            params: BTreeMap::new(),
            outputs,
        }
    }
}

fn unit_map(units: &[UnitSpec]) -> Result<BTreeMap<&str, &UnitSpec>, String> {
    let mut map = BTreeMap::new();
    for unit in units {
        if map.insert(unit.id.as_str(), unit).is_some() {
            return Err(format!("duplicate unit id {}", unit.id));
        }
    }
    Ok(map)
}

fn producers(unit: &UnitSpec) -> Vec<(&str, &str)> {
    let mut found = Vec::new();
    for input in &unit.inputs {
        match input {
            InputSpec::Item { unit, item, .. } => found.push((unit.as_str(), item.as_str())),
            InputSpec::Reference {
                producer: Some((unit, item)),
                ..
            } => found.push((unit.as_str(), item.as_str())),
            InputSpec::File { .. } | InputSpec::Reference { producer: None, .. } => {}
        }
    }
    found.sort();
    found
}

fn visit(
    id: &str,
    units: &BTreeMap<&str, &UnitSpec>,
    plan: &Plan,
    state: &mut BTreeMap<String, u8>,
    order: &mut Vec<String>,
) -> Result<(), String> {
    match state.get(id) {
        Some(2) => return Ok(()),
        Some(1) => return Err(format!("dependency cycle at {id}")),
        _ => {}
    }
    let unit = units.get(id).ok_or_else(|| format!("unknown unit {id}"))?;
    if !plan.contains(id) {
        return Err(format!("unit {id} is not in the plan"));
    }
    state.insert(id.into(), 1);
    for (producer, _) in producers(unit) {
        if !units.contains_key(producer) || !plan.contains(producer) {
            return Err(format!("unit {id} needs unavailable producer {producer}"));
        }
        visit(producer, units, plan, state, order)?;
    }
    state.insert(id.into(), 2);
    order.push(id.into());
    Ok(())
}

struct Selection {
    roots: BTreeSet<String>,
    order: Vec<String>,
    edges: Vec<Edge>,
}

fn select(units: &[UnitSpec], plan: &Plan, targets: &[Target]) -> Result<Selection, String> {
    let map = unit_map(units)?;
    for planned in plan.units() {
        if !map.contains_key(planned.as_str()) {
            return Err(format!("plan names unknown unit {planned}"));
        }
    }
    let mut roots = BTreeSet::new();
    for target in targets {
        match target {
            Target::Unit(id) => {
                if !map.contains_key(id.as_str()) || !plan.contains(id) {
                    return Err(format!("target {id} is unavailable"));
                }
                roots.insert(id.clone());
            }
            Target::All => roots.extend(plan.units().iter().cloned()),
        }
    }
    if roots.is_empty() {
        return Err("no targets selected".into());
    }
    let mut state = BTreeMap::new();
    let mut order = Vec::new();
    for root in &roots {
        visit(root, &map, plan, &mut state, &mut order)?;
    }
    let selected: BTreeSet<&str> = order.iter().map(String::as_str).collect();
    let mut edges = Vec::new();
    for id in &order {
        for input in &map[id.as_str()].inputs {
            let (producer, item, role) = match input {
                InputSpec::Item { unit, item, .. } => (unit, item, EdgeRole::Content),
                InputSpec::Reference {
                    producer: Some((unit, item)),
                    ..
                } => (unit, item, EdgeRole::Reference),
                InputSpec::File { .. } | InputSpec::Reference { producer: None, .. } => continue,
            };
            if !selected.contains(producer.as_str()) {
                return Err(format!("producer {producer} was not selected"));
            }
            edges.push(Edge {
                producer: producer.clone(),
                consumer: id.clone(),
                item: item.clone(),
                input: input.name().into(),
                role,
            });
        }
    }
    edges.sort();
    Ok(Selection {
        roots,
        order,
        edges,
    })
}

fn resolve_unit(
    unit: &UnitSpec,
    snapshot: &FrozenSnapshot,
    produced: &ProducedItems,
) -> Result<Vec<ResolvedInput>, String> {
    let mut inputs = Vec::new();
    for input in &unit.inputs {
        inputs.push(resolve_input(input, snapshot, produced)?);
    }
    inputs.sort_by(|a, b| a.spec.name().cmp(b.spec.name()));
    Ok(inputs)
}

fn signature(item: &ProducedItem) -> Vec<u8> {
    let mut files = item.files.clone();
    files.sort_by(|a, b| a.path.cmp(&b.path));
    let mut bytes = Vec::new();
    for file in files {
        bytes.extend_from_slice(&(file.bytes.len() as u64).to_be_bytes());
        bytes.extend_from_slice(&file.bytes);
    }
    bytes
}

fn reference_bytes_changed(
    unit: &UnitSpec,
    saved: &SavedResults,
    produced: &ProducedItems,
) -> bool {
    for input in &unit.inputs {
        let InputSpec::Reference {
            producer: Some((producer, item)),
            ..
        } = input
        else {
            continue;
        };
        let Some(now) = produced.get(&(producer.clone(), item.clone())) else {
            continue;
        };
        let before = saved
            .get(producer)
            .and_then(|saved_unit| saved_unit.outputs.get(item));
        if let Some(before) = before {
            if signature(now) != signature(before) {
                return true;
            }
        }
    }
    false
}

fn removal_intent(
    units: &[UnitSpec],
    plan: &Plan,
    saved: &SavedResults,
) -> BTreeMap<ItemKey, ProducedItem> {
    let map = unit_map(units).unwrap_or_default();
    let mut intent = BTreeMap::new();
    for (unit_id, saved_unit) in &saved.units {
        let declared: BTreeSet<&str> = if plan.contains(unit_id) {
            map.get(unit_id.as_str())
                .map(|unit| {
                    unit.outputs
                        .iter()
                        .map(|output| output.item.as_str())
                        .collect()
                })
                .unwrap_or_default()
        } else {
            BTreeSet::new()
        };
        for (item, produced) in &saved_unit.outputs {
            if !declared.contains(item.as_str()) {
                intent.insert((unit_id.clone(), item.clone()), produced.clone());
            }
        }
    }
    intent
}

impl BuildAdapter for FakeAdapter {
    fn execute(&mut self, request: &BuildRequest<'_>) -> Result<BuildOutcome, AdapterError> {
        let selection = select(request.units, request.plan, request.targets)
            .map_err(|message| AdapterError { message })?;
        let map = unit_map(request.units).map_err(|message| AdapterError { message })?;
        let mut produced = ProducedItems::new();
        let mut saved_after = request.saved.clone();
        let mut runs = Vec::new();
        let mut current = Vec::new();
        let mut worker_events = 0;

        for id in &selection.order {
            let unit = map[id.as_str()];
            let resolved = resolve_unit(unit, request.snapshot, &produced)
                .map_err(|message| AdapterError { message })?;
            let identity = unit_identity(request.config, unit, &resolved);
            let mut chosen = None;
            if request.store == StoreHealth::Available {
                if let Some(candidate) = request
                    .saved
                    .get(id)
                    .filter(|candidate| saved_outputs_valid(unit, &candidate.outputs))
                {
                    if candidate.identity == identity || self.fault == AdapterFault::StaleHit {
                        chosen = Some(candidate);
                    }
                }
            }
            let mut perform = chosen.is_none();
            if self.fault == AdapterFault::OverRebuild && !perform {
                perform = true;
                chosen = None;
            }
            if self.fault == AdapterFault::ReferenceBytes
                && !perform
                && reference_bytes_changed(unit, request.saved, &produced)
            {
                perform = true;
                chosen = None;
            }

            if !perform {
                let saved_unit = chosen.expect("a hit has a saved candidate");
                current.push(id.clone());
                for output in &unit.outputs {
                    let produced_item =
                        saved_unit
                            .outputs
                            .get(&output.item)
                            .ok_or_else(|| AdapterError {
                                message: format!("saved {id}/{} is incomplete", output.item),
                            })?;
                    produced.insert((id.clone(), output.item.clone()), produced_item.clone());
                }
            } else {
                let outputs = output_payloads(unit, &resolved);
                let job = self.job_request(unit, &resolved);
                let fixtures: Vec<FixtureFile> = outputs
                    .values()
                    .flat_map(|item| item.files.iter())
                    .map(|file| FixtureFile {
                        path: file.path.clone(),
                        bytes: file.bytes.clone(),
                    })
                    .collect();
                let expected: Vec<String> = fixtures.iter().map(|file| file.path.clone()).collect();
                let mut worker = MockWorker::new([MockStep {
                    expected_unit: id.to_string(),
                    result: Ok(fixtures),
                }]);
                let returned = worker.run(&job).map_err(|failure| AdapterError {
                    message: format!("worker failed on {id}: {}", failure.message),
                })?;
                if returned.files != expected {
                    return Err(AdapterError {
                        message: format!("worker returned unexpected files for {id}"),
                    });
                }
                worker_events += 1;
                runs.push(id.clone());
                for (item, produced_item) in &outputs {
                    produced.insert((id.clone(), item.clone()), produced_item.clone());
                }
                if request.store == StoreHealth::Available {
                    saved_after.insert(id.clone(), SavedUnit { identity, outputs });
                }
            }
        }

        if self.fault == AdapterFault::MissingTarget {
            if let Some(root) = selection.roots.iter().next() {
                if let Some(output) = map[root.as_str()].outputs.first() {
                    if let Some(required) = output
                        .files
                        .iter()
                        .find(|file| file.required)
                        .map(|file| file.path.clone())
                    {
                        if let Some(item) = produced.get_mut(&(root.clone(), output.item.clone())) {
                            item.files.retain(|file| file.path != required);
                        }
                    }
                }
            }
        }

        let mut requested = BTreeMap::new();
        for root in &selection.roots {
            for output in &map[root.as_str()].outputs {
                let key = (root.clone(), output.item.clone());
                if let Some(item) = produced.get(&key) {
                    requested.insert(key, item.clone());
                }
            }
        }

        Ok(BuildOutcome {
            observation: Observation {
                roots: selection.roots.into_iter().collect(),
                order: selection.order,
                edges: selection.edges,
                runs,
                current,
                requested,
                outputs: produced,
                removal_intent: removal_intent(request.units, request.plan, request.saved),
                worker_events,
            },
            saved_after,
        })
    }
}
