use atelier_build_v2::python_worker::{PYTHON_WORKER_FILES, PythonWorkerBundle};
use atelier_build_v2::validate::{SnapshotEntry, SourceSnapshot};

#[test]
fn worker_identity_binds_all_explicit_implementation_bytes_and_refuses_incomplete_views() {
    let mut snapshot: SourceSnapshot = PYTHON_WORKER_FILES
        .into_iter()
        .map(|name| (name.into(), SnapshotEntry::File(name.as_bytes().to_vec())))
        .collect();
    let baseline = PythonWorkerBundle::from_snapshot(&snapshot)
        .unwrap()
        .identity();
    for name in PYTHON_WORKER_FILES {
        let mut changed = snapshot.clone();
        changed.insert(
            name.into(),
            SnapshotEntry::File(b"changed implementation".to_vec()),
        );
        assert_ne!(
            baseline.digest,
            PythonWorkerBundle::from_snapshot(&changed)
                .unwrap()
                .identity()
                .digest
        );
        changed.remove(name);
        assert!(PythonWorkerBundle::from_snapshot(&changed).is_err());
    }
    snapshot.insert("ambient_dependency.py".into(), SnapshotEntry::File(vec![]));
    assert!(PythonWorkerBundle::from_snapshot(&snapshot).is_err());
    snapshot.remove("ambient_dependency.py");
    snapshot.insert("protocol.py".into(), SnapshotEntry::Symlink);
    assert!(PythonWorkerBundle::from_snapshot(&snapshot).is_err());
}
