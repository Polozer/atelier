use atelier_build_v2::{
    integrity::*, keys::*, leases::*, results::*, schema::*, source_hashes::*, store::*,
    validate::*, verify::*,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

static SERIAL: AtomicU64 = AtomicU64::new(0);

struct Workspace(PathBuf);

impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "atelier-v2-verify-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }

    fn store_root(&self) -> PathBuf {
        self.path("store")
    }

    fn result_store(&self) -> ResultStore {
        ResultStore::open(self.store_root()).unwrap()
    }

    fn verifier(&self) -> Verifier {
        Verifier::open(self.store_root()).unwrap()
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn process(pid: u32) -> ProcessIdentity {
    ProcessIdentity {
        pid,
        boot: "boot-verify".into(),
        started: format!("start-{pid}"),
    }
}

fn provenance(name: &str) -> Provenance {
    Provenance {
        checkout: name.into(),
        branch: name.into(),
        commit: name.into(),
        dirty: false,
        built_at: "2026-10-23T00:00:00Z".into(),
    }
}

fn set_readonly(path: &Path, mode: u32) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
    }
    #[cfg(not(unix))]
    {
        let _ = mode;
        let mut perms = fs::metadata(path).unwrap().permissions();
        perms.set_readonly(true);
        fs::set_permissions(path, perms).unwrap();
    }
}

fn set_writable(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o644)).unwrap();
    }
    #[cfg(not(unix))]
    {
        let mut perms = fs::metadata(path).unwrap().permissions();
        perms.set_readonly(false);
        fs::set_permissions(path, perms).unwrap();
    }
}

fn prepared_unit(id: &str, code_bytes: &[u8]) -> PreparedUnit {
    let declaration = Declaration {
        schema_version: SCHEMA_VERSION,
        cache_version: "1".into(),
        units: vec![Unit {
            id: id.into(),
            op: Op {
                kind: "data".into(),
                version: "1".into(),
            },
            script: "ops/run.py".into(),
            code: vec!["ops/run.py".into()],
            inputs: vec![],
            params: BTreeMap::new(),
            conditional: None,
            output_groups: vec![],
            outputs: vec![Item {
                id: "data".into(),
                logical_path: format!("/Data/{id}"),
                class: "Data".into(),
                destination: Destination::Store,
                files: vec![
                    OutputFile {
                        path: "result.bin".into(),
                        install_path: None,
                        required: true,
                    },
                    OutputFile {
                        path: "optional.bin".into(),
                        install_path: None,
                        required: false,
                    },
                ],
            }],
        }],
    };
    let registry = BTreeMap::from([(
        ("data".into(), "1".into()),
        OpDefinition {
            inputs: BTreeMap::new(),
            output_classes: BTreeSet::from(["Data".into()]),
            params: BTreeMap::new(),
        },
    )]);
    let snapshot = BTreeMap::from([(
        "ops/run.py".into(),
        SnapshotEntry::File(code_bytes.to_vec()),
    )]);
    let validated = validate(&declaration, &registry, &snapshot, &[]).unwrap();
    let implementation = ImplementationIdentity {
        version: "1".into(),
        digest: "a".repeat(64),
    };
    prepare(
        &declaration,
        &validated,
        id,
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
    .unwrap()
}

fn write_stored_object(store_root: &Path, bytes: &[u8]) -> String {
    let digest = sha256(bytes);
    let path = store_root
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&digest);
    if !path.exists() {
        fs::write(&path, bytes).unwrap();
        set_readonly(&path, 0o444);
    }
    digest
}

fn write_stored_record(
    store_root: &Path,
    unit: &PreparedUnit,
    files: Vec<(&str, &[u8], u32)>,
) -> ResultEnvelope {
    let mut stored_files = Vec::new();
    for (rel_path, bytes, mode) in files {
        let digest = write_stored_object(store_root, bytes);
        stored_files.push(StoredFile {
            path: rel_path.into(),
            digest,
            size: bytes.len() as u64,
            mode,
        });
    }
    let item = unit.ingredients().logical_outputs[0].clone();
    let envelope = ResultEnvelope {
        version: ENVELOPE_VERSION,
        result: ResultRecord {
            schema_version: RESULT_SCHEMA_VERSION,
            unit: unit.request("", "").unit,
            key: unit.key().into(),
            ingredients: unit.ingredients().clone(),
            outputs: vec![StoredItem {
                item,
                files: stored_files,
                external_locator: None,
            }],
            output_groups: vec![],
            provenance: provenance("test"),
        },
        upstream_result_keys: BTreeSet::new(),
    };
    let record_path = store_root
        .join("results")
        .join(format!("{}.json", unit.key()));
    if record_path.exists() {
        set_writable(&record_path);
        fs::remove_file(&record_path).unwrap();
    }
    fs::write(&record_path, canonical_bytes(&envelope).unwrap()).unwrap();
    set_readonly(&record_path, 0o444);
    envelope
}

#[test]
fn good_records_and_objects_verify_with_deterministic_counts() {
    let workspace = Workspace::new();
    let _store = workspace.result_store();
    let verifier = workspace.verifier();

    let unit_a = prepared_unit("unit_a", b"code_a");
    let unit_b = prepared_unit("unit_b", b"code_b");
    let env_a = write_stored_record(
        &workspace.store_root(),
        &unit_a,
        vec![
            ("result.bin", b"alpha-payload", 0o644),
            ("optional.bin", b"alpha-sidecar", 0o755),
        ],
    );
    let env_b = write_stored_record(
        &workspace.store_root(),
        &unit_b,
        vec![("result.bin", b"beta-payload", 0o644)],
    );
    let standalone_digest = write_stored_object(&workspace.store_root(), b"standalone-blob");

    let target = VerificationTarget {
        units: vec![&unit_a],
        result_keys: BTreeSet::from([unit_b.key().to_string()]),
        objects: BTreeMap::from([(standalone_digest.clone(), Some(15))]),
    };

    let report = verifier
        .verify(&target, VerificationMode::Full, process(10))
        .unwrap();
    assert!(report.is_all_verified());
    assert!(report.sample.is_none());
    assert_eq!(
        report.counts,
        VerificationCounts {
            verified_records: 2,
            missing_records: 0,
            corrupt_records: 0,
            malformed_records: 0,
            incomplete_manifests: 0,
            unsupported_records: 0,
            external_records: 0,
            unverified_records: 0,
            verified_objects: 4,
            missing_objects: 0,
            corrupt_objects: 0,
            malformed_objects: 0,
            unverified_objects: 0,
            bytes_hashed: (13 + 13 + 12 + 15),
        }
    );
    assert_eq!(
        classify_record_outcome(&report.records[unit_a.key()]),
        LookupDecision::Hit
    );
    assert_eq!(
        classify_record_outcome(&report.records[unit_b.key()]),
        LookupDecision::Hit
    );
    assert_eq!(
        classify_object_outcome(&report.objects[&standalone_digest]),
        LookupDecision::Hit
    );
    assert_eq!(
        report.records[unit_a.key()],
        RecordOutcome::Verified {
            key: env_a.result.key,
            unit: "unit_a".into(),
            objects_verified: 2,
            bytes_hashed: 26,
        }
    );
    assert_eq!(
        report.records[unit_b.key()],
        RecordOutcome::Verified {
            key: env_b.result.key,
            unit: "unit_b".into(),
            objects_verified: 1,
            bytes_hashed: 12,
        }
    );
}

#[test]
fn normal_hit_does_not_rehash_while_verifier_catches_same_size_mtime_mutation() {
    let workspace = Workspace::new();
    let store = workspace.result_store();
    let verifier = workspace.verifier();
    let unit = prepared_unit("unit_hit", b"code_hit");

    #[cfg(target_os = "macos")]
    let envelope = {
        let src = workspace.path("src.bin");
        fs::write(&src, b"original-16bytes").unwrap();
        let sources = BTreeMap::from([(("data".into(), "result.bin".into()), src)]);
        store
            .begin(
                &unit,
                provenance("pub"),
                process(1),
                vec![],
                BTreeSet::new(),
            )
            .unwrap()
            .stage(sources, |_| Ok(()))
            .unwrap()
            .publish(|_| Ok(()))
            .unwrap()
    };
    #[cfg(not(target_os = "macos"))]
    let envelope = write_stored_record(
        &workspace.store_root(),
        &unit,
        vec![("result.bin", b"original-16bytes", 0o644)],
    );

    let digest = envelope.result.outputs[0].files[0].digest.clone();
    let obj_path = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&digest);
    let before_meta = fs::symlink_metadata(&obj_path).unwrap();
    let before_len = before_meta.len();
    let before_mtime = before_meta.modified().unwrap();

    // Mutate bytes in place while preserving exact byte length, mtime and read-only mode.
    set_writable(&obj_path);
    fs::write(&obj_path, b"corrupted16bytes").unwrap();
    File::open(&obj_path)
        .unwrap()
        .set_modified(before_mtime)
        .unwrap();
    set_readonly(&obj_path, 0o444);

    let after_meta = fs::symlink_metadata(&obj_path).unwrap();
    assert_eq!(after_meta.len(), before_len);
    assert_eq!(after_meta.modified().unwrap(), before_mtime);

    // 1. Normal B2 lookup checks metadata/size only and does NOT rehash object bytes.
    let mut tx = store
        .begin(
            &unit,
            provenance("lookup"),
            process(2),
            vec![],
            BTreeSet::new(),
        )
        .unwrap();
    let lookup_res = tx.lookup();
    assert_eq!(classify_lookup_result(&lookup_res), LookupDecision::Hit);
    let hit = lookup_res
        .unwrap()
        .expect("normal lookup returns hit without rehashing");
    assert_eq!(hit.result.key, unit.key());
    let _ = tx.retain_hit(|_| Ok(())).unwrap();

    #[cfg(target_os = "macos")]
    {
        let restored = workspace.path("restored.bin");
        let clone_res = verifier
            .objects()
            .clone_to(&ObjectDigest::from_hex(&digest).unwrap(), &restored);
        assert_eq!(
            classify_restore_result(&clone_res),
            RestoreDecision::Restored
        );
    }

    // 2. Explicit Verifier bypasses hints/metadata, rehashes actual bytes, and reports Corrupt.
    let target = VerificationTarget {
        units: vec![&unit],
        ..VerificationTarget::default()
    };
    let report = verifier
        .verify(&target, VerificationMode::Full, process(3))
        .unwrap();
    assert!(!report.is_all_verified());
    assert_eq!(report.counts.corrupt_records, 1);
    assert_eq!(report.counts.corrupt_objects, 1);
    assert_eq!(report.counts.verified_records, 0);
    assert_eq!(report.counts.verified_objects, 0);
    assert_eq!(
        report.objects[&digest],
        ObjectOutcome::Corrupt {
            digest: digest.clone(),
            reason: ObjectCorruption::DigestMismatch {
                expected_digest: digest.clone(),
                actual_digest: sha256(b"corrupted16bytes"),
                size: 16,
            },
        }
    );
    assert_eq!(
        report.records[unit.key()],
        RecordOutcome::Corrupt {
            key: unit.key().into(),
            reason: RecordCorruption::CorruptObjects {
                digests: vec![digest],
            },
        }
    );
    assert_eq!(
        classify_record_outcome(&report.records[unit.key()]),
        LookupDecision::Miss(NonHitReason::CorruptRecord)
    );
}

#[test]
fn isolated_corrupt_truncated_oversized_missing_and_mismatched_objects_report_precisely() {
    let workspace = Workspace::new();
    let _store = workspace.result_store();
    let verifier = workspace.verifier();

    let good_unit = prepared_unit("good", b"good_code");
    write_stored_record(
        &workspace.store_root(),
        &good_unit,
        vec![("result.bin", b"intact-payload", 0o644)],
    );

    let missing_obj_unit = prepared_unit("missing_obj", b"missing_obj_code");
    let missing_env = write_stored_record(
        &workspace.store_root(),
        &missing_obj_unit,
        vec![("result.bin", b"will-vanish", 0o644)],
    );
    let missing_digest = missing_env.result.outputs[0].files[0].digest.clone();
    let missing_path = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&missing_digest);
    set_writable(&missing_path);
    fs::remove_file(&missing_path).unwrap();

    // Truncated object (actual 4 bytes < expected 10 bytes).
    let truncated_digest = write_stored_object(&workspace.store_root(), b"0123456789");
    let truncated_path = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&truncated_digest);
    set_writable(&truncated_path);
    fs::write(&truncated_path, b"0123").unwrap();
    set_readonly(&truncated_path, 0o444);

    // Oversized object (actual 12 bytes > expected 6 bytes).
    let oversized_digest = write_stored_object(&workspace.store_root(), b"012345");
    let oversized_path = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&oversized_digest);
    set_writable(&oversized_path);
    fs::write(&oversized_path, b"0123456789ab").unwrap();
    set_readonly(&oversized_path, 0o444);

    // Object-name and content-digest mismatch (valid read-only bytes placed under a different valid hex digest name).
    let wrong_name_digest = "f".repeat(64);
    let wrong_name_path = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&wrong_name_digest);
    fs::write(&wrong_name_path, b"bytes-with-different-hash").unwrap();
    set_readonly(&wrong_name_path, 0o444);

    // Writable object.
    let writable_digest = write_stored_object(&workspace.store_root(), b"writable-bytes");
    let writable_path = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&writable_digest);
    set_writable(&writable_path);

    // Non-regular object (directory).
    let dir_digest = "e".repeat(64);
    fs::create_dir(
        workspace
            .store_root()
            .join("objects")
            .join(OBJECT_ALGORITHM)
            .join(&dir_digest),
    )
    .unwrap();

    let target = VerificationTarget {
        units: vec![&good_unit, &missing_obj_unit],
        result_keys: BTreeSet::new(),
        objects: BTreeMap::from([
            (truncated_digest.clone(), Some(10)),
            (oversized_digest.clone(), Some(6)),
            (wrong_name_digest.clone(), Some(25)),
            (writable_digest.clone(), Some(14)),
            (dir_digest.clone(), Some(0)),
            ("not-a-valid-digest".into(), None),
        ]),
    };

    let report = verifier
        .verify(&target, VerificationMode::Full, process(20))
        .unwrap();
    assert!(!report.is_all_verified());

    // Good unit remains verified in isolation.
    assert!(matches!(
        report.records[good_unit.key()],
        RecordOutcome::Verified { .. }
    ));
    assert_eq!(
        report.records[missing_obj_unit.key()],
        RecordOutcome::MissingObjects {
            key: missing_obj_unit.key().into(),
            missing_digests: vec![missing_digest.clone()],
        }
    );
    assert_eq!(
        classify_record_outcome(&report.records[missing_obj_unit.key()]),
        LookupDecision::Miss(NonHitReason::MissingObject)
    );
    assert_eq!(
        report.objects[&missing_digest],
        ObjectOutcome::Missing {
            digest: missing_digest
        }
    );
    assert_eq!(
        report.objects[&truncated_digest],
        ObjectOutcome::Corrupt {
            digest: truncated_digest,
            reason: ObjectCorruption::Truncated {
                expected_size: 10,
                actual_size: 4,
                actual_digest: sha256(b"0123"),
            },
        }
    );
    assert_eq!(
        report.objects[&oversized_digest],
        ObjectOutcome::Corrupt {
            digest: oversized_digest,
            reason: ObjectCorruption::SizeMismatch {
                expected_size: 6,
                actual_size: 12,
                actual_digest: sha256(b"0123456789ab"),
            },
        }
    );
    assert_eq!(
        report.objects[&wrong_name_digest],
        ObjectOutcome::Corrupt {
            digest: wrong_name_digest.clone(),
            reason: ObjectCorruption::DigestMismatch {
                expected_digest: wrong_name_digest,
                actual_digest: sha256(b"bytes-with-different-hash"),
                size: 25,
            },
        }
    );
    assert_eq!(
        report.objects[&writable_digest],
        ObjectOutcome::Corrupt {
            digest: writable_digest,
            reason: ObjectCorruption::WritableObject,
        }
    );
    assert_eq!(
        report.objects[&dir_digest],
        ObjectOutcome::Corrupt {
            digest: dir_digest,
            reason: ObjectCorruption::NotRegularFile,
        }
    );
    assert!(matches!(
        report.objects["not-a-valid-digest"],
        ObjectOutcome::Malformed { .. }
    ));
}

#[test]
fn malformed_unsupported_and_tampered_records_report_precisely() {
    let workspace = Workspace::new();
    let _store = workspace.result_store();
    let verifier = workspace.verifier();

    let base_unit = prepared_unit("base", b"base_code");
    let base_env = write_stored_record(
        &workspace.store_root(),
        &base_unit,
        vec![("result.bin", b"payload", 0o644)],
    );

    let write_raw_record = |key: &str, bytes: &[u8], readonly: bool| {
        let path = workspace
            .store_root()
            .join("results")
            .join(format!("{key}.json"));
        fs::write(&path, bytes).unwrap();
        if readonly {
            set_readonly(&path, 0o444);
        } else {
            set_writable(&path);
        }
    };

    let missing_key = "1".repeat(64);
    let writable_key = "2".repeat(64);
    write_raw_record(&writable_key, &canonical_bytes(&base_env).unwrap(), false);

    let malformed_json_key = "3".repeat(64);
    write_raw_record(&malformed_json_key, b"{not valid json", true);

    let unknown_field_key = "4".repeat(64);
    let mut unknown_val = serde_json::to_value(&base_env).unwrap();
    unknown_val["unexpected"] = serde_json::json!(true);
    write_raw_record(
        &unknown_field_key,
        &serde_json::to_vec(&unknown_val).unwrap(),
        true,
    );

    let unsupported_env_key = "5".repeat(64);
    let mut unsup_env_val = serde_json::to_value(&base_env).unwrap();
    unsup_env_val["version"] = serde_json::json!(99);
    unsup_env_val["future_envelope_field"] = serde_json::json!("ignored_by_version_gate");
    write_raw_record(
        &unsupported_env_key,
        &serde_json::to_vec(&unsup_env_val).unwrap(),
        true,
    );

    let unsupported_schema_key = "6".repeat(64);
    let mut unsup_schema_val = serde_json::to_value(&base_env).unwrap();
    unsup_schema_val["result"]["schema_version"] = serde_json::json!(99);
    write_raw_record(
        &unsupported_schema_key,
        &serde_json::to_vec(&unsup_schema_val).unwrap(),
        true,
    );

    let unsupported_groups_key = "9".repeat(64);
    let mut unsup_groups_val = serde_json::to_value(&base_env).unwrap();
    unsup_groups_val["result"]["output_groups"] = serde_json::json!([{"id": "pieces"}]);
    write_raw_record(
        &unsupported_groups_key,
        &serde_json::to_vec(&unsup_groups_val).unwrap(),
        true,
    );

    // Valid envelope stored under a different filename key -> KeyMismatch.
    let wrong_record_key = "7".repeat(64);
    write_raw_record(
        &wrong_record_key,
        &canonical_bytes(&base_env).unwrap(),
        true,
    );

    // Tampered ingredients with key updated to match filename -> IngredientsKeyMismatch.
    let tampered_key = "8".repeat(64);
    let mut tampered_env = base_env.clone();
    tampered_env.result.key = tampered_key.clone();
    tampered_env.result.ingredients.cache_version = "tampered-version".into();
    write_raw_record(
        &tampered_key,
        &canonical_bytes(&tampered_env).unwrap(),
        true,
    );

    let target = VerificationTarget {
        units: vec![],
        result_keys: BTreeSet::from([
            "bad-key-syntax".into(),
            missing_key.clone(),
            writable_key.clone(),
            malformed_json_key.clone(),
            unknown_field_key.clone(),
            unsupported_env_key.clone(),
            unsupported_schema_key.clone(),
            unsupported_groups_key.clone(),
            wrong_record_key.clone(),
            tampered_key.clone(),
        ]),
        objects: BTreeMap::new(),
    };

    let report = verifier
        .verify(&target, VerificationMode::Full, process(30))
        .unwrap();
    assert!(!report.is_all_verified());
    assert!(matches!(
        report.records["bad-key-syntax"],
        RecordOutcome::Malformed { .. }
    ));
    assert_eq!(
        report.records[&missing_key],
        RecordOutcome::Missing {
            key: missing_key.clone()
        }
    );
    assert_eq!(
        report.records[&writable_key],
        RecordOutcome::Corrupt {
            key: writable_key,
            reason: RecordCorruption::NotRegularOrWritableRecord,
        }
    );
    assert!(matches!(
        report.records[&malformed_json_key],
        RecordOutcome::Malformed { .. }
    ));
    assert!(matches!(
        report.records[&unknown_field_key],
        RecordOutcome::Malformed { .. }
    ));
    assert_eq!(
        report.records[&unsupported_env_key],
        RecordOutcome::Unsupported {
            key: unsupported_env_key.clone(),
            reason: UnsupportedReason::EnvelopeVersion(99),
        }
    );
    assert_eq!(
        classify_record_outcome(&report.records[&unsupported_env_key]),
        LookupDecision::Miss(NonHitReason::UnsupportedRecord)
    );
    assert_eq!(
        report.records[&unsupported_schema_key],
        RecordOutcome::Unsupported {
            key: unsupported_schema_key,
            reason: UnsupportedReason::ResultSchemaVersion(99),
        }
    );
    assert_eq!(
        report.records[&unsupported_groups_key],
        RecordOutcome::Unsupported {
            key: unsupported_groups_key,
            reason: UnsupportedReason::OutputGroupsUnsupported,
        }
    );
    assert_eq!(
        report.records[&wrong_record_key],
        RecordOutcome::Corrupt {
            key: wrong_record_key.clone(),
            reason: RecordCorruption::KeyMismatch {
                requested_key: wrong_record_key,
                record_key: base_unit.key().into(),
            },
        }
    );
    assert!(matches!(
        report.records[&tampered_key],
        RecordOutcome::Corrupt {
            reason: RecordCorruption::IngredientsKeyMismatch { .. },
            ..
        }
    ));
}

#[test]
fn incomplete_and_invalid_manifests_report_precisely() {
    let workspace = Workspace::new();
    let _store = workspace.result_store();
    let verifier = workspace.verifier();

    let save_custom = |unit: &PreparedUnit, outputs: Vec<StoredItem>| {
        let envelope = ResultEnvelope {
            version: ENVELOPE_VERSION,
            result: ResultRecord {
                schema_version: RESULT_SCHEMA_VERSION,
                unit: unit.request("", "").unit,
                key: unit.key().into(),
                ingredients: unit.ingredients().clone(),
                outputs,
                output_groups: vec![],
                provenance: provenance("manifest"),
            },
            upstream_result_keys: BTreeSet::new(),
        };
        let path = workspace
            .store_root()
            .join("results")
            .join(format!("{}.json", unit.key()));
        fs::write(&path, canonical_bytes(&envelope).unwrap()).unwrap();
        set_readonly(&path, 0o444);
    };

    // 1. Empty outputs vec -> ItemCountMismatch.
    let u_count = prepared_unit("u_count", b"c1");
    save_custom(&u_count, vec![]);

    // 2. Missing required file (only optional.bin present) -> MissingRequiredFile.
    let u_missing_req = prepared_unit("u_missing_req", b"c2");
    let valid_digest = write_stored_object(&workspace.store_root(), b"opt");
    save_custom(
        &u_missing_req,
        vec![StoredItem {
            item: u_missing_req.ingredients().logical_outputs[0].clone(),
            files: vec![StoredFile {
                path: "optional.bin".into(),
                digest: valid_digest.clone(),
                size: 3,
                mode: 0o644,
            }],
            external_locator: None,
        }],
    );

    // 3. Undeclared file path -> UndeclaredFile.
    let u_undeclared = prepared_unit("u_undeclared", b"c3");
    save_custom(
        &u_undeclared,
        vec![StoredItem {
            item: u_undeclared.ingredients().logical_outputs[0].clone(),
            files: vec![
                StoredFile {
                    path: "result.bin".into(),
                    digest: valid_digest.clone(),
                    size: 3,
                    mode: 0o644,
                },
                StoredFile {
                    path: "extra.bin".into(),
                    digest: valid_digest.clone(),
                    size: 3,
                    mode: 0o644,
                },
            ],
            external_locator: None,
        }],
    );

    // 4. Duplicate file path -> DuplicateFile.
    let u_dup = prepared_unit("u_dup", b"c4");
    save_custom(
        &u_dup,
        vec![StoredItem {
            item: u_dup.ingredients().logical_outputs[0].clone(),
            files: vec![
                StoredFile {
                    path: "result.bin".into(),
                    digest: valid_digest.clone(),
                    size: 3,
                    mode: 0o644,
                },
                StoredFile {
                    path: "result.bin".into(),
                    digest: valid_digest.clone(),
                    size: 3,
                    mode: 0o644,
                },
            ],
            external_locator: None,
        }],
    );

    // 5. Invalid semantic mode (0o600) -> Malformed.
    let u_mode = prepared_unit("u_mode", b"c5");
    save_custom(
        &u_mode,
        vec![StoredItem {
            item: u_mode.ingredients().logical_outputs[0].clone(),
            files: vec![StoredFile {
                path: "result.bin".into(),
                digest: valid_digest,
                size: 3,
                mode: 0o600,
            }],
            external_locator: None,
        }],
    );

    // 6. Two distinct Store items in the same record claiming the same job-output path ("result.bin") -> DuplicateFile.
    let base_cross = prepared_unit("u_cross_dup", b"c6");
    let mut cross_ingredients = base_cross.ingredients().clone();
    let item_1 = cross_ingredients.logical_outputs[0].clone();
    let mut item_2 = item_1.clone();
    item_2.id = "data_second".into();
    item_2.logical_path = "/Data/u_cross_dup_second".into();
    item_2.files = vec![OutputFile {
        path: "result.bin".into(),
        install_path: None,
        required: true,
    }];
    cross_ingredients.logical_outputs = vec![item_1.clone(), item_2.clone()];
    #[derive(serde::Serialize)]
    struct CrossKeyEncoding<'a> {
        domain: &'static str,
        version: u32,
        ingredients: &'a IdentityIngredients,
    }
    let cross_key = sha256(
        &canonical_bytes(&CrossKeyEncoding {
            domain: "atelier-unit-key",
            version: KEY_ENCODING_VERSION,
            ingredients: &cross_ingredients,
        })
        .unwrap(),
    );
    let cross_digest = write_stored_object(&workspace.store_root(), b"shared");
    let cross_env = ResultEnvelope {
        version: ENVELOPE_VERSION,
        result: ResultRecord {
            schema_version: RESULT_SCHEMA_VERSION,
            unit: "u_cross_dup".into(),
            key: cross_key.clone(),
            ingredients: cross_ingredients,
            outputs: vec![
                StoredItem {
                    item: item_1,
                    files: vec![StoredFile {
                        path: "result.bin".into(),
                        digest: cross_digest.clone(),
                        size: 6,
                        mode: 0o644,
                    }],
                    external_locator: None,
                },
                StoredItem {
                    item: item_2,
                    files: vec![StoredFile {
                        path: "result.bin".into(),
                        digest: cross_digest,
                        size: 6,
                        mode: 0o644,
                    }],
                    external_locator: None,
                },
            ],
            output_groups: vec![],
            provenance: provenance("manifest"),
        },
        upstream_result_keys: BTreeSet::new(),
    };
    let cross_path = workspace
        .store_root()
        .join("results")
        .join(format!("{cross_key}.json"));
    fs::write(&cross_path, canonical_bytes(&cross_env).unwrap()).unwrap();
    set_readonly(&cross_path, 0o444);

    let target = VerificationTarget {
        units: vec![&u_count, &u_missing_req, &u_undeclared, &u_dup, &u_mode],
        result_keys: BTreeSet::from([cross_key.clone()]),
        ..VerificationTarget::default()
    };
    let report = verifier
        .verify(&target, VerificationMode::Full, process(40))
        .unwrap();
    assert!(!report.is_all_verified());
    assert_eq!(report.counts.incomplete_manifests, 5);
    assert_eq!(
        report.records[&cross_key],
        RecordOutcome::IncompleteManifest {
            key: cross_key,
            defect: ManifestDefect::DuplicateFile {
                item_id: "data_second".into(),
                path: "result.bin".into(),
            },
        }
    );
    assert_eq!(report.counts.malformed_records, 1);

    assert_eq!(
        report.records[u_count.key()],
        RecordOutcome::IncompleteManifest {
            key: u_count.key().into(),
            defect: ManifestDefect::ItemCountMismatch {
                expected: 1,
                actual: 0,
            },
        }
    );
    assert_eq!(
        report.records[u_missing_req.key()],
        RecordOutcome::IncompleteManifest {
            key: u_missing_req.key().into(),
            defect: ManifestDefect::MissingRequiredFile {
                item_id: "data".into(),
                path: "result.bin".into(),
            },
        }
    );
    assert_eq!(
        report.records[u_undeclared.key()],
        RecordOutcome::IncompleteManifest {
            key: u_undeclared.key().into(),
            defect: ManifestDefect::UndeclaredFile {
                item_id: "data".into(),
                path: "extra.bin".into(),
            },
        }
    );
    assert_eq!(
        report.records[u_dup.key()],
        RecordOutcome::IncompleteManifest {
            key: u_dup.key().into(),
            defect: ManifestDefect::DuplicateFile {
                item_id: "data".into(),
                path: "result.bin".into(),
            },
        }
    );
    assert!(matches!(
        report.records[u_mode.key()],
        RecordOutcome::Malformed { .. }
    ));
    assert_eq!(
        classify_record_outcome(&report.records[u_missing_req.key()]),
        LookupDecision::Miss(NonHitReason::IncompleteManifest)
    );
}

#[test]
fn external_zen_references_and_deterministic_sampling_never_report_verified() {
    let workspace = Workspace::new();
    let _store = workspace.result_store();
    let verifier = workspace.verifier();

    // Craft a record with a canonical key whose logical_outputs item uses Destination::External.
    let base = prepared_unit("zen_pkg", b"zen_code");
    let mut ingredients = base.ingredients().clone();
    let ext_item = Item {
        id: "cooked_pkg".into(),
        logical_path: "/Game/Packages/Cooked".into(),
        class: "CookedPackage".into(),
        files: vec![],
        destination: Destination::External,
    };
    ingredients.logical_outputs = vec![ext_item.clone()];

    #[derive(serde::Serialize)]
    struct KeyEncoding<'a> {
        domain: &'static str,
        version: u32,
        ingredients: &'a IdentityIngredients,
    }
    let ext_key = sha256(
        &canonical_bytes(&KeyEncoding {
            domain: "atelier-unit-key",
            version: KEY_ENCODING_VERSION,
            ingredients: &ingredients,
        })
        .unwrap(),
    );
    let ext_envelope = ResultEnvelope {
        version: ENVELOPE_VERSION,
        result: ResultRecord {
            schema_version: RESULT_SCHEMA_VERSION,
            unit: "zen_pkg".into(),
            key: ext_key.clone(),
            ingredients: ingredients.clone(),
            outputs: vec![StoredItem {
                item: ext_item.clone(),
                files: vec![],
                external_locator: Some("zen://chunk/0123456789abcdef".into()),
            }],
            output_groups: vec![],
            provenance: provenance("zen"),
        },
        upstream_result_keys: BTreeSet::new(),
    };
    let ext_path = workspace
        .store_root()
        .join("results")
        .join(format!("{ext_key}.json"));
    fs::write(&ext_path, canonical_bytes(&ext_envelope).unwrap()).unwrap();
    set_readonly(&ext_path, 0o444);

    // Also craft an external record missing its locator -> Unsupported.
    let mut no_loc_ingredients = ingredients;
    no_loc_ingredients.cache_version = "2".into();
    let no_loc_key = sha256(
        &canonical_bytes(&KeyEncoding {
            domain: "atelier-unit-key",
            version: KEY_ENCODING_VERSION,
            ingredients: &no_loc_ingredients,
        })
        .unwrap(),
    );
    let no_loc_envelope = ResultEnvelope {
        version: ENVELOPE_VERSION,
        result: ResultRecord {
            schema_version: RESULT_SCHEMA_VERSION,
            unit: "zen_pkg_missing_locator".into(),
            key: no_loc_key.clone(),
            ingredients: no_loc_ingredients,
            outputs: vec![StoredItem {
                item: ext_item,
                files: vec![],
                external_locator: None,
            }],
            output_groups: vec![],
            provenance: provenance("zen"),
        },
        upstream_result_keys: BTreeSet::new(),
    };
    let no_loc_path = workspace
        .store_root()
        .join("results")
        .join(format!("{no_loc_key}.json"));
    fs::write(&no_loc_path, canonical_bytes(&no_loc_envelope).unwrap()).unwrap();
    set_readonly(&no_loc_path, 0o444);

    // Mixed record with both a local Store item (whose object is corrupt) and an External item:
    // local objects MUST still be hashed so corrupt local payloads report Corrupt rather than hiding behind External.
    let mut mixed_ingredients = base.ingredients().clone();
    let local_item = mixed_ingredients.logical_outputs[0].clone();
    let mixed_ext_item = Item {
        id: "cooked_pkg".into(),
        logical_path: "/Game/Packages/CookedMixed".into(),
        class: "CookedPackage".into(),
        files: vec![],
        destination: Destination::External,
    };
    mixed_ingredients.logical_outputs = vec![local_item.clone(), mixed_ext_item.clone()];
    let mixed_key = sha256(
        &canonical_bytes(&KeyEncoding {
            domain: "atelier-unit-key",
            version: KEY_ENCODING_VERSION,
            ingredients: &mixed_ingredients,
        })
        .unwrap(),
    );
    let corrupt_mixed_digest = "d".repeat(64);
    let corrupt_mixed_obj = workspace
        .store_root()
        .join("objects")
        .join(OBJECT_ALGORITHM)
        .join(&corrupt_mixed_digest);
    fs::write(&corrupt_mixed_obj, b"bad-mixed").unwrap();
    set_readonly(&corrupt_mixed_obj, 0o444);
    let mixed_envelope = ResultEnvelope {
        version: ENVELOPE_VERSION,
        result: ResultRecord {
            schema_version: RESULT_SCHEMA_VERSION,
            unit: "zen_mixed".into(),
            key: mixed_key.clone(),
            ingredients: mixed_ingredients,
            outputs: vec![
                StoredItem {
                    item: local_item,
                    files: vec![StoredFile {
                        path: "result.bin".into(),
                        digest: corrupt_mixed_digest.clone(),
                        size: 9,
                        mode: 0o644,
                    }],
                    external_locator: None,
                },
                StoredItem {
                    item: mixed_ext_item,
                    files: vec![],
                    external_locator: Some("zen://chunk/mixed".into()),
                },
            ],
            output_groups: vec![],
            provenance: provenance("zen"),
        },
        upstream_result_keys: BTreeSet::new(),
    };
    let mixed_path = workspace
        .store_root()
        .join("results")
        .join(format!("{mixed_key}.json"));
    fs::write(&mixed_path, canonical_bytes(&mixed_envelope).unwrap()).unwrap();
    set_readonly(&mixed_path, 0o444);

    let ext_target = VerificationTarget {
        units: vec![],
        result_keys: BTreeSet::from([ext_key.clone(), no_loc_key.clone(), mixed_key.clone()]),
        objects: BTreeMap::new(),
    };
    let ext_report = verifier
        .verify(&ext_target, VerificationMode::Full, process(50))
        .unwrap();
    assert!(!ext_report.is_all_verified());
    assert_eq!(ext_report.counts.verified_records, 0);
    assert_eq!(ext_report.counts.external_records, 1);
    assert_eq!(ext_report.counts.unverified_records, 1);
    assert_eq!(ext_report.counts.unsupported_records, 1);
    assert_eq!(ext_report.counts.corrupt_records, 1);
    assert_eq!(ext_report.counts.corrupt_objects, 1);
    assert_eq!(
        ext_report.records[&mixed_key],
        RecordOutcome::Corrupt {
            key: mixed_key,
            reason: RecordCorruption::CorruptObjects {
                digests: vec![corrupt_mixed_digest],
            },
        }
    );
    assert_eq!(
        ext_report.records[&ext_key],
        RecordOutcome::External {
            key: ext_key.clone(),
            items: vec![ExternalItemReport {
                item_id: "cooked_pkg".into(),
                logical_path: "/Game/Packages/Cooked".into(),
                locator: "zen://chunk/0123456789abcdef".into(),
            }],
        }
    );
    assert_eq!(
        classify_record_outcome(&ext_report.records[&ext_key]),
        LookupDecision::Miss(NonHitReason::ExternalUnverified)
    );
    assert_eq!(
        ext_report.records[&no_loc_key],
        RecordOutcome::Unsupported {
            key: no_loc_key,
            reason: UnsupportedReason::ExternalWithoutLocator {
                item_id: "cooked_pkg".into(),
                logical_path: "/Game/Packages/Cooked".into(),
            },
        }
    );

    // Deterministic sampling across 4 valid units:
    let units: Vec<PreparedUnit> = (0..4)
        .map(|i| {
            let u = prepared_unit(&format!("sample_{i}"), format!("code_{i}").as_bytes());
            write_stored_record(
                &workspace.store_root(),
                &u,
                vec![("result.bin", format!("payload_{i}").as_bytes(), 0o644)],
            );
            u
        })
        .collect();
    let sample_target = VerificationTarget {
        units: units.iter().collect(),
        result_keys: BTreeSet::new(),
        objects: BTreeMap::new(),
    };
    let mode = VerificationMode::Sampled(SampleSpec {
        seed: 77,
        max_results: 2,
        max_objects: 1,
    });
    let r1 = verifier.verify(&sample_target, mode, process(51)).unwrap();
    let r2 = verifier.verify(&sample_target, mode, process(52)).unwrap();
    assert_eq!(r1.sample, r2.sample);
    assert_eq!(r1.records, r2.records);
    assert_eq!(r1.objects, r2.objects);
    assert_eq!(r1.counts, r2.counts);
    // Because 2 records and 1 object were skipped by sampling, overall report is NOT all verified.
    assert!(!r1.is_all_verified());
    assert_eq!(r1.counts.verified_records, 1);
    assert_eq!(r1.counts.unverified_records, 3);
    assert_eq!(r1.counts.verified_objects, 1);
    assert_eq!(r1.counts.unverified_objects, 1);
    let plan = r1.sample.as_ref().unwrap();
    assert_eq!(plan.selected_records.len(), 2);
    assert_eq!(plan.skipped_records.len(), 2);
    for skipped_key in &plan.skipped_records {
        assert_eq!(
            r1.records[skipped_key],
            RecordOutcome::Unverified {
                key: skipped_key.clone(),
                reason: UnverifiedReason::SampleSkipped,
            }
        );
        assert_eq!(
            classify_record_outcome(&r1.records[skipped_key]),
            LookupDecision::Miss(NonHitReason::UnverifiedSample)
        );
    }
}

#[test]
fn pin_guard_releases_claims_on_normal_error_and_panic_exits_and_crashed_lease_is_reclaimable() {
    let workspace = Workspace::new();
    let _store = workspace.result_store();
    let verifier = workspace.verifier();

    let unit = prepared_unit("pinned_unit", b"pinned_code");
    let env = write_stored_record(
        &workspace.store_root(),
        &unit,
        vec![("result.bin", b"pinned-payload", 0o644)],
    );
    let obj_digest = env.result.outputs[0].files[0].digest.clone();

    let target = VerificationTarget {
        units: vec![&unit],
        ..VerificationTarget::default()
    };

    // 1. Mid-verify error injection: observe active pin, verify crashed-lease reclaimability, then inject error.
    let mut captured_mid_verify: Option<LeaseRecord> = None;
    let err_res = verifier.verify_observed(&target, VerificationMode::Full, process(60), |step| {
        if let VerifyStep::ManifestObjectsPinned { result_key, lease } = step {
            assert_eq!(result_key, unit.key());
            assert!(lease.result_keys.contains(unit.key()));
            assert!(lease.object_digests.contains(&obj_digest));
            assert!(!lease.rooted);
            // While alive or unknown, GC may not reclaim. If the owner died abruptly, GC can reclaim.
            assert!(!lease.may_reclaim(|_| Liveness::Alive));
            assert!(!lease.may_reclaim(|_| Liveness::Unknown));
            assert!(lease.may_reclaim(|_| Liveness::Dead));
            captured_mid_verify = Some(lease.clone());
            return Err(io::Error::other("injected mid-verify failure"));
        }
        Ok(())
    });
    assert!(err_res.is_err());
    let mid_lease = captured_mid_verify.expect("reached ManifestObjectsPinned");

    // PinGuard::drop must have released the claims and removed the empty staging directory.
    let leases_after_err = verifier.leases().lock().unwrap().leases().unwrap();
    let saved_after_err = leases_after_err
        .iter()
        .find(|l| l.id == mid_lease.id)
        .unwrap();
    assert!(saved_after_err.rooted);
    assert!(saved_after_err.result_keys.is_empty());
    assert!(saved_after_err.object_digests.is_empty());
    assert!(!workspace.store_root().join(&mid_lease.staging).exists());

    // 2. Mid-verify panic unwind: PinGuard::drop still releases claims on panic.
    let panic_res = std::panic::catch_unwind(|| {
        let _ = verifier.verify_observed(&target, VerificationMode::Full, process(61), |step| {
            if matches!(step, VerifyStep::ManifestObjectsPinned { .. }) {
                panic!("injected mid-verify panic");
            }
            Ok(())
        });
    });
    assert!(panic_res.is_err());

    let leases_after_panic = verifier.leases().lock().unwrap().leases().unwrap();
    assert!(
        leases_after_panic
            .iter()
            .all(|l| { l.rooted && l.result_keys.is_empty() && l.object_digests.is_empty() })
    );
    assert_eq!(
        fs::read_dir(workspace.store_root().join("staging"))
            .unwrap()
            .count(),
        0
    );
}

#[test]
fn cache_failures_preserve_valid_work_while_invalid_or_nondeterministic_outputs_fail() {
    assert_eq!(
        classify_completion::<()>(LocalOutputStatus::Valid, Ok(())),
        CompletionDecision::Cached
    );

    // Store, clone, metadata and root failures keep valid local work as CompletedNotCached.
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Valid,
            Err(ResultError::Io(io::Error::other("disk full")))
        ),
        CompletionDecision::CompletedNotCached(StoreFailureKind::Io)
    );
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Valid,
            Err(ResultError::Store(StoreError::Clone(io::Error::from(
                io::ErrorKind::Unsupported
            ))))
        ),
        CompletionDecision::CompletedNotCached(StoreFailureKind::CloneUnsupported)
    );
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Valid,
            Err(ResultError::Root("root write failed".into()))
        ),
        CompletionDecision::CompletedNotCached(StoreFailureKind::RootCallback)
    );
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Valid,
            Err(ResultError::Invalid("corrupt existing record".into()))
        ),
        CompletionDecision::CompletedNotCached(StoreFailureKind::StoreMetadata)
    );

    // Invalid producer output, validator rejection and nondeterminism ALWAYS fail the unit.
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Invalid("missing required output".into()),
            Ok(())
        ),
        CompletionDecision::FailUnit(UnitFailureReason::InvalidOutput(
            "missing required output".into()
        ))
    );
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Invalid("bad mesh".into()),
            Err(ResultError::Io(io::Error::other("also store failed")))
        ),
        CompletionDecision::FailUnit(UnitFailureReason::InvalidOutput("bad mesh".into()))
    );
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Valid,
            Err(ResultError::Validation("validator rejected".into()))
        ),
        CompletionDecision::FailUnit(UnitFailureReason::InvalidOutput(
            "validator rejected".into()
        ))
    );
    let key = "a".repeat(64);
    assert_eq!(
        classify_completion::<()>(
            LocalOutputStatus::Valid,
            Err(ResultError::Nondeterminism(key.clone()))
        ),
        CompletionDecision::FailUnit(UnitFailureReason::Nondeterminism(key))
    );

    // Clone failures during restore report UnsupportedClone explicitly and never fall back to copying.
    assert_eq!(
        classify_restore_result(&Err(StoreError::Clone(io::Error::from(
            io::ErrorKind::Unsupported
        )))),
        RestoreDecision::UnsupportedClone
    );
    assert_eq!(
        classify_restore_result(&Err(StoreError::Io(io::Error::from(
            io::ErrorKind::NotFound
        )))),
        RestoreDecision::Miss(NonHitReason::MissingObject)
    );
}
