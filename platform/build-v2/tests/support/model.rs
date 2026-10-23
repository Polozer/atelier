//! Independent expectation model for the harness.
//!
//! Selection, ordering, identity comparison, hit/miss and output cutoff are decided here from
//! harness data only. No production selection, identity, store or plan code participates.
use crate::support::snapshot::FrozenSnapshot;
use crate::support::spec::{
    Edge, EdgeRole, HarnessConfig, InputSpec, ItemKey, Plan, SavedResults, SavedUnit, StoreHealth,
    Target, UnitSpec,
};
use crate::support::work::{
    ProducedItem, ProducedItems, ResolvedInput, output_payloads, resolve_input,
    saved_outputs_valid, unit_identity,
};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Expectation {
    pub roots: Vec<String>,
    pub order: Vec<String>,
    pub edges: Vec<Edge>,
    pub runs: Vec<String>,
    pub current: Vec<String>,
    pub requested: BTreeMap<ItemKey, ProducedItem>,
    pub outputs: BTreeMap<ItemKey, ProducedItem>,
    pub removal_intent: BTreeMap<ItemKey, ProducedItem>,
    pub worker_events: usize,
    pub saved_after: SavedResults,
}

struct Selection {
    roots: BTreeSet<String>,
    order: Vec<String>,
    edges: Vec<Edge>,
}

fn unit_map<'a>(units: &'a [UnitSpec]) -> Result<BTreeMap<&'a str, &'a UnitSpec>, String> {
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
                producer: Some((producer, item)),
                ..
            } => found.push((producer.as_str(), item.as_str())),
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
        if !units.contains_key(producer) {
            return Err(format!("unit {id} names unknown producer {producer}"));
        }
        if !plan.contains(producer) {
            return Err(format!(
                "unit {id} needs {producer}, which is not in the plan"
            ));
        }
        visit(producer, units, plan, state, order)?;
    }
    state.insert(id.into(), 2);
    order.push(id.into());
    Ok(())
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
                if !map.contains_key(id.as_str()) {
                    return Err(format!("target names unknown unit {id}"));
                }
                if !plan.contains(id) {
                    return Err(format!("target {id} is not in the plan"));
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
        let unit = map[id.as_str()];
        for input in &unit.inputs {
            let (producer, item, role) = match input {
                InputSpec::Item { unit, item, .. } => (unit, item, EdgeRole::Content),
                InputSpec::Reference {
                    producer: Some((producer, item)),
                    ..
                } => (producer, item, EdgeRole::Reference),
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
        inputs.push(
            resolve_input(input, snapshot, produced)
                .map_err(|error| format!("unit {}: {error}", unit.id))?,
        );
    }
    inputs.sort_by(|a, b| a.spec.name().cmp(b.spec.name()));
    Ok(inputs)
}

pub fn removal_intent(
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

#[allow(clippy::too_many_arguments)]
pub fn expect(
    config: &HarnessConfig,
    units: &[UnitSpec],
    plan: &Plan,
    targets: &[Target],
    snapshot: &FrozenSnapshot,
    saved: &SavedResults,
    store: StoreHealth,
) -> Result<Expectation, String> {
    let selection = select(units, plan, targets)?;
    let map = unit_map(units)?;
    let mut produced = ProducedItems::new();
    let mut runs = Vec::new();
    let mut current = Vec::new();
    let mut saved_after = saved.clone();

    for id in &selection.order {
        let unit = map[id.as_str()];
        let resolved = resolve_unit(unit, snapshot, &produced)?;
        let identity = unit_identity(config, unit, &resolved);
        let hit = match store {
            StoreHealth::Available => saved.get(id).filter(|candidate| {
                candidate.identity == identity && saved_outputs_valid(unit, &candidate.outputs)
            }),
            StoreHealth::Failing => None,
        };
        if let Some(saved_unit) = hit {
            current.push(id.clone());
            for output in &unit.outputs {
                let produced_item = saved_unit
                    .outputs
                    .get(&output.item)
                    .ok_or_else(|| format!("saved {id}/{} is incomplete", output.item))?;
                produced.insert((id.clone(), output.item.clone()), produced_item.clone());
            }
        } else {
            runs.push(id.clone());
            let outputs = output_payloads(unit, &resolved);
            for (item, produced_item) in &outputs {
                produced.insert((id.clone(), item.clone()), produced_item.clone());
            }
            if store == StoreHealth::Available {
                saved_after.insert(id.clone(), SavedUnit { identity, outputs });
            }
        }
    }

    let mut requested = BTreeMap::new();
    for root in &selection.roots {
        let unit = map[root.as_str()];
        for output in &unit.outputs {
            let key = (root.clone(), output.item.clone());
            let produced_item = produced
                .get(&key)
                .ok_or_else(|| format!("target {root}/{} produced nothing", output.item))?;
            requested.insert(key, produced_item.clone());
        }
    }

    let worker_events = runs.len();
    Ok(Expectation {
        roots: selection.roots.into_iter().collect(),
        order: selection.order,
        edges: selection.edges,
        runs,
        current,
        requested,
        removal_intent: removal_intent(units, plan, saved),
        outputs: produced,
        worker_events,
        saved_after,
    })
}
