"""Durable create intent and local ownership for one repository/release tag."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

CLAIMS = Path.home() / '.cache/atelier/release-publication'


class ClaimError(Exception):
    pass


def require(value, message):
    if not value:
        raise ClaimError(message)


def private_file(descriptor):
    info = os.fstat(descriptor)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and not info.st_mode & 0o077, 'release claim must be a private regular file')
    return info


class Claim:
    def __init__(self, folder, key, repository, metadata):
        self.path = folder / (key + '.json')
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.identity = dict(schema=1, repository=repository, tag=metadata['tag_name'], metadata_sha256=digest)
        self.value = {**self.identity, 'state': 'not-created', 'release_id': None}
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return
        with os.fdopen(descriptor, 'rb') as stream:
            private_file(stream.fileno())
            raw = stream.read(8193)
        require(len(raw) <= 8192, 'release claim exceeds its size bound')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ClaimError('release claim is unreadable; it was preserved') from None
        require(type(value) is dict and set(value) == set(self.value) and type(value['schema']) is int,
                'release claim has an invalid schema')
        require(all(value[k] == v for k, v in self.identity.items()),
                'saved publication request differs; use the original request or a new tag')
        require(value['state'] in ('not-created', 'creating', 'selected'), 'release claim has an invalid state')
        identifier = value['release_id']
        require((type(identifier) is int and identifier > 0) if value['state'] == 'selected' else identifier is None,
                'release claim has an invalid release identity')
        self.value = value

    def save(self, state, release_id=None):
        """Persist creating before POST; a crash never turns uncertainty into a new create."""
        value = {**self.identity, 'state': state, 'release_id': release_id}
        temporary = self.path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream, sort_keys=True); stream.write('\n')
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        self.value = value


@contextmanager
def acquire(repository, metadata):
    """@cc [owner:fontanierh,label:correctness] release-create-intent
    Publishers for the same user, machine and repository/tag MUST share one persistent mutex inode.
    A create intent MUST survive process exit and MUST NOT authorize another POST while uncertain.
    Unrelated destinations MUST NOT share a mutex or reserve native build capacity.
    """
    repository = repository.lower()
    folder = CLAIMS  # Artifact-cache overrides must not split destination ownership.
    folder.mkdir(parents=True, exist_ok=True)
    info = folder.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022,
            'release claim folder must be owned and not writable by others')
    key = hashlib.sha256((repository + '\n' + metadata['tag_name']).encode()).hexdigest()
    lock = folder / (key + '.lock')
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        held = private_file(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ClaimError('another publisher owns this repository/tag; retry after it exits') from None
        current = lock.lstat()
        require((held.st_dev, held.st_ino) == (current.st_dev, current.st_ino), 'release mutex identity changed')
        yield Claim(folder, key, repository, metadata)
    finally:
        os.close(descriptor)  # Never unlink the persistent mutex inode.
