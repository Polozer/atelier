"""treehouse_props.model (the tree house, Hidamari and Crater Park shrine props) submits a paid Tripo job only after
claiming its submission marker by exclusive creation: a held marker refuses before any upload, and the claim is given
back only when no generation POST was sent."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'


@pytest.fixture
def props(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location('treehouse_props_claim_test', TOOLS / 'treehouse_props.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import atelier.ai.tripo_asset as tripo
    monkeypatch.setattr(tripo, 'credential', lambda: 'test')
    monkeypatch.setattr(tripo, 'fetch', lambda client, work, wait: pytest.fail('no job was submitted'))
    return module, tripo


def prop(tmp_path):
    folder = tmp_path / 'out' / 'lantern'; folder.mkdir(parents=True, exist_ok=True)
    (folder / 'concept.jpg').write_bytes(b'concept')
    (folder / 'concept.json').write_text(json.dumps({'concept_sha256': hashlib.sha256(b'concept').hexdigest()}))
    return dict(out=tmp_path / 'out', tripo=tmp_path / 'tripo', originals=tmp_path / 'originals', record='concept.json')


def model(module, tmp_path):
    return module.model('lantern', 5000, 'test', False, **prop(tmp_path))


def test_a_held_marker_refuses_before_any_upload(props, tmp_path, monkeypatch):
    module, tripo = props
    calls = []
    monkeypatch.setattr(tripo, 'call', lambda client, method, path, **kw: calls.append(path))
    marker = tripo.private_folder(tmp_path / 'tripo' / 'lantern') / 'submission-started.json'
    marker.write_text('{}')
    slug, error = model(module, tmp_path)
    assert 'another submission is running' in error and calls == [] and marker.exists()


def test_a_failed_upload_gives_the_claim_back(props, tmp_path, monkeypatch):
    module, tripo = props
    def call(client, method, path, **kw):
        raise RuntimeError('upload refused')
    monkeypatch.setattr(tripo, 'call', call)
    slug, error = model(module, tmp_path)
    assert 'upload refused' in error
    assert not (tmp_path / 'tripo' / 'lantern' / 'api-private' / 'submission-started.json').exists()


def test_a_failed_generation_post_keeps_the_marker(props, tmp_path, monkeypatch):
    module, tripo = props
    calls = []
    def call(client, method, path, **kw):
        calls.append(path)
        if path == '/files':
            return {'data': {'file_token': 'token'}}
        raise RuntimeError('read timed out')
    monkeypatch.setattr(tripo, 'call', call)
    slug, error = model(module, tmp_path)
    assert calls == ['/files', '/generation/image-to-model'] and 'read timed out' in error
    marker = tmp_path / 'tripo' / 'lantern' / 'api-private' / 'submission-started.json'
    assert json.loads(marker.read_text())['request']['input'] == 'token'
    assert model(module, tmp_path)[1].startswith('another submission is running') and len(calls) == 2


def test_a_task_recorded_before_a_late_claim_is_not_submitted_again(props, tmp_path, monkeypatch):
    """A second caller decides no task is recorded, and before it claims the marker the first caller submits, records
    the task and releases the marker: once claimed, the second caller sees the recorded task and only fetches it."""
    module, tripo = props
    calls = []
    def call(client, method, path, **kw):
        calls.append(path)
        return {'data': {'file_token': 'token'}} if path == '/files' else {'data': {'task_id': 'task'}}
    monkeypatch.setattr(tripo, 'call', call)
    def fetch(client, work, wait):
        raise RuntimeError('fetched the recorded task')
    monkeypatch.setattr(tripo, 'fetch', fetch)
    claim, interleaved = module.os.open, []
    def late_open(path, flags, *args):
        if str(path).endswith('submission-started.json') and not interleaved:
            interleaved.append(True)
            assert 'fetched the recorded task' in model(module, tmp_path)[1]
        return claim(path, flags, *args)
    monkeypatch.setattr(module.os, 'open', late_open)
    assert 'fetched the recorded task' in model(module, tmp_path)[1]
    assert calls == ['/files', '/generation/image-to-model']
    assert not (tmp_path / 'tripo' / 'lantern' / 'api-private' / 'submission-started.json').exists()
