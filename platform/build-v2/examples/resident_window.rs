//! One real guarded resident-session window for C5c slice 6 (not a test; run once by hand, under
//! normal admission, only after review).
//!
//! `resident_window --python PATH --out DIR` runs the real Python job loop (the frozen
//! `atelier/build_v2` worker files, launched by `launch::WorkerCommand::python_job_loop`) through
//! the real bridge (`python -m atelier.build_v2.guarded_worker`), so every session goes through
//! the existing broker admission, process and tree guards, under the no-fork job sandbox. Each
//! case holds real B3 checkout locks (build exclusive, content shared); their custodian
//! duplicates are the session's custody, so the guard pins a custody monitor that the bridge
//! publishes once. Before every Run, the driver's `register` callback calls the production
//! `register_python_worker` for the worker and for the monitor on both real leases (the local
//! completion lease and the CAS write lease), then independently re-reads both lease records and
//! the session's `custodian.json` from disk.
//!
//! Cases (each with its own expected outcome):
//! - `s1-single`: A alone.
//! - `s2-reuse`: B then A in one session, A only after quiescence evidence.
//! - `s3-aba`: A, B, A again in one session; the second A gets its own prepared request.
//! - `s4-fresh`: A, then an idle expiry, then B in a fresh session with a fresh admission and
//!   monitor. (A real crash cannot be produced from inside the no-fork sandbox without fault
//!   injection, so this case is a fresh session, not a crash retry.)
//! - `s5-cancel`: a spinning unit cancelled while it runs.
//! - `s6-originals`: the controller's original B3 guards are dropped right after the monitor's
//!   registration; exclusion is then held by the custody set (the controller's session custody
//!   source, the bridge and the monitor), never by the dropped originals. Monitor-only custody is
//!   not observable: the bridge keeps its own custody descriptors until `guarded.run` returns
//!   (guarded_worker.py) and `run_session` borrows the session custody for the whole run.
//!
//! Evidence is written to DIR/evidence.json; every attempt folder is kept. The result certifies
//! only the resident session, Q3 retention and the B3 custody seam: not MAC1, orphan or GC
//! behaviour, nor the production A9 constructor.
use atelier_build_v2::checkout_locks::{BuildGuard, CheckoutLocks, ContentReadGuard, LockError};
use atelier_build_v2::completion::CompletionWork;
use atelier_build_v2::failure_policy::{End, Limits, Stop};
use atelier_build_v2::guard_adapter::{GuardedLauncher, WorkerCommand};
use atelier_build_v2::install::{InstallPolicy, LeaseIdentity, ProjectNamespace, ReceiptReader};
use atelier_build_v2::keys::{ImplementationIdentity, KeyContext, PreparedUnit, prepare};
use atelier_build_v2::launch::{self, PYTHON_JOB_LOOP_VERSION};
use atelier_build_v2::leases::{LeaseStore, ProcessIdentity};
use atelier_build_v2::python_backend::register_python_worker;
use atelier_build_v2::python_worker::{PYTHON_WORKER_FILES, PythonWorkerBundle};
use atelier_build_v2::results::{ResultStore, WriteTransaction};
use atelier_build_v2::schema::{
    Declaration, Destination, Item, Op, OutputFile, Provenance, SCHEMA_VERSION, Unit,
};
use atelier_build_v2::session_lifecycle::{SessionConfig, UnitPlan, UnitRecord};
use atelier_build_v2::source_hashes::SourceHashCache;
use atelier_build_v2::validate::{OpDefinition, SnapshotEntry, SourceSnapshot, validate};
use atelier_build_v2::worker_lifecycle::{
    CleanupCorrelation, Custody, CustodyIdentity, JobSandbox, LockScope, SessionKey, SessionSpec,
    SessionUnit, SystemClock, cleanup_confirmed, run_session_prepared, session_channel,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::os::fd::AsRawFd;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// The admission ceiling of one session: the full job profile, as in the C5b/C7 window.
const MEMORY_GIB: u32 = 10;
/// One enclosing deadline over the whole sequence of cases.
const SEQUENCE_DEADLINE: Duration = Duration::from_secs(1800);
/// Per-unit limits: work, cleanup, and the unit's own deadline from submission (its queue wait
/// included).
const UNIT_LIMITS: Limits = Limits {
    job: Duration::from_secs(120),
    cleanup: Duration::from_secs(60),
    overall: Some(Duration::from_secs(300)),
};
/// How long an idle, open session keeps its worker; S4 waits past it.
const IDLE: Duration = Duration::from_secs(3);
/// Quiescence evidence must arrive within this bound of a unit's terminal reply.
const QUIESCENCE: Duration = Duration::from_secs(10);
/// S5 cancels this long after the spinning unit's worker registration.
const CANCEL_AFTER: Duration = Duration::from_secs(2);

fn arg(name: &str) -> PathBuf {
    let args: Vec<String> = std::env::args().collect();
    let at = args.iter().position(|a| a == name).expect(name);
    PathBuf::from(&args[at + 1])
}

/// The op sources: `run(context)` writes its one declared output; `spin` runs until cancelled.
fn op_sources() -> BTreeMap<&'static str, &'static [u8]> {
    BTreeMap::from([
        (
            "ops/a.py",
            b"def run(context):\n    context.output(context.outputs[0]).write_text('A\\n')\n"
                as &[u8],
        ),
        (
            "ops/b.py",
            b"def run(context):\n    context.output(context.outputs[0]).write_text('B\\n')\n",
        ),
        (
            "ops/spin.py",
            b"def run(context):\n    n = 0\n    while True:\n        n += 1\n",
        ),
    ])
}

fn declaration() -> Declaration {
    let unit = |id: &str| Unit {
        id: id.into(),
        op: Op {
            kind: "resident-proof".into(),
            version: "1".into(),
        },
        script: format!("ops/{id}.py"),
        code: vec![format!("ops/{id}.py")],
        inputs: vec![],
        params: BTreeMap::new(),
        conditional: None,
        output_groups: vec![],
        outputs: vec![Item {
            id: "piece".into(),
            logical_path: format!("/Data/resident/{id}"),
            class: "Blob".into(),
            destination: Destination::Store,
            files: vec![OutputFile {
                path: "output/piece.txt".into(),
                install_path: None,
                required: true,
            }],
        }],
    };
    Declaration {
        schema_version: SCHEMA_VERSION,
        cache_version: "resident-window-1".into(),
        units: vec![unit("a"), unit("b"), unit("spin")],
    }
}

/// The frozen real worker files, read once from the checkout.
fn worker_snapshot(source: &Path) -> SourceSnapshot {
    PYTHON_WORKER_FILES
        .into_iter()
        .map(|name| {
            (
                name.to_string(),
                SnapshotEntry::File(fs::read(source.join(name)).expect(name)),
            )
        })
        .collect()
}

/// Materialize the frozen worker bytes read-only and build the production loop command.
fn worker_command(python: &Path, snapshot: &SourceSnapshot, folder: &Path) -> WorkerCommand {
    fs::create_dir(folder).unwrap();
    for (name, entry) in snapshot {
        let SnapshotEntry::File(bytes) = entry else {
            panic!("{name} is not a file")
        };
        let path = folder.join(name);
        fs::write(&path, bytes).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o444)).unwrap();
    }
    fs::set_permissions(folder, fs::Permissions::from_mode(0o555)).unwrap();
    let command = launch::WorkerCommand::python_job_loop(
        python.to_path_buf(),
        folder.join("python_worker.py"),
    )
    .unwrap();
    WorkerCommand {
        program: command.program,
        args: command.args.into_iter().map(Into::into).collect(),
        env: command.env,
        cwd: command.cwd,
    }
}

/// This controller's own identity, by the same boot and process-start scheme the guards use.
fn own_identity(python: &Path) -> ProcessIdentity {
    let pid = std::process::id();
    let output = Command::new(python)
        .args([
            "-c",
            "import sys\nfrom atelier.harness.capacity_protocol import boot_id, process_start\n\
             print(boot_id()); print(process_start(int(sys.argv[1])))",
        ])
        .arg(pid.to_string())
        .output()
        .unwrap();
    assert!(output.status.success(), "identity helper failed");
    let text = String::from_utf8(output.stdout).unwrap();
    let mut lines = text.lines();
    ProcessIdentity {
        pid,
        boot: lines.next().unwrap().into(),
        started: lines.next().unwrap().into(),
    }
}

/// `(pid, fd)` of every process holding `path` open, read-only through lsof.
fn holders(path: &Path) -> Vec<(u32, String)> {
    let output = Command::new("/usr/sbin/lsof")
        .args(["-n", "-P", "-F", "pf", "--"])
        .arg(path)
        .output()
        .unwrap();
    let mut found = vec![];
    let mut pid = None;
    for line in String::from_utf8_lossy(&output.stdout).lines() {
        if let Some(value) = line.strip_prefix('p') {
            pid = value.parse().ok();
        } else if let (Some(fd), Some(pid)) = (line.strip_prefix('f'), pid) {
            found.push((pid, fd.to_string()));
        }
    }
    found
}

/// Whether `pid` still exists, read-only through ps (no signal of any kind).
fn alive(pid: u32) -> bool {
    Command::new("/bin/ps")
        .args(["-o", "pid=", "-p", &pid.to_string()])
        .output()
        .map(|output| !String::from_utf8_lossy(&output.stdout).trim().is_empty())
        .unwrap_or(true)
}

/// Whether this controller has no child left at all (waitid WNOWAIT: never reaps, never signals).
fn no_children() -> bool {
    // SAFETY: waitid writes only into the siginfo_t we own.
    let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
    let flags = libc::WEXITED | libc::WNOHANG | libc::WNOWAIT;
    let found = unsafe { libc::waitid(libc::P_ALL, 0, &mut info, flags) };
    found == -1 && std::io::Error::last_os_error().raw_os_error() == Some(libc::ECHILD)
}

fn read_json(path: &Path) -> Value {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or(Value::Null)
}

fn installer_busy(checkout: &Path) -> bool {
    let locks = CheckoutLocks::open(checkout).unwrap();
    matches!(locks.try_build_exclusive(), Err(LockError::Busy))
}

fn reader_admitted(checkout: &Path) -> bool {
    let locks = CheckoutLocks::open(checkout).unwrap();
    locks.try_read_content().is_ok()
}

enum Wait {
    Got,
    Ended,
    Deadline,
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Batch,
    Fresh,
    Cancel,
    DropOriginals,
}

struct Case {
    name: &'static str,
    kind: Kind,
    /// (unit id, declared unit, expected end)
    units: Vec<(&'static str, &'static str, End)>,
    sessions: usize,
}

fn cases() -> Vec<Case> {
    let done = || End::Completed;
    vec![
        Case {
            name: "s1-single",
            kind: Kind::Batch,
            units: vec![("a", "a", done())],
            sessions: 1,
        },
        Case {
            name: "s2-reuse",
            kind: Kind::Batch,
            units: vec![("b", "b", done()), ("a", "a", done())],
            sessions: 1,
        },
        Case {
            name: "s3-aba",
            kind: Kind::Batch,
            units: vec![("a1", "a", done()), ("b", "b", done()), ("a2", "a", done())],
            sessions: 1,
        },
        Case {
            name: "s4-fresh",
            kind: Kind::Fresh,
            units: vec![("a", "a", done()), ("b", "b", done())],
            sessions: 2,
        },
        Case {
            name: "s5-cancel",
            kind: Kind::Cancel,
            units: vec![("spin", "spin", End::Failed(Stop::Cancelled))],
            sessions: 1,
        },
        Case {
            name: "s6-originals",
            kind: Kind::DropOriginals,
            units: vec![("a", "a", done())],
            sessions: 1,
        },
    ]
}

/// What every case shares.
struct World {
    python: PathBuf,
    command: WorkerCommand,
    owner: ProcessIdentity,
    prepared: BTreeMap<String, PreparedUnit>,
    sources: BTreeMap<&'static str, &'static [u8]>,
    started: Instant,
}

/// The two real leases of one unit, bound before any Run.
struct Leases {
    local: CompletionWork,
    cas: WriteTransaction,
}

fn lease_holds(store: &LeaseStore, id: &str, identity: &ProcessIdentity) -> Result<(), String> {
    // Under the store's metadata mutex, as every lease reader does.
    let records = store
        .lock()
        .and_then(|guard| guard.leases())
        .map_err(|error| error.to_string())?;
    let record = records
        .iter()
        .find(|record| record.id == id)
        .ok_or_else(|| format!("lease {id} is not on disk"))?;
    if record.workers.contains(identity) {
        Ok(())
    } else {
        Err(format!("lease {id} does not record {identity:?}"))
    }
}

fn provenance() -> Provenance {
    Provenance {
        checkout: "resident-window".into(),
        branch: "resident-window".into(),
        commit: "resident-window".into(),
        dirty: false,
        built_at: "resident-window".into(),
    }
}

fn identity_json(identity: &ProcessIdentity) -> Value {
    json!({"pid": identity.pid, "started": identity.started, "boot": identity.boot})
}

fn run_case(world: &World, case: &Case, root: &Path) -> (bool, Value) {
    let mut problems: Vec<String> = vec![];
    let checkout = root.join("checkout");
    let reports = root.join("reports");
    let jobs = root.join("jobs");
    for folder in [&checkout, &reports, &jobs] {
        fs::create_dir_all(folder).unwrap();
    }
    let checkout = checkout.canonicalize().unwrap();
    let locks = CheckoutLocks::open(&checkout).unwrap();
    let build: BuildGuard = locks.try_build_exclusive().unwrap();
    let read: ContentReadGuard = locks.try_read_content().unwrap();
    let custody = vec![
        build.duplicate_for_custodian().unwrap(),
        read.duplicate_for_custodian().unwrap(),
    ];
    let custody_set: BTreeSet<CustodyIdentity> = [
        CustodyIdentity::of(&custody[0], LockScope::Exclusive).unwrap(),
        CustodyIdentity::of(&custody[1], LockScope::Shared).unwrap(),
    ]
    .into();
    let lock_files: BTreeSet<(u64, u64)> = custody_set
        .iter()
        .map(|identity| (identity.device, identity.inode))
        .collect();
    let lock_paths: Vec<PathBuf> = ["build.lock", "content.lock"]
        .iter()
        .map(|name| checkout.join("build/build-v2/install").join(name))
        .collect();
    let session_fds: BTreeSet<String> = custody
        .iter()
        .map(|file| file.as_raw_fd().to_string())
        .collect();

    let reader = ReceiptReader::open(
        &checkout,
        InstallPolicy {
            project: ProjectNamespace::new("resident-window").unwrap(),
            allowed_install_roots: vec![],
        },
    )
    .unwrap();
    let store = ResultStore::open(root.join("cache")).unwrap();
    let local_leases = LeaseStore::open(checkout.join("build/build-v2/install/completions"));
    let identity = || LeaseIdentity {
        provenance: provenance(),
        owner: world.owner.clone(),
        workers: vec![],
        upstream_result_keys: BTreeSet::new(),
    };
    // Every unit's original leases are bound before any Run.
    let mut leases: BTreeMap<String, Leases> = BTreeMap::new();
    for (unit, declared, _) in &case.units {
        let prepared = &world.prepared[*declared];
        let local = reader
            .begin_completion(&build, prepared, identity())
            .unwrap();
        let cas = store
            .begin(
                prepared,
                provenance(),
                world.owner.clone(),
                vec![],
                BTreeSet::new(),
            )
            .unwrap();
        leases.insert(unit.to_string(), Leases { local, cas });
    }
    let local_leases = local_leases.unwrap();

    let key = SessionKey {
        worker_version: PYTHON_JOB_LOOP_VERSION.into(),
        command: world.command.clone(),
        memory_gib: MEMORY_GIB,
        sandbox: JobSandbox::NoFork,
        custody: custody_set,
    };
    let spec = SessionSpec {
        key: key.clone(),
        purpose: format!("build-v2 C5c resident window: {}", case.name),
        config: SessionConfig {
            cleanup: UNIT_LIMITS.cleanup,
            lifetime: Duration::from_secs(600),
            idle: IDLE,
            quiescence: Some(QUIESCENCE),
            custodian: true,
        },
        report_root: reports.clone(),
        custody,
    };
    let declared: BTreeMap<String, &str> = case
        .units
        .iter()
        .map(|(unit, declared, _)| (unit.to_string(), *declared))
        .collect();
    let units: Vec<SessionUnit> = case
        .units
        .iter()
        .map(|(unit, declared, _)| SessionUnit {
            plan: UnitPlan {
                id: unit.to_string(),
                limits: UNIT_LIMITS,
            },
            job: world.prepared[*declared].request(unit, &format!("/jobs/{unit}")),
            key: key.clone(),
        })
        .collect();

    let (handle, inbox) = session_channel();
    let (published, records) = mpsc::channel::<UnitRecord>();
    let (registered_tx, registered_rx) = mpsc::channel::<(String, bool)>();
    let mut originals = Some((build, read));
    let mut registrations: Vec<Value> = vec![];
    let mut s6: Value = Value::Null;
    let mut collected: Vec<UnitRecord> = vec![];
    let deadline = world.started + SEQUENCE_DEADLINE;
    let mut deadline_hit = false;

    let report = std::thread::scope(|scope| {
        let driver = scope.spawn(|| {
            let mut launcher = GuardedLauncher {
                bridge: vec![
                    world.python.clone().into(),
                    "-m".into(),
                    "atelier.build_v2.guarded_worker".into(),
                ],
            };
            let mut register = |unit: &String, process: &ProcessIdentity| -> Result<(), String> {
                let leases = leases
                    .get_mut(unit)
                    .ok_or_else(|| format!("no leases bound for {unit}"))?;
                // The production registration: local lease first, then the CAS lease.
                register_python_worker(&mut leases.local, Some(&mut leases.cas), process)?;
                // Independently: both lease records on disk now hold this identity.
                lease_holds(&local_leases, &leases.local.lease().id, process)?;
                lease_holds(store.leases(), &leases.cas.lease().id, process)?;
                // A monitor is the identity a durable correlation already names.
                let correlation = CleanupCorrelation::find(&reports, process);
                let monitor = correlation.is_some();
                if let Some(correlation) = &correlation {
                    let hex = correlation.invocation.len() == 32
                        && correlation
                            .invocation
                            .bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
                    if correlation.schema != 1
                        || correlation.monitor != *process
                        || !hex
                        || !correlation.receipts.starts_with(&reports)
                    {
                        return Err(format!("correlation mismatch: {correlation:?}"));
                    }
                }
                let busy = installer_busy(&checkout);
                registrations.push(json!({
                    "unit": unit, "role": if monitor { "monitor" } else { "worker" },
                    "identity": identity_json(process),
                    "correlation": correlation.as_ref().map(|c| json!({
                        "invocation": c.invocation, "receipts": c.receipts})),
                    "local_lease": leases.local.lease().id, "cas_lease": leases.cas.lease().id,
                    "installer_busy": busy,
                    "after_seconds": world.started.elapsed().as_secs_f64(),
                }));
                if !busy {
                    return Err("the installer was not excluded while the session lives".into());
                }
                if monitor && case.kind == Kind::DropOriginals && originals.is_some() {
                    let me = std::process::id();
                    let before: Vec<_> = lock_paths.iter().map(|path| holders(path)).collect();
                    drop(originals.take());
                    let after: Vec<_> = lock_paths.iter().map(|path| holders(path)).collect();
                    let mine: BTreeSet<String> = after
                        .iter()
                        .flatten()
                        .filter(|(pid, _)| *pid == me)
                        .map(|(_, fd)| fd.clone())
                        .collect();
                    let dropped: BTreeSet<String> = before
                        .iter()
                        .flatten()
                        .filter(|(pid, _)| *pid == me)
                        .map(|(_, fd)| fd.clone())
                        .filter(|fd| !session_fds.contains(fd))
                        .collect();
                    let monitor_holds = after
                        .iter()
                        .all(|list| list.iter().any(|(pid, _)| *pid == process.pid));
                    let busy = installer_busy(&checkout);
                    let shared_reader = reader_admitted(&checkout);
                    s6 = json!({
                        "holders_before": before, "holders_after": after,
                        "controller_fds_after": mine, "session_custody_fds": session_fds,
                        "dropped_original_fds": dropped, "monitor_holds_every_lock": monitor_holds,
                        "installer_busy_after_drop": busy, "shared_reader_admitted": shared_reader,
                        "claim": "exclusion is held by the custody set (the controller's session \
                                  custody source, the bridge and the monitor), not by the dropped \
                                  original guards; monitor-only custody is not observable",
                    });
                    if !(monitor_holds && busy && mine == session_fds && !dropped.is_empty()) {
                        return Err(
                            "custody attribution after dropping the originals failed".into()
                        );
                    }
                }
                let _ = registered_tx.send((unit.clone(), monitor));
                Ok(())
            };
            let mut prepare = |unit: &String, attempt: u32| -> Result<_, String> {
                let declared = declared.get(unit).ok_or("unknown unit")?;
                let prepared = &world.prepared[*declared];
                let folder = jobs.join(format!("{unit}-{attempt}"));
                fs::create_dir(&folder).map_err(|error| error.to_string())?;
                fs::create_dir(folder.join("output")).map_err(|error| error.to_string())?;
                let request = prepared.request(unit, &folder.display().to_string());
                for code in &request.code {
                    let bytes = world
                        .sources
                        .get(code.as_str())
                        .ok_or("unknown code file")?;
                    let path = folder.join(code);
                    fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
                    fs::write(&path, bytes).map_err(|error| error.to_string())?;
                }
                Ok(request)
            };
            run_session_prepared(
                &mut launcher,
                &SystemClock::new(),
                &spec,
                inbox,
                &mut register,
                &mut prepare,
                published,
            )
        });

        // Feed the session as the case requires, under the enclosing deadline. A driver that
        // ends early (its publication channel closes) is reported as such, never as a timeout.
        let wait_record = |collected: &mut Vec<UnitRecord>| -> Wait {
            loop {
                if Instant::now() >= deadline {
                    return Wait::Deadline;
                }
                match records.recv_timeout(Duration::from_secs(1)) {
                    Ok(record) => {
                        collected.push(record);
                        return Wait::Got;
                    }
                    Err(mpsc::RecvTimeoutError::Disconnected) => return Wait::Ended,
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                }
            }
        };
        let mut ended = false;
        match case.kind {
            Kind::Batch | Kind::DropOriginals => {
                for unit in units {
                    handle.submit(unit);
                }
                handle.close();
            }
            Kind::Fresh => {
                let mut units = units.into_iter();
                handle.submit(units.next().unwrap());
                match wait_record(&mut collected) {
                    Wait::Got => {
                        // Past the idle limit: the next unit needs a fresh session.
                        std::thread::sleep(IDLE + Duration::from_secs(2));
                        handle.submit(units.next().unwrap());
                    }
                    Wait::Ended => ended = true,
                    Wait::Deadline => deadline_hit = true,
                }
                handle.close();
            }
            Kind::Cancel => {
                for unit in units {
                    handle.submit(unit);
                }
                handle.close();
                // The spinning unit's worker registration, or the driver's end, or the deadline.
                let worker_registered = loop {
                    if Instant::now() >= deadline {
                        deadline_hit = true;
                        break false;
                    }
                    if driver.is_finished() {
                        ended = true;
                        break false;
                    }
                    match registered_rx.recv_timeout(Duration::from_secs(1)) {
                        Ok((_, false)) => break true,
                        Ok(_) | Err(mpsc::RecvTimeoutError::Timeout) => continue,
                        Err(mpsc::RecvTimeoutError::Disconnected) => {
                            ended = true;
                            break false;
                        }
                    }
                };
                if worker_registered {
                    std::thread::sleep(CANCEL_AFTER);
                    handle.cancel("spin");
                }
            }
        }
        while collected.len() < case.units.len() && !deadline_hit && !ended {
            match wait_record(&mut collected) {
                Wait::Got => {}
                Wait::Ended => ended = true,
                Wait::Deadline => {
                    deadline_hit = true;
                    handle.cancel_all();
                }
            }
        }
        driver.join().expect("the session driver panicked")
    });
    drop(registered_rx);

    let mut evidence = json!({"case": case.name});
    if deadline_hit {
        problems.push("the enclosing deadline passed".into());
    }
    let report = match report {
        Ok(report) => report,
        Err(error) => {
            problems.push(format!("run_session failed: {error:?}"));
            evidence["problems"] = json!(problems);
            evidence["registrations"] = json!(registrations);
            return (false, evidence);
        }
    };

    // Per-unit expected outcomes, each settled by its own receipt or quiescence evidence.
    let mut units_evidence = vec![];
    for (unit, _, expected) in &case.units {
        let Some(record) = report.units.iter().find(|record| record.unit == *unit) else {
            problems.push(format!("{unit}: no record"));
            continue;
        };
        if record.outcome.end != *expected {
            problems.push(format!(
                "{unit}: ended {:?}, expected {expected:?}",
                record.outcome.end
            ));
        }
        let settled = record
            .attempts
            .iter()
            .all(|attempt| attempt.custody == Custody::Released || attempt.quiescent.is_some());
        if !settled {
            problems.push(format!(
                "{unit}: published before release or quiescence evidence"
            ));
        }
        if !collected.iter().any(|published| published.unit == *unit) {
            problems.push(format!("{unit}: never published"));
        }
        units_evidence.push(json!({
            "unit": unit, "end": format!("{:?}", record.outcome.end),
            "attempts": record.attempts.iter().map(|attempt| json!({
                "attempt": attempt.attempt, "session": attempt.session,
                "custody": format!("{:?}", attempt.custody), "quiescent": attempt.quiescent,
            })).collect::<Vec<_>>(),
            "outputs": record.outputs.as_ref().map(|outputs| outputs.files.clone()),
            "abort": record.abort,
        }));
    }
    if report.sessions.len() != case.sessions {
        problems.push(format!(
            "{} sessions, expected {}",
            report.sessions.len(),
            case.sessions
        ));
    }

    // Every session's cleanup is positively correlated with its own guard invocation.
    let mut sessions_evidence = vec![];
    for session in &report.sessions {
        let folder = reports.join(format!("attempt-{}", session.attempt));
        if session.custody != Custody::Released {
            problems.push(format!(
                "session {}: {:?}",
                session.attempt, session.custody
            ));
        }
        let correlation = CleanupCorrelation::read(&folder).ok();
        let confirmed = correlation.as_ref().is_some_and(cleanup_confirmed);
        if !confirmed {
            problems.push(format!(
                "session {}: cleanup not confirmed",
                session.attempt
            ));
        }
        let cleanup = read_json(&folder.join("cleanup.json"));
        let child_matches = session.worker.as_ref().is_some_and(|worker| {
            cleanup["child"][0].as_u64() == Some(worker.pid.into())
                && cleanup["child"][1].as_u64().map(|v| v.to_string())
                    == Some(worker.started.clone())
        });
        if !child_matches {
            problems.push(format!(
                "session {}: cleanup.json names another child",
                session.attempt
            ));
        }
        let tree = read_json(&folder.join("memory-health-tree.json"));
        let receipt_locks: BTreeSet<(u64, u64)> = tree["custody"]["lock_files"]
            .as_array()
            .map(|files| {
                files
                    .iter()
                    .filter_map(|pair| Some((pair[0].as_u64()?, pair[1].as_u64()?)))
                    .collect()
            })
            .unwrap_or_default();
        if receipt_locks != lock_files {
            problems.push(format!(
                "session {}: the guard released other locks",
                session.attempt
            ));
        }
        sessions_evidence.push(json!({
            "attempt": session.attempt, "admitted": session.admitted,
            "worker": session.worker.as_ref().map(identity_json),
            "custody": format!("{:?}", session.custody),
            "correlation": correlation.as_ref().map(|c| json!({
                "monitor": identity_json(&c.monitor), "invocation": c.invocation})),
            "cleanup_confirmed": confirmed, "cleanup": cleanup,
            "tree_custody": tree["custody"],
            "resources": {
                "timings": read_json(&folder.join("execution-timings.json")),
                "memory": read_json(&folder.join("memory-health.json")),
            },
        }));
    }
    // Before every Run: a worker and a monitor registration for every unit.
    for (unit, _, _) in &case.units {
        for role in ["worker", "monitor"] {
            let found = registrations
                .iter()
                .any(|entry| entry["unit"] == *unit && entry["role"] == role);
            let ran = report
                .units
                .iter()
                .any(|record| record.unit == *unit && record.outcome.attempts > 0);
            if ran && !found {
                problems.push(format!("{unit}: no {role} registration"));
            }
        }
    }

    // Settlement: release every controller handle, then the installer must be admitted.
    let watched: Vec<u32> = registrations
        .iter()
        .filter_map(|entry| entry["identity"]["pid"].as_u64())
        .map(|pid| pid as u32)
        .collect();
    drop(originals);
    drop(spec);
    drop(leases);
    let installer_after = !installer_busy(&checkout);
    if !installer_after {
        problems.push("the installer is still excluded after settlement".into());
    }
    // Bounded: the launcher's reaper threads and the guards' monitors exit just after settlement.
    let settle_by = Instant::now() + Duration::from_secs(15);
    let (survivors, children) = loop {
        let survivors: Vec<u32> = watched.iter().copied().filter(|pid| alive(*pid)).collect();
        let children = !no_children();
        if (survivors.is_empty() && !children) || Instant::now() >= settle_by {
            break (survivors, children);
        }
        std::thread::sleep(Duration::from_millis(250));
    };
    if !survivors.is_empty() {
        problems.push(format!("owned processes survive: {survivors:?}"));
    }
    if children {
        problems.push("this controller still has children".into());
    }
    evidence["units"] = json!(units_evidence);
    evidence["sessions"] = json!(sessions_evidence);
    evidence["registrations"] = json!(registrations);
    evidence["installer_admitted_after_settlement"] = json!(installer_after);
    evidence["lock_files"] = json!(lock_files);
    if case.kind == Kind::DropOriginals {
        evidence["originals_dropped"] = s6;
    }
    evidence["problems"] = json!(problems);
    (problems.is_empty(), evidence)
}

fn main() -> ExitCode {
    let python = arg("--python");
    let out = arg("--out");
    fs::create_dir(&out).expect("--out must name a new folder");
    let out = out.canonicalize().unwrap();
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("../studio/atelier/build_v2");
    let snapshot = worker_snapshot(&source);
    let bundle = PythonWorkerBundle::from_snapshot(&snapshot).unwrap();
    let worker = bundle.identity();
    let command = worker_command(&python, &snapshot, &out.join("worker"));

    let declaration = declaration();
    let sources = op_sources();
    let ops: SourceSnapshot = sources
        .iter()
        .map(|(name, bytes)| (name.to_string(), SnapshotEntry::File(bytes.to_vec())))
        .collect();
    let registry = BTreeMap::from([(
        ("resident-proof".to_string(), "1".to_string()),
        OpDefinition {
            inputs: BTreeMap::new(),
            output_classes: BTreeSet::from(["Blob".to_string()]),
            params: BTreeMap::new(),
        },
    )]);
    let validated = validate(&declaration, &registry, &ops, &[]).unwrap();
    let validator = ImplementationIdentity {
        version: "resident-window-1".into(),
        digest: "0".repeat(64),
    };
    let mut prepared = BTreeMap::new();
    for unit in ["a", "b", "spin"] {
        let unit_prepared = prepare(
            &declaration,
            &validated,
            unit,
            &KeyContext {
                snapshot: &ops,
                versions: &BTreeMap::new(),
                produced: &BTreeMap::new(),
                produced_groups: &BTreeMap::new(),
                staged_inputs: &BTreeMap::new(),
                worker: &worker,
                validator: &validator,
            },
            &mut SourceHashCache::default(),
        )
        .unwrap();
        prepared.insert(unit.to_string(), unit_prepared);
    }
    let world = World {
        owner: own_identity(&python),
        python,
        command,
        prepared,
        sources,
        started: Instant::now(),
    };

    let mut ok = true;
    let mut evidence = vec![];
    for case in cases() {
        if world.started.elapsed() >= SEQUENCE_DEADLINE {
            ok = false;
            evidence.push(json!({"case": case.name, "problems": ["not started: deadline"]}));
            continue;
        }
        let root = out.join(case.name);
        fs::create_dir(&root).unwrap();
        let (passed, case_evidence) = run_case(&world, &case, &root);
        println!("{}: {}", case.name, if passed { "pass" } else { "FAIL" });
        ok &= passed;
        evidence.push(case_evidence);
    }
    let summary = json!({
        "schema": 1,
        "certifies": "resident session reuse, Q3 retention on real leases and the B3 custody seam \
                      only; not MAC1, orphan or GC behaviour, nor the production A9 constructor",
        "worker": {"version": worker.version, "digest": worker.digest},
        "memory_gib": MEMORY_GIB,
        "limits": {
            "unit_job_seconds": UNIT_LIMITS.job.as_secs(),
            "unit_cleanup_seconds": UNIT_LIMITS.cleanup.as_secs(),
            "unit_overall_seconds": UNIT_LIMITS.overall.map(|d| d.as_secs()),
            "session_lifetime_seconds": 600, "idle_seconds": IDLE.as_secs(),
            "quiescence_seconds": QUIESCENCE.as_secs(),
            "sequence_deadline_seconds": SEQUENCE_DEADLINE.as_secs(),
        },
        "owner": identity_json(&world.owner),
        "elapsed_seconds": world.started.elapsed().as_secs_f64(),
        "passed": ok,
        "cases": evidence,
    });
    fs::write(
        out.join("evidence.json"),
        serde_json::to_vec_pretty(&summary).unwrap(),
    )
    .unwrap();
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
