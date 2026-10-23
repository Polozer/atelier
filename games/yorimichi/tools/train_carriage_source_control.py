"""Processless immutable original/current three-carriage source and actual service-byte control."""
import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402
from atelier.atomic_files import atomic_json

COACHES = ('restaurant', 'first-class', 'second-class')


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def namespace(folder, output):
    for key in list(sys.modules):
        if key == 'train' or key.startswith('train.') or key == 'definition': sys.modules.pop(key)
    package = ModuleType('train'); package.__path__ = [str(folder)]; sys.modules['train'] = package
    yori.OUT = output
    return importlib.import_module('train.build')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authority', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    authority = json.loads(args.authority.read_text())
    for path, row in authority['files'].items():
        if digest(Path(path)) != row['sha256']: raise ValueError('Frozen carriage source/input/tool changed')
    root = args.output.parent; frozen = authority['frozen']
    old = namespace(Path(frozen['games/yorimichi/world/train/build.py']).parent, root / 'original')
    old.FU.stage(old.OUT / 'furniture'); images = old.make_textures()
    spec = importlib.util.spec_from_file_location('immutable_carriage_subset', frozen['games/yorimichi/tools/gltf_subset.py'])
    subset = importlib.util.module_from_spec(spec); spec.loader.exec_module(subset)
    controls = {}; infos = {}; placements = {}; atlases = {}; originals = {}
    for coach in old.L.vehicles():
        if coach.name not in COACHES: continue
        print('IMMUTABLE CARRIAGE CONSTRUCTOR START', coach.name, flush=True)
        info = old.build(coach, dict(images)); infos[coach.name] = info
        folder = old.OUT / coach.name; mesh = info['mesh']
        p = json.loads((folder / (coach.name + '-placements.json')).read_text()); placements[coach.name] = p
        leaves = {leaf['name']: 'SM_BTD_' + mesh.removeprefix('SM_BT_') + '_' +
                  ''.join(c if c.isalnum() else '_' for c in leaf['name'].removeprefix('Door_'))
                  for door in p['doors'] for leaf in door['leaves']}
        out = root / 'original-service'; out.mkdir(exist_ok=True)
        originals[coach.name] = {}
        for level in (0, 1, 2):
            source = folder / f'{mesh}_LOD{level}.glb'; doc, binary = subset.read(source)
            originals[coach.name][f'LOD{level}'] = dict(path=str(source), sha256=digest(source),
                source_triangles=info['triangles'][f'LOD{level}'])
            if level == 2: controls[f'{mesh}_LOD2'] = source; continue
            index = subset.names(doc)
            body, blob = subset.keep(doc, binary, drop={index[node] for node in leaves})
            body_path = out / f'{mesh}_LOD{level}.glb'; subset.write(body_path, body, blob); controls[body_path.stem] = body_path
            if level == 0:
                for node, key in leaves.items():
                    part, blob = subset.keep(doc, binary, only={index[node]})
                    target = out / (key + '.glb'); subset.write(target, part, blob); controls[key] = target
        atlas = old.TEX / ('T_BT_' + mesh.removeprefix('SM_BT_') + 'Interior.png')
        if atlas.exists(): atlases[coach.name] = digest(atlas)
        print('IMMUTABLE CARRIAGE CONSTRUCTOR COMPLETE', coach.name, info['triangles'], flush=True)
    current = namespace(GAME / 'world/train', root / 'current')
    source = importlib.import_module('train.carriage_source')
    planner = importlib.import_module('train.plan_carriage'); exporter = importlib.import_module('train.export_carriage')
    current.FU.stage(current.OUT / 'furniture'); images = current.make_textures(); rows = []
    for coach in current.L.vehicles():
        if coach.name not in COACHES: continue
        print('SELECTED CARRIAGE SOURCE START', coach.name, flush=True)
        folder = root / 'source-data' / coach.name
        info = current.build(coach, dict(images), source_sink=source.source_sink(current, folder, addon=authority['addon']))
        if info != {key: infos[coach.name][key] for key in info}: raise ValueError('Original carriage constructor/check census differs')
        if json.loads((folder / 'placements.json').read_text()) != placements[coach.name]:
            raise ValueError('Original carriage doors/seat/collision/placement/query data differs')
        inventory = json.loads((folder / 'inventory.json').read_text())
        for piece in inventory['pieces']:
            key = piece['name']; plan = root / 'plans' / key; product = root / 'exports' / key
            planner.main(['--source', str(folder / piece['source']), '--asset', key, '--output', str(plan)])
            exporter.main(['--input', str(plan / (key + '.glbdata')), '--output', str(product), '--format', '.glb'])
            original = controls.pop(key); actual = product / (key + '.glb')
            if original.read_bytes() != actual.read_bytes(): raise ValueError('Original/current complete carriage GLB bytes differ: ' + key)
            rows.append(dict(coach=coach.name, asset=key, triangles=piece['triangles'],
                original=dict(path=str(original), sha256=digest(original)), current=dict(path=str(actual), sha256=digest(actual))))
            print('CARRIAGE SERVICE GLB BYTE EXACT', key, piece['triangles'], flush=True)
        atlas = current.TEX / ('T_BT_' + info['mesh'].removeprefix('SM_BT_') + 'Interior.png')
        if coach.name in atlases and digest(atlas) != atlases[coach.name]: raise ValueError('Actual rendered interior atlas differs')
        if any(folder.glob('*.glb')): raise ValueError('Source-only capture serialized a combined GLB')
    if controls: raise ValueError('Missing current carriage source/export members')
    for path, row in authority['files'].items():
        if digest(Path(path)) != row['sha256']: raise ValueError('Frozen carriage source/input/tool changed during comparison')
    atomic_json(args.output, dict(schema=1, complete=True, original=authority['original'], source_head=authority['current_head'],
        authority_sha256=digest(args.authority), coverage='immutable_source_actual_atlas_and_service_glb_bytes_only',
        original_combined=originals, current_members=len(rows), maximum_triangles=max(row['triangles'] for row in rows), rows=rows))
    print('CARRIAGE SOURCE AND ACTUAL SERVICE BYTES COMPLETE', len(rows), flush=True)


if __name__ == '__main__': main()
