#!/usr/bin/env python3
"""Pull the Sonniss GDC masters the Belmonte train's sounds are cut from (make.py SPEC) into
~/.cache/atelier/sonniss/train, md5-checked, with the combat library's downloader (combat/fetch.py).

PICKS lists (local name, archive item, path inside the item, md5, bytes), as in combat/fetch.py; it is filled in once
the recordings are chosen. Local signal processing only (audio/SONNISS-LICENSE.txt).

Usage:  python3 fetch.py [--force]
"""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location('combat_fetch', Path(__file__).resolve().parent.parent / 'combat' / 'fetch.py')
combat = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(combat)
from atelier.paths import cache_dir  # noqa: E402  (combat/fetch.py put the studio on the path)

PICKS = []


def main():
    combat.ROOT, combat.PICKS = cache_dir('sonniss', 'train'), PICKS
    return combat.main()


if __name__ == '__main__':
    sys.exit(main())
