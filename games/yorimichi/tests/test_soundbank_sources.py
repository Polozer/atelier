"""Soundbank coverage, committed source admission and failed-publication safety."""
import ast
import fnmatch
import importlib.util
import io
import json
from pathlib import Path
import re
import tomllib
import wave

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('soundbank_prepare', GAME / 'assets/audio/soundbanks/prepare.py')
banks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(banks)


def write(path, data):
    path.write_text(json.dumps(data, indent=2))


def pcm(frames, frequency=300):
    samples = np.sin(np.arange(frames) * (2 * np.pi * frequency / banks.RATE)) * .15
    payload = io.BytesIO()
    with wave.open(payload, 'wb') as handle:
        handle.setparams((1, 2, banks.RATE, 0, 'NONE', 'not compressed'))
        handle.writeframes(np.rint(samples * 32767).astype('<i2').tobytes())
    return payload.getvalue()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'sources'
    root.mkdir()
    original = {'id': 'original', 'name': 'Original', 'selection': 0, 'legacy': True}
    catalog = {'version': 1, 'default': 'original', 'banks': [original]}
    write(root / 'catalog.json', catalog)
    folder = root / 'soft_contact'
    (folder / 'samples').mkdir(parents=True)
    manifest = {'version': 1, 'id': 'soft_contact', 'cues': {}, 'sources': {},
                'inherit_original': list(banks.INHERITED)}
    for cue_index, (cue, (loop, minimum, _)) in enumerate(banks.CUES.items()):
        names = []
        for index in range(minimum):
            name = cue.replace('.', '_') + f'_{index + 1:02d}'
            names.append(name)
            frames, overlap = (banks.RATE, 2400) if loop else (banks.RATE // 5, 0)
            path = folder / 'samples' / f'{name}.wav'
            path.write_bytes(pcm(frames, 300 + cue_index * 50 + index * 5))
            manifest['sources'][name] = {
                'file': f'samples/{name}.wav', 'sha256': banks.digest(path),
                'provenance': {'model': 'stable-audio-3-small-sfx', 'source_revision': 'a' * 40,
                               'weight_revision': 'b' * 40, 'prompt': 'Synthetic fixture only', 'seed': index,
                               'raw_sha256': 'c' * 64, 'processor_sha256': 'd' * 64,
                               'interval_frames_48k': [0, frames + overlap], 'crossfade_frames': overlap,
                               'sampler': {'steps': 8, 'cfg': 1, 'dit_dtype': 'fp16', 'decoder': 'same-s'}}}
        manifest['cues'][cue] = names
    write(folder / 'bank.json', manifest)
    catalog['banks'].append({'id': 'soft_contact', 'name': 'Soft Contact', 'selection': 1,
                             'manifest': 'soft_contact/bank.json', 'sha256': banks.digest(folder / 'bank.json')})
    write(root / 'catalog.json', catalog)
    return root, catalog, manifest, tmp_path / 'products'


def update(root, catalog, manifest):
    write(root / 'soft_contact/bank.json', manifest)
    catalog['banks'][1]['sha256'] = banks.digest(root / 'soft_contact/bank.json')
    write(root / 'catalog.json', catalog)


def test_original_delegates_without_rewriting_legacy_sources(tmp_path):
    path = GAME / 'assets/audio/soundbanks/catalog.json'
    before = path.read_bytes()
    result = banks.prepare(path, tmp_path / 'products')
    assert result['default'] == 'original'
    assert result['banks'] == [{'id': 'original', 'name': 'Original', 'selection': 0, 'legacy': True}]
    assert not (tmp_path / 'products/media').exists()
    assert path.read_bytes() == before


def test_coverage_tracks_actual_legacy_materials_and_skate_surface_slots():
    tree = ast.parse((GAME / 'unreal/Scripts/import_footsteps.py').read_text())
    mapping = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'MATERIAL_SURFACES' for t in n.targets))
    assert set(banks.FOOT_SURFACES) == set(mapping.values())
    root = GAME.parents[1]
    source = root / 'platform/engine/Plugins/Activities/Skate/Source/AtelierSkate/Private/SkateComponent.cpp'
    slots = re.search(r'USkateComponent::SurfaceRolls = \{([^}]+)\}', source.read_text()).group(1)
    assert banks.SKATE_SURFACES == ('concrete', *re.findall(r'TEXT\("([a-z]+)"\)', slots))


def test_all_other_platform_cue_families_explicitly_inherit_original():
    declared = tomllib.loads((GAME.parents[1] / 'platform/conventions/sound-cues.toml').read_text())
    replaced = {'footstep.<surface>', 'skate.roll.<surface>', 'skate.land'}
    for cue in declared.keys() - replaced:
        example = re.sub(r'<[^>]+>', 'reference', cue)
        assert any(fnmatch.fnmatchcase(example, pattern) for pattern in banks.INHERITED), cue


@pytest.mark.parametrize('damage', ['default', 'selection', 'inherit', 'coverage', 'alias', 'byte_alias', 'interval', 'checksum'])
def test_invalid_bank_fails_before_index_publication(source, damage):
    root, catalog, manifest, output = source
    if damage == 'default': catalog['default'] = 'soft_contact'
    elif damage == 'selection': catalog['banks'][1]['selection'] = True
    elif damage == 'inherit': manifest['inherit_original'].remove('horse.hoof')
    elif damage == 'coverage': del manifest['cues']['skate.roll.metal']
    elif damage == 'alias': manifest['cues']['footstep.wood'][0] = manifest['cues']['footstep.grass'][0]
    elif damage == 'byte_alias':
        originals = list(manifest['sources'].values())
        (root / 'soft_contact' / originals[1]['file']).write_bytes(
            (root / 'soft_contact' / originals[0]['file']).read_bytes())
        originals[1]['sha256'] = originals[0]['sha256']
    elif damage == 'interval': next(iter(manifest['sources'].values()))['provenance']['interval_frames_48k'][1] += 1
    elif damage == 'checksum': next(iter(manifest['sources'].values()))['sha256'] = '0' * 64
    update(root, catalog, manifest)
    with pytest.raises(ValueError):
        banks.prepare(root / 'catalog.json', output)
    assert not (output / 'manifest.json').exists()
    assert not (output / 'media').exists()


def test_changed_audio_interruption_preserves_published_index_and_bytes(source, monkeypatch):
    root, catalog, manifest, output = source
    prior = banks.prepare(root / 'catalog.json', output)
    index = (output / 'manifest.json').read_bytes()
    prior_files = {s['product']: (output / s['product']).read_bytes()
                   for b in prior['banks'] for s in b.get('sources', {}).values()}
    sample = next(iter(manifest['sources'].values()))
    path = root / 'soft_contact' / sample['file']
    path.write_bytes(pcm(banks.RATE // 5, 470))
    sample['sha256'] = banks.digest(path)
    update(root, catalog, manifest)
    def interrupt(*args):
        raise RuntimeError('Interrupted before index publication')
    monkeypatch.setattr(banks.os, 'replace', interrupt)
    with pytest.raises(RuntimeError, match='Interrupted'):
        banks.prepare(root / 'catalog.json', output)
    assert (output / 'manifest.json').read_bytes() == index
    assert all((output / name).read_bytes() == content for name, content in prior_files.items())


def test_corrupt_existing_product_is_not_repaired_by_overwrite(source):
    root, _, _, output = source
    report = banks.prepare(root / 'catalog.json', output)
    name = next(iter(report['banks'][1]['sources'].values()))['product']
    (output / name).write_bytes(b'corrupt')
    index = (output / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='Existing immutable'):
        banks.prepare(root / 'catalog.json', output)
    assert (output / name).read_bytes() == b'corrupt'
    assert (output / 'manifest.json').read_bytes() == index


def test_symlink_escape_and_clipped_source_are_rejected(source, tmp_path):
    root, catalog, manifest, output = source
    first = next(iter(manifest['sources'].values()))
    path = root / 'soft_contact' / first['file']
    outside = tmp_path / 'outside.wav'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='WAV path'):
        banks.prepare(root / 'catalog.json', output)
    path.unlink()
    payload = bytearray(outside.read_bytes())
    payload[44:46] = b'\xff\x7f'
    path.write_bytes(payload)
    first['sha256'] = banks.digest(path)
    update(root, catalog, manifest)
    with pytest.raises(ValueError, match='clipped'):
        banks.prepare(root / 'catalog.json', output)
