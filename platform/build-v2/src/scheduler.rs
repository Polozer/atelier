//! Static ready-frontier scheduling over A4 graphs and A3 identities.
//! Concrete cache/install authority and execution lifecycle belong to their existing adapters.
use crate::graph::{BuildGraph, SelectedGraph, Target};
use crate::groups::ValidatedGroup;
use crate::integrity::NonHitReason;
use crate::keys::{
    self, ImplementationIdentity, KeyContext, PreparedUnit, ProducedGroups, ProducedItems,
    SourceVersions,
};
use crate::schema::{Destination, StoredItem};
use crate::source_hashes::SourceHashCache;
use crate::validate::SourceSnapshot;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Demand {
    Stored,
    Checkout,
}

/// Runtime declarations supply only execution identity and explicit staged names.
/// `profile` groups compatible work; semantic worker options must already be keyed.
#[derive(Clone, Debug)]
pub struct Runtime {
    pub worker: ImplementationIdentity,
    pub validator: ImplementationIdentity,
    pub staged_inputs: BTreeMap<String, String>,
    pub profile: String,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Compatibility {
    pub worker_version: String,
    pub worker_digest: String,
    pub op_kind: String,
    pub op_version: String,
    pub profile: String,
}

pub struct Request<'a> {
    graph: &'a BuildGraph,
    selected: SelectedGraph,
    snapshot: &'a SourceSnapshot,
    versions: &'a SourceVersions,
    runtimes: &'a BTreeMap<String, Runtime>,
    /// Every explicit selected root must state its demand. Other units default to Stored.
    demands: &'a BTreeMap<String, Demand>,
}
impl<'a> Request<'a> {
    /// Selection and the immutable snapshot are bound together; callers cannot pair
    /// validation from another graph/snapshot with this scheduling request.
    pub fn select(
        graph: &'a BuildGraph,
        targets: &[Target],
        snapshot: &'a SourceSnapshot,
        versions: &'a SourceVersions,
        runtimes: &'a BTreeMap<String, Runtime>,
        demands: &'a BTreeMap<String, Demand>,
    ) -> Result<Self, String> {
        let selected = graph.select(targets, snapshot)?;
        for id in selected.order() {
            if !runtimes.contains_key(id) {
                return Err(format!("missing selected runtime: {id}"));
            }
        }
        Ok(Self {
            graph,
            selected,
            snapshot,
            versions,
            runtimes,
            demands,
        })
    }
    pub fn selected(&self) -> &SelectedGraph {
        &self.selected
    }
}

/// A view of backend-owned authority, not a new constructor for StoredHit/group seals.
pub struct CheckedView<'a> {
    pub key: &'a str,
    pub items: &'a [StoredItem],
    pub groups: &'a BTreeMap<String, ValidatedGroup>,
}

pub enum Lookup<C, T> {
    Current(C),
    Hit(C),
    Miss { ticket: T, reason: NonHitReason },
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Effects {
    pub staged_units: usize,
    pub installed_units: usize,
    pub receipt_writes: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Publication {
    Cached,
    NotCached(String),
}

pub struct Published<C> {
    pub checked: C,
    pub publication: Publication,
}

/// Real adapters must use existing A5/B2/B7 sealed handles as Checked/Ticket.
/// Fake test authority is a distinct type and cannot turn into production StoredHit.
/// Publication must validate/freeze/root per unit; failure never erases earlier results.
pub trait Backend {
    type Checked;
    type Ticket;
    type Completion;

    fn lookup(
        &mut self,
        unit: &PreparedUnit,
        demand: Demand,
    ) -> Result<Lookup<Self::Checked, Self::Ticket>, String>;
    fn view<'a>(&'a self, checked: &'a Self::Checked) -> CheckedView<'a>;
    /// Move sealed outputs into the scheduling identity context; tokens are never cloned or deserialized here.
    fn into_outputs(
        &mut self,
        checked: Self::Checked,
    ) -> (Vec<StoredItem>, BTreeMap<String, ValidatedGroup>);
    fn publish(
        &mut self,
        work: Work<Self::Ticket>,
        completion: Self::Completion,
    ) -> Result<Published<Self::Checked>, String>;
    /// Apply only this explicit demand and retain required roots/claims through existing APIs.
    /// Current must not rewrite output/receipt/index files. Stored never installs checkout files.
    fn settle(
        &mut self,
        unit: &PreparedUnit,
        checked: &mut Self::Checked,
        demand: Demand,
    ) -> Result<Effects, String>;
}

/// An original lookup ticket bound by the scheduler to one exact prepared unit.
/// Only this module constructs work; executors return the same owned handle in their event.
pub struct Work<T> {
    unit: String,
    prepared: PreparedUnit,
    ticket: T,
    compatibility: Compatibility,
}
impl<T> Work<T> {
    pub fn unit(&self) -> &str {
        &self.unit
    }
    pub fn prepared(&self) -> &PreparedUnit {
        &self.prepared
    }
    pub fn ticket(&self) -> &T {
        &self.ticket
    }
    pub fn ticket_mut(&mut self) -> &mut T {
        &mut self.ticket
    }
    pub fn compatibility(&self) -> &Compatibility {
        &self.compatibility
    }
    pub fn into_ticket(self) -> T {
        self.ticket
    }
}

pub enum Event<T, C> {
    Completed {
        work: Work<T>,
        completion: C,
        effects: Effects,
    },
    Failed {
        work: Work<T>,
        reason: String,
    },
    Cancelled {
        work: Work<T>,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Flow {
    Continue,
    Stop,
}

pub trait Control {
    fn cancelled(&self) -> bool;
}

/// Admission, worker sessions, retries, deadlines and cleanup belong to C5/C7.
/// Every submitted handle MUST return one terminal event, including queued cancellation.
/// Flow::Stop forbids starting more work; it does not waive settlement of owned handles.
/// A returned error or omitted outcome does not certify cleanup; scheduling stops with unresolved work blocked.
pub trait Executor<T, C> {
    fn batch(
        &mut self,
        work: Vec<Work<T>>,
        control: &dyn Control,
        emit: &mut dyn FnMut(Event<T, C>) -> Flow,
    ) -> Result<(), String>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum State {
    Waiting,
    Miss(NonHitReason),
    Current,
    Hit,
    Executed(Publication),
    Failed(String),
    Blocked(Vec<String>),
    Cancelled,
}
impl State {
    fn resolved(&self) -> bool {
        matches!(self, Self::Current | Self::Hit | Self::Executed(_))
    }
    fn unsuccessful(&self) -> bool {
        matches!(self, Self::Failed(_) | Self::Blocked(_) | Self::Cancelled)
    }
}

#[derive(Default)]
pub struct Report {
    pub states: BTreeMap<String, State>,
    pub keys: BTreeMap<String, String>,
    pub lookups: Vec<String>,
    pub batches: Vec<Vec<String>>,
    pub publications: Vec<String>,
    pub effects: Effects,
    pub fatal: Option<String>,
}

fn demand(request: &Request<'_>, unit: &str) -> Demand {
    request.demands.get(unit).copied().unwrap_or(Demand::Stored)
}

fn integrate<B: Backend>(
    backend: &mut B,
    unit_id: &str,
    prepared: &PreparedUnit,
    mut checked: B::Checked,
    requested: Demand,
    current: bool,
    items: &mut ProducedItems,
    groups: &mut ProducedGroups,
    report: &mut Report,
) -> Result<(), String> {
    let view = backend.view(&checked);
    if view.key != prepared.key() {
        return Err("backend returned authority for another prepared key".into());
    }
    // Borrowed metadata is copied only after the backend's exact-key check. The concrete
    // adapter, not raw deserialization here, owns manifest/projection validation and pins.
    let effects = backend.settle(prepared, &mut checked, requested)?;
    if current && (effects.installed_units != 0 || effects.receipt_writes != 0) {
        return Err("Current settlement unexpectedly rewrote checkout state".into());
    }
    if requested == Demand::Stored && effects.installed_units != 0 {
        return Err("Stored demand unexpectedly installed checkout files".into());
    }
    report.effects.staged_units += effects.staged_units;
    report.effects.installed_units += effects.installed_units;
    report.effects.receipt_writes += effects.receipt_writes;
    let view = backend.view(&checked);
    if view.key != prepared.key() {
        return Err("settlement changed prepared-key authority".into());
    }
    let (owned_items, owned_groups) = backend.into_outputs(checked);
    for item in owned_items {
        items.insert((unit_id.into(), item.item.id.clone()), item);
    }
    for (id, group) in owned_groups {
        groups.insert((unit_id.into(), id.clone()), group);
    }
    Ok(())
}

/// @cc [owner:fontanierh,label:correctness] static-frontier-lookup-before-dispatch
/// Scheduling MUST use A4 membership/order and A3 exact output-content identities, never
/// upstream input keys. Every currently ready lookup MUST finish before any miss is sent
/// to an executor; only compatible misses share a batch. Original miss tickets MUST be
/// preserved, and each completion MUST publish independently before downstream preparation.
/// Current/hit units MUST not launch jobs. Failure/cancellation MUST retain prior publication.
/// See tests/scheduler.rs; real lifecycle, dynamic targets and A6 integration remain pending.
pub fn run<B: Backend, E: Executor<B::Ticket, B::Completion>>(
    request: Request<'_>,
    backend: &mut B,
    executor: &mut E,
    control: &dyn Control,
    hashes: &mut SourceHashCache,
) -> Result<Report, String> {
    let membership: BTreeSet<_> = request.selected.order().iter().cloned().collect();
    if !request
        .selected
        .roots()
        .iter()
        .all(|id| request.demands.contains_key(id))
        || !request.demands.keys().all(|id| membership.contains(id))
    {
        return Err("explicit root demands must belong to the selected graph".into());
    }
    for (id, mode) in request.demands {
        if *mode == Demand::Checkout
            && !request
                .graph
                .unit(id)
                .unwrap()
                .outputs
                .iter()
                .any(|item| item.destination == Destination::Checkout)
        {
            return Err(format!(
                "Checkout demand has no declared checkout item: {id}"
            ));
        }
    }
    let mut parents: BTreeMap<String, BTreeSet<String>> = membership
        .iter()
        .map(|id| (id.clone(), BTreeSet::new()))
        .collect();
    for edge in request.selected.dependencies() {
        parents
            .get_mut(&edge.consumer)
            .unwrap()
            .insert(edge.producer.clone());
    }
    let mut report = Report {
        states: membership
            .iter()
            .map(|id| (id.clone(), State::Waiting))
            .collect(),
        ..Report::default()
    };
    let mut items = ProducedItems::new();
    let mut groups = ProducedGroups::new();
    // Undispatched misses keep their original lookup tickets while new ready hits resolve.
    let mut pending = Vec::new();
    loop {
        // Follow hit-unlocked frontiers to a fixed point before dispatching accumulated misses.
        loop {
            let mut progress = false;
            for id in request.selected.order() {
                if report.states[id] != State::Waiting {
                    continue;
                }
                let failed: Vec<_> = parents[id]
                    .iter()
                    .filter(|p| report.states[*p].unsuccessful())
                    .cloned()
                    .collect();
                if !failed.is_empty() {
                    report.states.insert(id.clone(), State::Blocked(failed));
                    progress = true;
                    continue;
                }
                if control.cancelled() {
                    report.states.insert(id.clone(), State::Cancelled);
                    progress = true;
                    continue;
                }
                if !parents[id].iter().all(|p| report.states[p].resolved()) {
                    continue;
                }
                progress = true;
                let unit = request
                    .graph
                    .unit(id)
                    .ok_or("selected unit missing from graph")?;
                let runtime = request
                    .runtimes
                    .get(id)
                    .ok_or_else(|| format!("missing selected runtime: {id}"))?;
                let prepared = match keys::prepare(
                    request.graph.declaration(),
                    request.selected.validation(),
                    id,
                    &KeyContext {
                        snapshot: request.snapshot,
                        versions: request.versions,
                        produced: &items,
                        produced_groups: &groups,
                        staged_inputs: &runtime.staged_inputs,
                        worker: &runtime.worker,
                        validator: &runtime.validator,
                    },
                    hashes,
                ) {
                    Ok(prepared) => prepared,
                    Err(error) => {
                        report.states.insert(id.clone(), State::Failed(error));
                        continue;
                    }
                };
                report.keys.insert(id.clone(), prepared.key().into());
                report.lookups.push(id.clone());
                let mode = demand(&request, id);
                match backend.lookup(&prepared, mode) {
                    Ok(reused @ (Lookup::Current(_) | Lookup::Hit(_))) => {
                        // Retain the distinction without asking the backend to look up twice.
                        let (checked, state) = match reused {
                            Lookup::Current(checked) => (checked, State::Current),
                            Lookup::Hit(checked) => (checked, State::Hit),
                            Lookup::Miss { .. } => unreachable!(),
                        };
                        let result = integrate(
                            backend,
                            id,
                            &prepared,
                            checked,
                            mode,
                            state == State::Current,
                            &mut items,
                            &mut groups,
                            &mut report,
                        );
                        match result {
                            Ok(()) => {
                                report.states.insert(id.clone(), state);
                            }
                            Err(error) => {
                                report.states.insert(id.clone(), State::Failed(error));
                            }
                        }
                    }
                    Ok(Lookup::Miss { ticket, reason }) => {
                        report.states.insert(id.clone(), State::Miss(reason));
                        pending.push(Work {
                            unit: id.clone(),
                            prepared,
                            ticket,
                            compatibility: Compatibility {
                                worker_version: runtime.worker.version.clone(),
                                worker_digest: runtime.worker.digest.clone(),
                                op_kind: unit.op.kind.clone(),
                                op_version: unit.op.version.clone(),
                                profile: runtime.profile.clone(),
                            },
                        });
                    }
                    Err(error) => {
                        report.states.insert(id.clone(), State::Failed(error));
                    }
                }
            }
            if !progress {
                break;
            }
        }
        if pending.is_empty() {
            break;
        }
        let mut batches: BTreeMap<Compatibility, Vec<Work<B::Ticket>>> = BTreeMap::new();
        for work in pending.drain(..) {
            batches
                .entry(work.compatibility.clone())
                .or_default()
                .push(work);
        }
        // Submit one compatibility batch, then refresh the ready frontier before the next.
        // A completed producer may unlock a hit that must not wait behind unrelated work.
        if let Some((_, batch)) = batches.pop_first() {
            pending.extend(batches.into_values().flatten());
            if control.cancelled() {
                for work in batch {
                    report.states.insert(work.unit, State::Cancelled);
                }
                continue;
            }
            report
                .batches
                .push(batch.iter().map(|work| work.unit.clone()).collect());
            let mut expected: BTreeMap<_, _> = batch
                .iter()
                .map(|work| (work.unit.clone(), work.prepared.key().to_string()))
                .collect();
            let executed = executor.batch(batch, control, &mut |event| {
                let work = match &event {
                    Event::Completed { work, .. }
                    | Event::Failed { work, .. }
                    | Event::Cancelled { work } => work,
                };
                if expected.remove(&work.unit).as_deref() != Some(work.prepared.key()) {
                    report.fatal = Some("executor returned unexpected or duplicate work".into());
                    return Flow::Stop;
                }
                match event {
                    Event::Completed {
                        work,
                        completion,
                        effects,
                    } => {
                        let id = work.unit.clone();
                        let prepared = work.prepared.clone();
                        match backend.publish(work, completion) {
                            Ok(published) => match integrate(
                                backend,
                                &id,
                                &prepared,
                                published.checked,
                                demand(&request, &id),
                                false,
                                &mut items,
                                &mut groups,
                                &mut report,
                            ) {
                                Ok(()) => {
                                    report.publications.push(id.clone());
                                    report
                                        .states
                                        .insert(id, State::Executed(published.publication));
                                }
                                Err(error) => {
                                    report.states.insert(id, State::Failed(error));
                                }
                            },
                            Err(error) => {
                                report.states.insert(id, State::Failed(error));
                            }
                        }
                        report.effects.staged_units += effects.staged_units;
                    }
                    Event::Failed { work, reason } => {
                        report.states.insert(work.unit, State::Failed(reason));
                    }
                    Event::Cancelled { work } => {
                        report.states.insert(work.unit, State::Cancelled);
                    }
                }
                if control.cancelled() || report.fatal.is_some() {
                    Flow::Stop
                } else {
                    Flow::Continue
                }
            });
            if let Err(error) = executed {
                report.fatal = Some(error);
            }
            if !expected.is_empty() {
                report.fatal.get_or_insert_with(|| {
                    "executor omitted terminal outcome; cleanup unresolved".into()
                });
            }
            for (id, _) in expected {
                report.states.insert(
                    id,
                    State::Failed("executor omitted terminal outcome".into()),
                );
            }
            if report.fatal.is_some() {
                break;
            }
        }
        if report.fatal.is_some() {
            break;
        }
    }
    if report.fatal.is_some() {
        for state in report.states.values_mut() {
            if *state == State::Waiting || matches!(state, State::Miss(_)) {
                *state = State::Blocked(vec!["executor lifecycle unresolved".into()]);
            }
        }
    }
    Ok(report)
}
