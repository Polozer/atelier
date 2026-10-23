#![cfg(any(target_os = "macos", target_os = "linux"))]
use atelier_build_v2::{
    demand::*, graph::*, install::*, integrity::NonHitReason, keys::*, leases::*, results::*,
    schema::*, source_hashes::*, store::StoreError, validate::*,
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
            "atelier-v2-demand-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, path: &str) -> PathBuf {
        self.0.join(path)
    }
    fn policy(&self) -> InstallPolicy {
        InstallPolicy {
            project: ProjectNamespace::new("fixture").unwrap(),
            allowed_install_roots: vec!["Content".into()],
        }
    }
    fn reader(&self) -> ReceiptReader {
        ReceiptReader::open(&self.0, self.policy()).unwrap()
    }
    fn installer(&self) -> Result<CheckoutInstaller, InstallError> {
        CheckoutInstaller::open(&self.0, self.path("cache"), self.policy())
    }
    fn store(&self) -> Result<ResultStore, ResultError> {
        ResultStore::open(self.path("cache"))
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
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

fn fixture() -> (BuildGraph, PreparedUnit, SourceSnapshot) {
    let declaration: Declaration = toml::from_str(r#"
schema_version = 2
cache_version = "fixture1"
[[units]]
id = "raw"
op = {kind = "fixture", version = "1"}
script = "op.py"
code = ["op.py"]
outputs = [{id = "raw", logical_path = "/Game/Raw", class = "Blob", destination = "store", files = [{path = "raw.bin"}]}]
[[units]]
id = "finish"
op = {kind = "fixture", version = "1"}
script = "op.py"
code = ["op.py"]
inputs = [{role = "reference", name = "rawref", logical_path = "/Game/Raw", class = "Blob", proof = "fixture", producer = {unit = "raw", item = "raw"}}]
outputs = [{id = "final", logical_path = "/Game/Final", class = "Blob", destination = "checkout", files = [{path = "final.bin", install_path = "Content/final.bin"}]}]
"#).unwrap();
    let registry = BTreeMap::from([(
        ("fixture".into(), "1".into()),
        OpDefinition {
            inputs: BTreeMap::from([(
                "rawref".into(),
                InputRule {
                    role: InputRole::Reference,
                    required: false,
                    allow_absent_file: false,
                    allow_selector: false,
                    require_whole_reason: false,
                    item_classes: BTreeSet::from(["Blob".into()]),
                },
            )]),
            output_classes: BTreeSet::from(["Blob".into()]),
            params: BTreeMap::new(),
        },
    )]);
    let roots = vec!["Content".into()];
    let snapshot = BTreeMap::from([("op.py".into(), SnapshotEntry::File(b"fixture".to_vec()))]);
    let graph = BuildGraph::validate(declaration.clone(), &registry, &roots).unwrap();
    let selected = graph
        .select(&[Target::Unit("finish".into())], &snapshot)
        .unwrap();
    assert_eq!(selected.order(), &["raw", "finish"]);
    let implementation = ImplementationIdentity {
        version: "1".into(),
        digest: "a".repeat(64),
    };
    let unit = prepare(
        &declaration,
        selected.validation(),
        "finish",
        &KeyContext {
            snapshot: &snapshot,
            versions: &BTreeMap::new(),
            produced: &BTreeMap::new(),
            produced_groups: &BTreeMap::new(),
            staged_inputs: &BTreeMap::from([("rawref".into(), "input/raw.json".into())]),
            worker: &implementation,
            validator: &implementation,
        },
        &mut SourceHashCache::default(),
    )
    .unwrap();
    (graph, unit, snapshot)
}
fn ownership(graph: &BuildGraph) -> OwnershipSnapshot {
    OwnershipSnapshot::from_projects([(ProjectNamespace::new("fixture").unwrap(), graph)]).unwrap()
}

#[test]
fn stored_miss_returns_original_single_prewrite_lease() {
    let workspace = Workspace::new();
    let (_, unit, _) = fixture();
    let StoredResolution::Miss(miss) = stored(&unit, || workspace.store(), identity()) else {
        panic!("empty cache is not a hit")
    };
    assert_eq!(miss.reason, NonHitReason::MissingRecord);
    assert!(miss.failure.is_none());
    let mut transaction = miss.transaction.unwrap();
    transaction
        .add_worker(ProcessIdentity {
            pid: 2,
            boot: "test".into(),
            started: "worker".into(),
        })
        .unwrap();
    let store = workspace.store().unwrap();
    let mutex = store.leases().lock().unwrap();
    let leases = mutex.leases().unwrap();
    assert_eq!(leases.len(), 1);
    assert_eq!(leases[0].id, transaction.lease().id);
    assert_eq!(leases[0].workers.len(), 1);
}

#[test]
fn unavailable_and_damaged_store_are_typed_non_hits() {
    let (_, unit, _) = fixture();
    for (error, reason) in [
        (
            ResultError::Io(std::io::Error::other("unavailable")),
            NonHitReason::StoreFailure,
        ),
        (
            ResultError::Store(StoreError::InvalidFile("damaged".into())),
            NonHitReason::CorruptObject,
        ),
        (
            ResultError::Store(StoreError::Io(std::io::Error::from(
                std::io::ErrorKind::NotFound,
            ))),
            NonHitReason::MissingObject,
        ),
    ] {
        let StoredResolution::Miss(miss) = stored(&unit, || Err(error), identity()) else {
            panic!("store failure is not a hit")
        };
        assert_eq!(miss.reason, reason);
        assert!(miss.failure.is_some());
        assert!(miss.transaction.is_none());
    }
}

#[test]
fn pending_recovery_is_hard_error_before_any_cache_access() {
    let workspace = Workspace::new();
    let (graph, unit, _) = fixture();
    let reader = workspace.reader();
    let guard = reader.locks().try_build_exclusive().unwrap();
    let journal = workspace.path("build/build-v2/install/journal.json");
    fs::write(&journal, b"unresolved install").unwrap();
    let result = checkout(
        &reader,
        &guard,
        &unit,
        || panic!("must not open cache"),
        identity(),
        &ownership(&graph),
        vec![],
    );
    assert!(matches!(result, Err(InstallError::Lock(_))));
    assert_eq!(fs::read(journal).unwrap(), b"unresolved install");
}

#[test]
fn checkout_miss_preserves_original_transaction() {
    let workspace = Workspace::new();
    let (graph, unit, _) = fixture();
    let reader = workspace.reader();
    let guard = reader.locks().try_build_exclusive().unwrap();
    let CheckoutResolution::Miss(miss) = checkout(
        &reader,
        &guard,
        &unit,
        || workspace.installer(),
        identity(),
        &ownership(&graph),
        vec![],
    )
    .unwrap() else {
        panic!("empty cache is not a hit")
    };
    assert_eq!(miss.reason, NonHitReason::MissingRecord);
    let transaction = miss.transaction.unwrap();
    let store = workspace.store().unwrap();
    let mutex = store.leases().lock().unwrap();
    let leases = mutex.leases().unwrap();
    assert_eq!(leases.len(), 1);
    assert_eq!(leases[0].id, transaction.lease().id);
}

#[test]
fn malformed_retirement_authority_refuses_before_cache_open_or_miss() {
    let workspace = Workspace::new();
    let (graph, unit, _) = fixture();
    let reader = workspace.reader();
    let guard = reader.locks().try_build_exclusive().unwrap();
    let removal = RemovalIntent {
        owner: OwnerId::new(ProjectNamespace::new("fixture").unwrap(), "/Game/Retired").unwrap(),
        expected_receipt_id: "malformed-receipt-id".into(),
        exact_paths: BTreeSet::from(["Content/retired.bin".into()]),
    };
    let opened = std::cell::Cell::new(false);
    let resolution = checkout(
        &reader,
        &guard,
        &unit,
        || {
            opened.set(true);
            workspace.installer()
        },
        identity(),
        &ownership(&graph),
        vec![removal],
    );
    assert!(matches!(resolution, Err(InstallError::Invalid(_))));
    assert!(!opened.get());
    assert!(!workspace.path("cache").exists());
    assert!(
        !workspace
            .path("build/build-v2/install/journal.json")
            .exists()
    );
}

#[test]
fn only_cache_origin_failures_become_checkout_non_hits() {
    let workspace = Workspace::new();
    let (graph, unit, _) = fixture();
    let reader = workspace.reader();
    let guard = reader.locks().try_build_exclusive().unwrap();
    // The same low-level code is a soft failure only with a genuine cache-origin wrapper.
    let CheckoutResolution::Miss(miss) = checkout(
        &reader,
        &guard,
        &unit,
        || {
            Err(InstallError::Cache(ResultError::Store(
                StoreError::InvalidDigest,
            )))
        },
        identity(),
        &ownership(&graph),
        vec![],
    )
    .unwrap() else {
        panic!("cache error is a non-hit")
    };
    assert_eq!(miss.reason, NonHitReason::MalformedObject);
    assert!(matches!(
        miss.failure,
        Some(ResultError::Store(StoreError::InvalidDigest))
    ));
    let hard = checkout(
        &reader,
        &guard,
        &unit,
        || Err(InstallError::Store(StoreError::InvalidDigest)),
        identity(),
        &ownership(&graph),
        vec![],
    );
    assert!(matches!(
        hard,
        Err(InstallError::Store(StoreError::InvalidDigest))
    ));
}

#[cfg(target_os = "macos")]
fn publish(workspace: &Workspace, unit: &PreparedUnit) {
    let path = workspace.path("produced.bin");
    fs::write(&path, b"final payload").unwrap();
    let identity = identity();
    workspace
        .store()
        .unwrap()
        .begin(
            unit,
            identity.provenance,
            identity.owner,
            identity.workers,
            identity.upstream_result_keys,
        )
        .unwrap()
        .stage(
            BTreeMap::from([(("final".into(), "final.bin".into()), path)]),
            |_| Ok(()),
        )
        .unwrap()
        .publish(|_| Ok(()))
        .unwrap();
}

#[cfg(target_os = "macos")]
#[test]
fn final_target_hit_installs_only_target_without_ancestor_materialization() {
    let workspace = Workspace::new();
    let (graph, unit, _) = fixture();
    publish(&workspace, &unit); // No raw result or raw output exists.
    fs::write(workspace.path("unrelated.bin"), b"keep").unwrap();
    let reader = workspace.reader();
    let guard = reader.locks().try_build_exclusive().unwrap();
    let CheckoutResolution::Hit(mut plan) = checkout(
        &reader,
        &guard,
        &unit,
        || workspace.installer(),
        identity(),
        &ownership(&graph),
        vec![],
    )
    .unwrap() else {
        panic!("final result is cached")
    };
    assert!(!workspace.path("Content/final.bin").exists());
    assert!(matches!(
        plan.commit(&guard, |_| Ok(())).unwrap(),
        InstallOutcome::Installed
    ));
    assert_eq!(
        fs::read(workspace.path("Content/final.bin")).unwrap(),
        b"final payload"
    );
    assert_eq!(fs::read(workspace.path("unrelated.bin")).unwrap(), b"keep");
    assert!(!workspace.path("raw.bin").exists());
    assert!(!workspace.path("Content/raw.bin").exists());
    let store = workspace.store().unwrap();
    let mutex = store.leases().lock().unwrap();
    assert_eq!(mutex.leases().unwrap().len(), 2); // Publication + final restore, no ancestor lookup.
}

#[cfg(target_os = "macos")]
#[test]
fn current_noop_never_opens_unavailable_cache_or_rewrites_files_and_receipts() {
    use std::os::unix::fs::MetadataExt;
    let workspace = Workspace::new();
    let (graph, unit, _) = fixture();
    publish(&workspace, &unit);
    let reader = workspace.reader();
    let guard = reader.locks().try_build_exclusive().unwrap();
    let CheckoutResolution::Hit(mut plan) = checkout(
        &reader,
        &guard,
        &unit,
        || workspace.installer(),
        identity(),
        &ownership(&graph),
        vec![],
    )
    .unwrap() else {
        panic!("hit")
    };
    plan.commit(&guard, |_| Ok(())).unwrap();
    fs::remove_dir_all(workspace.path("cache")).unwrap();
    fs::write(workspace.path("cache"), b"unavailable cache").unwrap();
    let index = workspace.path("build/build-v2/install/index.json");
    let index_bytes = fs::read(&index).unwrap();
    let indexed: serde_json::Value = serde_json::from_slice(&index_bytes).unwrap();
    let receipt_paths: Vec<_> = indexed["receipts"]
        .as_object()
        .unwrap()
        .values()
        .map(|id| {
            workspace.path(&format!(
                "build/build-v2/install/receipts/{}.json",
                id.as_str().unwrap()
            ))
        })
        .collect();
    let output = workspace.path("Content/final.bin");
    let metadata = |path: &PathBuf| {
        let m = fs::metadata(path).unwrap();
        (
            m.dev(),
            m.ino(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    let before = (metadata(&index), metadata(&output));
    let receipt_before: Vec<_> = receipt_paths
        .iter()
        .map(|p| (metadata(p), fs::read(p).unwrap()))
        .collect();
    for _ in 0..2 {
        let cold = workspace.reader();
        let CheckoutResolution::Current(receipts) = checkout(
            &cold,
            &guard,
            &unit,
            || panic!("Current must not open cache"),
            identity(),
            &ownership(&graph),
            vec![],
        )
        .unwrap() else {
            panic!("current")
        };
        assert_eq!(receipts.len(), 1);
    }
    assert_eq!(before, (metadata(&index), metadata(&output)));
    assert_eq!(
        receipt_before,
        receipt_paths
            .iter()
            .map(|p| (metadata(p), fs::read(p).unwrap()))
            .collect::<Vec<_>>()
    );
    assert_eq!(index_bytes, fs::read(index).unwrap());
    assert_eq!(fs::read(&output).unwrap(), b"final payload");
    assert_eq!(
        fs::read(workspace.path("cache")).unwrap(),
        b"unavailable cache"
    );
    // Current surviving output must not silently discard invalid retirement authority.
    let opened = std::cell::Cell::new(false);
    let retirement = RemovalIntent {
        owner: OwnerId::new(ProjectNamespace::new("fixture").unwrap(), "/Game/Retired").unwrap(),
        expected_receipt_id: "a".repeat(64),
        exact_paths: BTreeSet::new(),
    };
    let result = checkout(
        &reader,
        &guard,
        &unit,
        || {
            opened.set(true);
            Err(InstallError::Invalid(
                "retirement preflight sentinel".into(),
            ))
        },
        identity(),
        &ownership(&graph),
        vec![retirement],
    );
    assert!(!opened.get());
    assert!(matches!(result, Err(InstallError::Invalid(_))));
    // With a dirty receipt the same unavailable store is a typed non-hit, not Current.
    fs::write(&output, b"dirty local bytes").unwrap();
    let CheckoutResolution::Miss(miss) = checkout(
        &reader,
        &guard,
        &unit,
        || workspace.installer(),
        identity(),
        &ownership(&graph),
        vec![],
    )
    .unwrap() else {
        panic!("dirty is not current")
    };
    assert_eq!(miss.reason, NonHitReason::StoreFailure);
    assert_eq!(fs::read(&output).unwrap(), b"dirty local bytes");
}

#[cfg(target_os = "macos")]
#[test]
fn stored_hit_pins_without_install_and_failed_root_preserves_claims() {
    let workspace = Workspace::new();
    let (_, unit, _) = fixture();
    publish(&workspace, &unit);
    let StoredResolution::Hit(hit) = stored(&unit, || workspace.store(), identity()) else {
        panic!("hit")
    };
    assert_eq!(hit.result().result.key, unit.key());
    assert!(hit.groups().is_empty());
    assert!(!workspace.path("Content/final.bin").exists());
    assert!(hit.retain(|_| Err("root unavailable".into())).is_err());
    let store = workspace.store().unwrap();
    let mutex = store.leases().lock().unwrap();
    assert!(mutex.leases().unwrap().iter().any(|lease| !lease.rooted
        && lease.result_keys.contains(unit.key())
        && !lease.object_digests.is_empty()));
    assert!(!workspace.path("Content/final.bin").exists());
}
