//! Static Python dispatch through the existing C5b lifecycle, with no independent process owner.
use crate::failure_policy::{CleanupState, End, Limits, Stop};
use crate::guard_adapter::WorkerLauncher;
use crate::python_backend::{PythonCompletion, PythonInputs, PythonIo, PythonTicket};
use crate::python_worker::PythonWorkerBundle;
use crate::scheduler::{Control, Event, Executor, Flow, Work};
use crate::worker_lifecycle::{self, Custody, JobSpec, SystemClock};
use std::path::PathBuf;
use std::time::Duration;

/// Only guard ChildStarted identities count, one per attempt (including retries).
/// Missing reports/uncertain custody cannot certify zero or a complete count.
fn record_launches(io: &mut PythonIo, unit: &str, report: Option<&worker_lifecycle::Report>) {
    io.launches_by_unit.remove(unit);
    if let Some(report) = report {
        let count = report
            .attempts
            .iter()
            .filter(|attempt| attempt.worker.is_some())
            .count();
        io.launches += count;
        if !matches!(report.outcome.cleanup, CleanupState::Unconfirmed(_))
            && report.attempts.iter().all(|attempt| {
                attempt.custody == Custody::Released
                    && (!attempt.admitted || attempt.worker.is_some())
            })
        {
            io.launches_by_unit.insert(unit.into(), count);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::failure_policy::Outcome;
    use crate::leases::ProcessIdentity;
    use crate::worker_lifecycle::{AttemptRecord, Report};

    #[test]
    fn launch_evidence_counts_worker_attempts_and_never_turns_uncertainty_into_zero() {
        let mut io = PythonIo::default();
        let attempt = AttemptRecord {
            attempt: 1,
            admitted: false,
            worker: None,
            custody: Custody::Released,
        };
        let mut report = Report {
            outcome: Outcome {
                end: End::Failed(Stop::Cancelled),
                attempts: 0,
                cleanup: CleanupState::NotNeeded,
            },
            attempts: vec![attempt],
            outputs: None,
            abort: Some("submission failed".into()),
        };
        record_launches(&mut io, "known-zero", Some(&report));
        assert_eq!(io.launches_by_unit["known-zero"], 0);
        report.attempts[0].admitted = true;
        record_launches(&mut io, "admitted-only", Some(&report));
        assert!(!io.launches_by_unit.contains_key("admitted-only"));
        report.attempts[0].worker = Some(ProcessIdentity {
            pid: 123,
            boot: "fixture".into(),
            started: "one".into(),
        });
        let mut retry = report.attempts[0].clone();
        retry.attempt = 2;
        retry.worker.as_mut().unwrap().started = "two".into();
        report.attempts.push(retry);
        record_launches(&mut io, "retry", Some(&report));
        assert_eq!(io.launches_by_unit["retry"], 2);
        assert_eq!(io.launches, 2);
        report.attempts[1].custody = Custody::Held("cleanup uncertain".into());
        record_launches(&mut io, "held", Some(&report));
        assert!(!io.launches_by_unit.contains_key("held"));
        io.launches_by_unit.insert("missing-report".into(), 0);
        record_launches(&mut io, "missing-report", None);
        assert!(!io.launches_by_unit.contains_key("missing-report"));
    }
}

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
    /// submitted handle MUST get a terminal event. Each leased guard report parent MUST be
    /// reserved before submission, and lifecycle abort diagnostics MUST remain failures rather
    /// than appear as user cancellation. See failed_submission_keeps_abort_reason_without_claiming_user_cancellation
    /// and actual_python_first_build_and_current_noop_have_real_zero_launch_and_write_evidence.
    /// Production MUST refuse missing custodian
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
                work.inputs()
                    .io
                    .borrow_mut()
                    .launches_by_unit
                    .insert(work.unit().into(), 0);
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
            // Every early refusal below precedes submission. A returned lifecycle report replaces
            // this zero; missing/uncertain lifecycle evidence removes it rather than proving zero.
            work.inputs()
                .io
                .borrow_mut()
                .launches_by_unit
                .insert(work.unit().into(), 0);
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
            let report_root = scope.join("guard");
            if let Err(error) = std::fs::create_dir(&report_root) {
                stopped |= emit(Event::Failed {
                    work,
                    reason: format!("cannot reserve leased guard report parent: {error}"),
                }) == Flow::Stop;
                continue;
            }
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
                report_root,
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
                    .map_err(|error| format!("{error:?}"))
            });
            record_launches(
                &mut work.inputs().io.borrow_mut(),
                work.unit(),
                result.as_ref().ok(),
            );
            let event = match result {
                Ok(report)
                    if !matches!(report.outcome.cleanup, CleanupState::Unconfirmed(_))
                        && report
                            .attempts
                            .iter()
                            .all(|attempt| attempt.custody == Custody::Released) =>
                {
                    if let Some(reason) = report.abort {
                        stopped |= emit(Event::Failed { work, reason }) == Flow::Stop;
                        continue;
                    }
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
