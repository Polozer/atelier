"""The railway's earthworks (world/train/earthworks.py): the designed surface on a made-up line, then every built
terrain the Belmonte line crosses: carved to the formation at every 10 m sample outside the tunnels and the viaduct,
and unchanged away from the line."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))

import yori  # noqa: E402
from train import corridor as C, earthworks as E  # noqa: E402

TOLERANCE = .12         # metres between the formation and the carved ground at a sample
OPEN = ('cutting', 'deep cutting', 'embankment')


def made_up_line():
    """A straight line east along y = 0, rail at 100 m: cutting, a tunnel from 145 to 245 (between samples), embankment."""
    kind = lambda s: 'cutting' if s < 150 else 'tunnel' if s < 250 else 'embankment'   # noqa: E731
    return E.Line({'samples': [{'s': float(s), 'x': float(s), 'y': 0., 'rail_z': 100., 'ground_z': 100.,
                                'class': kind(s)} for s in range(0, 410, 10)]})


class Design(unittest.TestCase):
    ln = made_up_line()
    floor = 100. - E.FORMATION_DROP

    def setUp(self):
        E.line.cache_clear()

    def tearDown(self):
        E.line.cache_clear()

    def carve(self, x, y, z):
        return float(E.carve(np.array([x]), np.array([y]), np.array([z]), self.ln)[0])

    def test_a_cutting_is_lowered_to_the_formation_and_slopes_up_to_the_ground(self):
        self.assertAlmostEqual(self.carve(50., 0., 120.), self.floor, places=6)
        self.assertAlmostEqual(self.carve(50., -E.FLOOR_HALF, 120.), self.floor, places=6)
        side = self.carve(50., 20., 120.)
        self.assertGreater(side, self.floor + 3.)
        self.assertLess(side, 120.)
        self.assertEqual(self.carve(50., E.REACH + 5., 120.), 120.)

    def test_an_embankment_is_raised_to_the_formation(self):
        self.assertAlmostEqual(self.carve(320., 0., 90.), self.floor, places=6)
        self.assertLess(self.carve(320., 15., 90.), self.floor - 3.)
        self.assertEqual(self.carve(320., 80., 90.), 90.)

    def test_the_ground_over_a_tunnel_keeps_its_hood_and_is_left_alone_deep_inside(self):
        self.assertGreaterEqual(self.carve(200., 0., 103.), 100. + E.HOOD - 1e-6)
        self.assertEqual(self.carve(200., 0., 160.), 160.)

    def test_a_hole_opens_across_the_portal_only(self):
        holes = E.in_hole(np.array([146., 146., 100., 146.]), np.array([0., 20., 0., 0.]),
                          np.array([101., 101., 101., 140.]), self.ln)
        self.assertEqual(holes.tolist(), [True, False, False, False])

    def test_refining_a_coarse_sheet_carves_it_and_leaves_the_rest(self):
        xs, ys = np.arange(0., 401., 20.), np.arange(-200., 201., 20.)
        x, y = np.meshgrid(xs, ys)
        v = np.stack([x, y, np.full_like(x, 115.)], -1).reshape(-1, 3)
        w = len(xs)
        faces = [(j * w + i, j * w + i + 1, (j + 1) * w + i + 1) for j in range(len(ys) - 1) for i in range(w - 1)]
        faces += [(j * w + i, (j + 1) * w + i + 1, (j + 1) * w + i) for j in range(len(ys) - 1) for i in range(w - 1)]
        out, f, _, report = E.refine(v, faces, 2.5, ln=self.ln)
        self.assertGreater(report['refined'], 0)
        self.assertGreater(report['hole_triangles'], 0)
        from belmonte.source import Surface
        ground = Surface(out[f])
        self.assertLess(abs(float(ground.height(np.array([60.]), np.array([0.]))[0]) - self.floor), TOLERANCE)
        far = np.abs(v[:, 1]) > E.REACH + 25
        self.assertTrue(np.allclose(out[:len(v)][far, 2], 115.))

    def test_hidden_ground_stays_out_of_the_tunnel_bore(self):
        """Ground under another terrain (refine's hidden) is not carved, but nothing of it may stand inside a tunnel's
        bore (grass seen from the train): over the tunnel it is lifted under the hood by HIDDEN_CLEARANCE, across the
        mouth it opens like the shown ground, and elsewhere it is left as it is."""
        xs, ys = np.arange(100., 301., 8.), np.arange(-40., 41., 8.)
        x, y = np.meshgrid(xs, ys)
        # A hillside under the foothills, rising across the line: inside the bore height on one side.
        z = 101. + .12 * (y + 40.)
        v = np.stack([x, y, z], -1).reshape(-1, 3)
        w = len(xs)
        faces = [(j * w + i, j * w + i + 1, (j + 1) * w + i + 1) for j in range(len(ys) - 1) for i in range(w - 1)]
        faces += [(j * w + i, (j + 1) * w + i + 1, (j + 1) * w + i) for j in range(len(ys) - 1) for i in range(w - 1)]
        out, f, _, _ = E.refine(v, faces, 2.5, ln=self.ln, hidden=lambda x, y: np.ones(np.shape(x), bool))
        from belmonte.source import Surface
        ground = Surface(out[f])
        top = 100. + C.PORTAL_HEIGHT[1]          # over the lining's crown
        for s in np.arange(147., 244., 3.):     # the tunnel runs 145-245
            for u in (-2.6, 0., 2.6):           # the lining's half width
                h = float(ground.height(np.array([s]), np.array([u]))[0])
                if np.isfinite(h):
                    self.assertTrue(h >= top - 1e-6 or h <= 100. + C.PORTAL_HEIGHT[0], (s, u, h))
                    # layered under the shown ground's hood, never on it
                    self.assertLessEqual(h, 100. + E.HOOD - E.HIDDEN_CLEARANCE + 1e-6)
        # Along the open line it stays under the cutting (never over the formation), never raised; away from the
        # line and the tunnel it is not moved.
        for s in np.arange(102., 140., 3.):
            for u in (-6., -2.6, 0., 2.6, 6.):
                h = float(ground.height(np.array([s]), np.array([u]))[0])
                up, _, _ = E.design(np.array([s]), np.array([u]), self.ln)
                self.assertLessEqual(h, float(up[0]) - E.HIDDEN_CLEARANCE + .05, (s, u))
        moved = out[:len(v), 2] - v[:, 2]
        _, _, info = E.design(v[:, 0], v[:, 1], self.ln)
        self.assertTrue(np.all(moved[info['tunnel'] <= 0] <= 1e-9))
        far = ~np.isfinite(self.ln.project(v[:, 0], v[:, 1])[0])
        np.testing.assert_allclose(out[:len(v)][far, 2], v[far, 2])
        self.assertEqual(E.hidden_ground(np.array([60.]), np.array([0.]), np.array([95.]), self.ln).tolist(), [95.])
        self.assertLess(float(E.hidden_ground(np.array([60.]), np.array([0.]), np.array([101.]), self.ln)[0]),
                        100. - E.FORMATION_DROP - E.HIDDEN_CLEARANCE + 1e-6)

    def test_committed_line_is_loaded_unconditionally(self):
        E.line.cache_clear()
        self.assertIsNotNone(E.line())
        self.assertIsNotNone(C.load())


def samples():
    """The open 10 m samples of the built line, away from structure ends (whose cones and portals differ)."""
    data = json.loads(C.LINE.read_text())
    ln = E.Line(data)
    rows = [r for r in data['samples'] if r['class'] in OPEN]
    s = np.array([r['s'] for r in rows])
    keep = np.ones(len(s), bool)
    for a, b in ln.tunnels + ln.viaducts:
        keep &= (np.abs(s - a) > 6.) & (np.abs(s - b) > 6.)
    keep &= (s > 6.) & (s < ln.length - 6.)
    pick = lambda k: np.array([r[k] for r in rows])[keep]   # noqa: E731
    return ln, pick('x'), pick('y'), pick('rail_z')


@unittest.skipUnless(C.ROUTE.exists() and (yori.OUT / 'farhills.npy').exists(), 'route or world.layout not built')
class Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        E.line.cache_clear()
        cls.ln, cls.x, cls.y, cls.rail = samples()

    def check(self, name, carved, natural, inside):
        """carved/natural: height functions; inside: mask of the samples this terrain shows."""
        x, y, rail = self.x[inside], self.y[inside], self.rail[inside]
        z = carved(x, y)
        on = np.isfinite(z)
        self.assertTrue(on.any(), name)
        off = np.abs(z[on] - (rail[on] - E.FORMATION_DROP))
        with self.subTest(terrain=name, samples=int(on.sum())):
            self.assertLess(float(off.max()), TOLERANCE, f'{name}: {int((off > TOLERANCE).sum())} samples off, worst '
                            f'{off.max():.2f} m at {x[on][np.argmax(off)]:.0f}, {y[on][np.argmax(off)]:.0f}')
        # Away from the line the terrain is as it was.
        rng = np.random.default_rng(3)
        px, py = x[:, None] + rng.uniform(-600, 600, (len(x), 6)), y[:, None] + rng.uniform(-600, 600, (len(x), 6))
        s, _, _ = self.ln.project(px.ravel(), py.ravel())
        far = ~np.isfinite(s)
        a, b = carved(px.ravel()[far], py.ravel()[far]), natural(px.ravel()[far], py.ravel()[far])
        both = np.isfinite(a) & np.isfinite(b)
        with self.subTest(terrain=name, check='unchanged away from the line'):
            self.assertTrue(np.allclose(a[both], b[both], atol=1e-3), name)

    def test_belmonte_apron_and_country(self):
        from belmonte import layout as BM, source
        out = yori.OUT / 'belmonte'
        for name in ('SM_BM_NorthApron', 'SM_BM_NorthCountry'):
            if not (out / 'natural' / f'{name}.glb').exists():
                self.skipTest('Belmonte not built with its natural ground (world.belmonte)')
            built, natural = (source.Surface(source.triangles(out / d / f'{name}.glb')) for d in ('glb', 'natural'))
            shift = lambda surface: (lambda x, y: surface.height(x - BM.ORIGIN[0], y - BM.ORIGIN[1]) + BM.ORIGIN[2])  # noqa: E731
            # Near the seam with the valley's terrain (not carved) the apron eases its carving out: the bank covers it.
            inside = (self.y > BM.SOUTH_JOIN) & (E.seam_weight(self.x, self.y, BM.BOUNDS) >= 1.)
            if np.isfinite(shift(built)(self.x[inside], self.y[inside])).any():
                self.check(name, shift(built), shift(natural), inside)

    def test_hidamari_foothills(self):
        from hidamari import mountains
        from hidamari.layout import north_base_height
        sheet = mountains.mesh(north_base_height)
        from belmonte.source import Surface
        built = Surface(sheet['vertices'][sheet['faces']])
        natural = lambda x, y: mountains.height(x, y, north_base_height, carved=False)   # noqa: E731
        # The sheet also carries the far hills' aprons round the foothills (mountains.apron_grids), at their own height:
        # compare the foothills' footprint only.
        foothills = lambda x, y: np.where(mountains.contains(x, y), built.height(x, y), np.nan)   # noqa: E731
        inside = mountains.contains(self.x, self.y)
        self.check('HD_NorthMountains', foothills, natural, inside)

    def test_belmonte_valley_banks(self):
        from belmonte import layout as BM
        from train import track as T
        meshes, doc = T.layout()
        faces = []
        for row in doc['banks']:
            mesh = meshes[row['name']][0]
            v = np.asarray(mesh.verts) + row['origin']
            for f in mesh.faces:
                faces.extend([(v[f[0]], v[f[k]], v[f[k + 1]]) for k in range(1, len(f) - 1)])
        if not faces:
            self.skipTest('no bank over Belmonte\'s valley on this route')
        from belmonte.source import Surface
        bank = Surface(np.asarray(faces))
        inside = E.seam_weight(self.x, self.y, BM.BOUNDS) < 1.
        z = bank.height(self.x[inside], self.y[inside])
        on = np.isfinite(z)
        off = np.abs(z[on] - (self.rail[inside][on] - E.FORMATION_DROP))
        self.assertLess(float(off.max()), TOLERANCE)



SUPPORT_STEP = 2.               # metres between the whole-line support checks
BED = (-2.6, -2.45, -1.7, 0., 1.7, 2.45, 2.6)    # across the ballast bed: skirts, toes, shoulders, centre (track.py)
UNDER = 1.5 + .1                # the ground may lie this far under the rail top, no further: the skirts' foot
OVER = .70 - .1                 # ... and must stay this far under it inside the toes: under the ballast


def built_ground():
    """Every built terrain the line crosses, as one top surface: the far hills, Hidamari, the foothills, Belmonte's
    tiles, apron and country, and the track's own banks. None when they are not all built."""
    from terrain_product import load
    from belmonte import layout as BM, source
    from train import track as T
    out = yori.OUT
    owners = ('FarHills', 'HD_Terrain', 'HD_NorthMountains')
    glb = out / 'belmonte' / 'glb'
    names = ['SM_BM_NorthApron', 'SM_BM_NorthCountry']
    if not all((out / 'terrain' / o / 'final.npz').exists() for o in owners) or not glb.is_dir() or \
            not all((glb / f'{n}.glb').exists() for n in names) or not T.ROUTE.exists():
        return None
    faces = []
    for owner in owners:
        m = load(out / 'terrain' / owner / 'final.npz', owner=owner, stage='final', city=True)
        faces.append(m.vertices[m.triangles()])
    tiles = sorted(p for p in glb.glob('SM_BM_BT_Terrain_*.glb') if 'Collision' not in p.name)
    faces.append(np.concatenate([source.triangles(p) for p in tiles + [glb / f'{n}.glb' for n in names]]) + BM.ORIGIN)
    meshes, doc = T.layout()
    for row in doc['banks']:
        mesh = meshes[row['name']][0]
        v = np.asarray(mesh.verts) + row['origin']
        faces.append(np.asarray([(v[f[0]], v[f[k]], v[f[k + 1]]) for f in mesh.faces for k in range(1, len(f) - 1)]))
    return source.Surface(np.concatenate(faces))


@unittest.skipUnless(C.ROUTE.exists() and (yori.OUT / 'terrain' / 'FarHills' / 'final.npz').exists(),
                     'route or terrain products not built')
class Supported(unittest.TestCase):
    def test_the_track_neither_floats_nor_sinks_anywhere(self):
        """Every SUPPORT_STEP metres of open line (not in a tunnel or on a viaduct, outside the portals' holes), the
        ground the game shows (the top of every built terrain and bank) carries the ballast bed: no void under its
        skirts or centre (UNDER) and nothing standing over the formation inside its toes (OVER), whichever terrain
        owns it there; hidden ground (the far hills under the foothills) included."""
        ground = built_ground()
        if ground is None:
            self.skipTest('terrain products not all built')
        E.line.cache_clear()
        ln = E.line()
        s = np.arange(0., ln.length, SUPPORT_STEP)
        tun, _ = ln.inside(s, ln.tunnels)
        via, _ = ln.inside(s, ln.viaducts)
        open_ = (tun < -E.HOLE[0] / 2) & (via < 0.)       # clear of the portals' holes (HOLE) and off the viaducts
        s = s[open_]
        u = np.array(BED)
        x0, y0 = np.interp(s, ln.s, ln.xy[:, 0]), np.interp(s, ln.s, ln.xy[:, 1])
        rail = np.interp(s, ln.s, ln.rail)
        tx, ty = ln.tangent(s)
        z = ground.height(x0[:, None] - ty[:, None] * u, y0[:, None] + tx[:, None] * u) - rail[:, None]
        inside = np.abs(u) <= 2.45
        low = ~(z >= -UNDER)                                # NaN (no ground at all) counts as a void
        high = (z > -OVER) & inside[None]

        def stretches(mask):
            rows = np.flatnonzero(mask.any(1))
            if not len(rows):
                return []
            cuts = np.flatnonzero(np.diff(s[rows]) > SUPPORT_STEP * 1.5)
            return [(float(s[rows[a]]), float(s[rows[b]]), float(np.nanmax(np.abs(z[rows[a]:rows[b] + 1]))))
                    for a, b in zip(np.r_[0, cuts + 1], np.r_[cuts, len(rows) - 1])]
        self.assertEqual(stretches(low), [], 'the track floats (chainage from, to, worst metres)')
        self.assertEqual(stretches(high), [], 'ground stands over the formation (chainage from, to, worst metres)')

if __name__ == '__main__':
    unittest.main()


def test_conforming_neighbors_closes_large_and_small_carved_edge_gaps(monkeypatch):
    from belmonte.source import Surface
    class LowerTriangle:
        def project(self,x,y):
            y=np.asarray(y);return np.where(y<0.,0.,np.nan),np.zeros_like(y),np.zeros_like(y)
    monkeypatch.setattr(E,'touched',lambda p,ln:np.ones(len(p),bool))
    # Serialized failing edge dimensions/heights. Only the lower triangle is
    # selected; the other retains its coarse edge in the historical path.
    span=2.694580078125;end=10.822347640991211;node=10.97188949584961
    vertices=np.array([[0.,0.,0.],[span,0.,0.],[0.,span,0.],[0.,-span,0.]])
    faces=np.array([[0,1,2],[1,0,3]])
    for gap in [47.12689971923828,.010911836812482534,.007896164476129286]:
        high=3.*gap+3.*node-2.*end
        def carve(x,y,z,ln=None):
            return np.where(np.asarray(x)<1.e-10,high,end+(span-np.asarray(x))*(node-end)/(span/3.))
        monkeypatch.setattr(E,'carve',carve)
        old,of,oa,report=E.refine(vertices,faces,span/2.,{'colour':vertices[:,:1]+1.},LowerTriangle(),holes=False)
        new,nf,na,joined=E.refine(vertices,faces,span/2.,{'colour':vertices[:,:1]+1.},LowerTriangle(),holes=False,conform_neighbors=True)
        assert report['subdivision']==3 and report['refined']==1
        assert 'conforming_neighbors' not in report and joined['conforming_neighbors']==1
        # Existing vertices and every selected triangle stay exactly unchanged.
        np.testing.assert_array_equal(new[:len(old)],old)
        np.testing.assert_array_equal(nf[-9:],of[-9:])
        np.testing.assert_array_equal(na['colour'][:len(oa['colour'])],oa['colour'])
        selected=Surface(old[of[-9:]])
        x=np.linspace(.01,span-.01,61);y=np.zeros_like(x)
        old_coarse=Surface(old[of[:1]])
        assert abs(float(old_coarse.height(2.*span/3.,0.))-float(selected.height(2.*span/3.,0.))-gap)<1.e-9
        repaired=Surface(new[nf[:-9]])
        np.testing.assert_allclose(repaired.height(x,y),selected.height(x,y),atol=1.e-9)
        triangles=new[nf];area=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])[:,2]
        assert (area>1.e-10).all()


def test_conforming_neighbor_ownership_rejects_nearby_distinct_endpoints():
    # Candidate coordinate bins never authorize joining two different surfaces.
    v=np.array([[0.,0.,0.],[3.,0.,0.],[0.,3.,0.],[0.,-3.,0.],[4.e-8,0.,0.]])
    index={(i,j):k for k,(i,j) in enumerate(( (i,j) for i in range(4) for j in range(4-i) ))}
    # An explicit selected chain with an endpoint from a distinct height layer.
    allv=np.r_[v,[[2.,0.,0.],[1.,0.,0.],[0.,-1.,0.],[0.,-2.,0.]]]
    ids=np.zeros((1,10),int);ids[0,index[0,0]]=0;ids[0,index[3,0]]=1;ids[0,index[0,3]]=3
    ids[0,index[1,0]]=6;ids[0,index[2,0]]=5
    # Direct ownership disagreement must fail rather than silently choose a side.
    shifted=allv.copy();shifted[0,2]=.01
    import pytest
    with pytest.raises(ValueError,match='endpoints'):
        E._conform_neighbors(v,np.array([[4,1,2]]),np.array([[0,1,3]]),ids,index,3,shifted)


def test_nothing_grows_inside_a_tunnel():
    """Plants over a tunnel (any kind) whose foot is under the lining's crown would stand in the bore: they go; the
    forest higher up over the tunnel stays."""
    E.line.cache_clear()
    ln = E.line()
    for a, b in ln.tunnels:
        s = (a + b) / 2
        x, y = np.interp(s, ln.s, ln.xy[:, 0]), np.interp(s, ln.s, ln.xy[:, 1])
        rail = float(np.interp(s, ln.s, ln.rail))
        for name in ('Grass_A', 'Bush_Green_A', 'Tree_Pine_A', 'Rock_A'):
            keep, _ = C.settle(name, [x, x], [y, y], [rail + 2., rail + 40.])
            assert keep.tolist() == [False, True], (name, a, b)
