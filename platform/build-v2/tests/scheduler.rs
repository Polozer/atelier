//! Fake execution exercises the real A3 key/A4 graph loop; it is not production cache authority.
use atelier_build_v2::{
    graph::*, groups::ValidatedGroup, integrity::NonHitReason, keys::*, scheduler::*, schema::*,
    source_hashes::*, validate::*,
};
use std::cell::{Cell, RefCell};
use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

type Trace = Rc<RefCell<Vec<String>>>;
struct Checked {
    key: String,
    items: Vec<StoredItem>,
    groups: BTreeMap<String, ValidatedGroup>,
}
struct Fake {
    cache: BTreeMap<String, Checked>,
    outputs: BTreeMap<String, String>,
    trace: Trace,
    current: BTreeSet<String>,
    fail_publish: BTreeSet<String>,
    bad_key: bool,
    bad_settle: bool,
}
impl Fake {
    fn new(trace: Trace) -> Self {
        Self {
            cache: BTreeMap::new(),
            outputs: BTreeMap::new(),
            trace,
            current: BTreeSet::new(),
            fail_publish: BTreeSet::new(),
            bad_key: false,
            bad_settle: false,
        }
    }
}
impl Clone for Checked {
    fn clone(&self) -> Self {
        assert!(
            self.groups.is_empty(),
            "static fixture does not clone group authority"
        );
        Self {
            key: self.key.clone(),
            items: self.items.clone(),
            groups: BTreeMap::new(),
        }
    }
}
impl Backend for Fake {
    type Checked = Checked;
    type Ticket = String;
    type Completion = ();
    fn lookup(&mut self, u: &PreparedUnit, d: Demand) -> Result<Lookup<Checked, String>, String> {
        let id = &u.ingredients().logical_outputs[0].id;
        self.trace.borrow_mut().push(format!("lookup:{id}:{d:?}"));
        if let Some(c) = self.cache.get(u.key()) {
            let mut c = c.clone();
            if self.bad_key {
                c.key = "foreign".into()
            };
            return Ok(if self.current.contains(id) {
                Lookup::Current(c)
            } else {
                Lookup::Hit(c)
            });
        }
        Ok(Lookup::Miss {
            ticket: u.key().into(),
            reason: NonHitReason::MissingRecord,
        })
    }
    fn view<'a>(&'a self, c: &'a Checked) -> CheckedView<'a> {
        CheckedView {
            key: &c.key,
            items: &c.items,
            groups: &c.groups,
        }
    }
    fn into_outputs(
        &mut self,
        checked: Checked,
    ) -> (Vec<StoredItem>, BTreeMap<String, ValidatedGroup>) {
        (checked.items, checked.groups)
    }
    fn publish(&mut self, w: Work<String>, _: ()) -> Result<Published<Checked>, String> {
        assert_eq!(w.ticket(), w.prepared().key());
        let id = w.unit().to_string();
        self.trace.borrow_mut().push(format!("publish:{id}"));
        if self.fail_publish.contains(&id) {
            return Err("invalid result".into());
        }
        let items = w
            .prepared()
            .ingredients()
            .logical_outputs
            .iter()
            .map(|item| StoredItem {
                item: item.clone(),
                files: item
                    .files
                    .iter()
                    .map(|f| StoredFile {
                        path: f.path.clone(),
                        digest: self.outputs.get(&id).cloned().unwrap_or("a".repeat(64)),
                        size: 4,
                        mode: 0o644,
                    })
                    .collect(),
                external_locator: None,
            })
            .collect();
        let checked = Checked {
            key: w.prepared().key().into(),
            items,
            groups: BTreeMap::new(),
        };
        self.cache.insert(checked.key.clone(), checked.clone());
        Ok(Published {
            checked,
            publication: Publication::Cached,
        })
    }
    fn settle(&mut self, u: &PreparedUnit, _: &mut Checked, d: Demand) -> Result<Effects, String> {
        let id = &u.ingredients().logical_outputs[0].id;
        self.trace.borrow_mut().push(format!("settle:{id}:{d:?}"));
        Ok(Effects {
            installed_units: usize::from(
                (d == Demand::Checkout && !self.current.contains(id)) || self.bad_settle,
            ),
            receipt_writes: usize::from(
                (d == Demand::Checkout && !self.current.contains(id)) || self.bad_settle,
            ),
            staged_units: 0,
        })
    }
}
struct Never;
impl Control for Never {
    fn cancelled(&self) -> bool {
        false
    }
}
struct Flag(Rc<Cell<bool>>);
impl Control for Flag {
    fn cancelled(&self) -> bool {
        self.0.get()
    }
}
struct Jobs {
    trace: Trace,
    fail: BTreeSet<String>,
    cancel_after: Option<Rc<Cell<bool>>>,
    omit: bool,
}
impl Jobs {
    fn new(trace: Trace) -> Self {
        Self {
            trace,
            fail: BTreeSet::new(),
            cancel_after: None,
            omit: false,
        }
    }
}
impl Executor<String, ()> for Jobs {
    fn batch(
        &mut self,
        work: Vec<Work<String>>,
        _: &dyn Control,
        emit: &mut dyn FnMut(Event<String, ()>) -> Flow,
    ) -> Result<(), String> {
        for w in work {
            let id = w.unit().to_string();
            self.trace.borrow_mut().push(format!("execute:{id}"));
            if self.omit {
                continue;
            }
            let event = if self.fail.contains(&id) {
                Event::Failed {
                    work: w,
                    reason: "worker refusal".into(),
                }
            } else {
                Event::Completed {
                    work: w,
                    completion: (),
                    effects: Effects {
                        staged_units: 1,
                        ..Effects::default()
                    },
                }
            };
            let flow = emit(event);
            if let Some(flag) = &self.cancel_after {
                flag.set(true);
                return Ok(());
            }
            if flow == Flow::Stop {
                return Ok(());
            }
        }
        Ok(())
    }
}
struct Fixture {
    graph: BuildGraph,
    snapshot: SourceSnapshot,
    runtimes: BTreeMap<String, Runtime>,
    versions: SourceVersions,
}
fn fixture(reference: bool) -> Fixture {
    let role = if reference { "reference" } else { "content" };
    let input = if reference {
        format!(
            r#"{{role="{role}",name="upstream",logical_path="/Game/A",class="Blob",proof="fixture bounded read",producer={{unit="a",item="a"}}}}"#
        )
    } else {
        r#"{role="content",name="upstream",source={kind="item",unit="a",item="a"}}"#.into()
    };
    let text = format!(
        r#"
schema_version=2
cache_version="fixture1"
[[units]]
id="a"
op={{kind="fixture",version="1"}}
script="op.py"
code=["op.py"]
params={{value=1}}
outputs=[{{id="a",logical_path="/Game/A",class="Blob",destination="store",files=[{{path="a.bin"}}]}}]
[[units]]
id="b"
op={{kind="fixture",version="1"}}
script="op.py"
code=["op.py"]
params={{value=1}}
inputs=[{input}]
outputs=[{{id="b",logical_path="/Game/B",class="Blob",destination="checkout",files=[{{path="b.bin",install_path="Content/b.bin"}}]}}]
[[units]]
id="c"
op={{kind="fixture",version="1"}}
script="op.py"
code=["op.py"]
params={{value=1}}
outputs=[{{id="c",logical_path="/Game/C",class="Blob",destination="store",files=[{{path="c.bin"}}]}}]
"#
    );
    let declaration: Declaration = toml::from_str(&text).unwrap();
    let registry = BTreeMap::from([(
        ("fixture".into(), "1".into()),
        OpDefinition {
            inputs: BTreeMap::from([(
                "upstream".into(),
                InputRule {
                    role: if reference {
                        InputRole::Reference
                    } else {
                        InputRole::Content
                    },
                    required: false,
                    allow_absent_file: false,
                    allow_selector: false,
                    require_whole_reason: false,
                    item_classes: BTreeSet::from(["Blob".into()]),
                },
            )]),
            output_classes: BTreeSet::from(["Blob".into()]),
            params: BTreeMap::from([(
                "value".into(),
                ParamRule {
                    kind: ParamKind::Integer,
                    required: true,
                },
            )]),
        },
    )]);
    let graph = BuildGraph::validate(declaration, &registry, &["Content".into()]).unwrap();
    let implementation = ImplementationIdentity {
        version: "1".into(),
        digest: "d".repeat(64),
    };
    let runtimes = ["a", "b", "c"]
        .into_iter()
        .map(|id| {
            (
                id.into(),
                Runtime {
                    worker: implementation.clone(),
                    validator: implementation.clone(),
                    staged_inputs: if id == "b" {
                        BTreeMap::from([("upstream".into(), "inputs/upstream".into())])
                    } else {
                        BTreeMap::new()
                    },
                    profile: "default".into(),
                },
            )
        })
        .collect();
    Fixture {
        graph,
        snapshot: BTreeMap::from([("op.py".into(), SnapshotEntry::File(b"fixture".to_vec()))]),
        runtimes,
        versions: BTreeMap::new(),
    }
}
fn build(
    f: &Fixture,
    targets: &[&str],
    demands: &BTreeMap<String, Demand>,
    fake: &mut Fake,
    jobs: &mut Jobs,
    control: &dyn Control,
) -> Report {
    let ts = targets
        .iter()
        .map(|s| Target::Unit((*s).into()))
        .collect::<Vec<_>>();
    run(
        Request::select(
            &f.graph,
            &ts,
            &f.snapshot,
            &f.versions,
            &f.runtimes,
            demands,
        )
        .unwrap(),
        fake,
        jobs,
        control,
        &mut SourceHashCache::default(),
    )
    .unwrap()
}
#[test]
fn frontier_lookup_precedes_compatible_dispatch_and_hits_launch_nothing() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace.clone());
    let demands = BTreeMap::from([("a".into(), Demand::Stored), ("c".into(), Demand::Stored)]);
    let first = build(&f, &["a", "c"], &demands, &mut fake, &mut jobs, &Never);
    assert_eq!(first.batches, vec![vec!["a", "c"]]);
    assert_eq!(
        &trace.borrow()[..3],
        &["lookup:a:Stored", "lookup:c:Stored", "execute:a"]
    );
    trace.borrow_mut().clear();
    let hit = build(&f, &["a", "c"], &demands, &mut fake, &mut jobs, &Never);
    assert!(hit.batches.is_empty());
    assert!(hit.states.values().all(|s| *s == State::Hit));
    assert_eq!(hit.effects, Effects::default());
}
#[test]
fn equal_output_content_cuts_off_changed_producer_input_key() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let demands = BTreeMap::from([("b".into(), Demand::Checkout)]);
    let first = build(&f, &["b"], &demands, &mut fake, &mut jobs, &Never);
    let mut changed = fixture(false);
    changed.runtimes.get_mut("a").unwrap().worker.version = "2".into();
    let next = build(&changed, &["b"], &demands, &mut fake, &mut jobs, &Never);
    assert_ne!(first.keys["a"], next.keys["a"]);
    assert_eq!(first.keys["b"], next.keys["b"]);
    assert_eq!(next.states["b"], State::Hit);
    assert_eq!(next.batches, vec![vec!["a"]]);
    fake.outputs.insert("a".into(), "b".repeat(64));
    changed.runtimes.get_mut("a").unwrap().worker.version = "3".into();
    let unequal = build(&changed, &["b"], &demands, &mut fake, &mut jobs, &Never);
    assert_ne!(next.keys["b"], unequal.keys["b"]);
    assert!(matches!(unequal.states["b"], State::Executed(_)));
}
#[test]
fn reference_ordering_does_not_hash_producer_payload() {
    let mut f = fixture(true);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let demands = BTreeMap::from([("b".into(), Demand::Checkout)]);
    let first = build(&f, &["b"], &demands, &mut fake, &mut jobs, &Never);
    fake.outputs.insert("a".into(), "b".repeat(64));
    f.runtimes.get_mut("a").unwrap().worker.version = "2".into();
    let next = build(&f, &["b"], &demands, &mut fake, &mut jobs, &Never);
    assert_ne!(first.keys["a"], next.keys["a"]);
    assert_eq!(first.keys["b"], next.keys["b"]);
    assert_eq!(next.states["b"], State::Hit);
}
#[test]
fn independent_failure_retains_publication_and_blocks_only_dependents() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    jobs.fail.insert("a".into());
    let demands = BTreeMap::from([("b".into(), Demand::Checkout), ("c".into(), Demand::Stored)]);
    let report = build(&f, &["b", "c"], &demands, &mut fake, &mut jobs, &Never);
    assert!(matches!(report.states["a"], State::Failed(_)));
    assert_eq!(report.states["b"], State::Blocked(vec!["a".into()]));
    assert!(matches!(report.states["c"], State::Executed(_)));
    assert_eq!(report.publications, vec!["c"]);
    assert!(fake.cache.contains_key(&report.keys["c"]));
}
#[test]
fn cancellation_preserves_completed_units_and_marks_unreturned_work() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let flag = Rc::new(Cell::new(false));
    jobs.cancel_after = Some(flag.clone());
    let demands = BTreeMap::from([("a".into(), Demand::Stored), ("c".into(), Demand::Stored)]);
    let report = build(&f, &["a", "c"], &demands, &mut fake, &mut jobs, &Flag(flag));
    assert_eq!(report.publications, vec!["a"]);
    assert!(matches!(report.states["a"], State::Executed(_)));
    assert_eq!(report.states["c"], State::Cancelled);
}
#[test]
fn faulty_backend_key_and_materialization_claims_refuse() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let demands = BTreeMap::from([("a".into(), Demand::Stored)]);
    build(&f, &["a"], &demands, &mut fake, &mut jobs, &Never);
    fake.bad_key = true;
    let bad = build(&f, &["a"], &demands, &mut fake, &mut jobs, &Never);
    assert!(matches!(&bad.states["a"],State::Failed(s) if s.contains("another prepared key")));
    fake.bad_key = false;
    fake.bad_settle = true;
    let bad = build(&f, &["a"], &demands, &mut fake, &mut jobs, &Never);
    assert!(matches!(&bad.states["a"],State::Failed(s) if s.contains("Stored demand")));
}
#[test]
fn target_materialization_is_explicit_and_current_does_not_rewrite() {
    let f = fixture(false);
    let trace = Trace::default();
    let mut fake = Fake::new(trace.clone());
    let mut jobs = Jobs::new(trace);
    let demands = BTreeMap::from([("b".into(), Demand::Checkout)]);
    let first = build(&f, &["b"], &demands, &mut fake, &mut jobs, &Never);
    assert_eq!(first.effects.installed_units, 1);
    assert_eq!(first.effects.receipt_writes, 1);
    assert!(!first.states.contains_key("c"));
    // Fake Current is deliberately a separate tag; this adapter's incorrect rewrite is detected.
    fake.current.insert("b".into());
    let current = build(&f, &["b"], &demands, &mut fake, &mut jobs, &Never);
    assert_eq!(current.states["b"], State::Current);
    assert_eq!(current.effects, Effects::default());
    fake.bad_settle = true;
    let bad = build(&f, &["b"], &demands, &mut fake, &mut jobs, &Never);
    assert!(matches!(&bad.states["b"],State::Failed(s) if s.contains("Current settlement")));
}
