"""Stage a current native registry through its own normal build-product edge."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile


def stage(out, destination):
    """@cc [owner:fontanierh,label:correctness] soundbank-registry-staging
    The normal step MUST read the certified native soundbank product and publish
    its exact registry bytes. Invalid/candidate metadata or changing source bytes
    MUST fail before replacement. World staging and packaging MUST depend on this
    staged product. File presence or standalone execution is not native acceptance.
    """
    source = Path(out) / 'soundbank_import/registry.json'
    destination = Path(destination)
    if source.is_symlink() or not 0 < source.stat().st_size <= 1024 * 1024:
        raise ValueError('Invalid native soundbank registry extent')
    payload = source.read_bytes()
    if len(payload) > 1024 * 1024:
        raise ValueError('Native soundbank registry grew while reading')
    registry = json.loads(payload)
    if not isinstance(registry, dict) or not isinstance(registry.get('native'), dict):
        raise ValueError('Missing native registry metadata')
    native = registry.get('native', {})
    if (type(registry.get('version')) is not int or registry.get('version') != 1
            or registry.get('default') != 'original'
            or not isinstance(registry.get('banks'), list) or not registry['banks']
            or not isinstance(native.get('packages'), dict) or not native['packages']
            or not re.fullmatch('[0-9a-f]{64}', native.get('plan_sha256', ''))):
        raise ValueError('A verified native registry is required, not an import candidate')
    if source.resolve().is_relative_to(destination.resolve()):
        raise ValueError('Registry staging must not overwrite native source products')
    destination.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
        if source.is_symlink() or source.read_bytes() != payload:
            raise ValueError('Native registry changed during staging')
        os.replace(name, destination / 'registry.json')
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    stage(args.out, args.destination)
