"""Crater Park v2: the certified remesh on a dsl.Mesh (craterpark/v2/remesh.py).

Outside Blender the constrained Delaunay is a small Bowyer-Watson Delaunay accepted only where every constraint edge
is one of its edges (then it IS the constrained one); otherwise CDTError, as Blender's would fail closed. Blender's
own CDT on generated ramps is covered by the cleanpark remesh benchmark (a SMALL-slot job)."""
from pathlib import Path
import sys
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark.v2 import layout_m0, remesh, tjunction  # noqa: E402
from craterpark.v2.curves import Arc  # noqa: E402
from craterpark.v2.dsl import RIDING, ROLE, Mesh  # noqa: E402


def delaunay(Q):
    """Bowyer-Watson: triangles (m,3) into Q (k,2), counter-clockwise."""
    Q = np.asarray(Q, 'f8'); lo, hi = Q.min(0), Q.max(0); c = (lo + hi) / 2; r = max(float((hi - lo).max()), 1.) * 20
    P = np.vstack([Q, c + [-r, -r], c + [r, -r], c + [0, r]]); k = len(Q)
    tris = [(k, k + 1, k + 2)]
    for i in range(k):
        p = P[i]; T = np.array(tris); a, b, cc = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        ad, bd, cd = a - p, b - p, cc - p
        det = ((ad ** 2).sum(1) * (bd[:, 0] * cd[:, 1] - cd[:, 0] * bd[:, 1]) - (bd ** 2).sum(1) * (ad[:, 0] * cd[:, 1] - cd[:, 0] * ad[:, 1])
               + (cd ** 2).sum(1) * (ad[:, 0] * bd[:, 1] - bd[:, 0] * ad[:, 1]))
        bad = det > 1e-12
        edges = {}
        for t in T[bad].tolist():
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                key = tuple(sorted(e)); edges[key] = None if key in edges else e
        tris = [tuple(t) for t in T[~bad].tolist()] + [(e[0], e[1], i) for e in edges.values() if e is not None]
    T = np.array([t for t in tris if max(t) < k], 'i8').reshape(-1, 3)
    return T


def stub_cdt(Q2, edges):
    T = delaunay(Q2)
    have = {tuple(sorted(e)) for t in T.tolist() for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
    if any(tuple(sorted(e)) not in have for e in np.asarray(edges).tolist()):
        raise remesh.CDTError('a constraint edge is not Delaunay here')
    return T


def grid(nx, nz, x0=0., x1=10., z0=0., z1=10., y=lambda x, z: 0 * x):
    x = np.linspace(x0, x1, nx + 1); z = np.linspace(z0, z1, nz + 1)
    X, Z = np.meshgrid(x, z); V = np.stack([X.ravel(), y(X, Z).ravel(), Z.ravel()], 1)
    i = (np.arange(nz)[:, None] * (nx + 1) + np.arange(nx)[None]).ravel()
    F = np.concatenate([np.stack([i, i + nx + 1, i + 1], 1), np.stack([i + 1, i + nx + 1, i + nx + 2], 1)])
    return V, F


def distance_to(m, Q):
    """Each point's (k,3) distance to the mesh's surface (brute force: small meshes)."""
    T = m.triangles(); a, b, c = T[:, 0], T[:, 1], T[:, 2]
    n = np.cross(b - a, c - a); n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    best = np.full(len(Q), np.inf)
    for q in range(len(Q)):
        p = Q[q]; d = ((p - a) * n).sum(1); f = p - d[:, None] * n
        inside = np.ones(len(T), bool)
        for u, v in ((a, b), (b, c), (c, a)):
            inside &= (np.cross(v - u, f - u) * n).sum(1) >= -1e-12
        dist = np.where(inside, np.abs(d), np.inf)
        for u, v in ((a, b), (b, c), (c, a)):
            t = np.clip(((p - u) * (v - u)).sum(1) / np.maximum(((v - u) ** 2).sum(1), 1e-300), 0, 1)
            dist = np.minimum(dist, np.linalg.norm(u + t[:, None] * (v - u) - p, axis=1))
        best[q] = dist.min()
    return best


def heights_at(m, q):
    """The mesh's heights at the plan points q (k, 2), nan where none."""
    loc = remesh.Locator(m.V[m.F][:, :, [0, 2]]); tri, bc = loc.locate(q, eps=1e-7)
    h = np.full(len(q), np.nan); ok = tri >= 0
    h[ok] = (m.V[m.F[tri[ok]], 1] * bc[ok]).sum(1)
    return h


class SimplifyTests(unittest.TestCase):
    def setUp(self):
        self.real = remesh.cdt; remesh.cdt = stub_cdt

    def tearDown(self):
        remesh.cdt = self.real

    def test_a_flat_deck_becomes_a_few_faces_with_its_outline_uvs_and_tags(self):
        V, F = grid(10, 10)
        m = Mesh.part(V, F, material='material_000', role='riding', feature='deck', tag='landing', UV=V[:, [0, 2]] / 9.)
        diag = {}; out = remesh.simplify(m, diag=diag)
        self.assertLess(len(out.F), 20)
        self.assertAlmostEqual(out.areas().sum(), 100., places=9)
        self.assertTrue((out.face_normals()[:, 1] > .999).all())
        self.assertTrue(np.allclose(out.UV, out.V[:, [0, 2]] / 9.))
        self.assertEqual({int(x) for x in out.tag}, {int(m.tag[0])})
        self.assertEqual(out.features, ('deck',))
        self.assertEqual(diag.get('failed_patches', 0), 0)

    def test_a_curved_transition_stays_within_tolerance(self):
        R = 3.5
        V, F = grid(40, 8, 0., 3., 0., 6., y=lambda x, z: R - np.sqrt(R * R - x * x))
        m = Mesh.part(V, F, feature='quarter')
        out = remesh.simplify(m)
        self.assertLess(len(out.F), len(F) / 2)
        # within tol_h along each patch's direction, so at most that far from the surface
        self.assertLess(distance_to(out, V).max(), remesh.TOL_H + 1e-9)
        self.assertAlmostEqual(out.areas().sum(), m.areas().sum(), delta=m.areas().sum() * 1e-3)

    def test_a_crease_between_two_features_conforms_and_keeps_its_vertices(self):
        # a deck and a 30-degree ramp meeting at x = 5: the crease's vertices split (one per side); the ramp sampled
        # finer along z than the deck is not allowed (the network shares samples), so both use 10 rows
        dv, df = grid(5, 10, 0., 5.)
        rv, rf = grid(5, 10, 5., 10., y=lambda x, z: (x - 5.) * np.tan(np.radians(30)))
        m = Mesh.concat([Mesh.part(dv, df, feature='deck'), Mesh.part(rv, rf, feature='ramp')])
        out = remesh.simplify(m)
        self.assertEqual(tjunction.check(out)['tjunctions'], 0)
        crease = np.flatnonzero(np.abs(out.V[:, 0] - 5.) < 1e-9)
        self.assertEqual(len(crease), 2 * 11)                           # every crease vertex, on both sides
        self.assertEqual(set(out.features), {'deck', 'ramp'})
        self.assertAlmostEqual(out.areas().sum(), m.areas().sum(), places=9)

    def test_a_folded_patch_keeps_its_faces(self):
        V, F = grid(6, 6)
        V[24, 0] += 2.2                                                  # an interior vertex pulled over its neighbours
        m = Mesh.part(V, F, feature='folded')
        diag = {}; out = remesh.simplify(m, diag=diag)
        self.assertEqual(len(out.F), len(F))
        self.assertGreaterEqual(diag.get('failed_patches', 0), 1)
        self.assertGreaterEqual(sum(diag['reasons'].values()), 1)      # why it failed is recorded

    def test_inside_the_fine_faces_too_on_a_bowl(self):
        # a quarter pipe swept round a 9 m arc (curved both ways): a coarse edge crossing a long fine face kinks inside
        # it, off the fine surface (3.66 mm here when only vertices were checked); the crossings are certified too
        m = layout_m0.quarter_pipe(Arc((0., 0.), 9., 0., 40.), feature='bowl')[0]
        out = remesh.simplify(m, tol_h=.0025)
        self.assertLess(len(out.F), .8 * len(m.F))
        T = m.triangles()[m.role == ROLE[RIDING]]
        self.assertLess(distance_to(out, T.mean(1)).max(), .0025 + 1e-9)
        self.assertEqual(tjunction.check(out)['tjunctions'], 0)

    def test_a_seam_ending_inside_a_patch_keeps_its_faces(self):
        # a UV seam along x = 5 from z = 0 to z = 5 only: its twins lie in one patch (joined round the seam's end)
        V, F = grid(10, 10)
        seam = np.flatnonzero((np.abs(V[:, 0] - 5) < 1e-9) & (V[:, 2] < 5 - 1e-9))
        twin = len(V) + np.arange(len(seam)); V2 = np.vstack([V, V[seam]]); UV = np.vstack([V[:, [0, 2]], V[seam][:, [0, 2]] + [3., 0.]])
        remap = np.arange(len(V)); remap[seam] = twin
        right = (V[F].mean(1)[:, 0] > 5) & (V[F].mean(1)[:, 2] < 5)
        F2 = np.where(right[:, None], remap[F], F)
        m = Mesh.part(V2, F2, feature='deck', UV=UV)
        diag = {}; out = remesh.simplify(m, diag=diag)
        self.assertEqual(len(out.F), len(F))
        self.assertGreaterEqual(diag.get('seam_patches', 0), 1)

    def test_pieces_simplified_apart_with_keep_open_still_meet(self):
        # a curved sheet cut in two along z = 5 (as export's render chunks are): each simplified on its own
        R = 3.5
        V, F = grid(30, 20, 0., 3., 0., 10., y=lambda x, z: R - np.sqrt(R * R - x * x))
        c = V[F].mean(1)[:, 2] < 5
        # the lower half changes material at x = 1.5, so its chains along the cut end there; the upper's do not
        lower = V[F[c]].mean(1)[:, 0] < 1.5
        halves = [Mesh.concat([Mesh.part(V, F[c][lower], feature='quarter'),
                               Mesh.part(V, F[c][~lower], feature='quarter', material='material_000')]),
                  Mesh.part(V, F[~c], feature='quarter')]
        out = [remesh.simplify(h, keep_open=True) for h in halves]
        self.assertLess(sum(len(o.F) for o in out), len(F))
        self.assertEqual(tjunction.check(Mesh.concat(out))['tjunctions'], 0)
        cut = [np.unique(np.round(o.V[np.abs(o.V[:, 2] - 5) < 1e-9, 0], 9)) for o in out]
        self.assertTrue(np.array_equal(cut[0], cut[1]))                # the cut keeps every vertex on both sides
        self.assertEqual(len(cut[0]), 31)

    def test_kept_faces_are_unchanged(self):
        V, F = grid(10, 10)
        m = Mesh.part(V, F, feature='deck')
        out = remesh.simplify(m, keep=np.ones(len(F), bool))
        self.assertEqual(len(out.F), len(F))
        self.assertTrue(np.allclose(np.sort(out.triangles().reshape(-1, 9), 0), np.sort(m.triangles().reshape(-1, 9), 0)))


class FailClosedTests(unittest.TestCase):
    def test_closes_accepts_a_sheet_bounded_by_its_constraints_only(self):
        square = np.array([[0, 1, 2], [0, 2, 3]]); loop = [(0, 1), (1, 2), (2, 3), (3, 0)]
        self.assertTrue(remesh._closes(square, loop))
        self.assertFalse(remesh._closes(square[:1], loop))                         # a hole: an edge left open
        self.assertFalse(remesh._closes(np.r_[square, square[:1]], loop))          # an overlap: a face twice
        self.assertFalse(remesh._closes(np.array([[0, 1, 2], [0, 3, 2]]), loop))   # a flipped neighbour
        self.assertFalse(remesh._closes(square, loop[:3]))                         # a boundary edge not constrained

    def test_edge_defects_counts_open_and_non_manifold_edges(self):
        self.assertEqual(remesh._edge_defects(np.array([[0, 1, 2], [0, 2, 3]])), (4, 0))
        self.assertEqual(remesh._edge_defects(np.array([[0, 1, 2], [0, 2, 3], [2, 0, 4]])), (6, 1))


    def test_overlay_checks_late_crossings_and_outside_endpoints(self):
        x = np.arange(102.)
        P = np.array([(a, b) for a in x for b in (0., 1.)] + [(0., .5), (101., .5), (-1., .5), (102., .5)])
        T = np.array([t for i in range(101) for t in ((2*i,2*i+2,2*i+1), (2*i+1,2*i+2,2*i+3))])
        H = np.zeros(len(P)); H[150:152] = 1.
        E = np.array([[204,205], [206,207]])
        loc = remesh.Locator(P[T])
        error = remesh._crossing_errors(P, H, None, .003, None, T, loc, E)
        np.testing.assert_allclose(error, 1. / .003, atol=1e-8)
        A = np.zeros((len(P), 1)); A[150:152] = 1.
        error = remesh._crossing_errors(P, np.zeros(len(P)), A, .003, np.array([.02]), T, loc, E)
        np.testing.assert_allclose(error, 50., atol=1e-8)


    def test_a_patch_that_leaves_a_vertex_uncovered_fails_closed(self):
        P2 = np.array([[0., 0], [1, 0], [0, 1], [2, 2]]); H = np.zeros(4)
        real = remesh.cdt
        remesh.cdt = lambda Q, e: np.array([[0, 1, 2]])
        try:
            T = remesh.remesh_patch(P2, H, None, .003, None, [0, 1, 2], [(0, 1), (1, 2), (2, 0)], np.arange(4),
                                    lambda c: np.ones(len(c), bool), max_rounds=3)
        finally:
            remesh.cdt = real
        self.assertIsNone(T)

    def test_a_boundary_simplified_to_a_segment_fails_closed(self):
        P2 = np.array([[0., 0], [1, 0], [.5, 1e-4]]); H = np.zeros(3)
        T = remesh.remesh_patch(P2, H, None, .003, None, [0, 1], [(0, 1), (1, 0)], np.arange(3), lambda c: np.ones(len(c), bool))
        self.assertIsNone(T)


if __name__ == '__main__':
    unittest.main()
