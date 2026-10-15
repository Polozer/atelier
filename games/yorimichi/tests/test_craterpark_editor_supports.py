"""Editor-park supports: stone viaducts under every ramp, flush with its underside, clear of the pieces below."""
from pathlib import Path
import sys
import types

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, editor_supports as es  # noqa: E402


def sheet(pid, y, length=60., width=18., x0=0., z0=0.):
    """A flat run along +x at height y, as the bridge would hand it over (a triangulated sheet plus stations)."""
    xs, zs = np.meshgrid(np.arange(0, length + .1, 2.), np.arange(-width / 2, width / 2 + .1, 3.))
    V = np.stack([x0 + xs.ravel(), np.full(xs.size, y), z0 + zs.ravel()], 1)
    nz, nx = xs.shape
    i = (np.arange(nz - 1)[:, None] * nx + np.arange(nx - 1)[None]).ravel()
    F = np.concatenate([np.stack([i, i + nx, i + 1], 1), np.stack([i + 1, i + nx, i + nx + 1], 1)])
    stations = [dict(d=float(d), x=x0 + d, y=y, z=z0, h=0., a=0., w=width - 2, wl={'h': 0., 'R': 1.}, wr={'h': 0., 'R': 1.},
                     deck=0.) for d in np.arange(0, length + .1, 1.)]
    return types.SimpleNamespace(mesh=types.SimpleNamespace(V=V, F=F), metadata=dict(id=pid, type='run', stations=stations))


GRID = dict(x0=-60., z0=-60., G=2., nx=150, nz=150)
FLAT = np.zeros(150 * 150, 'f4')


def vertices(parts):
    return np.concatenate([p.V for p in parts]) if parts else np.zeros((0, 3))


def test_high_piece_rides_on_an_arcade_flush_under_it():
    parts, summary = es.build([sheet('p1', 30., length=120.)], FLAT, GRID)
    assert summary['pieces'] == {'p1': 'viaduct'} and summary['piers'] >= 3 and summary['arches'] >= 2
    assert all((p.material == dsl.MATERIAL[es.STONE]).all() and p.role[0] == dsl.ROLE[dsl.SIDE] for p in parts)
    V = vertices(parts)
    assert abs(V[:, 1].max() - (30. + es.EMBED)) < 1e-6, 'the stone meets the ramp in one line'
    assert V[:, 1].min() >= -es.SINK - 1e-6
    assert np.isfinite(V).all() and np.isfinite(np.concatenate([p.N for p in parts])).all()


def test_few_thick_piers_not_a_forest():
    parts, summary = es.build([sheet('p1', 30., length=120.)], FLAT, GRID)
    assert summary['piers'] <= 120. / es.SPAN_MIN
    assert sum(len(p.F) for p in parts) < 3000


def test_low_run_rests_on_a_solid_wall():
    parts, summary = es.build([sheet('p1', 3.)], FLAT, GRID)
    assert summary['arches'] == 0 and summary['piers'] >= 1
    assert vertices(parts)[:, 1].max() <= 3. + es.EMBED + 1e-6


def test_the_arcade_lifts_clear_of_a_piece_below():
    high, low = sheet('high', 40., length=120.), sheet('low', 10., length=20., x0=50.)
    parts, _ = es.build([high, low], FLAT, GRID)
    V = vertices([p for p in parts if p.features[0] == 'high_supports'])
    over = (V[:, 0] > 50.5) & (V[:, 0] < 69.5) & (np.abs(V[:, 2]) < 8.5)
    assert over.any() and (V[over, 1] >= 10. + es.OVER - 1e-6).all(), 'stone stands on or runs through the lower piece'


def test_supports_are_deterministic():
    a, _ = es.build([sheet('p1', 30.)], FLAT, GRID)
    b, _ = es.build([sheet('p1', 30.)], FLAT, GRID)
    assert np.array_equal(vertices(a), vertices(b))
