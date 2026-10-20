"""Audit every Belmonte building's collision against what is drawn (no Unreal).

    uv run python games/yorimichi/tools/belmonte_collision_audit.py [--json OUT] [--grid 0.2] [NAME ...]

For each building (belmonte/collision.py groups meshes placed with one transform) it measures the committed hulls
and the shell world.belmonte generates: the interior or wall volume a walker can reach, how deep, the drawn outer
wall and roof left without collision, and the collision triangles. world.belmonte runs the same audit on what it
generates and records it under `building_collision` in build/yorimichi/belmonte/build-report.json; this tool adds
the comparison with the committed hulls. A full run takes about ten minutes and 3 GB.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from belmonte import collision  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('names', nargs='*', help='buildings to audit (default: all)')
    parser.add_argument('--grid', type=float, default=collision.VOXEL, help='voxel size in metres')
    parser.add_argument('--json', type=Path, help='write every row here')
    args = parser.parse_args()
    buildings = collision.buildings()
    rows = []
    print('| building | reachable m3 (hulls -> generated) | deepest m | uncovered wall | uncovered roof | '
          'collision triangles | plugs | seconds |')
    print('|---|---|---|---|---|---|---|---|')
    for name in args.names or buildings:
        started = time.time()
        transform, entries = buildings[name]
        b = collision.load(name, transform, entries, h=args.grid)
        before = collision.audit(b, collision.committed(entries))
        shell = collision.generate(b)
        after = collision.audit(b, shell.faces, stats=False)
        row = {'name': name, 'meshes': [e['name'] for e in entries], 'hulls': before.row(), 'generated': after.row(),
               'plugs': shell.plugs, 'kept_drawn_triangles': shell.skin_triangles, 'seconds': round(time.time() - started, 1)}
        rows.append(row)
        print(f"| {name} | {before.intrusion_m3:.1f} -> {after.intrusion_m3:.1f} | {before.deepest_m:.1f} -> "
              f"{after.deepest_m:.1f} | {before.uncovered_wall:.1%} -> {after.uncovered_wall:.1%} | "
              f"{before.uncovered_roof:.1%} -> {after.uncovered_roof:.1%} | {before.collision_triangles} -> "
              f"{after.collision_triangles} | {shell.plugs} | {row['seconds']} |", flush=True)
    total = sum(r['generated']['collision_triangles'] for r in rows)
    failing = [r['name'] for r in rows if r['generated']['intrusion_m3'] or
               r['generated']['uncovered_wall'] > collision.MAX_UNCOVERED or
               r['generated']['uncovered_roof'] > collision.MAX_UNCOVERED]
    print(f'\n{len(rows)} buildings, {total} generated collision triangles, failing: {failing or "none"}')
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + '\n')
    return 1 if failing else 0


if __name__ == '__main__':
    sys.exit(main())
