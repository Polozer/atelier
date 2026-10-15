"""Verified package publication with in-memory GitHub state; no release writes or native jobs."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import zipfile

import pytest

from atelier import playtest, release
from atelier.cli import parse_args

REVISION = 'a' * 40
TAG = 'game-macos-1'
SPEC = dict(tag='game-macos-', launcher='Game/Play Game.command')
METADATA = dict(tag_name=TAG, target_commitish=REVISION, name=TAG, body='', prerelease=False)
sha = lambda body: hashlib.sha256(body).hexdigest()


@pytest.fixture
def package(tmp_path):
    root, stage = tmp_path / 'package', tmp_path / 'stage'
    root.mkdir(); stage.mkdir(mode=0o700)
    body = io.BytesIO()
    with zipfile.ZipFile(body, 'w') as archive:
        archive.writestr(SPEC['launcher'], '#!/bin/bash\n')
    content = body.getvalue()
    original = dict(app='Game.app', launcher='Play Game.command', revision=REVISION[:8], zip='Game.zip',
                    split=True, cook=dict(revision=REVISION, source_dirty=False))
    original['files'] = []
    for index, offset in enumerate(range(0, len(content), 55)):
        name = 'Game.zip.part-a' + chr(97 + index)
        block = content[offset:offset + 55]
        (root / name).write_bytes(block)
        original['files'].append(dict(file=name, bytes=len(block), sha256=sha(block)))
    (root / 'manifest.json').write_text(json.dumps(original))
    (root / 'SHA256SUMS').write_text(''.join(f"{e['sha256']}  {e['file']}\n" for e in original['files']))
    proof = tmp_path / 'verification.json'
    proof.write_text(json.dumps(dict(revision=REVISION, files=original['files'], architectures='arm64',
                                    launcher_sha256=sha(b'#!/bin/bash\n'))))
    return root, proof, stage, content


def prepare(package, **changes):
    root, proof, stage, _ = package
    options = dict(game='game', tag=TAG, revision=REVISION, repo='owner/repo', spec=SPEC,
                   part_bytes=40, title=TAG, notes='')
    options.update(changes)
    return release.prepare(root, proof, stage, **options)


class Stop:
    def __init__(self):
        self.value = False
        self.delays = []
    def is_set(self): return self.value
    def set(self): self.value = True
    def wait(self, delay): self.delays.append(delay)


class GitHub:
    def __init__(self):
        self.stop = Stop()
        self.release = None
        self.files = {}
        self.events = []
        self.failures = {}
        self.tag = None
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def read(self, path, *, missing=False, pages=False):
        self.events.append(('read', path))
        if path.startswith('git/ref/'):
            return dict(object=dict(type='commit', sha=self.tag)) if self.tag else None
        if path == 'releases?per_page=100':
            return [[deepcopy(self.release)]] if self.release else [[]]
        if path.startswith('releases/tags/') and self.release and self.release['draft']:
            return None  # Pending draft tags need the authenticated listing fallback.
        if path.endswith('assets?per_page=100'):
            return [[dict(name=name, size=len(body), digest='sha256:' + sha(body), state='uploaded')
                     for name, body in list(self.files.items())]]
        return deepcopy(self.release)

    def api(self, path, *, method='GET', data=None):
        self.events.append((method, path))
        if method == 'POST':
            self.release = dict(id=1, html_url='https://example.invalid/release', **data)
        elif method == 'PATCH':
            self.release.update(data)
            self.tag = self.release['target_commitish']
        else:
            raise AssertionError('unexpected mocked API request')
        if self.failures.get(method):
            raise self.failures.pop(method)
        return deepcopy(self.release)

    def upload(self, tag, path):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            self.events.append(('upload', path.name))
            time.sleep(.002)
            failure = self.failures.pop(path.name, None)
            if failure == 'absent':
                raise release.TransportError()
            if failure == 'persistent':
                self.failures[path.name] = failure
                raise release.TransportError()
            self.files[path.name] = path.read_bytes()
            if failure:
                raise failure
        finally:
            with self.lock:
                self.active -= 1


def publish(github, stage, **options):
    return release.publish_assets(github, stage, METADATA, workers=options.pop('workers', 2),
                                  revalidate=options.pop('revalidate', lambda: None), **options)


def test_cli_has_ergonomic_package_defaults():
    args = parse_args(['release', 'publish', 'game', 'build/game/package', '--tag', TAG, '--verification', 'proof.json'])
    assert (args.package, args.workers, args.part_mib, args.source, args.title) == ('build/game/package', 6, 200, None, None)


def test_rechunks_existing_split_package_without_joined_zip(package):
    root, proof, stage, content = package
    inputs = prepare(package)
    current = json.loads((stage / 'manifest.json').read_text())
    assert b''.join((stage / e['file']).read_bytes() for e in current['files']) == content
    assert all(e['bytes'] <= 40 and sha((stage / e['file']).read_bytes()) == e['sha256'] for e in current['files'])
    assert current['publication']['source_revision'] == REVISION
    assert current['publication']['archive_sha256'] == sha(content)
    assert (stage / 'verification.json').read_bytes() == proof.read_bytes()
    assert (stage / 'package-manifest.json').read_bytes() == (root / 'manifest.json').read_bytes()
    assert playtest.checksums((stage / 'SHA256SUMS').read_text()) == {e['file']: e['sha256'] for e in current['files']}
    assert not (root / 'Game.zip').exists()
    assert root / 'manifest.json' in inputs
    assert all(path.stat().st_mode & 0o077 == 0 for path in stage.iterdir())


def test_legacy_short_revision_and_unsplit_package_are_supported(package):
    root, proof, stage, content = package
    original = json.loads((root / 'manifest.json').read_text())
    original.pop('cook')
    original['split'] = False
    original['files'] = [dict(file='Game.zip', bytes=len(content), sha256=sha(content))]
    (root / 'Game.zip').write_bytes(content)
    (root / 'manifest.json').write_text(json.dumps(original))
    (root / 'SHA256SUMS').write_text(f'{sha(content)}  Game.zip\n')
    proof.write_text(json.dumps(dict(revision=REVISION[:8], files=original['files'], architectures='arm64',
                                    launcher_sha256=sha(b'#!/bin/bash\n'))))
    prepare(package, part_bytes=1000)
    assert (stage / 'Game.zip').read_bytes() == content


@pytest.mark.parametrize('mutation', ['bytes', 'proof', 'revision', 'dirty', 'order', 'sums', 'symlink', 'launcher'])
def test_bad_package_or_attestation_refuses_before_any_github_write(package, mutation):
    root, proof, stage, _ = package
    original = json.loads((root / 'manifest.json').read_text())
    if mutation == 'bytes':
        path = root / original['files'][0]['file']
        path.write_bytes(b'x' * path.stat().st_size)
    elif mutation == 'proof': proof.write_text('{}')
    elif mutation == 'revision': original['cook']['revision'] = 'b' * 40
    elif mutation == 'dirty': original['cook']['source_dirty'] = True
    elif mutation == 'order': original['files'].reverse()
    elif mutation == 'sums': (root / 'SHA256SUMS').write_text('')
    elif mutation == 'symlink':
        path = root / original['files'][0]['file']
        saved = root / 'saved'
        path.rename(saved); path.symlink_to(saved)
    elif mutation == 'launcher': original['launcher'] = 'Other.command'
    (root / 'manifest.json').write_text(json.dumps(original))
    with pytest.raises(release.PublishError):
        prepare(package)


def test_manifest_last_then_draft_publication_and_downloader_compatibility(package, tmp_path, monkeypatch):
    _, _, stage, _ = package
    prepare(package)
    github = GitHub()
    result = publish(github, stage)
    uploads = [name for action, name in github.events if action == 'upload']
    assert uploads[-1] == 'SHA256SUMS'
    assert github.events.index(('upload', 'SHA256SUMS')) < github.events.index(('PATCH', 'releases/1'))
    assert not result['draft'] and 1 < github.peak <= 2
    assets = [dict(name=name, size=len(body), digest='sha256:' + sha(body), browser_download_url=name)
              for name, body in github.files.items()]
    monkeypatch.setattr(playtest, '_open', lambda url, *args, **kwargs: io.BytesIO(github.files[url]))
    def unpack(archive, destination, *args):
        destination.mkdir()
        zipfile.ZipFile(archive).extractall(destination)
    monkeypatch.setattr(playtest, 'unpack', unpack)
    root = tmp_path / 'download'; root.mkdir()
    folder = playtest._ensure(root, 'game', dict(tag_name=TAG, assets=assets, html_url='url', published_at='now'),
                              SPEC['launcher'], lambda *_: None)
    assert (folder / SPEC['launcher']).is_file() and (folder / playtest.READY).is_file()


def test_completed_matching_assets_resume_without_upload_and_published_is_idempotent(package):
    stage = package[2]
    prepare(package)
    github = GitHub()
    github.release = dict(id=1, draft=True, **METADATA)
    first = sorted(stage.iterdir())[0]
    github.files[first.name] = first.read_bytes()
    publish(github, stage)
    assert ('upload', first.name) not in github.events
    github.events.clear()
    publish(github, stage)
    assert all(action not in ('upload', 'PATCH', 'POST') for action, _ in github.events)


@pytest.mark.parametrize('committed', [True, False])
def test_ambiguous_upload_observes_remote_before_retry(package, committed):
    stage = package[2]
    prepare(package)
    github = GitHub()
    name = sorted(stage.iterdir())[0].name
    github.failures[name] = release.TransportError() if committed else 'absent'
    publish(github, stage, workers=1)
    indices = [i for i, event in enumerate(github.events) if event == ('upload', name)]
    assert len(indices) == (1 if committed else 2)
    assert github.events[indices[0] + 1] == ('read', 'releases/1/assets?per_page=100')


def test_exhausted_upload_is_bounded_and_never_uploads_readiness_manifest(package):
    stage = package[2]
    prepare(package)
    github = GitHub()
    name = sorted(stage.iterdir())[0].name
    github.failures[name] = 'persistent'
    with pytest.raises(release.TransportError):
        publish(github, stage, workers=1)
    assert github.events.count(('upload', name)) == 3
    assert 'SHA256SUMS' not in github.files and github.release['draft']
    assert not any(action == 'PATCH' for action, _ in github.events)


@pytest.mark.parametrize('field,value', [('digest', None), ('digest', 'sha256:' + '0' * 64),
                                      ('size', 0), ('state', 'starter')])
def test_remote_conflict_or_missing_digest_never_clobbers(package, field, value):
    stage = package[2]; prepare(package)
    github = GitHub()
    github.release = dict(id=1, draft=True, **METADATA)
    path = sorted(stage.iterdir())[0]
    github.files[path.name] = path.read_bytes()
    original = github.read
    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get('pages'):
            result[0][0][field] = value
        return result
    github.read = read
    with pytest.raises(release.PublishError, match='never clobber'):
        publish(github, stage)
    assert not any(action in ('upload', 'PATCH', 'POST', 'DELETE') for action, _ in github.events)


def test_incomplete_existing_published_release_is_not_mutated(package):
    stage = package[2]; prepare(package)
    github = GitHub(); github.release = dict(id=1, draft=False, **METADATA)
    with pytest.raises(release.PublishError, match='published release is incomplete'):
        publish(github, stage)
    assert not any(action in ('upload', 'PATCH') for action, _ in github.events)


@pytest.mark.parametrize('operation', ['POST', 'PATCH'])
def test_ambiguous_release_mutation_is_observed_not_blindly_repeated(package, operation):
    stage = package[2]; prepare(package)
    github = GitHub(); github.failures[operation] = release.TransportError()
    assert publish(github, stage)['draft'] is False
    assert sum(action == operation for action, _ in github.events) == 1


@pytest.mark.parametrize('kind', ['input', 'output'])
def test_mutation_prevents_readiness_and_publication(package, kind):
    stage = package[2]; prepare(package)
    github = GitHub()
    def validate():
        if kind == 'input': raise release.PublishError('input changed')
        (stage / 'manifest.json').write_text('changed')
    with pytest.raises(release.PublishError, match='changed'):
        publish(github, stage, revalidate=validate)
    assert 'SHA256SUMS' not in github.files
    assert not any(action == 'PATCH' for action, _ in github.events)


def test_wrong_remote_tag_or_metadata_is_refused(package):
    stage = package[2]; prepare(package)
    github = GitHub(); github.tag = 'b' * 40
    with pytest.raises(release.PublishError, match='different source'):
        publish(github, stage)
    github.tag = None
    github.release = dict(id=1, draft=True, **{**METADATA, 'name': 'changed title'})
    with pytest.raises(release.PublishError, match='name conflicts'):
        publish(github, stage)


def test_selected_source_must_be_clean_and_reads_game_origin(tmp_path, monkeypatch):
    game = tmp_path / 'games/game'; game.mkdir(parents=True)
    (game / 'game.toml').write_text('[release]\ntag = "game-macos-"\nlauncher = "Game/Play Game.command"\n')
    dirty = [False]
    def git(argv, **kwargs):
        assert kwargs['cwd'] == tmp_path
        result = REVISION if argv[1] == 'rev-parse' else 'https://github.com/owner/repo.git' if argv[1] == 'config' else (' M source.py' if dirty[0] else '')
        return SimpleNamespace(returncode=0, stdout=result)
    monkeypatch.setattr(release.subprocess, 'run', git)
    assert release.source_identity(tmp_path, 'game') == (REVISION, 'owner/repo', SPEC)
    dirty[0] = True
    with pytest.raises(release.PublishError, match='clean'):
        release.source_identity(tmp_path, 'game')


def test_gh_transport_preserves_identity_and_pins_github_host(monkeypatch):
    github = release.GitHub('owner/repo', Stop())
    calls = []
    monkeypatch.setattr(github, 'run', lambda args, **kwargs: calls.append((args, kwargs)) or b'{}')
    github.api('releases', method='POST', data=METADATA)
    github.upload(dict(id=7), Path('/tmp/asset.zip'))
    assert '--hostname' in calls[0][0] and 'github.com' in calls[0][0]
    assert json.loads(calls[0][1]['data']) == METADATA
    assert calls[1][0] == ['api', 'https://uploads.github.com/repos/owner/repo/releases/7/assets?name=asset.zip',
        '--hostname', 'github.com', '--method', 'POST', '--header', 'Content-Type: application/octet-stream',
        '--input', '/tmp/asset.zip']
    assert '--clobber' not in calls[1][0]


@pytest.mark.parametrize('code,calls', [(503, 3), (401, 1), (404, 1)])
def test_gh_read_attempts_are_bounded_and_auth_failures_terminal(monkeypatch, code, calls):
    github = release.GitHub('owner/repo', Stop())
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(True)
        raise release.TransportError(code)
    monkeypatch.setattr(github, 'api', fail)
    with pytest.raises(release.TransportError):
        github.read('releases')
    assert len(attempts) == calls


@pytest.mark.parametrize('interrupt', ['deadline', 'cancel'])
def test_owned_gh_process_is_ended_on_deadline_or_cancellation(monkeypatch, interrupt):
    stop = Stop()
    github = release.GitHub('owner/repo', stop)
    calls = []
    class Child:
        returncode = None
        def communicate(self, **kwargs):
            calls.append(('communicate', kwargs))
            if interrupt == 'cancel': stop.set()
            raise subprocess.TimeoutExpired('gh', 1)
        def poll(self): return self.returncode
        def terminate(self): calls.append(('terminate',)); self.returncode = -15
        def wait(self, **kwargs): calls.append(('wait', kwargs)); return self.returncode
    monkeypatch.setattr(release.subprocess, 'Popen', lambda *args, **kwargs: Child())
    clock = iter([0, 0, 2])
    monkeypatch.setattr(release.time, 'monotonic', lambda: next(clock))
    with pytest.raises(release.TransportError):
        github.run(['api', 'unused'], timeout=1)
    assert ('terminate',) in calls
    assert calls[-1] == ('wait', {'timeout': 3})


def test_malformed_mutation_response_is_ambiguous_transport(monkeypatch):
    github = release.GitHub('owner/repo', Stop())
    monkeypatch.setattr(github, 'run', lambda *args, **kwargs: b'{')
    with pytest.raises(release.TransportError):
        github.api('releases', method='POST', data=METADATA)


def test_cli_routes_to_publisher_without_launching_a_job(monkeypatch):
    from atelier import cli
    seen = []
    monkeypatch.setattr(release, 'main', lambda *args, **kwargs: seen.append((args, kwargs)) or 0)
    assert cli.main(['release', 'publish', 'game', 'package', '--tag', TAG, '--verification', 'proof',
                     '--workers', '2', '--source', 'source']) == 0
    assert seen[0][0] == ('game', 'package')
    assert seen[0][1]['workers'] == 2 and seen[0][1]['source'] == 'source'


def test_main_publishes_existing_package_with_mocked_transport_and_removes_private_staging(package, tmp_path, monkeypatch):
    root, proof, _, _ = package
    github = GitHub()
    selected = []
    def source(path, game, package_revision=None):
        selected.append((path, game, package_revision))
        return REVISION, 'owner/repo', SPEC
    monkeypatch.setattr(release, 'source_identity', source)
    monkeypatch.setattr(release, 'GitHub', lambda *args: github)
    monkeypatch.setattr(release.paths, 'build_dir', lambda game: tmp_path / 'package')
    assert release.main('game', root, tag=TAG, verification=proof, source=tmp_path) == 0
    assert selected[-1] == (tmp_path, 'game', REVISION)
    assert not list((root / 'release-publish').iterdir())
    assert not github.release['draft']


def test_ready_manifest_with_missing_remote_assets_is_not_repaired(package):
    stage = package[2]; prepare(package)
    github = GitHub(); github.release = dict(id=1, draft=True, **METADATA)
    github.files['SHA256SUMS'] = (stage / 'SHA256SUMS').read_bytes()
    with pytest.raises(release.PublishError, match='missing assets'):
        publish(github, stage)
    assert not any(action in ('upload', 'PATCH') for action, _ in github.events)


def test_package_manifest_cannot_be_used_as_native_verification_report(package):
    root, proof, _, _ = package
    original = json.loads((root / 'manifest.json').read_text())
    original['revision'] = REVISION
    (root / 'manifest.json').write_text(json.dumps(original))
    proof.write_text(json.dumps(original))
    with pytest.raises(release.PublishError, match='native architecture'):
        prepare(package)


@pytest.mark.parametrize('part_mib,workers', [(0, 6), (1901, 6), (200, 0), (200, 7)])
def test_invalid_upload_bounds_refuse_before_source_or_transport(part_mib, workers):
    with pytest.raises(SystemExit, match='must be between'):
        release.main('game', 'unused', tag=TAG, verification='unused', part_mib=part_mib, workers=workers)


def test_gh_certificate_failure_is_not_retried_or_exposed(monkeypatch):
    github = release.GitHub('owner/repo', Stop())
    calls = []
    class Child:
        returncode = 1
        def communicate(self, **kwargs): return b'', b'x509: certificate signed by unknown authority: private detail'
        def poll(self): return 1
    monkeypatch.setattr(release.subprocess, 'Popen', lambda *args, **kwargs: calls.append(args) or Child())
    with pytest.raises(release.TransportError, match='certificate verification failed') as found:
        github.read('releases')
    assert 'private detail' not in str(found.value) and len(calls) == 1


def test_other_publisher_cannot_make_this_command_fill_an_incomplete_published_release(package):
    stage = package[2]; prepare(package)
    github = GitHub()
    def validate():
        github.release['draft'] = False
        github.tag = REVISION
    with pytest.raises(release.PublishError, match='published before all assets'):
        publish(github, stage, revalidate=validate)
    assert 'SHA256SUMS' not in github.files


def test_success_requires_observed_published_tag_identity(package):
    stage = package[2]; prepare(package)
    github = GitHub()
    original = github.read
    def read(path, **kwargs):
        return None if path.startswith('git/ref/') else original(path, **kwargs)
    github.read = read
    with pytest.raises(release.PublishError, match='tag is not yet observable'):
        publish(github, stage)
    assert github.release['draft'] is False  # The uncertain remote effect is preserved; rerun observes it.


def test_published_idempotent_success_rechecks_staged_bytes(package):
    stage = package[2]; prepare(package)
    github = GitHub(); publish(github, stage)
    def mutate():
        (stage / 'manifest.json').write_text('changed after remote preflight')
    with pytest.raises(release.PublishError, match='staged output changed'):
        publish(github, stage, revalidate=mutate)
