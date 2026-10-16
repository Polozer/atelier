"""Preserve an owned package with an invalid header before a fresh FBX import."""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid


def _pin(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or path.resolve() != path):
        raise ValueError('Expected an owned regular single-link foliage package: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = os.fdopen(fd, 'rb')
    if _pin(os.fstat(stream.fileno())) != _pin(info):
        stream.close()
        raise ValueError('Foliage package changed while opening: ' + str(path))
    return stream, info


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _receipt(folder, value):
    temporary = folder / 'receipt.next'
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(folder / 'receipt.json')
    _sync(folder)


def require_valid_or_missing(content, name):
    """Refuse damage that appeared after the admitted pre-editor preparation."""
    main = Path(content) / 'Japan/Assets' / (name + '.uasset')
    try:
        stream, _ = _open(main)
    except FileNotFoundError:
        return
    with stream:
        if stream.read(4) not in (b'\xc1\x83\x2a\x9e', b'\x9e\x2a\x83\xc1'):
            raise RuntimeError('Invalid foliage package appeared after pre-editor preparation: ' + name)


def quarantine_invalid_package(content, output, name, *, require_unloaded):
    """@cc [owner:fontanierh,label:correctness] preserve-invalid-owned-foliage-package
    The caller MUST validate the exact foliage owner before calling this function.
    Only a main package with an invalid UE package tag may be removed, together with its
    exact optional sidecars. Every removed byte MUST first have a durable verified copy.
    Links, foreign files and concurrent changes MUST refuse. Valid packages MUST stay intact.
    This operation MUST run inside the native owner's existing guard before editor startup;
    it neither certifies the replacement nor restores old packages after an import failure.
    require_unloaded MUST positively reject any already loaded owner/LOD package before removal.
    """
    if not name.isidentifier():
        raise ValueError('Expected one foliage owner name')
    content = Path(content).absolute()
    main = content / 'Japan/Assets' / (name + '.uasset')
    try:
        stream, info = _open(main)
    except FileNotFoundError:
        return None
    with stream:
        # UE accepts the native and byte-swapped PACKAGE_FILE_TAG. A valid tag alone
        # does not prove the rest of the package; deeper corruption still fails closed.
        if stream.read(4) in (b'\xc1\x83\x2a\x9e', b'\x9e\x2a\x83\xc1'):
            return None
    invalid_pin = _pin(info)
    require_unloaded()
    entries = []
    for path in (main.with_suffix('.uexp'), main.with_suffix('.ubulk'), main):
        try:
            stream, info = _open(path)
        except FileNotFoundError:
            if path == main:
                raise ValueError('Invalid foliage package disappeared before preservation')
            continue
        stream.close()
        if path == main and _pin(info) != invalid_pin:
            raise ValueError('Invalid foliage package changed before preservation')
        entries.append((path, info))
    root = Path(output).resolve() / 'logs/foliage-repair' / name
    if root.resolve() != root:
        raise ValueError('Foliage quarantine must not contain links')
    missing = []
    parent = root
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.resolve() != root or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError('Foliage quarantine must be private and owned')
    for directory in reversed(missing):
        _sync(directory.parent)
        _sync(directory)
    folder = root / uuid.uuid4().hex
    folder.mkdir(mode=0o700)
    _sync(root)
    receipt = {'schema': 1, 'owner': name, 'state': 'preserving', 'files': {}}
    _receipt(folder, receipt)
    for path, expected in entries:
        source, observed = _open(path)
        with source:
            if _pin(observed) != _pin(expected):
                raise ValueError('Foliage package changed before preservation')
            with (folder / path.name).open('xb') as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            if _pin(os.fstat(source.fileno())) != _pin(expected):
                raise ValueError('Foliage package changed during preservation')
            source.seek(0)
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        with (folder / path.name).open('rb') as saved:
            if hashlib.file_digest(saved, 'sha256').hexdigest() != digest:
                raise ValueError('Foliage package preservation did not verify')
        receipt['files'][path.name] = {'sha256': digest, 'size': expected.st_size}
    receipt['state'] = 'preserved'
    _receipt(folder, receipt)
    require_unloaded()
    # Recheck every leaf before the first removal. Remove the invalid main last:
    # interruption leaves either that same invalid main or a complete fresh-import hole.
    for path, expected in entries:
        source, observed = _open(path)
        source.close()
        if _pin(observed) != _pin(expected):
            raise ValueError('Foliage package changed before quarantine')
    for path, expected in entries:
        source, observed = _open(path)
        source.close()
        if _pin(observed) != _pin(expected):
            raise ValueError('Foliage package changed during quarantine')
        path.unlink()
        _sync(path.parent)
    receipt['state'] = 'quarantined'
    _receipt(folder, receipt)
    return folder
