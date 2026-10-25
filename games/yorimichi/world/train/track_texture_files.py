"""The Belmonte track's ballast-bed detail textures as files, for the railway assembly and the Unreal import.

Writes <output>/T_TK_<name>.png (track_textures.py, 8-bit sRGB, top row first) and <output>/textures.json:
{material: {file, tile_m, sha256}}, `file` relative to build/yorimichi/belmonte-track/. The railway assembly
(train_track_atomic_products.py) copies that mapping into track.json's `textures`; import_belmonte_track.py binds
MI_TK_Ballast and MI_TK_Cess to them.
"""
import argparse
import hashlib
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atelier.atomic_files import atomic_json  # noqa: E402
from train import track_textures as TT  # noqa: E402


def write(folder):
    """Every texture of TT.TEXTURED and the mapping, replacing any stale file in the folder; returns the mapping."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    wanted = {name + '.png' for name, _ in TT.TEXTURED.values()} | {'textures.json'}
    for stale in folder.iterdir():
        if stale.name not in wanted:
            stale.unlink()
    mapping = {}
    for material, (name, tile) in TT.TEXTURED.items():
        rgb = np.clip(np.round(TT.ALL[name]()[::-1, :, :3] * 255.), 0, 255).astype(np.uint8)  # bottom row first
        path = folder / (name + '.png')
        Image.fromarray(rgb, 'RGB').save(path)
        mapping[material] = dict(file=f'{folder.name}/{path.name}', tile_m=float(tile),
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    atomic_json(folder / 'textures.json', mapping)
    return mapping


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    mapping = write(args.output)
    print('BELMONTE TRACK TEXTURES COMPLETE', sorted(mapping), flush=True)


if __name__ == '__main__':
    main()
