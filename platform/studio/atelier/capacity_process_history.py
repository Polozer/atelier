"""Durable audit archives for released grants; never an ownership or release input."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from . import capacity_protocol as wire

TARGET_STATE = 2 * 1024 * 1024
MAX_STATE = 4 * 1024 * 1024
MAX_ARCHIVE = 2 * 1024 * 1024
ARRAYS = ('roster', 'exited', 'verified_roster')


def _json(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def _existing(path, expected):
    """Validate and sync the exact opened immutable file, never a later path lookup."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_mode & 0o077 or before.st_nlink != 1 or before.st_size != len(expected)):
            raise wire.CapacityError('Invalid capacity process history archive')
        raw = os.read(fd, MAX_ARCHIVE + 1)
        os.fsync(fd)
        after, current = os.fstat(fd), path.lstat()
        def binding(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                    info.st_uid, info.st_mode, info.st_nlink)
        if raw != expected or binding(before) != binding(after) or binding(after) != binding(current):
            raise wire.CapacityError('Capacity process history archive differs')
    finally:
        os.close(fd)


def _publish(directory, raw):
    if len(raw) > MAX_ARCHIVE:
        raise wire.CapacityError('Capacity process history archive exceeds its limit')
    folder = Path(directory) / 'process-history'
    for ancestor in (folder, *folder.parents):
        if ancestor.is_symlink() and str(ancestor) not in ('/tmp', '/var', '/etc'):
            raise wire.CapacityError('Capacity process history ancestors cannot be links')
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise wire.CapacityError('Capacity process history directory must be private and owned')
    digest = hashlib.sha256(raw).hexdigest()
    path = folder / (digest + '.json')
    temporary = folder / ('publish-' + secrets.token_hex(16))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            remaining = memoryview(raw)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise wire.CapacityError('Capacity process history write did not advance')
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temporary, path, follow_symlinks=False)  # Atomic publication, never overwrite.
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    _existing(path, raw)  # Also validates a matching retry after a pre-commit crash.
    for parent in (folder, Path(directory)):
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return digest


def encode_state(directory, state):
    """@cc [owner:fontanierh,label:safety] released-process-history-compaction
    Only RELEASED records MAY move exact process arrays to private SHA-bound audit files.
    Archive bytes and their parent directory MUST be durable before SQLite may commit a
    summary. Held and uncertain proof MUST remain intact. Archives MUST NOT grant ownership,
    release capacity or be deleted automatically when summaries are pruned or reoffered.
    """
    data = _json(state)
    size = len(data)
    if size > TARGET_STATE:
        for record in sorted(state['records'].values(), key=lambda item: item['sequence']):
            if size <= TARGET_STATE:
                break
            if record['state'] != 'released' or not record.get('roster'):
                continue
            counts = {key: len(record.get(key, [])) for key in ARRAYS}
            archive = dict(schema=1, namespace=wire.NAMESPACE, request_id=record['request']['id'],
                           nonce=record['nonce'], counts=counts, release_witness=record.get('release_witness'),
                           **{key: record.get(key, []) for key in ARRAYS})
            digest = _publish(directory, _json(archive).encode())
            before = len(_json(record))
            for key in ARRAYS:
                record.pop(key, None)
            record['process_history'] = dict(sha256=digest, counts=counts)
            size += len(_json(record)) - before
        data = _json(state)
    if len(data) > MAX_STATE:
        raise wire.CapacityError('Capacity state exceeds its limit')
    return data


def count(record, name):
    return record.get('process_history', {}).get('counts', {}).get(name, len(record.get(name, [])))
