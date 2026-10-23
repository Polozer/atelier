//! Three-way checks, clean-rebuild oracle and reproduction reporting.
use crate::support::adapter::{BuildAdapter, BuildRequest, Observation};
use crate::support::model::{self, Expectation};
use crate::support::snapshot::FrozenSnapshot;
use crate::support::spec::{
    Edge, HarnessConfig, Plan, SavedResults, StoreHealth, Target, UnitSpec,
};
use std::collections::BTreeSet;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Step {
    pub note: String,
    pub units: Vec<UnitSpec>,
    pub snapshot: FrozenSnapshot,
    pub plan: Plan,
    pub targets: Vec<Target>,
    pub store: StoreHealth,
    /// Hand-written expectation; seeded sequences leave this empty for the model to derive.
    pub expected_runs: Option<BTreeSet<String>>,
}

impl Step {
    pub fn new(
        note: impl Into<String>,
        units: Vec<UnitSpec>,
        snapshot: FrozenSnapshot,
        plan: Plan,
        targets: impl IntoIterator<Item = Target>,
    ) -> Self {
        Self {
            note: note.into(),
            units,
            snapshot,
            plan,
            targets: targets.into_iter().collect(),
            store: StoreHealth::Available,
            expected_runs: None,
        }
    }

    pub fn store(mut self, store: StoreHealth) -> Self {
        self.store = store;
        self
    }

    pub fn expect_runs(mut self, runs: impl IntoIterator<Item = impl Into<String>>) -> Self {
        self.expected_runs = Some(runs.into_iter().map(Into::into).collect());
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reproduction {
    pub seed: u64,
    pub steps: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Scenario {
    pub name: String,
    pub config: HarnessConfig,
    pub steps: Vec<Step>,
    pub reproduction: Option<Reproduction>,
}

impl Scenario {
    pub fn new(name: impl Into<String>, steps: Vec<Step>) -> Self {
        Self {
            name: name.into(),
            config: HarnessConfig::default(),
            steps,
            reproduction: None,
        }
    }

    pub fn seeded(mut self, seed: u64) -> Self {
        self.reproduction = Some(Reproduction {
            seed,
            steps: Vec::new(),
        });
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CheckedBuild {
    pub step: usize,
    pub note: String,
    pub expectation: Expectation,
    pub actual: Observation,
    pub clean: Observation,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProofStatus {
    Passed,
    Pending,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Report {
    pub scenario: String,
    pub builds: Vec<CheckedBuild>,
    pub pending: Vec<String>,
}

impl Report {
    pub fn status(&self) -> ProofStatus {
        if self.pending.is_empty() {
            ProofStatus::Passed
        } else {
            ProofStatus::Pending
        }
    }

    pub fn is_pass(&self) -> bool {
        self.status() == ProofStatus::Passed
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HarnessError {
    Model {
        step: usize,
        note: String,
        message: String,
        reproduction: Option<Reproduction>,
    },
    Adapter {
        step: usize,
        note: String,
        message: String,
        reproduction: Option<Reproduction>,
    },
    Mismatch {
        step: usize,
        note: String,
        field: &'static str,
        expected: String,
        actual: String,
        reproduction: Option<Reproduction>,
    },
}

impl HarnessError {
    pub fn reproduction(&self) -> Option<&Reproduction> {
        match self {
            Self::Model { reproduction, .. }
            | Self::Adapter { reproduction, .. }
            | Self::Mismatch { reproduction, .. } => reproduction.as_ref(),
        }
    }
}

impl fmt::Display for HarnessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Model {
                step,
                note,
                message,
                ..
            } => write!(formatter, "step {step} ({note}): model error: {message}"),
            Self::Adapter {
                step,
                note,
                message,
                ..
            } => write!(formatter, "step {step} ({note}): adapter error: {message}"),
            Self::Mismatch {
                step,
                note,
                field,
                expected,
                actual,
                ..
            } => write!(
                formatter,
                "step {step} ({note}): {field} mismatch: expected {expected}, got {actual}"
            ),
        }
    }
}

impl std::error::Error for HarnessError {}

fn reproduction_for(scenario: &Scenario, index: usize) -> Option<Reproduction> {
    scenario
        .reproduction
        .as_ref()
        .map(|reproduction| Reproduction {
            seed: reproduction.seed,
            steps: scenario.steps[..=index]
                .iter()
                .map(|step| step.note.clone())
                .collect(),
        })
}

fn order_problem(order: &[String], edges: &[Edge]) -> Option<String> {
    let position: std::collections::BTreeMap<&str, usize> = order
        .iter()
        .enumerate()
        .map(|(index, unit)| (unit.as_str(), index))
        .collect();
    for edge in edges {
        let producer = position.get(edge.producer.as_str())?;
        let consumer = position.get(edge.consumer.as_str())?;
        if producer >= consumer {
            return Some(format!(
                "{} runs after its consumer {}",
                edge.producer, edge.consumer
            ));
        }
    }
    None
}

fn mismatch(
    step: usize,
    note: &str,
    field: &'static str,
    expected: impl fmt::Debug,
    actual: impl fmt::Debug,
    reproduction: &Option<Reproduction>,
) -> HarnessError {
    HarnessError::Mismatch {
        step,
        note: note.into(),
        field,
        expected: format!("{expected:?}"),
        actual: format!("{actual:?}"),
        reproduction: reproduction.clone(),
    }
}

fn compare_build(
    step: usize,
    note: &str,
    step_spec: &Step,
    expectation: &Expectation,
    actual: &Observation,
    clean: &Observation,
    reproduction: &Option<Reproduction>,
) -> Result<(), HarnessError> {
    let expected_runs: BTreeSet<&str> = expectation.runs.iter().map(String::as_str).collect();
    let actual_runs: BTreeSet<&str> = actual.runs.iter().map(String::as_str).collect();
    if expected_runs != actual_runs {
        return Err(mismatch(
            step,
            note,
            "run set",
            &expected_runs,
            &actual_runs,
            reproduction,
        ));
    }
    if let Some(handwritten) = &step_spec.expected_runs {
        let handwritten: BTreeSet<&str> = handwritten.iter().map(String::as_str).collect();
        if handwritten != expected_runs {
            return Err(mismatch(
                step,
                note,
                "hand-written run set",
                &handwritten,
                &expected_runs,
                reproduction,
            ));
        }
    }

    let expected_order: BTreeSet<&str> = expectation.order.iter().map(String::as_str).collect();
    let actual_order: BTreeSet<&str> = actual.order.iter().map(String::as_str).collect();
    if expected_order != actual_order {
        return Err(mismatch(
            step,
            note,
            "selected order",
            &expected_order,
            &actual_order,
            reproduction,
        ));
    }
    if let Some(problem) = order_problem(&actual.order, &expectation.edges) {
        return Err(mismatch(
            step,
            note,
            "dependency order",
            "dependencies first",
            problem,
            reproduction,
        ));
    }

    let expected_roots: BTreeSet<&str> = expectation.roots.iter().map(String::as_str).collect();
    let actual_roots: BTreeSet<&str> = actual.roots.iter().map(String::as_str).collect();
    if expected_roots != actual_roots {
        return Err(mismatch(
            step,
            note,
            "roots",
            &expected_roots,
            &actual_roots,
            reproduction,
        ));
    }
    if expectation.edges != actual.edges {
        return Err(mismatch(
            step,
            note,
            "typed edges",
            &expectation.edges,
            &actual.edges,
            reproduction,
        ));
    }

    if expectation.requested != actual.requested {
        return Err(mismatch(
            step,
            note,
            "target outputs",
            &expectation.requested,
            &actual.requested,
            reproduction,
        ));
    }
    if actual.requested != clean.requested {
        return Err(mismatch(
            step,
            note,
            "target outputs vs clean rebuild",
            &clean.requested,
            &actual.requested,
            reproduction,
        ));
    }
    if expectation.requested != clean.requested {
        return Err(mismatch(
            step,
            note,
            "model target outputs vs clean rebuild",
            &clean.requested,
            &expectation.requested,
            reproduction,
        ));
    }

    if expectation.removal_intent != actual.removal_intent {
        return Err(mismatch(
            step,
            note,
            "removal intent",
            &expectation.removal_intent,
            &actual.removal_intent,
            reproduction,
        ));
    }
    if actual.worker_events != actual.runs.len() {
        return Err(mismatch(
            step,
            note,
            "worker events",
            actual.runs.len(),
            actual.worker_events,
            reproduction,
        ));
    }
    if expectation.worker_events != actual.worker_events {
        return Err(mismatch(
            step,
            note,
            "worker event count",
            expectation.worker_events,
            actual.worker_events,
            reproduction,
        ));
    }
    Ok(())
}

/// Runs every step against the adapter and a fresh empty-store adapter, comparing the model,
/// the hand-written run set (when present), target-only outputs and the clean rebuild.
pub fn run_scenario<A, C>(
    scenario: &Scenario,
    mut adapter_factory: A,
    mut clean_factory: C,
) -> Result<Report, HarnessError>
where
    A: FnMut() -> Box<dyn BuildAdapter>,
    C: FnMut() -> Box<dyn BuildAdapter>,
{
    let mut adapter = adapter_factory();
    let mut saved = SavedResults::default();
    let mut builds = Vec::new();
    for (index, step_spec) in scenario.steps.iter().enumerate() {
        let note = step_spec.note.clone();
        let reproduction = reproduction_for(scenario, index);
        let expectation = model::expect(
            &scenario.config,
            &step_spec.units,
            &step_spec.plan,
            &step_spec.targets,
            &step_spec.snapshot,
            &saved,
            step_spec.store,
        )
        .map_err(|message| HarnessError::Model {
            step: index,
            note: note.clone(),
            message,
            reproduction: reproduction.clone(),
        })?;

        let outcome = adapter
            .execute(&BuildRequest {
                config: &scenario.config,
                units: &step_spec.units,
                snapshot: &step_spec.snapshot,
                targets: &step_spec.targets,
                plan: &step_spec.plan,
                saved: &saved,
                store: step_spec.store,
            })
            .map_err(|error| HarnessError::Adapter {
                step: index,
                note: note.clone(),
                message: error.message,
                reproduction: reproduction.clone(),
            })?;

        let empty = SavedResults::default();
        let mut clean_adapter = clean_factory();
        let clean = clean_adapter
            .execute(&BuildRequest {
                config: &scenario.config,
                units: &step_spec.units,
                snapshot: &step_spec.snapshot,
                targets: &step_spec.targets,
                plan: &step_spec.plan,
                saved: &empty,
                store: StoreHealth::Available,
            })
            .map_err(|error| HarnessError::Adapter {
                step: index,
                note: note.clone(),
                message: format!("clean rebuild: {}", error.message),
                reproduction: reproduction.clone(),
            })?;

        compare_build(
            index,
            &note,
            step_spec,
            &expectation,
            &outcome.observation,
            &clean.observation,
            &reproduction,
        )?;

        if outcome.saved_after != expectation.saved_after {
            return Err(mismatch(
                index,
                &note,
                "saved results",
                &expectation.saved_after,
                &outcome.saved_after,
                &reproduction,
            ));
        }

        builds.push(CheckedBuild {
            step: index,
            note,
            expectation: expectation.clone(),
            actual: outcome.observation,
            clean: clean.observation,
        });
        saved = outcome.saved_after;
    }

    Ok(Report {
        scenario: scenario.name.clone(),
        builds,
        pending: vec![
            "A5/A9 scheduling and real worker proof remain pending; this run judges the harness"
                .into(),
        ],
    })
}
