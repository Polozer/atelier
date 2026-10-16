"""Preserve invalid owned bytes before the editor's startup asset-registry scan."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'world'))
import yori
from asset_catalog import FOLIAGE
from foliage_package_repair import quarantine_invalid_package


def require_no_editor():
    if 'unreal' in sys.modules:
        raise RuntimeError('Foliage preservation must precede the editor process image')


def main():
    name = os.environ['ATELIER_FOLIAGE']
    if name not in FOLIAGE:
        raise ValueError('Unknown foliage owner: ' + name)
    require_no_editor()
    preserved = quarantine_invalid_package(yori.GAME / 'unreal/Content', yori.OUT, name,
                                          require_unloaded=require_no_editor)
    if preserved is not None:
        print('Preserved invalid foliage package before fresh import: ' + str(preserved), flush=True)


if __name__ == '__main__':
    main()
