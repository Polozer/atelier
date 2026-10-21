"""The physical companionway drive reaches both deck joins in ship-local coordinates."""
import ast
import math
from pathlib import Path

import pytest


@pytest.mark.parametrize('side', [-1, 1])
def test_companionway_route_crosses_both_joins_and_returns(side):
    path = Path(__file__).resolve().parents[1] / 'scenarios/ferry_roundtrip_live.py'
    tree = ast.parse(path.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'companionway_route')
    namespace = {'math': math}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    deck = {'main_deck': {'x': [-40., 40.], 'z': [6., 7.]},
            'boat_deck': {'z': {'x': [-40., 40.], 'z': [10., 11.]}},
            'stair': {'y': [-1.7, -.7], 'foot_x': -26., 'foot_z': 6.2,
                      'top_x': -22., 'top_z': 10.225, 'tread': .28}}
    start = [15.2, side*4.5, 6.69]
    route = namespace['companionway_route'](deck, start)
    foot, top = deck['stair']['foot_x']-.28, deck['stair']['top_x']
    stair_points = [p for p in route if foot <= p[0] <= top and abs(p[1]+1.2) < 1e-10]
    assert route[0] == start
    assert stair_points[0] == pytest.approx([foot, -1.2, 6.2])
    assert stair_points[-1] == pytest.approx([top, -1.2, 10.225])
    assert all(0 < b[0]-a[0] <= .5 for a, b in zip(stair_points, stair_points[1:]))
    assert route[-1] == pytest.approx([-21.2, -1.2, 10.+(40.-21.2)/80.])
    assert route[-1][0] > top+.5  # Must walk onto the upper deck, beyond the nosing.
    return_route = list(reversed(route))
    assert return_route[0] == route[-1] and return_route[-1] == start
    assert max(p[2] for p in route) - min(p[2] for p in route) > 3.9
