"""Split a binary glTF by node: a copy keeping some subtrees, with only the meshes, materials, textures and buffer data they
use. Pure Python (no numpy), for the Belmonte train's door leaves (tools/belmonte_train_service.py).

    keep(gltf, binary, drop={...})        # everything but those subtrees (their ancestors keep their meshes)
    keep(gltf, binary, only={...})        # only those subtrees, under their ancestors' transforms (ancestors without meshes)
"""
import json
import struct
from pathlib import Path


def read(path):
    data = Path(path).read_bytes()
    assert data[:4] == b'glTF', path
    length = struct.unpack('<I', data[12:16])[0]
    gltf = json.loads(data[20:20 + length])
    offset = 20 + length
    binary = b''
    if offset < len(data):
        size, kind = struct.unpack('<II', data[offset:offset + 8])
        assert kind == 0x004E4942, path
        binary = data[offset + 8:offset + 8 + size]
    return gltf, binary


def write(path, gltf, binary):
    text = json.dumps(gltf, separators=(',', ':')).encode()
    text += b' ' * (-len(text) % 4)
    binary += b'\0' * (-len(binary) % 4)
    total = 12 + 8 + len(text) + (8 + len(binary) if binary else 0)
    out = struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<II', len(text), 0x4E4F534A) + text
    if binary:
        out += struct.pack('<II', len(binary), 0x004E4942) + binary
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(out)


def names(gltf):
    return {n.get('name'): i for i, n in enumerate(gltf['nodes'])}


def _texture_refs(value, found):
    """Every {'index': n} under a key ending in 'Texture' (core and extension material slots)."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith('Texture') and isinstance(item, dict) and 'index' in item:
                found.append(item)
            _texture_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _texture_refs(item, found)
    return found


def keep(gltf, binary, drop=(), only=None):
    """A new (gltf, binary). `drop`: node indices whose subtrees go. `only`: node indices whose subtrees alone keep
    meshes (their ancestors stay for the transforms)."""
    nodes = gltf['nodes']
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', [])}
    drop = set(drop)

    def under(i, roots):
        while i is not None:
            if i in roots:
                return True
            i = parent.get(i)
        return False
    meshed = {i for i in range(len(nodes)) if not under(i, drop) and (only is None or under(i, set(only)))}
    wanted = set(meshed)
    for i in list(meshed):
        p = parent.get(i)
        while p is not None:
            wanted.add(p)
            p = parent.get(p)
    if only is None:
        wanted = {i for i in range(len(nodes)) if not under(i, drop)}
    order = sorted(wanted)
    node_map = {old: new for new, old in enumerate(order)}
    out = {k: v for k, v in gltf.items() if k not in ('nodes', 'meshes', 'accessors', 'bufferViews', 'buffers', 'materials',
                                                       'textures', 'images', 'samplers', 'scenes', 'skins', 'animations')}
    maps = {k: {} for k in ('meshes', 'accessors', 'bufferViews', 'materials', 'textures', 'images', 'samplers')}
    lists = {k: [] for k in maps}
    blob = bytearray()

    def take(kind, index, build):
        if index not in maps[kind]:
            maps[kind][index] = len(lists[kind])
            lists[kind].append(None)
            lists[kind][maps[kind][index]] = build(gltf[kind][index])
        return maps[kind][index]

    def view(index):
        def build(v):
            data = binary[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']]
            blob.extend(b'\0' * (-len(blob) % 4))
            copy = dict(v, buffer=0, byteOffset=len(blob))
            blob.extend(data)
            return copy
        return take('bufferViews', index, build)

    def accessor(index):
        def build(a):
            assert 'sparse' not in a, 'sparse accessors are not supported'
            copy = dict(a)
            if 'bufferView' in a:
                copy['bufferView'] = view(a['bufferView'])
            return copy
        return take('accessors', index, build)

    def image(index):
        def build(im):
            copy = dict(im)
            if 'bufferView' in im:
                copy['bufferView'] = view(im['bufferView'])
            return copy
        return take('images', index, build)

    def texture(index):
        def build(t):
            copy = dict(t)
            if 'source' in t:
                copy['source'] = image(t['source'])
            if 'sampler' in t:
                copy['sampler'] = take('samplers', t['sampler'], dict)
            for ext in copy.get('extensions', {}).values():
                if isinstance(ext, dict) and 'source' in ext:
                    ext['source'] = image(ext['source'])
            return copy
        return take('textures', index, build)

    def material(index):
        def build(m):
            copy = json.loads(json.dumps(m))
            for ref in _texture_refs(copy, []):
                ref['index'] = texture(ref['index'])
            return copy
        return take('materials', index, build)

    def mesh(index):
        def build(m):
            copy = json.loads(json.dumps(m))
            for p in copy['primitives']:
                p['attributes'] = {k: accessor(v) for k, v in p['attributes'].items()}
                if 'indices' in p:
                    p['indices'] = accessor(p['indices'])
                if 'targets' in p:
                    p['targets'] = [{k: accessor(v) for k, v in t.items()} for t in p['targets']]
                if 'material' in p:
                    p['material'] = material(p['material'])
            return copy
        return take('meshes', index, build)

    new_nodes = []
    for old in order:
        n = {k: v for k, v in nodes[old].items() if k not in ('children', 'mesh', 'skin', 'camera')}
        children = [node_map[c] for c in nodes[old].get('children', []) if c in node_map]
        if children:
            n['children'] = children
        if old in meshed and 'mesh' in nodes[old]:
            n['mesh'] = mesh(nodes[old]['mesh'])
        new_nodes.append(n)
    scene = gltf['scenes'][gltf.get('scene', 0)]
    out['scenes'] = [dict(scene, nodes=[node_map[r] for r in scene['nodes'] if r in node_map])]
    out['scene'] = 0
    out['nodes'] = new_nodes
    for kind in maps:
        if lists[kind]:
            out[kind] = lists[kind]
    out['buffers'] = [{'byteLength': len(blob)}]
    return out, bytes(blob)


def subtree(gltf, root):
    """Node indices of the subtree at `root`."""
    found, stack = [], [root]
    while stack:
        i = stack.pop()
        found.append(i)
        stack.extend(gltf['nodes'][i].get('children', []))
    return found


def triangles(gltf):
    total = 0
    used = {n['mesh'] for n in gltf['nodes'] if 'mesh' in n}
    for m in used:
        for p in gltf['meshes'][m]['primitives']:
            if 'indices' in p:
                total += gltf['accessors'][p['indices']]['count'] // 3
            else:
                total += gltf['accessors'][p['attributes']['POSITION']]['count'] // 3
    return total
