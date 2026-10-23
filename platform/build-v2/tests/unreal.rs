//! T0 tests of the Unreal worker's controller side: context identity and validation, the scratch
//! project and its hash receipt, the worker command line and the two evidence files. No Unreal.
use atelier_build_v2::unreal::*;
use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

static SERIAL: AtomicU64 = AtomicU64::new(0);

struct Workspace(PathBuf);
impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "atelier-v2-unreal-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).unwrap();
        Self(path.canonicalize().unwrap())
    }
    fn path(&self, relative: &str) -> PathBuf {
        self.0.join(relative)
    }
    fn write(&self, relative: &str, bytes: &[u8]) -> PathBuf {
        let path = self.path(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, bytes).unwrap();
        path
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        // Unlock anything a test left read-only, then remove it.
        let _ = std::process::Command::new("chmod")
            .args(["-R", "u+w"])
            .arg(&self.0)
            .status();
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// A restored editor compile and the worker plugin, as produced folders.
fn produced(space: &Workspace) -> (PathBuf, PathBuf) {
    space.write(
        "editor/Binaries/Mac/UnrealEditor-AtelierImport.dylib",
        b"module bytes",
    );
    space.write(
        "editor/Binaries/Mac/UnrealEditor.modules",
        b"{\"BuildId\": \"b1\"}",
    );
    space.write(
        "plugins/AtelierBuildWorker/AtelierBuildWorker.uplugin",
        b"{\"Modules\": []}",
    );
    space.write(
        "plugins/AtelierBuildWorker/Binaries/Mac/UnrealEditor-AtelierBuildWorker.dylib",
        b"plugin bytes",
    );
    // Sources and intermediates beside the binaries are never cloned.
    space.write("plugins/AtelierBuildWorker/Source/Worker.cpp", b"// source");
    (
        space.path("editor/Binaries/Mac"),
        space.path("plugins/AtelierBuildWorker"),
    )
}

fn context(space: &Workspace) -> UnrealContext {
    let (editor, plugin) = produced(space);
    UnrealContext {
        engine_root: space.path("engine"),
        build_id: "5.8-build".into(),
        editor: Binaries {
            identity: tree_identity(&editor, None).unwrap(),
            dir: editor,
        },
        modules: vec![Module {
            name: "AtelierImport".into(),
            kind: "UncookedOnly".into(),
            loading_phase: "Default".into(),
        }],
        engine_plugins: vec!["PythonScriptPlugin".into(), "Interchange".into()],
        plugins: vec![Plugin {
            name: WORKER_PLUGIN.into(),
            identity: tree_identity(&plugin, Some(WORKER_PLUGIN)).unwrap(),
            dir: plugin,
        }],
        settings: vec!["-ForceDPCVars=r.GenerateMeshDistanceFields=0".into()],
    }
}

#[test]
fn the_profile_ignores_locations_and_follows_every_identity_field() {
    let space = Workspace::new();
    let base = context(&space);
    let mut moved = base.clone();
    moved.engine_root = PathBuf::from("/elsewhere/UE_5.8");
    moved.editor.dir = PathBuf::from("/restored/elsewhere");
    assert_eq!(
        moved.profile(),
        base.profile(),
        "locations are not identity"
    );
    let mut reordered = base.clone();
    reordered.engine_plugins.reverse();
    assert_eq!(
        reordered.profile(),
        base.profile(),
        "engine plugins are a set"
    );

    let mut changes: Vec<UnrealContext> = vec![];
    let mut change = |edit: &dyn Fn(&mut UnrealContext)| {
        let mut changed = base.clone();
        edit(&mut changed);
        changes.push(changed);
    };
    change(&|c| c.build_id = "5.8-other".into());
    change(&|c| c.editor.identity = "1".repeat(64));
    change(&|c| c.modules[0].loading_phase = "PostEngineInit".into());
    change(&|c| c.engine_plugins.push("Paper2D".into()));
    change(&|c| c.plugins[0].identity = "2".repeat(64));
    change(&|c| c.settings.push("-ini:Engine:[Core.Log]:Global=Log".into()));
    let mut profiles: BTreeSet<String> = changes.iter().map(UnrealContext::profile).collect();
    profiles.insert(base.profile());
    assert_eq!(profiles.len(), 7, "every identity field separates sessions");
    assert!(base.profile().starts_with("unreal-"));
}

#[test]
fn contexts_refuse_what_a_session_cannot_load_honestly() {
    let space = Workspace::new();
    let base = context(&space);
    base.validate().unwrap();
    let refused = |edit: &dyn Fn(&mut UnrealContext), why: &str| {
        let mut changed = base.clone();
        edit(&mut changed);
        let error = changed.validate().unwrap_err();
        assert!(error.to_string().contains(why), "{why}: {error}");
    };
    refused(
        &|c| c.engine_root = PathBuf::from("relative/UE"),
        "absolute",
    );
    refused(
        &|c| c.engine_root = PathBuf::from("/opt/Epic Games/UE"),
        "whitespace",
    );
    refused(&|c| c.build_id.clear(), "BuildId");
    refused(&|c| c.editor.identity = "not-a-digest".into(), "sha256");
    refused(&|c| c.modules.clear(), "at least one");
    refused(&|c| c.modules.push(c.modules[0].clone()), "twice");
    refused(&|c| c.plugins.clear(), WORKER_PLUGIN);
    refused(&|c| c.engine_plugins.push(WORKER_PLUGIN.into()), "repeated");
    refused(
        &|c| c.settings.push("-ExecCmds=quit".into()),
        "not a declared",
    );
    refused(
        &|c| c.settings.push("-ini:Engine:[A]:B=has space".into()),
        "not a declared",
    );
}

#[test]
fn a_tree_identity_names_paths_and_bytes_and_refuses_links() {
    let space = Workspace::new();
    let (editor, plugin) = produced(&space);
    let first = tree_identity(&editor, None).unwrap();
    assert_eq!(first, tree_identity(&editor, None).unwrap());
    fs::write(
        editor.join("UnrealEditor-AtelierImport.dylib"),
        b"other bytes",
    )
    .unwrap();
    let second = tree_identity(&editor, None).unwrap();
    assert_ne!(first, second);
    fs::rename(
        editor.join("UnrealEditor-AtelierImport.dylib"),
        editor.join("UnrealEditor-Renamed.dylib"),
    )
    .unwrap();
    assert_ne!(
        second,
        tree_identity(&editor, None).unwrap(),
        "paths are named"
    );
    // A plugin identity covers its descriptor and binaries, never its sources.
    let with_source = tree_identity(&plugin, Some(WORKER_PLUGIN)).unwrap();
    fs::write(plugin.join("Source/Worker.cpp"), b"// changed").unwrap();
    assert_eq!(
        with_source,
        tree_identity(&plugin, Some(WORKER_PLUGIN)).unwrap()
    );
    std::os::unix::fs::symlink("/etc/hosts", editor.join("link.dylib")).unwrap();
    assert!(tree_identity(&editor, None).is_err());
}

#[cfg(target_os = "macos")] // the scratch project needs APFS clones
#[test]
fn the_command_line_runs_the_worker_script_on_the_scratch_project_with_declared_settings() {
    let space = Workspace::new();
    let context = context(&space);
    let session = space.path("session");
    fs::create_dir(&session).unwrap();
    let scratch = ScratchProject::prepare(&session, &context).unwrap();
    let script = PathBuf::from("/checkout/platform/studio/atelier/build_v2/unreal_worker.py");
    let command = job_loop_command(&context, &scratch, &script).unwrap();
    assert_eq!(
        command.program,
        space.path("engine/Engine/Binaries/Mac/UnrealEditor-Cmd")
    );
    let mut expected = vec![
        scratch.uproject().to_str().unwrap().to_string(),
        "-run=pythonscript".into(),
        format!("-script={}", script.display()),
    ];
    expected.extend(UNREAL_WORKER_FLAGS.iter().map(|flag| flag.to_string()));
    expected.push(format!("-UserDir={}", scratch.user_dir().display()));
    expected.push("-ForceDPCVars=r.GenerateMeshDistanceFields=0".into());
    assert_eq!(command.args, expected);
    assert_eq!(
        command.env.keys().collect::<Vec<_>>(),
        ["LC_ALL", "TZ"],
        "nothing inherited"
    );
    assert!(
        job_loop_command(
            &context,
            &scratch,
            std::path::Path::new("/with space/worker.py")
        )
        .is_err()
    );
    let mut other = context.clone();
    other.build_id = "5.8-other".into();
    let error = job_loop_command(&other, &scratch, &script).unwrap_err();
    assert!(error.to_string().contains("another context"), "{error}");
}

#[test]
fn a_scratch_project_clones_only_declared_binaries_read_only_and_checks_their_identity() {
    let space = Workspace::new();
    let context = context(&space);
    let session = space.path("session");
    fs::create_dir(&session).unwrap();
    let scratch = match ScratchProject::prepare(&session, &context) {
        Ok(scratch) => scratch,
        Err(error) => {
            assert!(!cfg!(target_os = "macos"), "{error}");
            assert!(error.to_string().contains("requires macOS"), "{error}");
            return;
        }
    };
    let root = scratch.root().to_path_buf();
    assert_eq!(
        scratch.receipt().files.keys().cloned().collect::<Vec<_>>(),
        [
            "Binaries/Mac/UnrealEditor-AtelierImport.dylib",
            "Binaries/Mac/UnrealEditor.modules",
            "Plugins/AtelierBuildWorker/AtelierBuildWorker.uplugin",
            "Plugins/AtelierBuildWorker/Binaries/Mac/UnrealEditor-AtelierBuildWorker.dylib",
        ]
    );
    assert!(
        !root.join("Plugins/AtelierBuildWorker/Source").exists(),
        "no sources"
    );
    for folder in ["Content", "Config", "Saved", "Intermediate"] {
        assert_eq!(
            fs::read_dir(root.join(folder)).unwrap().count(),
            0,
            "{folder} starts empty"
        );
    }
    let descriptor: serde_json::Value =
        serde_json::from_slice(&fs::read(scratch.uproject()).unwrap()).unwrap();
    assert_eq!(descriptor["Modules"][0]["Name"], "AtelierImport");
    assert_eq!(descriptor["Modules"].as_array().unwrap().len(), 1);
    let plugins: Vec<_> = descriptor["Plugins"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p["Name"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(
        plugins,
        ["AtelierBuildWorker", "Interchange", "PythonScriptPlugin"]
    );
    assert!(
        descriptor.get("AdditionalPluginDirectories").is_none(),
        "no checkout plugins"
    );
    let expected = scratch.expected();
    assert_eq!(expected.worker_version, UNREAL_JOB_LOOP_VERSION);
    assert_eq!(expected.profile, context.profile());
    assert_eq!(
        expected.libraries.len(),
        2,
        "both libraries, by their cloned bytes"
    );

    // Read-only clones: an editor that wants to rebuild a module fails, by design.
    let library = root.join("Binaries/Mac/UnrealEditor-AtelierImport.dylib");
    assert!(fs::write(&library, b"rebuilt").is_err());
    assert!(fs::write(root.join("Binaries/Mac/UnrealEditor-New.dylib"), b"new").is_err());
    scratch.verify().unwrap();

    // A changed source after the clone is caught.
    fs::write(
        context.editor.dir.join("UnrealEditor.modules"),
        b"{\"BuildId\": \"b2\"}",
    )
    .unwrap();
    let error = scratch.verify().unwrap_err();
    assert!(
        error.to_string().contains("changed after it was cloned"),
        "{error}"
    );
    scratch.remove().unwrap();
    assert!(!root.exists());
    assert!(
        session.join(RECEIPT_FILE).exists(),
        "the receipt outlives the project"
    );

    // A declared identity that the bytes do not match refuses the session.
    let session = space.path("session-2");
    fs::create_dir(&session).unwrap();
    let error = ScratchProject::prepare(&session, &context).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("does not hold the declared binaries"),
        "{error}"
    );
}

#[cfg(target_os = "macos")] // the scratch project needs APFS clones
#[test]
fn context_and_import_evidence_are_required_well_formed_and_exact() {
    let space = Workspace::new();
    let context = context(&space);
    let session = space.path("session");
    fs::create_dir(&session).unwrap();
    let scratch = ScratchProject::prepare(&session, &context).unwrap();
    let report = session.join(CONTEXT_REPORT);
    assert!(
        scratch.verify_context_report().is_err(),
        "missing evidence is refused"
    );
    fs::write(&report, b"{\"version\": 1}").unwrap();
    assert!(
        scratch.verify_context_report().is_err(),
        "malformed evidence is refused"
    );
    let mut loaded = scratch.expected().clone();
    loaded.modules.insert("UndeclaredModule".into());
    let write = |loaded: &LoadedContext| {
        let value = ContextReport {
            version: EVIDENCE_VERSION,
            loaded: loaded.clone(),
        };
        fs::write(&report, serde_json::to_vec(&value).unwrap()).unwrap();
    };
    write(&loaded);
    let error = scratch.verify_context_report().unwrap_err();
    assert!(
        error.to_string().contains("different native context"),
        "{error}"
    );
    write(scratch.expected());
    assert_eq!(
        scratch.verify_context_report().unwrap().loaded,
        *scratch.expected()
    );

    let job = space.path("job");
    fs::create_dir_all(job.join("output")).unwrap();
    let declared = BTreeSet::from(["/Game/Meshes/Rock".to_string()]);
    assert!(
        read_import_evidence(&job, &declared).is_err(),
        "missing evidence is refused"
    );
    let evidence = |packages: &[&str]| {
        let value = ImportEvidence {
            version: EVIDENCE_VERSION,
            packages: packages
                .iter()
                .map(|package| PackageImports {
                    package: package.to_string(),
                    imports: vec![("/Script/Engine".into(), "Package".into())],
                })
                .collect(),
        };
        fs::create_dir_all(job.join("evidence")).unwrap();
        fs::write(
            job.join(IMPORT_EVIDENCE),
            serde_json::to_vec(&value).unwrap(),
        )
        .unwrap();
    };
    evidence(&["/Game/Meshes/Other"]);
    assert!(
        read_import_evidence(&job, &declared).is_err(),
        "undeclared package"
    );
    evidence(&[]);
    assert!(
        read_import_evidence(&job, &declared).is_err(),
        "omitted package"
    );
    evidence(&["/Game/Meshes/Rock"]);
    let read = read_import_evidence(&job, &declared).unwrap();
    assert_eq!(read.packages[0].imports[0].1, "Package");
    assert_eq!(
        fs::read_dir(job.join("output")).unwrap().count(),
        0,
        "outside output/"
    );
}

// ---- The worker over the real protocol ----
// macOS only: the scratch project needs APFS clones.
#[cfg(target_os = "macos")]
mod editor_session {
    use super::*;

    use atelier_build_v2::launch::{DirectChild, DirectWorker, LaunchedWorker, StartWorker};
    use atelier_build_v2::protocol::{FailureKind, JobRequest};
    use atelier_build_v2::worker_session::{Channel, Session};
    use std::io::{PipeReader, PipeWriter};
    use std::os::unix::fs::PermissionsExt;
    use std::path::Path;

    const OP: &str = r#"
import unreal
fake = unreal.AtelierFake

def run(context):
    p = context.params
    for name, payload in p.get('create', []):
        fake.create_package(name, payload.encode(), imports=[['/Script/Engine', 'StaticMesh']])
        fake.save_package(name)
    if 'derive' in p:
        source, target = p['derive']
        fake.create_package(target, fake.load_package(context.packages[source]) + b'!')
        fake.save_package(target)
    for name in p.get('keep', []):
        fake.keep_alive(name)
    for name in p.get('dirty', []):
        fake.dirty(name)
    if 'cvar' in p:
        fake.set_cvar(p['cvar'], '1')
    if 'stray' in p:
        fake.write_file(p['stray'], b'x')
    if 'raise' in p:
        raise ValueError(p['raise'])
"#;

    fn python() -> PathBuf {
        std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|directory| directory.join("python3"))
            .find(|path| path.is_file())
            .expect("python3 on PATH runs the stand-in editor")
    }

    /// A stand-in engine at `engine/` whose editor is `fake_unreal.py`, reporting `build_id`.
    fn fake_engine(space: &Workspace, build_id: &str) {
        let fixture = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fake_unreal.py");
        let source = fs::read_to_string(fixture).unwrap();
        let editor = space.write(
            "engine/Engine/Binaries/Mac/UnrealEditor-Cmd",
            format!("#!{} -sS\n{source}", python().display()).as_bytes(),
        );
        fs::set_permissions(&editor, fs::Permissions::from_mode(0o755)).unwrap();
        space.write(
            "engine/Engine/Build/Build.version",
            format!("{{\"BuildId\": \"{build_id}\"}}").as_bytes(),
        );
    }

    fn worker_script() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../studio/atelier/build_v2/unreal_worker.py")
            .canonicalize()
            .unwrap()
    }

    struct Editor {
        process: DirectWorker,
        channel: Channel<PipeReader, PipeWriter>,
        scratch: ScratchProject,
    }

    /// A prepared session on the stand-in editor.
    fn editor(space: &Workspace, context: &UnrealContext) -> Editor {
        let session = space.path("session");
        fs::create_dir_all(&session).unwrap();
        let scratch = ScratchProject::prepare(&session, context).unwrap();
        let command = job_loop_command(context, &scratch, &worker_script()).unwrap();
        let (process, pipes) = DirectChild.start(&command).unwrap();
        let channel = Channel::new(
            Session::new(UNREAL_JOB_LOOP_VERSION),
            pipes.responses,
            pipes.requests,
        );
        Editor {
            process,
            channel,
            scratch,
        }
    }

    /// A staged job folder: the op as declared code, input packages under `in/content/Game/`.
    fn job(
        space: &Workspace,
        name: &str,
        params: serde_json::Value,
        outputs: &[&str],
        inputs: &[(&str, &[u8])],
    ) -> JobRequest {
        let dir = space.path(&format!("jobs/{name}"));
        fs::create_dir_all(dir.join("output")).unwrap();
        space.write(&format!("jobs/{name}/ops/op.py"), OP.as_bytes());
        let mut staged = vec![];
        for (logical, bytes) in inputs {
            let path = format!("in/content/Game/{logical}.uasset");
            space.write(&format!("jobs/{name}/{path}"), bytes);
            staged.push(serde_json::json!({"name": logical, "path": path,
            "identity": {"state": "digest", "digest": "0".repeat(64)}}));
        }
        serde_json::from_value(serde_json::json!({
        "job_id": name, "unit": format!("unit.{name}"), "op": {"kind": "unreal_fixture", "version": "1"},
        "job_dir": dir.to_str().unwrap(), "script": "ops/op.py", "code": ["ops/op.py"],
        "inputs": staged, "params": params,
        "outputs": outputs.iter().map(|path| serde_json::json!({"path": path, "required": true})).collect::<Vec<_>>(),
    }))
    .unwrap()
    }

    fn output(job: &JobRequest, relative: &str) -> Vec<u8> {
        fs::read(Path::new(&job.job_dir).join("output").join(relative)).unwrap()
    }

    fn empty(path: &Path) -> bool {
        fs::read_dir(path).unwrap().next().is_none()
    }

    #[test]
    fn one_editor_serves_jobs_in_order_with_a_clean_game_folder_between_them() {
        let space = Workspace::new();
        fake_engine(&space, "5.8-build");
        let context = context(&space);
        let mut editor = editor(&space, &context);
        assert_eq!(editor.channel.handshake().unwrap(), UNREAL_JOB_LOOP_VERSION);
        let report = editor.scratch.verify_context_report().unwrap();
        assert_eq!(report.loaded.build_id, "5.8-build");
        assert!(
            !report.loaded.plugins.contains("ContentBrowserData"),
            "engine defaults are platform"
        );

        let rock = |name: &str, payload: &str| {
            job(
                &space,
                name,
                serde_json::json!({"create": [["/Game/Meshes/Rock", payload]]}),
                &["content/Game/Meshes/Rock.uasset"],
                &[],
            )
        };
        let mut bytes = vec![];
        for (name, payload) in [("a-1", "rock"), ("b", "other"), ("a-2", "rock")] {
            let request = rock(name, payload);
            let finished = editor.channel.run(request.clone()).unwrap();
            assert_eq!(
                finished.result.unwrap().files,
                ["content/Game/Meshes/Rock.uasset"]
            );
            bytes.push(output(&request, "content/Game/Meshes/Rock.uasset"));
            assert!(
                empty(&editor.scratch.content()),
                "/Game is empty after {name}"
            );
            let declared = BTreeSet::from(["/Game/Meshes/Rock".to_string()]);
            let evidence = read_import_evidence(Path::new(&request.job_dir), &declared).unwrap();
            assert_eq!(
                evidence.packages[0].imports,
                [("/Script/Engine".into(), "StaticMesh".into())]
            );
        }
        assert_eq!(bytes[0], bytes[2], "A, then B, then A gives the same A");
        assert_ne!(bytes[0], bytes[1]);

        // A staged input package sits read-only at its logical path, and is gone afterwards.
        let derived = job(
            &space,
            "derive",
            serde_json::json!({"derive": ["Source", "/Game/Meshes/Derived"]}),
            &["content/Game/Meshes/Derived.uasset"],
            &[("Source", b"source-bytes")],
        );
        assert!(editor.channel.run(derived.clone()).unwrap().result.is_ok());
        assert_eq!(
            output(&derived, "content/Game/Meshes/Derived.uasset"),
            b"source-bytes!"
        );
        assert!(empty(&editor.scratch.content()));

        editor.channel.shutdown().unwrap();
        assert!(editor.process.wait().unwrap().success());
        editor.scratch.verify().unwrap();
    }

    #[test]
    fn undeclared_saves_files_dirty_packages_and_op_errors_fail_and_the_next_job_runs() {
        let space = Workspace::new();
        fake_engine(&space, "5.8-build");
        let context = context(&space);
        let mut editor = editor(&space, &context);
        editor.channel.handshake().unwrap();
        let declared = ["content/Game/A.uasset"];
        let cases = [
            (
                serde_json::json!({"create": [["/Game/A", "a"], ["/Game/Extra", "x"]]}),
                FailureKind::Dependency,
                "undeclared packages",
            ),
            (
                serde_json::json!({"create": [["/Game/A", "a"]], "stray": "Stray.bin"}),
                FailureKind::Dependency,
                "undeclared file",
            ),
            (
                serde_json::json!({"create": [["/Game/A", "a"]], "dirty": ["/Game/A"]}),
                FailureKind::Job,
                "unsaved changes",
            ),
            (serde_json::json!({}), FailureKind::Job, "did not save"),
            (
                serde_json::json!({"raise": "bad mesh"}),
                FailureKind::Job,
                "bad mesh",
            ),
        ];
        for (index, (params, kind, reason)) in cases.into_iter().enumerate() {
            let request = job(&space, &format!("bad-{index}"), params, &declared, &[]);
            let failure = editor
                .channel
                .run(request.clone())
                .unwrap()
                .result
                .unwrap_err();
            assert_eq!(failure.kind, kind, "case {index}: {}", failure.message);
            assert!(
                failure.message.contains(reason),
                "case {index}: {}",
                failure.message
            );
            assert!(
                empty(&Path::new(&request.job_dir).join("output")),
                "case {index} left outputs"
            );
            assert!(
                empty(&editor.scratch.content()),
                "case {index} left /Game files"
            );
        }
        let good = job(
            &space,
            "good",
            serde_json::json!({"create": [["/Game/A", "a"]]}),
            &declared,
            &[],
        );
        assert!(
            editor.channel.run(good).unwrap().result.is_ok(),
            "the same editor runs the next job"
        );
        editor.channel.shutdown().unwrap();
        assert!(editor.process.wait().unwrap().success());
    }

    #[test]
    fn a_package_left_loaded_or_a_changed_setting_retires_the_editor_after_its_reply() {
        for (name, extra) in [
            ("keep", serde_json::json!({"keep": ["/Game/A"]})),
            ("cvar", serde_json::json!({"cvar": "r.Test"})),
        ] {
            let space = Workspace::new();
            fake_engine(&space, "5.8-build");
            let context = context(&space);
            let mut editor = editor(&space, &context);
            editor.channel.handshake().unwrap();
            let mut params = serde_json::json!({"create": [["/Game/A", "a"]]});
            params
                .as_object_mut()
                .unwrap()
                .extend(extra.as_object().unwrap().clone());
            let request = job(&space, name, params, &["content/Game/A.uasset"], &[]);
            let finished = editor.channel.run(request).unwrap();
            assert!(finished.result.is_ok(), "{name}: the job itself completed");
            // The editor exits instead of serving another job: the session ends, it is not reused.
            let ended = format!("{:?}", editor.channel.next_event().unwrap_err());
            assert!(
                ended.contains("end of stream in state Idle"),
                "{name}: {ended}"
            );
            assert!(
                editor.process.wait().unwrap().success(),
                "{name}: a clean exit"
            );
        }
    }

    #[test]
    fn a_different_native_context_or_a_module_rebuild_never_says_hello() {
        // The installed engine is not the one the session declared: the worker reports it and stops.
        let space = Workspace::new();
        fake_engine(&space, "5.8-other");
        let mut other = editor(&space, &context(&space));
        assert!(other.channel.handshake().is_err());
        assert!(!other.process.wait().unwrap().success());
        let error = other.scratch.verify_context_report().unwrap_err();
        assert!(
            error.to_string().contains("different native context"),
            "{error}"
        );

        // A library the editor wants to rebuild cannot be: the clone is read-only.
        let space = Workspace::new();
        fake_engine(&space, "5.8-build");
        let mut stale = context(&space);
        let library = stale.editor.dir.join("UnrealEditor-AtelierImport.dylib");
        fs::write(&library, b"stale").unwrap();
        stale.editor.identity = tree_identity(&stale.editor.dir, None).unwrap();
        let mut rebuilding = editor(&space, &stale);
        assert!(rebuilding.channel.handshake().is_err());
        assert!(!rebuilding.process.wait().unwrap().success());
        rebuilding.scratch.verify().unwrap();
        assert_eq!(
            fs::read(
                rebuilding
                    .scratch
                    .root()
                    .join("Binaries/Mac/UnrealEditor-AtelierImport.dylib")
            )
            .unwrap(),
            b"stale"
        );
    }
}
