"""Selected placement never borrows the old block or a stale geometry artifact."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'world'))
from craterpark import placement  # noqa: E402
from craterpark.v2 import dsl, v4_config, v4_placement  # noqa: E402
from hidamari import mountains  # noqa: E402


@pytest.fixture
def selected(tmp_path, monkeypatch):
    path = tmp_path / 'design.json'
    doc = {'frame': {'lift': 680}, 'ground': {'dig': {'kind': 'depth', 'DEPTH': 65}},
           'site': {'buildable': [[0, 0], [20, 0], [20, 20], [0, 20]]},
           'tower': {'deck_y': 125, 'roll_ins': [{'pos': [10, 10], 'heading': 0}]}}
    path.write_text(json.dumps(doc))
    monkeypatch.setenv(v4_config.SWITCH, str(path))
    return path, doc


def test_selected_missing_design_cannot_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv(v4_config.SWITCH, str(tmp_path / 'missing.json'))
    monkeypatch.setattr(placement, '_legacy_ground_triangles', lambda: pytest.fail('legacy geometry called'))
    monkeypatch.setattr(v4_placement, 'geometry_path', lambda: tmp_path / 'missing-geometry.npz')
    with pytest.raises(OSError):
        placement.ground_triangles()
    with pytest.raises(OSError):
        placement.drop_in()
    with pytest.raises(OSError):
        placement.contains(0, 0)


def test_depth_changes_floor_without_changing_crest(selected, monkeypatch):
    assert mountains.caldera_floor() == pytest.approx(float(mountains.apron_height(mountains.VOLCANO[1])) + mountains.CREST - 65)
    monkeypatch.delenv(v4_config.SWITCH)
    assert mountains.caldera_floor() == pytest.approx(float(mountains.apron_height(mountains.VOLCANO[1])) + mountains.CREST - mountains.DEPTH)


def test_selected_envelope_and_spawn_use_native_design(selected, monkeypatch):
    monkeypatch.setattr(placement, 'native_to_island', lambda q: np.asarray(q)[..., [0, 2, 1]])
    assert placement.contains([10, 21], [10, 10]).tolist() == [True, False]
    assert placement.contains([10, 21], [10, 10], margin=2).tolist() == [True, True]
    monkeypatch.setattr(v4_placement, 'identity', lambda: ('fixture', 1, 1, 'sha'))
    monkeypatch.setattr(v4_placement, '_geometry', lambda *a: (None, None, {'lines': [
        {'spawn': {'location_cm': [1000, -1000, 12500], 'yaw_deg': 0}}]}))
    ground, camera = placement.drop_in()
    np.testing.assert_allclose(ground, [10, 10, 125])
    np.testing.assert_allclose(camera, [2, 10, 131])


def test_terrain_and_snow_cache_keys_include_selected_geometry(monkeypatch):
    key = ['one']
    calls = []
    monkeypatch.setattr(mountains, '_park_identity', lambda: tuple(key))
    monkeypatch.setattr(mountains, '_surface_grid', lambda sampler, identity: calls.append(('surface', identity)))
    monkeypatch.setattr(mountains, '_snow_grid', lambda sampler, identity: calls.append(('snow', identity)))
    sampler = lambda x,y: 0
    mountains.surface_grid(sampler)
    mountains.snow_grid(sampler)
    key[0] = 'two'
    mountains.surface_grid(sampler)
    mountains.snow_grid(sampler)
    assert calls == [('surface', ('one',)), ('snow', ('one',)), ('surface', ('two',)), ('snow', ('two',))]


def test_current_geometry_required_and_cache_invalidates(selected, monkeypatch, tmp_path):
    path, doc = selected
    artifact = tmp_path / 'geometry.npz'
    monkeypatch.setattr(v4_placement, 'geometry_path', lambda: artifact)
    monkeypatch.setattr(placement, 'native_to_island', lambda q: np.asarray(q))
    mesh = dsl.Mesh(np.array([[0., 0, 0], [0, 0, 1], [1, 0, 0], [1, 2, 0]]),
                    np.array([[0, 1, 2], [1, 2, 3]]),
                    role=np.array([dsl.ROLE[dsl.GROUND], dsl.ROLE[dsl.RIDING]]))
    index = {'render': [{}], 'v4': v4_config.provenance(), 'accepted': True,
             'validation': {'ran': True, 'ok': True, 'supports': {'ran': True, 'ok': True}}}
    np.savez(artifact, index=np.asarray(json.dumps(index)), **mesh.to_arrays('r0_'))
    assert placement.ground_triangles().shape == (1, 3, 3)
    assert placement.piece_triangles().shape == (1, 3, 3)
    # Replacing same-sized data and preserving mtime still invalidates caches.
    import os
    st=artifact.stat()
    mesh.V[:,1]+=1.
    np.savez(artifact,index=np.asarray(json.dumps(index)),**mesh.to_arrays('r0_'))
    os.utime(artifact,ns=(st.st_atime_ns,st.st_mtime_ns))
    assert artifact.stat().st_size==st.st_size
    np.testing.assert_allclose(placement.ground_triangles()[0,:,1],1.)
    index['accepted']=False
    np.savez(artifact,index=np.asarray(json.dumps(index)),**mesh.to_arrays('r0_'))
    with pytest.raises(ValueError,match='accepted structural and support'):
        placement.ground_triangles()
    index['accepted']=True
    index['validation']['supports']['ok']=False
    np.savez(artifact,index=np.asarray(json.dumps(index)),**mesh.to_arrays('r0_'))
    with pytest.raises(ValueError,match='accepted structural and support'):
        placement.ground_triangles()
    doc['tower']['deck_y'] = 126
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='current design provenance'):
        placement.ground_triangles()


def test_terrain_stamp_receives_distinct_selected_identity(selected, monkeypatch):
    sentinel = ('new-geometry', 1, 2, 'new-source')
    monkeypatch.setattr(v4_placement, 'identity', lambda: sentinel)
    calls = []
    def stamp(natural, identity):
        calls.append(identity)
        q = np.ones((2, 2))
        return 0., 0., 1., q.astype(bool), q, q*0, q*12
    monkeypatch.setattr(placement, '_stamp', stamp)
    assert placement.terrain(.5, .5, 99., lambda x,y: 99.) == pytest.approx(12.)
    assert calls == [sentinel]
    monkeypatch.delenv(v4_config.SWITCH)
    placement.terrain(.5, .5, 99., lambda x,y: 99.)
    assert calls[-1] is None


def test_unsupported_depth_and_changed_frame_fail(selected):
    path, doc = selected
    doc['ground']['dig']['kind'] = 'dish'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='kind=depth'):
        mountains.caldera_floor()
    doc['frame']['lift'] = 700
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='coordinate frame'):
        placement.drop_in()
