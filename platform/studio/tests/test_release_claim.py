"""Local target ownership and crash-persistent draft intent; no network or native jobs."""
import json
import subprocess
import sys

import pytest

from atelier import release_claim

METADATA = dict(tag_name='game-1', target_commitish='a' * 40, name='game-1', body='notes', prerelease=False)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(release_claim, 'CLAIMS', tmp_path / 'claims')


def test_process_crash_releases_mutex_and_preserves_uncertain_create():
    command = ('import json,os,sys; from pathlib import Path; from atelier import release_claim; '
               'release_claim.CLAIMS=Path(sys.argv[2]); '
               'c=release_claim.acquire("owner/repo",json.loads(sys.argv[1])); '
               'held=c.__enter__(); held.save("creating"); os._exit(0)')
    subprocess.run([sys.executable, '-c', command, json.dumps(METADATA), str(release_claim.CLAIMS)],
                   check=True, timeout=5)
    with release_claim.acquire('owner/repo', METADATA) as claim:
        assert claim.value['state'] == 'creating' and claim.value['release_id'] is None
        assert claim.path.stat().st_mode & 0o777 == 0o600


def test_mutex_inode_is_not_replaced_between_attempts():
    with release_claim.acquire('owner/repo', METADATA) as claim:
        lock = claim.path.with_suffix('.lock')
        inode = lock.stat().st_ino
        claim.save('creating')
    with release_claim.acquire('owner/repo', METADATA) as claim:
        claim.save('selected', 123)
        assert lock.stat().st_ino == inode
    with release_claim.acquire('owner/repo', METADATA) as claim:
        assert claim.value['release_id'] == 123


@pytest.mark.parametrize('damage', ['oversized', 'partial', 'schema', 'state', 'id', 'public'])
def test_damaged_claim_refuses_without_overwriting(damage):
    with release_claim.acquire('owner/repo', METADATA) as claim:
        claim.save('creating')
        path = claim.path
    value = json.loads(path.read_text())
    if damage == 'oversized': path.write_bytes(b' ' * 8193)
    elif damage == 'partial': path.write_bytes(b'{')
    elif damage == 'schema': value['schema'] = True
    elif damage == 'state': value['state'] = 'maybe'
    elif damage == 'id': value['release_id'] = 123
    elif damage == 'public': path.chmod(0o644)
    if damage in ('schema', 'state', 'id'):
        path.write_text(json.dumps(value))
    before = path.read_bytes()
    with pytest.raises(release_claim.ClaimError):
        with release_claim.acquire('owner/repo', METADATA):
            pytest.fail('damaged claim accepted')
    assert path.read_bytes() == before


def test_symlink_state_is_not_followed(tmp_path):
    with release_claim.acquire('owner/repo', METADATA) as claim:
        path = claim.path
    target = tmp_path / 'unrelated'; target.write_text('untouched')
    path.symlink_to(target)
    with pytest.raises(OSError):
        with release_claim.acquire('owner/repo', METADATA):
            pytest.fail('followed claim symlink')
    assert target.read_text() == 'untouched'


def test_saved_claim_contains_metadata_digest_without_notes_contents():
    with release_claim.acquire('owner/repo', METADATA) as claim:
        claim.save('creating')
        value = json.loads(claim.path.read_text())
    assert len(value['metadata_sha256']) == 64
    assert 'body' not in value and METADATA['body'] not in value.values()


def test_artifact_cache_override_cannot_split_same_destination_ownership(tmp_path, monkeypatch):
    with release_claim.acquire('owner/repo', METADATA):
        monkeypatch.setenv('ATELIER_CACHE', str(tmp_path / 'different-artifact-cache'))
        with pytest.raises(release_claim.ClaimError, match='another publisher owns'):
            with release_claim.acquire('owner/repo', METADATA):
                pytest.fail('artifact cache changed destination ownership')
