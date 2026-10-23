//! Pure in-memory ingredient comparisons: no source/cache paths are opened.
use atelier_build_v2::explain::*;
use atelier_build_v2::schema::*;
use std::collections::BTreeMap;

fn ingredients() -> IdentityIngredients {
    IdentityIngredients {
        cache_version: "1".into(),
        op: Op {
            kind: "fixture".into(),
            version: "1".into(),
        },
        script: "ops/job.py".into(),
        code: BTreeMap::from([("ops/job.py".into(), "a".repeat(64))]),
        worker_version: "1".into(),
        worker_digest: "b".repeat(64),
        validator_version: "1".into(),
        validator_digest: "c".repeat(64),
        params: BTreeMap::from([(
            "setting".into(),
            serde_json::json!({"a":1,"b":"private-value"}),
        )]),
        content: BTreeMap::from([("selected".into(), ContentIdentity::Absent {})]),
        references: BTreeMap::from([(
            "reference".into(),
            ReferenceIdentity {
                logical_path: "/Game/Material".into(),
                class: "Material".into(),
            },
        )]),
        staged_inputs: BTreeMap::from([("selected".into(), "inputs/data.json".into())]),
        input_kinds: BTreeMap::from([("selected".into(), InputKind::File)]),
        logical_outputs: vec![],
        output_groups: vec![],
    }
}

#[test]
fn ingredient_differences_are_semantic_redacted_and_label_independent() {
    let original = ingredients();
    let old = IngredientSnapshot::capture(&original).unwrap();
    let mut changed = original.clone();
    changed.params.insert(
        "setting".into(),
        serde_json::json!({"b":"secret-new-value","a":1}),
    );
    changed.content.insert(
        "selected".into(),
        ContentIdentity::Digest {
            digest: "d".repeat(64),
        },
    );
    changed
        .references
        .get_mut("reference")
        .unwrap()
        .logical_path = "/Game/OtherPrivateName".into();
    changed.code.insert("ops/job.py".into(), "e".repeat(64));
    let diff = IngredientSnapshot::capture(&changed)
        .unwrap()
        .changes_from(&old);
    assert_eq!(
        diff,
        vec![
            IngredientChange {
                category: IngredientCategory::Code,
                slot: Some("ops/job.py".into())
            },
            IngredientChange {
                category: IngredientCategory::Parameter,
                slot: Some("setting".into())
            },
            IngredientChange {
                category: IngredientCategory::Content,
                slot: Some("selected".into())
            },
            IngredientChange {
                category: IngredientCategory::Reference,
                slot: Some("reference".into())
            },
        ]
    );
    let text = serde_json::to_string(&diff).unwrap();
    for value in [
        "private-value",
        "secret-new-value",
        "/Game/OtherPrivateName",
        &"e".repeat(64),
    ] {
        assert!(!text.contains(value));
    }
    // Reordering parameter object keys has A3's canonical semantics.
    let mut reordered = original.clone();
    reordered.params.insert(
        "setting".into(),
        serde_json::json!({"b":"private-value","a":1}),
    );
    assert!(
        IngredientSnapshot::capture(&reordered)
            .unwrap()
            .changes_from(&old)
            .is_empty()
    );
    // Scheduling labels, checkout/branch/commit, live platform/tool facts and source locators
    // are absent from this API, just as they are absent from prepared semantic ingredients.
    let old_label = BTreeMap::from([("old-label", old)]);
    let now = IngredientSnapshot::capture(&original).unwrap();
    assert!(now.changes_from(&old_label["old-label"]).is_empty());
}

#[test]
fn ingredient_versions_shapes_and_contract_changes_are_not_lost() {
    let original = ingredients();
    let old = IngredientSnapshot::capture(&original).unwrap();
    let mut changed = original.clone();
    changed.cache_version = "2".into();
    changed.op.version = "2".into();
    changed.script = "ops/other.py".into();
    changed.worker_digest = "d".repeat(64);
    changed.validator_version = "2".into();
    changed
        .staged_inputs
        .insert("selected".into(), "inputs/other.json".into());
    changed
        .input_kinds
        .insert("selected".into(), InputKind::Item);
    changed.logical_outputs.push(Item {
        id: "out".into(),
        logical_path: "/Game/Out".into(),
        class: "Data".into(),
        destination: Destination::Store,
        files: vec![],
    });
    let changes = IngredientSnapshot::capture(&changed)
        .unwrap()
        .changes_from(&old);
    let categories: Vec<_> = changes
        .iter()
        .map(|change| change.category.clone())
        .collect();
    assert_eq!(
        categories,
        vec![
            IngredientCategory::CacheVersion,
            IngredientCategory::Op,
            IngredientCategory::Entrypoint,
            IngredientCategory::Worker,
            IngredientCategory::Validator,
            IngredientCategory::StagedPath,
            IngredientCategory::InputKind,
            IngredientCategory::OutputContract
        ]
    );
    let mut removed = original;
    removed.params.clear();
    assert_eq!(
        IngredientSnapshot::capture(&removed)
            .unwrap()
            .changes_from(&old),
        vec![IngredientChange {
            category: IngredientCategory::Parameter,
            slot: Some("setting".into())
        }]
    );
}
