# Install precondition and fault evidence

`RestorePlan::commit_with` is nonblocking. It acquires exclusive content custody before creating
the install journal. A live shared reader can therefore return `InstallError::Lock(Busy)` before
any transaction starts. The old checkout stays readable and no journal is created. This is a
precondition refusal, not evidence that a failed transaction lost its barrier.

Once `JournalCreated` has run, an injected failure must leave its durable journal. Shared reader
admission then returns `RecoveryRequired` until exclusive recovery succeeds. Dropping the temporary
writer guard does not clear that journal barrier. The existing BSD `flock` locks are associated with
their open file description, not POSIX `fcntl` per-process record locks; guards never issue
`LOCK_UN`, and closing an unrelated descriptor does not release a live guard.

The portable regression exercises the real local-completion, install, lease and recovery APIs with
valid optional outputs all absent. No payload snapshot or APFS clone is fabricated. It establishes a
prior receipt index, holds a real shared reader, proves the exact pre-journal `Busy` error and then
releases that reader and injects the exact `JournalCreated` failure. It checks the hook, durable
journal, reader refusal, unchanged index and lease, retained completion evidence and recovery.

The APFS `CloneCreated` test now requires its fault hook, exact injected I/O error and journal to
exist before asserting reader exclusion. An arbitrary earlier error cannot stand in for this cut.
The original whole-binary-only report did not capture the error or whether the hook ran. A
precondition refusal explains the source-level sequence but remains an unproven diagnosis of that
historical run. There is no new evidence of product custody loss and no product locking change.

Linux proves the precondition and metadata-journal boundaries. The actual post-clone cut is still
macOS/APFS coverage deferred to MAC1; it is not reproduced by a local Mac run or relabelled portable
coverage. Install activation remains held until the recorded failure is classified with the exact
error/hook/journal evidence and the required native cut has been validated. No retry loop, sleep or
whole-suite serialization is added.
