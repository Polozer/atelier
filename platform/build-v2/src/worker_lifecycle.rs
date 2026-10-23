//! C5b: one job's owned worker lifecycle over guarded attempts, and the C5c session driver.
//!
//! [`Lifecycle`] is a pure state machine: a [`SessionLifecycle`] serving exactly one unit. It
//! combines the guard's observations ([`LaunchEvent`]), the worker session's events and caller
//! cancellation into C5a's [`JobPolicy`], and emits [`Command`]s. It tracks each attempt's custody
//! separately from the policy: an attempt is `Released` only by the guard's confirmed cleanup
//! receipt and `Held` on anything less. Nothing here releases capacity, signals a process or
//! deletes a result. [`run_session`] drives a session with a real [`WorkerLauncher`] and the C1a
//! session; [`run_job`] is a session with one unit.
use crate::failure_policy::{JobPolicy, Limits, MonoTime, Outcome, PolicyError};
use crate::guard_adapter::{
    AdmissionRequest, AttemptEvent, LaunchEvent, WorkerAttempt, WorkerCommand, WorkerLauncher,
};
use crate::leases::ProcessIdentity;
use crate::protocol::{JobOutputs, JobRequest, Request, Response, read_frame, write_frame};
use crate::session_lifecycle::{
    SessionCommand, SessionConfig, SessionInput, SessionLifecycle, UnitId, UnitPlan, UnitRecord,
};
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

/// One job across at most [`crate::failure_policy::MAX_ATTEMPTS`] guarded attempts: a
/// [`SessionLifecycle`] serving exactly one unit, closed at once.
#[derive(Clone, Debug)]
pub struct Lifecycle {
    inner: SessionLifecycle,
}

const JOB_UNIT: &str = "job";

fn commands(commands: Vec<SessionCommand>) -> Vec<Command> {
    commands
        .into_iter()
        .filter_map(|command| match command {
            SessionCommand::Submit { session } => Some(Command::Submit { attempt: session }),
            SessionCommand::Register {
                session, worker, ..
            } => Some(Command::RegisterWorker {
                attempt: session,
                worker,
            }),
            SessionCommand::Run { session, .. } => Some(Command::StartJob { attempt: session }),
            SessionCommand::Shutdown { session } => Some(Command::Shutdown { attempt: session }),
            SessionCommand::Stop { session } => Some(Command::Stop { attempt: session }),
            SessionCommand::Settled { .. } => None,
        })
        .collect()
}

impl Lifecycle {
    /// A queued job: the first command is `Submit { attempt: 1 }`.
    pub fn new(submitted: MonoTime, limits: Limits) -> (Self, Vec<Command>) {
        let mut inner = SessionLifecycle::new(SessionConfig {
            cleanup: limits.cleanup,
        });
        let unit = UnitPlan {
            id: JOB_UNIT.into(),
            limits,
        };
        let mut first = vec![];
        for input in [SessionInput::Submit(unit), SessionInput::Close] {
            first.extend(
                inner
                    .on(submitted, input)
                    .expect("a fresh session accepts one unit and close"),
            );
        }
        (Self { inner }, commands(first))
    }

    pub fn policy(&self) -> &JobPolicy {
        self.inner
            .unit_policy(JOB_UNIT)
            .expect("the lifecycle's one unit")
    }

    pub fn attempts(&self) -> Vec<AttemptRecord> {
        self.inner.sessions()
    }

    /// The finished job, once the outcome is known and every attempt is released or held.
    pub fn report(&self) -> Option<Report> {
        if !self.inner.settled() {
            return None;
        }
        let unit = self.inner.unit(JOB_UNIT)?;
        Some(Report {
            outcome: unit.outcome,
            attempts: self.attempts(),
            outputs: unit.outputs,
            abort: unit.abort,
        })
    }

    /// The next instant a [`Input::Tick`] can change anything.
    pub fn next_deadline(&self) -> Option<MonoTime> {
        self.inner.next_deadline()
    }

    /// @cc [owner:fontanierh,label:correctness] lifecycle-retry-once
    /// Only the guard's exit observation for the pinned worker identity, with no stop or
    /// shutdown requested and no guard or deadline stop, MAY become crash evidence; worker
    /// claims, pipe loss and foreign identities MUST NOT. A retry MUST be submitted only after
    /// the policy's `RequestAdmission`, which follows the previous attempt's confirmed cleanup
    /// receipt, and MUST launch only on the new attempt's own admission. See tests/worker_lifecycle.rs.
    pub fn on(&mut self, now: MonoTime, input: Input) -> Result<Vec<Command>, LifecycleError> {
        let input = match input {
            Input::Launch(event) => SessionInput::Launch(event),
            Input::Worker { attempt, event } => SessionInput::Worker {
                session: attempt,
                event,
            },
            Input::Registered { attempt, ok } => SessionInput::Registered {
                session: attempt,
                unit: JOB_UNIT.into(),
                ok,
            },
            Input::SubmitFailed { attempt, reason } => SessionInput::SubmitFailed {
                session: attempt,
                reason,
            },
            Input::Cancel => SessionInput::CancelAll,
            Input::Tick => SessionInput::Tick,
        };
        self.inner.on(now, input).map(commands)
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

/// Everything [`run_session`] needs for one session of compatible units.
pub struct SessionSpec {
    pub worker_version: String,
    pub command: WorkerCommand,
    pub purpose: String,
    pub memory_gib: u32,
    pub config: SessionConfig,
    /// The guard's execution limit for each session: a backstop, separate from unit job limits.
    pub execution_limit: Duration,
    /// Each session reports into a fresh `attempt-N` folder here.
    pub report_root: PathBuf,
    /// Checkout-lock duplicates; each session's custodian gets its own duplicate of each.
    pub custody: Vec<File>,
}

/// One unit for [`run_session`]: its lifecycle plan and the job request it runs.
#[derive(Clone, Debug)]
pub struct SessionUnit {
    pub plan: UnitPlan,
    pub job: JobRequest,
}

/// A settled session: every unit's record and every session's custody.
#[derive(Clone, Debug, PartialEq)]
pub struct SessionReport {
    pub sessions: Vec<AttemptRecord>,
    pub units: Vec<UnitRecord>,
}

enum Message {
    Launch(AttemptEvent),
    Frame {
        attempt: u32,
        frame: io::Result<Option<Response>>,
    },
    WriteFailed {
        attempt: u32,
        error: String,
    },
    Submit(Box<SessionUnit>),
    CancelUnit(UnitId),
    Cancel,
    Close,
}

/// Cancels a running [`run_job`] or [`run_session`] from another thread.
#[derive(Clone)]
pub struct Canceller(Sender<Message>);

impl Canceller {
    pub fn cancel(&self) {
        let _ = self.0.send(Message::Cancel);
    }
}

/// Feeds a running [`run_session`] from another thread.
#[derive(Clone)]
pub struct SessionHandle(Sender<Message>);

impl SessionHandle {
    pub fn submit(&self, unit: SessionUnit) {
        let _ = self.0.send(Message::Submit(Box::new(unit)));
    }
    pub fn cancel(&self, unit: &str) {
        let _ = self.0.send(Message::CancelUnit(unit.into()));
    }
    pub fn cancel_all(&self) {
        let _ = self.0.send(Message::Cancel);
    }
    /// No more units: drain, then end the session gracefully.
    pub fn close(&self) {
        let _ = self.0.send(Message::Close);
    }
}

struct Live<A> {
    handle: A,
    session: Session,
    /// Queue to the attempt's writer thread; dropping it closes the request pipe once the
    /// thread finishes any write in progress.
    writer: Option<Sender<Request>>,
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

/// Requests are written on their own thread, so a worker that stops reading can never block
/// the lifecycle's deadline, cancellation or stop handling (failure-policy-time-limits). A
/// blocked write ends when the guard stops the worker and the pipe closes.
fn writer(
    attempt: u32,
    mut stream: Box<dyn Write + Send>,
    sink: Sender<Message>,
) -> Sender<Request> {
    let (requests, queue) = mpsc::channel::<Request>();
    thread::spawn(move || {
        for request in queue {
            if let Err(error) = write_frame(&mut stream, &request) {
                let _ = sink.send(Message::WriteFailed {
                    attempt,
                    error: error.to_string(),
                });
                return;
            }
        }
    });
    requests
}

/// A channel pair for [`run_job`]: hand out the [`Canceller`], pass the other half in.
pub fn job_channel() -> (Canceller, JobInbox) {
    let (sender, receiver) = mpsc::channel();
    (Canceller(sender.clone()), JobInbox { sender, receiver })
}

/// A channel pair for [`run_session`]: hand out the [`SessionHandle`], pass the other half in.
pub fn session_channel() -> (SessionHandle, JobInbox) {
    let (sender, receiver) = mpsc::channel();
    (SessionHandle(sender.clone()), JobInbox { sender, receiver })
}

pub struct JobInbox {
    sender: Sender<Message>,
    receiver: Receiver<Message>,
}

fn send<A>(entry: &Live<A>, request: Request) -> Result<(), WorkerFault> {
    let writer = entry
        .writer
        .as_ref()
        .ok_or_else(|| WorkerFault::Disconnected("no request pipe".into()))?;
    writer
        .send(request)
        .map_err(|_| WorkerFault::Disconnected("the request pipe closed".into()))
}

fn fault_of(error: SessionError) -> WorkerFault {
    match error {
        SessionError::Disconnected(message) => WorkerFault::Disconnected(message),
        other => WorkerFault::Protocol(other.to_string()),
    }
}

/// Run one job to a settled [`Report`]: every attempt released or held. It is a session with
/// one unit, closed at once. `register` must durably add a worker identity to the write lease
/// (B2 `add_worker`).
pub fn run_job<L: WorkerLauncher>(
    launcher: &mut L,
    clock: &dyn Clock,
    spec: &JobSpec,
    inbox: JobInbox,
    register: &mut dyn FnMut(&ProcessIdentity) -> Result<(), String>,
) -> Result<Report, LifecycleError> {
    let session = SessionSpec {
        worker_version: spec.worker_version.clone(),
        command: spec.command.clone(),
        purpose: spec.purpose.clone(),
        memory_gib: spec.memory_gib,
        config: SessionConfig {
            cleanup: spec.limits.cleanup,
        },
        execution_limit: spec.limits.job,
        report_root: spec.report_root.clone(),
        custody: spec
            .custody
            .iter()
            .map(File::try_clone)
            .collect::<io::Result<_>>()
            .map_err(|error| {
                LifecycleError::Invariant(format!("cannot duplicate custody: {error}"))
            })?,
    };
    let _ = inbox.sender.send(Message::Submit(Box::new(SessionUnit {
        plan: UnitPlan {
            id: JOB_UNIT.into(),
            limits: spec.limits,
        },
        job: spec.job.clone(),
    })));
    let _ = inbox.sender.send(Message::Close);
    let (published, _records) = mpsc::channel();
    let report = run_session(
        launcher,
        clock,
        &session,
        inbox,
        &mut |_, worker| register(worker),
        published,
    )?;
    let unit = report
        .units
        .into_iter()
        .next()
        .ok_or_else(|| LifecycleError::Invariant("the job's unit is missing".into()))?;
    Ok(Report {
        outcome: unit.outcome,
        attempts: report.sessions,
        outputs: unit.outputs,
        abort: unit.abort,
    })
}

/// @cc [owner:fontanierh,label:correctness] session-publication-off-lifecycle
/// A settled unit's record MUST be handed off through `published` without waiting on its
/// receiver, so publication never blocks the lifecycle's deadlines, cancellation or stops.
/// See tests/guard_adapter.rs
/// (`run_session_hands_each_settled_unit_off_without_waiting_for_its_receiver`).
///
/// Run a session of compatible units to a settled [`SessionReport`]: every unit released or held,
/// after [`SessionHandle::close`]. `register` must durably add the session's worker identity to
/// the unit's write lease (B2 `add_worker`) before that unit runs.
pub fn run_session<L: WorkerLauncher>(
    launcher: &mut L,
    clock: &dyn Clock,
    spec: &SessionSpec,
    inbox: JobInbox,
    register: &mut dyn FnMut(&UnitId, &ProcessIdentity) -> Result<(), String>,
    published: Sender<UnitRecord>,
) -> Result<SessionReport, LifecycleError> {
    let mut lifecycle = SessionLifecycle::new(spec.config);
    let mut jobs: BTreeMap<UnitId, JobRequest> = BTreeMap::new();
    let mut live: BTreeMap<u32, Live<L::Attempt>> = BTreeMap::new();
    let mut pending: Vec<SessionInput> = vec![];
    let mut commands: Vec<SessionCommand> = vec![];
    let mut closed = false;
    loop {
        for command in std::mem::take(&mut commands) {
            match command {
                SessionCommand::Submit { session } => {
                    let request = (|| -> io::Result<AdmissionRequest> {
                        let queue_limit = lifecycle.queue_deadline().map(|deadline| {
                            // Slightly past the overall deadline, so the policy stops the
                            // attempt first and the guard withdraws it through normal cancel.
                            deadline
                                .elapsed()
                                .saturating_sub(clock.now().elapsed())
                                .saturating_add(spec.config.cleanup)
                        });
                        Ok(AdmissionRequest {
                            purpose: spec.purpose.clone(),
                            memory_gib: spec.memory_gib,
                            execution_limit: spec.execution_limit,
                            queue_limit,
                            report_dir: spec.report_root.join(format!("attempt-{session}")),
                            custody: spec
                                .custody
                                .iter()
                                .map(File::try_clone)
                                .collect::<io::Result<_>>()?,
                        })
                    })();
                    let submitted = request.and_then(|request| {
                        launcher.submit(session, &spec.command, request, {
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
                                reader(session, response, inbox.sender.clone());
                                writer(session, request, inbox.sender.clone())
                            });
                            live.insert(
                                session,
                                Live {
                                    handle,
                                    session: Session::new(spec.worker_version.clone()),
                                    writer,
                                },
                            );
                        }
                        Err(error) => pending.push(SessionInput::SubmitFailed {
                            session,
                            reason: error.to_string(),
                        }),
                    }
                }
                SessionCommand::Register {
                    session,
                    unit,
                    worker,
                } => {
                    let ok = register(&unit, &worker).is_ok();
                    pending.push(SessionInput::Registered { session, unit, ok });
                }
                SessionCommand::Run { session, unit } => {
                    let Some(entry) = live.get_mut(&session) else {
                        continue;
                    };
                    let request = match jobs.get(&unit) {
                        Some(job) => entry.session.run(job.clone()).map_err(fault_of),
                        None => Err(WorkerFault::Protocol(format!(
                            "no job request for unit {unit}"
                        ))),
                    };
                    if let Err(fault) = request.and_then(|request| send(entry, request)) {
                        pending.push(SessionInput::Worker {
                            session,
                            event: Err(fault),
                        });
                    }
                }
                SessionCommand::Shutdown { session } => {
                    let Some(entry) = live.get_mut(&session) else {
                        continue;
                    };
                    let request = entry.session.shutdown().map_err(fault_of);
                    if let Err(fault) = request.and_then(|request| send(entry, request)) {
                        pending.push(SessionInput::Worker {
                            session,
                            event: Err(fault),
                        });
                    }
                }
                SessionCommand::Stop { session } => {
                    if let Some(entry) = live.get_mut(&session) {
                        let _ = entry.handle.stop();
                    }
                }
                SessionCommand::Settled { unit } => {
                    if let Some(record) = lifecycle.unit(&unit) {
                        // An unbounded channel: a slow or absent receiver never blocks here.
                        let _ = published.send(record);
                    }
                }
            }
        }
        if closed && lifecycle.done() {
            return Ok(SessionReport {
                sessions: lifecycle.sessions(),
                units: jobs
                    .keys()
                    .filter_map(|unit| lifecycle.unit(unit))
                    .collect(),
            });
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
                    None => SessionInput::Tick,
                    Some(Message::Cancel) => {
                        closed = true;
                        SessionInput::CancelAll
                    }
                    Some(Message::Close) => {
                        closed = true;
                        SessionInput::Close
                    }
                    Some(Message::CancelUnit(unit)) => SessionInput::CancelUnit(unit),
                    Some(Message::Submit(unit)) => {
                        if closed || jobs.contains_key(&unit.plan.id) {
                            continue; // refused: the session is closed or the unit is known
                        }
                        jobs.insert(unit.plan.id.clone(), unit.job);
                        SessionInput::Submit(unit.plan)
                    }
                    Some(Message::WriteFailed { attempt, error }) => SessionInput::Worker {
                        session: attempt,
                        event: Err(WorkerFault::Disconnected(error)),
                    },
                    Some(Message::Launch(event)) => {
                        if matches!(event.event, LaunchEvent::Finished { .. }) {
                            // The admission owner is done; drop its pipes and handle.
                            if let Some(entry) = live.get_mut(&event.attempt) {
                                entry.writer = None;
                            }
                        }
                        SessionInput::Launch(event)
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
                        SessionInput::Worker {
                            session: attempt,
                            event,
                        }
                    }
                }
            }
        };
        commands = lifecycle.on(clock.now(), input)?;
    }
}
