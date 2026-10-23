"""On macOS every build-v2 Python job runs sandboxed: undeclared reads, checks, listings and network fail."""
import os
import socket
import subprocess
import sys
import threading

import pytest

from atelier.build_v2 import python_worker
from test_build_v2_python_worker import WORKER, Loop, failure, stage

pytestmark = [pytest.mark.macos_only]


@pytest.fixture
def loop():
    worker = Loop(WORKER)
    yield worker
    if worker.process.poll() is None:
        worker.process.kill()
        worker.process.wait()


@pytest.fixture
def outside(tmp_path):
    folder = tmp_path / 'undeclared'
    folder.mkdir()
    (folder / 'secret.txt').write_text('not an input')
    return folder


def attempt(tmp_path, loop, name, body):
    script = f'import os, socket\ndef run(context):\n    {body}\n    context.output("piece.txt").write_text("ran")\n'
    return loop.run(stage(tmp_path / name, script=script))


def test_sandboxed_job_reads_inputs_lists_its_folder_and_writes_output(tmp_path, loop):
    script = '''
import json, os
def run(context):
    data = context.input('shape').read_bytes()
    context.output('piece.txt').write_text(json.dumps([data.decode(), sorted(os.listdir('.')), dict(context.params)]))
    os.makedirs('output/pieces/a')  # a group folder under output/ is writable too
    open('output/pieces/a/m.glb', 'w').write('member')
'''
    assert loop.run(stage(tmp_path / 'job', script=script)) == {
        'type': 'completed', 'job_id': 'job-1', 'outputs': {'files': ['piece.txt', 'pieces/a/m.glb']}}
    assert (tmp_path / 'job/output/piece.txt').read_text() == '["ab", ["in", "ops", "output"], {"scale": 2}]'
    loop.close()


def test_job_logs_reach_the_loop_log_file_outside_the_job(tmp_path):
    script = 'import sys\ndef run(context):\n    print("job says hi")\n    print("job warns", file=sys.stderr)\n' \
             '    context.output("piece.txt").write_text("ok")\n'
    with open(tmp_path / 'worker.log', 'wb') as log:
        worker = Loop(WORKER, log=log)
        assert worker.run(stage(tmp_path / 'job', script=script))['type'] == 'completed'
        worker.close()
    assert {'job says hi', 'job warns'} <= set((tmp_path / 'worker.log').read_text().splitlines())


def test_sandboxed_jobs_give_the_same_bytes_under_other_ids_and_folders(tmp_path, loop):
    first = stage(tmp_path / 'one/job')
    second = stage(tmp_path / 'two/other/place', job_id='job-2')
    assert loop.run(first)['type'] == loop.run(second)['type'] == 'completed'
    assert (tmp_path / 'one/job/output/piece.txt').read_bytes() == (
        tmp_path / 'two/other/place/output/piece.txt').read_bytes()


def test_undeclared_read_fails_the_job(tmp_path, loop, outside):
    message = failure(attempt(tmp_path, loop, 'read', f'open({str(outside / "secret.txt")!r}).read()'), 'dependency')
    assert 'undeclared read' in message and 'secret' not in message
    assert not (tmp_path / 'read/output/piece.txt').exists()


def test_existence_check_of_an_undeclared_path_fails_instead_of_returning_false(tmp_path, loop, outside):
    for index, check in enumerate((outside / 'secret.txt', outside / 'missing.txt', tmp_path / 'sibling')):
        response = attempt(tmp_path, loop, f'exists{index}', f'os.path.exists({str(check)!r})')
        assert 'undeclared' in failure(response, 'dependency')


def test_listing_an_undeclared_folder_fails_the_job(tmp_path, loop, outside):
    assert 'undeclared' in failure(attempt(tmp_path, loop, 'list', f'os.listdir({str(outside)!r})'), 'dependency')
    assert 'undeclared' in failure(attempt(tmp_path, loop, 'parent', 'os.listdir("..")'), 'dependency')


def test_network_use_fails_the_job(tmp_path, loop):
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    accepted = []

    def accept():
        try:
            accepted.append(server.accept())
        except OSError:
            pass  # closed by the test without a connection

    threading.Thread(target=accept, daemon=True).start()
    port = server.getsockname()[1]
    try:
        body = f'socket.create_connection(("127.0.0.1", {port}), timeout=5)'
        assert 'undeclared' in failure(attempt(tmp_path, loop, 'net', body), 'dependency')
        assert accepted == []
    finally:
        server.close()


def test_undeclared_module_fails_the_job(tmp_path, loop, outside):
    (outside / 'stray.py').write_text('VALUE = 1\n')
    body = f'import sys; sys.path.append({str(outside)!r}); __import__("stray")'
    assert failure(attempt(tmp_path, loop, 'module', body), 'dependency')
    script = 'import helper\ndef run(context):\n    context.output("piece.txt").write_text("ran")\n'
    job = stage(tmp_path / 'local', script=script)
    (tmp_path / 'local/ops/helper.py').write_text('')  # in the job folder, but not declared code
    assert 'declared code closure' in failure(loop.run(job), 'dependency')


def test_writes_outside_output_and_to_inputs_are_refused(tmp_path, loop, outside):
    for index, target in enumerate(('in/shape.bin', 'ops/run.py', 'new.txt', str(outside / 'new.txt'))):
        response = attempt(tmp_path, loop, f'write{index}', f'open({target!r}, "w").write("changed")')
        assert failure(response, 'dependency')
    assert (tmp_path / 'write0/in/shape.bin').read_bytes() == b'ab'
    assert not (outside / 'new.txt').exists()


def test_changing_only_seed_or_params_changes_sandboxed_output(tmp_path, loop):
    texts = []
    for index, params in enumerate(({'scale': 1, 'seed': 4}, {'scale': 1, 'seed': 5}, {'scale': 2, 'seed': 4})):
        script = 'import random\ndef run(context):\n    context.output("piece.txt").write_text(f"{random.random()} {context.params}")\n'
        assert loop.run(stage(tmp_path / f'job{index}', script=script, params=params))['type'] == 'completed'
        texts.append((tmp_path / f'job{index}/output/piece.txt').read_text())
    assert len(set(texts)) == 3


def test_kernel_sandbox_stops_native_access_that_bypasses_the_python_guard(tmp_path, outside):
    job = stage(tmp_path / 'job')['job_dir']
    profile = python_worker.sandbox_profile(job)
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    port = server.getsockname()[1]

    def status(code):
        command = [python_worker.SANDBOX_EXEC, '-p', profile, sys.executable, *python_worker.CHILD_FLAGS, '-c', code]
        return subprocess.run(command, cwd=job, env=dict(python_worker.JOB_ENVIRONMENT), capture_output=True,
                              timeout=20).returncode

    secret = str(outside / 'secret.txt')
    try:
        assert status('open("in/shape.bin").read(); open("output/x", "w").write("ok")') == 0
        assert os.listdir(os.path.join(job, 'output')) == ['x']
        killed = -9
        assert status(f'import posix; posix.stat({secret!r})') == killed
        assert status(f'open({secret!r}).read()') == killed
        assert status(f'import os; os.listdir({str(outside)!r})') == killed
        assert status(f'import socket; socket.create_connection(("127.0.0.1", {port}), timeout=5)') == killed
        assert status('open("new.txt", "w")') == 1  # writes outside output/ are refused, not killed
        # Only the interpreter may be executed: any other binary is refused by the profile itself.
        for binary in ('/bin/echo', '/usr/bin/true', '/bin/sh'):
            assert status(f'import os; os.execv({binary!r}, [{binary!r}])') == 1
        assert not os.path.exists(os.path.join(job, 'new.txt'))
    finally:
        server.close()
