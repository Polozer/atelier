"""One explicit switch selects the design-driven park throughout the build."""
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path

SWITCH = 'ATELIER_CRATERPARK_V4_DESIGN'


def design_path():
    value = os.environ.get(SWITCH, '').strip()
    return Path(value).expanduser().resolve() if value else None


def selected():
    return design_path() is not None


def load_document(path=None):
    """Read the selected JSON object, without executing referenced Python helpers."""
    path = Path(path) if path is not None else design_path()
    if path is None:
        raise ValueError(f'{SWITCH} must select a design')
    document = json.loads(path.read_text())
    if not isinstance(document, dict):
        raise ValueError('v4 design must be a JSON object')
    return document


def input_paths(path=None):
    """@cc [owner:fontanierh] v4-design-inputs
    All data files the design loader may read MUST be recipe fingerprints.
    Selected design and referenced data MUST exist; missing data never selects the old park.
    """
    path = Path(path).resolve() if path is not None else design_path()
    if path is None:
        return []
    document = load_document(path)
    paths = [path]
    refs = [document.get('elements_file'), document.get('ground', {}).get('heightmap')]
    site = document.get('site', {})
    site_ref = site.get('file')
    for preferred in site.get('prefer', []):
        candidate = Path(preferred).expanduser()
        candidate = candidate if candidate.is_absolute() else path.parent / candidate
        if candidate.is_file():
            site_ref = preferred
            break
    refs += [site_ref, site.get('block_file')]
    for ref in refs:
        if not ref:
            continue
        candidate = Path(ref).expanduser()
        candidate = candidate if candidate.is_absolute() else path.parent / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise ValueError(f'v4 design input missing: {candidate.name}')
        paths.append(candidate)
    return list(dict.fromkeys(paths))


@lru_cache(maxsize=256)
def _file_sha(path, mtime_ns, size, ctime_ns):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    after = Path(path).stat()
    if (after.st_mtime_ns, after.st_size, after.st_ctime_ns) != (mtime_ns, size, ctime_ns):
        raise ValueError('v4 input changed while hashing; retry with stable inputs')
    return digest


def file_sha(path):
    path = Path(path).resolve()
    stat = path.stat()
    return _file_sha(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)


def provenance(path=None):
    """Portable names plus byte hashes; no machine paths in generated reports."""
    paths = input_paths(path)
    if not paths:
        raise ValueError('no v4 design selected')
    entries = [{'name': os.path.relpath(p, paths[0].parent),
                'sha256': file_sha(p)} for p in paths]
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'schema': 4, 'design_sha256': entries[0]['sha256'], 'source_sha256': digest, 'inputs': entries,
            'depth': load_document(paths[0]).get('ground', {}).get('dig', {}).get('DEPTH')}
