"""Menu auditions use real source products and reject stale/invalid inputs."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from atelier import build, build_products
from test_soundbank_sources import banks, pcm, source  # noqa: F401 (shared complete-bank fixture)


GAME = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('soundbank_previews', GAME / 'assets/audio/soundbank_previews/build.py')
previews = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previews)


@pytest.fixture
def inputs(source, tmp_path):
    root, _, _, prepared = source
    banks.prepare(root / 'catalog.json', prepared)
    footsteps, skate = tmp_path / 'footsteps', tmp_path / 'skate'
    (footsteps / 'stone').mkdir(parents=True)
    for i in range(4):
        (footsteps / 'stone' / f'stone_{i:02}.wav').write_bytes(pcm(9600, 120 + 30 * i))
    for i, kind in enumerate(('roll', 'skid', 'land')):
        (skate / kind).mkdir(parents=True)
        (skate / kind / f'{kind}_01.wav').write_bytes(pcm(48000 if kind != 'land' else 9600, 400 + 70 * i))
    return root / 'catalog.json', prepared, footsteps, skate, tmp_path / 'previews'


def test_deterministic_complete_pcm_and_source_identity(inputs):
    catalog, prepared, foot, skate, output = inputs
    before = {p: p.read_bytes() for root in (prepared, foot, skate) for p in root.rglob('*.wav')}
    report = previews.build(*inputs)
    assert [e['id'] for e in report['banks']] == ['original', 'soft_contact']
    assert {e['root'] for e in report['sources']} == {'footsteps', 'skate', 'prepared'}
    hashes = {entry['id']: entry['sha256'] for entry in report['banks']}
    assert len(set(hashes.values())) == 2
    for entry in report['banks']:
        with wave.open(str(output / entry['file']), 'rb') as stream:
            assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()) == (1, 2, 48000, 16 * 48000)
            audio = np.frombuffer(stream.readframes(stream.getnframes()), '<i2').astype(float)
        assert all(np.sqrt(np.mean(section ** 2)) > 1 for section in np.split(audio, 4))
        assert entry['bytes'] == 44 + 16 * 48000 * 2
    assert report == previews.build(*inputs)
    assert all(p.read_bytes() == payload for p, payload in before.items())


def test_missing_original_media_fails_before_any_output(inputs):
    (inputs[3] / 'skid/skid_01.wav').unlink()
    with pytest.raises(ValueError, match='Original concrete skate pool'):
        previews.build(*inputs)
    assert not inputs[-1].exists()


def test_prepared_corruption_and_stale_index_fail_before_output(inputs):
    manifest = json.loads((inputs[1] / 'manifest.json').read_text())
    bank = manifest['banks'][1]
    selected = bank['sources'][bank['cues']['footstep.stone'][0]]
    path = inputs[1] / selected['product']
    original = path.read_bytes()
    path.write_bytes(pcm(9600, 912))
    with pytest.raises(ValueError, match='checksum'):
        previews.build(*inputs)
    assert not inputs[-1].exists()
    path.write_bytes(original)
    manifest['catalog_sha256'] = '0' * 64
    (inputs[1] / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='stale'):
        previews.build(*inputs)
    assert not inputs[-1].exists()


def test_source_change_during_render_does_not_publish_index(inputs, monkeypatch):
    render = previews.render
    def change(pool):
        result = render(pool)
        (inputs[2] / 'stone/stone_00.wav').write_bytes(pcm(9600, 987))
        return result
    monkeypatch.setattr(previews, 'render', change)
    with pytest.raises(ValueError, match='media changed'):
        previews.build(*inputs)
    assert not (inputs[-1] / 'manifest.json').exists()


def test_normal_graph_owns_and_reads_complete_audio_products(tmp_path):
    recipe = build.load_recipe('yorimichi')
    graph = build_products.Graph(recipe.steps(SimpleNamespace(game='yorimichi', out=tmp_path, uproject=None)))
    step = graph.by_name['audio.soundbank_previews']
    assert set(step.reads) == {'audio.soundbanks', 'audio.footsteps', 'audio.skate'}
    assert {s.name for s in graph.select([step.name])} == {step.name, *step.reads}
    for name in step.reads:
        assert graph.owners[name] == name
        assert graph.by_name[name].products[0].paths == (tmp_path / 'audio' / name.split('.')[-1],)
