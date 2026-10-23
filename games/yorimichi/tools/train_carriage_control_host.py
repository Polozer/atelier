"""Freeze immutable carriage source/committed inputs on the host before bounded Blender controls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

GAME = Path(__file__).resolve().parents[1]
REPO = GAME.parents[1]
sys.path.insert(0, str(REPO / 'platform/studio'))
from atelier import engine
from atelier.harness.safety.guarded import run

ORIGINAL = '283329c07ea04bee34587022a3d43827468c66d7'


def git(*args): return subprocess.check_output(['git', '-C', str(REPO), *args])


def identity(path):
    if path.is_symlink() or not path.is_file(): raise ValueError('Carriage authority requires regular source files')
    stat = path.stat()
    return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), stat=[stat.st_dev, stat.st_ino,
                stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])


def addon_files():
    resources = Path(engine.blender()).resolve().parent.parent / 'Resources'
    candidates = sorted(resources.glob('*/scripts/addons_core/io_scene_gltf2'))
    if len(candidates) != 1: raise ValueError('Ambiguous installed Blender glTF addon')
    return dict(exporter=candidates[0] / 'blender/exp/export.py', writer=candidates[0] / 'io/exp/export.py')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv); root = args.output.resolve()
    if root.exists(): raise ValueError('Preserve existing carriage control evidence')
    root.mkdir(parents=True)
    head = git('rev-parse', 'HEAD').decode().strip(); status = git('status', '--short')
    records = {}
    def bind(path):
        records[str(path)] = identity(path)
    original = root / 'immutable'
    paths = git('ls-tree', '-r', '--name-only', ORIGINAL, '--', 'games/yorimichi/world/train',
                'games/yorimichi/assets/vehicles/belmonte-train/planning',
                'games/yorimichi/assets/vehicles/belmonte-train/textures',
                'games/yorimichi/assets/vehicles/belmonte-train/furniture',
                'games/yorimichi/assets/vehicles/belmonte-train/source.toml',
                'games/yorimichi/tools/gltf_subset.py').decode().splitlines()
    frozen = {}
    for relative in paths:
        if relative.startswith('games/yorimichi/world/train/') and not relative.endswith('.py'): continue
        data = git('show', ORIGINAL + ':' + relative)
        target = original / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        bind(target); frozen[relative] = str(target)
        # Actual committed input bytes must match the immutable source's inputs.
        if '/assets/' in relative:
            current = REPO / relative; before = identity(current)
            if current.read_bytes() != data: raise ValueError('Carriage committed input changed from immutable authority: ' + relative)
            bind(current)
            if identity(current) != before: raise ValueError('Carriage committed input changed while freezing')
    from atelier.build_inputs import local_imports
    closure = {*local_imports(GAME / 'world/train/build.py', (GAME / 'world', REPO / 'platform/studio')),
               *local_imports(GAME / 'tools/train_carriage_source_control.py',
                              (GAME / 'world', GAME / 'tools', REPO / 'platform/studio')),
               *(GAME / 'world/train').glob('*.py'), Path(__file__)}
    for path in sorted(closure): bind(path)
    addon = addon_files()
    for path in addon.values(): bind(path)
    authority = dict(schema=1, original=ORIGINAL, current_head=head, frozen=frozen, files=records,
                     addon={key: records[str(path)]['sha256'] for key, path in addon.items()})
    authority_path = root / 'authority.json'; authority_path.write_text(json.dumps(authority, indent=2) + '\n')
    result = run([engine.blender(), '--factory-startup', '-b', '--threads', '3', '--python-exit-code', '1', '--python',
        str(GAME / 'tools/train_carriage_source_control.py'), '--', '--authority', str(authority_path),
        '--output', str(root / 'result.json')], root / 'source.guard', timeout=1800, queue_seconds=1800,
        purpose='immutable original three carriage constructors/atlases and bounded service GLB bytes')
    if git('rev-parse', 'HEAD').decode().strip() != head or git('status', '--short') != status:
        raise ValueError('Current source checkout changed during carriage control')
    for path, before in records.items():
        if identity(Path(path)) != before: raise ValueError('Carriage source/input/tool changed during control')
    return result


if __name__ == '__main__': raise SystemExit(main())
