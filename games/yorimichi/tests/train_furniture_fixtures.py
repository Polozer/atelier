"""Small, valid baked GLBs for train pipeline tests; fitted source pairs stay real."""
import io
import json
import struct

from PIL import Image

from atelier.gltf import glb_pack
from train import bake_manifest as BM
from train import furniture as F


def bake(furniture):
    F.stage(furniture)
    lod = furniture / 'lod'
    lod.mkdir(exist_ok=True)
    image = io.BytesIO()
    Image.new('RGB', (4, 4), '#876543').save(image, format='PNG')
    positions = struct.pack('<9f', 0, 0, 0, .1, 0, 0, 0, .1, 0)
    pixels = image.getvalue()
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
                          'min': [0, 0, 0], 'max': [.1, .1, 0]}],
           'bufferViews': [{'buffer': 0, 'byteLength': len(positions)},
                           {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(pixels)}],
           'buffers': [{'byteLength': len(positions) + len(pixels)}],
           'images': [{'bufferView': 1, 'mimeType': 'image/png'}], 'textures': [{'source': 0}],
           'materials': [{'name': 'Baked', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}]}
    raw = glb_pack(doc, positions + pixels)
    summary = {}
    for aid, caps in BM.B.FURNITURE.items():
        screens = BM.B.screen_sizes(aid, .8)
        levels = []
        for k in ([0, 1] if caps[1] else [0]):
            path = lod / f'{aid}_LOD{k}.glb'
            path.write_bytes(raw)
            levels.append({'level': k, 'glb': path.name, 'bytes': len(raw), 'sha256': BM.sha(path),
                           'triangles': 1, 'screen_size': screens[f'lod{k}']})
        summary[aid] = {'source': f'{aid}.glb', 'source_sha256': BM.sha(furniture / f'{aid}.glb'),
                        'levels': levels, 'cull_screen_size': screens['cull'], 'bounds_radius_m': .8}
    (lod / 'summary.json').write_text(json.dumps(summary))
    return summary
