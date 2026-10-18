"""The production map recipe reaches the common guard and preserves a stopped job."""
import io
from types import SimpleNamespace

import pytest

from atelier import build, build_source


@pytest.mark.parametrize('exit_code', [0, 9], ids=['success', 'guard-stop'])
def test_map_generation_uses_guarded_admission(tmp_path, monkeypatch, exit_code):
    ctx = SimpleNamespace(game='yorimichi', out=tmp_path/'out', logs=tmp_path/'logs', uproject=None)
    recipe = build.load_recipe('yorimichi')
    step = next(step for step in recipe.steps(ctx) if step.name == 'world.map')
    command = step.commands[0]
    calls = []

    def guarded_run(argv, folder, **options):
        calls.append((argv, folder, options))
        folder.mkdir(parents=True)
        (folder/'stdout.log').write_text('map output\n')
        return exit_code

    monkeypatch.setattr(build_source.guarded, 'run', guarded_run)
    monkeypatch.setattr(build_source.subprocess, 'run',
                        lambda *args, **kwargs: pytest.fail('Map bypassed guarded admission'))
    log = io.StringIO()
    if exit_code:
        with pytest.raises(RuntimeError, match='world.map: command exited 9'):
            build.run_command(ctx, step, command, log)
    else:
        build.run_command(ctx, step, command, log)

    assert len(calls) == 1
    argv, folder, options = calls[0]
    assert argv == command.argv(ctx)
    assert command.script == recipe.WORLD/'map'/'build_map.py'
    assert folder == ctx.logs/'world.map.guard'
    assert options['purpose'] == 'atelier build yorimichi world.map'
    assert options['kind'] == 'job' and options['small_gib'] is None
    assert options.get('limit_gib', 10.) == 10.
    assert 'map output' in log.getvalue()
