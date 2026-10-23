"""Carriage service source boundaries preserve exact local node data before serialization."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
from types import ModuleType

import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
from train import carriage_mesh as M, carriage_source as S  # noqa: E402


def fixture():
    positions = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    normals = struct.pack('<9f', 0, 0, 1, 0, 0, 1, 0, 0, 1)
    indices = struct.pack('<3H', 0, 1, 2)
    binary = positions + normals + indices
    doc = dict(asset=dict(version='2.0'), scene=0, scenes=[dict(name='Scene', nodes=[0])],
        nodes=[dict(name='Vehicle', children=[1, 2], extras=dict(frame='original')),
               dict(name='Body', mesh=0), dict(name='Door_hinge', translation=[10, 0, 0], children=[3]),
               dict(name='Door_glass', mesh=0, extras=dict(pivot='local'))],
        materials=[dict(name='M_BT_Steel', pbrMetallicRoughness=dict(metallicFactor=1))],
        meshes=[dict(name='Linked', primitives=[dict(attributes=dict(POSITION=0, NORMAL=1), indices=2, material=0)])],
        accessors=[dict(bufferView=0, componentType=5126, count=3, type='VEC3'),
                   dict(bufferView=1, componentType=5126, count=3, type='VEC3'),
                   dict(bufferView=2, componentType=5123, count=3, type='SCALAR')],
        bufferViews=[dict(buffer=0, byteOffset=0, byteLength=36), dict(buffer=0, byteOffset=36, byteLength=36),
                     dict(buffer=0, byteOffset=72, byteLength=6)], buffers=[dict(byteLength=len(binary))])
    return doc, binary


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_every_linked_instance_counts_and_original_local_frame_drives_bounds():
    doc, binary = fixture()
    info = M.geometry(doc, binary)
    assert info == dict(triangles=2, bounds=[[0., 0., 0.], [11., 1., 0.]], slots=['M_BT_Steel'])
    doc['nodes'][0]['children'].append(1)
    with pytest.raises(ValueError, match='repeated'): M.geometry(doc, binary)


def test_raw_source_packet_precedes_any_glb_serialization_and_is_deterministic():
    doc, binary = fixture()
    source = S.encode('SM_BT_Test_LOD0', doc, binary)
    assert source == S.encode('SM_BT_Test_LOD0', doc, binary)
    assert not source.startswith(b'glTF')
    value, actual = S.decode(source, key='SM_BT_Test_LOD0')
    assert value['document'] == doc and actual == binary
    with pytest.raises(ValueError, match='changed'): S.decode(source[:-1] + bytes([source[-1] ^ 1]))


def test_body_and_leaf_subsets_retain_only_consumed_nodes_materials_and_buffers():
    doc, binary = fixture()
    body, door = S.subsets(doc, binary, mesh='SM_BT_Test', level=0, leaves={'Door_hinge': 'SM_BTD_Test_hinge'})
    assert body[0] == 'SM_BT_Test_LOD0' and door[0] == 'SM_BTD_Test_hinge'
    assert [n['name'] for n in body[1]['nodes']] == ['Vehicle', 'Body']
    assert [n['name'] for n in door[1]['nodes']] == ['Vehicle', 'Door_hinge', 'Door_glass']
    assert door[1]['nodes'][1]['translation'] == [10, 0, 0]
    assert door[1]['nodes'][2]['extras'] == dict(pivot='local')
    before = S.encode(door[0], door[1], door[2])
    changed = copy.deepcopy(doc)
    changed['materials'].append(dict(name='Unconsumed sibling'))
    changed['meshes'].append(copy.deepcopy(changed['meshes'][0]))
    changed['meshes'][1]['primitives'][0]['material'] = 1
    changed['nodes'][1]['mesh'] = 1
    _, revised = S.subsets(changed, binary, mesh='SM_BT_Test', level=0, leaves={'Door_hinge': 'SM_BTD_Test_hinge'})
    assert S.encode(revised[0], revised[1], revised[2]) == before
    assert S.subsets(doc, binary, mesh='SM_BT_Test', level=2, leaves={}) == [('SM_BT_Test_LOD2', doc, binary)]


@pytest.mark.parametrize('change', [
    lambda d: d['accessors'][0].update(sparse={}),
    lambda d: d['nodes'][0].update(children=[0]),
    lambda d: d['meshes'][0]['primitives'][0].update(targets=[]),
    lambda d: d['accessors'][2].update(count=300000),
    lambda d: d['nodes'][2].update(scale=[0, 1, 1]),
    lambda d: d.update(images=[dict(uri='external.png')]),
])
def test_incomplete_or_unsupported_node_corner_and_texture_policy_refuses(change):
    doc, binary = fixture(); change(doc)
    with pytest.raises(ValueError): M.geometry(doc, binary)


def test_instance_budget_cannot_be_hidden_by_shared_mesh_data():
    doc, binary = fixture()
    doc['nodes'] = [dict(name='Root', children=list(range(1, 32770)))] + [dict(mesh=0) for _ in range(32769)]
    with pytest.raises(ValueError, match='oversized'): S.encode('SM_BT_TooBig_LOD0', doc, binary)


def test_selected_plan_and_export_preserve_current_runtime_subset_bytes(tmp_path):
    from atelier.export_manifest import validate
    doc, binary = fixture()
    original = tmp_path / 'original.glb'; S.G.write(original, doc, binary)
    source = tmp_path / 'SM_BT_Test_LOD0.source'; source.write_bytes(S.encode(source.stem, doc, binary))
    plan = tmp_path / 'plan'
    load('carriage_plan_test', GAME / 'world/train/plan_carriage.py').main([
        '--source', str(source), '--asset', source.stem, '--output', str(plan)])
    value = json.loads((plan / 'plan.json').read_text())
    assert value['source_triangles'] == 2 and len(value['pieces']) == 1
    product = tmp_path / 'product'
    load('carriage_export_test', GAME / 'world/train/export_carriage.py').main([
        '--input', str(plan / (source.stem + '.glbdata')), '--output', str(product), '--format', '.glb'])
    assert (product / (source.stem + '.glb')).read_bytes() == original.read_bytes()
    assert validate(product, key=source.stem)['triangles'] == 2


def _fake_save_gltf():
    sort_order = ['asset', 'scene', 'scenes', 'nodes', 'materials', 'meshes', 'accessors', 'bufferViews', 'buffers']
    return sort_order


def test_source_writer_restores_original_on_success_and_failure(monkeypatch):
    names = ['io_scene_gltf2', 'io_scene_gltf2.blender', 'io_scene_gltf2.blender.exp',
             'io_scene_gltf2.blender.exp.export', 'io_scene_gltf2.io', 'io_scene_gltf2.io.exp',
             'io_scene_gltf2.io.exp.export', 'io_scene_gltf2.blender.com', 'io_scene_gltf2.blender.com.json_util']
    modules = {name: ModuleType(name) for name in names}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
        parent, _, child = name.rpartition('.')
        if parent in modules: setattr(modules[parent], child, module)
    exporter = modules['io_scene_gltf2.blender.exp.export']
    def original(json, buffer, export_settings): pytest.fail('combined GLB serialized')
    exporter.__write_file = original
    writer = modules['io_scene_gltf2.io.exp.export']
    writer.save_gltf = _fake_save_gltf
    exporter.__file__ = writer.__file__ = __file__
    import hashlib
    expected = {key: hashlib.sha256(Path(__file__).read_bytes()).hexdigest() for key in ('exporter', 'writer')}
    modules['io_scene_gltf2.blender.com.json_util'].BlenderJSONEncoder = json.JSONEncoder
    doc, binary = fixture(); received = []
    with S.capture_writer(lambda d, b, p: received.append((d, b, p)), expected=expected):
        exporter.__write_file(doc, binary, dict(gltf_format='GLB', gltf_filepath='SM_BT_Test_LOD0.glb'))
    assert exporter.__write_file is original and received[0][:2] == (doc, binary)
    with pytest.raises(RuntimeError):
        with S.capture_writer(lambda *args: None, expected=expected): raise RuntimeError('constructor failure')
    assert exporter.__write_file is original

    with pytest.raises(ValueError, match='prepared identity'):
        with S.capture_writer(lambda *args: pytest.fail('unbound addon accepted'),
                              expected=dict(expected, exporter='0' * 64)):
            pytest.fail('unbound addon accepted')
    assert exporter.__write_file is original


def test_actual_atlas_fixture_requires_unchanged_constructor_prefix_and_helpers(tmp_path):
    control = load('carriage_immutable_prefix_test', GAME / 'tools/train_carriage_source_control.py')
    original = tmp_path / 'original.py'; current = tmp_path / 'current.py'
    original.write_text('def helper():\n    return 7\ndef build(coach, images):\n    data = helper()\n    files = {}\n    return data\n')
    current.write_text('def helper():\n    return 7\ndef runtime_placements(coach):\n    return {}\n'
        'def build(coach, images, *, source_sink=None):\n    data = helper()\n'
        '    if source_sink is not None:\n        return source_sink(data)\n    files = {}\n    return data\n')
    control.same_original_constructor_prefix(original, current)
    text = current.read_text(); current.write_text(text.replace('data = helper()', 'data = 99'))
    with pytest.raises(ValueError, match='constructor source changed'):
        control.same_original_constructor_prefix(original, current)
    current.write_text(text.replace('return 7', 'return 8'))
    with pytest.raises(ValueError, match='helper source changed'):
        control.same_original_constructor_prefix(original, current)
