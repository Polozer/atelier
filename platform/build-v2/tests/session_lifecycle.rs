//! T0 tests of the pure C5c session lifecycle: units queued behind one guarded session at a
//! time, each with its own C5a policy. Times are milliseconds from the session's start.
use atelier_build_v2::failure_policy::{CleanupState, End, Expiry, Limits, MonoTime, Stop};
use atelier_build_v2::guard_adapter::{AttemptEvent, CleanupReceipt, ExitInfo, LaunchEvent};
use atelier_build_v2::leases::ProcessIdentity;
use atelier_build_v2::protocol::JobOutputs;
use atelier_build_v2::session_lifecycle::*;
use atelier_build_v2::worker_lifecycle::{Custody, LifecycleError};
use atelier_build_v2::worker_session::{Event as WorkerEvent, JobFinished};
use std::path::PathBuf;
use std::time::Duration;

const JOB: u64 = 60_000;
const CLEAN: u64 = 5_000;

fn t(ms: u64) -> MonoTime {
    MonoTime::from_elapsed(Duration::from_millis(ms))
}

fn worker(pid: u32) -> ProcessIdentity {
    ProcessIdentity {
        pid,
        boot: "boot-1".into(),
        started: format!("start-{pid}"),
    }
}

fn limits(overall: Option<u64>) -> Limits {
    Limits {
        job: Duration::from_millis(JOB),
        cleanup: Duration::from_millis(CLEAN),
        overall: overall.map(Duration::from_millis),
    }
}

fn plan(id: &str, overall: Option<u64>) -> SessionInput {
    SessionInput::Submit(UnitPlan {
        id: id.into(),
        limits: limits(overall),
    })
}

fn confirmed() -> LaunchEvent {
    LaunchEvent::Finished {
        cleanup: CleanupReceipt::Confirmed,
        receipts: PathBuf::from("receipts"),
    }
}

fn unconfirmed(reason: &str) -> LaunchEvent {
    LaunchEvent::Finished {
        cleanup: CleanupReceipt::Unconfirmed {
            reason: reason.into(),
        },
        receipts: PathBuf::from("receipts"),
    }
}

fn completed(job: &str) -> WorkerEvent {
    WorkerEvent::Finished(JobFinished {
        job_id: job.into(),
        result: Ok(JobOutputs {
            files: vec![format!("{job}.glb")],
        }),
        cancel_requested: false,
    })
}

struct Sim {
    lifecycle: SessionLifecycle,
    log: Vec<SessionCommand>,
}

impl Sim {
    fn new() -> Self {
        Self {
            lifecycle: SessionLifecycle::new(SessionConfig {
                cleanup: Duration::from_millis(CLEAN),
            }),
            log: vec![],
        }
    }

    fn at(&mut self, ms: u64, input: SessionInput) -> Vec<SessionCommand> {
        let commands = self
            .lifecycle
            .on(t(ms), input.clone())
            .unwrap_or_else(|error| panic!("{input:?}: {error:?}"));
        self.log.extend(commands.clone());
        commands
    }

    fn launch(&mut self, ms: u64, session: u32, event: LaunchEvent) -> Vec<SessionCommand> {
        self.at(
            ms,
            SessionInput::Launch(AttemptEvent {
                attempt: session,
                event,
            }),
        )
    }

    fn worker(&mut self, ms: u64, session: u32, event: WorkerEvent) -> Vec<SessionCommand> {
        self.at(
            ms,
            SessionInput::Worker {
                session,
                event: Ok(event),
            },
        )
    }

    /// Admission, the pinned worker, lease registration for `unit` and hello: `unit` runs.
    fn start(&mut self, ms: u64, session: u32, pid: u32, unit: &str) {
        assert_eq!(self.launch(ms, session, LaunchEvent::Admitted), vec![]);
        assert_eq!(
            self.launch(
                ms,
                session,
                LaunchEvent::ChildStarted {
                    worker: worker(pid)
                }
            ),
            vec![SessionCommand::Register {
                session,
                unit: unit.into(),
                worker: worker(pid)
            }]
        );
        assert_eq!(
            self.at(
                ms,
                SessionInput::Registered {
                    session,
                    unit: unit.into(),
                    ok: true
                }
            ),
            vec![]
        );
        assert_eq!(
            self.worker(
                ms,
                session,
                WorkerEvent::Ready {
                    worker_version: "w1".into()
                }
            ),
            vec![SessionCommand::Run {
                session,
                unit: unit.into()
            }]
        );
    }

    fn submits(&self) -> Vec<u32> {
        self.log
            .iter()
            .filter_map(|c| match c {
                SessionCommand::Submit { session } => Some(*session),
                _ => None,
            })
            .collect()
    }

    fn settled(&self) -> Vec<String> {
        self.log
            .iter()
            .filter_map(|c| match c {
                SessionCommand::Settled { unit } => Some(unit.clone()),
                _ => None,
            })
            .collect()
    }
}

#[test]
fn units_run_in_order_one_session_at_a_time() {
    let mut sim = Sim::new();
    assert_eq!(
        sim.at(0, plan("a", None)),
        vec![SessionCommand::Submit { session: 1 }]
    );
    assert_eq!(
        sim.at(0, plan("b", None)),
        vec![],
        "one admission at a time"
    );
    sim.at(0, SessionInput::Close);
    sim.start(10, 1, 101, "a");
    assert_eq!(
        sim.worker(100, 1, completed("a")),
        vec![SessionCommand::Shutdown { session: 1 }]
    );
    sim.worker(110, 1, WorkerEvent::Stopped);
    sim.launch(120, 1, exited(101));
    assert_eq!(
        sim.launch(130, 1, confirmed()),
        vec![
            SessionCommand::Submit { session: 2 },
            SessionCommand::Settled { unit: "a".into() }
        ],
        "the next session is queued only after the previous one is confirmed clean"
    );
    sim.start(200, 2, 202, "b");
    sim.worker(300, 2, completed("b"));
    sim.launch(310, 2, exited(202));
    sim.launch(320, 2, confirmed());
    assert!(sim.lifecycle.done());
    assert_eq!(sim.settled(), vec!["a".to_string(), "b".to_string()]);
    let a = sim.lifecycle.unit("a").unwrap();
    assert_eq!(a.outcome.end, End::Completed);
    assert_eq!(
        a.attempts,
        vec![UnitAttemptRecord {
            attempt: 1,
            session: 1,
            custody: Custody::Released
        }]
    );
    assert_eq!(sim.lifecycle.unit("b").unwrap().attempts[0].session, 2);
}

fn exited(pid: u32) -> LaunchEvent {
    LaunchEvent::ChildExited {
        worker: worker(pid),
        exit: ExitInfo::Code(0),
        stopped_by: None,
    }
}

#[test]
fn a_crash_retry_joins_a_later_session_only_after_confirmed_cleanup() {
    let mut sim = Sim::new();
    sim.at(0, plan("a", None));
    sim.at(0, plan("b", None));
    sim.at(0, SessionInput::Close);
    sim.start(10, 1, 101, "a");
    // The pinned worker exited with no stop requested: crash evidence for "a" only.
    assert_eq!(
        sim.launch(
            100,
            1,
            LaunchEvent::ChildExited {
                worker: worker(101),
                exit: ExitInfo::Signal(9),
                stopped_by: None
            }
        ),
        vec![]
    );
    assert_eq!(
        sim.at(200, SessionInput::Tick),
        vec![],
        "no session before the receipt"
    );
    assert_eq!(
        sim.launch(300, 1, confirmed()),
        vec![SessionCommand::Submit { session: 2 }]
    );
    // The retry is first in line; its second attempt runs in session 2.
    sim.start(400, 2, 202, "a");
    sim.worker(500, 2, completed("a"));
    sim.launch(510, 2, exited(202));
    sim.launch(520, 2, confirmed());
    sim.start(600, 3, 303, "b");
    sim.worker(700, 3, completed("b"));
    sim.launch(710, 3, exited(303));
    sim.launch(720, 3, confirmed());
    assert!(sim.lifecycle.done());
    let a = sim.lifecycle.unit("a").unwrap();
    assert_eq!(a.outcome.end, End::Completed);
    assert_eq!(a.outcome.attempts, 2);
    assert_eq!(
        a.attempts.iter().map(|x| x.session).collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert_eq!(sim.submits(), vec![1, 2, 3]);
}

#[test]
fn a_held_session_starts_no_further_session() {
    let mut sim = Sim::new();
    sim.at(0, plan("a", None));
    sim.at(0, plan("b", None));
    sim.at(0, SessionInput::Close);
    sim.start(10, 1, 101, "a");
    sim.launch(
        100,
        1,
        LaunchEvent::ChildExited {
            worker: worker(101),
            exit: ExitInfo::Signal(9),
            stopped_by: None,
        },
    );
    assert_eq!(
        sim.launch(200, 1, unconfirmed("tree cleanup incomplete")),
        vec![SessionCommand::Settled { unit: "b".into() }],
        "the waiting unit gives up; nothing new is queued"
    );
    let b = sim.lifecycle.unit("b").unwrap();
    assert_eq!(b.outcome.end, End::Failed(Stop::Cancelled));
    assert!(b.abort.unwrap().contains("unconfirmed"));
    assert!(b.attempts.is_empty(), "b never started");
    sim.at(100 + CLEAN, SessionInput::Tick);
    let a = sim.lifecycle.unit("a").unwrap();
    assert_eq!(
        a.outcome.cleanup,
        CleanupState::Unconfirmed(Expiry::CleanupLimit)
    );
    assert_eq!(
        a.attempts[0].custody,
        Custody::Held("tree cleanup incomplete".into())
    );
    assert_eq!(sim.submits(), vec![1]);
    assert!(sim.lifecycle.done());
}

#[test]
fn cancelling_one_waiting_unit_keeps_the_session_for_the_others() {
    let mut sim = Sim::new();
    sim.at(0, plan("a", None));
    sim.at(0, plan("b", None));
    assert_eq!(
        sim.at(5, SessionInput::CancelUnit("a".into())),
        vec![SessionCommand::Settled { unit: "a".into() }],
        "no stop: b still needs the session"
    );
    sim.start(10, 1, 101, "b");
    assert_eq!(
        sim.lifecycle.unit("a").unwrap().outcome.end,
        End::Failed(Stop::Cancelled)
    );
    // Cancelling the running unit stops the session through the guard.
    assert_eq!(
        sim.at(20, SessionInput::CancelUnit("b".into())),
        vec![SessionCommand::Stop { session: 1 }]
    );
}

#[test]
fn units_that_expire_while_waiting_withdraw_the_request_within_their_deadline() {
    let mut sim = Sim::new();
    sim.at(0, plan("a", Some(1_000)));
    sim.at(0, plan("b", Some(2_000)));
    sim.at(0, SessionInput::Close);
    assert_eq!(sim.lifecycle.queue_deadline(), Some(t(2_000)));
    assert_eq!(
        sim.at(1_000, SessionInput::Tick),
        vec![SessionCommand::Settled { unit: "a".into() }],
        "b still waits"
    );
    assert_eq!(
        sim.at(2_000, SessionInput::Tick),
        vec![
            SessionCommand::Stop { session: 1 },
            SessionCommand::Settled { unit: "b".into() }
        ]
    );
    // The withdrawn request settles no later than the last deadline: held, never released.
    assert!(sim.lifecycle.done());
    assert!(matches!(
        sim.lifecycle.sessions()[0].custody,
        Custody::Held(_)
    ));
}

#[test]
fn a_unit_after_close_or_twice_is_refused() {
    let mut sim = Sim::new();
    sim.at(0, plan("a", None));
    assert!(matches!(
        sim.lifecycle.on(t(1), plan("a", None)),
        Err(LifecycleError::Invariant(_))
    ));
    sim.at(2, SessionInput::Close);
    assert!(matches!(
        sim.lifecycle.on(t(3), plan("b", None)),
        Err(LifecycleError::Invariant(_))
    ));
}

#[test]
fn session_commands_never_delete_or_republish() {
    let mut sim = Sim::new();
    sim.at(0, plan("a", None));
    sim.at(0, SessionInput::Close);
    sim.start(10, 1, 101, "a");
    sim.worker(100, 1, completed("a"));
    sim.at(150, SessionInput::CancelAll);
    sim.launch(200, 1, exited(101));
    sim.launch(210, 1, confirmed());
    assert_eq!(sim.lifecycle.unit("a").unwrap().outcome.end, End::Completed);
    for command in &sim.log {
        assert!(matches!(
            command,
            SessionCommand::Submit { .. }
                | SessionCommand::Register { .. }
                | SessionCommand::Run { .. }
                | SessionCommand::Shutdown { .. }
                | SessionCommand::Stop { .. }
                | SessionCommand::Settled { .. }
        ));
    }
    assert!(!sim.log.contains(&SessionCommand::Stop { session: 1 }));
}
