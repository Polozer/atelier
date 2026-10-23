//! D1 (py_data): op definition, class-driven frozen output validation and real T1a multi-unit fixtures.
use atelier_build_v2::{
    keys::*, launch::*, py_data::*, results::*, schema::*, source_hashes::*, staging::*, store::*,
    validate::*, worker_session::*,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

static SERIAL: AtomicU64 = AtomicU64::new(0);

const UNSANDBOXED_TEST_VERSION: &str = "atelier-python-job-1+unsandboxed-test";

const DECLARATION_TOML: &str = r#"
schema_version = 2
cache_version = "v2-1"

[[units]]
id = "ferry.kit"
op = { kind = "py_data", version = "1" }
script = "ops/kit.py"
code = ["ops/kit.py", "ops/py_data.py"]
params = { seed = 11 }
outputs = [
  { id = "kit", logical_path = "/Data/Ferry/Kit", class = "Data", files = [{ path = "header.bin" }, { path = "bin/pack_tool.sh" }], destination = "store" },
  { id = "pier_ref", logical_path = "/Data/Ferry/PierRef", class = "JsonData", files = [{ path = "pier_meta.json" }], destination = "store" },
]

[[units]]
id = "ferry.route"
op = { kind = "py_data", version = "1" }
script = "ops/route.py"
code = ["ops/route.py", "ops/py_data.py"]
params = { seed = 17, scale = 2 }
inputs = [
  { role = "content", name = "harbour", source = { kind = "file", path = "SOURCE/harbours.json", selector = "/harbours/brinecove" } },
  { role = "content", name = "override", source = { kind = "file", path = "SOURCE/override.json", optional = true } },
  { role = "content", name = "kit", source = { kind = "item", unit = "ferry.kit", item = "kit" } },
  { role = "reference", name = "pier", logical_path = "/Data/Ferry/PierRef", class = "JsonData", proof = "reference_pier_meta_bytes", producer = { unit = "ferry.kit", item = "pier_ref" } },
]
outputs = [
  { id = "route", logical_path = "/Data/Ferry/Route", class = "RouteData", files = [{ path = "route.json" }], destination = "store" },
  { id = "summary", logical_path = "/Data/Ferry/Summary", class = "JsonData", files = [{ path = "summary.json", install_path = "Content/Data/ferry_summary.json" }, { path = "notes.json", install_path = "Content/Data/ferry_notes.json", required = false }], destination = "checkout" },
]

[[units]]
id = "ferry.runtime"
op = { kind = "py_data", version = "1" }
script = "ops/runtime.py"
code = ["ops/runtime.py", "ops/py_data.py"]
params = { seed = 23, tick_hz = 20 }
inputs = [
  { role = "content", name = "route", source = { kind = "item", unit = "ferry.route", item = "route" } },
]
outputs = [
  { id = "runtime", logical_path = "/Data/Ferry/Runtime", class = "RuntimeData", files = [{ path = "ferry_runtime.bin", install_path = "Content/Data/ferry_runtime.bin" }], destination = "checkout" },
]
"#;

const KIT_SCRIPT: &str = r#"
import py_data

def run(context):
    py_data.write_bytes(context, 'header.bin', f'KIT-SEED-{context.seed}'.encode('utf-8'), executable=False)
    py_data.write_bytes(context, 'bin/pack_tool.sh', b'#!/bin/sh\necho pack\n', executable=True)
    py_data.write_json(context, 'pier_meta.json', {'berth': 'north', 'seed': context.seed})
"#;

const ROUTE_SCRIPT: &str = r#"
import os, random
import py_data

def run(context):
    harbour = py_data.read_json(context, 'harbour')
    override = py_data.read_json(context, 'override', default={'speed_knots': 12})
    kit_dir = context.input('kit')
    header = (kit_dir / 'header.bin').read_bytes().decode('utf-8')
    tool_exec = bool(os.stat(kit_dir / 'bin/pack_tool.sh').st_mode & 0o111)
    header_exec = bool(os.stat(kit_dir / 'header.bin').st_mode & 0o111)
    pier_descriptor = py_data.read_json(context, 'pier')

    scale = context.params['scale']
    jitter = round(random.random(), 6)
    waypoints = [[float(c * scale) for c in pt] for pt in harbour['waypoints']]
    py_data.write_route(
        context,
        'route.json',
        route_id=harbour['id'],
        waypoints=waypoints,
        metadata={
            'header': header,
            'jitter': jitter,
            'pier_path': pier_descriptor['logical_path'],
            'speed_knots': override['speed_knots'],
            'tool_exec': tool_exec,
            'header_exec': header_exec,
        },
    )
    py_data.write_json(
        context,
        'summary.json',
        {
            'harbour': harbour['id'],
            'override_present': context.inputs['override'] is not None,
            'speed_knots': override['speed_knots'],
            'tool_exec': tool_exec,
            'header_exec': header_exec,
        },
    )
    if context.params.get('emit_notes'):
        py_data.write_json(context, 'notes.json', {'note': 'extra'})
    for extra in context.params.get('actions', []):
        exec(extra)
"#;

const RUNTIME_SCRIPT: &str = r#"
import json, struct
import py_data

def run(context):
    route_dir = context.input('route')
    route_doc = json.loads((route_dir / 'route.json').read_text(encoding='utf-8'))
    tick_hz = context.params['tick_hz']
    rec_meta = py_data.canonical_json_bytes({
        'route_id': route_doc['route_id'],
        'tick_hz': tick_hz,
        'waypoint_count': len(route_doc['waypoints']),
    })
    rec_dist = b''.join(struct.pack('>d', float(d)) for d in route_doc['distances_m'])
    py_data.write_runtime_binary(context, 'ferry_runtime.bin', [rec_meta, rec_dist])
"#;

struct Workspace(PathBuf);

impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "atelier-v2-py-data-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        if let Ok(entries) = fs::read_dir(&self.0) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.join("output").is_dir() {
                    let _ = remove_job(&path);
                }
            }
        }
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Default)]
struct MemoryObjects(BTreeMap<String, Vec<u8>>);

impl MemoryObjects {
    fn insert(&mut self, bytes: Vec<u8>) -> String {
        let digest = sha256(&bytes);
        self.0.insert(digest.clone(), bytes);
        digest
    }
}

impl ObjectSource for MemoryObjects {
    fn clone_object(&self, digest: &ObjectDigest, destination: &Path) -> Result<(), String> {
        let bytes = self
            .0
            .get(digest.as_hex())
            .ok_or_else(|| format!("object {digest} is not in MemoryObjects"))?;
        fs::write(destination, bytes).map_err(|error| error.to_string())?;
        fs::set_permissions(destination, fs::Permissions::from_mode(0o444))
            .map_err(|error| error.to_string())
    }
}

fn py_data_helper_source() -> Vec<u8> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../studio/atelier/build_v2/py_data.py");
    fs::read(path).unwrap()
}

fn python() -> PathBuf {
    std::env::split_paths(&std::env::var_os("PATH").unwrap())
        .map(|directory| directory.join("python3"))
        .find(|path| path.is_file())
        .expect("python3 on PATH runs the job loop")
}

fn use_sandbox() -> bool {
    cfg!(target_os = "macos")
}

fn worker_command(sandboxed: bool) -> WorkerCommand {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join(if sandboxed {
        "../studio/atelier/build_v2/python_worker.py"
    } else {
        "tests/fixtures/unsandboxed_job_loop.py"
    });
    WorkerCommand::python_job_loop(python(), script.canonicalize().unwrap())
}

fn worker_identity(sandboxed: bool) -> ImplementationIdentity {
    let version = if sandboxed {
        PYTHON_JOB_LOOP_VERSION
    } else {
        UNSANDBOXED_TEST_VERSION
    };
    let worker_path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../studio/atelier/build_v2/python_worker.py");
    let job_path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../studio/atelier/build_v2/python_job.py");
    let mut combined = fs::read(worker_path).unwrap();
    combined.extend_from_slice(&fs::read(job_path).unwrap());
    ImplementationIdentity {
        version: version.into(),
        digest: sha256(&combined),
    }
}

fn pipeline_spec() -> PyDataSpec {
    PyDataSpec::new()
        .with_content_slot("harbour", ContentSlotSpec::bounded(false))
        .with_content_slot("override", ContentSlotSpec::bounded(false))
        .with_content_slot("kit", ContentSlotSpec::bounded(false))
        .with_content_slot("route", ContentSlotSpec::bounded(false))
        .with_reference_slot("pier", false, ["JsonData"])
        .with_param("scale", ParamKind::Integer, false)
        .with_param("tick_hz", ParamKind::Integer, false)
        .with_param("emit_notes", ParamKind::Bool, false)
        .with_param("actions", ParamKind::Array, false)
}

fn pipeline_registry() -> OpRegistry {
    let mut registry = OpRegistry::new();
    pipeline_spec().register(&mut registry).unwrap();
    registry
}

fn staged_slots_for(unit_id: &str) -> BTreeMap<String, String> {
    match unit_id {
        "ferry.kit" => BTreeMap::new(),
        "ferry.route" => BTreeMap::from([
            ("harbour".into(), "in/harbour.json".into()),
            ("override".into(), "in/override.json".into()),
            ("kit".into(), "in/kit".into()),
            ("pier".into(), "in/pier.ref.json".into()),
        ]),
        "ferry.runtime" => BTreeMap::from([("route".into(), "in/route".into())]),
        other => panic!("unknown unit {other}"),
    }
}

struct PipelineFixture {
    declaration: Declaration,
    snapshot: SourceSnapshot,
    produced: ProducedItems,
    objects: MemoryObjects,
}

impl PipelineFixture {
    fn new(source_dir: &str) -> Self {
        let declaration =
            parse_declaration(&DECLARATION_TOML.replace("SOURCE", source_dir)).unwrap();
        let harbours = serde_json::json!({
            "harbours": {
                "brinecove": {
                    "id": "brinecove_harbour",
                    "waypoints": [[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.0, 16.0, 0.0]]
                },
                "hidamari": {
                    "id": "hidamari_harbour",
                    "waypoints": [[10.0, 0.0, 0.0], [20.0, 0.0, 0.0]]
                }
            }
        });
        let snapshot = BTreeMap::from([
            (
                "ops/py_data.py".into(),
                SnapshotEntry::File(py_data_helper_source()),
            ),
            (
                "ops/kit.py".into(),
                SnapshotEntry::File(KIT_SCRIPT.as_bytes().to_vec()),
            ),
            (
                "ops/route.py".into(),
                SnapshotEntry::File(ROUTE_SCRIPT.as_bytes().to_vec()),
            ),
            (
                "ops/runtime.py".into(),
                SnapshotEntry::File(RUNTIME_SCRIPT.as_bytes().to_vec()),
            ),
            (
                format!("{source_dir}/harbours.json"),
                SnapshotEntry::File(serde_json::to_vec(&harbours).unwrap()),
            ),
        ]);
        Self {
            declaration,
            snapshot,
            produced: ProducedItems::new(),
            objects: MemoryObjects::default(),
        }
    }

    fn validated(&self) -> ValidatedDeclaration {
        validate(
            &self.declaration,
            &pipeline_registry(),
            &self.snapshot,
            &["Content".into()],
        )
        .unwrap()
    }

    fn prepare_unit(&self, unit_id: &str, sandboxed: bool) -> PreparedUnit {
        let validated = self.validated();
        let staged = staged_slots_for(unit_id);
        let worker = worker_identity(sandboxed);
        let validator = py_data_validator_identity();
        prepare(
            &self.declaration,
            &validated,
            unit_id,
            &KeyContext {
                snapshot: &self.snapshot,
                versions: &BTreeMap::new(),
                produced: &self.produced,
                produced_groups: &BTreeMap::new(),
                staged_inputs: &staged,
                worker: &worker,
                validator: &validator,
            },
            &mut SourceHashCache::default(),
        )
        .unwrap()
    }

    /// Test-only fixture runner chaining C1b stage -> run_staged -> fixed_sources -> py_data validator.
    fn run_unit(
        &mut self,
        space: &Workspace,
        unit_id: &str,
        job_name: &str,
        sandboxed: bool,
    ) -> Result<(PreparedUnit, BTreeMap<(String, String), Vec<u8>>), String> {
        let prepared = self.prepare_unit(unit_id, sandboxed);
        check_py_data_unit_identity(&prepared)?;
        let job_dir = space.path(job_name);
        let staged = stage(&prepared, &self.snapshot, &self.objects, &job_dir, job_name)?;
        let worker = worker_identity(sandboxed);
        let outcome = run_staged(
            &DirectChild,
            &worker_command(sandboxed),
            &worker.version,
            &staged,
        );
        let actual = match outcome {
            Ok(JobOutcome::Completed(actual)) => actual,
            Ok(JobOutcome::Failed(failure)) => {
                let _ = remove_job(&job_dir);
                return Err(format!("{:?}: {}", failure.kind, failure.message));
            }
            Err(error) => {
                let _ = remove_job(&job_dir);
                return Err(error);
            }
        };
        let mapped = match fixed_sources(&prepared, &actual) {
            Ok(mapped) => mapped,
            Err(error) => {
                let _ = remove_job(&job_dir);
                return Err(error);
            }
        };

        let mut emitted_bytes = BTreeMap::new();
        for item in &prepared.ingredients().logical_outputs {
            let mut stored_files = Vec::new();
            for decl in &item.files {
                let key = (item.id.clone(), decl.path.clone());
                let Some(path) = mapped.get(&key) else {
                    if decl.required {
                        let _ = remove_job(&job_dir);
                        return Err(format!("missing required output {}", decl.path));
                    }
                    continue;
                };
                let bytes = fs::read(path).map_err(|error| error.to_string())?;
                let meta = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
                let mode = normalized_mode(meta.permissions().mode() & 0o777);
                if let Err(error) = validate_py_data_payload(&item.class, &decl.path, &bytes) {
                    let _ = remove_job(&job_dir);
                    return Err(error);
                }
                let digest = self.objects.insert(bytes.clone());
                stored_files.push(StoredFile {
                    path: decl.path.clone(),
                    digest,
                    size: bytes.len() as u64,
                    mode,
                });
                emitted_bytes.insert(key, bytes);
            }
            self.produced.insert(
                (unit_id.into(), item.id.clone()),
                StoredItem {
                    item: item.clone(),
                    files: stored_files,
                    external_locator: None,
                },
            );
        }
        remove_job(&job_dir)?;
        Ok((prepared, emitted_bytes))
    }
}

#[test]
fn op_definition_restricts_classes_to_data_and_requires_explicit_slots() {
    for valid in ["Data", "JsonData", "RouteData", "RuntimeData"] {
        assert_eq!(PyDataClass::parse(valid).unwrap().as_str(), valid);
    }
    for forbidden in ["StaticMeshSource", "Material", "SkeletalMesh", ""] {
        assert!(PyDataClass::parse(forbidden).is_err(), "{forbidden}");
    }

    // Empty output classes, non-integer seed, overlapping content/reference slots, or empty slot names fail.
    assert!(
        PyDataSpec::new()
            .with_output_classes(std::iter::empty())
            .build()
            .is_err()
    );
    assert!(
        PyDataSpec::new()
            .with_param("seed", ParamKind::String, false)
            .build()
            .is_err()
    );
    assert!(
        PyDataSpec::new()
            .with_content_slot("shared", ContentSlotSpec::bounded(false))
            .with_reference_slot("shared", false, ["JsonData"])
            .build()
            .is_err()
    );
    assert!(
        PyDataSpec::new()
            .with_reference_slot("empty_ref", false, std::iter::empty::<&str>())
            .build()
            .is_err()
    );

    // Broad content slots require a whole reason unless narrowed by a non-empty JSON pointer selector.
    let mut registry = OpRegistry::new();
    PyDataSpec::new()
        .with_content_slot("bundle", ContentSlotSpec::broad(true))
        .register(&mut registry)
        .unwrap();

    let mut fix = PipelineFixture::new("src");
    fix.declaration.units.truncate(1);
    fix.declaration.units[0].inputs = vec![Input::Content {
        name: "bundle".into(),
        source: ContentSource::File {
            path: "src/harbours.json".into(),
            selector: None,
            optional: false,
        },
        whole: None,
        conditional: None,
    }];
    assert!(
        validate(
            &fix.declaration,
            &registry,
            &fix.snapshot,
            &["Content".into()]
        )
        .is_err()
    );

    // Narrowing with a selector or adding a whole rationale passes validation.
    fix.declaration.units[0].inputs = vec![Input::Content {
        name: "bundle".into(),
        source: ContentSource::File {
            path: "src/harbours.json".into(),
            selector: Some("/harbours/brinecove".into()),
            optional: false,
        },
        whole: None,
        conditional: None,
    }];
    assert!(
        validate(
            &fix.declaration,
            &registry,
            &fix.snapshot,
            &["Content".into()]
        )
        .is_ok()
    );

    // Declaring a non-data output class (StaticMeshSource) on a py_data unit is rejected by A2 validation.
    fix.declaration.units[0].outputs[0].class = "StaticMeshSource".into();
    assert!(
        validate(
            &fix.declaration,
            &registry,
            &fix.snapshot,
            &["Content".into()]
        )
        .is_err()
    );
}

#[test]
fn clean_rebuild_byte_equality_across_workspaces_and_locators() {
    let sandboxed = use_sandbox();
    let space_a = Workspace::new();
    let space_b = Workspace::new();
    let mut fix_a = PipelineFixture::new("data/harbours");
    let mut fix_b = PipelineFixture::new("nested/other/source");

    for (idx, unit_id) in ["ferry.kit", "ferry.route", "ferry.runtime"]
        .into_iter()
        .enumerate()
    {
        let (prep_a, out_a) = fix_a
            .run_unit(&space_a, unit_id, &format!("a-{idx}"), sandboxed)
            .unwrap();
        let (prep_b, out_b) = fix_b
            .run_unit(&space_b, unit_id, &format!("b-other-{idx}"), sandboxed)
            .unwrap();
        assert_eq!(prep_a.key(), prep_b.key(), "unit {unit_id} key mismatch");
        assert_eq!(out_a, out_b, "unit {unit_id} output bytes mismatch");
        for bytes in out_a.values() {
            let text = String::from_utf8_lossy(bytes);
            for forbidden in [
                "data/harbours",
                "nested/other/source",
                "a-0",
                "b-other",
                space_a.0.to_str().unwrap(),
            ] {
                assert!(!text.contains(forbidden), "{forbidden} leaked into output");
            }
        }
    }

    #[cfg(target_os = "macos")]
    {
        use atelier_build_v2::leases::ProcessIdentity;
        use atelier_build_v2::verify::{VerificationMode, VerificationTarget, Verifier};

        // Also stage and publish through the real APFS ResultStore + validate_py_data_unit_outputs + Verifier.
        let store = ResultStore::open(space_a.path("store")).unwrap();
        let objects = ObjectStore::open(space_a.path("store")).unwrap();
        let kit_unit = fix_a.prepare_unit("ferry.kit", true);
        let owner = ProcessIdentity {
            pid: std::process::id(),
            boot: "boot-d1".into(),
            started: "start-d1".into(),
        };
        let prov = Provenance {
            checkout: "d1".into(),
            branch: "main".into(),
            commit: "3301a67b".into(),
            dirty: false,
            built_at: "now".into(),
        };
        let tx = store
            .begin(&kit_unit, prov, owner.clone(), vec![], BTreeSet::new())
            .unwrap();
        let staged_job = stage(
            &kit_unit,
            &fix_a.snapshot,
            &PinnedObjects::new(&objects, &tx),
            &space_a.path("real-store-job"),
            "real-store-job",
        )
        .unwrap();
        let JobOutcome::Completed(actual) = run_staged(
            &DirectChild,
            &worker_command(true),
            PYTHON_JOB_LOOP_VERSION,
            &staged_job,
        )
        .unwrap() else {
            panic!("sandboxed kit job failed");
        };
        let sources = fixed_sources(&kit_unit, &actual).unwrap();
        let staged_res = tx
            .stage(sources, |frozen| {
                validate_py_data_unit_outputs(&kit_unit, frozen)
            })
            .unwrap();
        let published = staged_res.publish(|_| Ok(())).unwrap();
        remove_job(staged_job.job_dir()).unwrap();

        let verifier = Verifier::open(space_a.path("store")).unwrap();
        let report = verifier
            .verify(
                &VerificationTarget {
                    units: vec![&kit_unit],
                    ..VerificationTarget::default()
                },
                VerificationMode::Full,
                owner,
            )
            .unwrap();
        assert!(report.is_all_verified());
        assert_eq!(published.result.key, kit_unit.key());
    }
}

#[test]
fn identical_selection_cutoff_and_relevant_edit_isolation() {
    let sandboxed = use_sandbox();
    let space = Workspace::new();
    let mut base = PipelineFixture::new("src");
    let (_, kit_out) = base
        .run_unit(&space, "ferry.kit", "base-kit", sandboxed)
        .unwrap();
    let (route_base, route_out) = base
        .run_unit(&space, "ferry.route", "base-route", sandboxed)
        .unwrap();
    let (runtime_base, runtime_out) = base
        .run_unit(&space, "ferry.runtime", "base-runtime", sandboxed)
        .unwrap();

    // 1. Edit unselected /harbours/hidamari in harbours.json: ferry.route key & outputs are unchanged.
    let mut unselected_edit = PipelineFixture::new("src");
    unselected_edit.produced = base.produced.clone();
    unselected_edit.objects = base.objects.clone();
    let edited_harbours = serde_json::json!({
        "harbours": {
            "brinecove": {
                "id": "brinecove_harbour",
                "waypoints": [[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.0, 16.0, 0.0]]
            },
            "hidamari": {
                "id": "hidamari_edited",
                "waypoints": [[999.0, 999.0, 0.0], [1000.0, 1000.0, 0.0]]
            }
        }
    });
    unselected_edit.snapshot.insert(
        "src/harbours.json".into(),
        SnapshotEntry::File(serde_json::to_vec(&edited_harbours).unwrap()),
    );
    assert_eq!(
        unselected_edit.prepare_unit("ferry.route", sandboxed).key(),
        route_base.key()
    );

    // 2. Comment edit in ops/route.py changes ferry.route's key, but its identical output stops propagation to ferry.runtime.
    let mut comment_edit = PipelineFixture::new("src");
    comment_edit.produced.insert(
        ("ferry.kit".into(), "kit".into()),
        base.produced[&("ferry.kit".into(), "kit".into())].clone(),
    );
    comment_edit.produced.insert(
        ("ferry.kit".into(), "pier_ref".into()),
        base.produced[&("ferry.kit".into(), "pier_ref".into())].clone(),
    );
    comment_edit.objects = base.objects.clone();
    comment_edit.snapshot.insert(
        "ops/route.py".into(),
        SnapshotEntry::File(format!("{ROUTE_SCRIPT}\n# comment-only change\n").into_bytes()),
    );
    let (route_comment, route_comment_out) = comment_edit
        .run_unit(&space, "ferry.route", "comment-route", sandboxed)
        .unwrap();
    assert_ne!(route_comment.key(), route_base.key());
    assert_eq!(route_comment_out, route_out);
    assert_eq!(
        comment_edit.prepare_unit("ferry.runtime", sandboxed).key(),
        runtime_base.key()
    );

    // 3. Relevant edit to ferry.runtime parameter (tick_hz: 20 -> 30) changes only ferry.runtime.
    let mut consumer_edit = PipelineFixture::new("src");
    consumer_edit.produced = base.produced.clone();
    consumer_edit.objects = base.objects.clone();
    consumer_edit.declaration.units[2]
        .params
        .insert("tick_hz".into(), serde_json::json!(30));
    assert_eq!(
        consumer_edit.prepare_unit("ferry.kit", sandboxed).key(),
        base.prepare_unit("ferry.kit", sandboxed).key()
    );
    assert_eq!(
        consumer_edit.prepare_unit("ferry.route", sandboxed).key(),
        route_base.key()
    );
    let (runtime_edited, runtime_edited_out) = consumer_edit
        .run_unit(&space, "ferry.runtime", "edited-runtime", sandboxed)
        .unwrap();
    assert_ne!(runtime_edited.key(), runtime_base.key());
    assert_ne!(runtime_edited_out, runtime_out);
    let _ = kit_out;
}

#[test]
fn optional_absent_versus_present_and_reference_only_identity() {
    let sandboxed = use_sandbox();
    let space = Workspace::new();
    let mut absent_fix = PipelineFixture::new("src");
    absent_fix
        .run_unit(&space, "ferry.kit", "opt-kit", sandboxed)
        .unwrap();
    let (route_absent, out_absent) = absent_fix
        .run_unit(&space, "ferry.route", "opt-absent", sandboxed)
        .unwrap();
    let summary_absent: serde_json::Value =
        serde_json::from_slice(&out_absent[&("summary".into(), "summary.json".into())]).unwrap();
    assert_eq!(summary_absent["override_present"], false);
    assert_eq!(summary_absent["speed_knots"], 12);

    // Present optional override changes key and output bytes.
    let mut present_fix = PipelineFixture::new("src");
    present_fix.produced = absent_fix.produced.clone();
    present_fix.objects = absent_fix.objects.clone();
    present_fix.snapshot.insert(
        "src/override.json".into(),
        SnapshotEntry::File(br#"{"speed_knots":15}"#.to_vec()),
    );
    let (route_present, out_present) = present_fix
        .run_unit(&space, "ferry.route", "opt-present", sandboxed)
        .unwrap();
    assert_ne!(route_present.key(), route_absent.key());
    let summary_present: serde_json::Value =
        serde_json::from_slice(&out_present[&("summary".into(), "summary.json".into())]).unwrap();
    assert_eq!(summary_present["override_present"], true);
    assert_eq!(summary_present["speed_knots"], 15);

    // Reference-only identity: changing pier_ref bytes does NOT change ferry.route's key or output.
    let mut ref_bytes_changed = PipelineFixture::new("src");
    ref_bytes_changed.produced = absent_fix.produced.clone();
    ref_bytes_changed.objects = absent_fix.objects.clone();
    let new_pier_digest = ref_bytes_changed
        .objects
        .insert(br#"{"berth":"south","seed":999}"#.to_vec());
    ref_bytes_changed
        .produced
        .get_mut(&("ferry.kit".into(), "pier_ref".into()))
        .unwrap()
        .files[0]
        .digest = new_pier_digest;
    assert_eq!(
        ref_bytes_changed
            .prepare_unit("ferry.route", sandboxed)
            .key(),
        route_absent.key()
    );

    // Changing reference logical_path DOES change ferry.route's key.
    ref_bytes_changed.declaration.units[0].outputs[1].logical_path =
        "/Data/Ferry/PierRefOther".into();
    if let Input::Reference { logical_path, .. } =
        &mut ref_bytes_changed.declaration.units[1].inputs[3]
    {
        *logical_path = "/Data/Ferry/PierRefOther".into();
    }
    assert_ne!(
        ref_bytes_changed
            .prepare_unit("ferry.route", sandboxed)
            .key(),
        route_absent.key()
    );
}

#[test]
fn executable_and_data_member_modes_roundtrip() {
    let sandboxed = use_sandbox();
    let space = Workspace::new();
    let mut fix = PipelineFixture::new("src");
    fix.run_unit(&space, "ferry.kit", "modes-kit", sandboxed)
        .unwrap();
    let stored_kit = &fix.produced[&("ferry.kit".into(), "kit".into())];
    let modes: BTreeMap<&str, u32> = stored_kit
        .files
        .iter()
        .map(|f| (f.path.as_str(), f.mode))
        .collect();
    assert_eq!(modes["header.bin"], 0o644);
    assert_eq!(modes["bin/pack_tool.sh"], 0o755);

    let (_, route_out) = fix
        .run_unit(&space, "ferry.route", "modes-route", sandboxed)
        .unwrap();
    let summary: serde_json::Value =
        serde_json::from_slice(&route_out[&("summary".into(), "summary.json".into())]).unwrap();
    assert_eq!(summary["tool_exec"], true);
    assert_eq!(summary["header_exec"], false);
}

#[test]
fn validator_and_staging_refuse_missing_extra_links_and_malformed_domain_data() {
    let sandboxed = use_sandbox();
    let space = Workspace::new();
    let mut base = PipelineFixture::new("src");
    base.run_unit(&space, "ferry.kit", "val-kit", sandboxed)
        .unwrap();

    // 1. Class-driven payload validation checks (independent of file extension):
    assert!(validate_py_data_payload("Data", "blob.any", b"non-empty").is_ok());
    assert!(validate_py_data_payload("Data", "blob.any", b"").is_err());
    assert!(validate_py_data_payload("StaticMeshSource", "mesh.glb", b"glb").is_err());

    // JsonData requires canonical sorted-key JSON object or array, even if named .dat
    assert!(validate_py_data_payload("JsonData", "payload.dat", br#"{"a":1,"b":2}"#).is_ok());
    assert!(validate_py_data_payload("JsonData", "payload.dat", br#"{"b":2,"a":1}"#).is_err());
    assert!(validate_py_data_payload("JsonData", "payload.dat", br#"{ "a": 1 }"#).is_err());
    assert!(validate_py_data_payload("JsonData", "payload.dat", b"42").is_err());
    assert!(validate_py_data_payload("JsonData", "payload.dat", b"{bad").is_err());

    // RouteData requires canonical JSON object with route_id, >= 2 finite 3D waypoints, and monotone distances_m
    let valid_route =
        br#"{"distances_m":[0.0,5.0],"route_id":"r1","waypoints":[[0.0,0.0,0.0],[3.0,4.0,0.0]]}"#;
    assert!(validate_py_data_payload("RouteData", "r.bin", valid_route).is_ok());
    for bad_route in [
        br#"{"distances_m":[0.0],"route_id":"r1","waypoints":[[0.0,0.0,0.0]]}"#.as_slice(),
        br#"{"distances_m":[0.0,5.0,3.0],"route_id":"r1","waypoints":[[0.0,0.0,0.0],[3.0,4.0,0.0],[6.0,8.0,0.0]]}"#.as_slice(),
        br#"{"distances_m":[1.0,5.0],"route_id":"r1","waypoints":[[0.0,0.0,0.0],[3.0,4.0,0.0]]}"#.as_slice(),
        br#"{"distances_m":[0.0,0.0],"route_id":"r1","waypoints":[[0.0,0.0,0.0],[0.0,0.0,0.0]]}"#.as_slice(),
        br#"{"distances_m":[0.0,5.0],"route_id":"","waypoints":[[0.0,0.0,0.0],[3.0,4.0,0.0]]}"#.as_slice(),
    ] {
        assert!(
            validate_py_data_payload("RouteData", "r.json", bad_route).is_err(),
            "{}",
            String::from_utf8_lossy(bad_route)
        );
    }

    // RuntimeData requires ATD1 v1 binary framing with complete non-empty records
    let valid_rt = b"ATD1\x01\x00\x00\x00\x01\x00\x00\x00\x03abc";
    assert!(validate_py_data_payload("RuntimeData", "rt.json", valid_rt).is_ok());
    for bad_rt in [
        b"ATD1\x01\x00\x00\x00".as_slice(),
        b"BAD!\x01\x00\x00\x00\x01\x00\x00\x00\x03abc".as_slice(),
        b"ATD1\x02\x00\x00\x00\x01\x00\x00\x00\x03abc".as_slice(),
        b"ATD1\x01\x00\x00\x00\x00".as_slice(),
        b"ATD1\x01\x00\x00\x00\x01\x00\x00\x00\x00".as_slice(),
        b"ATD1\x01\x00\x00\x00\x01\x00\x00\x00\x05abc".as_slice(),
        b"ATD1\x01\x00\x00\x00\x01\x00\x00\x00\x03abcX".as_slice(),
    ] {
        assert!(validate_py_data_payload("RuntimeData", "rt.bin", bad_rt).is_err());
    }

    // 2. Real worker runs with missing output, extra undeclared file, symlink, FIFO, or malformed route JSON all fail:
    for (idx, action) in [
        "os.remove('output/route.json')",
        "open('output/undeclared.txt', 'w').write('stray')",
        "os.symlink('/etc/hosts', 'output/link')",
        "os.mkfifo('output/fifo')",
        "open('output/route.json', 'w').write('{\"bad\": true}')",
    ]
    .into_iter()
    .enumerate()
    {
        let mut bad = PipelineFixture::new("src");
        bad.produced = base.produced.clone();
        bad.objects = base.objects.clone();
        bad.declaration.units[1]
            .params
            .insert("actions".into(), serde_json::json!([action]));
        assert!(
            bad.run_unit(&space, "ferry.route", &format!("bad-{idx}"), sandboxed)
                .is_err(),
            "action {action} should have failed"
        );
    }
}

#[test]
fn undeclared_reads_and_missing_required_inputs_fail_without_partial_publish() {
    let sandboxed = use_sandbox();
    let space = Workspace::new();
    let secret = space.path("undeclared-secret.json");
    fs::write(&secret, br#"{"secret":1}"#).unwrap();

    let mut base = PipelineFixture::new("src");
    base.run_unit(&space, "ferry.kit", "sec-kit", sandboxed)
        .unwrap();

    for (idx, attempt) in [
        format!("open({secret:?}).read()"),
        format!("os.path.exists({:?})", space.path("missing-undeclared")),
        "os.listdir('..')".to_string(),
        "from pathlib import Path; import sys; Path('output/undeclared_helper.py').write_text('X = 1'); sys.path.append('output'); import undeclared_helper".to_string(),
        format!("import sys; sys.path.append({:?}); import undeclared_helper", space.0),
    ]
    .into_iter()
    .enumerate()
    {
        let mut bad = PipelineFixture::new("src");
        bad.produced = base.produced.clone();
        bad.objects = base.objects.clone();
        bad.declaration.units[1]
            .params
            .insert("actions".into(), serde_json::json!([attempt]));
        let err = bad
            .run_unit(&space, "ferry.route", &format!("undec-{idx}"), sandboxed)
            .unwrap_err();
        assert!(
            err.contains("Dependency"),
            "expected Dependency failure, got: {err}"
        );
        assert!(
            !bad.produced
                .contains_key(&("ferry.route".into(), "route".into()))
        );
    }

    // Missing required source file or missing selector node fails precisely in A2 validation.
    let mut missing_src = PipelineFixture::new("src");
    missing_src.snapshot.remove("src/harbours.json");
    let err = validate(
        &missing_src.declaration,
        &pipeline_registry(),
        &missing_src.snapshot,
        &["Content".into()],
    )
    .unwrap_err()
    .to_string();
    assert!(err.contains("src/harbours.json"), "{err}");

    let mut missing_sel = PipelineFixture::new("src");
    if let Input::Content {
        source: ContentSource::File { selector, .. },
        ..
    } = &mut missing_sel.declaration.units[1].inputs[0]
    {
        *selector = Some("/harbours/nonexistent".into());
    }
    let err = validate(
        &missing_sel.declaration,
        &pipeline_registry(),
        &missing_sel.snapshot,
        &["Content".into()],
    )
    .unwrap_err()
    .to_string();
    assert!(err.contains("/harbours/nonexistent"), "{err}");

    // Missing upstream item object in the store fails in C1b staging before launching the worker, leaving no job folder.
    let mut missing_obj = PipelineFixture::new("src");
    missing_obj.produced = base.produced.clone();
    // Leave missing_obj.objects empty so cloning kit fails.
    let err = missing_obj
        .run_unit(&space, "ferry.route", "missing-upstream-obj", sandboxed)
        .unwrap_err();
    assert!(err.contains("not in MemoryObjects"), "{err}");
    assert!(!space.path("missing-upstream-obj").exists());
}

#[test]
fn seed_determinism_and_job_alone_versus_sequential_worker_purity() {
    let sandboxed = use_sandbox();
    let space = Workspace::new();

    // 1. Seed determinism: same seed -> identical output; different seed -> different key & output.
    let mut seed_a1 = PipelineFixture::new("src");
    seed_a1
        .run_unit(&space, "ferry.kit", "seed-kit", sandboxed)
        .unwrap();
    let (prep_17_a, out_17_a) = seed_a1
        .run_unit(&space, "ferry.route", "seed-17-a", sandboxed)
        .unwrap();

    let mut seed_a2 = PipelineFixture::new("src");
    seed_a2.produced = seed_a1.produced.clone();
    seed_a2.objects = seed_a1.objects.clone();
    let (prep_17_b, out_17_b) = seed_a2
        .run_unit(&space, "ferry.route", "seed-17-b", sandboxed)
        .unwrap();
    assert_eq!(prep_17_a.key(), prep_17_b.key());
    assert_eq!(out_17_a, out_17_b);

    let mut seed_99 = PipelineFixture::new("src");
    seed_99.produced = seed_a1.produced.clone();
    seed_99.objects = seed_a1.objects.clone();
    seed_99.declaration.units[1]
        .params
        .insert("seed".into(), serde_json::json!(99));
    let (prep_99, out_99) = seed_99
        .run_unit(&space, "ferry.route", "seed-99", sandboxed)
        .unwrap();
    assert_ne!(prep_99.key(), prep_17_a.key());
    assert_ne!(out_99, out_17_a);

    // 2. Job alone in a fresh worker process (out_17_a) vs sequential jobs (A -> B -> A) in one persistent worker loop:
    let job_a1 = stage(
        &prep_17_a,
        &seed_a1.snapshot,
        &seed_a1.objects,
        &space.path("seq-a1"),
        "seq-a1",
    )
    .unwrap();
    let job_b = stage(
        &prep_99,
        &seed_99.snapshot,
        &seed_99.objects,
        &space.path("seq-b"),
        "seq-b",
    )
    .unwrap();
    let job_a2 = stage(
        &prep_17_a,
        &seed_a1.snapshot,
        &seed_a1.objects,
        &space.path("seq-a2"),
        "seq-a2",
    )
    .unwrap();

    let worker = worker_identity(sandboxed);
    let (mut child, pipes) = DirectChild.start(&worker_command(sandboxed)).unwrap();
    let mut channel = Channel::new(
        Session::new(&worker.version),
        pipes.responses,
        pipes.requests,
    );
    channel.handshake().unwrap();

    for staged_job in [&job_a1, &job_b, &job_a2] {
        let finished = channel.run(staged_job.request().clone()).unwrap();
        let outputs = finished.result.expect("sequential job failed");
        collect_outputs(staged_job, &outputs.files).unwrap();
    }
    channel.shutdown().unwrap();
    drop(channel);
    assert!(child.wait().unwrap().success());

    let alone_route = &out_17_a[&("route".into(), "route.json".into())];
    let alone_summary = &out_17_a[&("summary".into(), "summary.json".into())];
    for staged_a in [&job_a1, &job_a2] {
        assert_eq!(
            &fs::read(staged_a.output_dir().join("route.json")).unwrap(),
            alone_route
        );
        assert_eq!(
            &fs::read(staged_a.output_dir().join("summary.json")).unwrap(),
            alone_summary
        );
    }
    assert_eq!(
        &fs::read(job_b.output_dir().join("route.json")).unwrap(),
        &out_99[&("route".into(), "route.json".into())]
    );
}
