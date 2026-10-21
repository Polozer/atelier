"""Belmonte's ground reads as what it is drawn with: grass, roads, paving, gravel, sand and rock (surfaces.py)."""
import ast
import re
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402,F401
from atelier.gltf import glb_parts  # noqa: E402
from belmonte import source, surfaces  # noqa: E402

GROUND = re.compile(r'SM_BM_(BT_Terrain_|BC_Pave_|BC_Piazza|BHip_(Course|Arenas|Infield|StableYard|SalonGrounds)|BE_\d_Grounds)')
# Plan metres from the region origin, read off the committed scene: what a skateboard, a bike or a foot finds there.
SPOTS = {
    'meadow west of the town': ((-375., 157.), 'Grass'),
    'meadow by the western estate': ((-721., 525.), 'Grass'),
    'country road north of the town': ((73., 237.), 'Road'),
    'road up to the northern estates': ((235., 637.), 'Road'),
    'cobbled street in town': ((41., 133.), 'Stone'),
    'limestone of the river gorge': ((-339., -73.), 'Rock'),
    'gravel path of an estate': ((583., 511.), 'Dirt'),
    'arena sand of an estate': ((661., 41.), 'Sand'),
    'racecourse sand track': ((-160., 372.), 'Sand'),
    'racecourse turf': ((-160., 410.), 'Grass'),
}


@pytest.fixture(scope='module')
def ground():
    return surfaces.ground(source.manifest(), source.LIBRARY, lambda name: bool(GROUND.match(name)))


def test_known_spots_read_their_surface(ground):
    names = list(SPOTS)
    found = surfaces.sample([SPOTS[name][0] for name in names], ground)
    assert {name: key for name, key in zip(names, found)} == {name: SPOTS[name][1] for name in names}


def test_terrain_faces_follow_their_strongest_layer():
    weights = np.array([[.9, .1, 0, 0], [.1, .8, .1, 0], [0, .1, .9, 0], [0, 0, .2, .8]])
    faces = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3], [0, 2, 2]])
    assert list(surfaces.face_keys(weights, faces)) == ['Grass', 'Grass', 'Road', 'Rock', 'Road']


def test_split_tile_keeps_its_geometry_and_names_each_section(tmp_path):
    entry = next(e for e in source.manifest()['meshes'] if e['name'] == 'SM_BM_BT_Terrain_3_3')
    before = source.LIBRARY / entry['path']
    after = tmp_path / 'tile.glb'
    counts = surfaces.split_terrain(before, after)
    assert sum(counts.values()) == entry['triangles'] and set(counts) <= set(surfaces.TERRAIN_KEYS)
    doc, _ = glb_parts(after.read_bytes())
    keys = [surfaces.slot_key(material['name']) for material in doc['materials']]
    assert keys == list(counts) and all(int(m['name'].split('_')[1]) == 0 for m in doc['materials'])
    old, new = source.triangles(before), source.triangles(after)
    assert np.array_equal(np.sort(old.reshape(len(old), -1), 0), np.sort(new.reshape(len(new), -1), 0))


def test_every_walkable_material_names_its_surface():
    """Fix the class: a source material with walkable faces either names a key, is the per-face terrain, or is water
    (which has no collision). A new ground material without a rule fails here instead of riding as concrete."""
    data = source.manifest()
    first = {}
    for placement in data['placements']:
        first.setdefault(placement['asset'], placement)
    unnamed = {}
    for entry in data['meshes']:
        placement = first[entry['source_asset']]
        doc, binary = glb_parts((source.LIBRARY / entry['path']).read_bytes())
        for mesh in doc['meshes']:
            for primitive in mesh['primitives']:
                path = placement['materials'][int(doc['materials'][primitive['material']]['name'].split('_')[1])]
                if surfaces.terrain_material(path) or surfaces.material_key(path) or 'water' in path:
                    continue
                p = surfaces._accessor(doc, binary, primitive['attributes']['POSITION']) @ source.FRAME.T
                f = surfaces._accessor(doc, binary, primitive['indices']).astype(int).reshape(-1, 3)
                n = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
                area = np.linalg.norm(n, axis=1) / 2
                unnamed[surfaces.leaf(path)] = unnamed.get(surfaces.leaf(path), 0.) + area[n[:, 2] > 1.8 * area].sum()
    assert {name: round(area) for name, area in unnamed.items() if area > 300.} == {}


def test_every_key_is_in_the_ride_and_footstep_tables():
    ini = (GAME / 'unreal/Config/DefaultGame.ini').read_text()
    ride = dict(re.findall(r'\("(\w+)",(\w+)\)', re.search(r'^SurfaceMaterials=(.*)$', ini, re.M).group(1)))
    script = ast.parse((GAME / 'unreal/Scripts/import_footsteps.py').read_text())
    steps = next(ast.literal_eval(node.value) for node in script.body
                 if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'MATERIAL_SURFACES')
    assert set(surfaces.KEYS) <= set(ride) and set(surfaces.KEYS) <= set(steps)
    assert {key: ride[key] for key in surfaces.KEYS} == {
        'Grass': 'Grass', 'Stone': 'Stone', 'Rock': 'Stone', 'Dirt': 'Dirt', 'Sand': 'Sand', 'Wood': 'Wood',
        'Metal': 'Metal', 'Road': 'Asphalt'}


def test_instances_carry_their_key_in_the_name():
    assert surfaces.instance_name('MI_BM_0a1b2c3d4e5f', 'Grass') == 'MI_BM_0a1b2c3d4e5f__Grass'
    assert surfaces.instance_name('MI_BM_0a1b2c3d4e5f', None) == 'MI_BM_0a1b2c3d4e5f'
    assert surfaces.material_key('/Game/Haras/Belmonte/Materials/MI_B_cobble.MI_B_cobble') == 'Stone'
    assert surfaces.material_key('/Game/Haras/Belmonte/Materials/MI_B_turf.MI_B_turf') == 'Grass'
    assert surfaces.material_key('/Game/Haras/Belmonte/Materials/MI_B_terrain_town.MI_B_terrain_town') is None
    assert surfaces.leaf('/Game/Maps/HarasValley.HarasValley:PersistentLevel.HarasVillage_1.MID_MI_B_accent_0') == 'accent_0'
