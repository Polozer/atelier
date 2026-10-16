"""Opt-in file preparation in the guarded child, before exec of the editor.

The explicit startup override is part of UnrealScript's command identity. Existing batch
compatibility already compares startup overrides, so different preflights cannot share a
process. The existing batch plan selects owners; a digest binds it across the admission wait.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import sys

KEY = 'ATELIER_UNREAL_PREFLIGHT'
MAX_PLAN = 4 * 1024**2


def set_environment(values):
    for key in os.environ.keys() - values.keys():
        del os.environ[key]
    for key, value in values.items():
        if os.environ.get(key) != value:
            os.environ[key] = value


def read_plan(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_size > MAX_PLAN):
            raise ValueError('Preflight needs an owned bounded regular batch plan')
        raw = stream.read(MAX_PLAN + 1)
        after = os.fstat(stream.fileno())
        visible = path.lstat()
        def pin(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if len(raw) > MAX_PLAN or pin(before) != pin(after) or pin(after) != pin(visible):
            raise ValueError('Preflight batch plan changed while reading')
    return raw


def wrap(argv, script, batch=None):
    """Read-only construction before admission. No script runs or file is changed here."""
    script = Path(script)
    if not script.is_absolute() or not script.is_file() or script.is_symlink():
        raise ValueError('Unreal preflight must be an existing absolute source file')
    command = [sys.executable, str(Path(__file__)), '--script', str(script)]
    if batch is not None:
        plan = Path(batch) / 'plan.json'
        command.extend(['--plan', str(plan), '--sha256', hashlib.sha256(read_plan(plan)).hexdigest()])
    return [*command, '--', *argv]


def prepare(script, plan=None, digest=None):
    """@cc [owner:fontanierh,label:safety] admitted-pre-editor-preparation
    File preparation MUST run only in the already admitted guarded child, before editor exec.
    A batch MUST bind its selected owner plan before waiting, validate it before any preparation,
    and prepare every selected owner before the one editor starts. Failure MUST prevent exec.
    Hooks MUST perform only owned file IO, never import Unreal, start native tools or take a lock.
    The wrapper MUST exec the original editor argv with the original environment and same PID.
    """
    script = Path(script)
    if not script.is_absolute() or not script.is_file() or script.is_symlink():
        raise ValueError('Unreal preflight source changed before execution')
    if 'unreal' in sys.modules or os.environ.get(KEY) != str(script):
        raise RuntimeError('Preflight requires fresh Python and its explicit startup override')
    if (plan is None) != (digest is None):
        raise ValueError('Preflight batch plan needs its exact digest')
    actions = [{}]
    if plan is not None:
        raw = read_plan(plan)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Preflight batch plan changed during admission wait')
        value = json.loads(raw)
        actions = [action['env'] for action in value['actions']]
        if value['kind'] != 'UnrealScript' or not actions or any(
                not isinstance(env, dict) or env.get(KEY) != str(script)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()) for env in actions):
            raise ValueError('Batch owners must share the explicit Unreal preflight')
    environment, path, argv = dict(os.environ), list(sys.path), list(sys.argv)
    try:
        for overrides in actions:
            if 'unreal' in sys.modules:
                raise RuntimeError('Preflight must not import Unreal')
            set_environment(environment | overrides)
            sys.path[:] = [str(Path(script).parent), *path]
            sys.argv = [str(script)]
            runpy.run_path(str(script), run_name='__main__')
        if 'unreal' in sys.modules:
            raise RuntimeError('Preflight must not import Unreal')
    finally:
        set_environment(environment)
        sys.path[:], sys.argv[:] = path, argv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('the original editor command is required')
    prepare(args.script, args.plan, args.sha256)
    os.execvpe(command[0], command, os.environ.copy())


if __name__ == '__main__':
    main()
