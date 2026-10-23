//! The launcher seam C1b consumes, and one staged job run end to end over it.
//!
//! [`StartWorker`] is the narrow interface the job runner needs: start a [`WorkerCommand`] with a
//! dedicated request/response pipe and later stop or reap it. The production launcher (C7) owns
//! admission, guards, deadlines and crash evidence and implements this seam; it appends
//! `--request-fd N --response-fd M` exactly as [`DirectChild`] does. [`DirectChild`] starts an owned
//! child with no admission and exists for tests and local tools only.
use crate::protocol::{FailureKind, WorkerFailure};
use crate::results::ActualOutput;
use crate::staging::{StagedJob, collect_outputs};
use crate::worker_session::{Channel, Session};
use std::collections::BTreeMap;
use std::io::{self, PipeReader, PipeWriter};
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};

/// A script path as the argument text a worker command carries; a non-UTF-8 path is refused, never
/// altered.
fn script_argument(path: &Path) -> io::Result<String> {
    path.to_str().map(str::to_owned).ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("worker script path is not UTF-8: {}", path.display()),
        )
    })
}

/// What to start. The launcher adds only the two protocol descriptor flags.
#[derive(Clone, Debug, PartialEq)]
pub struct WorkerCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    /// The complete environment; nothing is inherited.
    pub env: BTreeMap<String, String>,
    pub cwd: PathBuf,
}

impl WorkerCommand {
    /// The build-v2 Python job loop (`atelier/build_v2/python_worker.py`) under `interpreter`,
    /// isolated from user site and environment variables, in a neutral working folder. A non-UTF-8
    /// script path is refused.
    pub fn python_job_loop(interpreter: PathBuf, worker_script: PathBuf) -> io::Result<Self> {
        Ok(Self {
            program: interpreter,
            args: vec!["-I".into(), script_argument(&worker_script)?],
            env: BTreeMap::from([("LC_ALL".into(), "C".into()), ("TZ".into(), "UTC".into())]),
            cwd: PathBuf::from("/"),
        })
    }
}

/// Version the Python job loop announces in `hello`.
pub const PYTHON_JOB_LOOP_VERSION: &str = "atelier-python-job-1";

/// Flags of the background Blender that hosts the Blender job loop, before its `-P` script: no
/// user startup file or preferences, an explicit thread count that admission reads from argv
/// (it must precede `-P`), script errors as a non-zero exit, and no auto-run of embedded scripts.
pub const BLENDER_LOOP_FLAGS: [&str; 8] = [
    "--factory-startup",
    "-b",
    "--threads",
    "3",
    "--python-exit-code",
    "1",
    "--disable-autoexec",
    "-P",
];

impl WorkerCommand {
    /// The build-v2 Blender job loop (`atelier/build_v2/blender_worker.py`) inside the installed
    /// background Blender, which is the admitted worker process. The launcher appends the
    /// protocol descriptor flags after `--`, where Blender passes them to the script. Every job then
    /// runs in a fresh Blender started by the loop from this same binary. A non-UTF-8 script path
    /// is refused.
    pub fn blender_job_loop(blender: PathBuf, worker_script: PathBuf) -> io::Result<Self> {
        let mut args: Vec<String> = BLENDER_LOOP_FLAGS
            .iter()
            .map(|flag| flag.to_string())
            .collect();
        args.push(script_argument(&worker_script)?);
        args.push("--".into());
        Ok(Self {
            program: blender,
            args,
            env: BTreeMap::from([("LC_ALL".into(), "C".into()), ("TZ".into(), "UTC".into())]),
            cwd: PathBuf::from("/"),
        })
    }
}

/// Version the Blender job loop announces in `hello`.
pub const BLENDER_JOB_LOOP_VERSION: &str = "atelier-blender-job-1";

/// The same invocation for the guarded launcher (C7), field for field: program, arguments in
/// order, the complete environment and the working folder. Both launchers append only the two
/// protocol descriptor flags. Arguments here are always UTF-8 (the loop constructors refuse
/// anything else), so the conversion cannot fail.
impl From<WorkerCommand> for crate::guard_adapter::WorkerCommand {
    fn from(command: WorkerCommand) -> Self {
        Self {
            program: command.program,
            args: command.args.into_iter().map(Into::into).collect(),
            env: command.env,
            cwd: command.cwd,
        }
    }
}

/// The controller's ends of a worker's protocol pipe.
pub struct WorkerPipes {
    pub requests: PipeWriter,
    pub responses: PipeReader,
}

/// A started worker process.
pub trait LaunchedWorker {
    /// End the worker if it still runs, then reap it. Safe to call more than once.
    fn stop(&mut self) -> io::Result<ExitStatus>;
    /// Wait for a worker that was asked to shut down.
    fn wait(&mut self) -> io::Result<ExitStatus>;
}

/// Starts workers with a dedicated protocol pipe. Implemented by C7's supervised launcher.
pub trait StartWorker {
    type Worker: LaunchedWorker;
    fn start(&self, command: &WorkerCommand) -> io::Result<(Self::Worker, WorkerPipes)>;
}

/// An owned child with no admission, guard or deadline: tests and local tools only.
pub struct DirectChild;

pub struct DirectWorker(Child);

impl LaunchedWorker for DirectWorker {
    fn stop(&mut self) -> io::Result<ExitStatus> {
        if let Some(status) = self.0.try_wait()? {
            return Ok(status);
        }
        self.0.kill()?;
        self.0.wait()
    }
    fn wait(&mut self) -> io::Result<ExitStatus> {
        self.0.wait()
    }
}

impl StartWorker for DirectChild {
    type Worker = DirectWorker;
    fn start(&self, command: &WorkerCommand) -> io::Result<(DirectWorker, WorkerPipes)> {
        // std pipes are close-on-exec, so no other child inherits them.
        let (request_reader, request_writer) = io::pipe()?;
        let (response_reader, response_writer) = io::pipe()?;
        let inherited = [request_reader.as_raw_fd(), response_writer.as_raw_fd()];
        let mut process = Command::new(&command.program);
        process
            .args(&command.args)
            .args([
                "--request-fd".to_string(),
                inherited[0].to_string(),
                "--response-fd".to_string(),
                inherited[1].to_string(),
            ])
            .env_clear()
            .envs(&command.env)
            .current_dir(&command.cwd)
            .stdin(Stdio::null());
        // SAFETY: between fork and exec this only calls fcntl, which is async-signal-safe, to clear
        // close-on-exec on this child's own two protocol descriptors.
        unsafe {
            process.pre_exec(move || {
                for fd in inherited {
                    if libc::fcntl(fd, libc::F_SETFD, 0) == -1 {
                        return Err(io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
        let child = process.spawn()?;
        Ok((
            DirectWorker(child),
            WorkerPipes {
                requests: request_writer,
                responses: response_reader,
            },
        ))
    }
}

/// The outcome of one staged job, before B2 freezes and publishes anything.
#[derive(Debug)]
pub enum JobOutcome {
    /// Every file the job produced, fixed outputs and group members alike, for `WriteTransaction::stage_groups`.
    Completed(Vec<ActualOutput>),
    Failed(WorkerFailure),
}

/// @cc [owner:fontanierh,label:correctness] staged-job-run
/// Running a staged job MUST start one worker, complete the versioned handshake, send exactly the
/// staged request, and turn only a `completed` whose reported files equal the actual `output/` tree
/// into the complete actual file list; membership is decided by the result store. Worker failures,
/// protocol breaks and reported/actual mismatches MUST yield no outputs; a broken worker is
/// stopped, never reused. Nothing is published or deleted here. See tests/staging.rs.
pub fn run_staged<L: StartWorker>(
    launcher: &L,
    command: &WorkerCommand,
    worker_version: &str,
    staged: &StagedJob,
) -> Result<JobOutcome, String> {
    let (mut worker, pipes) = launcher
        .start(command)
        .map_err(|error| format!("cannot start the worker: {error}"))?;
    let mut channel = Channel::new(
        Session::new(worker_version),
        pipes.responses,
        pipes.requests,
    );
    let finished = channel
        .handshake()
        .and_then(|_| channel.run(staged.request().clone()));
    let finished = match finished {
        Ok(finished) => finished,
        Err(error) => {
            drop(channel);
            let _ = worker.stop();
            return Err(error.to_string());
        }
    };
    let outcome = match finished.result {
        Ok(outputs) => match collect_outputs(staged, &outputs.files) {
            Ok(sources) => JobOutcome::Completed(sources),
            Err(message) => JobOutcome::Failed(WorkerFailure {
                kind: FailureKind::Job,
                message,
            }),
        },
        Err(failure) => JobOutcome::Failed(failure),
    };
    let stopped = channel.shutdown();
    drop(channel);
    match stopped {
        Ok(()) => {
            let status = worker
                .wait()
                .map_err(|error| format!("cannot reap the worker: {error}"))?;
            if !status.success() {
                return Err(format!("the worker exited with {status} after stopping"));
            }
        }
        Err(error) => {
            let _ = worker.stop();
            return Err(error.to_string());
        }
    }
    Ok(outcome)
}
