//! C2b: the Blender job loop through staging, the launcher seam and the result store.
//!
//! The portable tests run the loop's test-only unsandboxed entry over a stand-in Blender
//! (tests/fixtures/fake_blender.py) that accepts only the job command line the loop must use. The
//! ignored `t1b_blender_session` runs the production entry inside the installed Blender, once, in
//! one admitted session; see the README's C2b section.
use atelier_build_v2::launch::*;
use atelier_build_v2::leases::ProcessIdentity;
use atelier_build_v2::protocol::FailureKind;
use atelier_build_v2::results::ResultStore;
use atelier_build_v2::staging::*;
use atelier_build_v2::store::ObjectDigest;
use atelier_build_v2::worker_session::{Channel, Session};
use atelier_build_v2::{keys::*, schema::*, source_hashes::*, validate::*};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{PipeReader, PipeWriter};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::ExitStatus;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

static SERIAL: AtomicU64 = AtomicU64::new(0);

const UNITS: &str = r#"
schema_version = 1
cache_version = "v2-1"

[[units]]
id = "demo.model"
op = { kind = "blender_model", version = "1" }
script = "ops/model.py"
code = ["ops/model.py"]
params = { seed = 7, name = "a" }
inputs = [
  { role = "content", name = "mesh", source = { kind = "file", path = "assets/pyramid.json", selector = "/pyramid" } },
]
outputs = [
  { id = "model", logical_path = "/Game/Demo/Model", class = "StaticMeshSource", files = [{ path = "model.glb", install_path = "Content/Demo/model.glb" }, { path = "probe.json", install_path = "Content/Demo/probe.json" }], destination = "checkout" },
]
"#;

/// The portable op: what a stand-in Blender can run. It leaves state in `bpy` and `sys.modules`
/// that a reused process would carry into the next job.
const FAKE_OP: &str = r#"
import bpy, json, random, sys

def run(context):
    seen = [getattr(bpy, 'left_behind', None), sorted(name for name in sys.modules if name.startswith('left_'))]
    bpy.left_behind = context.params['name']
    sys.modules['left_' + context.params['name']] = sys
    data = context.input('mesh').read_bytes()
    context.output('model.glb').write_bytes(data + json.dumps([context.params['name'], seen, random.random()]).encode())
    for attempt in context.params.get('attempts', []):
        exec(attempt)
    if not context.params.get('skip_probe'):
        context.output('probe.json').write_text(json.dumps({'resets': bpy.factory_resets, 'hash': hash('atelier-t1b'),
                                                            'inputs': {name: str(path) for name, path in context.inputs.items()}, 'seed': context.seed}))
"#;

fn fixture_file(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

struct Workspace(PathBuf);
impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "atelier-v2-blender-{}-{}",
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
        for entry in fs::read_dir(&self.0).unwrap() {
            let path = entry.unwrap().path();
            if path.join("output").is_dir() {
                remove_job(&path).unwrap();
            }
        }
        fs::remove_dir_all(&self.0).unwrap();
    }
}

/// This unit has no item inputs, so staging never clones an object.
struct NoObjects;
impl ObjectSource for NoObjects {
    fn clone_object(&self, _: &ObjectDigest, _: &Path) -> Result<(), String> {
        Err("the Blender fixture has no item inputs".into())
    }
}

fn registry() -> OpRegistry {
    let param = |kind| ParamRule {
        kind,
        required: false,
    };
    BTreeMap::from([(
        ("blender_model".into(), "1".into()),
        OpDefinition {
            inputs: BTreeMap::from([(
                "mesh".into(),
                InputRule {
                    role: InputRole::Content,
                    required: true,
                    allow_absent_file: false,
                    allow_selector: true,
                    require_whole_reason: false,
                    item_classes: BTreeSet::new(),
                },
            )]),
            output_classes: BTreeSet::from(["StaticMeshSource".into()]),
            params: BTreeMap::from([
                ("seed".into(), param(ParamKind::Integer)),
                ("name".into(), param(ParamKind::String)),
                ("attempts".into(), param(ParamKind::Array)),
                ("skip_probe".into(), param(ParamKind::Bool)),
            ]),
        },
    )])
}

struct Fixture {
    declaration: Declaration,
    snapshot: SourceSnapshot,
}

impl Fixture {
    fn new(op: &str, params: serde_json::Value) -> Self {
        let mut declaration = parse_declaration(UNITS).unwrap();
        declaration.units[0].params = serde_json::from_value(params).unwrap();
        let snapshot = BTreeMap::from([
            (
                "ops/model.py".into(),
                SnapshotEntry::File(op.as_bytes().to_vec()),
            ),
            (
                "assets/pyramid.json".into(),
                SnapshotEntry::File(fs::read(fixture_file("t1b/pyramid.json")).unwrap()),
            ),
        ]);
        Self {
            declaration,
            snapshot,
        }
    }

    fn prepared(&self) -> PreparedUnit {
        let validated = validate(
            &self.declaration,
            &registry(),
            &self.snapshot,
            &["Content".into()],
        )
        .unwrap();
        let identity = |version: &str| ImplementationIdentity {
            version: version.into(),
            digest: sha256(version.as_bytes()),
        };
        prepare(
            &self.declaration,
            &validated,
            "demo.model",
            &KeyContext {
                snapshot: &self.snapshot,
                versions: &BTreeMap::new(),
                produced: &BTreeMap::new(),
                produced_groups: &BTreeMap::new(),
                staged_inputs: &BTreeMap::from([("mesh".into(), "in/mesh.json".into())]),
                worker: &identity(BLENDER_JOB_LOOP_VERSION),
                validator: &identity("validator-1"),
            },
            &mut SourceHashCache::default(),
        )
        .unwrap()
    }
}

/// One started job loop serving many jobs: the resident shape a batch session drives.
struct Loop {
    worker: DirectWorker,
    channel: Channel<PipeReader, PipeWriter>,
    version: String,
}

impl Loop {
    fn start(command: &WorkerCommand, expected: &str) -> Result<Self, String> {
        let (mut worker, pipes) = DirectChild
            .start(command)
            .map_err(|error| error.to_string())?;
        let mut channel = Channel::new(Session::new(expected), pipes.responses, pipes.requests);
        match channel.handshake() {
            Ok(version) => Ok(Self {
                worker,
                channel,
                version,
            }),
            Err(error) => {
                drop(channel);
                let _ = worker.stop();
                Err(error.to_string())
            }
        }
    }

    /// One staged job to its outcome, exactly as `run_staged` decides it.
    fn run(&mut self, staged: &StagedJob) -> JobOutcome {
        let finished = self.channel.run(staged.request().clone()).unwrap();
        match finished.result {
            Ok(outputs) => match collect_outputs(staged, &outputs.files) {
                Ok(actual) => JobOutcome::Completed(actual),
                Err(message) => panic!("reported and actual outputs differ: {message}"),
            },
            Err(failure) => JobOutcome::Failed(failure),
        }
    }

    fn close(mut self) -> ExitStatus {
        self.channel.shutdown().unwrap();
        drop(self.channel);
        self.worker.wait().unwrap()
    }
}

fn stage_job(space: &Workspace, fixture: &Fixture, name: &str) -> StagedJob {
    stage(
        &fixture.prepared(),
        &fixture.snapshot,
        &NoObjects,
        &space.path(name),
        name,
    )
    .unwrap()
}

/// The B2 result store's decision on one outcome: publish a complete declared set or refuse.
fn publish(
    space: &Workspace,
    fixture: &Fixture,
    outcome: JobOutcome,
) -> Result<Vec<String>, String> {
    let prepared = fixture.prepared();
    let results = ResultStore::open(space.path("store")).unwrap();
    let transaction = results
        .begin(&prepared, provenance(), process(), vec![], BTreeSet::new())
        .unwrap();
    let actual = match outcome {
        JobOutcome::Completed(actual) => actual,
        JobOutcome::Failed(failure) => return Err(format!("failed: {failure:?}")),
    };
    let staged = transaction
        .stage_groups(actual, |_| Ok(()), |_, _, _| Ok(()))
        .map_err(|error| error.to_string())?;
    let envelope = staged
        .publish(|_| Ok(()))
        .map_err(|error| error.to_string())?;
    Ok(envelope
        .result
        .outputs
        .iter()
        .flat_map(|item| item.files.iter().map(|file| file.path.clone()))
        .collect())
}

/// Whether the result store holds a published result for this fixture's key.
fn published(space: &Workspace, fixture: &Fixture) -> bool {
    let results = ResultStore::open(space.path("store")).unwrap();
    let mut transaction = results
        .begin(
            &fixture.prepared(),
            provenance(),
            process(),
            vec![],
            BTreeSet::new(),
        )
        .unwrap();
    transaction.lookup().unwrap().is_some()
}

fn provenance() -> Provenance {
    Provenance {
        checkout: "test".into(),
        branch: "test".into(),
        commit: "test".into(),
        dirty: false,
        built_at: "now".into(),
    }
}

fn process() -> ProcessIdentity {
    ProcessIdentity {
        pid: std::process::id(),
        boot: "boot".into(),
        started: "start".into(),
    }
}

fn completed_paths(outcome: &JobOutcome) -> Vec<&str> {
    match outcome {
        JobOutcome::Completed(actual) => actual.iter().map(|file| file.path.as_str()).collect(),
        JobOutcome::Failed(failure) => panic!("job failed: {failure:?}"),
    }
}

fn failed(outcome: &JobOutcome) -> FailureKind {
    match outcome {
        JobOutcome::Failed(failure) => failure.kind.clone(),
        JobOutcome::Completed(actual) => panic!("job completed with {actual:?}"),
    }
}

fn read_outputs(job: &StagedJob) -> (Vec<u8>, Vec<u8>) {
    (
        fs::read(job.output_dir().join("model.glb")).unwrap(),
        fs::read(job.output_dir().join("probe.json")).unwrap(),
    )
}

fn python() -> PathBuf {
    std::env::split_paths(&std::env::var_os("PATH").unwrap())
        .map(|directory| directory.join("python3"))
        .find(|path| path.is_file())
        .expect("python3 on PATH runs the stand-in Blender")
}

/// A stand-in `Blender` inside an application bundle, run by an absolute interpreter.
fn fake_blender(space: &Workspace) -> PathBuf {
    let binary = space.path("platform/Blender.app/Contents/MacOS/Blender");
    fs::create_dir_all(binary.parent().unwrap()).unwrap();
    let source = fs::read_to_string(fixture_file("fake_blender.py")).unwrap();
    fs::write(&binary, format!("#!{}\n{source}", python().display())).unwrap();
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o755)).unwrap();
    binary
}

const UNSANDBOXED_TEST_VERSION: &str = "atelier-blender-job-1+unsandboxed-test";

/// The test-only unsandboxed Blender loop over the stand-in Blender.
fn fake_loop(blender: &Path) -> WorkerCommand {
    let mut command = WorkerCommand::python_job_loop(
        python(),
        fixture_file("unsandboxed_blender_loop.py")
            .canonicalize()
            .unwrap(),
    );
    command
        .args
        .extend(["--blender".into(), blender.to_string_lossy().into_owned()]);
    command
}

#[test]
fn blender_job_loop_command_keeps_explicit_threads_before_the_script() {
    let command = WorkerCommand::blender_job_loop(
        PathBuf::from("/Applications/Blender.app/Contents/MacOS/Blender"),
        PathBuf::from("/checkout/platform/studio/atelier/build_v2/blender_worker.py"),
    );
    assert_eq!(
        command.args,
        [
            "--factory-startup",
            "-b",
            "--threads",
            "3",
            "--python-exit-code",
            "1",
            "--disable-autoexec",
            "-P",
            "/checkout/platform/studio/atelier/build_v2/blender_worker.py",
            "--",
        ]
    );
    // Admission reads the thread count only before the script, from a program named Blender.
    let threads = command
        .args
        .iter()
        .position(|arg| arg == "--threads")
        .unwrap();
    assert!(threads < command.args.iter().position(|arg| arg == "-P").unwrap());
    assert_eq!(command.args.last().unwrap(), "--");
    assert_eq!(
        command.env.keys().collect::<Vec<_>>(),
        ["LC_ALL", "TZ"],
        "nothing else is inherited"
    );
    assert_ne!(BLENDER_JOB_LOOP_VERSION, PYTHON_JOB_LOOP_VERSION);
}

#[test]
fn an_unsandboxed_blender_loop_never_passes_a_production_keyed_handshake() {
    let space = Workspace::new();
    let fixture = Fixture::new(FAKE_OP, serde_json::json!({"seed": 7, "name": "a"}));
    assert_eq!(
        fixture.prepared().ingredients().worker_version,
        BLENDER_JOB_LOOP_VERSION
    );
    let job = stage_job(&space, &fixture, "job");
    let error = run_staged(
        &DirectChild,
        &fake_loop(&fake_blender(&space)),
        BLENDER_JOB_LOOP_VERSION,
        &job,
    )
    .unwrap_err();
    assert!(error.contains(UNSANDBOXED_TEST_VERSION), "{error}");
    assert!(fs::read_dir(job.output_dir()).unwrap().next().is_none());
}

#[test]
fn blender_jobs_give_equal_bytes_in_any_order_and_in_a_fresh_loop() {
    let space = Workspace::new();
    let blender = fake_blender(&space);
    let a = Fixture::new(FAKE_OP, serde_json::json!({"seed": 7, "name": "a"}));
    let b = Fixture::new(FAKE_OP, serde_json::json!({"seed": 7, "name": "b"}));
    let mut session = Loop::start(&fake_loop(&blender), UNSANDBOXED_TEST_VERSION).unwrap();
    let mut produced = BTreeMap::new();
    for (name, fixture) in [
        ("alone", &a),
        ("b-first", &b),
        ("b-then-a", &a),
        ("a-first", &a),
        ("a-then-b", &b),
        ("a-b-a", &a),
    ] {
        let job = stage_job(&space, fixture, name);
        assert_eq!(
            completed_paths(&session.run(&job)),
            ["model.glb", "probe.json"]
        );
        produced.insert(name, read_outputs(&job));
    }
    assert!(session.close().success());
    let mut fresh = Loop::start(&fake_loop(&blender), UNSANDBOXED_TEST_VERSION).unwrap();
    let job = stage_job(&space, &a, "fresh");
    assert_eq!(
        completed_paths(&fresh.run(&job)),
        ["model.glb", "probe.json"]
    );
    assert!(fresh.close().success());
    let fresh = read_outputs(&job);
    assert_eq!(produced["alone"], fresh);
    assert_eq!(produced["b-then-a"], fresh);
    assert_eq!(produced["a-b-a"], fresh);
    assert_eq!(produced["b-first"], produced["a-then-b"]);
    assert_ne!(produced["b-first"].0, fresh.0);
    let model = String::from_utf8(fresh.0).unwrap();
    // Exactly the selected bytes reached the job, and nothing the previous job left behind.
    assert!(model.contains(r#""materials":["Stone","Wood"]"#), "{model}");
    assert!(!model.contains("unselected"), "{model}");
    assert!(model.contains(r#"["a", [null, []], "#), "{model}");
    let probe: serde_json::Value = serde_json::from_slice(&fresh.1).unwrap();
    assert_eq!(probe["resets"], serde_json::json!([true]));
    assert_eq!(probe["inputs"], serde_json::json!({"mesh": "in/mesh.json"}));
}

#[test]
fn blender_job_seed_and_params_alone_change_the_bytes() {
    let space = Workspace::new();
    let mut session =
        Loop::start(&fake_loop(&fake_blender(&space)), UNSANDBOXED_TEST_VERSION).unwrap();
    let mut bytes = vec![];
    for (index, params) in [
        serde_json::json!({"seed": 7, "name": "a"}),
        serde_json::json!({"seed": 7, "name": "a"}),
        serde_json::json!({"seed": 8, "name": "a"}),
        serde_json::json!({"seed": 7, "name": "c"}),
    ]
    .into_iter()
    .enumerate()
    {
        let job = stage_job(
            &space,
            &Fixture::new(FAKE_OP, params),
            &format!("job-{index}"),
        );
        assert_eq!(completed_paths(&session.run(&job)).len(), 2);
        bytes.push(read_outputs(&job));
    }
    assert!(session.close().success());
    assert_eq!(bytes[0], bytes[1]);
    assert_eq!(BTreeSet::from_iter(&bytes[1..]).len(), 3);
}

#[test]
fn failed_or_incomplete_blender_jobs_publish_nothing_and_the_next_job_publishes() {
    let space = Workspace::new();
    let mut session =
        Loop::start(&fake_loop(&fake_blender(&space)), UNSANDBOXED_TEST_VERSION).unwrap();
    let cases = [
        (
            serde_json::json!(["raise ValueError('bad mesh')"]),
            false,
            Some(FailureKind::Job),
        ),
        (
            serde_json::json!([
                "import os\nos.symlink('/etc/hosts', context.output_dir / 'link.glb')"
            ]),
            false,
            Some(FailureKind::Dependency),
        ),
        // Completed, then refused by the result store: an undeclared extra file, a missing one.
        (
            serde_json::json!(["(context.output_dir / 'stray.bin').write_bytes(b'x')"]),
            false,
            None,
        ),
        (serde_json::json!([]), true, None),
    ];
    for (index, (attempts, skip_probe, kind)) in cases.into_iter().enumerate() {
        let fixture = Fixture::new(
            FAKE_OP,
            serde_json::json!({"seed": 7, "name": "a", "attempts": attempts, "skip_probe": skip_probe}),
        );
        let outcome = session.run(&stage_job(&space, &fixture, &format!("bad-{index}")));
        match kind {
            Some(kind) => assert_eq!(failed(&outcome), kind, "case {index}"),
            None => assert_ne!(completed_paths(&outcome), ["model.glb", "probe.json"]),
        }
        let refusal = publish(&space, &fixture, outcome).unwrap_err();
        assert!(!refusal.is_empty());
        assert!(!published(&space, &fixture), "case {index} published");
    }
    let good = Fixture::new(FAKE_OP, serde_json::json!({"seed": 7, "name": "a"}));
    let outcome = session.run(&stage_job(&space, &good, "good"));
    assert_eq!(
        publish(&space, &good, outcome).unwrap(),
        ["model.glb", "probe.json"]
    );
    assert!(published(&space, &good));
    assert!(session.close().success());
}

#[test]
fn a_missing_blender_fails_the_job_and_leaves_the_loop_stoppable() {
    let space = Workspace::new();
    let missing = space.path("absent/Blender.app/Contents/MacOS/Blender");
    let fixture = Fixture::new(FAKE_OP, serde_json::json!({"seed": 7, "name": "a"}));
    let job = stage_job(&space, &fixture, "job");
    let outcome = run_staged(
        &DirectChild,
        &fake_loop(&missing),
        UNSANDBOXED_TEST_VERSION,
        &job,
    )
    .unwrap();
    assert_eq!(failed(&outcome), FailureKind::Dependency);
    assert!(fs::read_dir(job.output_dir()).unwrap().next().is_none());
}

/// Mesh data of a GLB: per material name, each triangle's three (position, glTF UV) corners in
/// 1/1024 units, rotated to start at the smallest corner (winding kept), sorted.
type Corner = [i64; 5];

fn glb_triangles(bytes: &[u8]) -> (serde_json::Value, BTreeMap<String, Vec<[Corner; 3]>>) {
    let word = |at: usize| u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap()) as usize;
    assert_eq!(&bytes[0..4], b"glTF");
    assert_eq!(word(4), 2);
    assert_eq!(word(8), bytes.len());
    let json_length = word(12);
    assert_eq!(&bytes[16..20], b"JSON");
    let document: serde_json::Value = serde_json::from_slice(&bytes[20..20 + json_length]).unwrap();
    let bin_at = 20 + json_length;
    assert_eq!(&bytes[bin_at + 4..bin_at + 8], b"BIN\0");
    let bin = &bytes[bin_at + 8..bin_at + 8 + word(bin_at)];
    let accessor = |index: &serde_json::Value| -> Vec<Vec<f64>> {
        let accessor = &document["accessors"][index.as_u64().unwrap() as usize];
        let view = &document["bufferViews"][accessor["bufferView"].as_u64().unwrap() as usize];
        let width = match accessor["type"].as_str().unwrap() {
            "SCALAR" => 1,
            "VEC2" => 2,
            "VEC3" => 3,
            other => panic!("unexpected accessor type {other}"),
        };
        let (size, read): (usize, fn(&[u8]) -> f64) =
            match accessor["componentType"].as_u64().unwrap() {
                5126 => (4, |b| f32::from_le_bytes(b.try_into().unwrap()) as f64),
                5125 => (4, |b| u32::from_le_bytes(b.try_into().unwrap()) as f64),
                5123 => (2, |b| u16::from_le_bytes(b.try_into().unwrap()) as f64),
                5121 => (1, |b| b[0] as f64),
                other => panic!("unexpected component type {other}"),
            };
        let stride = view["byteStride"]
            .as_u64()
            .map_or(size * width, |stride| stride as usize);
        let start = view["byteOffset"].as_u64().unwrap_or(0) as usize
            + accessor["byteOffset"].as_u64().unwrap_or(0) as usize;
        (0..accessor["count"].as_u64().unwrap() as usize)
            .map(|element| {
                (0..width)
                    .map(|component| {
                        let at = start + element * stride + component * size;
                        read(&bin[at..at + size])
                    })
                    .collect()
            })
            .collect()
    };
    let mut triangles: BTreeMap<String, Vec<[Corner; 3]>> = BTreeMap::new();
    for mesh in document["meshes"].as_array().unwrap() {
        for primitive in mesh["primitives"].as_array().unwrap() {
            assert_eq!(primitive["mode"].as_u64().unwrap_or(4), 4, "triangles only");
            let material = document["materials"][primitive["material"].as_u64().unwrap() as usize]
                ["name"]
                .as_str()
                .unwrap()
                .to_string();
            let positions = accessor(&primitive["attributes"]["POSITION"]);
            let uvs = accessor(&primitive["attributes"]["TEXCOORD_0"]);
            let indices: Vec<usize> = match primitive.get("indices") {
                Some(index) => accessor(index)
                    .into_iter()
                    .map(|value| value[0] as usize)
                    .collect(),
                None => (0..positions.len()).collect(),
            };
            for triangle in indices.chunks(3) {
                let corners: [Corner; 3] = std::array::from_fn(|corner| {
                    let vertex = triangle[corner];
                    let [x, y, z] = positions[vertex][..] else {
                        panic!()
                    };
                    let [u, v] = uvs[vertex][..] else { panic!() };
                    [x, y, z, u, v].map(|value| (value * 1024.0).round() as i64)
                });
                triangles
                    .entry(material.clone())
                    .or_default()
                    .push(rotated(corners));
            }
        }
    }
    for list in triangles.values_mut() {
        list.sort();
    }
    (document, triangles)
}

fn rotated(corners: [Corner; 3]) -> [Corner; 3] {
    let first = (0..3).min_by_key(|&index| corners[index]).unwrap();
    [0, 1, 2].map(|offset| corners[(first + offset) % 3])
}

/// The frozen fixture's triangles as a GLB must hold them: glTF flips V (v' = 1 - v).
fn expected_triangles() -> BTreeMap<String, Vec<[Corner; 3]>> {
    let source: serde_json::Value =
        serde_json::from_slice(&fs::read(fixture_file("t1b/pyramid.json")).unwrap()).unwrap();
    let pyramid = &source["pyramid"];
    let mut triangles: BTreeMap<String, Vec<[Corner; 3]>> = BTreeMap::new();
    for face in pyramid["faces"].as_array().unwrap() {
        let corners: [Corner; 3] = std::array::from_fn(|index| {
            let position = &pyramid["positions"][face["corners"][index].as_u64().unwrap() as usize];
            let uv = &face["uvs"][index];
            let value = |value: &serde_json::Value| value.as_f64().unwrap();
            [
                value(&position[0]),
                value(&position[1]),
                value(&position[2]),
                value(&uv[0]),
                1.0 - value(&uv[1]),
            ]
            .map(|value| (value * 1024.0).round() as i64)
        });
        let material = pyramid["materials"][face["material"].as_u64().unwrap() as usize]
            .as_str()
            .unwrap()
            .to_string();
        triangles
            .entry(material)
            .or_default()
            .push(rotated(corners));
    }
    for list in triangles.values_mut() {
        list.sort();
    }
    triangles
}

#[test]
fn glb_reader_matches_a_hand_built_file() {
    // A one-triangle GLB built here: the fidelity check itself is tested before it judges Blender.
    let positions: [f32; 9] = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.5];
    let uvs: [f32; 6] = [0.0, 1.0, 1.0, 1.0, 0.0, 0.5];
    let mut bin: Vec<u8> = positions
        .iter()
        .chain(&uvs)
        .flat_map(|value| value.to_le_bytes())
        .collect();
    bin.extend([0u16, 1, 2, 0].iter().flat_map(|value| value.to_le_bytes()));
    let json = serde_json::json!({
        "asset": {"version": "2.0"},
        "materials": [{"name": "Stone"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2, "material": 0}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 0, "byteOffset": 36, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "bufferViews": [{"buffer": 0, "byteLength": 60}, {"buffer": 0, "byteOffset": 60, "byteLength": 6}],
    });
    let mut json = serde_json::to_vec(&json).unwrap();
    json.resize(json.len().div_ceil(4) * 4, b' ');
    let mut glb = b"glTF".to_vec();
    glb.extend(2u32.to_le_bytes());
    glb.extend(((12 + 8 + json.len() + 8 + bin.len()) as u32).to_le_bytes());
    glb.extend((json.len() as u32).to_le_bytes());
    glb.extend(b"JSON");
    glb.extend(&json);
    glb.extend((bin.len() as u32).to_le_bytes());
    glb.extend(b"BIN\0");
    glb.extend(&bin);
    let (_, triangles) = glb_triangles(&glb);
    let scaled = |values: [f64; 5]| values.map(|value| (value * 1024.0) as i64);
    assert_eq!(
        triangles,
        BTreeMap::from([(
            "Stone".to_string(),
            vec![[
                scaled([0.0, 0.0, 0.0, 0.0, 1.0]),
                scaled([1.0, 0.0, 0.0, 1.0, 1.0]),
                scaled([0.0, 1.0, 0.5, 0.0, 0.5]),
            ]]
        )])
    );
    let expected = expected_triangles();
    assert_eq!(expected["Stone"].len(), 4);
    assert_eq!(expected["Wood"].len(), 2);
}

/// T1b: the production Blender job loop inside the installed Blender, run once in one admitted
/// session. `ATELIER_T1B_BLENDER` names the Blender binary; `ATELIER_T1B_EVIDENCE`, when set, is
/// where the session writes its evidence record.
#[cfg(target_os = "macos")]
#[test]
#[ignore = "T1b: installed Blender, one admitted session"]
fn t1b_blender_session() {
    let blender = PathBuf::from(std::env::var("ATELIER_T1B_BLENDER").expect("ATELIER_T1B_BLENDER"));
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../studio/atelier/build_v2/blender_worker.py")
        .canonicalize()
        .unwrap();
    let command = WorkerCommand::blender_job_loop(blender.clone(), script);
    let op = fs::read_to_string(fixture_file("t1b/pyramid_op.py")).unwrap();
    let space = Workspace::new();
    let secret = space.path("outside/secret.txt");
    fs::create_dir(space.path("outside")).unwrap();
    fs::write(&secret, b"not an input").unwrap();
    fs::write(space.path("outside/outside_mod.py"), b"VALUE = 1\n").unwrap();
    let missing = space.path("outside/never-created.png");
    let session_started = Instant::now();
    let mut runs: Vec<serde_json::Value> = vec![];
    let mut record = |name: &str, elapsed: Duration, outcome: &JobOutcome| {
        let files: BTreeMap<String, String> = match outcome {
            JobOutcome::Completed(actual) => actual
                .iter()
                .map(|file| (file.path.clone(), sha256(&fs::read(&file.source).unwrap())))
                .collect(),
            JobOutcome::Failed(_) => BTreeMap::new(),
        };
        let failure = match outcome {
            JobOutcome::Failed(failure) => {
                serde_json::json!({"kind": format!("{:?}", failure.kind),
                                                              "message": failure.message})
            }
            JobOutcome::Completed(_) => serde_json::Value::Null,
        };
        runs.push(
            serde_json::json!({"job": name, "ms": elapsed.as_millis() as u64, "files": files,
                                     "failure": failure}),
        );
    };
    let fixture = |params: serde_json::Value| Fixture::new(&op, params);
    let a = fixture(serde_json::json!({"seed": 7, "name": "a"}));
    let b = fixture(serde_json::json!({"seed": 7, "name": "b"}));

    let started = Instant::now();
    let mut session = Loop::start(&command, BLENDER_JOB_LOOP_VERSION).unwrap();
    let loop_start_ms = started.elapsed().as_millis() as u64;
    let worker_version = session.version.clone();
    let mut run = |session: &mut Loop, fixture: &Fixture, name: &str| {
        let job = stage_job(&space, fixture, name);
        let started = Instant::now();
        let outcome = session.run(&job);
        record(name, started.elapsed(), &outcome);
        (outcome, job)
    };

    // Order independence and a fresh process: the same export bytes every time.
    let mut produced = BTreeMap::new();
    for (name, fixture) in [
        ("alone", &a),
        ("b-first", &b),
        ("b-then-a", &a),
        ("a-first", &a),
        ("a-then-b", &b),
        ("a-b-a", &a),
    ] {
        let (outcome, job) = run(&mut session, fixture, name);
        assert_eq!(
            completed_paths(&outcome),
            ["model.glb", "probe.json"],
            "{name}"
        );
        produced.insert(name, read_outputs(&job));
    }
    // Seed determinism: same seed same bytes (above), another seed other bytes.
    let (outcome, seed_job) = run(
        &mut session,
        &fixture(serde_json::json!({"seed": 8, "name": "a"})),
        "seed-8",
    );
    assert_eq!(completed_paths(&outcome).len(), 2);
    let seed_8 = read_outputs(&seed_job);

    // Failures publish nothing, and the next job behaves.
    let attempts = |attempts: serde_json::Value| {
        fixture(serde_json::json!({"seed": 7, "name": "a", "attempts": attempts}))
    };
    let failure = attempts(serde_json::json!(["raise ValueError('t1b failure')"]));
    let (outcome, _) = run(&mut session, &failure, "raises");
    assert_eq!(failed(&outcome), FailureKind::Job);
    assert!(publish(&space, &failure, outcome).is_err());
    let (outcome, after_failure) = run(&mut session, &a, "after-failure");
    assert_eq!(completed_paths(&outcome).len(), 2);
    let after_failure = read_outputs(&after_failure);
    let mut refusals = BTreeMap::new();
    for (name, fixture) in [
        (
            "extra",
            attempts(serde_json::json!([
                "(context.output_dir / 'stray.bin').write_bytes(b'x')"
            ])),
        ),
        (
            "missing",
            fixture(serde_json::json!({"seed": 7, "name": "a", "skip_probe": true})),
        ),
        (
            "link",
            attempts(serde_json::json!([
                "os.symlink('/etc/hosts', context.output_dir / 'link.glb')"
            ])),
        ),
    ] {
        let (outcome, _) = run(&mut session, &fixture, name);
        let refusal = publish(&space, &fixture, outcome).unwrap_err();
        assert!(!published(&space, &fixture), "{name} published");
        refusals.insert(name, refusal);
    }

    // Undeclared access: each attempt is its own job and must fail as a dependency failure.
    let mut denials = BTreeMap::new();
    for (name, attempt) in [
        ("read-existing", format!("open({:?}).read()", secret)),
        ("check-missing", format!("os.path.exists({:?})", missing)),
        (
            "list-folder",
            format!("os.listdir({:?})", space.path("outside")),
        ),
        (
            "code-load",
            format!(
                "sys.path.insert(0, {:?})\nimport outside_mod",
                space.path("outside")
            ),
        ),
        (
            "network",
            "socket.create_connection(('127.0.0.1', 9), timeout=2)".to_string(),
        ),
        (
            "native-read-existing",
            format!("bpy.data.images.load({:?})", secret),
        ),
    ] {
        let (outcome, _) = run(&mut session, &attempts(serde_json::json!([attempt])), name);
        assert_eq!(failed(&outcome), FailureKind::Dependency, "{name}");
        denials.insert(name, "dependency");
    }
    // The documented gap: a native (C) probe of a missing undeclared path is not intercepted.
    let gap = attempts(serde_json::json!([format!(
        "try:\n    bpy.data.images.load({:?})\nexcept RuntimeError:\n    pass",
        missing
    )]));
    let (outcome, _) = run(&mut session, &gap, "native-check-missing");
    let native_missing = match &outcome {
        JobOutcome::Completed(_) => "not intercepted (documented gap)".to_string(),
        JobOutcome::Failed(failure) => format!("{:?}: {}", failure.kind, failure.message),
    };

    // A good job publishes, then the loop stops cleanly.
    let (outcome, _) = run(&mut session, &a, "publish");
    assert_eq!(
        publish(&space, &a, outcome).unwrap(),
        ["model.glb", "probe.json"]
    );
    let loop_status = session.close();
    assert!(loop_status.success(), "{loop_status}");

    // A fresh loop process gives the same bytes.
    let mut fresh = Loop::start(&command, BLENDER_JOB_LOOP_VERSION).unwrap();
    let (outcome, fresh_job) = run(&mut fresh, &a, "fresh-process");
    assert_eq!(completed_paths(&outcome).len(), 2);
    let fresh_outputs = read_outputs(&fresh_job);
    assert!(fresh.close().success());

    // Export bytes: equal in every order and process; the probe too except, if Blender's Python
    // ignores the declared hash seed, its `hash` field.
    let probe = |bytes: &[u8]| -> serde_json::Value { serde_json::from_slice(bytes).unwrap() };
    let without_hash = |bytes: &[u8]| {
        let mut value = probe(bytes);
        value.as_object_mut().unwrap().remove("hash");
        value
    };
    for name in ["alone", "b-then-a", "a-first", "a-b-a"] {
        assert_eq!(produced[name].0, fresh_outputs.0, "{name} export bytes");
        assert_eq!(
            without_hash(&produced[name].1),
            without_hash(&fresh_outputs.1),
            "{name} probe"
        );
    }
    assert_eq!(after_failure.0, fresh_outputs.0);
    assert_eq!(produced["b-first"].0, produced["a-then-b"].0);
    assert_ne!(produced["b-first"].0, fresh_outputs.0);
    assert_ne!(seed_8.0, fresh_outputs.0, "another seed moves the object");
    let hashes: BTreeSet<_> = produced
        .values()
        .chain([&fresh_outputs, &after_failure])
        .map(|outputs| probe(&outputs.1)["hash"].to_string())
        .collect();

    // Exactly the selected payload, params, seed and declared code reached the job.
    let seen = probe(&fresh_outputs.1);
    let selected = serde_json::to_vec(
        &serde_json::from_slice::<serde_json::Value>(
            &fs::read(fixture_file("t1b/pyramid.json")).unwrap(),
        )
        .unwrap()["pyramid"],
    )
    .unwrap();
    assert_eq!(seen["inputs"], serde_json::json!({"mesh": "in/mesh.json"}));
    assert_eq!(seen["params"], serde_json::json!({"seed": 7, "name": "a"}));
    assert_eq!(seen["seed"], 7);
    assert_eq!(seen["listing"], serde_json::json!(["in", "ops", "output"]));
    assert_eq!(
        seen["job_modules"],
        serde_json::json!(["atelier_job_entry"])
    );
    assert_eq!(
        seen["factory_scene_before"],
        serde_json::json!([[], [], []])
    );

    // Corner, UV and material fidelity of the export.
    let (document, triangles) = glb_triangles(&fresh_outputs.0);
    assert_eq!(triangles, expected_triangles());
    assert_eq!(document["nodes"].as_array().unwrap().len(), 1);
    assert_eq!(document["nodes"][0]["name"], "a");

    let evidence = serde_json::json!({
        "worker_version": worker_version,
        "blender": {"binary": blender, "version": seen["blender"], "build_hash": seen["build_hash"],
                    "addons": seen["addons"]},
        "loop_start_ms": loop_start_ms,
        "session_ms": session_started.elapsed().as_millis() as u64,
        "job_runs": runs.len(),
        "loop_processes": 2,
        "export_sha256": sha256(&fresh_outputs.0),
        "probe_sha256": sha256(&fresh_outputs.1),
        "seed_8_export_sha256": sha256(&seed_8.0),
        "selected_sha256": seen["selected_sha256"],
        "hash_seed": {"env": seen["hash_seed"], "hash_randomization": seen["hash_randomization"],
                      "distinct_hash_values": hashes.len()},
        "refusals": refusals,
        "denials": denials,
        "native_missing_check": native_missing,
        "loop_exit": loop_status.to_string(),
        "runs": runs,
        "selected_bytes_len": selected.len(),
    });
    if let Ok(path) = std::env::var("ATELIER_T1B_EVIDENCE") {
        fs::write(path, serde_json::to_vec_pretty(&evidence).unwrap()).unwrap();
    }
    println!("{}", serde_json::to_string_pretty(&evidence).unwrap());
}
