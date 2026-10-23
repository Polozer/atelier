"""The build-v2 Python job loop runs real tiny jobs over inherited pipes (portable, no isolation claim)."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from atelier.build_v2 import protocol, python_worker

WORKER = Path(python_worker.__file__)

ECHO = '''
def run(context):
    data = context.input('shape').read_bytes()
    scale = context.params['scale']
    context.output('piece.txt').write_bytes(data * scale + str(context.seed).encode())
'''


def stage(root, script=ECHO, inputs=None, code=None, **job):
    """A hand-staged job folder; the Rust staging layer builds the same shape from a PreparedUnit."""
    root.mkdir(parents=True)
    (root / 'output').mkdir()
    files = {'ops/run.py': script, **(code or {})}
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding='utf-8')
        (root / path).chmod(0o444)
    staged = []
    for name, (path, data) in (inputs if inputs is not None else {'shape': ('in/shape.bin', b'ab')}).items():
        if data is not None:
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(data)
            (root / path).chmod(0o444)
        staged.append({'name': name, 'path': path, 'identity': {'state': 'absent'} if data is None
                       else {'state': 'digest', 'digest': '0' * 64}})
    request = {'job_id': 'job-1', 'unit': 'u', 'op': {'kind': 'py', 'version': '1'}, 'job_dir': str(root),
               'script': 'ops/run.py', 'code': sorted(files), 'inputs': staged, 'params': {'scale': 2},
               'outputs': [{'path': 'piece.txt', 'required': True}]}
    request.update(job)
    return request


class Loop:
    """A direct owned worker child over two inherited pipes, as the launcher starts it."""

    def __init__(self, *flags, log=None):
        request_read, self.request_write = os.pipe()
        self.response_read, response_write = os.pipe()
        self.process = subprocess.Popen(
            [sys.executable, '-I', str(WORKER), '--request-fd', str(request_read), '--response-fd',
             str(response_write), *flags], pass_fds=(request_read, response_write), stdin=subprocess.DEVNULL,
            stdout=log, stderr=log)
        os.close(request_read)
        os.close(response_write)
        self.requests = os.fdopen(self.request_write, 'wb', buffering=0)
        self.responses = os.fdopen(self.response_read, 'rb', buffering=0)
        assert self.read() == {'type': 'hello', 'worker_version': 'atelier-python-job-1'}

    def send(self, message):
        protocol.write_frame(self.requests, protocol.REQUEST, message)

    def read(self):
        return protocol.read_frame(self.responses, protocol.RESPONSE)

    def run(self, job):
        self.send({'type': 'run', 'job': job})
        assert self.read() == {'type': 'started', 'job_id': job['job_id']}
        return self.read()

    def close(self):
        self.send({'type': 'shutdown'})
        assert self.read() == {'type': 'stopped'}
        assert self.read() is None
        self.requests.close()
        self.responses.close()
        assert self.process.wait(timeout=10) == 0


@pytest.fixture
def loop():
    worker = Loop('--no-sandbox-portable-test')
    yield worker
    if worker.process.poll() is None:
        worker.process.kill()
        worker.process.wait()


def failure(response, kind):
    assert response['type'] == 'failed', response
    assert response['failure']['kind'] == kind, response
    return response['failure']['message']


def test_job_runs_and_reports_its_declared_outputs(tmp_path, loop):
    job = stage(tmp_path / 'job')
    assert loop.run(job) == {'type': 'completed', 'job_id': 'job-1', 'outputs': {'files': ['piece.txt']}}
    assert (tmp_path / 'job/output/piece.txt').read_bytes() == b'abab0'
    loop.close()


def test_same_bytes_under_other_job_ids_and_folders(tmp_path, loop):
    script = '''
import os, random, time
def run(context):
    context.output('piece.txt').write_text(repr((hash('salted'), random.random(), time.time(),
                                                 sorted(vars(context.__class__)), context.inputs)))
'''
    first = stage(tmp_path / 'a/job', script=script)
    second = stage(tmp_path / 'elsewhere/deeper/folder', script=script, job_id='other-id')
    assert loop.run(first)['type'] == 'completed'
    assert loop.run(second)['type'] == 'completed'
    produced = [(Path(job['job_dir']) / 'output/piece.txt').read_bytes() for job in (first, second)]
    assert produced[0] == produced[1]
    assert b'job-1' not in produced[0] and b'other-id' not in produced[1]


def test_changing_only_seed_or_params_changes_output(tmp_path, loop):
    script = '''
import random
def run(context):
    context.output('piece.txt').write_text(f'{random.random()} {context.params["scale"]}')
'''
    outputs = []
    for index, params in enumerate(({'scale': 1, 'seed': 1}, {'scale': 1, 'seed': 1}, {'scale': 1, 'seed': 2},
                                    {'scale': 3, 'seed': 1})):
        job = stage(tmp_path / f'job{index}', script=script, params=params)
        assert loop.run(job)['type'] == 'completed'
        outputs.append((tmp_path / f'job{index}/output/piece.txt').read_text())
    assert outputs[0] == outputs[1]
    assert len(set(outputs[1:])) == 3


def test_optional_absent_input_is_none_and_creates_no_file(tmp_path, loop):
    script = '''
def run(context):
    try:
        context.input('extra')
        found = 'present'
    except LookupError:
        found = 'absent'
    context.output('piece.txt').write_text(f'{context.inputs["extra"]} {found}')
'''
    job = stage(tmp_path / 'job', script=script, inputs={'shape': ('shape.bin', b'x'), 'extra': ('extra.bin', None)})
    assert loop.run(job)['type'] == 'completed'
    assert (tmp_path / 'job/output/piece.txt').read_text() == 'None absent'
    assert not (tmp_path / 'job/extra.bin').exists()


def test_staged_presence_must_match_the_declared_identity(tmp_path, loop):
    job = stage(tmp_path / 'job', inputs={'shape': ('shape.bin', None)})
    (tmp_path / 'job/shape.bin').write_bytes(b'stray')
    assert 'staged presence' in failure(loop.run(job), 'protocol')


def test_wall_clock_is_fixed_and_entropy_is_refused(tmp_path, loop):
    clock = '''
import datetime, time
def run(context):
    context.output('piece.txt').write_text(f'{time.time()} {datetime.datetime.now(datetime.timezone.utc).isoformat()}')
'''
    job = stage(tmp_path / 'clock', script=clock)
    assert loop.run(job)['type'] == 'completed'
    assert (tmp_path / 'clock/output/piece.txt').read_text() == '946684800.0 2000-01-01T00:00:00+00:00'
    for index, call in enumerate(('os.urandom(4)', 'uuid.uuid4()', '__import__("secrets")', 'random.SystemRandom()')):
        script = f'import os, random, uuid\ndef run(context):\n    {call}\n'
        assert loop.run(stage(tmp_path / f'entropy{index}', script=script))['failure']['kind'] == 'dependency'


def test_only_declared_code_loads_and_the_checkout_is_not_importable(tmp_path, loop):
    helper = 'def value():\n    return "helper"\n'
    uses_helper = 'import helper\ndef run(context):\n    context.output("piece.txt").write_text(helper.value())\n'
    declared = stage(tmp_path / 'declared', script=uses_helper, code={'ops/helper.py': helper})
    assert loop.run(declared)['type'] == 'completed'
    undeclared = stage(tmp_path / 'undeclared', script=uses_helper)
    (tmp_path / 'undeclared/ops/helper.py').write_text(helper)  # present on disk, not declared
    assert 'declared code closure' in failure(loop.run(undeclared), 'dependency')
    probe = '''
import sys
def run(context):
    try:
        import atelier
        found = 'importable'
    except ImportError:
        found = 'missing'
    context.output('piece.txt').write_text(found + ' ' + str(any('platform/studio' in p for p in sys.path)))
'''
    assert loop.run(stage(tmp_path / 'probe', script=probe))['type'] == 'completed'
    assert (tmp_path / 'probe/output/piece.txt').read_text() == 'missing False'


def test_job_sees_only_its_result_descriptor_and_declared_environment(tmp_path, loop):
    probe = '''
import os
def run(context):
    open_fds = []
    for fd in range(3, 256):
        try:
            os.fstat(fd)
            open_fds.append(fd)
        except OSError:
            pass
    context.output('piece.txt').write_text(f'{len(open_fds)} {sorted(os.environ)}')
'''
    assert loop.run(stage(tmp_path / 'job', script=probe))['type'] == 'completed'
    count, environment = (tmp_path / 'job/output/piece.txt').read_text().split(' ', 1)
    assert count == '1'  # the result pipe; neither protocol descriptor is inherited
    assert environment == repr(sorted(python_worker.JOB_ENVIRONMENT))


def test_outputs_must_match_the_declaration(tmp_path, loop):
    extra = 'def run(context):\n    (context.output_dir / "other.txt").write_text("x")\n'
    assert 'undeclared' in failure(loop.run(stage(tmp_path / 'extra', script=extra)), 'job')
    missing = 'def run(context):\n    pass\n'
    assert 'missing' in failure(loop.run(stage(tmp_path / 'missing', script=missing)), 'job')
    optional = stage(tmp_path / 'optional', script=missing, outputs=[{'path': 'piece.txt', 'required': False}])
    assert loop.run(optional) == {'type': 'completed', 'job_id': 'job-1', 'outputs': {'files': []}}
    link = 'import os\ndef run(context):\n    os.symlink("/etc/hosts", context.output("piece.txt"))\n'
    assert 'os.symlink' in failure(loop.run(stage(tmp_path / 'link', script=link)), 'dependency')
    fifo = 'import os\ndef run(context):\n    os.mkfifo(context.output("piece.txt"))\n'
    assert 'regular file' in failure(loop.run(stage(tmp_path / 'fifo', script=fifo)), 'job')
    raises = 'def run(context):\n    raise ValueError("bad mesh")\n'
    assert 'bad mesh' in failure(loop.run(stage(tmp_path / 'raises', script=raises)), 'job')


def test_cancel_stops_the_job_and_the_loop_serves_the_next(tmp_path, loop):
    slow = 'import threading\ndef run(context):\n    threading.Event().wait(60)\n'
    job = stage(tmp_path / 'slow', script=slow)
    loop.send({'type': 'run', 'job': job})
    assert loop.read() == {'type': 'started', 'job_id': 'job-1'}
    loop.send({'type': 'cancel', 'job_id': 'job-1'})
    failure(loop.read(), 'cancelled')
    assert list((tmp_path / 'slow/output').iterdir()) == []
    loop.send({'type': 'cancel', 'job_id': 'job-1'})  # late: no reply
    assert loop.run(stage(tmp_path / 'next', job_id='job-2'))['type'] == 'completed'
    loop.close()


def test_refuses_to_run_unsandboxed_without_the_portable_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(python_worker, 'SANDBOX_EXEC', str(tmp_path / 'missing-sandbox'))
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    with os.fdopen(request_write, 'wb') as requests:
        protocol.write_frame(requests, protocol.REQUEST, {'type': 'run', 'job': stage(tmp_path / 'job')})
        protocol.write_frame(requests, protocol.REQUEST, {'type': 'shutdown'})
    with os.fdopen(request_read, 'rb') as requests, os.fdopen(response_write, 'wb') as responses:
        python_worker.Worker(requests, responses, sandboxed=True).serve()
    with os.fdopen(response_read, 'rb') as responses:
        replies = [protocol.read_frame(responses, protocol.RESPONSE) for _ in range(4)]
    assert replies[1] == {'type': 'started', 'job_id': 'job-1'}
    assert 'no supported job sandbox' in failure(replies[2], 'dependency')
    assert replies[3] == {'type': 'stopped'}
    assert list((tmp_path / 'job/output').iterdir()) == []


def test_undeclared_path_checks_fail_even_when_missing_or_caught(tmp_path, loop):
    missing = str(tmp_path / 'never-created')
    for index, body in enumerate((f'os.path.exists({missing!r})', f'Path({missing!r}).is_file()',
                                  f'os.listdir({missing!r})', 'os.listdir("..")',
                                  f'open({missing!r}, "w")', 'subprocess.run(["true"])')):
        script = ('import os, subprocess\nfrom pathlib import Path\ndef run(context):\n'
                  f'    try:\n        {body}\n    except BaseException:\n        pass\n'
                  '    context.output("piece.txt").write_text("ran")\n')
        job = stage(tmp_path / f'job{index}', script=script)
        assert 'undeclared' in failure(loop.run(job), 'dependency')
        assert list((tmp_path / f'job{index}/output').iterdir()) == []
    assert not os.path.exists(missing)


def test_ctypes_imports_but_named_native_libraries_and_sockets_are_refused(tmp_path, loop):
    imports = 'import ctypes\ndef run(context):\n    context.output("piece.txt").write_text("ok")\n'
    assert loop.run(stage(tmp_path / 'imports', script=imports))['type'] == 'completed'
    for index, body in enumerate(('ctypes.CDLL("libc.dylib")', 'socket.socketpair()',
                                  'socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9))')):
        script = f'import ctypes, socket\ndef run(context):\n    {body}\n'
        assert 'undeclared' in failure(loop.run(stage(tmp_path / f'job{index}', script=script)), 'dependency')
