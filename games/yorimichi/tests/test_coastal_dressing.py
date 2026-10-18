"""The reference-led scenery must leave working waterfronts and routes usable."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'world'))
import yori  # noqa: E402,F401
import coastal_dressing as D  # noqa: E402
import shorelines as S  # noqa: E402


def test_coastal_features_leave_harbor_pier_town_and_rail_cover_clear():
    x = np.array([600., -150., -255., 1273., 2850., -150.])
    y = np.array([-175., -170., -99.51, 301.8, 2000., -530.])
    assert not D.clear_footprint(x, y, 18.).any()
    # Also reject an offshore rock whose centre is clear but whose footprint
    # crosses the harbor boundary or the protected occupied town frontage.
    assert not D.clear_footprint(285., -200., 20.)
    assert not D.clear_footprint(35., -140., 20.)


def test_new_coastal_rocks_and_trees_use_existing_assets_and_safe_footprints():
    objects = D.placements(lambda x, y: S.height(x, y, np.full_like(x, 60.)))
    assert sum(len(rows) for name, rows in objects.items() if name.startswith('SW_Boulder')) > 100
    assert sum(len(rows) for name, rows in objects.items() if name.startswith('Tree_')) > 1000
    assert set(objects) <= {'SW_Boulder_A', 'SW_Boulder_B', 'SW_Boulder_C',
                            'Tree_Pine_B', 'Tree_Maple_A', 'Tree_Ginkgo', 'Tree_Cedar_B', 'Bush_Ochre_A'}
    for name, rows in objects.items():
        p = np.asarray(rows)
        assert np.isfinite(p).all()
        radius = p[:, 4]*1.8 if name.startswith('SW_Boulder') else np.full(len(p), 13.)
        assert D.clear_footprint(p[:, 0], p[:, 1], radius).all()


def test_country_groves_reach_into_backshore_and_leave_meadow_gaps():
    objects = D.placements(lambda x,y: S.height(x,y,np.full_like(x,120.)))
    p = np.array([row for name,rows in objects.items() if name.startswith('Tree_') for row in rows])
    p = p[(p[:,1] > 4200.) & (p[:,1] < 6200.)]
    d, _ = S.field(p[:,0],p[:,1])
    assert np.count_nonzero(d > 350.) > 500
    # Dense groves and empty patches must coexist at the same distance from
    # the coast; a thin uniform parallel row cannot meet this occupancy range.
    p = p[(d > 130.) & (d < 350.) & (p[:,0] > 1500.)]
    counts, _ = np.histogram(p[:,1], np.arange(4200.,6201.,100.))
    assert counts.max() > 15
    assert np.count_nonzero(counts < 4) >= 3


def test_extended_groves_leave_the_region_join_and_complete_rail_clear():
    import json
    p=np.array([[r['x'],r['y']] for r in json.loads(S.RAIL_LINE.read_text())['samples']])
    assert not D.clear_footprint(p[:,0],p[:,1],13.).any()
    # The existing Belmonte producer seats its own woodland on collar triangles;
    # the coastal country sampler must not place a second set across that join.
    assert not D.clear_footprint(1750.,4800.,13.)
    assert not D.clear_footprint(1760.,4800.,13.)


def test_compact_shoulders_preserve_existing_rows_and_clear_whole_footprints():
    import copy
    sites=D.shoulder_sites()
    assert len(sites)==74
    x,y,size=np.asarray([(r[1],r[2],r[3]) for r in sites]).T
    assert D.clear_footprint(x,y,3.*size).all()
    assert size.min()>3. and size.max()<5.36
    # Both transformed source assets and their colliders fit inside this radius.
    for asset in ['SW_Boulder_A','SW_Boulder_B']:
        hx,hy=(1.6,1.36) if asset.endswith('_A') else (2.24,1.12)
        assert np.hypot(hx,hy)<3.
    old={'SW_Boulder_A':[[500.,500.,20.,0.,5.]],'Tree_Pine_B':[[10.,20.,30.,40.,2.]]}
    before=copy.deepcopy(old)
    D.append_shoulders(old,lambda x,y: .01*x+.02*y)
    assert old['Tree_Pine_B']==before['Tree_Pine_B']
    assert old['SW_Boulder_A'][0]==before['SW_Boulder_A'][0]
    added={n:rows[len(before.get(n,[])):] for n,rows in old.items()}
    assert sum(map(len,added.values()))==74
    for rows in added.values():
        for x,y,z,yaw,size in rows:assert abs(z-(.01*x+.02*y+.2*size))<=.00051
