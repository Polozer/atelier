//! The launcher seam C1b consumes, and one staged job run end to end over it.
//!
//! [`StartWorker`] is the narrow interface the job runner needs: start a [`WorkerCommand`] with a
//! dedicated request/response pipe and later stop or reap it. The production launcher (C7) owns
//! admission, guards, deadlines and crash evidence and implements this seam; it appends
//! `--request-fd N --response-fd M` exactly as [`DirectChild`] does. [`DirectChild`] starts an owned
//! child with no admission and exists for tests and local tools only.
use crate::keys::PreparedUnit;
use crate::protocol::{FailureKind, WorkerFailure};
use crate::results::OutputSources;
use crate::staging::{StagedJob, collect_outputs};
use crate::worker_session::{Channel, Session};
use std::collections::BTreeMap;
use std::io::{self, PipeReader, PipeWriter};
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, ExitStatus, Stdio};

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
    /// isolated from user site and environment variables, in a neutral working folder.
    pub fn python_job_loop(interpreter: PathBuf, worker_script: PathBuf) -> Self {
        Self {
            program: interpreter,
            args: vec!["-I".into(), worker_script.to_string_lossy().into_owned()],
            env: BTreeMap::from([("LC_ALL".into(), "C".into()), ("TZ".into(), "UTC".into())]),
            cwd: PathBuf::from("/"),
        }
    }
}

/// Version the Python job loop announces in `hello`.
pub const PYTHON_JOB_LOOP_VERSION: &str = "atelier-python-job-1";

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
    /// The complete output manifest for `WriteTransaction::stage`.
    Completed(OutputSources),
    Failed(WorkerFailure),
}

/// @cc [owner:fontanierh,label:correctness] staged-job-run
/// Running a staged job MUST start one worker, complete the versioned handshake, send exactly the
/// staged request, and turn only a `completed` whose reported files equal the actual `output/` tree
/// into a manifest. Worker failures, protocol breaks and mismatched outputs MUST yield no manifest;
/// a broken worker is stopped, never reused. Nothing is published or deleted here. See
/// tests/python_jobs.rs.
pub fn run_staged<L: StartWorker>(
    launcher: &L,
    command: &WorkerCommand,
    worker_version: &str,
    prepared: &PreparedUnit,
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
        Ok(outputs) => match collect_outputs(staged, prepared, &outputs.files) {
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
