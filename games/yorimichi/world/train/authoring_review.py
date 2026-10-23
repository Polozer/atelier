"""Explicit legacy coach scenes for diagnostics, isolated from the bounded production library."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yori  # noqa: E402
from train import build as builder  # noqa: E402


def main(argv=None):
    """@cc [owner:fontanierh,label:correctness] isolated-coach-authoring-diagnostics
    Legacy combined exports and blend scenes MUST remain in an explicitly selected
    diagnostic root. They MUST NOT overwrite or satisfy the production train library.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output != (yori.OUT / 'belmonte-train-authoring').resolve():
        raise ValueError('Legacy coach diagnostics require the isolated authoring root')
    builder.OUT = output
    builder.TEX = output / 'textures'
    builder.main()


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
