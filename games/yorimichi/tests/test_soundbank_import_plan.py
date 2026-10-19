"""Portable complete-bank preflight before Unreal can mutate any packages."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from atelier import build, build_products
from test_soundbank_sources import banks, pcm, source, update  # noqa: F401 (shared fixture)
from test_soundbank_previews import inputs, previews  # noqa: F401 (shared fixture)

GAME = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('soundbank_import_plan', GAME / 'soundbank_import.py')
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


@pytest.fixture
def planned(inputs, tmp_path):
    catalog, prepared, footsteps, skate, _ = inputs
    out = tmp_path / 'out'
    product = out / 'audio/soundbanks'
    shutil.copytree(prepared, product)
    previews.build(catalog, product, footsteps, skate, out / 'audio/soundbank_previews')
    return out, catalog.parent, footsteps, skate


def test_portable_plan_maps_complete_native_slots_and_original_is_audition_only(planned):
    out, source, _, _ = planned
    plan = planner.build(out, source)
    assert plan == json.loads((out / 'audio/soundbank_import_plan/manifest.json').read_text())
    original, alternative = plan['banks']
    assert original['runtime']['selection'] == 0 and original['runtime']['legacy']
    assert original['runtime']['asset'] == ''
    assert [w['name'] for w in original['waves']] == ['Audition']
    assert original['footsteps'] == original['oneshots'] == original['loops'] == {}
    assert set(alternative['footsteps']) == set(banks.FOOT_SURFACES)
    assert set(alternative['oneshots']) == {'land' + ('' if s == 'concrete' else '_' + s) for s in banks.SKATE_SURFACES}
    assert set(alternative['loops']) == {'roll' + ('' if s == 'concrete' else '_' + s) for s in banks.SKATE_SURFACES} | {'skid'}
    waves = {w['name'] for w in alternative['waves']}
    assert all(set(names) <= waves for names in alternative['footsteps'].values())
    assert all(set(names) <= waves for names in alternative['oneshots'].values())
    assert set(alternative['loops'].values()) <= waves
    assert all(not Path(w['path']).is_absolute() and '..' not in Path(w['path']).parts
               for row in plan['banks'] for w in row['waves'])
    runtime = planner.registry(plan)
    assert 'waves' not in json.dumps(runtime)
    assert str(out) not in json.dumps(plan)
    assert plan == planner.build(out, source)


def test_corrupt_media_outside_audition_surface_is_still_rejected(planned):
    out, source, _, _ = planned
    doc = json.loads((out / 'audio/soundbanks/manifest.json').read_text())
    entry = doc['banks'][1]
    sample = entry['sources'][entry['cues']['footstep.leaves'][0]]
    path = out / 'audio/soundbanks' / sample['product']
    path.write_bytes(pcm(sample['frames'], 1873))
    with pytest.raises(ValueError, match='checksum'):
        planner.build(out, source)
    assert not (out / 'audio/soundbank_import_plan').exists()


def test_stale_audition_producer_is_rejected_before_plan_publication(planned):
    out, source, _, _ = planned
    path = out / 'audio/soundbank_previews/manifest.json'
    report = json.loads(path.read_text())
    report['producer_sha256'] = '0' * 64
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='auditions'):
        planner.build(out, source)
    assert not (out / 'audio/soundbank_import_plan').exists()


def test_multiple_continuous_variants_fail_instead_of_silently_dropping_one(planned):
    out, source, footsteps, skate = planned
    catalog = json.loads((source / 'catalog.json').read_text())
    manifest = json.loads((source / 'soft_contact/bank.json').read_text())
    cue = 'skate.roll.concrete'
    original = manifest['sources'][manifest['cues'][cue][0]]
    extra = copy.deepcopy(original)
    extra['file'] = 'samples/extra_roll.wav'
    path = source / 'soft_contact' / extra['file']
    path.write_bytes(pcm(48000, 1873))
    extra['sha256'] = banks.digest(path)
    manifest['sources']['extra_roll'] = extra
    manifest['cues'][cue].append('extra_roll')
    update(source, catalog, manifest)
    banks.prepare(source / 'catalog.json', out / 'audio/soundbanks')
    previews.build(source / 'catalog.json', out / 'audio/soundbanks', footsteps, skate, out / 'audio/soundbank_previews')
    with pytest.raises(ValueError, match='one continuous loop'):
        planner.build(out, source)


def test_normal_plan_graph_reads_all_prepared_products(tmp_path):
    recipe = build.load_recipe('yorimichi')
    graph = build_products.Graph(recipe.steps(SimpleNamespace(game='yorimichi', out=tmp_path, uproject=None)))
    step = graph.by_name['audio.soundbank_import_plan']
    assert set(step.reads) == {'audio.soundbanks', 'audio.soundbank_previews'}
    assert {s.name for s in graph.select([step.name])} == {
        step.name, 'audio.soundbanks', 'audio.soundbank_previews', 'audio.footsteps', 'audio.skate'}
