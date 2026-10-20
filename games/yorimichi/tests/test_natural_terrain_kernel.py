"""Numerical reference sampled before separating the natural kernel from final mountain deformation."""
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from hidamari import mountains, natural_terrain  # noqa: E402


def test_natural_terrain_preserves_the_established_height_field(monkeypatch):
    monkeypatch.setenv('ATELIER_CRATERPARK_EDITOR_PARK', 'off')
    monkeypatch.delenv('ATELIER_CRATERPARK_V4_DESIGN', raising=False)
    # Metres: apron, former summit/shoulder, caldera floor/wall/rim, outer flanks and northern join.
    x = np.array([-700, -150, 0, 400, 550, 750, 850, 950, 1150, 1350, 1500, 1900, 2200, 2400,
                  850, 850, 550, 0], float)
    y = np.array([500, 750, 1250, 1750, 1930, 2350, 2400, 2500, 2400, 2400, 2900, 3200, 3500,
                  3900, 2000, 2850, 2150, 2100], float)
    expected = [47., 71.65814556566235, 131.7217126267516, 481.24817196547457, 607.0609559647115,
                639.339334321366, 640.3756758865231, 640.0816650038221, 639.6084887509264,
                734.9704569191333, 435.57242896662757, 154.50088018476382, 110.90924966445279,
                116.38535029514642, 670.36447190081, 680.7750114381074, 664.300107784241,
                348.0281450746779]
    np.testing.assert_allclose(natural_terrain.natural_height(x, y), expected, rtol=0, atol=1e-9)
    np.testing.assert_array_equal(mountains.natural_height(x, y), natural_terrain.natural_height(x, y))
    assert mountains.BOUNDS[:2] == natural_terrain.GRID_ORIGIN


def test_final_mountain_snow_keeps_the_shared_polar_noise():
    # Snow's callers retain the existing module API as well as the natural geometry's noise implementation.
    radius, angle = np.array([400., 700.]), np.array([-.8, 2.])
    np.testing.assert_array_equal(mountains.downslope_noise(radius, angle, 22., 68),
                                  natural_terrain.downslope_noise(radius, angle, 22., 68))
