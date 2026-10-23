mod support;

use std::collections::{BTreeMap, BTreeSet};
use support::adapter::{AdapterFault, BuildAdapter, FakeAdapter};
use support::check::{HarnessError, ProofStatus, Report, Scenario, Step, run_scenario};
use support::random;
use support::snapshot::{FileOrigin, FrozenFile, FrozenSnapshot};
use support::spec::{HarnessConfig, InputSpec, OutputSpec, Plan, StoreHealth, Target, UnitSpec};
use support::work::{
    MemberFile, ProducedItem, ProducedItems, output_payloads, resolve_input, unit_identity,
};

fn correct() -> Box<dyn BuildAdapter> {
    Box::new(FakeAdapter::new())
}

fn run(scenario: &Scenario) -> Result<Report, HarnessError> {
    run_scenario(scenario, correct, correct)
}

fn faulty(fault: AdapterFault) -> impl FnMut() -> Box<dyn BuildAdapter> {
    move || Box::new(FakeAdapter::with_fault(fault))
}

fn chain_units() -> Vec<UnitSpec> {
    vec![
        UnitSpec::new("data")
            .file_input("source", "data/source.bin")
            .output(OutputSpec::new("out", "/Game/Data/Out").file("out/data.bin")),
        UnitSpec::new("refpkg")
            .file_input("source", "data/ref.bin")
            .output(OutputSpec::new("out", "/Game/Ref/Out").file("out/ref.bin")),
        UnitSpec::new("mid")
            .item_input("data", "data", "out")
            .reference_from("ref", "/Game/Ref/Out", "Asset", "refpkg", "out")
            .output(OutputSpec::new("out", "/Game/Mid/Out").file("out/mid.bin")),
        UnitSpec::new("final")
            .item_input("mid", "mid", "out")
            .output(OutputSpec::new("out", "/Game/Final/Out").file("out/final.bin")),
    ]
}

fn chain_snapshot() -> FrozenSnapshot {
    FrozenSnapshot::builder()
        .file("data/source.bin", vec![1, 2, 3])
        .file("data/ref.bin", vec![4, 5, 6])
        .build()
}

fn chain_target() -> Vec<Target> {
    vec![Target::Unit("final".into())]
}

#[test]
fn snapshot_owns_binary_untracked_ignored_and_absent_inputs() {
    let snapshot = FrozenSnapshot::builder()
        .file("data/binary.bin", vec![0, 255, 0, 1])
        .untracked("scratch/upload.bin", vec![1])
        .ignored("build/generated.bin", vec![2])
        .executable("tools/run", vec![3])
        .file("data/empty.bin", Vec::new())
        .build();

    assert_eq!(
        snapshot.get("data/binary.bin").unwrap().bytes,
        vec![0, 255, 0, 1]
    );
    assert_eq!(
        snapshot.get("scratch/upload.bin").unwrap().origin,
        FileOrigin::Untracked
    );
    assert_eq!(
        snapshot.get("build/generated.bin").unwrap().origin,
        FileOrigin::Ignored
    );
    assert_eq!(snapshot.get("tools/run").unwrap().mode, 0o755);
    assert!(snapshot.get("missing.bin").is_none());
    assert_eq!(snapshot.len(), 5);
    assert!(snapshot.get("data/empty.bin").is_some());
    assert!(snapshot.get("data/empty.bin").unwrap().bytes.is_empty());

    let next = snapshot.with_file("data/binary.bin", vec![9]);
    assert_eq!(
        snapshot.get("data/binary.bin").unwrap().bytes,
        vec![0, 255, 0, 1]
    );
    assert!(next.contains("data/binary.bin"));
    assert!(!next.without("data/binary.bin").contains("data/binary.bin"));

    assert_eq!(FrozenFile::new(vec![0]).with_mode(0o700).mode, 0o755);
    assert_eq!(FrozenFile::new(vec![0]).with_mode(0o600).mode, 0o644);
}

#[test]
fn hand_written_model_and_adapter_agree_and_clean_rebuild_matches_targets() {
    let units = chain_units();
    let snapshot = chain_snapshot();
    let plan = Plan::all(&units);
    let target = chain_target();
    let mut steps = vec![
        Step::new(
            "initial",
            units.clone(),
            snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["data", "refpkg", "mid", "final"]),
    ];

    let reference_snapshot = snapshot.with_file("data/ref.bin", vec![9, 9, 9]);
    steps.push(
        Step::new(
            "reference bytes change",
            units.clone(),
            reference_snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["refpkg"]),
    );

    let mut coded = units.clone();
    coded[0].code = "code-2".into();
    steps.push(
        Step::new(
            "code change with identical output",
            coded.clone(),
            reference_snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["data"]),
    );

    let content_snapshot = reference_snapshot.with_file("data/source.bin", vec![7, 7]);
    steps.push(
        Step::new(
            "content change reruns downstream",
            coded.clone(),
            content_snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["data", "mid", "final"]),
    );

    steps.push(
        Step::new(
            "store failure keeps no saves",
            coded.clone(),
            content_snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .store(StoreHealth::Failing)
        .expect_runs(["data", "refpkg", "mid", "final"]),
    );

    steps.push(
        Step::new(
            "store recovery restores hits",
            coded.clone(),
            content_snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(Vec::<String>::new()),
    );

    let scenario = Scenario::new("chain", steps);
    let report = run(&scenario).expect("the chain scenario matches its model");
    assert_eq!(report.builds.len(), 6);
    assert_eq!(report.status(), ProofStatus::Pending);
    assert!(!report.is_pass());
    assert!(!report.pending.is_empty());

    for build in &report.builds {
        let step = &scenario.steps[build.step];
        if let Some(handwritten) = &step.expected_runs {
            let model: BTreeSet<_> = build.expectation.runs.iter().cloned().collect();
            let actual: BTreeSet<_> = build.actual.runs.iter().cloned().collect();
            assert_eq!(handwritten, &model);
            assert_eq!(handwritten, &actual);
        }
    }

    let first = &report.builds[0];
    assert_eq!(
        first.actual.requested.keys().cloned().collect::<Vec<_>>(),
        vec![("final".to_string(), "out".to_string())]
    );
    assert_eq!(first.actual.outputs.len(), 4);
    assert_eq!(report.builds[1].actual.runs, vec!["refpkg".to_string()]);
    assert_eq!(report.builds[2].actual.runs, vec!["data".to_string()]);
}

#[test]
fn absent_and_empty_optional_inputs_are_distinct() {
    let units = vec![
        UnitSpec::new("opt")
            .optional_file_input("maybe", "data/opt.bin")
            .output(OutputSpec::new("out", "/Game/Opt").file("out/opt.bin")),
    ];
    let plan = Plan::all(&units);
    let target = vec![Target::Unit("opt".into())];
    let absent = FrozenSnapshot::builder().build();
    let empty = absent.with_file("data/opt.bin", Vec::new());
    let nonempty = absent.with_file("data/opt.bin", vec![1]);
    let steps = vec![
        Step::new(
            "absent",
            units.clone(),
            absent.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["opt"]),
        Step::new(
            "present empty",
            units.clone(),
            empty.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["opt"]),
        Step::new(
            "absent again",
            units.clone(),
            absent.clone(),
            plan.clone(),
            vec![Target::All],
        )
        .expect_runs(["opt"]),
        Step::new(
            "present nonempty",
            units.clone(),
            nonempty,
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["opt"]),
    ];
    let report = run(&Scenario::new("optional", steps)).expect("optional identity is modeled");
    assert_eq!(report.builds.len(), 4);
    assert_eq!(report.builds[2].actual.roots, vec!["opt".to_string()]);
}

#[test]
fn plan_add_and_remove_changes_selection_and_removal_intent() {
    let units = vec![
        UnitSpec::new("base")
            .file_input("data", "data/base.bin")
            .output(OutputSpec::new("out", "/Game/Base").file("out/base.bin")),
        UnitSpec::new("main")
            .item_input("base", "base", "out")
            .output(OutputSpec::new("out", "/Game/Main").file("out/main.bin")),
        UnitSpec::new("extra")
            .file_input("data", "data/extra.bin")
            .output(OutputSpec::new("out", "/Game/Extra").file("out/extra.bin")),
    ];
    let snapshot = FrozenSnapshot::builder()
        .file("data/base.bin", vec![1])
        .file("data/extra.bin", vec![2])
        .build();
    let initial_plan = Plan::new(["base", "main"]);
    let added_plan = Plan::new(["base", "main", "extra"]);
    let target_main = vec![Target::Unit("main".into())];
    let target_all = vec![Target::All];
    let steps = vec![
        Step::new(
            "initial plan",
            units.clone(),
            snapshot.clone(),
            initial_plan.clone(),
            target_main.clone(),
        )
        .expect_runs(["base", "main"]),
        Step::new(
            "add extra but keep target main",
            units.clone(),
            snapshot.clone(),
            added_plan.clone(),
            target_main,
        )
        .expect_runs(Vec::<String>::new()),
        Step::new(
            "target all includes extra",
            units.clone(),
            snapshot.clone(),
            added_plan,
            target_all.clone(),
        )
        .expect_runs(["extra"]),
        Step::new(
            "remove extra from the plan",
            units.clone(),
            snapshot.clone(),
            initial_plan,
            target_all,
        )
        .expect_runs(Vec::<String>::new()),
    ];
    let report = run(&Scenario::new("plan-membership", steps)).expect("plan membership is modeled");
    assert_eq!(report.builds.len(), 4);
    assert_eq!(report.builds[1].actual.runs, Vec::<String>::new());
    assert_eq!(report.builds[2].actual.runs, vec!["extra".to_string()]);
    assert!(
        report.builds[3]
            .actual
            .removal_intent
            .contains_key(&("extra".to_string(), "out".to_string()))
    );
}

fn planner_units() -> Vec<UnitSpec> {
    vec![
        UnitSpec::new("plan")
            .file_input("plan", "data/plan.bin")
            .output(OutputSpec::new("a", "/Game/Plan/A").file("out/a.bin"))
            .output(OutputSpec::new("b", "/Game/Plan/B").file("out/b.bin")),
        UnitSpec::new("use.b")
            .item_input("member", "plan", "b")
            .output(OutputSpec::new("out", "/Game/UseB").file("out/use.b.bin")),
        UnitSpec::new("tail")
            .item_input("up", "use.b", "out")
            .output(OutputSpec::new("out", "/Game/Tail").file("out/tail.bin")),
    ]
}

#[test]
fn planner_roster_change_preserves_the_stable_member_and_removes_only_dropped_work() {
    let units = planner_units();
    let snapshot = FrozenSnapshot::builder()
        .file("data/plan.bin", vec![1, 2, 3])
        .build();
    let plan = Plan::all(&units);
    let target = vec![Target::Unit("tail".into())];
    let mut steps = vec![
        Step::new(
            "A/B roster",
            units.clone(),
            snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["plan", "use.b", "tail"]),
    ];

    let mut roster = units.clone();
    roster[0].outputs = vec![
        OutputSpec::new("b", "/Game/Plan/B").file("out/b.bin"),
        OutputSpec::new("c", "/Game/Plan/C").file("out/c.bin"),
    ];
    steps.push(
        Step::new(
            "B/C roster",
            roster.clone(),
            snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["plan"]),
    );

    let mut coded = roster.clone();
    coded[0].code = "planner-code-2".into();
    steps.push(
        Step::new(
            "planner code change",
            coded.clone(),
            snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["plan"]),
    );

    let mut moved = coded.clone();
    moved[0].outputs[0].files[0].path = "out/b2.bin".into();
    steps.push(
        Step::new(
            "member path change",
            moved.clone(),
            snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["plan", "use.b", "tail"]),
    );

    let mut executable = moved.clone();
    executable[0].outputs[0].files[0].mode = 0o755;
    steps.push(
        Step::new(
            "member mode change",
            executable,
            snapshot.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["plan", "use.b"]),
    );

    let scenario = Scenario::new("planner-roster", steps);
    let report = run(&scenario).expect("the planner roster scenario matches its model");
    let intent = &report.builds[1].actual.removal_intent;
    assert_eq!(intent.len(), 1);
    assert!(intent.contains_key(&("plan".to_string(), "a".to_string())));
    assert_eq!(report.builds[1].actual.runs, vec!["plan".to_string()]);
    assert_eq!(report.builds[2].actual.runs, vec!["plan".to_string()]);
    assert_eq!(
        report.builds[3].actual.runs,
        vec!["plan".to_string(), "use.b".to_string(), "tail".to_string()]
    );
    assert!(report.builds[4].actual.runs.contains(&"use.b".to_string()));
    assert!(!report.builds[4].actual.runs.contains(&"tail".to_string()));
}

fn fault_scenario(edit_reference: bool) -> Scenario {
    let units = chain_units();
    let snapshot = chain_snapshot();
    let plan = Plan::all(&units);
    let target = chain_target();
    let (edited, runs) = if edit_reference {
        (
            snapshot.with_file("data/ref.bin", vec![9, 9, 9]),
            vec!["refpkg"],
        )
    } else {
        (
            snapshot.with_file("data/source.bin", vec![9, 9]),
            vec!["data", "mid", "final"],
        )
    };
    Scenario::new(
        "faults",
        vec![
            Step::new(
                "initial",
                units.clone(),
                snapshot,
                plan.clone(),
                target.clone(),
            )
            .expect_runs(["data", "refpkg", "mid", "final"]),
            Step::new("edit", units, edited, plan, target).expect_runs(runs),
        ],
    )
}

fn mismatch_field(error: &HarnessError) -> &'static str {
    match error {
        HarnessError::Mismatch { field, .. } => field,
        other => panic!("expected a mismatch, got {other:?}"),
    }
}

#[test]
fn deliberately_faulty_adapters_are_caught() {
    let stale = run_scenario(
        &fault_scenario(false),
        faulty(AdapterFault::StaleHit),
        correct,
    )
    .expect_err("a stale hit must fail the run-set comparison");
    assert_eq!(mismatch_field(&stale), "run set");

    let rebuild = run_scenario(
        &fault_scenario(true),
        faulty(AdapterFault::OverRebuild),
        correct,
    )
    .expect_err("an over-rebuild must fail the run-set comparison");
    assert_eq!(mismatch_field(&rebuild), "run set");

    let reference = run_scenario(
        &fault_scenario(true),
        faulty(AdapterFault::ReferenceBytes),
        correct,
    )
    .expect_err("keying on reference bytes must fail the run-set comparison");
    assert_eq!(mismatch_field(&reference), "run set");

    let target = run_scenario(
        &fault_scenario(false),
        faulty(AdapterFault::MissingTarget),
        correct,
    )
    .expect_err("a missing target output must fail the target comparison");
    assert_eq!(mismatch_field(&target), "target outputs");
}

#[test]
fn seeded_sequences_match_the_model_and_keep_reproduction_data() {
    for seed in 0..16 {
        let scenario = random::scenario(seed);
        let report = run(&scenario).unwrap_or_else(|error| panic!("seed {seed}: {error}"));
        assert_eq!(report.status(), ProofStatus::Pending);
    }

    let scenario = random::scenario(7);
    let error = run_scenario(&scenario, faulty(AdapterFault::MissingTarget), correct)
        .expect_err("the missing-target fault must be caught on the seeded scenario");
    let reproduction = error
        .reproduction()
        .expect("a seeded failure carries its reproduction data");
    assert_eq!(reproduction.seed, 7);
    assert!(!reproduction.steps.is_empty());
    let expected_steps: Vec<String> = scenario
        .steps
        .iter()
        .take(reproduction.steps.len())
        .map(|step| step.note.clone())
        .collect();
    assert_eq!(reproduction.steps, expected_steps);
    assert_eq!(random::scenario(7), scenario);
    assert!(run(&scenario).is_ok());
}

#[test]
fn support_sources_do_not_reference_production_decision_code() {
    let sources = [
        ("support/mod.rs", include_str!("support/mod.rs")),
        ("support/snapshot.rs", include_str!("support/snapshot.rs")),
        ("support/spec.rs", include_str!("support/spec.rs")),
        ("support/work.rs", include_str!("support/work.rs")),
        ("support/model.rs", include_str!("support/model.rs")),
        ("support/adapter.rs", include_str!("support/adapter.rs")),
        ("support/check.rs", include_str!("support/check.rs")),
        ("support/random.rs", include_str!("support/random.rs")),
    ];
    for (name, source) in sources {
        for forbidden in [
            "atelier_build_v2::keys",
            "atelier_build_v2::graph",
            "atelier_build_v2::store",
            "atelier_build_v2::results",
            "atelier_build_v2::validate",
            "BuildGraph",
            "parse_declaration",
            "SourceSnapshot",
            "ResultRecord",
        ] {
            assert!(!source.contains(forbidden), "{name} references {forbidden}");
        }
        for line in source
            .lines()
            .filter(|line| line.contains("atelier_build_v2::"))
        {
            assert!(
                line.contains("fixture") || line.contains("protocol") || line.contains("schema"),
                "{name} uses a decision module: {line}"
            );
        }
    }
}

#[test]
fn identity_is_semantic_and_does_not_mirror_a_production_byte_format() {
    let snapshot = FrozenSnapshot::builder()
        .file("data/plan.bin", vec![1, 2, 3])
        .build();
    let config = HarnessConfig::default();
    let unit = UnitSpec::new("plan")
        .file_input("data", "data/plan.bin")
        .output(OutputSpec::new("b", "/Game/B").file("out/b.bin"));
    let resolved =
        vec![resolve_input(&unit.inputs[0], &snapshot, &BTreeMap::new()).expect("fixture input")];
    let identity = unit_identity(&config, &unit, &resolved);
    let payload = output_payloads(&unit, &resolved)["b"].files[0]
        .bytes
        .clone();

    let mut coded = unit.clone();
    coded.code = "code-2".into();
    assert_ne!(identity, unit_identity(&config, &coded, &resolved));
    assert_eq!(
        payload,
        output_payloads(&coded, &resolved)["b"].files[0].bytes
    );

    let mut moved = unit.clone();
    moved.outputs[0].files[0].path = "out/b2.bin".into();
    assert_ne!(identity, unit_identity(&config, &moved, &resolved));
    assert_ne!(
        payload,
        output_payloads(&moved, &resolved)["b"].files[0].bytes
    );

    let mut executable = unit.clone();
    executable.outputs[0].files[0].mode = 0o755;
    assert_ne!(identity, unit_identity(&config, &executable, &resolved));
    assert_eq!(
        payload,
        output_payloads(&executable, &resolved)["b"].files[0].bytes
    );

    let member = ProducedItem {
        logical_path: "/Game/B".into(),
        class: "Asset".into(),
        files: vec![MemberFile {
            path: "out/b.bin".into(),
            mode: 0o644,
            bytes: vec![7],
        }],
    };
    let mut produced = ProducedItems::new();
    produced.insert(("plan".into(), "b".into()), member.clone());
    produced.insert(("plan".into(), "renamed".into()), member.clone());
    let consumer = UnitSpec::new("use")
        .item_input("member", "plan", "b")
        .output(OutputSpec::new("out", "/Game/Use").file("out/use.bin"));
    let by_b = unit_identity(
        &config,
        &consumer,
        &[resolve_input(&consumer.inputs[0], &snapshot, &produced).expect("member")],
    );
    let mut renamed_consumer = consumer.clone();
    renamed_consumer.inputs[0] = InputSpec::item("member", "plan", "renamed");
    let by_renamed = unit_identity(
        &config,
        &renamed_consumer,
        &[resolve_input(&renamed_consumer.inputs[0], &snapshot, &produced).expect("member")],
    );
    assert_eq!(by_b, by_renamed);

    let mut moved_consumer = consumer.clone();
    moved_consumer.inputs[0] = moved_consumer.inputs[0]
        .clone()
        .staged_as("in/member-moved");
    let by_staged = unit_identity(
        &config,
        &moved_consumer,
        &[resolve_input(&moved_consumer.inputs[0], &snapshot, &produced).expect("member")],
    );
    assert_ne!(by_b, by_staged);

    let mut changed_mode = member;
    changed_mode.files[0].mode = 0o755;
    produced.insert(("plan".into(), "b".into()), changed_mode);
    let by_mode = unit_identity(
        &config,
        &consumer,
        &[resolve_input(&consumer.inputs[0], &snapshot, &produced).expect("member")],
    );
    assert_ne!(by_b, by_mode);
}

#[test]
fn raw_source_mode_is_ambient_but_item_member_mode_is_identity() {
    let units = vec![
        UnitSpec::new("leaf")
            .file_input("source", "data/source.bin")
            .output(OutputSpec::new("out", "/Game/Leaf").file("out/leaf.bin")),
        UnitSpec::new("use")
            .item_input("leaf", "leaf", "out")
            .output(OutputSpec::new("out", "/Game/Use").file("out/use.bin")),
    ];
    let plan = Plan::all(&units);
    let target = vec![Target::Unit("use".into())];
    let source = FrozenSnapshot::builder()
        .file("data/source.bin", vec![1, 2, 3])
        .build();
    let chmod = source.with_entry(
        "data/source.bin",
        FrozenFile::new(vec![1, 2, 3]).with_mode(0o755),
    );
    let mut item_mode = units.clone();
    item_mode[0].outputs[0].files[0].mode = 0o755;
    let steps = vec![
        Step::new(
            "initial",
            units.clone(),
            source.clone(),
            plan.clone(),
            target.clone(),
        )
        .expect_runs(["leaf", "use"]),
        Step::new(
            "raw source chmod",
            units.clone(),
            chmod,
            plan.clone(),
            target.clone(),
        )
        .expect_runs(Vec::<String>::new()),
        Step::new("item member mode", item_mode, source, plan, target).expect_runs(["leaf", "use"]),
    ];
    let report = run(&Scenario::new("mode-semantics", steps)).expect("mode semantics are modeled");
    assert_eq!(report.builds[1].actual.runs, Vec::<String>::new());
    assert_eq!(
        report.builds[2].actual.runs,
        vec!["leaf".to_string(), "use".to_string()]
    );
}
