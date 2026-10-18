"""Bounded real listen-host/guest map travel, with no live bridge or forced positions.

Compile and stage data.network first. Run with --zone KEY (a single static map
zone); both local players use the ordinary map resolver. The host tours first and
vacates the destination before the guest joins. This is same-machine NullRHI
travel/collision acceptance, separate from rendered controller/phone UI checks,
packaging, adverse-network tests and two-machine acceptance.
"""
import argparse
import hashlib
from contextlib import ExitStack
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

from atelier import paths
from atelier.build import Context
from atelier.harness.safety import guarded
from atelier.harness.safety.guard import attach, reap
from atelier.harness.safety.process import spawn_game
from network_review_common import current_native_build, require_clean_source, source_revision


def landing_checks(rows, zone, mode, expected):
    """Admit measured native landing, not just target presence or a successful exit."""
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return {'one_destination': False}
    row = rows[0]
    def finite(value):
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    target, landed = row.get('target'), row.get('landed')
    vectors = all(isinstance(v, list) and len(v) == 3 and all(finite(n) for n in v) for v in [target, landed])
    angles = all(finite(row.get(k)) for k in ['yaw', 'target_yaw'])
    return dict(one_destination=row.get('zone') == zone,
                staged_target=vectors and math.dist(target, expected['target']) < 1,
                staged_yaw=angles and abs((row['target_yaw']-expected['yaw']+180) % 360-180) < .01,
                network_role=row.get('net_mode') == mode and row.get('authority') is (mode == 2),
                floor=all(row.get(k) is True for k in ['on_ground', 'walkable', 'capsule_clear']),
                settled=finite(row.get('speed')) and 0 <= row['speed'] < 5,
                position=vectors and math.dist(target[:2], landed[:2]) < 5 and abs(target[2]-landed[2]) < 30,
                facing=angles and abs((row['yaw']-row['target_yaw']+180) % 360-180) < 1,
                trace_height=finite(row.get('above_cm')) and row['above_cm'] == expected['above_cm'])


def current_data(ctx, zone):
    """Require current producer/import/staging certificates, not a manually copied map."""
    from atelier import build_snapshot
    from atelier.build import load_recipe, order, fingerprint, outputs_present
    build_snapshot.require_complete(ctx.out, game=ctx.game, repo=paths.REPO)
    done = {}
    for step in order(load_recipe(ctx.game).steps(ctx), ['data.network']):
        stamp = json.loads((ctx.stamps / (step.name + '.json')).read_text())
        value = fingerprint(step, done)
        if stamp.get('fingerprint') != value or not outputs_present(step):
            raise RuntimeError('Native map acceptance requires a current build: '+step.name)
        done[step.name] = value
    content = ctx.uproject.parent / 'Content/Data'
    raw = (content / 'map/map.json').read_bytes()
    if raw != (ctx.out / 'map/map.json').read_bytes():
        raise RuntimeError('Staged map differs from the generated producer output')
    selected = [z for z in json.loads(raw)['zones'] if z['key'] == zone]
    if len(selected) != 1:
        raise ValueError('The staged map must contain exactly one chosen static zone')
    entry = selected[0]
    above = entry.get('above_m', 25.)
    if type(above) not in (int, float) or not math.isfinite(above) or not 0 <= above <= 60:
        raise ValueError('Selected zone has invalid authored landing height')
    expected = dict(target=[entry['x']*100, -entry['y']*100, entry['z']*100],
                    yaw=-entry['yaw'], above_cm=above*100)
    identity = json.loads((content / 'Network/session.json').read_text())
    return dict(map_sha256=hashlib.sha256(raw).hexdigest(), expected=expected,
                identity=identity['signature'], stage_fingerprint=done['data.network'])


def read(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def worker(out, zone, port):
    """@cc [owner:fontanierh,label:correctness] native-map-travel-acceptance
    Both native local players MUST use the ordinary map resolver and guest RPC.
    Evidence MUST bind current clean source, compiled modules and staged destination;
    collision-at-destination alone MUST NOT count as accepted player travel. The host
    MUST vacate before the guest tour, and both owned games MUST exit under the normal
    aggregate/actual-child guards before the caller reports acceptance. Controller and
    phone UI, packaged builds and adverse-network coverage remain separate.
    """
    revision = require_clean_source()
    ctx = Context('yorimichi')
    binary = current_native_build(ctx)
    data = current_data(ctx, zone)
    expected = data['expected']
    started, spoken = time.monotonic(), 0.
    games = []
    with ExitStack() as stack:
        def launch(role, destination):
            root = out / role
            root.mkdir()
            log = stack.enter_context((root / 'stdout.log').open('w'))
            cmd = [str(ctx.unreal_app), str(ctx.uproject), destination, '-game', '-nullrhi', '-nosound', '-nosplash',
                   '-nolive', '-unattended', '-stdout', '-FullStdOutLogOutput', '-MULTIHOME=127.0.0.1',
                   '-ExecCmds=t.MaxFPS 30', '-mapqa', '-mapqazone='+zone, '-reviewdir='+str(root),
                   '-preferencesfile='+str(root / 'preferences.txt'), '-markersave='+str(root / 'markers.json'),
                   '-atlasnamesfile='+str(root / 'atlas-names.json')]
            if role == 'host':
                cmd += [f'-port={port}', '-networkqa=server', '-networklisten', '-networkqadir='+str(out / 'session'),
                        '-mapqakeepalive=120']
            (root / 'command.json').write_text(json.dumps(cmd, indent=2)+'\n')
            game = spawn_game(cmd, stdout=log, stderr=subprocess.STDOUT)
            games.append((role, game))
            stack.callback(reap, game)
            monitor = stack.enter_context(attach(game.pid, root / 'memory.json', duration=240, limit_gib=10))
            if monitor is None:
                raise RuntimeError('Actual-child guard unavailable: '+role)
            return game, monitor

        def wait(label, condition, active):
            nonlocal spoken
            while time.monotonic() - started < 235:
                for role, game, monitor in active:
                    if monitor.poll() is not None and game.poll() is None:
                        raise RuntimeError('Actual-child guard lost: '+role)
                    if game.poll() not in (None, 0):
                        raise RuntimeError(f'{role} exited {game.returncode}')
                if condition():
                    print(label+': complete', flush=True)
                    return
                if any(game.poll() is not None for _, game, _ in active):
                    raise RuntimeError('Game exited before '+label)
                if time.monotonic() - spoken > 15:
                    spoken = time.monotonic()
                    print(f'{label}: awaiting native progress, {spoken-started:.1f}s elapsed', flush=True)
                time.sleep(.2)
            raise RuntimeError('Native map travel deadline expired')

        host, host_guard = launch('host', '/Game/Japan/Maps/Slice?game=/Script/Yorimichi.JapanNetworkGameMode?capacity=2?listen')
        active = [('host', host, host_guard)]
        wait('host tour and vacated destination', lambda: read(out / 'host/map_qa.json') is not None and
             read(out / 'session/server-world.json') is not None, active)
        checks = {'host_'+k: v for k, v in landing_checks(read(out / 'host/map_qa.json'), zone, 2, expected).items()}
        if not all(checks.values()):
            raise RuntimeError('Host landing rejected: '+str(checks))
        guest, guest_guard = launch('guest', f'127.0.0.1:{port}')
        active.append(('guest', guest, guest_guard))
        wait('guest tour and native disconnect', lambda: read(out / 'guest/map_qa.json') is not None and
             read(out / 'session/server-complete.json') is not None, active)
        for role, game in games:
            if game.wait(timeout=10) != 0:
                raise RuntimeError('Nonzero native exit: '+role)
        checks.update({'guest_'+k: v for k, v in landing_checks(read(out / 'guest/map_qa.json'), zone, 3, expected).items()})
        connected = read(out / 'session/server-connected.json')
        checks['host_observed_network_admission'] = (isinstance(connected, dict) and connected.get('stage') == 'connected'
            and connected.get('error') == '' and connected.get('net_mode') == 2 and connected.get('players') == 2
            and connected.get('player_pawns') == 2 and connected.get('world_ready') is True
            and connected.get('identity') == data['identity'])
    checks['source_unchanged'] = source_revision() == revision
    checks['native_binary_unchanged'] = current_native_build(ctx) == binary
    checks['staged_data_unchanged'] = current_data(ctx, zone) == data
    report = dict(source=revision, native_build=binary, staged=data, zone=zone, passed=all(checks.values()), checks=checks,
                  scope=__doc__.strip())
    (out / 'checks.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(checks), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zone', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', args.zone):
        parser.error('Choose an authored static zone key')
    root = args.out.resolve()
    if args.worker:
        if args.port is None or not 1 <= args.port <= 65535:
            parser.error('Private worker requires its reserved native port')
        return worker(root, args.zone, args.port)
    require_clean_source()
    ctx = Context('yorimichi')
    current_native_build(ctx)
    current_data(ctx, args.zone)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        parser.error('Use a fresh evidence directory')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    return guarded.run([sys.executable, str(Path(__file__).resolve()), '--worker', '--zone', args.zone,
                        '--out', str(root), '--port', str(port)], root / 'guard', kind='game',
                       timeout=260, progress=15, aggregate_tree=True)


if __name__ == '__main__':
    raise SystemExit(main())
