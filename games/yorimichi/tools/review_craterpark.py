"""The Crater Park tour: screenshots (and optional flythroughs) of the generated park in the island, under the render
guard, for the owner's page after every build (docs/CRATERPARK.md, "Review").

    nice -n 10 uv run python games/yorimichi/tools/review_craterpark.py            # the tour, about 6-15 min
    nice -n 10 uv run python games/yorimichi/tools/review_craterpark.py --video    # plus one flythrough per line
    nice -n 10 uv run python games/yorimichi/tools/review_craterpark.py --plan     # the shot list only, no game

The cameras follow the park as built, from the build's own outputs, so the tour changes with the layout:
- `craterpark/park.json`: the park actor's transform and one start per line (`lines`, else the drop-in `spawn`);
- `craterpark/v2/geometry.npz`: every feature's faces, for the aerials and each feature's framing;
- `craterpark/v2/geometry-report.json`: the airs (`checks` kind 'air': lip, landing start, lip angle);
- `craterpark/v2/lines/<line>.npz`: each line's path, for the flythroughs;
- the layout module (v2/layout.py, through generate.default_layout): feature kinds and the bowls, and gaps or features
  the geometry does not have yet.

Shots: `aerial` and `aerial_plan` (the whole park), `tower_<line>` (from the tower deck down each line), `gap_<feature>`
(a side view of every air with the rider launched off the lip at the design speed and caught near the apex), and
`feature_<id>` (every bowl, half bowl, elbow or quarter pipe; berms when there are none). The worker runs the editor
game (`-game`, live bridge), takes every shot in the game's own look, writes `tour.json` and `index.html` (a contact
sheet), and quits only the game it launched.
"""
from pathlib import Path
from contextlib import ExitStack
import argparse, html, importlib, json, math, shutil, subprocess, sys, time

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
sys.path.insert(0, str(GAME / 'world' / 'regions'))
import numpy as np  # noqa: E402
from atelier.play_limits import GAME_GIB, GAME_MAX_GIB  # noqa: E402
import yori  # noqa: E402
from craterpark import placement  # noqa: E402

LIP_SPEED = 18.5          # m/s: the airs' design lip speed (plan/layout.md: 17.8-18.9)
G = 9.81
SHOT_TYPES = ('aerial', 'tower', 'gap', 'feature')
FEATURE_WORDS = ('half_bowl', 'quarter', 'qp', 'elbow', 'vert')
# The r4 review's fixed views round the caldera and of the volcano from far away (island metres x east, y north, z up;
# camera, target, horizontal FOV): kind 'far', taken only when asked (--shots far), to check the park stays hidden.
FAR = {
    'rim': ((1180, 2080, 735), (900, 2420, 690), 62.),
    'zeppelin': ((300, 1300, 1300), (860, 2420, 650), 55.),
    'city': ((720, 430, 82), (850, 2400, 600), 55.),
    'hidamari': ((760, 260, 33), (850, 2400, 560), 50.),
    'hidamari_east': ((1000, 300, 34), (850, 2400, 560), 50.),
    'belmonte': ((550, 4500, 215), (850, 2400, 560), 50.),
    'trail': ((1060, 1130, 175), (850, 2400, 700), 55.),
}


# ---------------------------------------------------------------------------------------------------- the shot plan
def ue(native):
    """Native (x, y up, z) metres -> island Unreal cm (park.json's own transform)."""
    return [round(float(v), 1) for v in placement.to_unreal(np.asarray(native, 'f8'))]


def ue_dir(at, d):
    """A native direction at a native point -> an Unreal cm vector of the same length in metres x 100."""
    return (placement.to_unreal(np.asarray(at, 'f8') + d) - placement.to_unreal(np.asarray(at, 'f8'))).tolist()


def flat(v):
    v = np.array([v[0], 0., v[2]], 'f8'); n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.array([1., 0., 0.])


def shot(kind, name, camera, target, fov, about, **extra):
    """One camera: Unreal cm (world), horizontal FOV degrees."""
    return {'kind': kind, 'name': name, 'camera_cm': [round(float(c), 1) for c in camera],
            'target_cm': [round(float(c), 1) for c in target], 'fov': fov, 'about': about, **extra}


def features(out):
    """{feature: {'centre', 'lo', 'hi', 'normal' (mean of its upward faces, native), 'top'}} from geometry.npz."""
    path = out / 'v2' / 'geometry.npz'
    if not path.exists():
        return {}
    data = np.load(path)
    index = json.loads(str(data['index']))
    pts, nrm = {}, {}
    for i, _ in enumerate(index['render']):
        p = f'r{i}_'
        V, F = data[p + 'V'], data[p + 'F']
        names = [str(n) for n in data[p + 'features']]
        t = V[F]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        for k, name in enumerate(names):
            m = data[p + 'feature'] == k
            if not m.any():
                continue
            pts.setdefault(name, []).append(t[m].reshape(-1, 3))
            nrm.setdefault(name, []).append(n[m][n[m][:, 1] > 0].sum(0) if (n[m][:, 1] > 0).any() else np.zeros(3))
    result = {}
    for name, chunks in pts.items():
        a = np.concatenate(chunks)
        lo, hi = a.min(0), a.max(0)
        normal = np.sum(nrm[name], 0)
        result[name] = {'centre': ((lo + hi) / 2).tolist(), 'lo': lo.tolist(), 'hi': hi.tolist(),
                        'normal': (normal / max(np.linalg.norm(normal), 1e-9)).tolist(), 'top': float(hi[1])}
    return result


def layout_module():
    """The layout generate.py builds (D's v2/layout.py once it has park(), else M0), and D's data module if present."""
    from craterpark.v2 import generate
    mods = []
    for name in dict.fromkeys([generate.default_layout(), 'layout']):
        try:
            mods.append(importlib.import_module(f'craterpark.v2.{name}'))
        except Exception as e:                     # a layout mid-edit must not stop the tour
            print('tour: layout', name, 'not readable:', type(e).__name__, e, flush=True)
    return mods


def along(line, layout, s):
    """A native point on a layout line at plan distance s (its profile height), and the plan direction there."""
    s = float(np.clip(s, 0., line.path.length))
    if hasattr(line.path, 'at'):
        # A vert elbow includes an airborne drift between separate ground
        # legs. Its authored path can be evaluated without inventing a curve
        # across that discontinuity.
        p, d = line.path.at(s)
    else:
        c = layout.curve(line.path)
        p = np.asarray(c.point([s]), 'f8').reshape(-1)[:2]
        d = np.asarray(c.tangent([s]), 'f8').reshape(-1)[:2]
    k = np.asarray([(a, b) for a, b, _ in layout.knots(line)], 'f8')
    y = float(np.interp(s, k[:, 0], k[:, 1]))
    return np.array([p[0], y, p[1]]), np.array([d[0], 0., d[1]])


def plan(out=None):
    """Every shot of the tour, from the build's outputs and the layout (see the module docstring)."""
    out = Path(out or yori.OUT / 'craterpark')
    park = json.loads((out / 'park.json').read_text())
    report = json.loads((out / 'v2' / 'geometry-report.json').read_text()) if (out / 'v2' / 'geometry-report.json').exists() else {}
    feats = features(out)
    mods = layout_module()
    data = next((m for m in mods if hasattr(m, 'LINES')), None)
    shots = []

    # the whole park: v2 stays on the r4 block (dressing.check), so its bounds frame every layout the same way
    t = placement.ground_triangles().reshape(-1, 3)          # island metres
    starts = park.get('lines') or [{'key': 'drop-in', 'name': 'Drop-in', 'spawn': park['spawn']}]
    tower = np.asarray(starts[0]['spawn']['location_cm'], 'f8')
    c = (t.min(0) + t.max(0)) / 2
    centre = np.array([c[0] * 100, -c[1] * 100, c[2] * 100]); size = float(np.linalg.norm((t.max(0) - t.min(0))[:2]))
    back = tower - centre; back[2] = 0; back /= max(np.linalg.norm(back), 1.)
    shots.append(shot('aerial', 'aerial', centre + back * size * 100 * .75 + [0, 0, size * 100 * .45], centre, 60.,
                      'the whole park from above and behind the tower'))
    shots.append(shot('aerial', 'aerial_plan', centre + back * 100 + [0, 0, size * 100 * 1.05], centre, 60.,
                      'the whole park from straight above (north is not up: the camera faces the park from the tower)'))

    # the tower deck, down each line
    for line in starts:
        at = np.asarray(line['spawn']['location_cm'], 'f8'); yaw = math.radians(line['spawn']['yaw_deg'])
        f = np.array([math.cos(yaw), math.sin(yaw), 0.])
        shots.append(shot('tower', f'tower_{line["key"]}', at - f * 300 + [0, 0, 220], at + f * 6000 + [0, 0, -2200], 75.,
                          f'{line.get("name", line["key"])}: from the roll-in crest down the line', line=line['key']))

    # every air, from the side, with the rider launched off the lip
    airs = [c for c in report.get('checks', []) if c.get('kind') == 'air' and 'lip' in c]
    if not airs and data is not None:                       # from the layout: its gap features
        for line in data.LINES:
            for f in line.features:
                if f.kind == 'gap':
                    lip, d = along(line, data, f.s0); land, _ = along(line, data, f.s1)
                    take = next((g for g in line.features if g.tag == 'takeoff' and abs(g.s1 - f.s0) < 1), None)
                    deg = float(take.params.get('lip_deg', 24)) if take else 24.
                    airs.append({'feature': f.id, 'lip': lip.tolist(), 'landing_start': land.tolist(), 'lip_degrees': deg,
                                 'gap': f.s1 - f.s0, 'from': 'layout'})
    for a in airs:
        lip, land = np.asarray(a['lip'], 'f8'), np.asarray(a['landing_start'], 'f8')
        d = flat(land - lip); side = np.array([-d[2], 0., d[0]])
        gap = float(a.get('gap', np.linalg.norm((land - lip)[[0, 2]])))
        mid = lip + d * (gap / 2 + 4.)
        cam = mid + side * max(30., 1.5 * gap) + [0, 4., 0]
        deg = math.radians(float(a.get('lip_degrees', 24.)))
        velocity = (d * math.cos(deg) + np.array([0, math.sin(deg), 0])) * LIP_SPEED
        shots.append(shot('gap', f'gap_{a["feature"]}', ue(cam), ue(mid + [0, 3., 0]), 62.,
                          f'{a["feature"]}: a {gap:.0f} m gap from the side, the rider launched at {LIP_SPEED} m/s',
                          lip_cm=ue(lip), yaw=round(math.degrees(math.atan2(*ue_dir(lip, d)[1::-1])), 2),
                          launch_cm_s=[round(v, 1) for v in ue_dir(lip, velocity)],
                          apex_s=round(LIP_SPEED * math.sin(deg) / G, 2)))

    # bowls, half bowls, elbows and quarter pipes: framed from their geometry, else from the layout
    kinds = {c['feature']: c['kind'] for c in report.get('checks', []) if 'feature' in c and 'kind' in c}
    if data is not None:
        for line in data.LINES:
            for f in line.features:
                kinds.setdefault(f.id, f.kind)
        for b in getattr(data, 'BOWLS', ()):
            kinds.setdefault(b.id, 'bowl')
    wanted = [k for k, v in kinds.items() if v == 'bowl' or any(w in v or w in k for w in FEATURE_WORDS)]
    if not any(kinds.get(k) != 'bowl' for k in wanted):
        wanted += [k for k, v in kinds.items() if v == 'berm']
    t0 = np.asarray(ue([0, 0, 0]), 'f8')
    for fid in wanted:
        f = feats.get(fid)
        if f is None and data is not None:                  # not built yet: from the layout
            b = next((b for b in getattr(data, 'BOWLS', ()) if b.id == fid), None)
            if b is not None:
                c = np.array([b.centre[0], b.rim_y, b.centre[1]]); r = np.array(b.size + (0,))[[0, 2, 1]] / 2
                f = {'centre': c.tolist(), 'lo': (c - [r[0], b.rim_y - b.floor_y, r[0]]).tolist(),
                     'hi': (c + [r[0], 0, r[0]]).tolist(), 'normal': [0, 1, 0], 'top': b.rim_y}
            else:
                g = next(((ln, x) for ln in data.LINES for x in ln.features if x.id == fid), None)
                if g:
                    p, _ = along(g[0], data, (g[1].s0 + g[1].s1) / 2)
                    h = g[1].width / 2
                    f = {'centre': p.tolist(), 'lo': (p - [h, 4, h]).tolist(), 'hi': (p + [h, 4, h]).tolist(),
                         'normal': [0, 1, 0], 'top': float(p[1] + 4)}
        if f is None:
            continue
        c, lo, hi = (np.asarray(f[k], 'f8') for k in ('centre', 'lo', 'hi'))
        extent = float(max(np.linalg.norm((hi - lo)[[0, 2]]), 8.))
        n = np.asarray(f['normal'], 'f8'); n[1] = 0
        if np.linalg.norm(n) > .3:                          # a wall facing one way: look into its transition
            n /= np.linalg.norm(n)
            cam = c + n * (extent * .9 + 6.) + [0, f['top'] - c[1] + extent * .25 + 2., 0]
        else:                                               # a bowl: from its rim on the tower's side, looking down in
            toward = np.asarray(placement.to_unreal(c), 'f8')
            u = (tower - toward); u[2] = 0; u /= max(np.linalg.norm(u), 1.)
            # back to native: probe the transform's plan axes
            ex = np.asarray(ue([1, 0, 0]), 'f8') - t0; ez = np.asarray(ue([0, 0, 1]), 'f8') - t0
            w = np.linalg.solve(np.stack([ex[:2], ez[:2]], 1), u[:2])
            w = np.array([w[0], 0, w[1]]); w /= max(np.linalg.norm(w), 1e-9)
            cam = c + w * extent * .55 + [0, f['top'] - c[1] + extent * .35 + 4., 0]
        shots.append(shot('feature', f'feature_{fid}', ue(cam), ue(c), 70., f'{fid} ({kinds.get(fid, "?")})'))
    for name, (at, target, fov) in FAR.items():
        shots.append(shot('far', name, [at[0] * 100, -at[1] * 100, at[2] * 100], [target[0] * 100, -target[1] * 100, target[2] * 100],
                          fov, 'the r4 review view ' + name))
    return shots


def line_paths(out=None):
    """{line: (k, 3) native path} from the generated line files, only the lines park.json starts (a file left from an
    earlier layout is skipped)."""
    out = Path(out or yori.OUT / 'craterpark'); folder = out / 'v2' / 'lines'
    if not folder.exists():
        return {}
    park = json.loads((out / 'park.json').read_text()) if (out / 'park.json').exists() else {}
    keys = {ln['key'] for ln in park.get('lines', [])}
    return {p.stem: np.load(p)['path'] for p in sorted(folder.glob('*.npz')) if not keys or p.stem in keys}


def chase(path, step=1.5, behind=10., ahead=14., up=5.):
    """Chase-camera frames along a native path: [(camera, target)] in Unreal cm."""
    p = np.asarray(path, 'f8')
    seg = np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=1)
    s = np.concatenate([[0.], np.cumsum(seg)])
    if s[-1] <= 0:
        return []
    def at(q):
        q = np.clip(q, 0, s[-1]); return np.stack([np.interp(q, s, p[:, k]) for k in range(3)], -1)
    frames = []
    for q in np.arange(0., s[-1], step):
        cam = at(q - behind) + [0, up, 0]; tgt = at(q + ahead) + [0, 1., 0]
        frames.append((ue(cam), ue(tgt)))
    return frames


def contact_sheet(out, shots, videos):
    rows = ''.join(f'<figure><img src="{html.escape(s["name"])}.png" loading="lazy"><figcaption><b>{html.escape(s["name"])}</b> '
                   f'{html.escape(s["about"])}</figcaption></figure>' for s in shots if (out / f'{s["name"]}.png').exists())
    vids = ''.join(f'<figure><video src="{html.escape(v)}" controls muted loop></video><figcaption>{html.escape(v)}</figcaption></figure>'
                   for v in videos)
    (out / 'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Crater Park tour</title><style>body{font:14px system-ui;margin:16px;background:#f6f4ef;color:#222}'
        'main{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}figure{margin:0}'
        'img,video{width:100%;border-radius:6px}@media(prefers-color-scheme:dark){body{background:#1b1b1b;color:#ddd}}</style>'
        f'<h1>Crater Park tour</h1><main>{rows}{vids}</main>\n')


# ---------------------------------------------------------------------------------------------------- the game run
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--plan', action='store_true', help='print the shot list and exit (no game)')
    parser.add_argument('--port', type=int, default=8841)
    parser.add_argument('--shots', default='', help='comma-separated shot names or kinds: aerial, tower, gap, feature (the default), far')
    parser.add_argument('--video', action='store_true', help='also film a chase flythrough of each line (mp4, ffmpeg)')
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--no-rider', action='store_true', help='gap shots without launching the rider')
    parser.add_argument('--out', default='', help='folder for the shots (default: build output craterpark/review)')
    parser.add_argument('--settle', type=float, default=6., help='seconds to wait at each camera before the shot')
    parser.add_argument('--memory-gib', type=float, default=GAME_GIB, help=f'memory guard limit, {GAME_GIB:g} (the default) to {GAME_MAX_GIB:g} GiB, as atelier play')
    parser.add_argument('--startup', type=float, default=780., help='seconds to wait for the game (a first run builds shaders)')
    args = parser.parse_args()
    if not math.isfinite(args.memory_gib) or not GAME_GIB <= args.memory_gib <= GAME_MAX_GIB:
        sys.exit(f'--memory-gib must be {GAME_GIB:g} to {GAME_MAX_GIB:g}')
    wanted = args.shots.split(',') if args.shots else SHOT_TYPES
    shots = [s for s in plan() if s['name'] in wanted or s['kind'] in wanted]
    frames = {k: chase(p) for k, p in line_paths().items()} if args.video else {}
    if args.plan:
        print(json.dumps({'shots': shots, 'video_frames': {k: len(v) for k, v in frames.items()}}, indent=1))
        return 0
    from atelier import live
    from atelier.build import Context
    from atelier.harness.safety import guarded
    live.URL = f'http://127.0.0.1:{args.port}'
    out = Path(args.out) if args.out else yori.OUT / 'craterpark' / 'review'
    out.mkdir(parents=True, exist_ok=True)
    budget = args.settle + 6 + sum(len(v) for v in frames.values()) * .7 + 60
    work = len(shots) * (args.settle + 6) + sum(len(v) for v in frames.values()) * .7 + 120
    if not args.worker:
        argv = [sys.executable, str(Path(__file__).resolve()), '--worker', '--port', str(args.port), '--out', str(out),
                '--settle', str(args.settle), '--startup', str(args.startup), '--memory-gib', str(args.memory_gib),
                '--fps', str(args.fps)] + (['--shots', args.shots] if args.shots else []) + (['--video'] if args.video else []) \
            + (['--no-rider'] if args.no_rider else [])
        return guarded.run(argv, out / 'guard', timeout=args.startup + work + budget, purpose='Crater Park tour', kind='game',
                           limit_gib=args.memory_gib)
    return worker(args, out, shots, frames, Context('yorimichi'), live, args.startup + work + budget)


def worker(args, out, shots, frames, ctx, live, duration):
    from atelier.harness.safety.guard import attach as attach_memory_guard, reap
    from atelier.harness.safety.process import spawn_game
    (out / 'passed.json').unlink(missing_ok=True)
    (out / 'tour.json').write_text(json.dumps({'shots': shots}, indent=1) + '\n')
    log = (out / 'game.log').open('w')
    cmd = [str(ctx.unreal_app), str(ctx.uproject), '/Game/Japan/Maps/Slice', '-game', '-windowed', '-resx=1536', '-resy=1024',
           '-nosplash', '-stdout', f'-liveport={args.port}', '-ini:Engine:[HTTPServer.Listeners]:DefaultBindAddress=localhost',
           '-preferencesfile=' + str(out / 'settings.txt'), '-ExecCmds=t.MaxFPS 60,r.RHISetGPUCaptureOptions 0,DisableAllScreenMessages']
    p = spawn_game(cmd, stdout=log, stderr=subprocess.STDOUT)
    guards = ExitStack()
    monitor = None

    def run(code):
        if monitor is not None and monitor.poll() is not None and p.poll() is None:
            raise RuntimeError('Memory monitor exited before the game')
        r = live.request('/python', code, timeout=60)
        if not r.get('ok'):
            raise RuntimeError(r)
        text = r.get('output', '').strip()
        if text:
            print(text, flush=True)
        return r

    def capture(path, wait=30.):
        path.unlink(missing_ok=True)
        run('unreal.LiveLibrary.screenshot(' + repr(str(path)) + ')')
        deadline = time.monotonic() + wait
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert path.exists(), path

    def camera(at, target, fov):
        run('assert unreal.MegaParkValidation.review_camera(unreal.Vector(%r,%r,%r),unreal.Vector(%r,%r,%r),%r)'
            % (*at, *target, fov))

    videos, done = [], []
    try:
        monitor = guards.enter_context(attach_memory_guard(p.pid, out / 'memory-health.json', duration=duration,
                                                            limit_gib=args.memory_gib))
        deadline = time.monotonic() + args.startup
        while time.monotonic() < deadline:
            if p.poll() is not None:
                raise RuntimeError('Game exited ' + str(p.returncode))
            try:
                state = live.request('/state', timeout=1); break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Bridge startup timed out')
        (out / 'initial-state.json').write_text(json.dumps(state, indent=2))
        run("import unreal, json\nw=unreal.LiveLibrary.game_world()\nparks=unreal.GameplayStatics.get_all_actors_of_class(w,unreal.SuperUltraMegaPark)\n"
            "crater=[a for a in parks if abs(a.get_actor_location().z-%r)<1]\nassert crater,'no Crater Park actor'\n"
            "print('crater park components',len(crater[0].get_components_by_class(unreal.StaticMeshComponent)))"
            % placement.unreal_transform()['location_cm'][2])
        run('unreal.YorimichiLive.film_hud(True)')
        riding = False
        for i, s in enumerate(shots):
            camera(s['camera_cm'], s['target_cm'], s['fov'])
            # the island streams textures and builds distance fields for a while after loading
            time.sleep(25 if i == 0 else args.settle)
            if s['kind'] == 'gap' and not args.no_rider:
                lip = s['lip_cm']
                # on the lip facing the landing, then the design lip velocity; the apex comes about apex_s later
                run(f'unreal.YorimichiLive.skate_place(unreal.Vector({lip[0]},{lip[1]},{lip[2]}),{s["yaw"]})')
                time.sleep(.3)
                v = s['launch_cm_s']
                run(f'unreal.YorimichiLive.skate_launch(unreal.Vector({v[0]},{v[1]},{v[2]}))')
                time.sleep(max(s['apex_s'] - .15, .2))
                riding = True
            capture(out / f'{s["name"]}.png')
            done.append(s['name'])
            if riding:
                time.sleep(2.5)                               # let him land before the next camera
                (out / f'{s["name"]}-ride.txt').write_text(run('print(unreal.YorimichiLive.skate_state())')['output'])
                riding = False
        for line, cams in frames.items():
            folder = out / f'video_{line}'; shutil.rmtree(folder, ignore_errors=True); folder.mkdir()
            camera(*cams[0], 80.); time.sleep(args.settle)
            for k, (at, target) in enumerate(cams):
                camera(at, target, 80.)
                time.sleep(.12)
                capture(folder / f'{k:05d}.png', wait=10.)
            mp4 = out / f'flythrough_{line}.mp4'
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(args.fps), '-i', str(folder / '%05d.png'),
                            '-vf', 'scale=1536:-2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', str(mp4)], check=True)
            shutil.rmtree(folder)
            videos.append(mp4.name)
        run('unreal.MegaParkValidation.restore_player_camera()\nunreal.YorimichiLive.film_hud(False)')
        (out / 'passed.json').write_text(json.dumps({'shots': done, 'videos': videos}, indent=2))
    finally:
        contact_sheet(out, shots, videos)
        try:
            if p.poll() is None:
                live.request('/python', "unreal.SystemLibrary.quit_game(unreal.LiveLibrary.game_world(),None,unreal.QuitPreference.QUIT,False)", timeout=5)
        except Exception:
            pass
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            reap(p)
        guards.close()
        log.close()
    print('CRATER PARK TOUR', len(done), 'shots', len(videos), 'videos ->', out / 'index.html', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
