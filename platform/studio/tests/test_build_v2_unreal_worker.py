"""Unit checks of the build-v2 Unreal job loop's own rules (no editor; the session runs in tests/unreal.rs)."""
import os
from pathlib import Path
import sys
import types

import pytest

from atelier.build_v2 import unreal_worker
from atelier.build_v2.unreal_worker import Editor, JobRefused, StartRefused, Worker


def test_protocol_descriptors_must_appear_once_and_be_pipes(tmp_path):
    read, write = os.pipe()
    try:
        assert unreal_worker.protocol_fds(f'x.uproject -stdout --request-fd {read} --response-fd {write}') == (read, write)
        assert not os.get_inheritable(read) and not os.get_inheritable(write)
        for line in (f'--request-fd {read}', f'--request-fd {read} --request-fd {read} --response-fd {write}',
                     f'--request-fd x --response-fd {write}'):
            with pytest.raises(StartRefused):
                unreal_worker.protocol_fds(line)
        with open(tmp_path / 'file', 'w') as regular:
            with pytest.raises(StartRefused, match='not a pipe'):
                unreal_worker.protocol_fds(f'--request-fd {regular.fileno()} --response-fd {write}')
    finally:
        os.close(read)
        os.close(write)


def test_package_names_come_only_from_primary_files_under_the_content_root():
    assert unreal_worker.package_of('content/Game/Meshes/Rock.uasset', 'content/Game/') == '/Game/Meshes/Rock'
    assert unreal_worker.package_of('content/Game/Maps/Crater.umap', 'content/Game/') == '/Game/Maps/Crater'
    assert unreal_worker.package_of('content/Game/Meshes/Rock.ubulk', 'content/Game/') is None
    assert unreal_worker.package_of('other/Rock.uasset', 'content/Game/') is None
    for path in ('', '/abs', 'a/../b', 'a//b', 'a\\b', './a'):
        with pytest.raises(JobRefused):
            unreal_worker._job_relative(path, 'output')


class Unloading:
    """An editor whose unload call says it unloaded everything while one package stays alive."""

    def __init__(self, survivor):
        self.alive = {'/Game/A', '/Game/B'}
        self.survivor = survivor
        unreal = types.SimpleNamespace(
            AtelierBuildWorkerLibrary=None,
            find_object=lambda outer, name: name if name in self.alive else None,
            EditorLoadingAndSavingUtils=types.SimpleNamespace(unload_packages=self.unload_packages),
            SystemLibrary=types.SimpleNamespace(collect_garbage=lambda: None))
        self.editor = Editor(unreal)

    def unload_packages(self, objects):
        self.alive -= set(objects) - {self.survivor}
        return True  # "any" were unloaded


def test_unload_checks_every_package_by_name_and_never_trusts_the_unload_result():
    assert Unloading(survivor=None).editor.unload(['/Game/A', '/Game/B']) == []
    assert Unloading(survivor='/Game/B').editor.unload(['/Game/A', '/Game/B']) == ['/Game/B']


def test_python_state_is_restored_and_job_modules_are_dropped(tmp_path):
    job = tmp_path / 'job'
    (job / 'ops').mkdir(parents=True)
    (job / 'ops/helper_c3_unit.py').write_text('VALUE = 1\n')
    state = unreal_worker._PythonState()
    sys.path.insert(0, str(job / 'ops'))
    os.environ['ATELIER_C3_UNIT'] = '1'
    import helper_c3_unit  # noqa: F401
    unreal_worker._PythonState.restore(state, job)
    assert str(job / 'ops') not in sys.path
    assert 'ATELIER_C3_UNIT' not in os.environ
    assert 'helper_c3_unit' not in sys.modules


class Fake:
    """Just enough editor for `Worker.execute` to reach its job checks."""

    def __init__(self, project):
        self.project = project

    def project_dir(self):
        return self.project


def worker(tmp_path):
    project = tmp_path / 'project'
    (project / 'Content').mkdir(parents=True)
    return Worker(Fake(project), None, None), project


def job(tmp_path, outputs, **extra):
    folder = tmp_path / 'job'
    (folder / 'output').mkdir(parents=True, exist_ok=True)
    return {'job_id': 'j', 'job_dir': str(folder), 'script': 'ops/op.py', 'code': ['ops/op.py'], 'inputs': [],
            'params': {}, 'outputs': [{'path': path, 'required': True} for path in outputs], **extra}


@pytest.mark.parametrize('path', ['content/Game/Rock.txt', 'output/Game/Rock.uasset', 'content/Engine/Rock.uasset'])
def test_outputs_must_be_package_files_under_the_game_content_root(tmp_path, path):
    loop, _ = worker(tmp_path)
    with pytest.raises(JobRefused, match='is not a package file') as refusal:
        loop.execute(job(tmp_path, [path]), set(), [])
    assert refusal.value.kind == 'protocol'


def test_a_job_never_starts_on_a_non_empty_game_folder_or_output(tmp_path):
    loop, project = worker(tmp_path)
    request = job(tmp_path, ['content/Game/A.uasset'])
    (project / 'Content/Left.uasset').write_bytes(b'x')
    with pytest.raises(JobRefused, match='/Game is not empty') as refusal:
        loop.execute(request, set(), [])
    assert refusal.value.kind == 'dependency'
    (Path(request['job_dir']) / 'output/stale').write_bytes(b'x')
    with pytest.raises(JobRefused, match='output/ is not empty'):
        loop.execute(request, set(), [])
