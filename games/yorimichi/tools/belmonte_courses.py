"""Belmonte racecourse centrelines for the racing service (docs/RACING.md).

The Belmonte venue came from Haras Valley, whose venue data keeps each track as a closed centreline sampled every 2 m
(`tracks` in its venue JSON): Blender plan metres, +X east, +Y north, in the frame Belmonte's region keeps
(world/regions/belmonte/layout.py places it at ORIGIN). This tool reads that file once and writes the committed,
simplified copy the game stages (world/racing/belmonte_courses.json); the game never reads Haras Valley data.

    uv run python games/yorimichi/tools/belmonte_courses.py PATH/TO/haras.json
"""
import argparse
import json
import math
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
OUT = GAME / 'world' / 'racing' / 'belmonte_courses.json'
TOLERANCE_M = .01


def simplify(points, tolerance=TOLERANCE_M):
    """Douglas-Peucker on an open run of 2D points (the ends are kept)."""
    if len(points) < 3:
        return list(points)
    (ax, ay), (bx, by) = points[0][:2], points[-1][:2]
    length = math.hypot(bx - ax, by - ay) or 1e-9
    worst, index = 0., 0
    for i in range(1, len(points) - 1):
        px, py = points[i][:2]
        d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
        if d > worst:
            worst, index = d, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[:index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


def length(points, closed=True):
    count = len(points) if closed else len(points) - 1
    return sum(math.dist(points[i][:2], points[(i + 1) % len(points)][:2]) for i in range(count))


def convert(source):
    tracks = source['tracks']
    out = {'version': 1,
           'frame': 'Belmonte region plan metres (+X east, +Y north, Z up); world = region origin + point',
           'source': 'Haras Valley venue data, key tracks (closed centrelines sampled every 2 m), simplified to 1 cm',
           'tracks': {}}
    for name in ('turf', 'sand'):
        track = tracks[name]
        points = [[round(p[0], 3), round(p[1], 3), round(p[2], 3)] for p in track['points']]
        assert track['closed']
        # The finish post is finish_s metres from the first sample: keep that sample first. A closed run is simplified
        # as two open halves split at the sample farthest from it.
        far = max(range(len(points)), key=lambda i: math.dist(points[0][:2], points[i][:2]))
        kept = simplify(points[:far + 1])[:-1] + simplify(points[far:] + [points[0]])[:-1]
        out['tracks'][name] = {'closed': True, 'finish_s': track['finish_s'], 'lane_width_m': track['lane_width'],
                               'length_m': round(length(points), 3), 'points': kept}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source', type=Path, help="Haras Valley venue JSON with a 'tracks' key")
    args = parser.parse_args()
    data = convert(json.loads(args.source.read_text()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(',', ':')) + '\n')
    for name, track in data['tracks'].items():
        print(f"{name}: {len(track['points'])} points, {track['length_m']} m, finish_s {track['finish_s']}")


if __name__ == '__main__':
    main()
