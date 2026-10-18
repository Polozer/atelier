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


def test_coastal_trees_use_existing_assets_and_safe_footprints_without_the_removed_rocks():
    objects = D.placements(lambda x, y: S.height(x, y, np.full_like(x, 60.)))
    assert not any(name.startswith('SW_Boulder') for name in objects)
    assert sum(len(rows) for name, rows in objects.items() if name.startswith('Tree_')) > 1000
    assert set(objects) <= {'Tree_Pine_B', 'Tree_Maple_A', 'Tree_Ginkgo', 'Tree_Cedar_B', 'Bush_Ochre_A'}
    for name, rows in objects.items():
        p = np.asarray(rows)
        assert np.isfinite(p).all()
        radius = p[:, 4]*1.8 if name.startswith('SW_Boulder') else np.full(len(p), 13.)
        assert D.clear_footprint(p[:, 0], p[:, 1], radius).all()


def test_removing_mainland_boulders_preserves_the_original_vegetation_stream():
    import hashlib
    import json
    objects=D.placements(lambda x,y:np.full_like(x,10.))
    # Recorded from original a357552d coastal_dressing.py SHA256
    # 08f5081d28bf9362d5dbe534dfe31495ee9fdfc298fdf4d01057d24419989fe1.
    assert hashlib.sha256(json.dumps(objects,separators=(',',':')).encode()).hexdigest()==\
        'fce58794bc6b89c1154a804a91250fe238f831f14c02403554c6b36a5a7bae7d'


def test_west_repair_moves_only_surviving_owned_roots_and_rejects_rail_overlap(monkeypatch):
    import copy
    import pytest
    from hidamari import layout
    import farhills_grid
    from train import earthworks
    owned={'Tree_Maple_A':[[-350.,-125.,1.,10.,2.],[-600.,-125.,2.,20.,3.]]}
    world={'instances':{'Tree_Maple_A':copy.deepcopy(owned['Tree_Maple_A'])+
                       [[-350.,-130.,3.,30.,4.]],'SW_Boulder_A':[[-350.,-530.,0.,0.,2.]]}}
    before=copy.deepcopy(world)
    axis=np.array([-400.,-300.]);grid=(axis,axis,np.zeros((2,2)))
    monkeypatch.setattr(farhills_grid,'mesh_grid',lambda n:grid)
    monkeypatch.setattr(farhills_grid,'source_grid',lambda:grid)
    monkeypatch.setattr(layout,'H',None)
    monkeypatch.setattr(layout,'coastal_backdrop_height',lambda x,y,z:np.full_like(x,10.25))
    monkeypatch.setattr(earthworks,'carve',lambda x,y,z:z)
    def query(xs,ys,z,x,y,**kwargs):
        np.testing.assert_array_equal(x,[-350.])
        np.testing.assert_array_equal(y,[-125.])
        np.testing.assert_array_equal(kwargs['edge_knots'][0,-300.],[-300.,0.,300.])
        return kwargs['shape'](x,y,np.zeros_like(x))
    monkeypatch.setattr(S,'sample_grid_mesh',query)
    D.repair_west_forest(world,np.zeros((3,3)),owned)
    assert world['instances']['Tree_Maple_A'][0]==[-350.,-125.,9.95,10.,2.]
    assert world['instances']['Tree_Maple_A'][1:]==before['instances']['Tree_Maple_A'][1:]
    assert world['instances']['SW_Boulder_A']==before['instances']['SW_Boulder_A']
    monkeypatch.setattr(earthworks,'carve',lambda x,y,z:z-1.)
    with pytest.raises(ValueError,match='overlaps railway'):
        D.repair_west_forest(world,np.zeros((3,3)),owned)


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


def test_city_street_starts_at_this_worlds_road_not_a_stale_or_missing_world_json(tmp_path, monkeypatch):
    # gen_world dresses the coast before it writes world.json: a clean build directory has none, and an incremental
    # one holds the previous world's road. The city street profile must start at the road being generated.
    import json
    from hidamari import layout
    import train.corridor
    monkeypatch.setattr(yori, 'OUT', tmp_path)
    # integrate() sets both module globals: register their restoration (or removal) before it runs.
    monkeypatch.setattr(layout, 'H', getattr(layout, 'H', None), raising=False)
    monkeypatch.setattr(layout.street_height, 'start', None, raising=False)
    monkeypatch.delattr(layout.street_height, 'start')
    monkeypatch.setattr(D, 'placements', lambda ground: {})
    monkeypatch.setattr(train.corridor, 'clear_instances', lambda objects: None)
    world = {'road': [[-300., -99., 8.], [295., 82., 21.], [120., 40., 15.]], 'instances': {}}
    D.integrate(world, np.zeros((64, 64), np.float32))
    assert list(layout.street_height.start) == [295., 82.]
    (tmp_path / 'world.json').write_text(json.dumps({'road': [[290., 70., 20.]]}))
    D.integrate(world, np.zeros((64, 64), np.float32))
    assert list(layout.street_height.start) == [295., 82.]
