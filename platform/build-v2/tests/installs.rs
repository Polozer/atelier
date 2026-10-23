#![cfg(any(target_os = "macos", target_os = "linux"))]
use atelier_build_v2::{
    graph::*, install::*, keys::*, leases::*, results::*, schema::*, source_hashes::*, validate::*,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Workspace(PathBuf);
impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "atelier-v2-installs-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, p: &str) -> PathBuf {
        self.0.join(p)
    }
    fn installer(&self, project: &str) -> CheckoutInstaller {
        CheckoutInstaller::open(
            &self.0,
            self.path("cache"),
            InstallPolicy {
                project: namespace(project),
                allowed_install_roots: vec![
                    format!("games/{project}/Content"),
                    format!("games/{project}/Binaries"),
                ],
            },
        )
        .unwrap()
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn namespace(project: &str) -> ProjectNamespace {
    ProjectNamespace::new(project).unwrap()
}
fn identity() -> LeaseIdentity {
    LeaseIdentity {
        provenance: Provenance {
            checkout: "fixture".into(),
            branch: "fixture".into(),
            commit: "fixture".into(),
            dirty: false,
            built_at: "now".into(),
        },
        owner: ProcessIdentity {
            pid: 1,
            boot: "test".into(),
            started: "owner".into(),
        },
        workers: vec![],
        upstream_result_keys: BTreeSet::new(),
    }
}
fn fixture(project: &str, version: &str) -> (BuildGraph, PreparedUnit) {
    fixture_named(project, version, "/Game/Shared")
}
fn fixture_named(project: &str, version: &str, logical: &str) -> (BuildGraph, PreparedUnit) {
    let declaration = Declaration {
        schema_version: SCHEMA_VERSION,
        cache_version: version.into(),
        units: vec![Unit {
            id: "export".into(),
            op: Op {
                kind: "blob".into(),
                version: "1".into(),
            },
            script: "ops/run.py".into(),
            code: vec!["ops/run.py".into()],
            inputs: vec![],
            params: BTreeMap::new(),
            conditional: None,
            output_groups: vec![],
            outputs: vec![Item {
                id: "mesh".into(),
                logical_path: logical.into(),
                class: "Blob".into(),
                destination: Destination::Checkout,
                files: vec![
                    OutputFile {
                        path: "output/main.bin".into(),
                        install_path: Some(format!("games/{project}/Content/Shared.bin")),
                        required: true,
                    },
                    OutputFile {
                        path: "output/extra.bin".into(),
                        install_path: Some(format!("games/{project}/Content/Shared.side")),
                        required: false,
                    },
                ],
            }],
        }],
    };
    let registry = BTreeMap::from([(
        ("blob".into(), "1".into()),
        OpDefinition {
            inputs: BTreeMap::new(),
            output_classes: BTreeSet::from(["Blob".into()]),
            params: BTreeMap::new(),
        },
    )]);
    let roots = vec![
        format!("games/{project}/Content"),
        format!("games/{project}/Binaries"),
    ];
    let graph = BuildGraph::validate(declaration.clone(), &registry, &roots).unwrap();
    let snapshot = BTreeMap::from([("ops/run.py".into(), SnapshotEntry::File(b"script".to_vec()))]);
    let validated = validate(&declaration, &registry, &snapshot, &roots).unwrap();
    let implementation = ImplementationIdentity {
        version: "1".into(),
        digest: "a".repeat(64),
    };
    let unit = prepare(
        &declaration,
        &validated,
        "export",
        &KeyContext {
            snapshot: &snapshot,
            versions: &BTreeMap::new(),
            produced: &BTreeMap::new(),
            produced_groups: &BTreeMap::new(),
            staged_inputs: &BTreeMap::new(),
            worker: &implementation,
            validator: &implementation,
        },
        &mut SourceHashCache::default(),
    )
    .unwrap();
    (graph, unit)
}
fn view(project: &str, graph: &BuildGraph) -> OwnershipSnapshot {
    OwnershipSnapshot::from_projects([(namespace(project), graph)]).unwrap()
}

#[test]
fn receipt_owner_namespace_is_explicit_and_independent_of_selected_roots() {
    assert_ne!(
        OwnerId::new(namespace("first"), "/Game/Shared").unwrap(),
        OwnerId::new(namespace("second"), "/Game/Shared").unwrap()
    );
    assert_eq!(
        OwnerId::new(namespace("first"), "/Game/Shared").unwrap(),
        OwnerId::new(namespace("first"), "/game/shared").unwrap()
    );
    for bad in ["", ".", "..", "project/name", "with space"] {
        assert!(ProjectNamespace::new(bad).is_err());
    }
    let workspace = Workspace::new();
    let installer = workspace.installer("first");
    let guard = installer.locks().try_build_exclusive().unwrap();
    let (_, unit) = fixture("first", "1");
    assert!(matches!(
        installer.receipt_status(&guard, &unit).unwrap(),
        CurrentStatus::Dirty
    ));
    assert!(
        installer
            .prepare_restore(
                &guard,
                &unit,
                identity(),
                &view("first", &fixture("first", "1").0),
                vec![]
            )
            .unwrap()
            .is_none()
    );
}

#[cfg(target_os = "macos")]
fn publish(
    workspace: &Workspace,
    unit: &PreparedUnit,
    main: &[u8],
    side: Option<&[u8]>,
    mode: u32,
) {
    use std::os::unix::fs::PermissionsExt;
    let serial = NEXT.fetch_add(1, Ordering::Relaxed);
    let main_path = workspace.path(&format!("produced-{serial}"));
    fs::write(&main_path, main).unwrap();
    fs::set_permissions(&main_path, fs::Permissions::from_mode(mode)).unwrap();
    let mut sources = BTreeMap::from([(("mesh".into(), "output/main.bin".into()), main_path)]);
    if let Some(side) = side {
        let path = workspace.path(&format!("side-{serial}"));
        fs::write(&path, side).unwrap();
        sources.insert(("mesh".into(), "output/extra.bin".into()), path);
    }
    let identity = identity();
    ResultStore::open(workspace.path("cache"))
        .unwrap()
        .begin(
            unit,
            identity.provenance,
            identity.owner,
            identity.workers,
            identity.upstream_result_keys,
        )
        .unwrap()
        .stage(sources, |_| Ok(()))
        .unwrap()
        .publish(|_| Ok(()))
        .unwrap();
}
#[cfg(target_os = "macos")]
fn restore(
    installer: &CheckoutInstaller,
    guard: &atelier_build_v2::checkout_locks::BuildGuard,
    unit: &PreparedUnit,
    view: &OwnershipSnapshot,
) {
    assert!(matches!(
        installer
            .prepare_restore(guard, unit, identity(), view, vec![])
            .unwrap()
            .unwrap()
            .commit(guard, |_| Ok(()))
            .unwrap(),
        InstallOutcome::Installed
    ));
}

#[cfg(target_os = "macos")]
#[test]
fn install_modes_receipts_and_clone_independence_survive_cache_removal() {
    use std::os::unix::fs::PermissionsExt;
    let workspace = Workspace::new();
    let installer = workspace.installer("first");
    let guard = installer.locks().try_build_exclusive().unwrap();
    let (graph, unit) = fixture("first", "1");
    let view = view("first", &graph);
    publish(&workspace, &unit, b"executable", Some(b"side"), 0o755);
    restore(&installer, &guard, &unit, &view);
    let path = workspace.path("games/first/Content/Shared.bin");
    assert_eq!(
        fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o755
    );
    fs::remove_dir_all(workspace.path("cache")).unwrap();
    assert!(matches!(
        installer.receipt_status(&guard, &unit).unwrap(),
        CurrentStatus::Current(_)
    ));
    fs::write(&path, b"edited independently").unwrap();
    assert!(matches!(
        installer.receipt_status(&guard, &unit).unwrap(),
        CurrentStatus::Dirty
    ));
    assert_eq!(
        fs::read(workspace.path("games/first/Content/Shared.side")).unwrap(),
        b"side"
    );
}

#[cfg(target_os = "macos")]
#[test]
fn two_projects_same_logical_item_never_overwrite_receipts_or_retire_neighbor_sidecars() {
    let workspace = Workspace::new();
    let first = workspace.installer("first");
    let second = workspace.installer("second");
    let guard = first.locks().try_build_exclusive().unwrap();
    let (a1, u1) = fixture("first", "1");
    let (b1, v1) = fixture("second", "1");
    let both =
        OwnershipSnapshot::from_projects([(namespace("first"), &a1), (namespace("second"), &b1)])
            .unwrap();
    publish(&workspace, &u1, b"first", Some(b"first-side"), 0o644);
    publish(&workspace, &v1, b"second", Some(b"second-side"), 0o644);
    restore(&first, &guard, &u1, &both);
    restore(&second, &guard, &v1, &both);
    let (a2, u2) = fixture("first", "2");
    let both =
        OwnershipSnapshot::from_projects([(namespace("first"), &a2), (namespace("second"), &b1)])
            .unwrap();
    publish(&workspace, &u2, b"first-new", None, 0o644);
    restore(&first, &guard, &u2, &both);
    assert!(!workspace.path("games/first/Content/Shared.side").exists());
    assert_eq!(
        fs::read(workspace.path("games/second/Content/Shared.side")).unwrap(),
        b"second-side"
    );
    assert!(matches!(
        first.receipt_status(&guard, &u2).unwrap(),
        CurrentStatus::Current(_)
    ));
    assert!(matches!(
        second.receipt_status(&guard, &v1).unwrap(),
        CurrentStatus::Current(_)
    ));
}

#[cfg(target_os = "macos")]
#[test]
fn every_durable_install_cut_recovers_old_or_committed_named_files() {
    let cuts = [
        InstallEvent::JournalCreated,
        InstallEvent::FileStaged(0),
        InstallEvent::FileStaged(1),
        InstallEvent::Ready,
        InstallEvent::OldMoved(0),
        InstallEvent::NewMoved(0),
        InstallEvent::OldMoved(1),
        InstallEvent::NewMoved(1),
        InstallEvent::ReceiptsReady,
        InstallEvent::IndexCommitted,
        InstallEvent::CleanupComplete,
    ];
    for cut in cuts {
        let workspace = Workspace::new();
        let installer = workspace.installer("first");
        let guard = installer.locks().try_build_exclusive().unwrap();
        let (g1, u1) = fixture("first", "1");
        publish(&workspace, &u1, b"old", Some(b"old-side"), 0o644);
        restore(&installer, &guard, &u1, &view("first", &g1));
        let (g2, u2) = fixture("first", "2");
        let view = view("first", &g2);
        publish(&workspace, &u2, b"new", Some(b"new-side"), 0o755);
        let mut plan = installer
            .prepare_restore(&guard, &u2, identity(), &view, vec![])
            .unwrap()
            .unwrap();
        assert!(
            plan.commit_with(
                &guard,
                |event| if event == cut {
                    Err(std::io::Error::other("injected"))
                } else {
                    Ok(())
                },
                |_| Ok(())
            )
            .is_err(),
            "{cut:?}"
        );
        let committed = matches!(
            cut,
            InstallEvent::IndexCommitted | InstallEvent::CleanupComplete
        );
        if cut != InstallEvent::CleanupComplete {
            assert!(matches!(
                installer.locks().try_read_content(),
                Err(atelier_build_v2::checkout_locks::LockError::RecoveryRequired)
            ));
        }
        installer.recover(&guard, &view).unwrap();
        assert_eq!(
            fs::read(workspace.path("games/first/Content/Shared.bin")).unwrap(),
            if committed { &b"new"[..] } else { &b"old"[..] },
            "{cut:?}"
        );
        assert_eq!(
            fs::read(workspace.path("games/first/Content/Shared.side")).unwrap(),
            if committed {
                &b"new-side"[..]
            } else {
                &b"old-side"[..]
            },
            "{cut:?}"
        );
        installer.recover(&guard, &view).unwrap();
        installer.locks().try_read_content().unwrap();
    }
}

#[cfg(target_os = "macos")]
#[test]
fn foreign_files_busy_readers_root_failures_and_unknown_recovery_are_explicit() {
    use atelier_build_v2::checkout_locks::LockError;
    let workspace = Workspace::new();
    let installer = workspace.installer("first");
    let guard = installer.locks().try_build_exclusive().unwrap();
    let (graph, unit) = fixture("first", "1");
    let view = view("first", &graph);
    publish(&workspace, &unit, b"new", None, 0o644);
    fs::create_dir_all(workspace.path("games/first/Content")).unwrap();
    let target = workspace.path("games/first/Content/Shared.bin");
    fs::write(&target, b"foreign").unwrap();
    let mut plan = installer
        .prepare_restore(&guard, &unit, identity(), &view, vec![])
        .unwrap()
        .unwrap();
    assert!(plan.commit(&guard, |_| Ok(())).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"foreign");
    fs::remove_file(&target).unwrap();
    let reader = installer.locks().try_read_content().unwrap();
    assert!(matches!(
        plan.commit(&guard, |_| Ok(())),
        Err(InstallError::Lock(LockError::Busy))
    ));
    drop(reader);
    assert!(matches!(
        plan.commit(&guard, |_| Err("root unavailable".into()))
            .unwrap(),
        InstallOutcome::InstalledWithRootPending(_)
    ));
    assert!(matches!(
        installer.receipt_status(&guard, &unit).unwrap(),
        CurrentStatus::Current(_)
    ));
    let (next_graph, next) = fixture("first", "2");
    let next_view = crate::view("first", &next_graph);
    publish(&workspace, &next, b"later", None, 0o644);
    let mut plan = installer
        .prepare_restore(&guard, &next, identity(), &next_view, vec![])
        .unwrap()
        .unwrap();
    assert!(
        plan.commit_with(
            &guard,
            |event| if event == InstallEvent::NewMoved(0) {
                Err(std::io::Error::other("cut"))
            } else {
                Ok(())
            },
            |_| Ok(())
        )
        .is_err()
    );
    fs::write(&target, b"unknown external edit").unwrap();
    assert!(installer.recover(&guard, &next_view).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"unknown external edit");
    assert!(matches!(
        installer.locks().try_read_content(),
        Err(LockError::RecoveryRequired)
    ));
}

#[cfg(target_os = "macos")]
#[test]
fn whole_item_retirement_requires_exact_current_namespaced_receipt_authority() {
    let workspace = Workspace::new();
    let installer = workspace.installer("first");
    let guard = installer.locks().try_build_exclusive().unwrap();
    let (before, old) = fixture("first", "1");
    publish(&workspace, &old, b"old", Some(b"old-side"), 0o644);
    restore(&installer, &guard, &old, &view("first", &before));
    let CurrentStatus::Current(receipts) = installer.receipt_status(&guard, &old).unwrap() else {
        panic!("missing receipt")
    };
    let receipt = &receipts[0];
    let id = sha256(&canonical_bytes(receipt).unwrap());
    let removal = RemovalIntent {
        owner: receipt.owner.clone(),
        expected_receipt_id: id,
        exact_paths: receipt
            .files
            .iter()
            .map(|f| f.install_path.clone())
            .collect(),
    };
    let (after, new) = fixture_named("first", "2", "/Game/Replacement");
    let after_view = view("first", &after);
    publish(&workspace, &new, b"replacement", None, 0o644);
    let mut stale = removal.clone();
    stale.expected_receipt_id = "0".repeat(64);
    let mut plan = installer
        .prepare_restore(&guard, &new, identity(), &after_view, vec![stale])
        .unwrap()
        .unwrap();
    assert!(plan.commit(&guard, |_| Ok(())).is_err());
    assert!(
        installer
            .prepare_restore(
                &guard,
                &old,
                identity(),
                &view("first", &before),
                vec![removal.clone()]
            )
            .is_err()
    );
    let mut foreign = removal.clone();
    foreign.owner.project = namespace("other");
    assert!(
        installer
            .prepare_restore(&guard, &new, identity(), &after_view, vec![foreign])
            .is_err()
    );
    let mut plan = installer
        .prepare_restore(&guard, &new, identity(), &after_view, vec![removal])
        .unwrap()
        .unwrap();
    assert!(matches!(
        plan.commit(&guard, |_| Ok(())).unwrap(),
        InstallOutcome::Installed
    ));
    assert_eq!(
        fs::read(workspace.path("games/first/Content/Shared.bin")).unwrap(),
        b"replacement"
    );
    assert!(!workspace.path("games/first/Content/Shared.side").exists());
    assert!(matches!(
        installer.receipt_status(&guard, &old).unwrap(),
        CurrentStatus::Dirty
    ));
    assert!(matches!(
        installer.receipt_status(&guard, &new).unwrap(),
        CurrentStatus::Current(_)
    ));
}

#[test]
fn malformed_journal_and_linked_metadata_fail_closed_without_cleanup() {
    use atelier_build_v2::checkout_locks::LockError;
    let workspace = Workspace::new();
    let installer = workspace.installer("first");
    let guard = installer.locks().try_build_exclusive().unwrap();
    let (graph, _) = fixture("first", "1");
    let view = view("first", &graph);
    let journal = workspace.path("build/build-v2/install/journal.json");
    let unrelated = workspace.path("unrelated");
    fs::write(&unrelated, b"keep").unwrap();
    for invalid in [
        &b"[]"[..],
        &b"{"[..],
        &b"{\"digest\":\"bad\",\"journal\":{}}"[..],
    ] {
        fs::write(&journal, invalid).unwrap();
        assert!(installer.recover(&guard, &view).is_err());
        assert_eq!(fs::read(&journal).unwrap(), invalid);
        assert_eq!(fs::read(&unrelated).unwrap(), b"keep");
        assert!(matches!(
            installer.locks().try_read_content(),
            Err(LockError::RecoveryRequired)
        ));
    }
    fs::remove_file(&journal).unwrap();
    std::os::unix::fs::symlink(&unrelated, &journal).unwrap();
    assert!(installer.recover(&guard, &view).is_err());
    assert!(
        fs::symlink_metadata(&journal)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    assert_eq!(fs::read(&unrelated).unwrap(), b"keep");
    let isolated = Workspace::new();
    let target = Workspace::new();
    fs::write(target.path("sentinel"), b"foreign").unwrap();
    std::os::unix::fs::symlink(&target.0, isolated.path("build")).unwrap();
    assert!(
        CheckoutInstaller::open(
            &isolated.0,
            isolated.path("cache"),
            InstallPolicy {
                project: namespace("first"),
                allowed_install_roots: vec!["games/first/Content".into()]
            }
        )
        .is_err()
    );
    assert_eq!(fs::read(target.path("sentinel")).unwrap(), b"foreign");
}
