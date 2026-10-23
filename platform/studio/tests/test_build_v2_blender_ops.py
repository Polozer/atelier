"""Portable D2 decoder/ownership/failure checks; no Blender export fidelity claim."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from atelier import mesh_ir, mesh_collision
from atelier.build_v2 import blender_ops as ops
from atelier.build_v2.blender_validate import mesh_facts, validate_export_receipt, FBX_HEADER, decode_mesh_payload
from test_mesh_ir import payload


LIMITS = dict(max_pieces=8, max_manifest_bytes=1024 * 1024,
              max_member_bytes=mesh_ir.MAX_BYTES, max_total_bytes=2 * mesh_ir.MAX_BYTES)


def emit_plan(root, *, whole_collision=False):
    meta, original = mesh_ir.decode(payload())  # independent existing source fixture/decoder
    rows = []
    for index, asset in enumerate(['Whole_A', 'Whole_B']):
        piece = dict(original)
        piece['positions'] = original['positions'] + [index * 2, 0, 0]
        collision_piece = dict(original, positions=np.vstack([original['positions'], [0, 0, 1]]).astype('<f4'))
        collision_piece['colours'] = [(label, domain, kind, np.vstack([values, values[0]]) if domain == 'POINT' else values) for label, domain, kind, values in original['colours']]
        collisions = [mesh_collision.encode(collision_piece, slots=['Material'], matrix=meta['matrix'])] if whole_collision and index == 0 else []
        raw = mesh_ir.encode(piece, key=asset, slots=meta['slots'], matrix=meta['matrix'], options={}, collisions=collisions)
        (root / (asset + '.npz')).write_bytes(raw)
        rows.append(dict(name=asset, payload=asset + '.npz', sha256=hashlib.sha256(raw).hexdigest(),
                         triangles=1, polygons=1, source_faces=[index],
                         min=[index * 2, 0, 0], max=[index * 2 + 1, 1, 0], collision_hulls=len(collisions),
                         slots=['Material'], source_material_indices=[0]))
    value = dict(schema=1, parent='Whole', complete=True, triangle_limit=32768, partition='logical',
                 collision_owner='Whole_A' if whole_collision else None, source_triangles=2, source_polygons=2,
                 source_collision_hulls=int(whole_collision),
                 slots=['Material'], matrix=np.eye(4).tolist(), pieces=rows)
    (root / 'plan.json').write_text(json.dumps(value, sort_keys=True))
    return value


def planned(tmp_path):
    root = tmp_path / 'plan'
    root.mkdir()
    return root, emit_plan(root)


def test_existing_decoder_and_in_job_plan_preserve_complete_corner_and_owner_data(tmp_path):
    root, value = planned(tmp_path)
    assert ops.verify_plan(root, parent='Whole', limits=LIMITS) == value
    raw = (root / 'Whole_A.npz').read_bytes()
    meta, piece = mesh_ir.decode(raw)
    facts = mesh_facts(raw, expected_asset='Whole_A')
    assert facts['uv_channels'] == ['UVMap', 'Piece1']
    assert facts['colour_channels'] == [['Color', 'POINT', 'BYTE_COLOR']]
    assert piece['normals'].tobytes() == np.asarray([[0, -0.0, 1]] * 3, dtype='<f4').tobytes()
    assert facts['slots'] == meta['slots'] == ['Material']
    assert facts['min'] == [0, 0, 0] and facts['max'] == [1, 1, 0]


@pytest.mark.parametrize('fault', ['truncated', 'extra', 'missing', 'alias', 'overlap', 'bound', 'hash'])
def test_producer_refuses_bad_emitted_inventory_and_bindings(tmp_path, fault):
    root, value = planned(tmp_path)
    if fault == 'truncated':
        path = root / 'Whole_A.npz'
        path.write_bytes(path.read_bytes()[:20])
        value['pieces'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif fault == 'extra':
        (root / 'unowned.bin').write_bytes(b'foreign')
    elif fault == 'missing':
        (root / 'Whole_A.npz').unlink()
    elif fault == 'alias':
        value['pieces'][1]['name'] = 'whole_a'
    elif fault == 'overlap':
        value['pieces'][1]['source_faces'] = [0]
    elif fault == 'bound':
        value['pieces'][0]['max'] = [99, 1, 0]
    else:
        value['pieces'][0]['sha256'] = '0' * 64
    (root / 'plan.json').write_text(json.dumps(value))
    with pytest.raises((ValueError, OSError)):
        ops.verify_plan(root, parent='Whole', limits=LIMITS)


def test_plan_links_limits_and_whole_collision_misownership_refuse(tmp_path):
    root, value = planned(tmp_path)
    path = root / 'Whole_A.npz'
    outside = tmp_path / 'outside'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='link'):
        ops.verify_plan(root, parent='Whole', limits=LIMITS)
    path.unlink()
    path.write_bytes(outside.read_bytes())
    with pytest.raises(ValueError, match='count'):
        ops.verify_plan(root, parent='Whole', limits={**LIMITS, 'max_pieces': 1})
    value['collision_owner'] = 'Whole_B'
    value['source_collision_hulls'] = 1
    (root / 'plan.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='collision'):
        ops.verify_plan(root, parent='Whole', limits=LIMITS)
    assert outside.read_bytes() == path.read_bytes()


def test_whole_collision_corner_payload_belongs_to_one_explicit_piece(tmp_path):
    root = tmp_path / 'plan'
    root.mkdir()
    emit_plan(root, whole_collision=True)
    value = ops.verify_plan(root, parent='Whole', limits=LIMITS)
    assert [row['collision_hulls'] for row in value['pieces']] == [1, 0]
    meta, _piece = mesh_ir.decode((root / 'Whole_A.npz').read_bytes())
    collision = mesh_collision.decode(meta['collisions'][0])
    assert collision['normals'].tobytes() == np.asarray([[0, -0.0, 1]] * 3, dtype='<f4').tobytes()


def test_run_plan_uses_only_keyed_owned_output_root_and_checks_before_return(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('output').mkdir()
    context = SimpleNamespace(params=dict(output_root='output/pieces', parent='Whole', plan_limits=LIMITS))
    value = ops.run_plan(context, emit_plan)
    assert [r['name'] for r in value['pieces']] == ['Whole_A', 'Whole_B']
    with pytest.raises(FileExistsError):
        ops.run_plan(context, emit_plan)
    context.params['output_root'] = '../foreign'
    with pytest.raises(ValueError, match='root'):
        ops.run_plan(context, emit_plan)
    assert not (tmp_path.parent / 'foreign').exists()


def test_selected_payload_consumer_refuses_wrong_role_and_malformed_bytes_before_blender(tmp_path, monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail('invalid selected payload reached Blender export')
    monkeypatch.setattr(ops, '_export_mesh', unexpected)
    root, _value = planned(tmp_path)
    (root / 'Whole_B.npz').unlink()
    (root / 'plan.json').unlink()
    context = SimpleNamespace(params=dict(format='fbx', payload_encoding='mesh_ir', payload_role='collision',
                                          payload_member='Whole_A.npz'), inputs={'payload': root},
                              outputs=['Whole_A.fbx', 'export.json'])
    with pytest.raises(ValueError, match='selected'):
        ops.run_export_piece(context)
    context.params['payload_role'] = 'geometry'
    (root / 'Whole_A.npz').write_bytes(b'truncated mesh')
    with pytest.raises((ValueError, OSError)):
        ops.run_export_piece(context)
    assert not (tmp_path / 'export.json').exists()


def test_real_serializer_parse_refusal_prevents_receipt_success(tmp_path, monkeypatch):
    root, _value = planned(tmp_path)
    (root / 'Whole_B.npz').unlink()
    (root / 'plan.json').unlink()
    out = tmp_path / 'output'
    out.mkdir()
    context = SimpleNamespace(params=dict(format='fbx', payload_encoding='mesh_ir', payload_role='geometry',
                                          payload_member='Whole_A.npz'), inputs={'payload': root},
                              outputs=['Whole_A.fbx', 'export.json'], output=lambda name: out / name)
    # Failure injection only: no stand-in serializer success or native-fidelity claim.
    monkeypatch.setattr(ops, '_export_mesh', lambda _a, _m, _p, path, _o: path.write_bytes(b'truncated'))
    def refused(_path, **_kwargs):
        raise ValueError('existing FBX parser refused serialization')
    monkeypatch.setattr(ops, 'verify_emitted_fbx', refused)
    with pytest.raises(ValueError, match='parser refused'):
        ops.run_export_piece(context)
    assert not (out / 'export.json').exists()


def test_receipt_and_binary_framing_check_never_claims_native_fidelity():
    facts = mesh_facts(payload(), expected_asset='Part')
    primary = FBX_HEADER + b'bounded-framing-fixture'
    digest = hashlib.sha256(primary).hexdigest()
    source_digest = hashlib.sha256(payload()).hexdigest()
    receipt = dict(schema=1, asset='Part', primary='Part.fbx', triangles=1, bounds=[[0, 0, 0], [1, 1, 0]],
                   sha256=digest, metadata=dict(geometry_sha256=source_digest, slots=['Material'], polygons=1,
                                               collision_hulls=0, uv_channels=['UVMap', 'Piece1']))
    raw = json.dumps(receipt).encode()
    assert validate_export_receipt(raw, primary, asset='Part', primary_digest=digest,
                                    payload_digest=source_digest, facts=facts) == receipt
    for broken in [b'{}', raw[:-1], raw.replace(b'"Part.fbx"', b'"Other.fbx"')]:
        with pytest.raises(ValueError):
            validate_export_receipt(broken, primary, asset='Part', primary_digest=digest,
                                    payload_digest=source_digest, facts=facts)
    with pytest.raises(ValueError, match='FBX'):
        validate_export_receipt(raw, b'truncated', asset='Part', primary_digest=digest,
                                payload_digest=source_digest, facts=facts)


def test_per_piece_options_cannot_widen_owned_outputs_or_silently_override_selection():
    assert ops.export_options({'axis_forward': '-Y'}, {'axis_up': 'Z'}) == {'axis_forward': '-Y', 'axis_up': 'Z'}
    for options in [{'filepath': 'foreign.fbx'}, {'use_selection': False}, {'bake_anim': True},
                    {'object_types': ['LIGHT']}, {'batch_mode': 'SCENE'}, {'path_mode': 'COPY'}]:
        with pytest.raises(ValueError):
            ops.export_options(options, {})


def test_retained_village_schema2_sample_decodes_complete_mesh_and_owned_collision(tmp_path):
    """Old source sample coverage only; no reconstructed execution or native fidelity claim."""
    root = Path(__file__).resolve().parents[2] / 'build-v2/tests/fixtures/blender'
    raw = (root / 'Village_Edges.npz').read_bytes()
    provenance = json.loads((root / 'Village_Edges.provenance.json').read_bytes())
    assert hashlib.sha256(raw).hexdigest() == provenance['sha256']
    assert len(raw) == provenance['bytes'] == 138217
    meta, piece, facts = decode_mesh_payload(raw)
    assert meta['schema'] == 2
    assert facts['asset'] == 'Village_Edges'
    assert facts['triangles'] == 7860 and facts['polygons'] == 3574
    assert facts['collision_hulls'] == len(meta['collisions']) == 89
    assert facts['slots'] == ['VillagePalette'] and facts['used_material_indices'] == [0]
    assert facts['matrix'] == np.eye(4).tolist()
    assert facts['uv_channels'] == ['UVMap']
    assert facts['colour_channels'] == [['Color', 'POINT', 'FLOAT_COLOR']]
    assert len(piece['normals']) == sum(map(len, piece['faces']))
    assert all(len(hull['vertices']) >= 4 for hull in meta['collisions'])

    output = tmp_path / 'current-whole-group'
    output.mkdir()
    manifest = ops.emit_whole_payload(output, raw, parent='Village_Edges')
    assert ops.verify_plan(output, parent='Village_Edges', limits=LIMITS) == manifest
    assert (output / 'Village_Edges.npz').read_bytes() == raw
    assert manifest['collision_owner'] == 'Village_Edges'
    with pytest.raises(ValueError):
        ops.emit_whole_payload(output, raw, parent='Village_Edges')


def test_plan_refuses_hardlinked_owned_names(tmp_path):
    root, _manifest = planned(tmp_path)
    outside = tmp_path / 'unowned-alias.npz'
    os.link(root / 'Whole_A.npz', outside)
    with pytest.raises(ValueError, match='link'):
        ops.verify_plan(root, parent='Whole', limits=LIMITS)
    assert outside.read_bytes() == (root / 'Whole_A.npz').read_bytes()
