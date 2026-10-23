//! The C5c resident window's exact setup sequence (`tests/support/resident_setup.rs`, shared with
//! `examples/resident_window.rs`) on any host, stopping before any launch: no bridge, worker,
//! interpreter or admission is started. It binds the worker identity and command, validates and
//! prepares every unit with the proof's install policy, takes the real B3 locks and custody, opens
//! the receipt reader with the same policy, binds both leases of every case's units, and runs the
//! production registration on them, then re-reads both leases from disk.
#![cfg(unix)]

#[path = "support/resident_setup.rs"]
mod setup;

use atelier_build_v2::launch::PYTHON_JOB_LOOP_VERSION;
use atelier_build_v2::leases::{LeaseStore, ProcessIdentity};
use atelier_build_v2::python_backend::register_python_worker;
use atelier_build_v2::worker_lifecycle::{JobSandbox, LockScope};
use std::collections::BTreeSet;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

struct Scratch(PathBuf);
impl Scratch {
    fn new() -> Self {
        let path =
            std::env::temp_dir().join(format!("atelier-v2-resident-setup-{}", std::process::id()));
        fs::create_dir(&path).unwrap();
        Self(path.canonicalize().unwrap())
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        // The materialized worker folder is read-only by design.
        let _ = fs::set_permissions(self.0.join("worker"), fs::Permissions::from_mode(0o755));
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn on_disk(store: &LeaseStore, id: &str) -> bool {
    store
        .lock()
        .and_then(|guard| guard.leases())
        .is_ok_and(|records| records.iter().any(|record| record.id == id))
}

/// The example's cases, as (unit id, declared unit) pairs.
const CASES: [(&str, &[(&str, &str)]); 5] = [
    ("s1-single", &[("a", "a")]),
    ("s2-reuse", &[("b", "b"), ("a", "a")]),
    ("s3-aba", &[("a1", "a"), ("b", "b"), ("a2", "a")]),
    ("s5-cancel", &[("spin", "spin")]),
    ("s6-originals", &[("a", "a")]),
];

#[test]
fn the_resident_window_setup_binds_every_input_without_launching() {
    let scratch = Scratch::new();
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("../studio/atelier/build_v2");
    // Never executed: the sequence stops before any launch.
    let python = Path::new("/usr/bin/python3");

    // A relative interpreter is refused: the loop runs with `/` as its working folder.
    let snapshot = setup::worker_snapshot(&source).unwrap();
    assert!(
        setup::worker_command(Path::new("python3"), &snapshot, &scratch.0.join("relative"))
            .is_err()
    );

    let world = setup::world(python, &source, &scratch.0.join("worker")).unwrap();
    assert_eq!(world.command.program, python);
    assert_eq!(world.command.cwd, Path::new("/"));
    assert_eq!(world.worker.digest.len(), 64);
    assert_eq!(
        world
            .prepared
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>(),
        setup::UNITS.to_vec()
    );
    // The install policy the reader and `validate` share is valid and non-empty.
    let policy = setup::install_policy().unwrap();
    assert_eq!(policy.allowed_install_roots, setup::install_roots());
    assert!(!policy.allowed_install_roots.is_empty());

    let owner = ProcessIdentity {
        pid: std::process::id(),
        boot: "setup-test".into(),
        started: "setup-test".into(),
    };
    let worker = ProcessIdentity {
        pid: std::process::id(),
        boot: "setup-test".into(),
        started: "setup-test-worker".into(),
    };
    let monitor = ProcessIdentity {
        pid: std::process::id(),
        boot: "setup-test".into(),
        started: "setup-test-monitor".into(),
    };
    for (case, units) in CASES {
        let root = scratch.0.join(case);
        fs::create_dir(&root).unwrap();
        let mut bound = setup::case_setup(&world, &owner, &root, units)
            .unwrap_or_else(|error| panic!("{case}: {error}"));

        // Real B3 custody: the build lock exclusive and the content lock shared, as the key's set.
        assert_eq!(bound.custody.len(), 2, "{case}");
        let scopes: BTreeSet<LockScope> = bound.custody_set.iter().map(|c| c.scope).collect();
        assert_eq!(
            scopes,
            [LockScope::Exclusive, LockScope::Shared].into(),
            "{case}"
        );
        assert_eq!(bound.key.custody, bound.custody_set, "{case}");
        assert_eq!(bound.key.sandbox, JobSandbox::NoFork, "{case}");
        assert_eq!(bound.key.memory_gib, setup::MEMORY_GIB, "{case}");
        assert_eq!(bound.key.worker_version, PYTHON_JOB_LOOP_VERSION, "{case}");
        assert_eq!(bound.lock_files.len(), 2, "{case}");
        assert!(bound.lock_paths.iter().all(|path| path.is_file()), "{case}");
        assert!(setup::installer_busy(&bound.checkout), "{case}");
        assert!(setup::reader_admitted(&bound.checkout), "{case}");

        // Both leases of every unit are bound, and on disk, before any launch.
        assert_eq!(bound.leases.len(), units.len(), "{case}");
        for (unit, (local_id, cas_id)) in &bound.lease_ids {
            assert!(on_disk(&bound.local_leases, local_id), "{case} {unit}");
            assert!(on_disk(bound.store.leases(), cas_id), "{case} {unit}");
        }
        // The production registration of a worker and a monitor, then the independent re-read
        // the register callback's before-Run gate makes.
        for (unit, leases) in bound.leases.iter_mut() {
            let (local_id, cas_id) = &bound.lease_ids[unit];
            assert!(
                setup::lease_holds(&bound.local_leases, local_id, &worker).is_err(),
                "{case} {unit}"
            );
            for identity in [&worker, &monitor] {
                register_python_worker(&mut leases.local, Some(&mut leases.cas), identity).unwrap();
            }
            for identity in [&worker, &monitor] {
                setup::lease_holds(&bound.local_leases, local_id, identity).unwrap();
                setup::lease_holds(bound.store.leases(), cas_id, identity).unwrap();
            }
        }

        // Dropping the originals leaves the custody duplicates holding the locks.
        drop(bound.originals.take());
        assert!(setup::installer_busy(&bound.checkout), "{case}");
        let checkout = bound.checkout.clone();
        drop(bound);
        assert!(!setup::installer_busy(&checkout), "{case}");
    }
}
