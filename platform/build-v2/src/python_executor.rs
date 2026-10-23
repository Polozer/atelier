//! Static Python dispatch through the existing C5b lifecycle, with no independent process owner.
use crate::failure_policy::{CleanupState, End, Limits, Stop};
use crate::guard_adapter::WorkerLauncher;
use crate::python_backend::{PythonCompletion, PythonInputs, PythonTicket};
use crate::python_worker::PythonWorkerBundle;
use crate::scheduler::{Control, Event, Executor, Flow, Work};
use crate::worker_lifecycle::{self, Custody, JobSpec, SystemClock};
use std::path::PathBuf;
use std::time::Duration;

pub struct PythonExecution {
    pub interpreter: PathBuf,
    pub bundle: PythonWorkerBundle,
    pub profile: String,
    pub memory_gib: u32,
    pub limits: Limits,
}

pub struct PythonExecutor<L> {
    launcher: L,
    config: PythonExecution,
    scripted_fixture: bool,
}

impl<L> PythonExecutor<L> {
    /// Production dispatch remains refused until C5c exposes actual before-Run custodian identity.
    /// The ordinary constructor cannot enable a scripted/test registration bypass.
    pub fn new(launcher: L, config: PythonExecution) -> Self {
        Self {
            launcher,
            config,
            scripted_fixture: false,
        }
    }

    #[cfg(test)]
    pub(crate) fn scripted_fixture(launcher: L, config: PythonExecution) -> Self {
        Self {
            launcher,
            config,
            scripted_fixture: true,
        }
    }
}

impl<L: WorkerLauncher + Send> Executor<PythonTicket, PythonInputs, PythonCompletion>
    for PythonExecutor<L>
{
    /// @cc [owner:fontanierh,label:safety] static-python-cleanup-before-publication
    /// Dispatch MUST use C5b run_job and register the actual worker idempotently on both leases
    /// before Run. Unconfirmed cleanup or any non-Released attempt MUST be fatal before publishing
    /// or starting more work. Cancellation MUST go through the existing lifecycle channel; every
    /// submitted handle MUST get a terminal event. Production MUST refuse missing custodian
    /// registration until C5c slice5 supplies it. Scripted fixture execution proves sandbox/I/O
    /// only, never actual admission/monitor custody. See python_backend::tests (T1a pending).
    fn batch(
        &mut self,
        work: Vec<Work<PythonTicket, PythonInputs>>,
        control: &dyn Control,
        emit: &mut dyn FnMut(Event<PythonTicket, PythonInputs, PythonCompletion>) -> Flow,
    ) -> Result<(), String> {
        if !self.scripted_fixture {
            // C5b currently registers only the loop. A caller cannot assert monitor custody by flag.
            for work in work {
                emit(Event::Failed {
                    work,
                    reason: "custodian registration unsupported until C5c slice5".into(),
                });
            }
            return Err("actual custodian registration unavailable".into());
        }
        let mut stopped = false;
        let mut fatal = None;
        for mut work in work {
            if stopped || control.cancelled() {
                stopped |= emit(Event::Cancelled { work }) == Flow::Stop;
                continue;
            }
            let compatibility = work.compatibility();
            let worker = self.config.bundle.identity();
            if compatibility.worker_version != worker.version
                || compatibility.worker_digest != worker.digest
                || compatibility.profile != self.config.profile
            {
                stopped |= emit(Event::Failed {
                    work,
                    reason: "execution context differs from keyed runtime".into(),
                }) == Flow::Stop;
                continue;
            }
            let job_dir = work.inputs().staged.job_dir();
            let scope = job_dir.parent().ok_or("job has no leased parent")?;
            let command = match self.config.bundle.command(&self.config.interpreter, scope) {
                Ok(command) => command,
                Err(reason) => {
                    stopped |= emit(Event::Failed { work, reason }) == Flow::Stop;
                    continue;
                }
            };
            work.inputs().io.borrow_mut().worker_files_written +=
                crate::python_worker::PYTHON_WORKER_FILES.len();
            let spec = JobSpec {
                job: work.inputs().staged.request().clone(),
                worker_version: worker.version,
                command,
                purpose: "build-v2 static Python unit".into(),
                memory_gib: self.config.memory_gib,
                limits: self.config.limits,
                report_root: scope.join("guard"),
                custody: vec![], // Inputs are independent; no checkout read guard survives staging.
            };
            let (cancel, inbox) = worker_lifecycle::job_channel();
            let result = std::thread::scope(|scope| {
                let launcher = &mut self.launcher;
                let ticket = work.ticket_mut();
                let driver = scope.spawn(move || {
                    worker_lifecycle::run_job(
                        launcher,
                        &SystemClock::new(),
                        &spec,
                        inbox,
                        &mut |identity| ticket.register(identity),
                    )
                });
                while !driver.is_finished() {
                    if control.cancelled() {
                        cancel.cancel();
                    }
                    std::thread::sleep(Duration::from_millis(5));
                }
                driver
                    .join()
                    .map_err(|_| "Python lifecycle driver panicked".to_string())?
                    .map_err(|error| error.to_string())
            });
            if let Ok(report) = &result {
                work.inputs().io.borrow_mut().launches += report
                    .attempts
                    .iter()
                    .filter(|attempt| attempt.worker.is_some())
                    .count();
            }
            let event = match result {
                Ok(report)
                    if !matches!(report.outcome.cleanup, CleanupState::Unconfirmed(_))
                        && report
                            .attempts
                            .iter()
                            .all(|attempt| attempt.custody == Custody::Released) =>
                {
                    match report.outcome.end {
                        End::Completed => match report.outputs {
                            Some(outputs) => Event::Completed {
                                work,
                                completion: PythonCompletion {
                                    reported: outputs.files,
                                },
                            },
                            None => {
                                fatal = Some("completed lifecycle omitted output manifest".into());
                                Event::Failed {
                                    work,
                                    reason: "completed lifecycle omitted output manifest".into(),
                                }
                            }
                        },
                        End::Failed(Stop::Cancelled) => Event::Cancelled { work },
                        End::Failed(reason) => Event::Failed {
                            work,
                            reason: format!("Python unit failed: {reason:?}"),
                        },
                    }
                }
                Ok(_) => {
                    fatal = Some("Python attempt cleanup remains held".into());
                    Event::Failed {
                        work,
                        reason: "Python attempt cleanup remains held".into(),
                    }
                }
                Err(reason) => {
                    fatal = Some(reason.clone());
                    Event::Failed { work, reason }
                }
            };
            stopped |= emit(event) == Flow::Stop || fatal.is_some();
        }
        fatal.map_or(Ok(()), Err)
    }
}
