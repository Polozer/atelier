//! C2b: the Blender job loop through staging, the launcher seam and the result store.
//!
//! The portable tests run the loop's test-only unsandboxed entry over a stand-in Blender
//! (tests/fixtures/fake_blender.py) that accepts only the job command line the loop must use. The
//! T1b session with the installed Blender is the `t1b_blender_session` example, run once in one
//! admitted session; see the README's C2b section.
#[path = "support/blender.rs"]
mod support;

use atelier_build_v2::launch::*;
use atelier_build_v2::protocol::FailureKind;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use support::*;

#[test]
fn blender_job_loop_command_keeps_explicit_threads_before_the_script() {
    let command = WorkerCommand::blender_job_loop(
        PathBuf::from("/Applications/Blender.app/Contents/MacOS/Blender"),
        PathBuf::from("/checkout/platform/studio/atelier/build_v2/blender_worker.py"),
    )
    .unwrap();
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
fn a_loop_command_converts_to_the_guarded_launcher_command_field_for_field() {
    use atelier_build_v2::guard_adapter;
    use std::ffi::OsString;
    let mut command = WorkerCommand::blender_job_loop(
        PathBuf::from("/Applications/Blender.app/Contents/MacOS/Blender"),
        PathBuf::from("/checkout/build_v2/blender_worker.py"),
    )
    .unwrap();
    command.env.insert("PATH_EXTRA".into(), "a b=c".into());
    command.cwd = PathBuf::from("/private/var/empty");
    let guarded = guard_adapter::WorkerCommand::from(command.clone());
    assert_eq!(guarded.program, command.program);
    assert_eq!(
        guarded.args,
        command.args.iter().map(OsString::from).collect::<Vec<_>>(),
        "every argument, in order"
    );
    let position = |arg: &str| guarded.args.iter().position(|a| a == arg).unwrap();
    assert!(position("--threads") < position("-P"));
    assert_eq!(guarded.args.last().unwrap(), "--");
    assert_eq!(
        guarded.env, command.env,
        "the complete environment, nothing added"
    );
    assert_eq!(guarded.cwd, PathBuf::from("/private/var/empty"));
    let python = WorkerCommand::python_job_loop(
        PathBuf::from("/usr/bin/python3"),
        PathBuf::from("/checkout/build_v2/python_worker.py"),
    )
    .unwrap();
    let guarded = guard_adapter::WorkerCommand::from(python.clone());
    assert_eq!(guarded.args, ["-I", "/checkout/build_v2/python_worker.py"]);
    assert_eq!(
        (guarded.program, guarded.env, guarded.cwd),
        (python.program, python.env, python.cwd)
    );
}

#[test]
fn job_loop_commands_refuse_a_non_utf8_script_path_instead_of_replacing_it() {
    use std::os::unix::ffi::OsStringExt;
    let script = PathBuf::from(std::ffi::OsString::from_vec(
        b"/checkout/build_v2/worker\xff.py".to_vec(),
    ));
    let program = PathBuf::from("/usr/bin/worker");
    for refusal in [
        WorkerCommand::python_job_loop(program.clone(), script.clone()).unwrap_err(),
        WorkerCommand::blender_job_loop(program.clone(), script.clone()).unwrap_err(),
    ] {
        assert_eq!(refusal.kind(), std::io::ErrorKind::InvalidInput);
        assert!(refusal.to_string().contains("not UTF-8"), "{refusal}");
    }
    // The same path in UTF-8 is kept byte for byte.
    let script = PathBuf::from("/checkout/build_v2/worker\u{e9}.py");
    let command = WorkerCommand::python_job_loop(program, script).unwrap();
    assert_eq!(command.args, ["-I", "/checkout/build_v2/worker\u{e9}.py"]);
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
            "failed:",
        ),
        (
            serde_json::json!([
                "import os\nos.symlink('/etc/hosts', context.output_dir / 'link.glb')"
            ]),
            false,
            Some(FailureKind::Dependency),
            "failed:",
        ),
        // Completed, then refused by the result store: an undeclared extra file, a missing one.
        (
            serde_json::json!(["(context.output_dir / 'stray.bin').write_bytes(b'x')"]),
            false,
            None,
            "unknown actual output path",
        ),
        (
            serde_json::json!([]),
            true,
            None,
            "missing output probe.json",
        ),
    ];
    for (index, (attempts, skip_probe, kind, reason)) in cases.into_iter().enumerate() {
        let fixture = Fixture::new(
            FAKE_OP,
            serde_json::json!({"seed": 7, "name": "a", "attempts": attempts, "skip_probe": skip_probe}),
        );
        let outcome = session.run(&stage_job(&space, &fixture, &format!("bad-{index}")));
        match kind {
            Some(kind) => assert_eq!(failed(&outcome), kind, "case {index}"),
            None => assert_ne!(completed_paths(&outcome), ["model.glb", "probe.json"]),
        }
        // Path membership is refused before anything is frozen, on every platform. A missing
        // file is found while freezing, so elsewhere the APFS-only clone refuses first.
        let reason = if cfg!(target_os = "macos") || !reason.starts_with("missing") {
            reason
        } else {
            "requires macOS"
        };
        let refusal = publish(&space, &fixture, outcome).unwrap_err();
        assert!(refusal.contains(reason), "case {index}: {refusal}");
        assert!(!published(&space, &fixture), "case {index} published");
    }
    let good = Fixture::new(FAKE_OP, serde_json::json!({"seed": 7, "name": "a"}));
    let outcome = session.run(&stage_job(&space, &good, "good"));
    assert_eq!(completed_paths(&outcome), ["model.glb", "probe.json"]);
    let published_files = publish(&space, &good, outcome);
    if cfg!(target_os = "macos") {
        assert_eq!(published_files.unwrap(), ["model.glb", "probe.json"]);
        assert!(published(&space, &good));
    } else {
        // B2 freezes outputs by APFS clone only; elsewhere publication refuses, and says why.
        assert!(published_files.unwrap_err().contains("requires macOS"));
    }
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
