//! C5c: one guarded worker session serving a sequence of units.
//!
//! [`SessionLifecycle`] is the pure state machine behind both [`crate::worker_lifecycle::run_job`]
//! (a session with one unit) and resident batch sessions. A *session* is one guarded attempt: one
//! admission, one bridge and one pinned worker identity, tracked exactly as C5b tracks an attempt
//! (custody `Released` only from the guard's confirmed receipt, `Held` on anything less). Each
//! *unit* is one job with its own C5a [`JobPolicy`]: its job limit starts when it is assigned to an
//! admitted session, its overall deadline counts from its submission, and a crash retry joins a
//! later session only after the session it ran on is confirmed clean.
//!
//! In this version a session serves at most one unit: per-unit settlement evidence, which a reused
//! worker needs, comes later. Nothing here releases capacity, signals a process or deletes a result.
use crate::failure_policy::{
    CleanupState, Decision, End, Event as PolicyEvent, JobPolicy, Limits, MonoTime, Observation,
    Outcome, Phase, Stop,
};
use crate::guard_adapter::{AttemptEvent, CleanupReceipt, LaunchEvent, StoppedBy};
use crate::leases::ProcessIdentity;
use crate::protocol::JobOutputs;
use crate::worker_lifecycle::{AttemptRecord, Custody, LifecycleError, WorkerFault};
use crate::worker_session::Event as WorkerEvent;
use std::time::Duration;

pub type UnitId = String;

/// One unit as the lifecycle sees it. The driver keeps the job request itself.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnitPlan {
    pub id: UnitId,
    pub limits: Limits,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SessionConfig {
    /// How long an ending session may take to deliver its cleanup receipt.
    pub cleanup: Duration,
}

#[derive(Clone, Debug, PartialEq)]
pub enum SessionInput {
    /// A unit joins the queue; `now` is its submission time.
    Submit(UnitPlan),
    /// No more units will be submitted.
    Close,
    CancelUnit(UnitId),
    /// Cancel every unit and close.
    CancelAll,
    /// A guard observation for one session (`attempt` is the session number).
    Launch(AttemptEvent),
    Worker {
        session: u32,
        event: Result<WorkerEvent, WorkerFault>,
    },
    /// The session's worker was durably added to the unit's write lease (or not).
    Registered {
        session: u32,
        unit: UnitId,
        ok: bool,
    },
    /// The session's admission owner could not be started; nothing is held.
    SubmitFailed {
        session: u32,
        reason: String,
    },
    Tick,
}

/// @cc [owner:fontanierh,label:correctness] session-commands-keep-published
/// Session commands MUST be limited to queueing, stopping and talking to a session's own worker,
/// lease registration and handing settled unit records to the caller. No command MAY delete,
/// replace or unpublish a published result. See tests/session_lifecycle.rs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionCommand {
    /// Queue a new guarded session (one admission).
    Submit { session: u32 },
    /// Add the session's pinned worker to `unit`'s write lease before it may write for it.
    Register {
        session: u32,
        unit: UnitId,
        worker: ProcessIdentity,
    },
    /// Send `unit`'s job (`run`) on the session.
    Run { session: u32, unit: UnitId },
    /// Ask an idle, healthy worker to exit (`shutdown`).
    Shutdown { session: u32 },
    /// Ask the guard to stop or withdraw the session. Never certifies cleanup.
    Stop { session: u32 },
    /// `unit` has its final outcome and every attempt of it is released or held.
    Settled { unit: UnitId },
}

#[derive(Clone, Debug, PartialEq)]
pub struct UnitAttemptRecord {
    pub attempt: u32,
    pub session: u32,
    pub custody: Custody,
}

#[derive(Clone, Debug, PartialEq)]
pub struct UnitRecord {
    pub unit: UnitId,
    pub outcome: Outcome,
    pub attempts: Vec<UnitAttemptRecord>,
    /// The worker's reported outputs, for downstream validation and publication.
    pub outputs: Option<JobOutputs>,
    /// Why the lifecycle gave up when no failure kind describes it (for example a launch error).
    pub abort: Option<String>,
}

#[derive(Clone, Debug)]
struct SessionSlot {
    record: AttemptRecord,
    ready: bool,
    shutdown_sent: bool,
    stop_sent: bool,
    exited: bool,
    finished: bool,
    settle_by: Option<MonoTime>,
    /// The unit assigned to this session, running or awaiting its settlement.
    active: Option<usize>,
    /// A unit has been assigned (a session serves one unit in this version).
    used: bool,
    /// The earliest overall deadline of a unit that gave up while waiting for this session: an
    /// unneeded session's settlement never outlasts it.
    cap: Option<MonoTime>,
}

impl SessionSlot {
    fn new(session: u32) -> Self {
        Self {
            record: AttemptRecord {
                attempt: session,
                admitted: false,
                worker: None,
                custody: Custody::Pending,
            },
            ready: false,
            shutdown_sent: false,
            stop_sent: false,
            exited: false,
            finished: false,
            settle_by: None,
            active: None,
            used: false,
            cap: None,
        }
    }

    fn ending(&self) -> bool {
        self.stop_sent || self.shutdown_sent || self.finished
    }

    fn stop(&mut self, out: &mut Vec<SessionCommand>) {
        // Never interrupt the guard's own unwinding once the worker has exited.
        if !self.stop_sent && !self.exited && !self.finished {
            self.stop_sent = true;
            out.push(SessionCommand::Stop {
                session: self.record.attempt,
            });
        }
    }

    fn shutdown(&mut self, out: &mut Vec<SessionCommand>) {
        if !self.shutdown_sent {
            self.shutdown_sent = true;
            out.push(SessionCommand::Shutdown {
                session: self.record.attempt,
            });
        }
    }
}

#[derive(Clone, Debug)]
struct UnitSlot {
    plan: UnitPlan,
    policy: JobPolicy,
    /// Absolute end of the unit's optional overall deadline; `None` if absent or never reached.
    overall_deadline: Option<MonoTime>,
    attempts: Vec<UnitAttemptRecord>,
    /// The session this unit is assigned to, from assignment until it is requeued for a retry.
    session: Option<u32>,
    registered: bool,
    job_sent: bool,
    terminal_seen: bool,
    outcome: Option<Outcome>,
    outputs: Option<JobOutputs>,
    abort: Option<String>,
    settled_sent: bool,
}

impl UnitSlot {
    fn waiting(&self) -> bool {
        self.session.is_none()
            && matches!(
                self.policy.phase(),
                Phase::Queued | Phase::AwaitingReadmission { .. }
            )
    }

    fn settled(&self) -> bool {
        self.outcome.is_some() && self.attempts.iter().all(|a| a.custody != Custody::Pending)
    }

    fn record(&self) -> Option<UnitRecord> {
        Some(UnitRecord {
            unit: self.plan.id.clone(),
            outcome: self.outcome.clone()?,
            attempts: self.attempts.clone(),
            outputs: self.outputs.clone(),
            abort: self.abort.clone(),
        })
    }
}

#[derive(Clone, Debug)]
pub struct SessionLifecycle {
    config: SessionConfig,
    sessions: Vec<SessionSlot>,
    units: Vec<UnitSlot>,
    closed: bool,
}

fn reached(at: Option<MonoTime>, now: MonoTime) -> bool {
    at.is_some_and(|at| now >= at)
}

/// How a unit's final decision ends its session when nothing else needs it.
enum Ending {
    Shutdown,
    Stop,
    Neither,
}

impl SessionLifecycle {
    pub fn new(config: SessionConfig) -> Self {
        Self {
            config,
            sessions: vec![],
            units: vec![],
            closed: false,
        }
    }

    /// Every session (guarded attempt) so far, in order.
    pub fn sessions(&self) -> Vec<AttemptRecord> {
        self.sessions.iter().map(|s| s.record.clone()).collect()
    }

    pub fn unit_policy(&self, unit: &str) -> Option<&JobPolicy> {
        self.units
            .iter()
            .find(|u| u.plan.id == unit)
            .map(|u| &u.policy)
    }

    pub fn unit(&self, unit: &str) -> Option<UnitRecord> {
        self.units
            .iter()
            .find(|u| u.plan.id == unit)
            .and_then(UnitSlot::record)
    }

    /// Every unit has its final outcome and every attempt of it and every session is released
    /// or held.
    pub fn settled(&self) -> bool {
        self.units.iter().all(UnitSlot::settled)
            && self
                .sessions
                .iter()
                .all(|s| s.record.custody != Custody::Pending)
    }

    /// Closed, and settled.
    pub fn done(&self) -> bool {
        self.closed && self.settled()
    }

    /// The next instant a [`SessionInput::Tick`] can change anything.
    pub fn next_deadline(&self) -> Option<MonoTime> {
        self.sessions
            .iter()
            .filter(|s| s.record.custody == Custody::Pending)
            .filter_map(|s| s.settle_by)
            .chain(self.units.iter().filter_map(|u| u.policy.next_deadline()))
            .min()
    }

    /// The latest instant a waiting unit can still start: a session's queue limit.
    /// `None` when some waiting unit has no overall deadline.
    pub fn queue_deadline(&self) -> Option<MonoTime> {
        let mut latest = None;
        for unit in self.units.iter().filter(|u| u.waiting()) {
            match unit.policy.next_deadline() {
                None => return None,
                Some(at) => latest = Some(latest.map_or(at, |l: MonoTime| l.max(at))),
            }
        }
        latest
    }

    fn live(&self) -> Option<usize> {
        self.sessions
            .last()
            .filter(|s| !s.finished)
            .map(|_| self.sessions.len() - 1)
    }

    fn session_index(&self, session: u32) -> Option<usize> {
        self.sessions
            .iter()
            .position(|s| s.record.attempt == session)
    }

    fn unit_index(&self, unit: &str) -> Option<usize> {
        self.units.iter().position(|u| u.plan.id == unit)
    }

    /// @cc [owner:fontanierh,label:correctness] session-retry-once
    /// Only the guard's exit observation for a session's pinned worker, with no stop or shutdown
    /// requested and no guard or deadline stop, MAY become crash evidence, and only for the unit
    /// assigned to that session; worker claims, pipe loss and foreign identities MUST NOT. A
    /// unit's retry MUST wait for its policy's `RequestAdmission`, which follows the confirmed
    /// cleanup receipt of the session it ran on, and MUST start only in a later session after
    /// that session's own admission. See tests/session_lifecycle.rs.
    pub fn on(
        &mut self,
        now: MonoTime,
        input: SessionInput,
    ) -> Result<Vec<SessionCommand>, LifecycleError> {
        let mut out = vec![];
        match input {
            SessionInput::Submit(plan) => {
                if self.closed {
                    return Err(LifecycleError::Invariant(
                        "a unit was submitted after close".into(),
                    ));
                }
                if self.unit_index(&plan.id).is_some() {
                    return Err(LifecycleError::Invariant(format!(
                        "unit {} was submitted twice",
                        plan.id
                    )));
                }
                self.units.push(UnitSlot {
                    policy: JobPolicy::new(now, plan.limits),
                    overall_deadline: plan.limits.overall.and_then(|span| now.checked_add(span)),
                    plan,
                    attempts: vec![],
                    session: None,
                    registered: false,
                    job_sent: false,
                    terminal_seen: false,
                    outcome: None,
                    outputs: None,
                    abort: None,
                    settled_sent: false,
                });
            }
            SessionInput::Close => self.closed = true,
            SessionInput::CancelAll => {
                self.closed = true;
                for index in 0..self.units.len() {
                    self.decide(now, index, PolicyEvent::CancelRequested, &mut out)?;
                }
            }
            SessionInput::CancelUnit(unit) => {
                if let Some(index) = self.unit_index(&unit) {
                    self.decide(now, index, PolicyEvent::CancelRequested, &mut out)?;
                }
            }
            SessionInput::Tick => {
                for index in 0..self.units.len() {
                    self.decide(now, index, PolicyEvent::Tick, &mut out)?;
                }
            }
            SessionInput::SubmitFailed { session, reason } => {
                let Some(s) = self.session_index(session) else {
                    return Ok(out);
                };
                // A submit error means no admission owner was started
                // (launcher-submit-error-means-nothing-started), so nothing is held.
                let live = self.live() == Some(s);
                let slot = &mut self.sessions[s];
                slot.finished = true;
                slot.record.custody = Custody::Released;
                if live {
                    self.abort_waiting(now, &format!("launch failed: {reason}"), &mut out)?;
                }
            }
            SessionInput::Registered { session, unit, ok } => {
                let (Some(s), Some(index)) = (self.session_index(session), self.unit_index(&unit))
                else {
                    return Ok(out);
                };
                if self.live() == Some(s) && self.units[index].session == Some(session) {
                    if ok {
                        self.units[index].registered = true;
                        self.run_if_ready(s, &mut out);
                    } else {
                        self.units[index].abort.get_or_insert(
                            "worker identity could not be added to the write lease".into(),
                        );
                        self.decide(now, index, PolicyEvent::CancelRequested, &mut out)?;
                    }
                }
            }
            SessionInput::Worker { session, event } => {
                if let Some(s) = self.session_index(session) {
                    if self.live() == Some(s) {
                        self.worker(now, s, event, &mut out)?;
                    }
                }
            }
            SessionInput::Launch(AttemptEvent { attempt, event }) => {
                self.launch(now, attempt, event, &mut out)?
            }
        }
        self.pump(now, &mut out)?;
        self.settle(now, &mut out);
        for unit in &mut self.units {
            if !unit.settled_sent && unit.settled() {
                unit.settled_sent = true;
                out.push(SessionCommand::Settled {
                    unit: unit.plan.id.clone(),
                });
            }
        }
        Ok(out)
    }

    /// Every unit waiting for the live session gives up with `reason`.
    fn abort_waiting(
        &mut self,
        now: MonoTime,
        reason: &str,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        for index in 0..self.units.len() {
            if self.units[index].waiting() {
                self.units[index].abort.get_or_insert(reason.into());
                self.decide(now, index, PolicyEvent::CancelRequested, out)?;
            }
        }
        Ok(())
    }

    /// Assign waiting units to the live session, end a session nothing needs, and queue a
    /// session for waiting units.
    fn pump(&mut self, now: MonoTime, out: &mut Vec<SessionCommand>) -> Result<(), LifecycleError> {
        if let Some(s) = self.live() {
            let slot = &self.sessions[s];
            if slot.record.admitted && !slot.ending() && slot.active.is_none() && !slot.used {
                while let Some(index) = self.units.iter().position(UnitSlot::waiting) {
                    self.assign(now, s, index, out)?;
                    if self.sessions[s].active.is_some() {
                        break;
                    }
                }
            }
            let slot = &mut self.sessions[s];
            let wanted = !slot.used && self.units.iter().any(UnitSlot::waiting);
            if slot.active.is_none() && !slot.ending() && !wanted {
                // Nothing needs this session: withdraw a queued request, or end an idle worker.
                if slot.record.admitted && slot.ready {
                    slot.shutdown(out);
                } else {
                    slot.stop(out);
                }
                if slot.settle_by.is_none() {
                    slot.settle_by = [now.checked_add(self.config.cleanup), slot.cap]
                        .into_iter()
                        .flatten()
                        .min();
                }
            }
            return Ok(());
        }
        if !self.units.iter().any(UnitSlot::waiting) {
            return Ok(());
        }
        match self.sessions.last().map(|s| s.record.custody.clone()) {
            // The previous session's receipt is still due: no second admission meanwhile.
            Some(Custody::Pending) => Ok(()),
            Some(Custody::Held(_)) => self.abort_waiting(
                now,
                "a previous session's cleanup is unconfirmed, so no new session may start",
                out,
            ),
            None | Some(Custody::Released) => {
                let session = self.sessions.len() as u32 + 1;
                self.sessions.push(SessionSlot::new(session));
                out.push(SessionCommand::Submit { session });
                Ok(())
            }
        }
    }

    /// Give waiting unit `index` to admitted session `s`: this is the unit's own admission, so its
    /// job limit starts now.
    fn assign(
        &mut self,
        now: MonoTime,
        s: usize,
        index: usize,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        let session = self.sessions[s].record.attempt;
        let decision = self.units[index]
            .policy
            .decide(now, PolicyEvent::Admitted)
            .map_err(LifecycleError::Policy)?;
        match decision {
            Decision::Launch { attempt } => {
                let unit = &mut self.units[index];
                unit.session = Some(session);
                unit.registered = false;
                unit.job_sent = false;
                unit.terminal_seen = false;
                unit.attempts.push(UnitAttemptRecord {
                    attempt,
                    session,
                    custody: Custody::Pending,
                });
                let slot = &mut self.sessions[s];
                slot.active = Some(index);
                slot.used = true;
                if let Some(worker) = slot.record.worker.clone() {
                    out.push(SessionCommand::Register {
                        session,
                        unit: self.units[index].plan.id.clone(),
                        worker,
                    });
                }
                Ok(())
            }
            other => self.apply(now, index, other, out),
        }
    }

    fn run_if_ready(&mut self, s: usize, out: &mut Vec<SessionCommand>) {
        let slot = &self.sessions[s];
        let Some(index) = slot.active else {
            return;
        };
        let unit = &mut self.units[index];
        if slot.ready
            && unit.registered
            && !unit.job_sent
            && matches!(unit.policy.phase(), Phase::Running { .. })
        {
            unit.job_sent = true;
            out.push(SessionCommand::Run {
                session: slot.record.attempt,
                unit: unit.plan.id.clone(),
            });
        }
    }

    fn decide(
        &mut self,
        now: MonoTime,
        index: usize,
        event: PolicyEvent,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        let decision = self.units[index]
            .policy
            .decide(now, event)
            .map_err(LifecycleError::Policy)?;
        self.apply(now, index, decision, out)
    }

    fn apply(
        &mut self,
        now: MonoTime,
        index: usize,
        decision: Decision,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        let assigned = self.units[index]
            .session
            .and_then(|session| self.session_index(session));
        match decision {
            Decision::Wait | Decision::Launch { .. } => {}
            Decision::BeginCleanup { stop, .. } => {
                let Some(s) = assigned else {
                    return Err(LifecycleError::Invariant(
                        "cleanup for a unit with no session".into(),
                    ));
                };
                let unit = &self.units[index];
                let slot = &mut self.sessions[s];
                let graceful = matches!(stop, Stop::WorkerReported(_))
                    && slot.ready
                    && unit.terminal_seen
                    && !slot.exited;
                if graceful {
                    slot.shutdown(out);
                } else {
                    slot.stop(out);
                }
            }
            Decision::RequestAdmission { .. } => {
                let previous = self.units[index].attempts.last().map(|a| a.custody.clone());
                if previous != Some(Custody::Released) {
                    return Err(LifecycleError::Invariant(
                        "a retry needs the previous session's confirmed cleanup".into(),
                    ));
                }
                // Back in the queue for a later session; `pump` queues one.
                if let Some(s) = assigned {
                    self.sessions[s].active = None;
                }
                self.units[index].session = None;
            }
            Decision::Finish(outcome) => {
                let unconfirmed = matches!(outcome.cleanup, CleanupState::Unconfirmed(_));
                let completed = outcome.end == End::Completed;
                let deadline = self.units[index].overall_deadline;
                self.units[index].outcome = Some(outcome);
                let Some(s) = assigned else {
                    // Finished while waiting: if nothing else needs the session it waited for,
                    // `pump` ends it, and its settlement never outlasts this unit's deadline.
                    if let Some(s) = self.live() {
                        let slot = &mut self.sessions[s];
                        if !slot.used {
                            slot.cap = [slot.cap, deadline].into_iter().flatten().min();
                        }
                    }
                    return Ok(());
                };
                let ending = {
                    let slot = &self.sessions[s];
                    if completed && slot.ready && !slot.exited {
                        Ending::Shutdown
                    } else if !completed {
                        Ending::Stop
                    } else {
                        Ending::Neither
                    }
                };
                let slot = &mut self.sessions[s];
                if !slot.finished {
                    match ending {
                        Ending::Shutdown => slot.shutdown(out),
                        Ending::Stop => slot.stop(out),
                        Ending::Neither => {}
                    }
                    if slot.settle_by.is_none() {
                        // Wait for the cleanup limit, but never past the overall deadline,
                        // which covers cleanup too (failure-policy-time-limits). An
                        // overflowing sum is never reached. Unsettled custody is then held.
                        slot.settle_by = [now.checked_add(self.config.cleanup), deadline]
                            .into_iter()
                            .flatten()
                            .min();
                    }
                }
                if unconfirmed {
                    let reason =
                        "the policy's cleanup limit or deadline passed without a confirmed receipt";
                    if slot.record.custody == Custody::Pending {
                        slot.record.custody = Custody::Held(reason.into());
                    }
                    if let Some(last) = self.units[index].attempts.last_mut() {
                        if last.custody == Custody::Pending {
                            last.custody = Custody::Held(reason.into());
                        }
                    }
                }
            }
        }
        Ok(())
    }

    /// A malformed or inconsistent guard report for session `s`: never crash or cleanup evidence.
    fn fault(
        &mut self,
        now: MonoTime,
        s: usize,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        self.sessions[s].stop(out);
        if self.live() != Some(s) {
            return Ok(());
        }
        match self.sessions[s].active {
            Some(index) => match self.units[index].policy.phase() {
                Phase::Running { .. } | Phase::CleaningUp { .. } => self.decide(
                    now,
                    index,
                    PolicyEvent::Observed(Observation::ProtocolViolation),
                    out,
                ),
                _ => Ok(()),
            },
            None if !self.sessions[s].record.admitted => {
                self.abort_waiting(now, "the guard reported an inconsistent attempt", out)
            }
            None => Ok(()),
        }
    }

    fn launch(
        &mut self,
        now: MonoTime,
        session: u32,
        event: LaunchEvent,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        let Some(s) = self.session_index(session) else {
            return Ok(());
        };
        let current = self.sessions.len() == s + 1;
        if let LaunchEvent::Finished { cleanup, .. } = event {
            let custody = match cleanup.clone() {
                CleanupReceipt::Confirmed => Custody::Released,
                CleanupReceipt::Unconfirmed { reason } => Custody::Held(reason),
            };
            let confirmed = cleanup == CleanupReceipt::Confirmed;
            let slot = &mut self.sessions[s];
            slot.finished = true;
            slot.record.custody = custody.clone();
            let (exited, admitted, active) = (slot.exited, slot.record.admitted, slot.active);
            for unit in &mut self.units {
                for attempt in &mut unit.attempts {
                    if attempt.session == session && attempt.custody != Custody::Released {
                        attempt.custody = custody.clone();
                    }
                }
            }
            if !current {
                return Ok(());
            }
            let Some(index) = active else {
                if !admitted && !exited {
                    self.abort_waiting(now, "the admission owner ended before admission", out)?;
                }
                return Ok(());
            };
            return match self.units[index].policy.phase().clone() {
                Phase::CleaningUp { .. } if confirmed => {
                    self.decide(now, index, PolicyEvent::CleanupFinished, out)
                }
                Phase::Running { .. } => {
                    // The guard finished without reporting the worker's exit.
                    self.decide(
                        now,
                        index,
                        PolicyEvent::Observed(Observation::ProtocolViolation),
                        out,
                    )?;
                    if confirmed {
                        self.decide(now, index, PolicyEvent::CleanupFinished, out)?;
                    }
                    Ok(())
                }
                _ => Ok(()),
            };
        }
        if self.live() != Some(s) {
            return Ok(());
        }
        match event {
            LaunchEvent::Queued | LaunchEvent::Finished { .. } => Ok(()),
            LaunchEvent::Admitted => {
                if self.sessions[s].record.admitted {
                    return self.fault(now, s, out);
                }
                self.sessions[s].record.admitted = true;
                Ok(())
            }
            LaunchEvent::ChildStarted { worker } => {
                let (admitted, pinned) = {
                    let record = &self.sessions[s].record;
                    (record.admitted, record.worker.clone())
                };
                match pinned {
                    _ if !admitted => self.fault(now, s, out),
                    Some(pinned) if pinned == worker => Ok(()),
                    Some(_) => self.fault(now, s, out),
                    None => {
                        self.sessions[s].record.worker = Some(worker.clone());
                        if let Some(index) = self.sessions[s].active {
                            let unit = &self.units[index];
                            if unit.outcome.is_none() && !unit.registered {
                                out.push(SessionCommand::Register {
                                    session,
                                    unit: unit.plan.id.clone(),
                                    worker,
                                });
                            }
                        }
                        Ok(())
                    }
                }
            }
            LaunchEvent::ChildExited {
                worker, stopped_by, ..
            } => {
                let slot = &mut self.sessions[s];
                if slot.record.worker.as_ref() != Some(&worker) {
                    return self.fault(now, s, out);
                }
                slot.exited = true;
                let requested = slot.stop_sent || slot.shutdown_sent;
                let event = match stopped_by {
                    Some(StoppedBy::Guard) | Some(StoppedBy::Deadline) => {
                        Some(PolicyEvent::Observed(Observation::GuardStopped))
                    }
                    // Someone else asked the admission owner to stop: a cancellation, never a crash.
                    Some(StoppedBy::Cancel) if !requested => Some(PolicyEvent::CancelRequested),
                    Some(StoppedBy::Cancel) => None,
                    None if requested => None,
                    None => Some(PolicyEvent::Observed(Observation::UnexpectedExit)),
                };
                match (event, slot.active) {
                    (Some(event), Some(index)) => self.decide(now, index, event, out),
                    _ => Ok(()),
                }
            }
            LaunchEvent::Fault(_) => self.fault(now, s, out),
        }
    }

    fn worker(
        &mut self,
        now: MonoTime,
        s: usize,
        event: Result<WorkerEvent, WorkerFault>,
        out: &mut Vec<SessionCommand>,
    ) -> Result<(), LifecycleError> {
        let active = self.sessions[s].active;
        match event {
            Ok(WorkerEvent::Ready { .. }) => {
                self.sessions[s].ready = true;
                self.run_if_ready(s, out);
                Ok(())
            }
            Ok(WorkerEvent::Started { .. }) | Ok(WorkerEvent::Stopped) => Ok(()),
            Ok(WorkerEvent::Finished(finished)) => {
                let Some(index) = active else {
                    return Ok(());
                };
                self.units[index].terminal_seen = true;
                match finished.result {
                    Ok(outputs) => {
                        self.decide(now, index, PolicyEvent::Completed, out)?;
                        let unit = &mut self.units[index];
                        if unit
                            .outcome
                            .as_ref()
                            .is_some_and(|o| o.end == End::Completed)
                        {
                            unit.outputs = Some(outputs);
                        }
                        Ok(())
                    }
                    Err(failure) => {
                        self.decide(now, index, PolicyEvent::WorkerFailed(failure.kind), out)
                    }
                }
            }
            Err(WorkerFault::Protocol(_)) => match active {
                Some(index)
                    if matches!(
                        self.units[index].policy.phase(),
                        Phase::Running { .. } | Phase::CleaningUp { .. }
                    ) =>
                {
                    self.decide(
                        now,
                        index,
                        PolicyEvent::Observed(Observation::ProtocolViolation),
                        out,
                    )
                }
                _ => Ok(()),
            },
            Err(WorkerFault::Disconnected(_)) => Ok(()),
        }
    }

    fn settle(&mut self, now: MonoTime, out: &mut Vec<SessionCommand>) {
        for slot in &mut self.sessions {
            if slot.record.custody == Custody::Pending && reached(slot.settle_by, now) {
                let reason = "no confirmed cleanup receipt within the cleanup limit";
                slot.record.custody = Custody::Held(reason.into());
                slot.stop(out);
                let session = slot.record.attempt;
                for unit in &mut self.units {
                    for attempt in &mut unit.attempts {
                        if attempt.session == session && attempt.custody == Custody::Pending {
                            attempt.custody = Custody::Held(reason.into());
                        }
                    }
                }
            }
        }
    }
}
