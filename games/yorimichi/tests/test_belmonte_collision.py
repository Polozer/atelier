"""Belmonte's buildings collide as drawn: no walker gets inside a wall or an unfurnished interior.

A playtest fell into a building while skating: the committed hulls miss upper storeys, roofs, chimneys and the
grandstand tiers. world.belmonte now generates each building's collision (belmonte/collision.py) and fails its
build if any building stays open; these fast checks hold the mechanism to the rule on the worst offenders at a
coarse grid. tools/belmonte_collision_audit.py audits all 66 buildings at the build's grid.
"""
from functools import lru_cache
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from belmonte import build, collision, source  # noqa: E402

BUILDINGS = collision.buildings()


COARSE = .4
WORST = ['SM_BM_BHip_SecondStand', 'SM_BM_BT_blk_17', 'SM_BM_BT_blk_10', 'SM_BM_BHip_Stables', 'SM_BM_BE_4_Stables',
         'SM_BM_BH_Porta_SE']


@lru_cache(maxsize=1)
def generated(name, h=COARSE):
    transform, entries = BUILDINGS[name]
    b = collision.load(name, transform, entries, h=h)
    return b, collision.generate(b)


def test_every_drawn_building_is_covered():
    names = {e['name'] for _, entries in BUILDINGS.values() for e in entries}
    houses = {m['name'] for m in source.manifest()['meshes']
              if m['name'].startswith(('SM_BM_BT_blk_', 'SM_BM_BVV_Farm_')) or m['name'].endswith(('_Villa', '_Stables'))}
    assert houses <= names
    assert len(BUILDINGS) == 66
    assert {'SM_BM_BH_Osteria_Taproom', 'SM_BM_BHip_SalonHall'} <= names


@pytest.mark.parametrize('name', WORST)
def test_walker_cannot_enter_walls_or_unfurnished_interiors(name):
    b, shell = generated(name)
    result = collision.audit(b, shell.faces, stats=False)
    assert result.intrusion_m3 == 0, (name, result.worst)
    assert result.deepest_m == 0, (name, result.worst)
    assert result.uncovered_wall <= collision.MAX_UNCOVERED, (name, result.row())
    assert result.uncovered_roof <= collision.MAX_UNCOVERED, (name, result.row())
    # Far cheaper than drawing it: the shell is the hulls, the simplified surface they miss and the plugs.
    assert result.collision_triangles < sum(len(f) for f in b.drawn.values()) / 3, (name, result.collision_triangles)
    # What is added to the hulls keeps to what is drawn: none of it stands in the open air off the drawn walls
    # (plugs sit in the openings, so a voxel of rasterisation either side of either is allowed).
    hulls = collision.committed([e for e in b.entries if 'collision' in e])
    added = np.concatenate([shell.faces[k][len(v):] for k, v in hulls.items()])
    assert not (b.rasterise(added) & b.clear()).any(), name


@pytest.mark.parametrize('name', ['SM_BM_BHip_SecondStand', 'SM_BM_BT_blk_17', 'SM_BM_BH_Porta_SE'])
def test_the_check_fails_on_the_committed_hulls(name):
    """The original defect: the source scene's hulls leave drawn storeys, roofs and stand tiers open."""
    b, _ = generated(name)
    entries = b.entries
    result = collision.audit(b, collision.committed(entries))
    assert result.intrusion_m3 > 1. or result.uncovered_roof > .05, result.row()
    # The hulls themselves are closed convex solids; what they lack is coverage.
    assert result.open_edges == 0 and result.thinnest_m >= .5


@pytest.mark.parametrize('key,name', [('belmonte_osteria', 'SM_BM_BH_Osteria'), ('belmonte_salon', 'SM_BM_BHip_Salon')])
def test_furnished_interiors_stay_open_to_walk_in(key, name):
    b, shell = generated(name, collision.VOXEL)
    zone = next(z for z in build.map_zones(0.) if z['key'] == key)
    transform = b.transform
    # The map stop's floor point, in the building's local frame.
    world = np.array([zone['x'], zone['y'], zone['z']]) - build.L.ORIGIN
    native = world * [100., -100., 100.] - transform['translation_cm']
    q = np.asarray(transform['rotation_xyzw'], float) * [-1., -1., -1., 1.]
    local = collision.planting.rotate(q, native) / transform['scale'] / [100., -100., 100.]
    occupied = b.rasterise(np.concatenate(list(shell.faces.values())))
    reach = b.reachable(occupied)
    i = b.index(local[None] + [0., 0., .9])[0]
    assert reach[i[0], i[1], i[2]], (key, local)


def test_collision_glb_round_trips(tmp_path):
    _, shell = generated('SM_BM_BH_Porta_SE', collision.VOXEL)
    faces = shell.faces['SM_BM_BH_Porta_SE']
    path = tmp_path / 'SM_BM_BH_Porta_SE_Collision.glb'
    collision.write_glb(path, faces)
    np.testing.assert_allclose(source.triangles(path), faces, atol=1e-4)
    # Every face outward, as the drawn meshes are: the committed hulls are wound into their solids and are turned, and
    # each closed plug is built outward. The skate surface keeps a face's side and rides through one taken from behind.
    name = 'SM_BM_BE_4_Stables'
    b, stables = generated(name)
    owner = next(e['name'] for e in b.entries if 'collision' in e)
    hulls = collision.committed(b.entries)[owner]
    assert volume(hulls) < 0 < volume(stables.faces[owner][:len(hulls)])
    plugs = stables.faces[owner][-stables.plug_triangles:]
    assert stables.plug_triangles and all(volume(piece) > 0 for piece in pieces(plugs))


def volume(faces):
    return np.einsum('ij,ij->i', faces[:, 0], np.cross(faces[:, 1], faces[:, 2])).sum() / 6


def pieces(faces):
    """The edge-connected pieces of a triangle soup."""
    _, vertex = np.unique(faces.reshape(-1, 3).round(4), axis=0, return_inverse=True)
    vertex = vertex.reshape(-1, 3)
    label = np.arange(vertex.max() + 1)
    while True:
        low = label[vertex].min(1)
        merged = label.copy()
        for k in range(3):
            np.minimum.at(merged, vertex[:, k], low)
        merged = merged[merged]
        if (merged == label).all():
            break
        label = merged
    piece = label[vertex[:, 0]]
    return [faces[piece == p] for p in np.unique(piece)]


def test_build_writes_generated_shells_for_buildings_only(tmp_path, monkeypatch):
    data = source.manifest()
    keep = 'SM_BM_BH_Porta_SE'
    small = {k: v for k, v in BUILDINGS.items() if k == keep}
    monkeypatch.setattr(build, 'OUT', tmp_path)
    monkeypatch.setattr(collision, 'buildings', lambda _data=None: small)
    (tmp_path / 'glb').mkdir()
    meshes = [dict(m) for m in data['meshes'] if m['name'] in (keep, 'SM_BM_BP_Bench')]
    report = build.building_collision(data, meshes)
    entry = next(m for m in meshes if m['name'] == keep)
    assert entry['collision']['generated'] and entry['collision']['path'] == f'glb/{keep}_Collision.glb'
    assert source.sha(tmp_path / entry['collision']['path']) == entry['collision']['sha256']
    assert report[keep]['plugs'] >= 0 and report[keep]['reachable_m3'] == 0 and report[keep]['triangles'][keep] > 0
    bench = next(m for m in meshes if m['name'] == 'SM_BM_BP_Bench')
    assert bench['collision']['path'].startswith('meshes/')     # untouched here; main() turns it outward
    hulls = source.LIBRARY / bench['collision']['path']
    turned = build.outward_hulls(hulls)
    assert turned['path'] == f'glb/{hulls.name}' and turned['source'] == bench['collision']['path']
    faces = source.triangles(tmp_path / turned['path'])
    assert volume(source.triangles(hulls)) < 0 < volume(faces) and len(faces) == len(source.triangles(hulls))
