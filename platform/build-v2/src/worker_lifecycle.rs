//! C5b: one job's owned worker lifecycle over guarded attempts.
//!
//! [`Lifecycle`] is a pure state machine. It combines the guard's observations
//! ([`LaunchEvent`]), the worker session's events and caller cancellation into C5a's
//! [`JobPolicy`], and emits [`Command`]s. It tracks each attempt's custody separately from the
//! policy: an attempt is `Released` only by the guard's confirmed cleanup receipt and `Held` on
//! anything less. Nothing here releases capacity, signals a process or deletes a result.
//! [`run_job`] drives it with a real [`WorkerLauncher`] and the C1a session.
use crate::failure_policy::{
    CleanupState, Decision, End, Event as PolicyEvent, JobPolicy, Limits, MonoTime, Observation,
    Outcome, Phase, PolicyError, Stop,
};
use crate::guard_adapter::{
    AdmissionRequest, AttemptEvent, CleanupReceipt, LaunchEvent, StoppedBy, WorkerAttempt,
    WorkerCommand, WorkerLauncher,
};
use crate::leases::ProcessIdentity;
use crate::protocol::{JobOutputs, JobRequest, Response, read_frame, write_frame};
use crate::worker_session::{Event as WorkerEvent, Session, SessionError};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{self, Read, Write};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::thread;
use std::time::{Duration, Instant};

/// @cc [owner:fontanierh,label:safety] lifecycle-unconfirmed-cleanup-held
/// An attempt MUST become `Released` only from the guard's confirmed cleanup receipt, or when its
/// launch never started. Unconfirmed receipts, policy deadlines, cleanup limits and controller
/// gaps MUST leave it `Held`; a held attempt MUST NOT be relaunched, and the lifecycle MUST NOT
/// release capacity or checkout custody itself. See tests/worker_lifecycle.rs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Custody {
    /// Started and not yet settled by a receipt.
    Pending,
    /// The guard confirmed cleanup (and, if admitted, capacity close released).
    Released,
    /// Cleanup is unconfirmed: capacity and checkout custody stay with the guard.
    Held(String),
}

#[derive(Clone, Debug, PartialEq)]
pub struct AttemptRecord {
    pub attempt: u32,
    pub admitted: bool,
    pub worker: Option<ProcessIdentity>,
    pub custody: Custody,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Report {
    pub outcome: Outcome,
    pub attempts: Vec<AttemptRecord>,
    /// The worker's reported outputs, for downstream validation and publication.
    pub outputs: Option<JobOutputs>,
    /// Why the lifecycle gave up when no failure kind describes it (for example a launch error).
    pub abort: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum WorkerFault {
    Protocol(String),
    /// The pipe ended or failed. Not crash evidence: only the guard's exit observation is.
    Disconnected(String),
}

#[derive(Clone, Debug, PartialEq)]
pub enum Input {
    Launch(AttemptEvent),
    Worker {
        attempt: u32,
        event: Result<WorkerEvent, WorkerFault>,
    },
    /// The attempt's worker identity was durably added to the write lease (or not).
    Registered {
        attempt: u32,
        ok: bool,
    },
    SubmitFailed {
        attempt: u32,
        reason: String,
    },
    Cancel,
    Tick,
}

/// @cc [owner:fontanierh,label:correctness] lifecycle-keeps-published
/// Lifecycle commands MUST be limited to queueing, stopping and talking to the attempt's own
/// worker and lease registration. No command MAY delete, replace or unpublish a published
/// result; completed outputs are handed to the caller. See tests/worker_lifecycle.rs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Command {
    /// Queue a new admitted attempt.
    Submit { attempt: u32 },
    /// Add the pinned worker identity to the write lease before it may write.
    RegisterWorker {
        attempt: u32,
        worker: ProcessIdentity,
    },
    /// Send the job (`run`) on the attempt's session.
    StartJob { attempt: u32 },
    /// Ask an idle, healthy worker to exit (`shutdown`).
    Shutdown { attempt: u32 },
    /// Ask the guard to stop or withdraw the attempt. Never certifies cleanup.
    Stop { attempt: u32 },
}

#[derive(Clone, Debug, PartialEq)]
pub enum LifecycleError {
    Policy(PolicyError),
    /// An internal invariant failed; the attempt state is left unchanged.
    Invariant(String),
}

#[derive(Clone, Debug)]
struct Attempt {
    record: AttemptRecord,
    registered: bool,
    ready: bool,
    job_sent: bool,
    terminal_seen: bool,
    shutdown_sent: bool,
    stop_sent: bool,
    exited: bool,
    finished: bool,
    settle_by: Option<MonoTime>,
}

impl Attempt {
    fn new(attempt: u32) -> Self {
        Self {
            record: AttemptRecord {
                attempt,
                admitted: false,
                worker: None,
                custody: Custody::Pending,
            },
            registered: false,
            ready: false,
            job_sent: false,
            terminal_seen: false,
            shutdown_sent: false,
            stop_sent: false,
            exited: false,
            finished: false,
            settle_by: None,
        }
    }
}

/// One job across at most [`crate::failure_policy::MAX_ATTEMPTS`] guarded attempts.
#[derive(Clone, Debug)]
pub struct Lifecycle {
    policy: JobPolicy,
    limits: Limits,
    attempts: Vec<Attempt>,
    outcome: Option<Outcome>,
    outputs: Option<JobOutputs>,
    abort: Option<String>,
}

fn reached(at: Option<MonoTime>, now: MonoTime) -> bool {
    at.is_some_and(|at| now >= at)
}

impl Lifecycle {
    /// A queued job: the first command is `Submit { attempt: 1 }`.
    pub fn new(submitted: MonoTime, limits: Limits) -> (Self, Vec<Command>) {
        let lifecycle = Self {
            policy: JobPolicy::new(submitted, limits),
            limits,
            attempts: vec![Attempt::new(1)],
            outcome: None,
            outputs: None,
            abort: None,
        };
        (lifecycle, vec![Command::Submit { attempt: 1 }])
    }

    pub fn policy(&self) -> &JobPolicy {
        &self.policy
    }

    pub fn attempts(&self) -> Vec<AttemptRecord> {
        self.attempts.iter().map(|a| a.record.clone()).collect()
    }

    /// The finished job, once the outcome is known and every attempt is released or held.
    pub fn report(&self) -> Option<Report> {
        let outcome = self.outcome.clone()?;
        if self
            .attempts
            .iter()
            .any(|a| a.record.custody == Custody::Pending)
        {
            return None;
        }
        Some(Report {
            outcome,
            attempts: self.attempts(),
            outputs: self.outputs.clone(),
            abort: self.abort.clone(),
        })
    }

    /// The next instant a [`Input::Tick`] can change anything.
    pub fn next_deadline(&self) -> Option<MonoTime> {
        self.attempts
            .iter()
            .filter(|a| a.record.custody == Custody::Pending)
            .filter_map(|a| a.settle_by)
            .chain(self.policy.next_deadline())
            .min()
    }

    fn current(&self) -> u32 {
        self.attempts.last().map_or(0, |a| a.record.attempt)
    }

    fn slot(&mut self, attempt: u32) -> Option<&mut Attempt> {
        self.attempts
            .iter_mut()
            .find(|a| a.record.attempt == attempt)
    }

    /// @cc [owner:fontanierh,label:correctness] lifecycle-retry-once
    /// Only the guard's exit observation for the pinned worker identity, with no stop or
    /// shutdown requested and no guard or deadline stop, MAY become crash evidence; worker
    /// claims, pipe loss and foreign identities MUST NOT. A retry MUST be submitted only after
    /// the policy's `RequestAdmission`, which follows the previous attempt's confirmed cleanup
    /// receipt, and MUST launch only on the new attempt's own admission. See tests/worker_lifecycle.rs.
    pub fn on(&mut self, now: MonoTime, input: Input) -> Result<Vec<Command>, LifecycleError> {
        let mut out = vec![];
        match input {
            Input::Cancel => self.decide(now, PolicyEvent::CancelRequested, &mut out)?,
            Input::Tick => self.decide(now, PolicyEvent::Tick, &mut out)?,
            Input::SubmitFailed { attempt, reason } => {
                if let Some(slot) = self.slot(attempt) {
                    // Nothing was started, so nothing is held.
                    slot.finished = true;
                    slot.record.custody = Custody::Released;
                }
                if attempt == self.current() {
                    self.abort.get_or_insert(format!("launch failed: {reason}"));
                    self.decide(now, PolicyEvent::CancelRequested, &mut out)?;
                }
            }
            Input::Registered { attempt, ok } => {
                if attempt == self.current() {
                    if ok {
                        if let Some(slot) = self.slot(attempt) {
                            slot.registered = true;
                        }
                        self.start_job(&mut out);
                    } else {
                        self.abort.get_or_insert(
                            "worker identity could not be added to the write lease".into(),
                        );
                        self.decide(now, PolicyEvent::CancelRequested, &mut out)?;
                    }
                }
            }
            Input::Worker { attempt, event } => {
                if attempt == self.current() {
                    self.worker(now, event, &mut out)?;
                }
            }
            Input::Launch(AttemptEvent { attempt, event }) => {
                self.launch(now, attempt, event, &mut out)?
            }
        }
        self.settle(now, &mut out);
        Ok(out)
    }

    fn phase(&self) -> Phase {
        self.policy.phase().clone()
    }

    fn index(&self, attempt: u32) -> Option<usize> {
        self.attempts
            .iter()
            .position(|a| a.record.attempt == attempt)
    }

    fn start_job(&mut self, out: &mut Vec<Command>) {
        if !matches!(self.phase(), Phase::Running { .. }) {
            return;
        }
        let attempt = self.current();
        if let Some(slot) = self.slot(attempt) {
            if slot.ready && slot.registered && !slot.job_sent {
                slot.job_sent = true;
                out.push(Command::StartJob { attempt });
            }
        }
    }

    fn stop(slot: &mut Attempt, out: &mut Vec<Command>) {
        // Never interrupt the guard's own unwinding once the worker has exited.
        if !slot.stop_sent && !slot.exited && !slot.finished {
            slot.stop_sent = true;
            out.push(Command::Stop {
                attempt: slot.record.attempt,
            });
        }
    }

    fn decide(
        &mut self,
        now: MonoTime,
        event: PolicyEvent,
        out: &mut Vec<Command>,
    ) -> Result<(), LifecycleError> {
        let decision = self
            .policy
            .decide(now, event)
            .map_err(LifecycleError::Policy)?;
        let attempt = self.current();
        match decision {
            Decision::Wait | Decision::Launch { .. } => {}
            Decision::BeginCleanup { stop, .. } => {
                let Some(slot) = self.slot(attempt) else {
                    return Err(LifecycleError::Invariant(
                        "cleanup without an attempt".into(),
                    ));
                };
                let graceful = matches!(stop, Stop::WorkerReported(_))
                    && slot.ready
                    && slot.terminal_seen
                    && !slot.exited;
                if graceful && !slot.shutdown_sent {
                    slot.shutdown_sent = true;
                    out.push(Command::Shutdown { attempt });
                } else if !graceful {
                    Self::stop(slot, out);
                }
            }
            Decision::RequestAdmission { attempt: next } => {
                let previous = self.slot(attempt).map(|slot| slot.record.custody.clone());
                if previous != Some(Custody::Released) {
                    return Err(LifecycleError::Invariant(
                        "a retry needs the previous attempt's confirmed cleanup".into(),
                    ));
                }
                self.attempts.push(Attempt::new(next));
                out.push(Command::Submit { attempt: next });
            }
            Decision::Finish(outcome) => {
                let cleanup = self.limits.cleanup;
                let unconfirmed = matches!(outcome.cleanup, CleanupState::Unconfirmed(_));
                let completed = outcome.end == End::Completed;
                self.outcome = Some(outcome);
                if let Some(slot) = self.slot(attempt) {
                    if !slot.finished {
                        if completed && slot.ready && !slot.exited {
                            if !slot.shutdown_sent {
                                slot.shutdown_sent = true;
                                out.push(Command::Shutdown { attempt });
                            }
                        } else if !completed {
                            Self::stop(slot, out);
                        }
                        slot.settle_by
                            .get_or_insert(now.checked_add(cleanup).unwrap_or(now));
                    }
                    if unconfirmed && slot.record.custody == Custody::Pending {
                        slot.record.custody = Custody::Held(
                            "the policy's cleanup limit or deadline passed without a confirmed receipt"
                                .into(),
                        );
                    }
                }
            }
        }
        Ok(())
    }

    /// A malformed or inconsistent guard report: never crash or cleanup evidence.
    fn fault(
        &mut self,
        now: MonoTime,
        attempt: u32,
        out: &mut Vec<Command>,
    ) -> Result<(), LifecycleError> {
        if let Some(slot) = self.slot(attempt) {
            Self::stop(slot, out);
        }
        if attempt != self.current() {
            return Ok(());
        }
        match self.phase() {
            Phase::Running { .. } | Phase::CleaningUp { .. } => self.decide(
                now,
                PolicyEvent::Observed(Observation::ProtocolViolation),
                out,
            ),
            Phase::Queued | Phase::AwaitingReadmission { .. } => {
                self.abort
                    .get_or_insert("the guard reported an inconsistent attempt".into());
                self.decide(now, PolicyEvent::CancelRequested, out)
            }
            Phase::Done(_) => Ok(()),
        }
    }

    fn launch(
        &mut self,
        now: MonoTime,
        attempt: u32,
        event: LaunchEvent,
        out: &mut Vec<Command>,
    ) -> Result<(), LifecycleError> {
        let current = attempt == self.current();
        let Some(index) = self.index(attempt) else {
            return Ok(());
        };
        if let LaunchEvent::Finished { cleanup, .. } = event {
            let slot = &mut self.attempts[index];
            slot.finished = true;
            let confirmed = cleanup == CleanupReceipt::Confirmed;
            slot.record.custody = match cleanup {
                CleanupReceipt::Confirmed => Custody::Released,
                CleanupReceipt::Unconfirmed { reason } => Custody::Held(reason),
            };
            let (exited, admitted) = (slot.exited, slot.record.admitted);
            if !current {
                return Ok(());
            }
            return match self.phase() {
                Phase::CleaningUp { .. } if confirmed => {
                    self.decide(now, PolicyEvent::CleanupFinished, out)
                }
                Phase::Running { .. } => {
                    // The guard finished without reporting the worker's exit.
                    self.decide(
                        now,
                        PolicyEvent::Observed(Observation::ProtocolViolation),
                        out,
                    )?;
                    if confirmed {
                        self.decide(now, PolicyEvent::CleanupFinished, out)?;
                    }
                    Ok(())
                }
                Phase::Queued | Phase::AwaitingReadmission { .. } if !admitted && !exited => {
                    self.abort
                        .get_or_insert("the admission owner ended before admission".into());
                    self.decide(now, PolicyEvent::CancelRequested, out)
                }
                _ => Ok(()),
            };
        }
        if !current || self.attempts[index].finished {
            return Ok(());
        }
        match event {
            LaunchEvent::Queued | LaunchEvent::Finished { .. } => Ok(()),
            LaunchEvent::Admitted => {
                if self.attempts[index].record.admitted {
                    return self.fault(now, attempt, out);
                }
                self.attempts[index].record.admitted = true;
                match self.phase() {
                    Phase::Queued | Phase::AwaitingReadmission { .. } => {
                        self.decide(now, PolicyEvent::Admitted, out)
                    }
                    _ => Ok(()),
                }
            }
            LaunchEvent::ChildStarted { worker } => {
                let (admitted, pinned) = {
                    let record = &self.attempts[index].record;
                    (record.admitted, record.worker.clone())
                };
                match pinned {
                    _ if !admitted => self.fault(now, attempt, out),
                    Some(pinned) if pinned == worker => Ok(()),
                    Some(_) => self.fault(now, attempt, out),
                    None => {
                        self.attempts[index].record.worker = Some(worker.clone());
                        if self.outcome.is_none() {
                            out.push(Command::RegisterWorker { attempt, worker });
                        }
                        Ok(())
                    }
                }
            }
            LaunchEvent::ChildExited {
                worker, stopped_by, ..
            } => {
                let slot = &mut self.attempts[index];
                if slot.record.worker.as_ref() != Some(&worker) {
                    return self.fault(now, attempt, out);
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
                match event {
                    Some(event) => self.decide(now, event, out),
                    None => Ok(()),
                }
            }
            LaunchEvent::Fault(_) => self.fault(now, attempt, out),
        }
    }

    fn worker(
        &mut self,
        now: MonoTime,
        event: Result<WorkerEvent, WorkerFault>,
        out: &mut Vec<Command>,
    ) -> Result<(), LifecycleError> {
        let attempt = self.current();
        match event {
            Ok(WorkerEvent::Ready { .. }) => {
                if let Some(slot) = self.slot(attempt) {
                    slot.ready = true;
                }
                self.start_job(out);
                Ok(())
            }
            Ok(WorkerEvent::Started { .. }) | Ok(WorkerEvent::Stopped) => Ok(()),
            Ok(WorkerEvent::Finished(finished)) => {
                if let Some(slot) = self.slot(attempt) {
                    slot.terminal_seen = true;
                }
                match finished.result {
                    Ok(outputs) => {
                        self.decide(now, PolicyEvent::Completed, out)?;
                        if self
                            .outcome
                            .as_ref()
                            .is_some_and(|o| o.end == End::Completed)
                        {
                            self.outputs = Some(outputs);
                        }
                        Ok(())
                    }
                    Err(failure) => self.decide(now, PolicyEvent::WorkerFailed(failure.kind), out),
                }
            }
            Err(WorkerFault::Protocol(_)) => match self.phase() {
                Phase::Running { .. } | Phase::CleaningUp { .. } => self.decide(
                    now,
                    PolicyEvent::Observed(Observation::ProtocolViolation),
                    out,
                ),
                _ => Ok(()),
            },
            Err(WorkerFault::Disconnected(_)) => Ok(()),
        }
    }

    fn settle(&mut self, now: MonoTime, out: &mut Vec<Command>) {
        for slot in &mut self.attempts {
            if slot.record.custody == Custody::Pending && reached(slot.settle_by, now) {
                slot.record.custody =
                    Custody::Held("no confirmed cleanup receipt within the cleanup limit".into());
                Self::stop(slot, out);
            }
        }
    }
}

/// The controller's monotonic clock. Tests supply their own.
pub trait Clock {
    fn now(&self) -> MonoTime;
}

pub struct SystemClock(Instant);

impl SystemClock {
    pub fn new() -> Self {
        Self(Instant::now())
    }
}

impl Default for SystemClock {
    fn default() -> Self {
        Self::new()
    }
}

impl Clock for SystemClock {
    fn now(&self) -> MonoTime {
        MonoTime::from_elapsed(self.0.elapsed())
    }
}

/// Everything [`run_job`] needs for one job.
pub struct JobSpec {
    pub job: JobRequest,
    pub worker_version: String,
    pub command: WorkerCommand,
    pub purpose: String,
    pub memory_gib: u32,
    pub limits: Limits,
    /// Each attempt reports into a fresh `attempt-N` folder here.
    pub report_root: PathBuf,
    /// Checkout-lock duplicates; each attempt's custodian gets its own duplicate of each.
    pub custody: Vec<File>,
}

enum Message {
    Launch(AttemptEvent),
    Frame {
        attempt: u32,
        frame: io::Result<Option<Response>>,
    },
    Cancel,
}

/// Cancels a running [`run_job`] from another thread.
#[derive(Clone)]
pub struct Canceller(Sender<Message>);

impl Canceller {
    pub fn cancel(&self) {
        let _ = self.0.send(Message::Cancel);
    }
}

struct Live<A> {
    handle: A,
    session: Session,
    writer: Option<Box<dyn Write + Send>>,
}

fn reader(attempt: u32, mut stream: Box<dyn Read + Send>, sink: Sender<Message>) {
    thread::spawn(move || {
        loop {
            let frame = read_frame::<_, Response>(&mut stream);
            let last = !matches!(frame, Ok(Some(_)));
            if sink.send(Message::Frame { attempt, frame }).is_err() || last {
                return;
            }
        }
    });
}

/// A channel pair for [`run_job`]: hand out the [`Canceller`], pass the other half in.
pub fn job_channel() -> (Canceller, JobInbox) {
    let (sender, receiver) = mpsc::channel();
    (Canceller(sender.clone()), JobInbox { sender, receiver })
}

pub struct JobInbox {
    sender: Sender<Message>,
    receiver: Receiver<Message>,
}

fn fault_of(error: SessionError) -> WorkerFault {
    match error {
        SessionError::Disconnected(message) => WorkerFault::Disconnected(message),
        other => WorkerFault::Protocol(other.to_string()),
    }
}

/// Run one job to a settled [`Report`]: every attempt released or held.
/// `register` must durably add a worker identity to the write lease (B2 `add_worker`).
pub fn run_job<L: WorkerLauncher>(
    launcher: &mut L,
    clock: &dyn Clock,
    spec: &JobSpec,
    inbox: JobInbox,
    register: &mut dyn FnMut(&ProcessIdentity) -> Result<(), String>,
) -> Result<Report, LifecycleError> {
    let (mut lifecycle, first) = Lifecycle::new(clock.now(), spec.limits);
    let mut live: BTreeMap<u32, Live<L::Attempt>> = BTreeMap::new();
    let mut pending: Vec<Input> = vec![];
    let mut commands = first;
    loop {
        for command in std::mem::take(&mut commands) {
            match command {
                Command::Submit { attempt } => {
                    let request = (|| -> io::Result<AdmissionRequest> {
                        let remaining = lifecycle.policy().next_deadline();
                        let queue_limit = remaining.map(|deadline| {
                            // Slightly past the overall deadline, so the policy stops the
                            // attempt first and the guard withdraws it through normal cancel.
                            deadline
                                .elapsed()
                                .saturating_sub(clock.now().elapsed())
                                .saturating_add(spec.limits.cleanup)
                        });
                        Ok(AdmissionRequest {
                            purpose: spec.purpose.clone(),
                            memory_gib: spec.memory_gib,
                            execution_limit: spec.limits.job,
                            queue_limit,
                            report_dir: spec.report_root.join(format!("attempt-{attempt}")),
                            custody: spec
                                .custody
                                .iter()
                                .map(File::try_clone)
                                .collect::<io::Result<_>>()?,
                        })
                    })();
                    let submitted = request.and_then(|request| {
                        launcher.submit(attempt, &spec.command, request, {
                            let sink = inbox.sender.clone();
                            let (events, relay) = mpsc::channel::<AttemptEvent>();
                            thread::spawn(move || {
                                for event in relay {
                                    if sink.send(Message::Launch(event)).is_err() {
                                        return;
                                    }
                                }
                            });
                            events
                        })
                    });
                    match submitted {
                        Ok(mut handle) => {
                            let writer = handle.take_pipes().map(|(response, request)| {
                                reader(attempt, response, inbox.sender.clone());
                                request
                            });
                            live.insert(
                                attempt,
                                Live {
                                    handle,
                                    session: Session::new(spec.worker_version.clone()),
                                    writer,
                                },
                            );
                        }
                        Err(error) => pending.push(Input::SubmitFailed {
                            attempt,
                            reason: error.to_string(),
                        }),
                    }
                }
                Command::RegisterWorker { attempt, worker } => pending.push(Input::Registered {
                    attempt,
                    ok: register(&worker).is_ok(),
                }),
                Command::StartJob { attempt } | Command::Shutdown { attempt } => {
                    if let Some(entry) = live.get_mut(&attempt) {
                        let request = match command {
                            Command::StartJob { .. } => entry.session.run(spec.job.clone()),
                            _ => entry.session.shutdown(),
                        };
                        let sent = request.map_err(fault_of).and_then(|request| {
                            let writer = entry.writer.as_mut().ok_or_else(|| {
                                WorkerFault::Disconnected("no request pipe".into())
                            })?;
                            write_frame(writer, &request)
                                .map_err(|error| WorkerFault::Disconnected(error.to_string()))
                        });
                        if let Err(fault) = sent {
                            pending.push(Input::Worker {
                                attempt,
                                event: Err(fault),
                            });
                        }
                    }
                }
                Command::Stop { attempt } => {
                    if let Some(entry) = live.get_mut(&attempt) {
                        let _ = entry.handle.stop();
                    }
                }
            }
        }
        if let Some(report) = lifecycle.report() {
            return Ok(report);
        }
        let input = match pending.pop() {
            Some(input) => input,
            None => {
                let message = match lifecycle.next_deadline() {
                    Some(deadline) => {
                        let wait = deadline
                            .elapsed()
                            .saturating_sub(clock.now().elapsed())
                            .max(Duration::from_millis(1));
                        match inbox.receiver.recv_timeout(wait) {
                            Ok(message) => Some(message),
                            Err(RecvTimeoutError::Timeout) => None,
                            Err(RecvTimeoutError::Disconnected) => None,
                        }
                    }
                    None => inbox.receiver.recv().ok(),
                };
                match message {
                    None => Input::Tick,
                    Some(Message::Cancel) => Input::Cancel,
                    Some(Message::Launch(event)) => {
                        if matches!(event.event, LaunchEvent::Finished { .. }) {
                            // The admission owner is done; drop its pipes and handle.
                            if let Some(entry) = live.get_mut(&event.attempt) {
                                entry.writer = None;
                            }
                        }
                        Input::Launch(event)
                    }
                    Some(Message::Frame { attempt, frame }) => {
                        let Some(entry) = live.get_mut(&attempt) else {
                            continue;
                        };
                        let event = match frame {
                            Ok(Some(response)) => entry.session.receive(response).map_err(fault_of),
                            Ok(None) => match entry.session.end_of_stream() {
                                Ok(()) => continue,
                                Err(error) => Err(fault_of(error)),
                            },
                            Err(error) => Err(if error.kind() == io::ErrorKind::InvalidData {
                                WorkerFault::Protocol(error.to_string())
                            } else {
                                WorkerFault::Disconnected(error.to_string())
                            }),
                        };
                        Input::Worker { attempt, event }
                    }
                }
            }
        };
        commands = lifecycle.on(clock.now(), input)?;
    }
}
