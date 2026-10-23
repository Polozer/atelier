//! T0 real-process tests of the guard adapter and job driver, with a stand-in bridge
//! (tests/fixtures/fake_bridge.py) instead of real admission, and a disposable Python worker that
//! owns one descendant. Every wait is a bounded handshake; nothing sleeps.
use atelier_build_v2::failure_policy::{CleanupState, End, Limits, Stop};
use atelier_build_v2::guard_adapter::*;
use atelier_build_v2::leases::ProcessIdentity;
use atelier_build_v2::protocol::{JobRequest, Response, read_frame};
use atelier_build_v2::schema::{Op, OutputFile};
use atelier_build_v2::worker_lifecycle::*;
use serde_json::Value;
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

static SERIAL: AtomicU64 = AtomicU64::new(0);
/// One bound for every handshake in these tests.
const BOUND: Duration = Duration::from_secs(5);

struct Workspace(PathBuf);
impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "atelier-v2-guard-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

fn launcher(scenario: &str) -> GuardedLauncher {
    GuardedLauncher {
        bridge: vec![
            "python3".into(),
            fixture("fake_bridge.py").into(),
            scenario.into(),
        ],
    }
}

fn worker(space: &Workspace, scenario: &str) -> WorkerCommand {
    let mut env = BTreeMap::new();
    env.insert("PATH".into(), std::env::var("PATH").unwrap());
    env.insert(
        "WORKER_FD_REPORT".into(),
        space.path("worker-fds.json").display().to_string(),
    );
    env.insert(
        "CRASH_MARKER".into(),
        space.path("crash-marker").display().to_string(),
    );
    WorkerCommand {
        program: "python3".into(),
        args: vec![fixture("disposable_worker.py").into(), scenario.into()],
        env,
        cwd: space.0.clone(),
    }
}

fn request(space: &Workspace, name: &str, custody: Vec<File>) -> AdmissionRequest {
    AdmissionRequest {
        purpose: "build-v2 T0 fake guard".into(),
        memory_gib: 1,
        execution_limit: Duration::from_secs(30),
        queue_limit: None,
        report_dir: space.path(name),
        custody,
    }
}

fn next(events: &mpsc::Receiver<AttemptEvent>) -> LaunchEvent {
    events
        .recv_timeout(BOUND)
        .expect("bridge event within bound")
        .event
}

/// A conflicting installer: a separate open file description asking for exclusion.
fn try_exclusive(path: &Path) -> bool {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    // SAFETY: flock on a descriptor we own.
    unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) == 0 }
}

/// The installer gets exclusion within the bound: a blocking flock in a helper thread, so a
/// concurrent test's fork (which briefly shares every descriptor until exec) cannot flake it.
fn acquired_within(path: &Path, bound: Duration) -> bool {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    let (done, acquired) = mpsc::channel();
    thread::spawn(move || {
        // SAFETY: flock on a descriptor this thread owns.
        let ok = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) == 0 };
        let _ = done.send(ok);
    });
    acquired.recv_timeout(bound).unwrap_or(false)
}

fn locked(path: &Path) -> File {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .unwrap();
    // SAFETY: flock on a descriptor we own.
    assert_eq!(
        unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) },
        0
    );
    file
}

fn json(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn inode(file: &File) -> (u64, u64) {
    let meta = file.metadata().unwrap();
    (meta.dev(), meta.ino())
}

fn holds(record: &Value, wanted: (u64, u64)) -> bool {
    record["open"]
        .as_object()
        .unwrap()
        .values()
        .any(|pair| (pair[0].as_u64().unwrap(), pair[1].as_u64().unwrap()) == wanted)
}

#[test]
fn bridge_events_decode_strictly() {
    let receipts = Path::new("r");
    assert_eq!(
        decode_event(r#"{"event":"queued"}"#, receipts),
        LaunchEvent::Queued
    );
    assert_eq!(
        decode_event(
            r#"{"event":"child_exited","pid":7,"started":"s","boot":"b","returncode":-9,"stopped_by":null}"#,
            receipts
        ),
        LaunchEvent::ChildExited {
            worker: ProcessIdentity {
                pid: 7,
                boot: "b".into(),
                started: "s".into()
            },
            exit: ExitInfo::Signal(9),
            stopped_by: None,
        }
    );
    for bad in [
        "not json",
        r#"{"event":"queued","extra":1}"#,
        r#"{"event":"child_started","pid":0,"started":"s","boot":"b"}"#,
        r#"{"event":"child_started","pid":7,"started":"","boot":"b"}"#,
        r#"{"event":"finished","cleanup":"probably","reason":null}"#,
    ] {
        assert!(
            matches!(decode_event(bad, receipts), LaunchEvent::Fault(_)),
            "{bad}"
        );
    }
}

#[test]
fn bridge_alone_receives_its_descriptors_and_the_worker_only_the_protocol_pipe() {
    let space = Workspace::new();
    let lock_path = space.path("checkout.lock");
    let original = locked(&lock_path);
    let custody = original.try_clone().unwrap();
    let custody_inode = inode(&custody);
    let (sink, events) = mpsc::channel();
    let mut attempt = launcher("normal")
        .submit(
            1,
            &worker(&space, "normal"),
            request(&space, "attempt-1", vec![custody]),
            sink,
        )
        .unwrap();
    assert_eq!(next(&events), LaunchEvent::Queued);
    assert_eq!(next(&events), LaunchEvent::Admitted);
    assert!(matches!(next(&events), LaunchEvent::ChildStarted { .. }));
    let (mut response, request) = attempt.take_pipes().unwrap();
    let hello = read_frame::<_, Response>(&mut response).unwrap();
    assert!(matches!(hello, Some(Response::Hello { .. })));
    drop((response, request)); // the worker then sees EOF and exits cleanly
    assert!(matches!(
        next(&events),
        LaunchEvent::ChildExited {
            exit: ExitInfo::Code(0),
            stopped_by: None,
            ..
        }
    ));
    assert!(matches!(
        next(&events),
        LaunchEvent::Finished {
            cleanup: CleanupReceipt::Confirmed,
            ..
        }
    ));
    attempt.wait().unwrap();
    let bridge = json(&space.path("attempt-1/inherited.json"));
    let open = bridge["open"].as_object().unwrap();
    let mut expected: Vec<i64> = ["events", "liveness", "spec", "request", "response"]
        .iter()
        .map(|name| bridge[*name].as_i64().unwrap())
        .chain(
            bridge["custody"]
                .as_array()
                .unwrap()
                .iter()
                .map(|fd| fd.as_i64().unwrap()),
        )
        .collect();
    expected.sort();
    let mut got: Vec<i64> = open.keys().map(|fd| fd.parse().unwrap()).collect();
    got.sort();
    assert_eq!(
        got, expected,
        "the bridge inherits exactly its own descriptors"
    );
    assert!(holds(&bridge, custody_inode));
    assert_eq!(
        bridge["cwd"].as_str().map(PathBuf::from),
        Some(fs::canonicalize(&space.0).unwrap())
    );
    let worker_fds = json(&space.path("worker-fds.json"));
    let mut worker_open: Vec<i64> = worker_fds["open"]
        .as_object()
        .unwrap()
        .keys()
        .map(|fd| fd.parse().unwrap())
        .collect();
    worker_open.sort();
    let mut protocol = vec![
        worker_fds["request_fd"].as_i64().unwrap(),
        worker_fds["response_fd"].as_i64().unwrap(),
    ];
    protocol.sort();
    assert_eq!(
        worker_open, protocol,
        "the worker inherits only the protocol pipe"
    );
    assert!(
        !holds(&worker_fds, custody_inode),
        "custody never reaches the worker"
    );
    drop(original);
}

#[test]
fn stop_signals_only_the_unreaped_bridge_and_never_a_stale_pid() {
    let space = Workspace::new();
    let (sink, events) = mpsc::channel();
    let mut attempt = launcher("queue_forever")
        .submit(
            1,
            &worker(&space, "normal"),
            request(&space, "attempt-1", vec![]),
            sink,
        )
        .unwrap();
    assert_eq!(next(&events), LaunchEvent::Queued);
    // A queued stop withdraws: no child was spawned and the receipt confirms it.
    assert!(attempt.stop().unwrap());
    assert!(matches!(
        next(&events),
        LaunchEvent::Finished {
            cleanup: CleanupReceipt::Confirmed,
            ..
        }
    ));
    attempt.wait().unwrap();
    assert!(
        !space.path("attempt-1/stdout.log").exists(),
        "no worker was started"
    );
    // Exited and reaped: its PID is no longer ours, so nothing is signalled.
    assert!(!attempt.stop().unwrap());
    assert!(!attempt.stop().unwrap());
}

#[test]
fn custody_duplicate_keeps_exclusion_after_the_launcher_drops_its_own_descriptor() {
    let space = Workspace::new();
    let lock_path = space.path("checkout.lock");
    let original = locked(&lock_path);
    // The same open file description (F_DUPFD_CLOEXEC), as B3's duplicate_for_custodian returns.
    let custody = original.try_clone().unwrap();
    let (sink, events) = mpsc::channel();
    let mut attempt = launcher("queue_forever")
        .submit(
            1,
            &worker(&space, "normal"),
            request(&space, "attempt-1", vec![custody]),
            sink,
        )
        .unwrap();
    assert_eq!(next(&events), LaunchEvent::Queued);
    // Closing the launcher's own descriptor does not unlock: BSD flock, no LOCK_UN on drop.
    drop(original);
    assert!(
        !try_exclusive(&lock_path),
        "the custodian's duplicate still excludes installers"
    );
    assert!(attempt.stop().unwrap());
    assert!(matches!(next(&events), LaunchEvent::Finished { .. }));
    attempt.wait().unwrap();
    // The last descriptor of the description closed with the custodian.
    assert!(acquired_within(&lock_path, BOUND));
}

#[test]
fn controller_loss_stops_the_attempt_through_the_liveness_pipe() {
    let space = Workspace::new();
    let (sink, events) = mpsc::channel();
    let attempt = launcher("queue_forever")
        .submit(
            1,
            &worker(&space, "normal"),
            request(&space, "attempt-1", vec![]),
            sink,
        )
        .unwrap();
    assert_eq!(next(&events), LaunchEvent::Queued);
    drop(attempt);
    assert!(matches!(next(&events), LaunchEvent::Finished { .. }));
    assert!(space.path("attempt-1/liveness-eof").exists());
}

fn job() -> JobRequest {
    JobRequest {
        job_id: "job".into(),
        unit: "fixture/piece".into(),
        op: Op {
            kind: "fixture".into(),
            version: "1".into(),
        },
        job_dir: "/jobs/job".into(),
        script: "code/run.py".into(),
        code: vec!["code/run.py".into()],
        inputs: vec![],
        params: Default::default(),
        outputs: vec![OutputFile {
            path: "piece.glb".into(),
            install_path: None,
            required: true,
        }],
    }
}

fn spec(space: &Workspace, scenario: &str, cleanup_ms: u64) -> JobSpec {
    JobSpec {
        job: job(),
        worker_version: "disposable-1".into(),
        command: worker(space, scenario),
        purpose: "build-v2 T0 fake guard".into(),
        memory_gib: 1,
        limits: Limits {
            job: Duration::from_secs(30),
            cleanup: Duration::from_millis(cleanup_ms),
            overall: Some(Duration::from_secs(60)),
        },
        report_root: space.0.clone(),
        custody: vec![],
    }
}

fn drive(
    scenario: &str,
    bridge: &str,
    cancel_on_register: bool,
    cleanup_ms: u64,
) -> (Report, Vec<ProcessIdentity>, Workspace) {
    let space = Workspace::new();
    let spec = spec(&space, scenario, cleanup_ms);
    let (canceller, inbox) = job_channel();
    let mut registered = vec![];
    let report = run_job(
        &mut launcher(bridge),
        &SystemClock::new(),
        &spec,
        inbox,
        &mut |worker| {
            registered.push(worker.clone());
            if cancel_on_register {
                canceller.cancel();
            }
            Ok(())
        },
    )
    .unwrap();
    (report, registered, space)
}

#[test]
fn driver_runs_a_job_over_dedicated_pipes_and_registers_the_worker_first() {
    let (report, registered, _space) = drive("normal", "normal", false, 3_000);
    assert_eq!(report.outcome.end, End::Completed);
    assert_eq!(report.outputs.unwrap().files, vec!["piece.glb".to_string()]);
    assert_eq!(report.attempts.len(), 1);
    assert_eq!(report.attempts[0].custody, Custody::Released);
    assert_eq!(registered, vec![report.attempts[0].worker.clone().unwrap()]);
}

#[test]
fn driver_retries_one_crash_with_a_fresh_admission_and_report_folder() {
    let (report, registered, space) = drive("crash_once", "normal", false, 3_000);
    assert_eq!(report.outcome.end, End::Completed);
    assert_eq!(report.outcome.attempts, 2);
    assert_eq!(registered.len(), 2);
    assert_ne!(registered[0], registered[1]);
    assert!(space.path("attempt-1/inherited.json").exists());
    assert!(space.path("attempt-2/inherited.json").exists());
    assert!(
        report
            .attempts
            .iter()
            .all(|a| a.custody == Custody::Released)
    );

    let (report, _, _space) = drive("crash", "normal", false, 3_000);
    assert_eq!(report.outcome.end, End::Failed(Stop::Crash));
    assert_eq!(report.outcome.attempts, 2);
}

#[test]
fn driver_never_retries_guard_stops_cancellation_or_foreign_exits() {
    let (report, _, _s) = drive("hang", "guard_stop", false, 3_000);
    assert_eq!(report.outcome.end, End::Failed(Stop::GuardStop));
    assert_eq!(report.attempts.len(), 1);

    let (report, _, _s) = drive("hang", "normal", true, 3_000);
    assert_eq!(report.outcome.end, End::Failed(Stop::Cancelled));
    assert_eq!(report.attempts.len(), 1);
    assert_eq!(report.attempts[0].custody, Custody::Released);

    let (report, _, _s) = drive("crash", "foreign_exit", false, 3_000);
    assert_eq!(report.outcome.end, End::Failed(Stop::Protocol));
    assert_eq!(report.attempts.len(), 1);
}

#[test]
fn driver_holds_an_attempt_whose_cleanup_is_unconfirmed() {
    let (report, _, _s) = drive("crash", "unconfirmed", false, 200);
    assert_eq!(report.outcome.end, End::Failed(Stop::Crash));
    assert!(matches!(
        report.outcome.cleanup,
        CleanupState::Unconfirmed(_)
    ));
    assert_eq!(
        report.attempts.len(),
        1,
        "a held attempt is never relaunched"
    );
    assert_eq!(
        report.attempts[0].custody,
        Custody::Held("scripted uncertain cleanup".into())
    );
}

/// Larger than any pipe buffer, so the launcher is still writing the spec when the bridge closes it.
fn padded(mut command: WorkerCommand) -> WorkerCommand {
    command.env.insert("PADDING".into(), "x".repeat(1 << 20));
    command
}

#[test]
fn submit_refuses_a_non_utf8_argument_before_starting_any_admission_owner() {
    let space = Workspace::new();
    let (sink, events) = mpsc::channel();
    let mut command = worker(&space, "normal");
    command.args.push(OsString::from_vec(vec![0xff, 0xfe]));
    let refused =
        launcher("normal").submit(1, &command, request(&space, "attempt-1", vec![]), sink);
    assert_eq!(
        refused.err().map(|error| error.kind()),
        Some(io::ErrorKind::InvalidInput)
    );
    assert!(
        !space.path("attempt-1").exists(),
        "refused before the report folder, so no bridge ever started"
    );
    assert!(events.recv_timeout(Duration::from_millis(200)).is_err());
}

#[test]
fn a_spec_write_failure_after_the_spawn_ends_unconfirmed_and_never_errs() {
    let space = Workspace::new();
    let (sink, events) = mpsc::channel();
    let mut attempt = launcher("spec_closed")
        .submit(
            1,
            &padded(worker(&space, "normal")),
            request(&space, "attempt-1", vec![]),
            sink,
        )
        .expect("an admission owner exists, so submit must not err");
    assert!(space.path("attempt-1/inherited.json").exists());
    assert!(
        attempt.take_pipes().is_none(),
        "no protocol pipes without a spec"
    );
    assert!(matches!(
        next(&events),
        LaunchEvent::Finished {
            cleanup: CleanupReceipt::Unconfirmed { .. },
            ..
        }
    ));
    assert!(
        !attempt.wait().unwrap().success(),
        "withdrawn by the launcher's SIGTERM"
    );
}

#[test]
fn driver_reports_launch_failure_only_before_a_spawn() {
    // Refused before any spawn: a launch failure, nothing held, nothing started.
    let space = Workspace::new();
    let mut job = spec(&space, "normal", 200);
    job.command.args.push(OsString::from_vec(vec![0xff]));
    let (_canceller, inbox) = job_channel();
    let report = run_job(
        &mut launcher("normal"),
        &SystemClock::new(),
        &job,
        inbox,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(report.abort.unwrap().starts_with("launch failed"));
    assert_eq!(report.attempts.len(), 1);
    assert_eq!(report.attempts[0].custody, Custody::Released);
    assert!(!space.path("attempt-1").exists());

    // A spawned bridge whose spec write failed is not a launch failure: without a cleanup
    // receipt the attempt is held, never released, and never relaunched.
    let space = Workspace::new();
    let mut job = spec(&space, "normal", 200);
    job.command = padded(job.command);
    let (_canceller, inbox) = job_channel();
    let report = run_job(
        &mut launcher("spec_closed"),
        &SystemClock::new(),
        &job,
        inbox,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(
        !report
            .abort
            .unwrap_or_default()
            .starts_with("launch failed")
    );
    assert_eq!(report.attempts.len(), 1);
    assert!(matches!(report.attempts[0].custody, Custody::Held(_)));
    assert!(space.path("attempt-1/inherited.json").exists());
}

#[test]
fn concurrent_handshakes_stay_within_bound() {
    // Two attempts at once must not share descriptors or events.
    let handles: Vec<_> = (0..2)
        .map(|_| thread::spawn(|| drive("normal", "normal", false, 3_000).0.outcome.end))
        .collect();
    for handle in handles {
        assert_eq!(handle.join().unwrap(), End::Completed);
    }
}
