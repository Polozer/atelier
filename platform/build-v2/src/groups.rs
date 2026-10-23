//! Bounded discovery metadata and private validation tokens for opaque D2 payloads.
//! No geometry IR, live directory discovery, publication, dispatch or deletion.
use crate::keys::normalized_mode;
use crate::paths::{Claims, claim, logical_path, relative_path};
use crate::schema::{Destination, Item, OutputFile, StoredFile, StoredItem};
use crate::source_hashes::valid_digest;
use crate::store::PreparedObject;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlanEncoding {
    MeshIr,
    MeshSet,
    EncodedGlb,
}

/// Fixed before execution. Runtime names/membership must never replace this contract.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OutputGroupContract {
    pub id: String,
    /// Relative to the job output directory, exclusive to this group.
    pub root: String,
    /// Declared semantic param containing the worker-visible output/<root> path.
    pub root_param: String,
    /// Relative to root, owned by the group rather than a second fixed Item.
    pub manifest: String,
    pub adapter_version: String,
    pub parent: String,
    pub encoding: PlanEncoding,
    pub class: String,
    pub logical_namespace: String,
    pub max_pieces: u64,
    pub max_manifest_bytes: u64,
    pub max_member_bytes: u64,
    pub max_total_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MemberProjection {
    pub payload: String,
    pub encoding: PlanEncoding,
}

/// Complete immutable result data. Deserialization alone grants no validation token.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoredOutputGroup {
    pub id: String,
    pub files: Vec<StoredFile>,
    pub projections: BTreeMap<String, MemberProjection>,
}

/// Discovery checks only; the source-specific validator still certifies the payloads.
#[derive(Debug)]
pub struct PlanRoster {
    raw: Value,
    stored: StoredOutputGroup,
}
impl PlanRoster {
    pub fn raw(&self) -> &Value {
        &self.raw
    }
    pub fn stored(&self) -> &StoredOutputGroup {
        &self.stored
    }
}

/// Only frozen-source validation or trusted result restoration can issue this token.
/// It does not publish anything; B2 must match it to its own leased prepared objects.
#[derive(Debug)]
pub struct ValidatedGroup {
    contract: OutputGroupContract,
    stored: StoredOutputGroup,
}
impl ValidatedGroup {
    pub fn contract(&self) -> &OutputGroupContract {
        &self.contract
    }
    pub fn stored(&self) -> &StoredOutputGroup {
        &self.stored
    }
    pub fn project(&self, piece: &str) -> Result<StoredItem, String> {
        let projection = self
            .stored
            .projections
            .get(piece)
            .ok_or("unknown projected piece")?;
        let file = self
            .stored
            .files
            .iter()
            .find(|file| file.path == projection.payload)
            .ok_or("projected member is absent")?
            .clone();
        Ok(StoredItem {
            item: Item {
                id: piece.into(),
                logical_path: format!("{}/{piece}", self.contract.logical_namespace),
                class: self.contract.class.clone(),
                destination: Destination::Store,
                files: vec![OutputFile {
                    path: file.path.clone(),
                    install_path: None,
                    required: true,
                }],
            },
            files: vec![file],
            external_locator: None,
        })
    }
}

pub(crate) fn name(value: &str) -> Result<(), String> {
    if !value
        .as_bytes()
        .first()
        .is_some_and(u8::is_ascii_alphabetic)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
    {
        return Err(format!("invalid authored piece/group name: {value:?}"));
    }
    Ok(())
}
fn text<'a>(value: &'a Value, field: &str) -> Result<&'a str, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing string {field}"))
}
fn integer(value: &Value, field: &str) -> Result<u64, String> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("missing unsigned integer {field}"))
}

impl OutputGroupContract {
    pub fn validate_root_param(&self, params: &crate::schema::Params) -> Result<(), String> {
        if params.get(&self.root_param) != Some(&Value::String(format!("output/{}", self.root))) {
            return Err("output group root differs from explicit keyed worker param".into());
        }
        Ok(())
    }
    pub fn validate(&self) -> Result<(), String> {
        name(&self.id)?;
        name(&self.parent)?;
        name(&self.root_param)?;
        relative_path(&self.root, true)?;
        relative_path(&self.manifest, true)?;
        logical_path(&self.logical_namespace)?;
        if self.adapter_version.trim().is_empty()
            || self.class.trim().is_empty()
            || self.max_pieces == 0
            || self.max_manifest_bytes == 0
            || self.max_member_bytes == 0
            || self.max_total_bytes == 0
            || self.max_manifest_bytes > self.max_member_bytes
            || self.max_member_bytes > self.max_total_bytes
        {
            return Err("invalid bounded output-group contract".into());
        }
        Ok(())
    }
}

/// Share one output-namespace policy with A2, including group/fixed aliases and ancestors.
pub fn validate_ownership(groups: &[OutputGroupContract], fixed: &[String]) -> Result<(), String> {
    let mut claims = Claims::new();
    for path in fixed {
        relative_path(path, true)?;
        claim(&mut claims, path, "fixed output")?;
    }
    let mut ids = BTreeSet::new();
    for group in groups {
        group.validate()?;
        if !ids.insert(&group.id) {
            return Err("duplicate output group id".into());
        }
        claim(&mut claims, &group.root, &group.id)?;
    }
    Ok(())
}

fn check_recorded(
    contract: &OutputGroupContract,
    stored: &StoredOutputGroup,
) -> Result<(), String> {
    contract.validate()?;
    if stored.id != contract.id
        || stored.projections.is_empty()
        || stored.projections.len() as u64 > contract.max_pieces
    {
        return Err("wrong group identity or piece count".into());
    }
    let mut claims = Claims::new();
    let mut by_path = BTreeMap::new();
    let mut total = 0u64;
    for file in &stored.files {
        relative_path(&file.path, true)?;
        claim(&mut claims, &file.path, "group member")?;
        if !valid_digest(&file.digest)
            || ![0o644, 0o755].contains(&file.mode)
            || file.size > contract.max_member_bytes
        {
            return Err("invalid group member digest/mode/size".into());
        }
        total = total.checked_add(file.size).ok_or("group size overflow")?;
        by_path.insert(file.path.as_str(), file);
    }
    if total > contract.max_total_bytes {
        return Err("group byte budget exceeded".into());
    }
    let manifest = by_path
        .get(contract.manifest.as_str())
        .ok_or("missing group manifest")?;
    if manifest.size > contract.max_manifest_bytes {
        return Err("manifest byte budget exceeded".into());
    }
    let mut expected = BTreeSet::from([contract.manifest.as_str()]);
    let mut pieces = Claims::new();
    for (piece, projection) in &stored.projections {
        name(piece)?;
        claim(&mut pieces, piece, "piece")?;
        if projection.encoding != contract.encoding {
            return Err("wrong projected payload type".into());
        }
        let suffix = match contract.encoding {
            PlanEncoding::EncodedGlb => ".mesh",
            _ => ".npz",
        };
        if projection.payload != format!("{piece}{suffix}")
            || !expected.insert(projection.payload.as_str())
            || !by_path.contains_key(projection.payload.as_str())
        {
            return Err("missing, duplicate or foreign projected payload".into());
        }
    }
    if expected != by_path.keys().copied().collect() {
        return Err("foreign or incomplete group membership".into());
    }
    Ok(())
}

/// Parse the existing plan envelope, never reinterpret its opaque geometry payloads.
/// This alone is not a source-format certificate or a publication token.
pub fn parse_manifest(
    contract: &OutputGroupContract,
    bytes: &[u8],
    files: &[StoredFile],
) -> Result<PlanRoster, String> {
    contract.validate()?;
    if bytes.len() as u64 > contract.max_manifest_bytes {
        return Err("manifest byte budget exceeded".into());
    }
    let raw: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    if integer(&raw, "schema")? != 1
        || text(&raw, "parent")? != contract.parent
        || raw.get("complete") != Some(&Value::Bool(true))
        || integer(&raw, "triangle_limit")? != 32768
    {
        return Err("incomplete, foreign or unsupported plan".into());
    }
    let expected_kind = match contract.encoding {
        PlanEncoding::MeshIr => None,
        PlanEncoding::MeshSet => Some("mesh_set"),
        PlanEncoding::EncodedGlb => Some("encoded_glb"),
    };
    if raw.get("kind").and_then(Value::as_str) != expected_kind
        || (expected_kind.is_none() && raw.get("kind").is_some())
    {
        return Err("wrong plan encoding".into());
    }
    let rows = raw
        .get("pieces")
        .and_then(Value::as_array)
        .ok_or("missing pieces")?;
    if rows.is_empty() || rows.len() as u64 > contract.max_pieces {
        return Err("piece count budget exceeded".into());
    }
    let mut projections = BTreeMap::new();
    let mut triangles = 0u64;
    for (index, row) in rows.iter().enumerate() {
        let piece = text(row, "name")?;
        name(piece)?;
        let count = integer(row, "triangles")?;
        if count == 0 || count > 32768 {
            return Err("piece triangle budget exceeded".into());
        }
        triangles = triangles
            .checked_add(count)
            .ok_or("triangle total overflow")?;
        if contract.encoding != PlanEncoding::EncodedGlb {
            let whole_hulls = integer(&raw, "source_collision_hulls")?;
            if integer(row, "collision_hulls")? != if index == 0 { whole_hulls } else { 0 } {
                return Err("whole collision owner differs".into());
            }
        }
        let payload = text(row, "payload")?;
        let file = files
            .iter()
            .find(|file| file.path == payload)
            .ok_or("missing payload member")?;
        if text(row, "sha256")? != file.digest {
            return Err("payload digest differs from plan".into());
        }
        if projections
            .insert(
                piece.into(),
                MemberProjection {
                    payload: payload.into(),
                    encoding: contract.encoding.clone(),
                },
            )
            .is_some()
        {
            return Err("duplicate piece name".into());
        }
    }
    if triangles != integer(&raw, "source_triangles")? {
        return Err("incomplete triangle total".into());
    }
    let mut files = files.to_vec();
    files.sort_by(|a, b| a.path.cmp(&b.path));
    let stored = StoredOutputGroup {
        id: contract.id.clone(),
        files,
        projections,
    };
    check_recorded(contract, &stored)?;
    Ok(PlanRoster { raw, stored })
}

/// @cc [owner:fontanierh,label:correctness] frozen-group-member-projection
/// A group token MUST follow complete manifest checks and source-specific validation
/// of the same frozen PreparedObjects already hashed by B1. Child projections MUST
/// contain only their named member; no planner key, roster digest or sibling bytes.
/// B2 must retain/match these same prepared objects through publication. See tests/groups.rs.
pub fn validate_frozen(
    contract: &OutputGroupContract,
    objects: &BTreeMap<String, &PreparedObject>,
    validator: impl FnOnce(&PlanRoster, &BTreeMap<String, &PreparedObject>) -> Result<(), String>,
) -> Result<ValidatedGroup, String> {
    contract.validate()?;
    let manifest = objects
        .get(&contract.manifest)
        .ok_or("missing frozen manifest")?;
    if manifest.size() > contract.max_manifest_bytes {
        return Err("manifest byte budget exceeded".into());
    }
    let files: Vec<_> = objects
        .iter()
        .map(|(path, object)| StoredFile {
            path: path.clone(),
            digest: object.digest().to_string(),
            size: object.size(),
            mode: normalized_mode(object.source_mode()),
        })
        .collect();
    let mut bytes = Vec::new();
    manifest
        .reader()
        .map_err(|error| error.to_string())?
        .take(contract.max_manifest_bytes)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.len() as u64 != manifest.size() {
        return Err("frozen manifest size differs".into());
    }
    let roster = parse_manifest(contract, &bytes, &files)?;
    validator(&roster, objects)?;
    Ok(ValidatedGroup {
        contract: contract.clone(),
        stored: roster.stored,
    })
}

/// Only B2's trusted immutable-result reader may restore a token without repeating
/// source validation. Check every named object under the same result/GC lock first.
pub(crate) fn restore_recorded(
    contract: &OutputGroupContract,
    stored: &StoredOutputGroup,
    mut check_object: impl FnMut(&StoredFile) -> Result<(), String>,
) -> Result<ValidatedGroup, String> {
    check_recorded(contract, stored)?;
    for file in &stored.files {
        check_object(file)?;
    }
    Ok(ValidatedGroup {
        contract: contract.clone(),
        stored: stored.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::keys::canonical_bytes;
    use crate::source_hashes::sha256;

    fn fixture() -> (OutputGroupContract, StoredOutputGroup) {
        let contract = OutputGroupContract {
            id: "geometry".into(),
            root: "geometry".into(),
            root_param: "output_root".into(),
            manifest: "plan.json".into(),
            adapter_version: "d2.mesh-plan/1".into(),
            parent: "Village_Edges".into(),
            encoding: PlanEncoding::MeshIr,
            class: "GeometryPayload".into(),
            logical_namespace: "/Internal/Plans/Village_Edges".into(),
            max_pieces: 1024,
            max_manifest_bytes: 4 * 1024 * 1024,
            max_member_bytes: 128 * 1024 * 1024,
            max_total_bytes: 1024 * 1024 * 1024,
        };
        let bytes = include_bytes!("../examples/plans/village_edges.plan.json");
        let files = vec![
            StoredFile {
                path: "plan.json".into(),
                digest: sha256(bytes),
                size: bytes.len() as u64,
                mode: 0o644,
            },
            StoredFile {
                path: "Village_Edges.npz".into(),
                digest: "020a2216fd56fea8992dec94acc335b33704a3c8464c9e8691ab4909272cc539".into(),
                size: 138217,
                mode: 0o644,
            },
        ];
        let roster = parse_manifest(&contract, bytes, &files).unwrap();
        (contract, roster.stored)
    }

    #[test]
    fn recorded_group_projects_only_selected_member_without_output_reads() {
        let (contract, stored) = fixture();
        let mut checked = Vec::new();
        let first = restore_recorded(&contract, &stored, |file| {
            checked.push(file.path.clone());
            Ok(())
        })
        .unwrap();
        assert_eq!(checked, ["Village_Edges.npz", "plan.json"]);
        let selected = first.project("Village_Edges").unwrap();
        let content = serde_json::json!({"domain":"atelier-item-content","version":1,
            "logical_path":selected.item.logical_path,"class":selected.item.class,"files":selected.files});
        assert_eq!(
            sha256(&canonical_bytes(&content).unwrap()),
            "3c4fcd2d192350e7ebdf6a3ce2dcca75284b27671d09949547515b819479232c"
        );
        let mut changed = first.stored.clone();
        changed
            .files
            .iter_mut()
            .find(|file| file.path == "plan.json")
            .unwrap()
            .digest = "a".repeat(64);
        changed.files.push(StoredFile {
            path: "Sibling.npz".into(),
            digest: "b".repeat(64),
            size: 10,
            mode: 0o644,
        });
        changed.projections.insert(
            "Sibling".into(),
            MemberProjection {
                payload: "Sibling.npz".into(),
                encoding: PlanEncoding::MeshIr,
            },
        );
        let second = restore_recorded(&contract, &changed, |_| Ok(())).unwrap();
        assert_ne!(first.stored(), second.stored());
        assert_eq!(selected, second.project("Village_Edges").unwrap());
        assert_ne!(selected, second.project("Sibling").unwrap());
        changed
            .files
            .iter_mut()
            .find(|file| file.path == "Village_Edges.npz")
            .unwrap()
            .mode = 0o755;
        assert_ne!(
            selected,
            restore_recorded(&contract, &changed, |_| Ok(()))
                .unwrap()
                .project("Village_Edges")
                .unwrap()
        );
        assert!(restore_recorded(&contract, &changed, |_| Err("blob absent".into())).is_err());
        changed.projections.get_mut("Sibling").unwrap().payload = "missing.npz".into();
        assert!(restore_recorded(&contract, &changed, |_| Ok(())).is_err());
    }
    fn key_fixture(
        contract: &OutputGroupContract,
    ) -> (
        crate::schema::Declaration,
        crate::validate::OpRegistry,
        crate::validate::SourceSnapshot,
    ) {
        use crate::schema::*;
        use crate::validate::*;
        let planner = Unit {
            id: "planner".into(),
            op: Op {
                kind: "fixture".into(),
                version: "1".into(),
            },
            script: "ops/plan.py".into(),
            code: vec!["ops/plan.py".into()],
            inputs: vec![],
            params: BTreeMap::from([(
                "output_root".into(),
                Value::String("output/geometry".into()),
            )]),
            outputs: vec![],
            output_groups: vec![contract.clone()],
            conditional: None,
        };
        let child = Unit {
            id: "export.Village_Edges".into(),
            op: planner.op.clone(),
            script: "ops/export.py".into(),
            code: vec!["ops/export.py".into()],
            inputs: vec![Input::Content {
                name: "payload".into(),
                source: ContentSource::GroupMember {
                    unit: "planner".into(),
                    group: "geometry".into(),
                    piece: "Village_Edges".into(),
                },
                whole: None,
                conditional: None,
            }],
            params: BTreeMap::from([
                (
                    "payload_member".into(),
                    Value::String("Village_Edges.npz".into()),
                ),
                ("format".into(), Value::String(".fbx".into())),
            ]),
            outputs: vec![Item {
                id: "mesh".into(),
                logical_path: "/Game/Village/Village_Edges".into(),
                class: "StaticMeshSource".into(),
                files: vec![
                    OutputFile {
                        path: "Village_Edges.fbx".into(),
                        install_path: None,
                        required: true,
                    },
                    OutputFile {
                        path: "export.json".into(),
                        install_path: None,
                        required: true,
                    },
                ],
                destination: Destination::Store,
            }],
            output_groups: vec![],
            conditional: None,
        };
        let registry = BTreeMap::from([(
            ("fixture".into(), "1".into()),
            OpDefinition {
                inputs: BTreeMap::from([(
                    "payload".into(),
                    InputRule {
                        role: InputRole::Content,
                        required: false,
                        allow_absent_file: false,
                        allow_selector: false,
                        require_whole_reason: false,
                        item_classes: BTreeSet::from(["GeometryPayload".into()]),
                    },
                )]),
                output_classes: BTreeSet::from([
                    "GeometryPayload".into(),
                    "StaticMeshSource".into(),
                ]),
                params: ["output_root", "payload_member", "format"]
                    .into_iter()
                    .map(|name| {
                        (
                            name.into(),
                            ParamRule {
                                kind: ParamKind::String,
                                required: false,
                            },
                        )
                    })
                    .collect(),
            },
        )]);
        let snapshot = BTreeMap::from([
            (
                "ops/plan.py".into(),
                SnapshotEntry::File(b"fixture planner v1".to_vec()),
            ),
            (
                "ops/export.py".into(),
                SnapshotEntry::File(b"fixture exporter v1".to_vec()),
            ),
        ]);
        (
            Declaration {
                schema_version: SCHEMA_VERSION,
                cache_version: "fixture-1".into(),
                units: vec![planner, child],
            },
            registry,
            snapshot,
        )
    }

    fn prepared(
        declaration: &crate::schema::Declaration,
        registry: &crate::validate::OpRegistry,
        snapshot: &crate::validate::SourceSnapshot,
        groups: &crate::keys::ProducedGroups,
        unit: &str,
    ) -> Result<crate::keys::PreparedUnit, String> {
        use crate::keys::*;
        let validated = crate::validate::validate(declaration, registry, snapshot, &[])
            .map_err(|e| e.to_string())?;
        let staged = if unit == "planner" {
            BTreeMap::new()
        } else {
            BTreeMap::from([("payload".into(), "inputs/payload".into())])
        };
        let implementation = ImplementationIdentity {
            version: "fixture-worker-1".into(),
            digest: "c".repeat(64),
        };
        prepare(
            declaration,
            &validated,
            unit,
            &KeyContext {
                snapshot,
                versions: &BTreeMap::new(),
                produced: &BTreeMap::new(),
                produced_groups: groups,
                staged_inputs: &staged,
                worker: &implementation,
                validator: &implementation,
            },
            &mut crate::source_hashes::SourceHashCache::default(),
        )
    }

    #[test]
    fn fixed_group_contract_keys_planner_without_runtime_membership() {
        let (contract, stored) = fixture();
        let (mut declaration, registry, snapshot) = key_fixture(&contract);
        let mut groups = BTreeMap::from([(
            ("planner".into(), "geometry".into()),
            restore_recorded(&contract, &stored, |_| Ok(())).unwrap(),
        )]);
        let before = prepared(&declaration, &registry, &snapshot, &groups, "planner").unwrap();
        groups.clear();
        assert_eq!(
            before.key(),
            prepared(&declaration, &registry, &snapshot, &groups, "planner")
                .unwrap()
                .key()
        );
        declaration.units[0].output_groups[0].max_pieces += 1;
        assert_ne!(
            before.key(),
            prepared(&declaration, &registry, &snapshot, &groups, "planner")
                .unwrap()
                .key()
        );
        declaration.units[0].output_groups[0].max_pieces -= 1;
        declaration.units[0].output_groups[0].adapter_version = "d2.mesh-plan/2".into();
        assert_ne!(
            before.key(),
            prepared(&declaration, &registry, &snapshot, &groups, "planner")
                .unwrap()
                .key()
        );
        declaration.schema_version = crate::schema::LEGACY_SCHEMA_VERSION;
        assert!(prepared(&declaration, &registry, &snapshot, &groups, "planner").is_err());
    }

    #[test]
    fn member_keys_cut_off_planner_and_sibling_changes_but_bind_selected_view() {
        let (contract, stored) = fixture();
        let (declaration, registry, mut snapshot) = key_fixture(&contract);
        let mut groups = BTreeMap::from([(
            ("planner".into(), "geometry".into()),
            restore_recorded(&contract, &stored, |_| Ok(())).unwrap(),
        )]);
        let first = prepared(
            &declaration,
            &registry,
            &snapshot,
            &groups,
            "export.Village_Edges",
        )
        .unwrap();
        let planner_before =
            prepared(&declaration, &registry, &snapshot, &groups, "planner").unwrap();
        snapshot.insert(
            "ops/plan.py".into(),
            crate::validate::SnapshotEntry::File(b"fixture planner v1 # comment".to_vec()),
        );
        assert_ne!(
            planner_before.key(),
            prepared(&declaration, &registry, &snapshot, &groups, "planner")
                .unwrap()
                .key()
        );
        assert_eq!(
            first.key(),
            prepared(
                &declaration,
                &registry,
                &snapshot,
                &groups,
                "export.Village_Edges"
            )
            .unwrap()
            .key()
        );
        let mut changed = stored.clone();
        changed
            .files
            .iter_mut()
            .find(|file| file.path == "plan.json")
            .unwrap()
            .digest = "d".repeat(64);
        changed.files.push(StoredFile {
            path: "Sibling.npz".into(),
            digest: "e".repeat(64),
            size: 10,
            mode: 0o644,
        });
        changed.projections.insert(
            "Sibling".into(),
            MemberProjection {
                payload: "Sibling.npz".into(),
                encoding: PlanEncoding::MeshIr,
            },
        );
        groups.insert(
            ("planner".into(), "geometry".into()),
            restore_recorded(&contract, &changed, |_| Ok(())).unwrap(),
        );
        assert_eq!(
            first.key(),
            prepared(
                &declaration,
                &registry,
                &snapshot,
                &groups,
                "export.Village_Edges"
            )
            .unwrap()
            .key()
        );
        changed
            .files
            .iter_mut()
            .find(|file| file.path == "Village_Edges.npz")
            .unwrap()
            .digest = "a".repeat(64);
        groups.insert(
            ("planner".into(), "geometry".into()),
            restore_recorded(&contract, &changed, |_| Ok(())).unwrap(),
        );
        let changed_bytes = prepared(
            &declaration,
            &registry,
            &snapshot,
            &groups,
            "export.Village_Edges",
        )
        .unwrap();
        assert_ne!(first.key(), changed_bytes.key());
        changed
            .files
            .iter_mut()
            .find(|file| file.path == "Village_Edges.npz")
            .unwrap()
            .mode = 0o755;
        groups.insert(
            ("planner".into(), "geometry".into()),
            restore_recorded(&contract, &changed, |_| Ok(())).unwrap(),
        );
        assert_ne!(
            changed_bytes.key(),
            prepared(
                &declaration,
                &registry,
                &snapshot,
                &groups,
                "export.Village_Edges"
            )
            .unwrap()
            .key()
        );
        let mut unknown = declaration.clone();
        let crate::schema::Input::Content {
            source: crate::schema::ContentSource::GroupMember { piece, .. },
            ..
        } = &mut unknown.units[1].inputs[0]
        else {
            panic!()
        };
        *piece = "Missing".into();
        assert!(
            prepared(
                &unknown,
                &registry,
                &snapshot,
                &groups,
                "export.Village_Edges"
            )
            .is_err()
        );
        groups.clear();
        assert!(
            prepared(
                &declaration,
                &registry,
                &snapshot,
                &groups,
                "export.Village_Edges"
            )
            .is_err()
        );
    }
}
