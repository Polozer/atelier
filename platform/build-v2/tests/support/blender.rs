//! Shared fixtures for the C2b Blender job tests and the T1b session example: the declared
//! unit, workspaces, a resident loop over the launcher seam, the result-store decision and an
//! independent GLB reader.
#![allow(dead_code)] // each including target uses a different subset

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

pub static SERIAL: AtomicU64 = AtomicU64::new(0);

pub const UNITS: &str = r#"
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
pub const FAKE_OP: &str = r#"
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

pub fn fixture_file(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

pub struct Workspace(pub PathBuf);
impl Workspace {
    pub fn new() -> Self {
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "atelier-v2-blender-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    pub fn path(&self, name: &str) -> PathBuf {
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
pub struct NoObjects;
impl ObjectSource for NoObjects {
    fn clone_object(&self, _: &ObjectDigest, _: &Path) -> Result<(), String> {
        Err("the Blender fixture has no item inputs".into())
    }
}

pub fn registry() -> OpRegistry {
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

pub struct Fixture {
    pub declaration: Declaration,
    pub snapshot: SourceSnapshot,
}

impl Fixture {
    pub fn new(op: &str, params: serde_json::Value) -> Self {
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

    pub fn prepared(&self) -> PreparedUnit {
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
pub struct Loop {
    pub worker: DirectWorker,
    pub channel: Channel<PipeReader, PipeWriter>,
    pub version: String,
}

impl Loop {
    pub fn start(command: &WorkerCommand, expected: &str) -> Result<Self, String> {
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
    pub fn run(&mut self, staged: &StagedJob) -> JobOutcome {
        let finished = self.channel.run(staged.request().clone()).unwrap();
        match finished.result {
            Ok(outputs) => match collect_outputs(staged, &outputs.files) {
                Ok(actual) => JobOutcome::Completed(actual),
                Err(message) => panic!("reported and actual outputs differ: {message}"),
            },
            Err(failure) => JobOutcome::Failed(failure),
        }
    }

    pub fn close(mut self) -> ExitStatus {
        self.channel.shutdown().unwrap();
        drop(self.channel);
        self.worker.wait().unwrap()
    }
}

pub fn stage_job(space: &Workspace, fixture: &Fixture, name: &str) -> StagedJob {
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
pub fn publish(
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
pub fn published(space: &Workspace, fixture: &Fixture) -> bool {
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

pub fn provenance() -> Provenance {
    Provenance {
        checkout: "test".into(),
        branch: "test".into(),
        commit: "test".into(),
        dirty: false,
        built_at: "now".into(),
    }
}

pub fn process() -> ProcessIdentity {
    ProcessIdentity {
        pid: std::process::id(),
        boot: "boot".into(),
        started: "start".into(),
    }
}

pub fn completed_paths(outcome: &JobOutcome) -> Vec<&str> {
    match outcome {
        JobOutcome::Completed(actual) => actual.iter().map(|file| file.path.as_str()).collect(),
        JobOutcome::Failed(failure) => panic!("job failed: {failure:?}"),
    }
}

pub fn failed(outcome: &JobOutcome) -> FailureKind {
    match outcome {
        JobOutcome::Failed(failure) => failure.kind.clone(),
        JobOutcome::Completed(actual) => panic!("job completed with {actual:?}"),
    }
}

pub fn read_outputs(job: &StagedJob) -> (Vec<u8>, Vec<u8>) {
    (
        fs::read(job.output_dir().join("model.glb")).unwrap(),
        fs::read(job.output_dir().join("probe.json")).unwrap(),
    )
}

pub fn python() -> PathBuf {
    std::env::split_paths(&std::env::var_os("PATH").unwrap())
        .map(|directory| directory.join("python3"))
        .find(|path| path.is_file())
        .expect("python3 on PATH runs the stand-in Blender")
}

/// A stand-in `Blender` inside an application bundle, run by an absolute interpreter.
pub fn fake_blender(space: &Workspace) -> PathBuf {
    let binary = space.path("platform/Blender.app/Contents/MacOS/Blender");
    fs::create_dir_all(binary.parent().unwrap()).unwrap();
    let source = fs::read_to_string(fixture_file("fake_blender.py")).unwrap();
    fs::write(&binary, format!("#!{} -sS\n{source}", python().display())).unwrap();
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o755)).unwrap();
    binary
}

pub const UNSANDBOXED_TEST_VERSION: &str = "atelier-blender-job-1+unsandboxed-test";

/// The test-only unsandboxed Blender loop over the stand-in Blender.
pub fn fake_loop(blender: &Path) -> WorkerCommand {
    let mut command = WorkerCommand::python_job_loop(
        python(),
        fixture_file("unsandboxed_blender_loop.py")
            .canonicalize()
            .unwrap(),
    )
    .unwrap();
    command.args.extend([
        "--blender".into(),
        blender.to_str().expect("UTF-8 test path").into(),
    ]);
    command
}

/// Mesh data of a GLB: per material name, each triangle's three (position, glTF UV) corners in
/// 1/1024 units, rotated to start at the smallest corner (winding kept), sorted.
pub type Corner = [i64; 5];

pub fn glb_triangles(bytes: &[u8]) -> (serde_json::Value, BTreeMap<String, Vec<[Corner; 3]>>) {
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

pub fn rotated(corners: [Corner; 3]) -> [Corner; 3] {
    let first = (0..3).min_by_key(|&index| corners[index]).unwrap();
    [0, 1, 2].map(|offset| corners[(first + offset) % 3])
}

/// The frozen fixture's triangles as a GLB must hold them: glTF flips V (v' = 1 - v).
pub fn expected_triangles() -> BTreeMap<String, Vec<[Corner; 3]>> {
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
