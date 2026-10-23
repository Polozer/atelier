//! Bounded seeded graph, edit and store-failure sequences.
use crate::support::check::{Scenario, Step};
use crate::support::snapshot::FrozenSnapshot;
use crate::support::spec::{InputSpec, OutputSpec, Plan, StoreHealth, Target, UnitSpec};

pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Self {
            state: seed
                .wrapping_mul(0x9e37_79b9_7f4a_7c15)
                .wrapping_add(0x1234_5678_9abc_def1)
                | 1,
        }
    }

    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 13;
        value ^= value >> 7;
        value ^= value << 17;
        self.state = value;
        value
    }

    fn below(&mut self, limit: u64) -> u64 {
        if limit == 0 { 0 } else { self.next() % limit }
    }

    fn bool(&mut self) -> bool {
        self.next() & 1 == 1
    }
}

fn optional_input(unit: &UnitSpec) -> Option<(String, String)> {
    unit.inputs.iter().find_map(|input| match input {
        InputSpec::File {
            name,
            path,
            optional: true,
            ..
        } => Some((name.clone(), path.clone())),
        _ => None,
    })
}

/// Builds a deterministic bounded scenario. The same seed always yields the same steps.
pub fn scenario(seed: u64) -> Scenario {
    let mut rng = Rng::new(seed);
    let count = 3 + rng.below(4) as usize;
    let mut units = Vec::new();
    let mut snapshot = FrozenSnapshot::builder();

    for index in 0..count {
        let data_path = format!("data/u{index}.bin");
        snapshot = snapshot.file(
            data_path.clone(),
            vec![index as u8, rng.next() as u8, 0, 255],
        );
        let mut unit = UnitSpec::new(format!("u{index}")).file_input("data", data_path);
        if index > 0 {
            if rng.bool() {
                unit = unit.item_input("up", format!("u{}", index - 1), "main");
            }
            if rng.bool() {
                let producer = rng.below(index as u64) as usize;
                unit = unit.reference_from(
                    "ref",
                    format!("/Game/Ref/u{producer}"),
                    "Asset",
                    format!("u{producer}"),
                    "main",
                );
            }
        }
        if rng.bool() {
            unit = unit.optional_file_input("opt", format!("data/opt{index}.bin"));
        }
        unit = unit.output(
            OutputSpec::new("main", format!("/Game/Out/u{index}"))
                .file(format!("out/u{index}.bin")),
        );
        if rng.bool() {
            unit = unit.output(
                OutputSpec::new("side", format!("/Game/Side/u{index}"))
                    .file(format!("out/u{index}.side.bin")),
            );
        }
        units.push(unit);
    }

    snapshot = snapshot.file("data/spare.bin", vec![9, 9, 9]);
    units.push(
        UnitSpec::new("spare")
            .file_input("data", "data/spare.bin")
            .output(OutputSpec::new("main", "/Game/Out/spare").file("out/spare.bin")),
    );

    let mut snapshot = snapshot.build();
    let mut plan = Plan::all(&units);
    let target = Target::Unit(format!("u{}", count - 1));
    let mut store = StoreHealth::Available;
    let mut steps = vec![Step::new(
        "initial",
        units.clone(),
        snapshot.clone(),
        plan.clone(),
        [target.clone()],
    )];

    let edits = 2 + rng.below(4) as usize;
    for edit in 0..edits {
        let note = match rng.below(7) {
            0 => {
                let index = rng.below(count as u64) as usize;
                let bytes = vec![rng.next() as u8, rng.next() as u8, edit as u8];
                snapshot = snapshot.with_file(format!("data/u{index}.bin"), bytes);
                format!("edit content u{index}")
            }
            1 => {
                let candidates: Vec<_> = units.iter().filter_map(optional_input).collect();
                if candidates.is_empty() {
                    "optional input unavailable".into()
                } else {
                    let (_, path) = &candidates[rng.below(candidates.len() as u64) as usize];
                    if snapshot.contains(path) {
                        snapshot = snapshot.without(path);
                        format!("remove optional {path}")
                    } else {
                        snapshot = snapshot.with_file(path.clone(), Vec::new());
                        format!("add empty optional {path}")
                    }
                }
            }
            2 => {
                let index = rng.below(count as u64) as usize;
                units[index].code = format!("code-{}", edit + 2);
                format!("change code u{index}")
            }
            3 => {
                let index = rng.below(count as u64) as usize;
                units[index].outputs[0].files[0].path = format!("out/u{index}-r{}.bin", edit + 2);
                format!("move output path u{index}")
            }
            4 => {
                let index = rng.below(count as u64) as usize;
                let mode = units[index].outputs[0].files[0].mode;
                units[index].outputs[0].files[0].mode = if mode == 0o644 { 0o755 } else { 0o644 };
                format!("change output mode u{index}")
            }
            5 => {
                if plan.contains("spare") {
                    plan.remove("spare");
                    "remove spare from plan".into()
                } else {
                    plan.insert("spare");
                    "add spare to plan".into()
                }
            }
            _ => {
                store = match store {
                    StoreHealth::Available => StoreHealth::Failing,
                    StoreHealth::Failing => StoreHealth::Available,
                };
                format!("store now {store:?}")
            }
        };
        steps.push(
            Step::new(
                note,
                units.clone(),
                snapshot.clone(),
                plan.clone(),
                [target.clone()],
            )
            .store(store),
        );
    }

    Scenario::new(format!("seeded-{seed}"), steps).seeded(seed)
}
