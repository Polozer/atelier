"""A new character's grips started from another's: the poser opens each grip already posed, for a person to adjust.

    uv run python games/yorimichi/assets/characters/grips/seed.py --from modori --to nox

Reads the committed poses of --from (grips/<from>/poses.json) and writes build/yorimichi/grips/<to>/poses.json, the
poser's editing copy for --to, which must not have one yet. Each grip of --from that --to's moments.json also has keeps:

- `params`: every finger joint's bend, spread and twist from its rest pose, in degrees about the joint's own axes, which
  carry from one hand on the humanoid contract to another;
- `offset`: the hand's move from where the game held it at the grip's moment, which --to's own moments then place;
- `prop_placed`, so the poser does not move a glider grip again.

A seeded grip is a `draft` without `derived` (what the game needs, which the poser computes on its next save), so
game.py leaves it out until a person has opened it in the poser, checked it on --to's hand and saved.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'world')); import yori  # noqa: E402

KEPT = ('params', 'offset', 'prop_placed')


def seed(source, moments, stamp, when):
    """The poser's saved state for a character whose grips are `moments`, from another's `source` poses: `stamp` as
    serve.py stamps a save, `when` as the poser stamps its log (ISO 8601)."""
    grips = {}
    for gid in sorted({g['id'] for g in moments['grips']} & set(source['grips'])):
        st = source['grips'][gid]
        if not st.get('params'):
            continue
        grips[gid] = {'status': 'draft', 'notes': '', 'edits': 0, **{k: st[k] for k in KEPT if k in st},
                      'log': [{'at': when, 'action': f"seeded from {source['character']}"}], 'derived': None}
    return {'tool': source['tool'], 'version': source['version'], 'character': moments['character'],
            'frame': source['frame'], 'units': source['units'], 'grips': grips,
            'saved': {'at': stamp, 'by': 'operator', 'seeded_from': source['character']}}


def main(args):
    source = json.loads((HERE / args.source / 'poses.json').read_text())
    workspace = yori.OUT / 'grips' / args.to
    moments = json.loads((workspace / 'moments.json').read_text())
    target = workspace / 'poses.json'
    assert not target.exists(), f'{target} exists: seeding would replace its poses'
    stamp = time.strftime('%Y%m%d-%H%M%S') + f'-{int(time.time() * 1000) % 1000:03d}'
    when = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    poses = seed(source, {**moments, 'character': args.to}, stamp, when)
    target.write_text(json.dumps(poses, indent=1) + '\n')
    print('GRIPS SEEDED', args.to, 'from', args.source, sorted(poses['grips']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--from', dest='source', required=True, help='a character with committed grips (grips/<id>/)')
    parser.add_argument('--to', required=True, help="the character to seed: its moments.json is in the poser's workspace")
    main(parser.parse_args())
