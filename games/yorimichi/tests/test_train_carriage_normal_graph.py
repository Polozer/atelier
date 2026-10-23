"""The complete normal recipe admits selected carriage owners and isolated diagnostics."""
from pathlib import Path
from types import SimpleNamespace
import argparse
import ast

import pytest

from atelier import build, build_batches, build_cache
from atelier.build_products import Graph

GAME = Path(__file__).resolve().parents[1]


def recipe(out):
    ctx = SimpleNamespace(out=out.resolve(), game='yorimichi', uproject=None)
    steps = build.load_recipe('yorimichi').steps(ctx)
    return ctx, steps, {step.name: step for step in steps}


def test_complete_recipe_validates_batches_and_portable_ownership(tmp_path):
    ctx, steps, rows = recipe(tmp_path)
    Graph(steps).select(['world.belmonte_train_service'])
    for step in steps:
        build_batches.validate(step)
        if step.cache:
            build_cache.roots(ctx, step)
    production = build.order(steps, ['world.belmonte_train'])
    assert {step.name for step in production} == {
        'world.belmonte_train', 'world.belmonte_train.addon',
        *(f'world.belmonte_train.{kind}.{coach}' for kind in ('request', 'source')
          for coach in ('locomotive', 'tender', 'baggage-van', 'restaurant', 'first-class', 'second-class', 'brake-van'))}
    assert isinstance(rows['world.belmonte_train'].commands[0], build.Call)
    assert all(command.script != GAME / 'world/train/build.py'
               for step in production for command in step.commands if isinstance(command, build.Blender))
    assert 'world.belmonte_train_furniture_lods' not in {step.name for step in production}


def test_service_requires_complete_source_library_and_real_reader_closure(tmp_path):
    _, _, rows = recipe(tmp_path)
    service = rows['world.belmonte_train_service']
    assert service.commands[0].args == ('--source-library', str(tmp_path / 'belmonte-train/service-meshes.json'))
    assert 'belmonte_train.library' in service.reads
    assert {'world.belmonte_train_route', 'world.belmonte_train_assembly'} <= set(service.needs)
    for relative in ('world/train/service_meshes.py', 'world/train/carriage_mesh.py',
                     'world/train/bake_manifest.py', 'world/train/budgets.py', 'tools/gltf_subset.py'):
        assert GAME / relative in service.inputs
    assert any(path.name == 'file_copy.py' for path in service.inputs)
    assert 'world.belmonte_train_furniture_lods' in rows['world.belmonte_train_assembly'].needs


def test_legacy_blend_review_has_an_explicit_disjoint_authoring_root(tmp_path):
    _, steps, rows = recipe(tmp_path)
    authoring = rows['world.belmonte_train_authoring']; review = rows['world.belmonte_train_review']
    source = tmp_path / 'belmonte-train-authoring'
    assert authoring.explicit and review.explicit
    assert authoring.commands[0].args == ('--output', str(source))
    assert review.commands[0].args == ('--source', str(source))
    assert review.needs == ['world.belmonte_train_authoring']
    assert all(path.is_relative_to(source) for path in authoring.outputs + review.outputs)
    assert not any(step.name == authoring.name for step in build.order(steps, ['world.belmonte_train_service']))


def test_authoring_entry_rejects_production_before_invoking_legacy_builder(tmp_path):
    # Execute the actual CLI function without importing Blender or running a constructor.
    source = GAME / 'world/train/authoring_review.py'
    node = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    calls = []
    builder = SimpleNamespace(main=lambda: calls.append(True))
    namespace = dict(argparse=argparse, Path=Path, yori=SimpleNamespace(OUT=tmp_path), builder=builder, __doc__='diagnostic')
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    with pytest.raises(ValueError, match='isolated'):
        namespace['main'](['--output', str(tmp_path / 'belmonte-train')])
    assert calls == []
    namespace['main'](['--output', str(tmp_path / 'belmonte-train-authoring')])
    assert calls == [True]
    assert builder.OUT == tmp_path / 'belmonte-train-authoring'
    assert builder.TEX == builder.OUT / 'textures'
