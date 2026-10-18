"""Validate the committed racing courses before publishing their runtime copy."""
import hashlib
import json
import math
from pathlib import Path

GAME = Path(__file__).resolve().parents[2]
DATA = GAME / 'world/racing/belmonte_courses.json'
SCENE = GAME / 'assets/belmonte/source.json'
FRAME = 'Belmonte region plan metres (+X east, +Y north, Z up); world = region origin + point'


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load(path=DATA, scene=SCENE):
    """@cc [owner:fontanierh,label:correctness] racing-course-source
    Published courses MUST match the committed venue scene, declare their frame and version,
    and have finite nondegenerate closed tracks with measured lap lengths and valid finish
    offsets. Invalid data MUST fail before staging writes any runtime file.
    """
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1 or data.get('frame') != FRAME:
        raise ValueError('Unsupported racing course version or coordinate frame')
    provenance = data.get('source')
    if not isinstance(provenance, dict) or provenance.get('venue_scene_sha256') != hashlib.sha256(Path(scene).read_bytes()).hexdigest():
        raise ValueError('Racing courses differ from their committed venue scene; revalidate them')
    tracks = data.get('tracks')
    if not isinstance(tracks, dict) or set(tracks) != {'turf', 'sand'}:
        raise ValueError('Racing courses must contain turf and sand tracks')
    for name, track in tracks.items():
        if not isinstance(track, dict) or track.get('closed') is not True:
            raise ValueError(f'{name}: the racing course must be closed')
        points = track.get('points')
        if not isinstance(points, list) or not 3 <= len(points) <= 4096 or any(
                not isinstance(p, list) or len(p) != 3 or not all(number(x) for x in p) for p in points):
            raise ValueError(f'{name}: expected 3–4096 finite XYZ course points')
        lengths = [math.dist(a[:2], b[:2]) for a, b in zip(points, points[1:] + points[:1])]
        lap = sum(lengths)
        if min(lengths) <= 1e-6 or lap <= 1.:
            raise ValueError(f'{name}: degenerate racing course segment')
        measured = track.get('length_m')
        if not number(measured) or abs(lap - measured) > .01:
            raise ValueError(f'{name}: racing course lap length differs from its geometry')
        finish = track.get('finish_s')
        if not number(finish) or not 0. <= finish < lap:
            raise ValueError(f'{name}: finish offset must lie inside the racing course lap')
        width = track.get('lane_width_m')
        if not number(width) or width >= 0.:
            raise ValueError(f'{name}: lanes must step inward from the outer course line')
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
        if area <= 0.:
            raise ValueError(f'{name}: racing course must run counter-clockwise')
    return data
