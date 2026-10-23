"""Selected Gondola command ownership and complete ordinary graph declarations."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

GAME = Path(__file__).resolve().parents[1]


def load(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


commands = load('gondola_commands_test',GAME / 'assets/vehicles/gondola/commands.py')
graph = load('gondola_graph_test',GAME / 'gondola_atomic_build.py')


class Mesh:
    def __init__(self,name):
        self.name = name; self.events = []; self.parts = []; self.origins = []

    @contextmanager
    def at(self,*args,**kwargs):
        self.events.append(('enter',args,kwargs))
        try: yield
        finally: self.events.append(('exit',))

    def box(self,*args,**kwargs):
        self.events.append(('box',args,kwargs))
        self.parts.append((0,1)); self.origins.append('replay')


def test_selected_replay_retains_nested_order_and_author_origin():
    recorder = commands.Recorder('GD_Selected')
    with recorder.at((2,3,4),yaw=37):
        recorder.box((1,2,3),(4,5,6),'GD_Timber')
        with recorder.at((0,1,0)):
            recorder.box((7,8,9),(1,1,1),'GD_Stone')
    mesh = commands.replay(dict(schema=1,asset=recorder.name,commands=recorder.commands),Mesh)
    assert [row[0] for row in mesh.events] == ['enter','box','enter','box','exit','exit']
    assert mesh.events[1][1] == ([1,2,3],[4,5,6],'GD_Timber')
    assert mesh.origins == [row[4] for row in recorder.commands if row[0] == 'primitive']
    assert all('test_gondola_atomic_build.py:' in origin for origin in mesh.origins)


@pytest.mark.parametrize('stream',[
    [['exit','at']], [['enter','at',[],{}]],
    [['enter','at',[],{}],['exit','wall']],
    [['primitive','unknown',[],{},'source:1']],
    [['primitive','box',[float('nan')],{},'source:1']],
])
def test_invalid_stream_refuses_before_any_geometry(stream):
    constructed = []
    class Tracked(Mesh):
        def __init__(self,name): constructed.append(name); super().__init__(name)
    with pytest.raises(ValueError):
        commands.replay(dict(schema=1,asset='GD_Selected',commands=stream),Tracked)
    assert constructed == []


def test_unknown_source_operation_and_unpublished_height_refuse():
    recorder = commands.Recorder('GD_Selected')
    with pytest.raises(AttributeError): recorder.new_primitive()
    height = commands.thaw(dict(height_samples=[[1.,2.,3.],[4.,5.,6.]]))
    assert height(1.,2.) == 3.
    with pytest.raises(ValueError): height(1.,2.000000001)


def test_kit_planners_own_one_selected_source_and_query(tmp_path):
    steps = graph.kit_steps(SimpleNamespace(out=tmp_path))
    parameters,render,collision = graph.kit_names()
    planners = [step for step in steps if step.name.startswith('world.gondola_kit.geometry.')]
    assert len(planners) == len(render) == 23
    for step,key in zip(planners,render):
        assert step.reads == ['gondola_kit.source.'+key]
        assert len(step.products) == 2
        assert step.products[1].name == 'gondola_kit.query.'+key
        assert step.commands[0].threads == 3
        assert step.commands[0].factory_startup is True
    collisions = [step for step in steps if step.name.startswith('world.gondola_kit.collision.')]
    assert len(collisions) == len(collision) == 10
    assert len({path for step in planners+collisions for product in step.products for path in product.paths}) == 56
    final = next(step for step in steps if step.name == 'world.gondola_kit')
    assert final.reads[:3] == ['gondola_kit.atomic','gondola_kit.audit','gondola_kit.textures']


def test_site_planners_own_selected_commands_and_declare_complete_query_membership(tmp_path):
    steps=graph.site_steps(SimpleNamespace(out=tmp_path))
    planners=[step for step in steps if step.name.startswith('world.gondola_site.geometry.')]
    assert len(planners)==31
    for step in planners:
        key=step.name.rsplit('.',1)[-1]
        assert step.reads==['gondola_site.source.'+key]
        assert step.products[1].name=='gondola_site.query.'+key
        assert step.commands[0].threads==3 and step.commands[0].factory_startup
    query_steps=graph.query_steps(SimpleNamespace(out=tmp_path))
    structure=next(step for step in query_steps if step.name=='world.gondola_structures_sources')
    assert 'belmonte_north.geometry.SM_BM_NorthCountry' in structure.reads
    assert all(not name.startswith('world.') and '.export.' not in name for name in structure.reads)
    assert not structure.deferred_inputs
    assert tmp_path/'gondola/world/structure-source-data' in structure.products[0].paths


def test_actual_full_cold_recipe_graph_accepts_source_products_and_legacy_collectors(tmp_path,monkeypatch):
    from atelier import build
    from atelier.build_products import Graph
    recipe=build.load_recipe('yorimichi')
    original=recipe.gondola_steps
    def migrated(ctx):
        retained=[step for step in original(ctx) if step.name=='world.gondola_service' or step.name.startswith('unreal.')]
        return [*graph.kit_steps(ctx),*graph.query_steps(ctx),*graph.site_steps(ctx),*retained]
    monkeypatch.setattr(recipe,'gondola_steps',migrated)
    steps=recipe.steps(SimpleNamespace(game='yorimichi',out=tmp_path,uproject=None))
    complete=Graph(steps)
    selected=complete.select(['world.gondola_site'])
    names=[step.name for step in selected]
    assert 'world.gondola_structures_sources' in names
    assert names.index('world.gondola_ground_sources')<names.index('world.gondola_ground_inputs')
    assert names.index('world.gondola_structures_sources')<names.index('world.gondola_structure_inputs')
    assert not any('.export.' in name and ('belmonte' in name or 'hidamari' in name) for name in names)
    projection=complete.by_name['world.gondola_structures_sources']
    assert not projection.deferred_inputs and projection.cache
    for name in ('world.gondola_structure_inputs','world.gondola_ground_inputs'):
        legacy=complete.by_name[name]
        assert legacy.deferred_inputs and not legacy.reads and not legacy.products and not legacy.cache

    source=graph.load('gondola_graph_source_coverage',graph.WORLD/'gondola/source_inputs.py')
    for key in source.structure_keys():
        product='belmonte_models.geometry.'+key
        owner=complete.by_name[complete.owners[product]]
        assert tmp_path/'planned_exports/belmonte_models'/key in next(p for p in owner.products if p.name==product).paths
    country='belmonte_north.geometry.SM_BM_NorthCountry'
    owner=complete.by_name[complete.owners[country]]
    assert tmp_path/'planned_exports/belmonte_north/SM_BM_NorthCountry' in next(p for p in owner.products if p.name==country).paths
