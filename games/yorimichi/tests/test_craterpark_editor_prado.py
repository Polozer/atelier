"""The shipped Prado bowl (editor piece p5): clean copings and edges, no smeared painting, no flicker.

The bowl is meshed by the pinned editor compiler (Node), as the build does, then laid out by editor_generate.piece_mesh
(editor_decal) and editor_coping. No Blender, game or native physics needed.
"""
import copy
import json
from pathlib import Path
import shutil
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, editor_boost as eb, editor_coping as ec, editor_decal as ed, editor_generate as eg  # noqa: E402
from craterpark.v2 import editor_prado as ep, tjunction  # noqa: E402
from craterpark.v2.editor import frontend  # noqa: E402

APP = Path(__file__).resolve().parents[1] / 'tools' / 'craterpark_editor'
PAINTING = (1024, 1536)          # tools/craterpark_textures.py DECALS['prado'] size
TILES = (512, 256)


@pytest.fixture(scope='module')
def prado(tmp_path_factory):
    if shutil.which('node') is None:
        pytest.skip('editor compiler needs Node.js')
    tmp = tmp_path_factory.mktemp('prado')
    doc = eg.select(json.loads((APP / 'shipped.json').read_text()), {'p5'})
    (tmp / 'src').mkdir()
    (tmp / 'src' / 'park.json').write_text(json.dumps(doc))
    snap = frontend.snapshot(tmp / 'src' / 'park.json', tmp / 'snap', terrain_dir=APP / 'data')
    piece, = [p for p in frontend.compile_snapshot(snap, tmp / 'mesh').pieces if p.metadata['id'] == 'p5']
    parts = eg.piece_mesh(piece, eg.DECALS['Prado'])
    copings, rails, _ = ec.build([piece], {}, brick={'p5'})
    return types.SimpleNamespace(piece=piece, parts=parts, copings=copings, rails=rails)


@pytest.fixture(scope='module')
def boosted(prado):
    """The shipped Prado as the build makes it, a boost zone (editor_prado): sunburst walls, a level sun, the letters."""
    piece = copy.copy(prado.piece)
    piece.metadata = {**piece.metadata, 'params': {**(piece.metadata.get('params') or {}), 'boost': 1}}
    V, N, F = np.asarray(piece.mesh.V, 'f8'), np.asarray(piece.mesh.N, 'f8'), eg.orient(piece.mesh.V, piece.mesh.F,
                                                                                         piece.mesh.N)
    side = np.zeros(len(F), bool)
    for c in eg.SIDE_COLOURS:
        side |= (np.abs(piece.colors[F] - c).max(2) < 0.02).all(1)
    ride, _ = ec._classes(piece)
    centre, box = ep.plan(V, N, F, np.where(side, 2, np.where(ride, 0, 1)))
    return types.SimpleNamespace(parts=eg.piece_mesh(piece, eg.DECALS['Prado']), centre=centre, box=box,
                                 floor=(V, N, F, ride & ~side))


def material(parts, name):
    return [m for m in parts if dsl.MATERIALS[int(m.material[0])] == name]


def areas(m):
    t = m.V[m.F]
    return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2


def welded_edges(V, F):
    """(edges (k, 2) of welded points, faces per edge) of the non-degenerate faces."""
    _, ids = np.unique(np.round(np.asarray(V) / 1e-3).astype('i8'), axis=0, return_inverse=True)
    W = ids.ravel()[np.asarray(F)]
    t = np.asarray(V)[np.asarray(F)]
    ok = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) > 1e-9
    E = np.sort(np.concatenate([W[ok][:, [0, 1]], W[ok][:, [1, 2]], W[ok][:, [2, 0]]]), 1)
    return np.unique(E, axis=0, return_counts=True), ok, W


def coplanar_overlaps(meshes, gap=2e-3):
    """Pairs of faces lying in one plane (within `gap`) over each other, from different meshes or one mesh's faces
    that share no corner (a band laid over itself): they flicker."""
    tris = np.concatenate([m.V[m.F][areas(m) > 1e-6] for m in meshes])
    T = tris
    keys = np.round(T / 1e-3).astype('i8')
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    c = T.mean(1)
    cell = {}
    for i, key in enumerate(map(tuple, np.floor(c / 1.).astype(int).tolist())):
        cell.setdefault(key, []).append(i)
    hits = 0
    for i in range(len(T)):
        key = tuple(np.floor(c[i]).astype(int))
        near = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                for j in cell.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                if j != i and not (keys[i][:, None] == keys[j][None]).all(2).any()]
        for j in near:
            if abs(n[i] @ n[j]) < .999 or abs((c[j] - T[i, 0]) @ n[i]) > gap:
                continue
            # c[j] inside triangle i (in i's plane)?
            a, b, d = T[i]
            v0, v1, v2 = b - a, d - a, c[j] - a
            d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
            den = d00 * d11 - d01 * d01
            v = (d11 * d20 - d01 * d21) / den
            w = (d00 * d21 - d01 * d20) / den
            if v > 1e-3 and w > 1e-3 and v + w < 1 - 1e-3:
                hits += 1
    return hits


def test_lip_directions_hold_their_side_on_a_vert_wall():
    """A vert wall's top row has its centroid on the lip line itself: its side was read from that row and flipped from
    one lip point to the next. Every face on the edge votes now (the deck's on the other side)."""
    x = np.arange(0., 20.1, 2.)
    V, F, C = [], [], []
    ride, deck = [0.863, 0.762, 0.674], [0.874, 0.51, 0.322]
    for i, xi in enumerate(x):
        # deck edge and back; the wall's top (its own vertex, as the editor's crease), foot; the floor's far edge
        V += [(xi, 0., 5.), (xi, 0., 8.), (xi, 0., 5.), (xi, -.5, 5.), (xi, -.5, -5.)]
        C += [deck, deck, ride, ride, ride]
        if i:
            a, b = 5 * (i - 1), 5 * i
            F += [(a, a + 1, b + 1), (a, b + 1, b)]                               # deck
            F += [(a + 2, b + 2, b + 3), (a + 2, b + 3, a + 3)]                   # vert wall: centroids on the lip in plan
            F += [(a + 3, b + 3, b + 4), (a + 3, b + 4, a + 4)]                   # floor
    piece = types.SimpleNamespace(mesh=types.SimpleNamespace(V=np.array(V, 'f8'), F=np.array(F)),
                                  colors=np.array(C), metadata={'id': 'v', 'type': 'bowl', 'info': {}})
    (points, into, run), = ec.lip_frames(piece)
    assert np.allclose(points[:, [1, 2]], [0., 5.]) and np.allclose(into, [0., 0., -1.]) and np.allclose(run, 0.)


def test_brick_coping_faces_out_follows_the_lip_and_never_flips(prado):
    for (q, n, run, closed), mesh in zip(ec._join([f for f in ec.lip_frames(prado.piece)]), prado.copings):
        assert np.allclose(np.linalg.norm(n, axis=1), 1.)
        turn = np.degrees(np.arccos(np.clip((n * np.roll(n, 1, 0)).sum(1), -1, 1)))
        assert turn.max() < 25., 'the band twisted over between two lip points'
        assert 0. <= run.min() and run.max() < 1.
    for mesh in prado.copings:
        t = mesh.V[mesh.F]
        fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        assert ((fn * mesh.N[mesh.F].sum(1)).sum(1) > 0).all(), 'a face winds against its normals'
        top = (mesh.N[mesh.F][:, :, 1] > .9).all(1)                                 # the grind top's faces
        assert top.sum() >= 2 * (len(np.unique(mesh.UV[:, 0])) - 1) and (fn[top, 1] > 0).all(), 'its top faces up'
        assert (areas(mesh) > 1e-6).all()
    # the deck behind the bowl's lip is wide; the spine's top is not: its bands meet, no wider than it
    widths = sorted(ec.deck_reach(q, n) for q, n, _, _ in ec._join(ec.lip_frames(prado.piece)))
    assert widths[-1] == ec.BRICK_PROFILE[-1][0] and widths[0] < .31


def test_closed_coping_loops_have_whole_bricks(prado):
    for mesh in prado.copings:
        u = mesh.UV[:, 0]
        assert abs(u.max() - round(u.max())) < 1e-6


def test_deck_meets_the_wall_and_the_outer_skirt_exactly(prado):
    """No open or non-manifold edge on the deck: its lip edge is the wall's top, its outer edge the skirt's top (the
    deep pocket's skirt stood 2 m proud of its deck)."""
    piece = prado.piece
    (E, count), ok, W = welded_edges(piece.mesh.V, piece.mesh.F)
    ride, deck = ec._classes(piece)
    deck_edges = np.unique(np.sort(np.concatenate([W[ok & deck][:, [0, 1]], W[ok & deck][:, [1, 2]],
                                                   W[ok & deck][:, [2, 0]]]), 1), axis=0)
    lookup = {tuple(e): c for e, c in zip(E.tolist(), count.tolist())}
    counts = np.array([lookup[tuple(e)] for e in deck_edges.tolist()])
    assert (counts == 2).all(), f'{(counts == 1).sum()} open and {(counts > 2).sum()} non-manifold deck edges'


def test_prado_surfaces_are_watertight_with_no_slivers(prado):
    mesh = dsl.Mesh.concat(prado.parts)
    assert tjunction.check(mesh)['tjunctions'] == 0
    for m in prado.parts:
        t = m.V[m.F]
        shortest = np.linalg.norm(t - np.roll(t, 1, 1), axis=2).min(1)
        assert (areas(m) > 1e-6).all() and (shortest > 1e-4).all()
        fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        assert ((fn * m.N[m.F].sum(1)).sum(1) > 0).all(), 'a face winds against its normals'


def test_nothing_lies_coplanar_over_anything_else(prado):
    assert coplanar_overlaps(prado.parts + prado.copings) == 0


def test_painting_is_laid_down_the_walls_never_smeared(prado):
    decal, = material(prado.parts, eg.DECALS['Prado'])
    lo, hi = ed.stretch(decal.V, decal.F, decal.UV[decal.F], PAINTING)
    t = decal.V[decal.F]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    flat = np.abs(n[:, 1]) / np.linalg.norm(n, axis=1) > .999
    assert np.allclose(lo[flat], hi[flat], rtol=.02), 'the floor keeps the painting exactly, from above'
    # the plan projection gave vertical faces 0.0 texels/m one way (a smear); laid down the wall they keep over 1
    assert lo.min() > 1. and (hi / lo).max() < 12.
    assert decal.UV.min() >= 0. and decal.UV.max() <= 1.


def test_rim_is_a_tile_band_and_the_deck_is_concrete(prado):
    tile, = material(prado.parts, ed.TILE)
    lo, hi = ed.stretch(tile.V, tile.F, tile.UV[tile.F], TILES)
    assert (hi / lo).max() < 2.5 and np.median(lo) > 200.
    lip = max(ec._join(ec.lip_frames(prado.piece)), key=lambda l: len(l[0]))[0]
    length = np.linalg.norm(np.diff(np.vstack([lip, lip[:1]]), axis=0), axis=1).sum()
    assert abs(areas(tile).sum() / (ed.BAND * length) - 1) < .1, 'the band runs all round the lip, BAND deep'
    deck, = material(prado.parts, dsl.CONCRETE)
    assert (deck.N[:, 1] > .8).all(), 'only the deck is plain concrete'


def test_slice_splits_faces_conformingly():
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], 'f8')
    F = np.array([[0, 1, 2], [0, 2, 3]])
    field = V[:, 0] + .1 * V[:, 2]
    V2, F2, X2, f2 = ed._slice(V, F, field[:, None], field, .5)
    t = V2[F2]
    assert np.isclose(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2, 1.)
    assert all(((f2[f] <= .5 + 1e-9).all() or (f2[f] >= .5 - 1e-9).all()) for f in F2)
    (_, count), _, _ = welded_edges(V2, F2)
    assert count.max() == 2                                    # the cut vertices are shared, no T-junction


def test_boosted_prado_is_its_graphics_cut_in(boosted):
    names = {dsl.MATERIALS[int(m.material[0])] for m in boosted.parts}
    assert set(ep.PAINTS) | {eb.GOLD} <= names and eg.DECALS['Prado'] not in names and ed.TILE not in names
    mesh = dsl.Mesh.concat(boosted.parts)
    assert tjunction.check(mesh)['tjunctions'] == 0
    for m in boosted.parts:
        # the sunburst's straight cuts (editor_boost.paint) leave a few collinear faces where one runs along a row of
        # vertices: no area, nothing drawn, the mesh still conforming
        ok = areas(m) > 1e-6
        assert ok.mean() > .98
        t = m.V[m.F[ok]]
        fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        assert ((fn * m.N[m.F[ok]].sum(1)).sum(1) > 0).all(), 'a face winds against its normals'
    assert len(mesh.F) < 300_000, "the bands' refinement splits only the faces that need it"


def test_boosted_prado_sun_and_letters_lie_on_level_floor(boosted):
    V, N, F, ride = boosted.floor
    flat = ride & (N[F][:, :, 1] > ep.FLAT).all(1)
    P, Y = ep._level(V, F, flat)
    under = np.linalg.norm(P - boosted.centre, axis=1) < eb.SUN_RADIUS
    assert np.ptp(Y[under]) <= ep.LEVEL + 1e-6, 'the sun lies on level floor, not down the slope to the deep end'
    box = boosted.box
    assert box and (box['along'], box['side']) == ep.READ, 'the letters texture lays its concrete for this box'
    assert box['x0'] % ep.TILE == 0 and box['z0'] % ep.TILE == 0, "on the floor's concrete tiles"
    letters, = material(boosted.parts, ep.LETTERS)
    size = np.array(ep.BOX if box['along'] == 0 else ep.BOX[::-1])
    assert np.isclose(areas(letters).sum(), size.prod(), rtol=1e-3), 'the whole box, flat'
    uv = letters.UV[letters.F]
    assert uv.min() > -1e-6 and uv.max() < 1 + 1e-6
    assert np.ptp(letters.V[letters.F][..., 1]) <= ep.LEVEL + 1e-6


def test_box_uv_reads_left_to_right_from_its_side():
    """Facing +z (reader at -z) the reader's right is -x; facing +x it is +z: u grows to the right, v (image rows) toward
    the reader, the baseline (v = 1) on the reader's side, as the r5 render read them."""
    V = np.array([[0., 0., 0.], [32., 0., 0.], [0., 0., 8.]])
    uv = ep.box_uv(V, {'x0': 0., 'z0': 0., 'along': 0, 'side': -1})
    assert np.allclose(uv, [[1, 1], [0, 1], [1, 0]])
    V = np.array([[0., 0., 0.], [0., 0., 32.], [8., 0., 0.]])
    uv = ep.box_uv(V, {'x0': 0., 'z0': 0., 'along': 1, 'side': -1})
    assert np.allclose(uv, [[0, 1], [1, 1], [0, 0]])
