"""Registry publication is exact and atomic; native certification belongs to its graph edge."""
import importlib.util
import json
from pathlib import Path

import pytest

GAME = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('soundbank_stage', GAME / 'soundbank_stage.py')
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


@pytest.fixture
def registry(tmp_path):
    source = tmp_path / 'out/soundbank_import/registry.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'version': 1, 'default': 'original', 'banks': [{'id': 'original'}],
                                 'native': {'plan_sha256': '1' * 64, 'packages': {'original/Audition.uasset': '2' * 64}}}))
    return tmp_path / 'out', source, tmp_path / 'Content/Data/Soundbanks'


def test_staging_preserves_exact_native_registry_bytes(registry):
    out, source, destination = registry
    staging.stage(out, destination)
    assert (destination / 'registry.json').read_bytes() == source.read_bytes()


@pytest.mark.parametrize('failure', ['candidate', 'replace', 'source_changed'])
def test_failed_staging_preserves_previous_registry(registry, monkeypatch, failure):
    out, source, destination = registry
    destination.mkdir(parents=True)
    previous = destination / 'registry.json'
    previous.write_bytes(b'previous complete registry')
    if failure == 'candidate':
        source.write_text(json.dumps({'plan_sha256': '1' * 64, 'packages': {'original/Audition.uasset': '2' * 64}}))
    elif failure == 'replace':
        def fail(*args):
            raise OSError('controlled publication failure')
        monkeypatch.setattr(staging.os, 'replace', fail)
    else:
        read = Path.read_bytes
        calls = 0
        def changed(path):
            nonlocal calls
            if path == source:
                calls += 1
                if calls == 2:
                    return b'changed after copying'
            return read(path)
        monkeypatch.setattr(Path, 'read_bytes', changed)
    with pytest.raises((ValueError, OSError)):
        staging.stage(out, destination)
    assert previous.read_bytes() == b'previous complete registry'
    assert list(destination.iterdir()) == [previous]
