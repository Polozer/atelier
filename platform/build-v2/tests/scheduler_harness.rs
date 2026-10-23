//! Test-only translation into the independent A8 BuildAdapter seam. The oracle remains unchanged.
#![allow(dead_code)]
mod support;
use atelier_build_v2::{
    graph, groups::ValidatedGroup, integrity::NonHitReason, keys::*, scheduler::*, schema::*,
    source_hashes::*, validate::*,
};
use sha2::{Digest, Sha256};
use std::{cell::RefCell, collections::BTreeMap, rc::Rc};
use support::{
    adapter::{AdapterError, BuildAdapter, BuildOutcome, BuildRequest, FakeAdapter, Observation},
    check::{Scenario, Step, run_scenario},
    snapshot::FrozenSnapshot,
    spec::{self, Edge, EdgeRole, InputSpec, OutputSpec, Plan, SavedUnit, StoreHealth, UnitSpec},
    work::{ProducedItem, ProducedItems, output_payloads, resolve_input, unit_identity},
};
struct Authority {
    unit: String,
    key: String,
    items: Vec<StoredItem>,
    payloads: BTreeMap<String, ProducedItem>,
    groups: BTreeMap<String, ValidatedGroup>,
}
#[derive(Default)]
struct Adapter {
    cache: BTreeMap<String, Authority>,
    overbuild: bool,
}
struct Cache<'a> {
    saved: &'a mut BTreeMap<String, Authority>,
    produced: Rc<RefCell<ProducedItems>>,
    healthy: bool,
    overbuild: bool,
}
impl Clone for Authority {
    fn clone(&self) -> Self {
        assert!(
            self.groups.is_empty(),
            "static fixture does not clone group authority"
        );
        Self {
            unit: self.unit.clone(),
            key: self.key.clone(),
            items: self.items.clone(),
            payloads: self.payloads.clone(),
            groups: BTreeMap::new(),
        }
    }
}
impl Backend for Cache<'_> {
    type Checked = Authority;
    type Ticket = String;
    type Completion = BTreeMap<String, ProducedItem>;
    fn lookup(&mut self, u: &PreparedUnit, _: Demand) -> Result<Lookup<Authority, String>, String> {
        let id = &u.request("diagnostic", "job").unit;
        if self.healthy && !self.overbuild {
            if let Some(a) = self.saved.get(id).filter(|a| a.key == u.key()) {
                return Ok(Lookup::Hit(a.clone()));
            }
        }
        Ok(Lookup::Miss {
            ticket: u.key().into(),
            reason: NonHitReason::MissingRecord,
        })
    }
    fn view<'a>(&'a self, a: &'a Authority) -> CheckedView<'a> {
        CheckedView {
            key: &a.key,
            items: &a.items,
            groups: &a.groups,
        }
    }
    fn into_outputs(
        &mut self,
        checked: Authority,
    ) -> (Vec<StoredItem>, BTreeMap<String, ValidatedGroup>) {
        (checked.items, checked.groups)
    }
    fn publish(
        &mut self,
        w: Work<String>,
        payloads: Self::Completion,
    ) -> Result<Published<Authority>, String> {
        assert_eq!(w.ticket(), w.prepared().key());
        let items = w
            .prepared()
            .ingredients()
            .logical_outputs
            .iter()
            .map(|item| {
                let p = &payloads[&item.id];
                StoredItem {
                    item: item.clone(),
                    external_locator: None,
                    files: p
                        .files
                        .iter()
                        .map(|f| StoredFile {
                            path: f.path.clone(),
                            digest: format!("{:x}", Sha256::digest(&f.bytes)),
                            size: f.bytes.len() as u64,
                            mode: f.mode,
                        })
                        .collect(),
                }
            })
            .collect();
        let a = Authority {
            unit: w.unit().into(),
            key: w.prepared().key().into(),
            items,
            payloads,
            groups: BTreeMap::new(),
        };
        if self.healthy {
            self.saved.insert(a.unit.clone(), a.clone());
        }
        Ok(Published {
            checked: a,
            publication: if self.healthy {
                Publication::Cached
            } else {
                Publication::NotCached("fixture unavailable cache".into())
            },
        })
    }
    fn settle(
        &mut self,
        _: &PreparedUnit,
        a: &mut Authority,
        _: Demand,
    ) -> Result<Effects, String> {
        for (id, p) in &a.payloads {
            self.produced
                .borrow_mut()
                .insert((a.unit.clone(), id.clone()), p.clone());
        }
        Ok(Effects::default())
    }
}
struct Jobs<'a> {
    request: &'a BuildRequest<'a>,
    produced: Rc<RefCell<ProducedItems>>,
}
struct Control;
impl atelier_build_v2::scheduler::Control for Control {
    fn cancelled(&self) -> bool {
        false
    }
}
impl Executor<String, BTreeMap<String, ProducedItem>> for Jobs<'_> {
    fn batch(
        &mut self,
        work: Vec<Work<String>>,
        _: &dyn atelier_build_v2::scheduler::Control,
        emit: &mut dyn FnMut(Event<String, BTreeMap<String, ProducedItem>>) -> Flow,
    ) -> Result<(), String> {
        for w in work {
            let unit = self
                .request
                .units
                .iter()
                .find(|u| u.id == w.unit())
                .unwrap();
            let inputs = unit
                .inputs
                .iter()
                .map(|i| resolve_input(i, self.request.snapshot, &self.produced.borrow()))
                .collect::<Result<Vec<_>, _>>()?;
            let payloads = output_payloads(unit, &inputs);
            if emit(Event::Completed {
                work: w,
                completion: payloads,
                effects: Effects {
                    staged_units: 1,
                    ..Effects::default()
                },
            }) == Flow::Stop
            {
                break;
            }
        }
        Ok(())
    }
}
fn error(message: impl ToString) -> AdapterError {
    AdapterError {
        message: message.to_string(),
    }
}
impl BuildAdapter for Adapter {
    fn execute(&mut self, r: &BuildRequest<'_>) -> Result<BuildOutcome, AdapterError> {
        let mut snapshot = SourceSnapshot::new();
        let mut units = Vec::new();
        let mut registry = OpRegistry::new();
        let mut runtimes = BTreeMap::new();
        for u in r.units.iter().filter(|u| r.plan.contains(&u.id)) {
            // The fixture's per-unit code and output mode policy are explicit keyed declarations.
            let script = format!("ops/{}.py", u.id);
            snapshot.insert(
                script.clone(),
                SnapshotEntry::File(u.code.as_bytes().to_vec()),
            );
            let mut rules = BTreeMap::new();
            let mut staged = BTreeMap::new();
            let mut inputs = Vec::new();
            for i in &u.inputs {
                staged.insert(i.name().into(), i.staged_path());
                let (role, optional, input) = match i {
                    InputSpec::File {
                        name,
                        path,
                        optional,
                        ..
                    } => {
                        if let Some(f) = r.snapshot.get(path) {
                            snapshot.insert(path.clone(), SnapshotEntry::File(f.bytes.clone()));
                        }
                        (
                            InputRole::Content,
                            *optional,
                            Input::Content {
                                name: name.clone(),
                                source: ContentSource::File {
                                    path: path.clone(),
                                    selector: None,
                                    optional: *optional,
                                },
                                whole: None,
                                conditional: None,
                            },
                        )
                    }
                    InputSpec::Item {
                        name, unit, item, ..
                    } => (
                        InputRole::Content,
                        false,
                        Input::Content {
                            name: name.clone(),
                            source: ContentSource::Item {
                                unit: unit.clone(),
                                item: item.clone(),
                            },
                            whole: None,
                            conditional: None,
                        },
                    ),
                    InputSpec::Reference {
                        name,
                        logical_path,
                        class,
                        producer,
                        ..
                    } => (
                        InputRole::Reference,
                        false,
                        Input::Reference {
                            name: name.clone(),
                            logical_path: logical_path.clone(),
                            class: class.clone(),
                            proof: "independent fixture reference work".into(),
                            producer: producer.as_ref().map(|(unit, item)| ItemRef {
                                unit: unit.clone(),
                                item: item.clone(),
                            }),
                        },
                    ),
                };
                rules.insert(
                    i.name().into(),
                    InputRule {
                        role,
                        required: true,
                        allow_absent_file: optional,
                        allow_selector: false,
                        require_whole_reason: false,
                        item_classes: r
                            .units
                            .iter()
                            .flat_map(|u| u.outputs.iter().map(|o| o.class.clone()))
                            .collect(),
                    },
                );
                inputs.push(input);
            }
            let kind = format!("fixture_{}", u.id);
            registry.insert(
                (kind.clone(), u.op_version.clone()),
                OpDefinition {
                    inputs: rules,
                    output_classes: u.outputs.iter().map(|o| o.class.clone()).collect(),
                    params: BTreeMap::from([
                        (
                            "value".into(),
                            ParamRule {
                                kind: ParamKind::String,
                                required: true,
                            },
                        ),
                        (
                            "declared_op".into(),
                            ParamRule {
                                kind: ParamKind::String,
                                required: true,
                            },
                        ),
                        (
                            "modes".into(),
                            ParamRule {
                                kind: ParamKind::Object,
                                required: true,
                            },
                        ),
                    ]),
                },
            );
            let modes: serde_json::Value = serde_json::to_value(
                u.outputs
                    .iter()
                    .map(|o| {
                        (
                            o.item.clone(),
                            o.files
                                .iter()
                                .map(|f| (f.path.clone(), f.mode))
                                .collect::<BTreeMap<_, _>>(),
                        )
                    })
                    .collect::<BTreeMap<_, _>>(),
            )
            .unwrap();
            units.push(Unit {
                id: u.id.clone(),
                op: Op {
                    kind,
                    version: u.op_version.clone(),
                },
                script: script.clone(),
                code: vec![script],
                inputs,
                params: BTreeMap::from([
                    ("value".into(), u.params.clone().into()),
                    ("declared_op".into(), u.op_kind.clone().into()),
                    ("modes".into(), modes),
                ]),
                outputs: u
                    .outputs
                    .iter()
                    .map(|o| Item {
                        id: o.item.clone(),
                        logical_path: o.logical_path.clone(),
                        class: o.class.clone(),
                        destination: Destination::Store,
                        files: o
                            .files
                            .iter()
                            .map(|f| OutputFile {
                                path: f.path.clone(),
                                install_path: None,
                                required: f.required,
                            })
                            .collect(),
                    })
                    .collect(),
                output_groups: vec![],
                conditional: None,
            });
            runtimes.insert(
                u.id.clone(),
                Runtime {
                    worker: ImplementationIdentity {
                        version: r.config.worker_version.clone(),
                        digest: "a".repeat(64),
                    },
                    validator: ImplementationIdentity {
                        version: r.config.validator_version.clone(),
                        digest: "b".repeat(64),
                    },
                    staged_inputs: staged,
                    profile: "fixture".into(),
                },
            );
        }
        let declaration = Declaration {
            schema_version: SCHEMA_VERSION,
            cache_version: r.config.cache_version.clone(),
            units,
        };
        let graph = graph::BuildGraph::validate(declaration, &registry, &[]).map_err(error)?;
        let targets = r
            .targets
            .iter()
            .map(|t| match t {
                spec::Target::Unit(id) => graph::Target::Unit(id.clone()),
                spec::Target::All => graph::Target::All,
            })
            .collect::<Vec<_>>();
        let selected = graph.select(&targets, &snapshot).map_err(error)?;
        let demands = selected
            .roots()
            .iter()
            .map(|id| (id.clone(), Demand::Stored))
            .collect();
        let order = selected.order().to_vec();
        let roots = selected.roots().iter().cloned().collect();
        let edges = selected
            .dependencies()
            .iter()
            .map(|d| Edge {
                producer: d.producer.clone(),
                consumer: d.consumer.clone(),
                item: match &d.output {
                    graph::DependencyOutput::Item(item) => item.clone(),
                    _ => unreachable!("this adapter constructs only fixed outputs"),
                },
                input: d.input.clone(),
                role: match d.role {
                    graph::EdgeRole::Content => EdgeRole::Content,
                    graph::EdgeRole::Reference => EdgeRole::Reference,
                },
            })
            .collect();
        let produced = Rc::new(RefCell::new(ProducedItems::new()));
        let mut cache = Cache {
            saved: &mut self.cache,
            produced: produced.clone(),
            healthy: r.store == StoreHealth::Available,
            overbuild: self.overbuild,
        };
        let mut jobs = Jobs {
            request: r,
            produced: produced.clone(),
        };
        let versions = SourceVersions::new();
        let report = run(
            Request::select(&graph, &targets, &snapshot, &versions, &runtimes, &demands)
                .map_err(error)?,
            &mut cache,
            &mut jobs,
            &Control,
            &mut SourceHashCache::default(),
        )
        .map_err(error)?;
        if report
            .states
            .values()
            .any(|s| !matches!(s, State::Current | State::Hit | State::Executed(_)))
        {
            return Err(error(format!("scheduler incomplete: {:?}", report.states)));
        }
        let outputs = produced.borrow().clone();
        let mut saved_after = r.saved.clone();
        let mut runs = Vec::new();
        let mut current = Vec::new();
        for id in &order {
            let u = r.units.iter().find(|u| &u.id == id).unwrap();
            match report.states[id] {
                State::Executed(_) => runs.push(id.clone()),
                _ => current.push(id.clone()),
            };
            let resolved = u
                .inputs
                .iter()
                .map(|i| resolve_input(i, r.snapshot, &outputs))
                .collect::<Result<Vec<_>, _>>()
                .map_err(error)?;
            saved_after.insert(
                id,
                SavedUnit {
                    identity: unit_identity(r.config, u, &resolved),
                    outputs: u
                        .outputs
                        .iter()
                        .map(|o| {
                            (
                                o.item.clone(),
                                outputs[&(id.clone(), o.item.clone())].clone(),
                            )
                        })
                        .collect(),
                },
            );
        }
        let requested = outputs
            .iter()
            .filter(|((id, _), _)| selected.roots().contains(id))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        // This bounded static adapter explicitly refuses retirement cases; it does not guess ownership.
        for id in r.saved.units.keys() {
            if !r.plan.contains(id) {
                return Err(error(
                    "persisted dynamic retirement not supported by static adapter",
                ));
            }
        }
        Ok(BuildOutcome {
            observation: Observation {
                roots,
                order,
                edges,
                runs,
                current,
                requested,
                outputs,
                removal_intent: BTreeMap::new(),
                worker_events: report.effects.staged_units,
            },
            saved_after,
        })
    }
}
fn scenario() -> Scenario {
    let units = vec![
        UnitSpec::new("source")
            .file_input("input", "source.bin")
            .output(OutputSpec::new("out", "/Game/Source").file("source.bin")),
        UnitSpec::new("finish")
            .item_input("piece", "source", "out")
            .output(OutputSpec::new("out", "/Game/Finish").file("finish.bin")),
    ];
    let snapshot = FrozenSnapshot::builder()
        .file("source.bin", b"same output".to_vec())
        .build();
    let plan = Plan::all(&units);
    let mut edited = units.clone();
    edited[0].code = "code-2".into();
    Scenario::new(
        "real static scheduler over independent model",
        vec![
            Step::new(
                "cold",
                units.clone(),
                snapshot.clone(),
                plan.clone(),
                [spec::Target::Unit("finish".into())],
            )
            .expect_runs(["source", "finish"]),
            Step::new(
                "unchanged",
                units,
                snapshot.clone(),
                plan.clone(),
                [spec::Target::Unit("finish".into())],
            )
            .expect_runs(Vec::<String>::new()),
            Step::new(
                "producer code edit leaves same payload",
                edited.clone(),
                snapshot.clone(),
                plan.clone(),
                [spec::Target::Unit("finish".into())],
            )
            .expect_runs(["source"]),
            Step::new(
                "content mutation",
                edited,
                snapshot.with_file("source.bin", b"changed".to_vec()),
                plan,
                [spec::Target::Unit("finish".into())],
            )
            .expect_runs(["source", "finish"]),
        ],
    )
}
#[test]
fn independent_model_and_clean_oracle_judge_real_static_scheduler() {
    let report = run_scenario(
        &scenario(),
        || Box::new(Adapter::default()),
        || Box::new(FakeAdapter::new()),
    )
    .unwrap();
    assert_eq!(report.builds.len(), 4);
    assert!(!report.is_pass());
    assert_eq!(report.pending.len(), 1); // Real worker/materialization acceptance stays pending.
}
#[test]
fn independent_model_rejects_faulty_scheduler_adapter_overbuild() {
    let result = run_scenario(
        &scenario(),
        || {
            Box::new(Adapter {
                overbuild: true,
                ..Adapter::default()
            })
        },
        || Box::new(FakeAdapter::new()),
    );
    assert!(result.is_err());
}
