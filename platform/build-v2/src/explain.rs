//! Observations for future CLI callers. Reporting never reads sources, payloads or cache paths.
//! Scheduling labels are diagnostic; every semantic comparison uses A3's original ingredients.
use crate::groups::ValidatedGroup;
use crate::integrity::NonHitReason;
use crate::keys::{PreparedUnit, canonical_bytes};
use crate::scheduler::{
    self, Backend, CheckedView, Control, Effects, Event, Executor, FinalDemands, Flow,
    InputFailure, Lookup, Publication, Published, Report, StagedInputs, State, Work,
};
use crate::schema::{IdentityIngredients, StoredItem};
use crate::source_hashes::sha256;
use serde::Serialize;
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IngredientCategory {
    CacheVersion,
    Op,
    Entrypoint,
    Code,
    Worker,
    Validator,
    Parameter,
    Content,
    Reference,
    StagedPath,
    InputKind,
    OutputContract,
    GroupContract,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct IngredientChange {
    pub category: IngredientCategory,
    /// Declared code path or slot name only; never its value, bytes or locator.
    pub slot: Option<String>,
}

/// Compact diagnostic fingerprints, not keys or result authority. No original values are retained.
#[derive(Clone, Debug, Default)]
pub struct IngredientSnapshot(BTreeMap<IngredientChange, String>);
impl IngredientSnapshot {
    /// @cc [owner:fontanierh,label:correctness] explain-original-ingredients
    /// Fingerprints MUST use A3 canonical ingredient values, without source reads, producer input
    /// keys or provenance/platform additions. Reports MUST expose category/slot differences only,
    /// never original parameter/reference values. Missing baselines MUST NOT imply a changed input.
    /// See tests/explain.rs ingredient_differences_are_semantic_redacted_and_label_independent.
    pub fn capture(ingredients: &IdentityIngredients) -> Result<Self, String> {
        let mut result = Self::default();
        let mut add = |category, slot, bytes: Result<Vec<u8>, String>| -> Result<(), String> {
            result
                .0
                .insert(IngredientChange { category, slot }, sha256(&bytes?));
            Ok(())
        };
        use IngredientCategory::*;
        add(
            CacheVersion,
            None,
            canonical_bytes(&ingredients.cache_version),
        )?;
        add(Op, None, canonical_bytes(&ingredients.op))?;
        add(Entrypoint, None, canonical_bytes(&ingredients.script))?;
        add(
            Worker,
            None,
            canonical_bytes(&(&ingredients.worker_version, &ingredients.worker_digest)),
        )?;
        add(
            Validator,
            None,
            canonical_bytes(&(
                &ingredients.validator_version,
                &ingredients.validator_digest,
            )),
        )?;
        for (slot, value) in &ingredients.code {
            add(Code, Some(slot.clone()), canonical_bytes(value))?;
        }
        for (slot, value) in &ingredients.params {
            add(Parameter, Some(slot.clone()), canonical_bytes(value))?;
        }
        for (slot, value) in &ingredients.content {
            add(Content, Some(slot.clone()), canonical_bytes(value))?;
        }
        for (slot, value) in &ingredients.references {
            add(Reference, Some(slot.clone()), canonical_bytes(value))?;
        }
        for (slot, value) in &ingredients.staged_inputs {
            add(StagedPath, Some(slot.clone()), canonical_bytes(value))?;
        }
        for (slot, value) in &ingredients.input_kinds {
            add(InputKind, Some(slot.clone()), canonical_bytes(value))?;
        }
        add(
            OutputContract,
            None,
            canonical_bytes(&ingredients.logical_outputs),
        )?;
        add(
            GroupContract,
            None,
            canonical_bytes(&ingredients.output_groups),
        )?;
        Ok(result)
    }

    pub fn changes_from(&self, previous: &Self) -> Vec<IngredientChange> {
        self.0
            .keys()
            .chain(previous.0.keys())
            .cloned()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .filter(|key| self.0.get(key) != previous.0.get(key))
            .collect()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MissReason {
    MissingRecord,
    MissingObject,
    CorruptRecord,
    CorruptObject,
    MalformedRecord,
    MalformedObject,
    IncompleteManifest,
    UnsupportedRecord,
    ExternalUnverified,
    UnverifiedSample,
    StoreFailure,
}
impl From<&NonHitReason> for MissReason {
    fn from(value: &NonHitReason) -> Self {
        match value {
            NonHitReason::MissingRecord => Self::MissingRecord,
            NonHitReason::MissingObject => Self::MissingObject,
            NonHitReason::CorruptRecord => Self::CorruptRecord,
            NonHitReason::CorruptObject => Self::CorruptObject,
            NonHitReason::MalformedRecord => Self::MalformedRecord,
            NonHitReason::MalformedObject => Self::MalformedObject,
            NonHitReason::IncompleteManifest => Self::IncompleteManifest,
            NonHitReason::UnsupportedRecord => Self::UnsupportedRecord,
            NonHitReason::ExternalUnverified => Self::ExternalUnverified,
            NonHitReason::UnverifiedSample => Self::UnverifiedSample,
            NonHitReason::StoreFailure => Self::StoreFailure,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case", tag = "kind", content = "reason")]
pub enum LookupReason {
    IdentityOnly,
    Current,
    StoredHit,
    Miss(MissReason),
    Refused,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Waiting,
    IdentityOnly,
    Current,
    StoredHit,
    Executed,
    Failed,
    SourceUnavailable,
    SourceChanged,
    InvalidInputs,
    Blocked,
    Cancelled,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CacheOutcome {
    Cached,
    NotCached,
    AttemptedUnknown,
}

#[derive(Clone, Debug, Default)]
struct Observation {
    key: Option<String>,
    ingredients: Option<IngredientSnapshot>,
    lookup: Option<LookupReason>,
    completed: usize,
    terminal: usize,
    publication: Option<CacheOutcome>,
    effects: Effects,
    staged: usize,
    settlement_unknown: bool,
}

/// Shared only by observers for one scheduler invocation. Owns no execution capabilities.
#[derive(Clone, Default)]
pub struct Recorder(Rc<RefCell<BTreeMap<String, Observation>>>);

#[derive(Clone, Debug, Serialize)]
pub struct UnitExplanation {
    pub unit: String,
    pub key: Option<String>,
    pub outcome: Outcome,
    pub lookup: Option<LookupReason>,
    /// None means no supplied previous observation; Some(empty) means unchanged ingredients.
    pub ingredient_changes: Option<Vec<IngredientChange>>,
    pub submitted: usize,
    /// Worker identities seen in actual lifecycle attempts, including retries; not successful Runs.
    pub launched_attempts: Option<usize>,
    pub completed: usize,
    pub publication: Option<CacheOutcome>,
    pub restored: bool,
    pub installed_units: usize,
    pub receipt_writes: usize,
    /// False after a settlement error: counts retain confirmed effects, not a claim of no writes.
    pub effects_complete: bool,
    pub unsatisfied_stored: bool,
    pub unsatisfied_checkout: bool,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct SummaryCounts {
    pub identity_only: usize,
    pub current: usize,
    pub stored_hits: usize,
    pub submitted: usize,
    pub launched_attempts: Option<usize>,
    pub worker_completed: usize,
    pub cached: usize,
    pub not_cached: usize,
    pub publication_unknown: usize,
    pub restored: usize,
    pub installed_units: usize,
    pub receipt_writes: usize,
    pub failed: usize,
    pub blocked: usize,
    pub cancelled: usize,
    pub unsatisfied_units: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct BuildSummary {
    pub units: Vec<UnitExplanation>,
    pub counts: SummaryCounts,
    /// Lifecycle uncertainty is distinct from ordinary per-unit failure. Error text is not copied.
    pub lifecycle_unresolved: bool,
    pub effects_complete: bool,
}

impl Recorder {
    pub fn backend<'a, B>(&self, inner: &'a mut B) -> ObservedBackend<'a, B> {
        ObservedBackend {
            inner,
            recorder: self.clone(),
        }
    }
    pub fn executor<'a, E>(&self, inner: &'a mut E) -> ObservedExecutor<'a, E> {
        ObservedExecutor {
            inner,
            recorder: self.clone(),
        }
    }
    /// Save only compact semantic fingerprints for an explicitly chosen future comparison.
    /// Caller matches observations by its stable logical owner; unit labels are not identities.
    pub fn ingredients(&self) -> BTreeMap<String, IngredientSnapshot> {
        self.0
            .borrow()
            .iter()
            .filter_map(|(id, observation)| {
                observation
                    .ingredients
                    .clone()
                    .map(|value| (id.clone(), value))
            })
            .collect()
    }

    /// @cc [owner:fontanierh,label:correctness] explain-counts-are-observed-effects
    /// Summary MUST distinguish identity-only resolution, hit, actual restore, submission, actual
    /// launch evidence, completion and publication. Publication success MUST survive later failure.
    /// Missing records/blobs MUST NOT be called evicted. A report MUST NOT copy free-form errors,
    /// params or environment values. No extra lookup, materialization, tree walk or hash is allowed.
    /// See tests/explain.rs and A7 assertions in python_backend::tests (MAC1 pending).
    pub fn summarize(
        &self,
        report: &Report,
        previous: &BTreeMap<String, IngredientSnapshot>,
        launches: Option<&BTreeMap<String, usize>>,
    ) -> Result<BuildSummary, String> {
        let observations = self.0.borrow();
        if observations
            .keys()
            .any(|id| !report.states.contains_key(id))
        {
            return Err("observer contains units outside scheduler report".into());
        }
        let submitted: BTreeMap<String, usize> =
            report
                .batches
                .iter()
                .flatten()
                .fold(BTreeMap::new(), |mut counts, id| {
                    *counts.entry(id.clone()).or_default() += 1;
                    counts
                });
        if launches.is_some_and(|launches| launches.keys().any(|id| !submitted.contains_key(id))) {
            return Err("launch evidence names an unsubmitted unit".into());
        }
        let mut summary = BuildSummary {
            units: vec![],
            counts: SummaryCounts::default(),
            lifecycle_unresolved: report.fatal.is_some(),
            effects_complete: true,
        };
        summary.counts.launched_attempts = launches.and_then(|map| {
            submitted
                .keys()
                .all(|id| map.contains_key(id))
                .then(|| map.values().sum())
        });
        let mut observed_effects = Effects::default();
        for (id, state) in &report.states {
            let empty = Observation::default();
            let observation = observations.get(id).unwrap_or(&empty);
            if observation.key.as_ref() != report.keys.get(id) {
                return Err("observer and scheduler prepared keys disagree".into());
            }
            let sent = submitted.get(id).copied().unwrap_or(0);
            if observation.terminal > sent || observation.completed > observation.terminal {
                return Err("observer has duplicate or unsubmitted terminal outcomes".into());
            }
            let outcome = match state {
                State::Waiting | State::Miss(_) => Outcome::Waiting,
                State::Identity => Outcome::IdentityOnly,
                State::Current => Outcome::Current,
                State::Hit => Outcome::StoredHit,
                State::Executed(_) => Outcome::Executed,
                State::Failed(_) => Outcome::Failed,
                State::InputRefused(InputFailure::Unavailable(_)) => Outcome::SourceUnavailable,
                State::InputRefused(InputFailure::Changed(_)) => Outcome::SourceChanged,
                State::InputRefused(InputFailure::Invalid(_)) => Outcome::InvalidInputs,
                State::Blocked(_) => Outcome::Blocked,
                State::Cancelled => Outcome::Cancelled,
            };
            let restored = observation.lookup == Some(LookupReason::StoredHit)
                && observation.effects.installed_units > 0;
            let counts = &mut summary.counts;
            counts.identity_only += usize::from(outcome == Outcome::IdentityOnly);
            counts.current += usize::from(outcome == Outcome::Current);
            counts.stored_hits += usize::from(observation.lookup == Some(LookupReason::StoredHit));
            counts.submitted += sent;
            counts.worker_completed += observation.completed;
            counts.cached += usize::from(observation.publication == Some(CacheOutcome::Cached));
            counts.not_cached +=
                usize::from(observation.publication == Some(CacheOutcome::NotCached));
            counts.publication_unknown +=
                usize::from(observation.publication == Some(CacheOutcome::AttemptedUnknown));
            summary.effects_complete &= !observation.settlement_unknown;
            counts.restored += usize::from(restored);
            counts.installed_units += observation.effects.installed_units;
            counts.receipt_writes += observation.effects.receipt_writes;
            counts.failed += usize::from(matches!(
                outcome,
                Outcome::Failed
                    | Outcome::SourceUnavailable
                    | Outcome::SourceChanged
                    | Outcome::InvalidInputs
            ));
            counts.blocked += usize::from(outcome == Outcome::Blocked);
            counts.cancelled += usize::from(outcome == Outcome::Cancelled);
            counts.unsatisfied_units += usize::from(report.unsatisfied.contains_key(id));
            observed_effects.staged_units += observation.staged;
            observed_effects.installed_units += observation.effects.installed_units;
            observed_effects.receipt_writes += observation.effects.receipt_writes;
            summary.units.push(UnitExplanation {
                unit: id.clone(),
                key: observation.key.clone(),
                outcome,
                lookup: observation.lookup.clone(),
                ingredient_changes: previous.get(id).and_then(|old| {
                    observation
                        .ingredients
                        .as_ref()
                        .map(|current| current.changes_from(old))
                }),
                submitted: sent,
                launched_attempts: launches.and_then(|map| {
                    if sent == 0 {
                        Some(0)
                    } else {
                        map.get(id).copied()
                    }
                }),
                completed: observation.completed,
                publication: observation.publication.clone(),
                restored,
                installed_units: observation.effects.installed_units,
                receipt_writes: observation.effects.receipt_writes,
                effects_complete: !observation.settlement_unknown,
                unsatisfied_stored: report
                    .unsatisfied
                    .get(id)
                    .is_some_and(|demands| demands.contains(&scheduler::Demand::Stored)),
                unsatisfied_checkout: report
                    .unsatisfied
                    .get(id)
                    .is_some_and(|demands| demands.contains(&scheduler::Demand::Checkout)),
            });
        }
        if observed_effects != report.effects {
            return Err("observer and scheduler settlement/staging effects disagree".into());
        }
        for id in &report.publications {
            if !observations.get(id).is_some_and(|value| {
                matches!(
                    value.publication,
                    Some(CacheOutcome::Cached | CacheOutcome::NotCached)
                )
            }) {
                return Err("scheduler publication lacks observed backend success".into());
            }
        }
        Ok(summary)
    }
}

pub struct ObservedBackend<'a, B> {
    pub inner: &'a mut B,
    recorder: Recorder,
}
impl<B: Backend> Backend for ObservedBackend<'_, B> {
    type Checked = B::Checked;
    type Ticket = B::Ticket;
    type Inputs = B::Inputs;
    type Completion = B::Completion;
    fn lookup(
        &mut self,
        unit: &PreparedUnit,
        demand: &FinalDemands,
    ) -> Result<Lookup<Self::Checked, Self::Ticket>, String> {
        let id = unit.request("", "").unit;
        let result = self.inner.lookup(unit, demand);
        let mut observations = self.recorder.0.borrow_mut();
        let observation = observations.entry(id).or_default();
        observation.key = Some(unit.key().into());
        observation.ingredients = IngredientSnapshot::capture(unit.ingredients()).ok();
        observation.lookup = Some(match &result {
            Ok(Lookup::Recorded(_)) => LookupReason::IdentityOnly,
            Ok(Lookup::Current(_)) => LookupReason::Current,
            Ok(Lookup::Hit(_)) => LookupReason::StoredHit,
            Ok(Lookup::Miss { reason, .. }) => LookupReason::Miss(reason.into()),
            Err(_) => LookupReason::Refused,
        });
        result
    }
    fn view<'a>(&'a self, checked: &'a Self::Checked) -> CheckedView<'a> {
        self.inner.view(checked)
    }
    fn prepare_inputs(
        &mut self,
        unit: &PreparedUnit,
        ticket: &mut Self::Ticket,
    ) -> Result<StagedInputs<Self::Inputs>, InputFailure> {
        let result = self.inner.prepare_inputs(unit, ticket);
        if let Ok(staged) = &result {
            self.recorder
                .0
                .borrow_mut()
                .entry(unit.request("", "").unit)
                .or_default()
                .staged += staged.staged_units;
        }
        result
    }
    fn into_outputs(
        &mut self,
        checked: Self::Checked,
    ) -> (Vec<StoredItem>, BTreeMap<String, ValidatedGroup>) {
        self.inner.into_outputs(checked)
    }
    fn publish(
        &mut self,
        work: Work<Self::Ticket, Self::Inputs>,
        completion: Self::Completion,
    ) -> Result<Published<Self::Checked>, String> {
        let id = work.unit().to_string();
        let result = self.inner.publish(work, completion);
        self.recorder
            .0
            .borrow_mut()
            .entry(id)
            .or_default()
            .publication = Some(match &result {
            Ok(published) => match &published.publication {
                Publication::Cached => CacheOutcome::Cached,
                Publication::NotCached(_) => CacheOutcome::NotCached,
            },
            Err(_) => CacheOutcome::AttemptedUnknown,
        });
        result
    }
    fn settle(
        &mut self,
        unit: &PreparedUnit,
        checked: &mut Self::Checked,
        demand: &FinalDemands,
    ) -> Result<Effects, String> {
        let result = self.inner.settle(unit, checked, demand);
        {
            let mut observations = self.recorder.0.borrow_mut();
            let observation = observations.entry(unit.request("", "").unit).or_default();
            match &result {
                Ok(effects) => observation.effects = *effects,
                Err(_) => observation.settlement_unknown = true,
            }
        }
        result
    }
}

pub struct ObservedExecutor<'a, E> {
    pub inner: &'a mut E,
    recorder: Recorder,
}
impl<T, I, C, E: Executor<T, I, C>> Executor<T, I, C> for ObservedExecutor<'_, E> {
    fn batch(
        &mut self,
        work: Vec<Work<T, I>>,
        control: &dyn Control,
        emit: &mut dyn FnMut(Event<T, I, C>) -> Flow,
    ) -> Result<(), String> {
        self.inner.batch(work, control, &mut |event| {
            let (id, completed) = match &event {
                Event::Completed { work, .. } => (work.unit(), true),
                Event::Failed { work, .. } | Event::Cancelled { work } => (work.unit(), false),
            };
            {
                let mut observations = self.recorder.0.borrow_mut();
                let observation = observations.entry(id.into()).or_default();
                observation.terminal += 1;
                observation.completed += usize::from(completed);
            }
            emit(event)
        })
    }
}
