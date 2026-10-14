"""Crater Park v2 core: the data model, the sweep, the seam network, and the Unreal contract of the export."""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'world'))

from craterpark.v2 import dsl, export, generate, layout_m0, network  # noqa: E402
from craterpark.v2.curves import Line, Spline  # noqa: E402
from craterpark.v2.profile import Profile  # noqa: E402
from craterpark.v2.sweep import sweep  # noqa: E402

# r4's own build output (build.json, park.json) for the key-set comparison: CRATERPARK_R4_BUILD names its folder
R4 = Path(os.environ.get('CRATERPARK_R4_BUILD', '/nonexistent'))


def edges_of(F):
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    return e


def assert_closed_and_oriented(mesh):
    P, F = mesh.welded(1e-7)
    e = edges_of(F)
    directed, count = np.unique(e, axis=0, return_counts=True)
    assert count.max() == 1, 'an edge is used twice the same way: inconsistent orientation'
    undirected, ucount = np.unique(np.sort(e, 1), axis=0, return_counts=True)
    assert (ucount == 2).all(), f'{int((ucount != 2).sum())} open or non-manifold edges'
    t = P[F]
    volume = np.einsum('ij,ij->i', t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6
    assert volume > 0, 'faces point inward'
    return volume


def test_tessellation_takes_the_smallest_spacing():
    tess = dsl.RIDING_TESS
    # R 3.5 m at 2 mm chord would allow 3.9 degrees; the 2 degree rule decides
    assert math.degrees(tess.step_angle(3.5)) == pytest.approx(2.0)
    p = Profile([('arc', 3.5, 90)])
    s = p.samples(tess)
    turn = np.degrees(np.diff(p.angle(s)))
    assert turn.max() <= 2.0 + 1e-9 and len(s) - 1 == 45
    # a big radius: the chord rule decides, and the max edge caps straight lines
    assert math.degrees(tess.step_angle(1000.)) < 2.0
    assert np.diff(Profile([('line', 10.)]).samples(tess)).max() <= 4.0


def test_spline_is_parameterised_by_arc_length():
    sp = Spline([(0, 0), (10, 4), (20, -2), (30, 0)])
    t = np.linspace(0, sp.length, 4001)
    steps = np.linalg.norm(np.diff(sp.point(t), axis=0), axis=1)
    assert steps.sum() == pytest.approx(sp.length, rel=1e-6)
    assert np.allclose(steps, steps.mean(), rtol=1e-3)


def test_network_keeps_semantic_samples_and_merges_the_rest():
    net = network.Network(tol=.02)
    net.add('k', Line((0, 0), (10, 0)))
    net.propose('k', [1., 2., 5.], priority=0)
    net.propose('k', [1.01, 4.995], priority=1)
    net.propose('k', [5.005], semantic=True)
    net.propose('k', [5.01], semantic=True)
    t = net.merge()['k']
    assert 1.01 in t and 1. not in t           # the higher priority wins
    assert 5.005 in t and 5.01 in t            # semantic samples are never merged away
    assert 5. not in t and 4.995 not in t
    assert t[0] == 0. and t[-1] == 10. and np.all(np.diff(t) > 0)


def test_sweep_normals_follow_the_faces_and_point_up_on_riding():
    path = Spline([(0, 0), (8, 3), (16, 0)])
    for side in (1, -1):
        m = sweep(path, Profile([('arc', 3.5, 80)]), side=side, feature='qp')
        fn = m.face_normals()
        assert (np.einsum('ij,ij->i', fn, m.N[m.F].mean(1)) > .99).all()
        assert (fn[:, 1] > 0).all()
    kicker = sweep(Line((0, 0), (6, 0)), Profile([('arc', 12., 15.)]), mode='longitudinal', across=3., feature='k')
    assert (kicker.face_normals()[:, 1] > .9).all()
    # profile stations by arc length: the last row sits exactly on the profile's end
    end = Profile([('arc', 12., 15.)]).end
    assert kicker.V[:, 1].max() == pytest.approx(end[1])


def test_one_deck_and_one_quarter_pipe_are_watertight_with_conforming_seams():
    park = layout_m0.park()
    m = park.mesh
    assert_closed_and_oriented(m)
    riding = m.role == dsl.ROLE['riding']
    fn = m.face_normals()
    assert (fn[riding, 1] > -1e-9).all()           # riding faces look up (the vertical extension: sideways)
    assert (np.einsum('ij,ij->i', fn, m.N[m.F].mean(1)) > .9).all()
    # the deck lies exactly at the drop-in's height, under it
    deck = m.material == dsl.MATERIAL[dsl.DECK]
    assert np.allclose(m.V[np.unique(m.F[deck])][:, 1], layout_m0.DROP[1])
    assert len(park.rails) == 1 and np.allclose(park.rails[0].points[:, 1], layout_m0.DROP[1])
    # dihedral along the transition stays within 2 degrees between neighbouring rows
    tran = m.subset(riding & (m.material == dsl.MATERIAL[dsl.CONCRETE]))
    P, F = tran.welded(1e-7)
    fn = tran.face_normals()
    e = np.sort(edges_of(F), 1); owner = np.tile(np.arange(len(F)), 3)
    order = np.lexsort((e[:, 1], e[:, 0])); e, owner = e[order], owner[order]
    same = (e[1:] == e[:-1]).all(1)
    a, b = owner[:-1][same], owner[1:][same]
    angle = np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i', fn[a], fn[b]), -1, 1)))
    assert angle.max() <= 2.0 + 1e-6


def test_geometry_bundle_and_line_npz(tmp_path):
    park = layout_m0.park()
    arrays, index = generate.bundle(park)
    assert index['folded_left_out'] == 0 and index['lines'] == []
    assert all(e['name'].startswith('SM_CP_') for e in index['render'])
    assert all(e['name'].startswith('UC_CP_') for e in index['collision'])
    assert not any(dsl.MATERIALS.index(m) is None for e in index['render'] for m in e['materials'])
    path = export.line_npz(park.mesh, park.lines[0], tmp_path / 'm0.npz')
    z = np.load(path)
    assert z['triangles'].shape[1:] == (3, 3) and len(z['triangles']) == len(z['face_tag']) == len(z['face_feature'])
    assert z['path'].shape[1] == 3 and z['spawn_position'].shape == (3,) and z['entry_speed'].shape == (2,)
    assert 'base' not in set(z['face_role'])


def fake_mesh(out, name, vertices, faces, materials, face_materials, uvs=None, normals=None, ao=None):
    """export_mesh without Blender: the same entry, from the arrays."""
    vertices = np.asarray(vertices, 'f8'); faces = np.asarray(faces)
    used = vertices[np.unique(faces)]
    (Path(out) / 'fbx' / f'{name}.fbx').write_bytes(name.encode())
    return {'name': name, 'fbx': f'fbx/{name}.fbx', 'sha256': export.sha(Path(out) / 'fbx' / f'{name}.fbx'),
            'native_origin': export.origin_of(used).tolist(),
            'bounds': {'minimum': used.min(0).tolist(), 'maximum': used.max(0).tolist()},
            'vertices': len(vertices), 'triangles': len(faces), 'materials': list(materials)}


@pytest.mark.skipif(not (R4 / 'build.json').exists(), reason='set CRATERPARK_R4_BUILD to an r4 build/yorimichi/craterpark folder')
def test_export_keeps_r4s_build_and_park_json_key_sets(tmp_path):
    from craterpark import placement
    park_, module = generate.compile_park('layout_m0')
    lines = generate.line_spawns(park_, module)
    arrays, _ = generate.bundle(park_, lines)
    np.savez(tmp_path / 'g.npz', **arrays)
    (tmp_path / 'fbx').mkdir()
    (tmp_path / 'fbx' / 'SM_CP_mesh_0000_000.fbx').write_bytes(b'stale')
    build, park = export.write(tmp_path, placement.SOURCE, np.load(tmp_path / 'g.npz'), placement, fake_mesh)
    r4 = json.loads((R4 / 'build.json').read_text()); r4park = json.loads((R4 / 'park.json').read_text())
    assert set(build) == set(r4)
    for kind in ('render', 'collision'):
        want = {tuple(sorted(e)) for e in r4[kind]}
        assert {tuple(sorted(e)) for e in build[kind]} == want
        assert build[kind]
    assert set(r4park) <= set(park) <= set(r4park) | {'lines', 'trees'}
    assert [ln['key'] for ln in park['lines']] == ['m0'] and park['spawn'] == park['lines'][0]['spawn']
    # the smoke's start stands on the r4 drop-in, facing r4's way: the same spawn as r4
    assert np.allclose(park['spawn']['location_cm'], r4park['spawn']['location_cm'], atol=.01)
    assert park['spawn']['yaw_deg'] == pytest.approx((r4park['spawn']['yaw_deg'] + 180) % 360 - 180)
    for kind in ('render', 'collision'):
        assert {tuple(sorted(e)) for e in park[kind]} == {tuple(sorted(e)) for e in r4park[kind]}
    assert {tuple(sorted(e)) for e in park['rails']} == {tuple(sorted(e)) for e in r4park['rails']}
    assert set(park['spawn']) == set(r4park['spawn'])
    assert park['location_cm'] == r4park['location_cm'] and park['yaw_deg'] == r4park['yaw_deg']
    assert park['mesh_root'] == r4park['mesh_root'] and park['name'] == r4park['name']
    assert build['scene_sha256'] == r4['scene_sha256'] and park['rails'] and park['rails_required']
    known = set(dsl.MATERIALS) | {'M_Collision'}
    assert all(set(e['materials']) <= known for e in build['render'] + build['collision'])
    assert all(e['name'].startswith('SM_CP_') for e in build['render'])
    assert all(e['name'].startswith('UC_CP_') for e in build['collision'])
    assert (tmp_path / 'fbx' / 'SM_CP_ImportSeed.fbx').exists()
    assert not (tmp_path / 'fbx' / 'SM_CP_mesh_0000_000.fbx').exists()
    assert json.loads((tmp_path / 'build.json').read_text()) == build


def test_fill_handles_a_concave_outline_without_new_vertices():
    L = np.array([[0, 0, 0], [4, 0, 0], [4, 0, 1], [1, 0, 1], [1, 0, 4], [0, 0, 4]], float)
    F = network.fill(L, [0, 1, 0])
    t = L[F]; n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    assert len(F) == 4 and (n[:, 1] > 0).all() and np.linalg.norm(n, axis=1).sum() / 2 == pytest.approx(7.)


def test_regions_on_one_network_key_share_their_seam_vertices():
    path = Spline([(0, 0), (6, 2), (12, 0)])
    net = network.Network(); net.add('k', path)
    a_prof = Profile([('arc', 3.5, 60)]); b_prof = Profile([('line', 2.)], start=tuple(a_prof.end))
    net.propose('k', path.samples(dsl.RIDING_TESS, offsets=(0., 6.)), priority=1)
    net.propose('k', path.samples(dsl.SIDE_TESS, offsets=(0., 6.)))
    t = net.merge()['k']
    a = sweep(path, a_prof, t=t, feature='a'); b = sweep(path, b_prof, t=t, feature='b')
    assert np.array_equal(a.V[a.seams['a.right']], b.V[b.seams['b.left']])
