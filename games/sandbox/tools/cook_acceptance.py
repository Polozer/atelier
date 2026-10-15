"""Offline evidence tools for the opt-in sandbox cook trial. Never launch or certify native parity."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    started = spoken = time.monotonic()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024**2), b''):
            value.update(block)
            now = time.monotonic()
            require(now - started < 2700, 'evidence hash exceeded 45 minutes')
            if now - spoken >= 25:
                print(f'cook evidence: hashing {path.name}', flush=True)
                spoken = now
    return value.hexdigest()


def frozen(path, expected):
    require(path.is_file() and not path.is_symlink() and re.fullmatch(r'[0-9a-f]{64}', expected),
            'frozen saved asset needs a regular file and exact SHA-256')
    require(digest(path) == expected, 'saved serialization probe changed; a resave cannot prove the header-only case')


def runtime(text):
    """Parse only explicit fixture markers; missing or conflicting observations refuse."""
    require(len(text.encode()) <= 16 * 1024**2, 'runtime log exceeds evidence bound')
    result = dict(assets={}, actors={}, identity=None)
    def once(mapping, key, value):
        require(key not in mapping or mapping[key] == value, 'conflicting runtime fixture observation')
        mapping[key] = value
    for line in text.splitlines():
        if 'ATELIER_COOK_ASSET ' in line:
            match = re.search(r'ATELIER_COOK_ASSET name=(\w+) state=(missing|loaded)(?: type=(float|double) value=([^ ]+))?$', line)
            require(match is not None, 'malformed asset observation')
            value = dict(state=match[2])
            if match[2] == 'loaded':
                require(match[3] is not None, 'loaded probe lacks native type/value')
                value.update(type=match[3], value=float(match[4]))
                require(math.isfinite(value['value']), 'nonfinite probe value')
            else:
                require(match[3] is None, 'missing probe has a payload')
            once(result['assets'], match[1], value)
        elif 'ATELIER_COOK_IDENTITY ' in line:
            match = re.search(r'ATELIER_COOK_IDENTITY map=(\w+) config=([\w-]+) gi=(\d+) reflection=(\d+)$', line)
            require(match is not None, 'malformed config/renderer observation')
            value = dict(map=match[1], config=match[2], gi=int(match[3]), reflection=int(match[4]))
            require(result['identity'] in (None, value), 'conflicting config/renderer identity')
            result['identity'] = value
        elif 'ATELIER_COOK_ACTOR ' in line:
            match = re.search(r'ATELIER_COOK_ACTOR tag=(\w+) scale=([^ ]+) location=([^ ]+)$', line)
            require(match is not None, 'malformed map actor observation')
            value = {key: [float(n) for n in match[index].split(',')] for key, index in (('scale', 2), ('location', 3))}
            require(all(len(v) == 3 and all(math.isfinite(n) for n in v) for v in value.values()), 'invalid actor transform')
            once(result['actors'], match[1], value)
    require(result['identity'] is not None and result['assets'] and result['actors'], 'incomplete runtime fixture evidence')
    return result


def check_runtime(log, expected):
    descriptor = os.open(log, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), 'runtime log must be a regular file')
        data = source.read(16 * 1024**2 + 1)
    require(len(data) <= 16 * 1024**2, 'runtime log exceeds evidence bound')
    observed = runtime(data.decode())
    expected_raw = expected.read_bytes()
    require(observed == json.loads(expected_raw), 'runtime map/assets/config/renderer differ from expected fixture')
    log_sha, expected_sha = hashlib.sha256(data).hexdigest(), hashlib.sha256(expected_raw).hexdigest()
    require(digest(log) == log_sha and digest(expected) == expected_sha, 'runtime evidence changed during checking')
    return dict(runtime_checks_passed=True, native_parity=False, observed=observed,
                log_sha256=log_sha, expected_sha256=expected_sha)


def source_record(source):
    from atelier import provenance
    status = provenance.status(root=source)
    require(not any(line.startswith('??') for line in status.splitlines()), 'record or remove untracked source first')
    return dict(revision=provenance.head(root=source), patch=provenance.git('diff', '--binary', 'HEAD', root=source))


def retain(build, destination, *, source, recorded_source, label, extras=(), frozen_asset=None, frozen_sha=None):
    """@cc [owner:fontanierh,label:correctness] isolated-cook-acceptance-evidence
    Retention MUST verify the completed receipt, raw observed log and independent archived bytes
    before publishing its evidence manifest. It MUST NOT write build stamps, restore cooker state,
    run native work or claim semantic parity. A frozen serialization source MUST remain byte-identical.
    """
    require(not destination.exists(), 'choose a new evidence destination; never overwrite a previous sample')
    require(destination.resolve() != build.resolve() and build.resolve() not in destination.resolve().parents,
            'retain evidence outside the build tree that the next cook replaces')
    if frozen_asset is not None or frozen_sha is not None:
        require(frozen_asset is not None and frozen_sha is not None, 'supply both frozen asset and SHA')
        frozen(frozen_asset, frozen_sha)
    spec = importlib.util.spec_from_file_location('sandbox_cook_inventory', Path(__file__).with_name('cook_experiment.py'))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    receipt_path = build / 'package/cook.json'
    stamp = build / 'stamps/unreal.cook.json'
    receipt_raw, stamp_raw = receipt_path.read_bytes(), stamp.read_bytes()
    receipt = json.loads(receipt_raw)
    guard = build / 'logs/unreal.cook.guard'
    observation_path = guard / 'cook-observation.json'
    observation_raw = observation_path.read_bytes()
    identities = {path: hashlib.sha256(raw).hexdigest() for path, raw in
                  ((receipt_path, receipt_raw), (stamp, stamp_raw), (observation_path, observation_raw))}
    observation = json.loads(observation_raw)
    require(receipt['experimental'] is True and receipt['native_parity'] is False
            and receipt['cook'] == observation and observation['validated'] is True
            and observation['command_succeeded'] is True and observation['cook_completed'] is True
            and observation['modern_dependencies'] is True, 'cook receipt lacks matching completed modern observation')
    require(observation.get('reason') == label, 'sample label differs from this cook reason; do not retain a previous run')
    require(digest(guard / 'stdout.log') == observation['log_sha256'], 'retained UAT log differs from the observed byte stream')
    recorded = json.loads(recorded_source.read_text())
    require(source_record(source) == recorded, 'source differs from the pre-run record')
    require(recorded['revision'] == receipt['source']['revision']
            and bool(recorded['patch']) == receipt['source']['dirty'], 'source identity differs from cook receipt')
    app = tool.app(build / 'package')
    require(not app.is_symlink() and app.resolve().is_relative_to((build / 'package/archive').resolve()),
            'archived app must remain inside its owned archive')
    require(tool.inventory(app, sys.stdout) == receipt['files'], 'archived app differs from the cook receipt')
    for path in app.rglob('*'):
        if path.is_symlink():
            require(not Path(os.readlink(path)).is_absolute()
                    and path.resolve(strict=True).is_relative_to(app.resolve()), 'archived app has a nonportable/external symlink')
    for path in guard.rglob('*'):
        require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'guard evidence contains an unsupported leaf')
    destination.mkdir(parents=True)
    deadline, spoken = time.monotonic() + 2700, time.monotonic()
    def copy_owned(source_path, target):
        nonlocal spoken
        source_path = Path(source_path)
        require(any(source_path.resolve().is_relative_to(root.resolve()) for root in (app, guard)),
                'evidence copy escaped its owned source tree')
        descriptor = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source_file, Path(target).open('xb') as output:
            info = os.fstat(source_file.fileno())
            require(stat.S_ISREG(info.st_mode), 'evidence copy requires an owned regular file')
            os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
            for block in iter(lambda: source_file.read(1024**2), b''):
                require(time.monotonic() < deadline, 'evidence copy exceeded 45 minutes')
                output.write(block)
                if time.monotonic() - spoken >= 25:
                    print(f'cook evidence: copying {source_path.name}', flush=True)
                    spoken = time.monotonic()
    try:
        copied = destination / 'app' / app.name
        shutil.copytree(app, copied, symlinks=True, copy_function=copy_owned)
        shutil.copytree(guard, destination / 'guard', symlinks=False, copy_function=copy_owned)
        shutil.copy2(receipt_path, destination / 'cook.json')
        value = json.loads(stamp_raw)
        require(value['fingerprint'] == receipt['source']['fingerprint'], 'cook stamp differs from the certified source')
        require(not any(value.get(key) for key in ('touched', 'restored_from', 'reused_from', 'pooled_from')),
                'sample must be actual native execution, not a touched/restored stamp')
        commands = [item for item in value.get('commands', []) if item.get('kind') == 'UnrealPackage']
        require(len(commands) == 1 and commands[0].get('scope') == 'command invocation'
                and commands[0].get('phases', {}).get('cook') == observation,
                'native package command receipt does not match this cook observation')
        shutil.copy2(stamp, destination / 'unreal.cook.stamp.json')
        (destination / 'source.patch').write_text(recorded['patch'])
        shutil.copy2(recorded_source, destination / 'source-record.json')
        names = set()
        for path in extras:
            require(path.is_file() and not path.is_symlink() and path.name not in names, 'extra evidence must have unique regular names')
            names.add(path.name)
            target = destination / 'extra' / path.name
            target.parent.mkdir(exist_ok=True)
            expected = digest(path)
            shutil.copy2(path, target)
            require(digest(path) == expected == digest(target), 'extra evidence changed during retention')
        require(tool.inventory(copied, sys.stdout) == receipt['files']
                and tool.inventory(app, sys.stdout) == receipt['files'], 'source/copied archive changed during retention')
        require(digest(destination / 'guard/stdout.log') == observation['log_sha256'], 'copied log changed')
        require(digest(guard / 'stdout.log') == observation['log_sha256'], 'source log changed during retention')
        for path, copy in ((receipt_path, destination / 'cook.json'), (stamp, destination / 'unreal.cook.stamp.json'),
                           (observation_path, destination / 'guard/cook-observation.json')):
            require(digest(path) == identities[path] == digest(copy), 'receipt, observation or stamp changed during retention')
        require(source_record(source) == recorded, 'source changed during retention')
        if frozen_asset is not None:
            frozen(frozen_asset, frozen_sha)
        files = {p.relative_to(destination).as_posix(): digest(p) for p in sorted(destination.rglob('*'))
                 if p.is_file() and not p.is_symlink()}
        report = dict(schema=1, label=label, native_parity=False, files=files,
                      source=receipt['source'], observation=observation,
                      frozen_asset_sha256=frozen_sha, retained_only=True)
        temporary = destination / '.evidence.json.tmp'
        with temporary.open('x') as output:
            output.write(json.dumps(report, indent=2) + '\n')
        temporary.replace(destination / 'evidence.json')
        return report
    except BaseException:
        # Partial evidence stays inspectable but cannot masquerade as a completed manifest.
        (destination / 'evidence.json').unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('retain'); p.add_argument('build', type=Path); p.add_argument('destination', type=Path)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--label', required=True)
    p.add_argument('--source-record', required=True, type=Path)
    p.add_argument('--extra', action='append', default=[], type=Path)
    p.add_argument('--frozen-asset', type=Path); p.add_argument('--frozen-sha')
    p = sub.add_parser('runtime'); p.add_argument('log', type=Path); p.add_argument('expected', type=Path)
    p = sub.add_parser('frozen'); p.add_argument('asset', type=Path); p.add_argument('sha256')
    p = sub.add_parser('record'); p.add_argument('source', type=Path); p.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'retain':
        result = retain(args.build, args.destination, source=args.source, label=args.label, extras=args.extra,
                        recorded_source=args.source_record, frozen_asset=args.frozen_asset, frozen_sha=args.frozen_sha)
    elif args.action == 'runtime':
        result = check_runtime(args.log, args.expected)
    elif args.action == 'frozen':
        frozen(args.asset, args.sha256); result = dict(frozen=True, sha256=args.sha256, native_parity=False)
    else:
        result = source_record(args.source)
        with args.destination.open('x') as output:
            output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
