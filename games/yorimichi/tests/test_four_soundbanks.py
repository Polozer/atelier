"""The shipped choices contain independent complete banks through native preflight."""
import json
from pathlib import Path

from test_soundbank_sources import banks, source  # noqa: F401
from test_soundbank_previews import inputs, previews  # noqa: F401
from test_soundbank_import_plan import planner
from test_soundbank_native_import import consumer


SOURCE = Path(__file__).resolve().parents[1] / 'assets/audio/soundbanks'
CHOICES = [('original', 0), ('soft_contact', 1), ('dry_street', 2), ('warm_motion', 3)]


def test_shipped_four_choices_have_complete_independent_sources():
    catalog = banks.catalog(SOURCE / 'catalog.json')
    assert catalog['default'] == 'original'
    assert [(b['id'], b['selection']) for b in catalog['banks']] == CHOICES
    assert catalog['banks'][0] == dict(id='original', name='Original', selection=0, legacy=True)
    hashes = set()
    for entry in catalog['banks'][1:]:
        manifest = json.loads((SOURCE / entry['manifest']).read_text())
        assert len(entry['sources']) == 53
        assert sum(s['bytes'] for s in entry['sources'].values()) <= banks.MAX_BANK_BYTES
        current = {s['sha256'] for s in entry['sources'].values()}
        assert len(current) == 53 and hashes.isdisjoint(current)
        hashes.update(current)
        for cue, names in manifest['cues'].items():
            origins = {manifest['sources'][n]['provenance']['raw_sha256'] for n in names}
            if cue.startswith(('footstep.', 'skate.land.')):
                assert len(origins) >= 2, (entry['id'], cue)
            else:
                assert len(names) == 1  # The runtime supports one loop per slot.


def test_all_four_banks_reach_native_preflight_and_keep_original_audition(inputs, tmp_path):
    _, _, footsteps, skate, _ = inputs
    out = tmp_path / 'four-bank-build'
    banks.prepare(SOURCE / 'catalog.json', out / 'audio/soundbanks')
    previews.build(SOURCE / 'catalog.json', out / 'audio/soundbanks', footsteps, skate,
                   out / 'audio/soundbank_previews')
    plan = planner.build(out, SOURCE)
    assert consumer.preflight(out, SOURCE) == plan
    registry = planner.registry(plan)
    assert [(b['id'], b['selection']) for b in registry['banks']] == CHOICES
    for row in plan['banks']:
        original = row['runtime']['legacy']
        assert len(row['waves']) == (1 if original else 54)
        assert bool(row['runtime']['asset']) is not original
        assert len(row['footsteps']) == (0 if original else 7)
        assert len(row['oneshots']) == (0 if original else 8)
        assert len(row['loops']) == (0 if original else 9)
    assert len({b['audition_sha256'] for b in registry['banks']}) == 4

    control = tmp_path / 'original-only'
    control.mkdir()
    catalog = json.loads((SOURCE / 'catalog.json').read_text())
    catalog['banks'] = catalog['banks'][:1]
    (control / 'catalog.json').write_text(json.dumps(catalog))
    prepared = tmp_path / 'original-prepared'
    audition = tmp_path / 'original-preview'
    banks.prepare(control / 'catalog.json', prepared)
    previews.build(control / 'catalog.json', prepared, footsteps, skate, audition)
    assert (audition / 'original.wav').read_bytes() == (out / 'audio/soundbank_previews/original.wav').read_bytes()
