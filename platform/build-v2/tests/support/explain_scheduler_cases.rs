//! Reuses the existing deterministic scheduler fixture, not production cache authority.
use super::*;
use atelier_build_v2::explain::*;

fn observed(
    f: &Fixture,
    targets: &[&str],
    demands: &BTreeMap<String, FinalDemands>,
    fake: &mut Fake,
    jobs: &mut Jobs,
    recorder: &Recorder,
) -> Report {
    jobs.source_guard = Some(fake.source_guard.clone());
    let targets: Vec<_> = targets
        .iter()
        .map(|id| Target::Unit((*id).into()))
        .collect();
    run(
        Request::select(
            &f.graph,
            &targets,
            &f.snapshot,
            &f.versions,
            &f.runtimes,
            demands,
        )
        .unwrap(),
        &mut recorder.backend(fake),
        &mut recorder.executor(jobs),
        &Never,
        &mut SourceHashCache::default(),
    )
    .unwrap()
}
fn checkout_b() -> BTreeMap<String, FinalDemands> {
    BTreeMap::from([("b".into(), BTreeSet::from([Demand::Checkout]))])
}

#[test]
fn summary_first_noop_and_mixed_frontiers_match_existing_operation_trace() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace.clone());
    let mut demands = checkout_b();
    demands.insert("c".into(), BTreeSet::from([Demand::Stored]));
    let first = Recorder::default();
    let report = observed(&f, &["b", "c"], &demands, &mut fake, &mut jobs, &first);
    let summary = first.summarize(&report, &BTreeMap::new(), None).unwrap();
    assert_eq!(summary.counts.submitted, 3);
    assert_eq!(summary.counts.worker_completed, 3);
    assert_eq!(summary.counts.cached, 3);
    assert_eq!(summary.counts.installed_units, 1);
    assert_eq!(summary.counts.launched_attempts, None); // fake execution is not real launch proof
    assert!(
        summary
            .units
            .iter()
            .all(|unit| unit.ingredient_changes.is_none())
    );
    assert_eq!(
        trace
            .borrow()
            .iter()
            .filter(|line| line.starts_with("execute:"))
            .count(),
        3
    );
    let previous = first.ingredients();
    fake.current.insert("b".into());
    fake.recorded.insert("a".into());
    trace.borrow_mut().clear();
    let noop = Recorder::default();
    let report = observed(&f, &["b", "c"], &demands, &mut fake, &mut jobs, &noop);
    let summary = noop
        .summarize(&report, &previous, Some(&BTreeMap::new()))
        .unwrap();
    assert_eq!(summary.counts.identity_only, 1);
    assert_eq!(summary.counts.current, 1);
    assert_eq!(summary.counts.stored_hits, 1);
    assert_eq!(summary.counts.launched_attempts, Some(0));
    assert_eq!(
        summary.counts.submitted + summary.counts.restored + summary.counts.receipt_writes,
        0
    );
    assert!(
        summary
            .units
            .iter()
            .all(|unit| unit.ingredient_changes == Some(vec![]))
    );
    assert!(
        !trace
            .borrow()
            .iter()
            .any(|line| line.starts_with("inputs:") || line.starts_with("execute:"))
    );
    let key = report.keys["c"].clone();
    fake.cache.remove(&key);
    let mixed = Recorder::default();
    let report = observed(&f, &["b", "c"], &demands, &mut fake, &mut jobs, &mixed);
    let summary = mixed.summarize(&report, &previous, None).unwrap();
    assert_eq!(summary.counts.submitted, 1);
    assert_eq!(summary.counts.worker_completed, 1);
    assert_eq!(summary.counts.current, 1);
    assert_eq!(summary.counts.receipt_writes, 0);
}

#[test]
fn summary_output_cutoff_uses_selected_content_not_producer_key() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let old = Recorder::default();
    let report = observed(&f, &["b"], &checkout_b(), &mut fake, &mut jobs, &old);
    let mut changed = fixture(false);
    changed.runtimes.get_mut("a").unwrap().worker.version = "manual-v2".into();
    let next = Recorder::default();
    let next_report = observed(&changed, &["b"], &checkout_b(), &mut fake, &mut jobs, &next);
    let summary = next
        .summarize(&next_report, &old.ingredients(), None)
        .unwrap();
    assert_ne!(report.keys["a"], next_report.keys["a"]);
    assert_eq!(report.keys["b"], next_report.keys["b"]);
    assert_eq!(summary.counts.submitted, 1);
    assert_eq!(
        summary.units[0].ingredient_changes,
        Some(vec![IngredientChange {
            category: IngredientCategory::Worker,
            slot: None
        }])
    );
    assert_eq!(summary.units[1].ingredient_changes, Some(vec![]));
    assert_eq!(summary.units[1].lookup, Some(LookupReason::StoredHit));
    assert!(!summary.units[1].restored); // hit already installed; no clone/receipt rewrite
}

#[test]
fn summary_restored_hit_requires_actual_settlement_effects() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let first = Recorder::default();
    observed(&f, &["b"], &checkout_b(), &mut fake, &mut jobs, &first);
    fake.installed.remove("b");
    fake.recorded.insert("a".into());
    let recorder = Recorder::default();
    let report = observed(&f, &["b"], &checkout_b(), &mut fake, &mut jobs, &recorder);
    let summary = recorder
        .summarize(&report, &first.ingredients(), Some(&BTreeMap::new()))
        .unwrap();
    assert_eq!(summary.counts.identity_only, 1);
    assert_eq!(summary.counts.stored_hits, 1);
    assert_eq!(summary.counts.restored, 1);
    assert_eq!(summary.counts.receipt_writes, 1);
    assert_eq!(summary.counts.launched_attempts, Some(0));
}

#[test]
fn summary_missing_blob_is_typed_refusal_without_eviction_or_error_text() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let prior = Recorder::default();
    let report = observed(&f, &["b"], &checkout_b(), &mut fake, &mut jobs, &prior);
    fake.cache.remove(&report.keys["b"]);
    fake.recorded.insert("a".into());
    fake.miss_reason = Some(NonHitReason::MissingObject);
    fake.unavailable.insert("b".into());
    let recorder = Recorder::default();
    let report = observed(&f, &["b"], &checkout_b(), &mut fake, &mut jobs, &recorder);
    let summary = recorder
        .summarize(&report, &prior.ingredients(), None)
        .unwrap();
    let b = summary.units.iter().find(|unit| unit.unit == "b").unwrap();
    assert_eq!(
        b.lookup,
        Some(LookupReason::Miss(MissReason::MissingObject))
    );
    assert_eq!(b.outcome, Outcome::SourceUnavailable);
    assert_eq!(
        summary.counts.submitted + summary.counts.worker_completed + summary.counts.receipt_writes,
        0
    );
    let text = serde_json::to_string(&summary).unwrap();
    assert!(!text.contains("evicted"));
    assert!(!text.contains("selected source adapter unsupported"));
}

#[test]
fn summary_not_cached_feeds_downstream_and_late_failure_keeps_partial_success() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    fake.not_cached.insert("a".into());
    jobs.fail.insert("c".into());
    let mut demands = checkout_b();
    demands.insert("a".into(), BTreeSet::from([Demand::Stored]));
    demands.insert("c".into(), BTreeSet::from([Demand::Stored]));
    let recorder = Recorder::default();
    let report = observed(
        &f,
        &["a", "b", "c"],
        &demands,
        &mut fake,
        &mut jobs,
        &recorder,
    );
    let summary = recorder.summarize(&report, &BTreeMap::new(), None).unwrap();
    assert_eq!(summary.counts.submitted, 3);
    assert_eq!(summary.counts.worker_completed, 2);
    assert_eq!(summary.counts.not_cached, 1);
    assert_eq!(summary.counts.cached, 1);
    assert_eq!(summary.counts.failed, 1);
    assert_eq!(summary.counts.installed_units, 1);
    assert!(summary.units[0].unsatisfied_stored);
    assert_eq!(summary.units[1].outcome, Outcome::Executed);
}

#[test]
fn summary_keeps_published_result_when_settlement_fails_and_marks_unknown_attempts() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    fake.fail_settle.insert("a".into());
    fake.fail_publish.insert("c".into());
    let recorder = Recorder::default();
    let demands = BTreeMap::from([
        ("a".into(), BTreeSet::from([Demand::Stored])),
        ("c".into(), BTreeSet::from([Demand::Stored])),
    ]);
    let report = observed(&f, &["a", "c"], &demands, &mut fake, &mut jobs, &recorder);
    let summary = recorder
        .summarize(&report, &BTreeMap::new(), Some(&BTreeMap::new()))
        .unwrap();
    assert_eq!(summary.counts.cached, 1); // scheduler successful-publications list omits failed settlement
    assert_eq!(summary.counts.publication_unknown, 1); // Err is not proof nothing was published
    assert_eq!(summary.counts.failed, 2);
    assert_eq!(summary.counts.launched_attempts, None); // submitted work has no authentic launch observation
    assert!(!summary.effects_complete);
    assert!(report.publications.is_empty());
    assert!(fake.cache.contains_key(&report.keys["a"]));
}

#[test]
fn summary_refuses_mismatched_evidence_and_retains_unresolved_lifecycle() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    jobs.omit = true;
    let recorder = Recorder::default();
    let mut report = observed(&f, &["b"], &checkout_b(), &mut fake, &mut jobs, &recorder);
    let summary = recorder.summarize(&report, &BTreeMap::new(), None).unwrap();
    assert!(summary.executor_fatal);
    assert_eq!(summary.counts.worker_completed + summary.counts.cached, 0);
    assert_eq!(summary.counts.blocked, 1);
    assert!(
        recorder
            .summarize(
                &report,
                &BTreeMap::new(),
                Some(&BTreeMap::from([("foreign".into(), 1)]))
            )
            .is_err()
    );
    report.keys.insert("a".into(), "foreign".into());
    assert!(recorder.summarize(&report, &BTreeMap::new(), None).is_err());
}

#[test]
fn summary_rejected_hit_does_not_count_successful_reuse() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let demands = BTreeMap::from([("a".into(), BTreeSet::from([Demand::Stored]))]);
    observed(
        &f,
        &["a"],
        &demands,
        &mut fake,
        &mut jobs,
        &Recorder::default(),
    );
    fake.bad_key = true;
    let recorder = Recorder::default();
    let report = observed(&f, &["a"], &demands, &mut fake, &mut jobs, &recorder);
    let summary = recorder.summarize(&report, &BTreeMap::new(), None).unwrap();
    assert_eq!(summary.counts.failed, 1);
    assert_eq!(summary.counts.stored_hits + summary.counts.restored, 0);
    assert_eq!(summary.counts.submitted + summary.counts.cached, 0);
    assert_eq!(summary.units[0].lookup, Some(LookupReason::StoredHit));
    assert_eq!(summary.units[0].outcome, Outcome::Failed);
}

#[test]
fn summary_wrong_publication_key_is_unknown_even_if_record_was_written() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    fake.bad_publish_key = true;
    let demands = BTreeMap::from([("a".into(), BTreeSet::from([Demand::Stored]))]);
    let recorder = Recorder::default();
    let report = observed(&f, &["a"], &demands, &mut fake, &mut jobs, &recorder);
    let summary = recorder.summarize(&report, &BTreeMap::new(), None).unwrap();
    assert_eq!(summary.counts.failed, 1);
    assert_eq!(summary.counts.worker_completed, 1);
    assert_eq!(summary.counts.cached + summary.counts.not_cached, 0);
    assert_eq!(summary.counts.publication_unknown, 1);
    assert!(report.publications.is_empty());
    assert!(fake.cache.contains_key(&report.keys["a"])); // publication error is not proof of no write
}
