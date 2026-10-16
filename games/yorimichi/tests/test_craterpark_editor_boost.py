"""The boost zones' Giant sunburst (world/regions/craterpark/v2/editor_boost.py): every piece the owner gave a boost
(params.boost > 0) is painted, and nothing else is.

The shipped park's boosted line is meshed by the pinned editor compiler (Node), as the build does, then laid out by
editor_generate.piece_mesh and editor_coping.build. No Blender, game or native physics needed.
"""
import json
import math
from pathlib import Path
import shutil
import sys
import types

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'tools'))
from craterpark.v2 import dsl, editor_boost as eb, editor_coping as ec, editor_generate as eg, tjunction  # noqa: E402
from craterpark.v2.editor import frontend  # noqa: E402

APP = GAME / 'tools' / 'craterpark_editor'
PAINTED = {dsl.MATERIAL[m] for m in eb.PAINTS}


def boosted_ids(doc):
    return {p['id'] for p in doc['pieces'] if ((p.get('params') or {}).get('boost') or 0) > 0}


@pytest.fixture(scope='module')
def shipped(tmp_path_factory):
    """The shipped park's lines that hold a boost zone, compiled; each piece's riding parts, plain and painted."""
    if shutil.which('node') is None:
        pytest.skip('editor compiler needs Node.js')
    doc = json.loads((APP / 'shipped.json').read_text())
    boosts = boosted_ids(doc)
    lines = {p['line'] for p in doc['pieces'] if p['id'] in boosts}
    chosen = eg.select(doc, lines)
    tmp = tmp_path_factory.mktemp('boost')
    (tmp / 'src').mkdir()
    (tmp / 'src' / 'park.json').write_text(json.dumps(chosen))
    snap = frontend.snapshot(tmp / 'src' / 'park.json', tmp / 'snap', terrain_dir=APP / 'data')
    pieces = frontend.compile_snapshot(snap, tmp / 'mesh', timeout=600).pieces
    params = {p['id']: p.get('params') or {} for p in chosen['pieces']}
    for piece in pieces:
        piece.metadata['params'] = params[piece.metadata['id']]
    decals = {p['id'] for p in chosen['pieces'] for key in eg.DECALS
              if p['type'] == 'bowl' and key in (p.get('name') or '')}
    parts = {p.metadata['id']: eg.piece_mesh(p) for p in pieces if p.metadata['id'] not in decals}
    return types.SimpleNamespace(doc=doc, boosts=boosts, pieces={p.metadata['id']: p for p in pieces}, parts=parts)


def plain(piece):
    """The piece's parts as they were before the boost look (its boost set to 0)."""
    meta = dict(piece.metadata, params=dict(piece.metadata['params'], boost=0))
    return eg.piece_mesh(types.SimpleNamespace(mesh=piece.mesh, colors=piece.colors, metadata=meta))


def test_the_shipped_boost_zones_are_the_flow_bowl_and_both_u_turns(shipped):
    assert shipped.boosts == {'p45', 'p47', 'p51'}
    assert all(eb.boosted(shipped.pieces[i]) for i in shipped.boosts)


def test_every_boost_piece_is_painted_and_no_other_piece_is(shipped):
    for pid, parts in shipped.parts.items():
        used = {int(m) for part in parts for m in np.unique(part.material)}
        if pid in shipped.boosts:
            assert {dsl.MATERIAL[m] for m in (eb.MAGENTA, eb.YELLOW, eb.SUN, eb.GOLD)} <= used, pid
            painted = [p for p in parts if int(p.material[0]) in PAINTED]
            assert all((p.role == dsl.ROLE[dsl.RIDING]).all() for p in painted), 'only the riding faces are painted'
        else:
            assert not used & PAINTED, f'{pid} is not a boost zone but is painted'


def test_the_paint_keeps_the_surface_its_decks_and_its_sides(shipped):
    """The cut moves no surface: the same area per role, the decks' wood and the sides untouched in area, and the
    piece still conforms within itself (no T-junction)."""
    for pid in shipped.boosts:
        piece = shipped.pieces[pid]
        before, after = dsl.Mesh.concat(plain(piece)), dsl.Mesh.concat(shipped.parts[pid])
        for role in (dsl.RIDING, dsl.SIDE):
            a0 = before.where(role=role).areas().sum()
            assert abs(after.where(role=role).areas().sum() - a0) < 1e-6 * a0, (pid, role)
        assert tjunction.check(after)['tjunctions'] == 0, pid
        ride, deck = ec._classes(piece)
        F = piece.mesh.F
        t = piece.mesh.V[F[deck]]
        deck_area = .5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum()
        wood = after.where(role=dsl.RIDING, material=eg.WOOD).areas().sum()
        assert abs(wood - deck_area) < 1e-6 * deck_area, f'{pid}: the deck stays wood, nothing else does'


def _wedge(sun, angle):
    return math.floor(((angle - sun['start']) % (2 * math.pi)) / sun['width'])


def test_rays_are_exact_wedges_from_the_sun_alternating_magenta_and_yellow(shipped):
    for pid in shipped.boosts:
        piece, mesh = shipped.pieces[pid], dsl.Mesh.concat(shipped.parts[pid])
        side = np.zeros(len(piece.mesh.F), bool)
        ride, _ = ec._classes(piece)
        sun = eb.layout(piece, piece.mesh.V, piece.mesh.N, eg.orient(piece.mesh.V, piece.mesh.F, piece.mesh.N), ride & ~side)
        C = sun['centre']
        seen = {}
        for name in (eb.MAGENTA, eb.YELLOW):
            m = mesh.where(material=name)
            t = m.V[m.F][:, :, [0, 2]] - C
            k = np.array([_wedge(sun, a) for a in np.arctan2(*(t.mean(1) - 0).T[::-1])])
            assert (k % 2 == (0 if name == eb.MAGENTA else 1)).all(), (pid, name)
            # every corner of a ray's face lies in its own wedge (on its edges within the cut's snap)
            for edge in (0, 1):
                a = sun['start'] + (k + edge) * sun['width']
                d = np.stack([np.cos(a), np.sin(a)], 1)
                signed = t[:, :, 0] * d[:, None, 1] - t[:, :, 1] * d[:, None, 0]     # r sin(edge - angle)
                outside = signed if edge == 0 else -signed
                assert outside.max() <= eb.SNAP + 1e-6, (pid, name, 'a ray face crosses its wedge edge')
            assert (np.linalg.norm(t, axis=2) >= sun['radius'] - eb.SNAP - 1e-6).all(), (pid, 'a ray inside the sun')
            seen.update({int(x): name for x in np.unique(k)})
        disc = mesh.where(material=eb.SUN)
        assert (np.linalg.norm(disc.V[:, [0, 2]] - C, axis=1) <= sun['radius'] - eb.RING + eb.SNAP + 1e-6).all(), pid
        if sun['count'] is None:
            assert sun['width'] == pytest.approx(2 * math.pi / eb.RAYS) and len(seen) == eb.RAYS, pid
        else:
            assert sun['count'] % 2 == 1 and seen[0] == seen[sun['count'] - 1] == eb.MAGENTA, pid
            assert sun['width'] == pytest.approx(2 * math.pi / eb.RAYS, rel=.2), pid


def test_rays_run_up_the_walls_to_the_coping(shipped):
    """Painted faces reach the lip: the lip's height is painted on every boosted piece, and the walls take both
    colours."""
    for pid in shipped.boosts:
        mesh = dsl.Mesh.concat(shipped.parts[pid])
        lips = ec._join(ec.piece_lips(shipped.pieces[pid]))
        top = max(q[:, 1].max() for q, *_ in lips)
        for name in (eb.MAGENTA, eb.YELLOW):
            m = mesh.where(material=name)
            assert m.V[:, 1].max() > top - .02, (pid, name)
            steep = np.abs(m.face_normals()[:, 1]) < .5
            assert steep.any(), (pid, name, 'no wall painted')


def test_u_turn_sun_sits_on_the_inside_of_the_turn(shipped):
    for pid in ('p47', 'p51'):
        piece = shipped.pieces[pid]
        ride, _ = ec._classes(piece)
        sun = eb.layout(piece, piece.mesh.V, piece.mesh.N, eg.orient(piece.mesh.V, piece.mesh.F, piece.mesh.N), ride)
        S = np.array([[s['x'], s['z']] for s in piece.metadata['stations']])
        r = np.linalg.norm(S - sun['centre'], axis=1)
        assert r.std() < .05 * r.mean(), 'the centre of the turn: every station as far from it'
        assert sun['radius'] < r.mean(), 'the sun stays on the inner half of the floor'


def test_boost_copings_are_gold_and_their_rails_unchanged(shipped):
    pieces = [shipped.pieces[i] for i in shipped.parts]
    steel, rails0, _ = ec.build(pieces, {})
    gold, rails1, _ = ec.build(pieces, {}, gold=shipped.boosts)
    assert [r.points.tolist() for r in rails0] == [r.points.tolist() for r in rails1], 'the grind lines never move'
    golden = np.concatenate([m.V[m.F[m.material == dsl.MATERIAL[ec.GOLD]]].mean(1) for m in gold])
    assert len(golden), 'gold coping'
    assert not any((m.material == dsl.MATERIAL[ec.GOLD]).any() for m in steel)
    # every gold face is at a boost piece's lip, and every boost piece's lip is gold
    boost_lips = np.concatenate([q for i in shipped.boosts for q, _ in ec.piece_lips(shipped.pieces[i])])
    other_lips = np.concatenate([q for i in shipped.parts if i not in shipped.boosts
                                 for q, _ in ec.piece_lips(shipped.pieces[i])])
    near = lambda P, Q: np.min(np.linalg.norm(P[:, None] - Q[None], axis=2), 1)
    g = golden[::3]
    assert (near(g, boost_lips) <= near(g, other_lips) + .05).all(), 'gold coping off a boost zone'

    # the coping face nearest every boost lip point (but a joint's, shared with a plain piece) is gold
    faces = np.concatenate([m.V[m.F].mean(1) for m in gold])
    is_gold = np.concatenate([m.material == dsl.MATERIAL[ec.GOLD] for m in gold])
    own = boost_lips[near(boost_lips, other_lips) > .05]
    nearest = np.array([np.argmin(np.linalg.norm(faces - q, axis=1)) for q in own[::3]])
    assert is_gold[nearest].all(), 'a boost lip with steel coping'


def test_a_future_boosted_straight_run_gets_the_look_automatically():
    """A run the owner boosts later is painted from params.boost alone: a sun at its middle, rays up both walls."""
    ride, deck = [0.863, 0.762, 0.674], [0.874, 0.51, 0.322]
    xs = np.arange(0., 40.1, 2.)
    # rows across the run (z, y): a deck, a wall, the floor, a wall, a deck; a face takes its first corner's colour
    rows = [(-7.5, 3.), (-6., 3.), (-4., 1.), (-2., 0.), (2., 0.), (4., 1.), (6., 3.), (7.5, 3.)]
    n, last = len(xs), len(rows) - 1
    V = np.array([(x, y, z) for z, y in rows for x in xs], 'f8')
    C = np.array([deck if j in (0, last) else ride for j in range(len(rows)) for _ in xs], 'f8')
    F = []
    for j in range(last):
        for i in range(n - 1):
            a, b = j * n + i, (j + 1) * n + i
            F += [(b, b + 1, a), (b + 1, a + 1, a)] if j == last - 1 else [(a, b, b + 1), (a, b + 1, a + 1)]
    F = np.array(F)
    N = dsl.vertex_normals(V, F)
    stations = [{'d': x, 'x': x, 'z': 0., 'y': 0., 'h': 0.} for x in xs]
    meta = {'id': 'q1', 'type': 'run', 'stations': stations, 'params': {'boost': 1.5}, 'line': 'Lx'}
    piece = types.SimpleNamespace(mesh=types.SimpleNamespace(V=V, N=N, F=F), colors=C, metadata=meta)
    parts = eg.piece_mesh(piece)
    used = {dsl.MATERIALS[int(m)] for p in parts for m in np.unique(p.material)}
    assert {eb.MAGENTA, eb.YELLOW, eb.SUN, eb.GOLD} <= used
    sun = eb.layout(piece, V, N, F, np.ones(len(F), bool))
    assert sun['centre'] == pytest.approx([20., 0.]) and sun['count'] is None
    meta['params'] = {'boost': 0}
    assert not {dsl.MATERIALS[int(m)] for p in eg.piece_mesh(piece) for m in np.unique(p.material)} & set(eb.PAINTS)


def test_the_paints_are_registered_after_every_older_material():
    import craterpark_textures as ct
    assert dsl.MATERIALS.index('coping_steel') == 46, 'older material indices never move'
    assert dsl.MATERIALS[-4:] == eb.PAINTS
    specs = {m['id']: m for m in json.loads((GAME / 'assets' / 'craterpark' / 'materials.json').read_text())}
    for name in (eb.MAGENTA, eb.YELLOW, eb.SUN):
        spec = specs[name]
        assert spec['finish'] == 'lacquer' and spec['texture'] in ct.BOOST_PAINTS
        painting, _ = ct.BOOST_PAINTS[spec['texture']]
        assert spec['derivedFrom'] == f'restyle/{painting}.jpg'
        assert (GAME / 'assets' / 'craterpark' / spec['derivedFrom']).is_file()
    assert specs[eb.GOLD]['finish'] == 'metal' and specs[eb.GOLD]['texture'] is None
    assert ec.GOLD == eb.GOLD
