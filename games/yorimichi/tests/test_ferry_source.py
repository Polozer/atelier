"""The region importer must retain the audited opening and refuse stale source/product identities."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
from regions.hidamari.ferry_source import validated_harbor  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def proof(tmp_path):
    repo = tmp_path / 'repo'; build = repo / 'build/yorimichi'
    paths = {'code': repo / 'games/yorimichi/world/regions/hidamari/ferry_cut.py',
             'layout': repo / 'games/yorimichi/world/regions/ferry/route.py',
             'ground': build / 'terrain/final.npz',
             'base': build / 'hidamari/assets/HD_Harbor.fbx',
             'site': build / 'ferry/terminals/site.json',
             'mesh': build / 'hidamari/ferry/HD_Harbor.fbx',
             'receipt': build / 'hidamari/ferry/cut.json'}
    for key in ('code', 'layout', 'ground', 'base', 'mesh'):
        p = paths[key]; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(key)
    paths['site'].parent.mkdir(parents=True, exist_ok=True)
    site = {'pass': True, 'inputs': {'code': {str(paths[k].relative_to(repo)): sha(paths[k]) for k in ('code', 'layout')},
            'exports': {'hidamari': {str(paths[k].relative_to(build)): sha(paths[k]) for k in ('base', 'ground')}}}}
    paths['site'].write_text(json.dumps(site))
    cut = {'failures': [], 'cuts': [{'cap_normals_pass': True}],
           'source': str(paths['base'].relative_to(build)), 'site': str(paths['site'].relative_to(build)),
           'inputs': {str(paths[k].relative_to(repo)): sha(paths[k]) for k in ('code', 'base', 'site')},
           'output_sha256': sha(paths['mesh'])}
    paths['receipt'].write_text(json.dumps(cut))
    return repo, build, paths, cut


def test_importer_selects_only_the_final_region_source(tmp_path):
    repo, build, paths, _ = proof(tmp_path)
    assert validated_harbor(build, repo) == paths['mesh']
    assert validated_harbor(build, repo) != paths['base']


@pytest.mark.parametrize('changed', ['code', 'layout', 'ground', 'base', 'site', 'mesh'])
def test_changed_source_or_product_refuses(tmp_path, changed):
    repo, build, paths, _ = proof(tmp_path)
    if changed == 'site':
        site = json.loads(paths['site'].read_text()); site['pass'] = False
        paths['site'].write_text(json.dumps(site))
    else:
        paths[changed].write_text('changed')
    with pytest.raises(ValueError, match='failed|changed'):
        validated_harbor(build, repo)


@pytest.mark.parametrize('change', ['inward-cap', 'missing-cuts', 'different-source'])
def test_failed_or_incomplete_cut_refuses(tmp_path, change):
    repo, build, paths, cut = proof(tmp_path)
    if change == 'inward-cap': cut['cuts'][0]['cap_normals_pass'] = False
    elif change == 'missing-cuts': cut['cuts'] = []
    else: cut['source'] = 'hidamari/assets/another.fbx'
    paths['receipt'].write_text(json.dumps(cut))
    with pytest.raises(ValueError, match='failed|different source'):
        validated_harbor(build, repo)
