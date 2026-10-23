"""Every step passes the declaration checks the build runs at launch, before any work."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from atelier import build_batches, build_cache

GAME = Path(__file__).resolve().parents[1]


def test_cached_and_batched_steps_pass_launch_validation(tmp_path):
    # A refused declaration stops a full build before its first step, so check the whole recipe here.
    spec = importlib.util.spec_from_file_location('yorimichi_launch_recipe', GAME / 'build.py')
    recipe = importlib.util.module_from_spec(spec); spec.loader.exec_module(recipe)
    ctx = SimpleNamespace(game='yorimichi', out=tmp_path, uproject=tmp_path / 'Yorimichi.uproject')
    for step in recipe.steps(ctx):
        build_batches.validate(step)
        if step.cache and not step.audit:
            build_cache.roots(ctx, step)
