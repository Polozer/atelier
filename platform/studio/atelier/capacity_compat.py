"""Durable compatibility barrier for full capacity admission.

Legacy launchers open the existing lane files for writing. Sealing those same inodes
refuses fresh legacy opens, but cannot revoke a preopened descriptor. Full activation
therefore requires an authoritative new OS boot after the seal, never a process scan.
Explicit prior-boot promotion can preserve that proof through a stable-volume migration.
"""
from contextlib import ExitStack
from dataclasses import asdict
import ctypes
import errno
import fcntl
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

from . import capacity_protocol as wire
from .capacity import Resources

DEFAULT_RECORD = Path.home() / '.cache/atelier/capacity/cutover.json'
PROTOCOL = 3


def read(path=None):
    path = Path(path or DEFAULT_RECORD)
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    parent = path.parent.stat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise wire.CapacityError('Capacity cutover directory must be private and owned')
    value = wire.decode(wire.private_file(path, limit=wire.MAX_FRAME))
    wire.fields(value, ('schema', 'state', 'activation_id', 'seal_boot_id', 'policy_sha256',
                        'socket', 'disk_pool', 'locks', 'total', 'reserve', 'protocol'),
                        ('migration_archive_sha256', 'activation_proof'))
    if (type(value['schema']) is not int or value['schema'] not in (1, 2, 3)
            or type(value['protocol']) is not int or value['protocol'] != PROTOCOL
            or value['state'] not in ('preparing', 'sealed', 'active')):
        raise wire.CapacityError('Unsupported capacity cutover record')
    if (value['schema'] == 3) != ('activation_proof' in value) or (value['schema'] == 3 and value['state'] != 'active'):
        raise wire.CapacityError('Prior-boot provenance requires a schema3 active record')
    if 'migration_archive_sha256' in value and (value['schema'] not in (2, 3) or not isinstance(value['migration_archive_sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', value['migration_archive_sha256']) is None):
        raise wire.CapacityError('Invalid capacity migration provenance')
    for key in ('activation_id', 'seal_boot_id', 'policy_sha256', 'socket', 'disk_pool'):
        wire.text(value[key], maximum=4096)
    try:
        if str(uuid.UUID(value['seal_boot_id'])) != value['seal_boot_id']:
            raise ValueError
        if uuid.UUID(value['activation_id']).hex != value['activation_id']:
            raise ValueError
    except ValueError:
        raise wire.CapacityError('Invalid cutover activation or boot identity') from None
    if (re.fullmatch('[0-9a-f]{64}', value['policy_sha256']) is None
            or not Path(value['socket']).is_absolute() or not Path(value['disk_pool']).is_absolute()):
        raise wire.CapacityError('Invalid cutover policy or endpoint')
    wire.fields(value['locks'], ('big', 'small', 'fitting'))
    for item in value['locks'].values():
        wire.fields(item, ('path', 'device', 'inode', 'ctime_ns', 'mode')
                    + (('volume_uuid',) if value['schema'] in (2, 3) else ()))
        if not Path(wire.text(item['path'], maximum=4096)).is_absolute():
            raise wire.CapacityError('Capacity lane path must be absolute')
        for key in ('device', 'inode', 'ctime_ns', 'mode'):
            wire.integer(item[key])
        if value['schema'] in (2, 3):
            _uuid(item['volume_uuid'])
    if wire.resources(value['reserve']).excess(wire.resources(value['total'])):
        raise wire.CapacityError('Cutover reserve exceeds total capacity')
    return value


def _uuid(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value or uuid.UUID(value).int == 0:
            raise ValueError
    except ValueError:
        raise wire.CapacityError('Invalid stable capacity volume UUID') from None
    return value


def _volume_uuid(path):
    """Read the actual filesystem UUID; a device number is not stable across Darwin boots."""
    if sys.platform != 'darwin':
        raise wire.CapacityError('Stable capacity volume UUID observation is unavailable')
    class AttrList(ctypes.Structure):
        _fields_ = [('count', ctypes.c_uint16), ('reserved', ctypes.c_uint16),
                    ('common', ctypes.c_uint32), ('volume', ctypes.c_uint32),
                    ('directory', ctypes.c_uint32), ('file', ctypes.c_uint32),
                    ('fork', ctypes.c_uint32)]
    # Darwin sys/attr.h: ATTR_BIT_MAP_COUNT=5, ATTR_VOL_INFO|ATTR_VOL_UUID.
    attributes = AttrList(5, 0, 0, 0x80040000, 0, 0, 0)
    result = ctypes.create_string_buffer(20)  # uint32 length followed by uuid_t.
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = type(path) is int
    operation = libc.fgetattrlist if descriptor else libc.getattrlist
    operation.argtypes = [ctypes.c_int if descriptor else ctypes.c_char_p, ctypes.POINTER(AttrList), ctypes.c_void_p,
                          ctypes.c_size_t, ctypes.c_ulong]
    operation.restype = ctypes.c_int
    if operation(path if descriptor else os.fsencode(path), ctypes.byref(attributes), result, len(result), 0) != 0:
        raise wire.CapacityError('Stable capacity volume UUID observation failed')
    if int.from_bytes(result.raw[:4], sys.byteorder) != len(result):
        raise wire.CapacityError('Incomplete stable capacity volume UUID observation')
    return _uuid(str(uuid.UUID(bytes=result.raw[4:])))


def _pin(path, info, *, volume=True, fd=None):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1):
        raise wire.CapacityError('Capacity lanes must be owned single-link regular files')
    value = dict(path=str(path), device=info.st_dev, inode=info.st_ino,
                 ctime_ns=info.st_ctime_ns, mode=stat.S_IMODE(info.st_mode))
    if volume:
        value['volume_uuid'] = _volume_uuid(path if fd is None else fd)
    return value


def _same_seal(observed, recorded):
    return {k: v for k, v in observed.items() if k != 'device'} == {
        k: v for k, v in recorded.items() if k != 'device'}


def _check_paths(value):
    from .safety.render_lock import lock_paths
    if {name: str(p) for name, p in lock_paths().items()} != {name: item['path'] for name, item in value['locks'].items()}:
        raise wire.CapacityError('Capacity lane paths differ from the fixed compatibility barrier')
    for item in value['locks'].values():
        for parent in Path(item['path']).parents:
            if parent.is_symlink() and str(parent) not in ('/tmp', '/var', '/etc'):
                raise wire.CapacityError('Capacity lane ancestors cannot be symlinks')


def _write_denied(path):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EPERM):
            return
        raise wire.CapacityError('Cannot establish the legacy write-open barrier') from None
    else:
        os.close(fd)
        raise wire.CapacityError('Legacy write-open is still permitted, including through an ACL')


def verify(path=None, *, policy_sha256=None, active=True, handles=None):
    """@cc [owner:fontanierh,label:safety] durable-capacity-compatibility
    Full capacity MUST require unchanged sealed single-link legacy inodes on their recorded stable
    volume UUIDs, actual same-UID
    write-open denial and a positive OS boot change after sealing. Schema3 MUST additionally
    revalidate both exact archived seals and the explicit prior-boot promotion provenance;
    the stable-volume migration date MUST NOT replace the original descriptor-closure boot.
    Missing observations,
    a process scan or an operator assertion MUST NOT establish closure of preopened FDs.
    No failure MAY unseal the lane files or fall back to legacy admission.
    """
    return _verify_seal(path, policy_sha256=policy_sha256, active=active, handles=handles)


def verify_maintenance(path=None, *, policy_sha256=None, handles=None):
    """@cc [owner:fontanierh,label:safety] sealed-exclusive-maintenance
    Maintenance MUST require a schema2 SEALED record from the current boot and unchanged stable
    lane identities with actual write denial, plus the hash-bound archived schema1 seal from an
    earlier boot. Fresh same-boot prepare MUST NOT qualify. It MUST NOT claim closure of preopened descriptors
    or full activation. Every maintenance job MUST hold all three lane mutexes exclusively.
    """
    if not isinstance(policy_sha256, str) or len(policy_sha256) != 64 or any(
            c not in '0123456789abcdef' for c in policy_sha256):
        raise wire.CapacityError('Maintenance requires the original sealed policy digest')
    value = _verify_seal(path, policy_sha256=policy_sha256, active=False, handles=handles, maintenance=True)
    _migration_evidence(value, wire.boot_id())
    return value


def _migration_evidence(value, closure_boot):
    archive = DEFAULT_RECORD.with_name(f'cutover.schema1.{value["activation_id"]}.json')
    if 'migration_archive_sha256' not in value:
        raise wire.CapacityError('Maintenance requires archived prior-boot volume migration evidence')
    original = read(archive)
    raw = wire.private_file(archive, limit=wire.MAX_FRAME)
    if (original is None or hashlib.sha256(raw).hexdigest() != value['migration_archive_sha256']
            or wire.decode(raw) != original or original['schema'] != 1 or original['state'] != 'sealed'
            or original['seal_boot_id'] == closure_boot
            or any(original[key] != value[key] for key in ('activation_id', 'policy_sha256', 'socket',
                       'disk_pool', 'total', 'reserve', 'protocol'))
            or any(not _same_seal({k: v for k, v in pin.items() if k != 'volume_uuid'}, original['locks'][name])
                   for name, pin in value['locks'].items())):
        raise wire.CapacityError('Maintenance prior-boot migration evidence differs from the sealed policy')
    return original


def _prior_boot_evidence(value):
    proof = wire.fields(value['activation_proof'], ('kind', 'original_seal_sha256', 'migrated_seal_sha256',
                                                   'promotion_boot_id', 'broker_epoch'))
    if proof['kind'] != 'prior-boot-volume-migration':
        raise wire.CapacityError('Unsupported prior-boot promotion proof')
    wire.integer(proof['broker_epoch'], minimum=1)
    archive = DEFAULT_RECORD.with_name(f'cutover.schema2.{value["activation_id"]}.json')
    raw = wire.private_file(archive, limit=wire.MAX_FRAME)
    migrated = read(archive)
    if (migrated is None or migrated['schema'] != 2 or migrated['state'] != 'sealed'
            or hashlib.sha256(raw).hexdigest() != proof['migrated_seal_sha256'] or wire.decode(raw) != migrated
            or migrated['seal_boot_id'] != proof['promotion_boot_id']
            or migrated.get('migration_archive_sha256') != proof['original_seal_sha256']
            or {**migrated, 'schema': 3, 'state': 'active', 'activation_proof': proof} != value):
        raise wire.CapacityError('Prior-boot migration proof differs from the archived seals')
    original = _migration_evidence(migrated, proof['promotion_boot_id'])
    if original['seal_boot_id'] == wire.boot_id():
        raise wire.CapacityError('Prior-boot closure requires a positive OS boot change')
    return original


def _verify_seal(path, *, policy_sha256, active, handles, maintenance=False):
    if Path(path or DEFAULT_RECORD) != DEFAULT_RECORD or os.environ.get('ATELIER_RENDER_LOCK'):
        raise wire.CapacityError('Full capacity requires the fixed machine compatibility paths')
    value = read(path)
    if value is None or value['state'] != ('active' if active else 'sealed'):
        raise wire.CapacityError('Capacity cutover is not active' if active else 'Capacity cutover is not sealed')
    if value['schema'] not in (2, 3):
        raise wire.CapacityError('Legacy cutover seal requires explicit volume migration and another OS boot')
    if policy_sha256 is not None and value['policy_sha256'] != policy_sha256:
        raise wire.CapacityError('Capacity cutover policy differs from the reviewed broker policy')
    same_boot = wire.boot_id() == value['seal_boot_id']
    if value['schema'] == 3:
        _prior_boot_evidence(value)
    if maintenance and not same_boot:
        raise wire.CapacityError('Maintenance requires a verified current-boot seal')
    if not maintenance and same_boot and value['schema'] != 3:
        raise wire.CapacityError('Full capacity requires a verified new OS boot after sealing legacy lanes')
    _check_paths(value)
    for name, item in value['locks'].items():
        path = Path(item['path'])
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            pin = _pin(path, os.fstat(fd), fd=fd)
            if (pin != item if maintenance else not _same_seal(pin, item)) or pin['mode'] != 0o400:
                raise wire.CapacityError('Capacity lane inode, seal or change identity was modified')
            if handles is not None and _pin(path, os.fstat(handles[name].fileno()), fd=handles[name].fileno()) != pin:
                raise wire.CapacityError('Shared capacity lock belongs to a replaced lane inode')
            _write_denied(path)
            if _pin(path, os.lstat(path)) != pin:
                raise wire.CapacityError('Capacity lane changed during verification')
        finally:
            os.close(fd)
    return value


def refuse_unmanaged(purpose):
    if read() is not None:
        raise wire.CapacityError(f'{purpose} has no full-capacity lifecycle; use a migrated guarded entry point')


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.parent.stat()
    if path.parent.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise wire.CapacityError('Capacity cutover directory must be private and owned')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(wire.encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _policy(config):
    from .capacity_broker import load_config
    settings = load_config(config)
    if settings.get('mode') != 'capacity' or Path(settings['cutover']) != DEFAULT_RECORD:
        raise wire.CapacityError('Full capacity needs the machine default cutover record')
    return settings


def prepare(config):
    """Seal only under every existing exclusive mutex; never remove, replace or auto-unseal them."""
    from .safety.render_lock import lock_paths
    settings = _policy(config)
    if os.environ.get('ATELIER_RENDER_LOCK'):
        raise wire.CapacityError('A cutover cannot seal overridden legacy lane paths')
    if read() is not None:
        raise wire.CapacityError('A cutover record already exists; do not overwrite its closure evidence')
    paths = lock_paths()
    big = paths['big']
    with ExitStack() as stack:
        admission = stack.enter_context(big.with_name(f'{big.stem}.admission{big.suffix}').open('a+'))
        fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handles = {}
        for name, path in paths.items():
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
            handle = stack.enter_context(os.fdopen(fd, 'r+b'))
            _pin(path, os.fstat(fd), fd=fd)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles[name] = handle
        value = dict(schema=2, state='preparing', activation_id=uuid.uuid4().hex,
                     seal_boot_id=wire.boot_id(), policy_sha256=settings['policy_sha256'],
                     protocol=PROTOCOL, socket=str(settings['state_directory'] / 'broker.sock'),
                     disk_pool=str(settings['disk_pool']),
                     total=asdict(settings['total']), reserve=asdict(settings['reserve']),
                     locks={name: _pin(paths[name], os.fstat(h.fileno()), fd=h.fileno()) for name, h in handles.items()})
        _save(DEFAULT_RECORD, value)  # A partial seal must already refuse upgraded launchers.
        for handle in handles.values():
            os.fchmod(handle.fileno(), 0o400)
            os.fsync(handle.fileno())
        value['locks'] = {name: _pin(paths[name], os.fstat(h.fileno()), fd=h.fileno()) for name, h in handles.items()}
        for path in paths.values():
            _write_denied(path)
        value['state'] = 'sealed'
        _save(DEFAULT_RECORD, value)
    return value


def activate(config):
    settings = _policy(config)
    value = verify(policy_sha256=settings['policy_sha256'], active=False)
    with ExitStack() as stack:
        handles = {}
        for name, item in value['locks'].items():
            fd = os.open(item['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            handle = stack.enter_context(os.fdopen(fd, 'rb'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles[name] = handle
        value = verify(policy_sha256=settings['policy_sha256'], active=False, handles=handles)
        value['state'] = 'active'
        _save(DEFAULT_RECORD, value)
    return value


def _archive_seal(archive, original):
    """@cc [owner:fontanierh,label:safety] immutable-seal-archive-publication
    Seal archives MUST never overwrite existing bytes. Exact private single-link bytes, their
    final FD/path identity and parent directory MUST be verified and synced before returning.
    """
    if len(original) > wire.MAX_FRAME:
        raise wire.CapacityError('Capacity seal archive exceeds its limit')
    temporary = archive.with_name(archive.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            pending = memoryview(original)
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise wire.CapacityError('Capacity seal archive write did not advance')
                pending = pending[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temporary, archive, follow_symlinks=False)  # Publish atomically without replacement.
        except FileExistsError:
            pass  # A retry must validate the exact existing bytes and descriptor below.
    finally:
        temporary.unlink(missing_ok=True)
    fd = os.open(archive, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077
                or info.st_size != len(original) or os.read(fd, wire.MAX_FRAME + 1) != original):
            raise wire.CapacityError('Existing capacity seal archive differs from the original')
        os.fsync(fd)
        after, current = os.fstat(fd), os.lstat(archive)
        def binding(sample):
            return (sample.st_dev, sample.st_ino, sample.st_ctime_ns, sample.st_mtime_ns,
                    sample.st_size, sample.st_uid, sample.st_mode, sample.st_nlink)
        if binding(info) != binding(after) or binding(after) != binding(current):
            raise wire.CapacityError('Existing capacity seal archive changed during validation')
    finally:
        os.close(fd)
    directory = os.open(archive.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def promote_prior_boot(config):
    """@cc [owner:fontanierh,label:safety] explicit-prior-boot-capacity-promotion
    Only a migrated current-boot schema2 SEALED record MAY promote without another reboot.
    Both archived seals MUST prove the actual earlier OS boot and unchanged sealed identities.
    All three read-only lane mutexes and the admission mutex MUST be held exclusively while
    checking fresh healthy uncharged maintenance state and publishing durable schema3 ACTIVE.
    No seal date, inode, reserve, database or uncertain grant MAY be rewritten or discarded.
    """
    from .capacity_client import status
    settings = _policy(config)
    existing = read()
    resume = existing is not None and existing['schema'] == 3
    value = (verify(policy_sha256=settings['policy_sha256']) if resume
             else verify_maintenance(policy_sha256=settings['policy_sha256']))
    from .safety.render_lock import lock_paths
    big = lock_paths()['big']
    with ExitStack() as stack:
        admission = stack.enter_context(big.with_name(f'{big.stem}.admission{big.suffix}').open('a+'))
        fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handles = {}
        for name, item in value['locks'].items():
            fd = os.open(item['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            handle = stack.enter_context(os.fdopen(fd, 'rb'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles[name] = handle
        if resume:
            value = verify(policy_sha256=settings['policy_sha256'], handles=handles)
            # Roll forward a valid ACTIVE publication after interrupted sync/service restart.
            # Never rewrite it as SEALED or clear a retained grant.
            for schema in (1, 2):
                archive = DEFAULT_RECORD.with_name(f'cutover.schema{schema}.{value["activation_id"]}.json')
                _archive_seal(archive, wire.private_file(archive, limit=wire.MAX_FRAME))
            _archive_seal(DEFAULT_RECORD, wire.private_file(DEFAULT_RECORD, limit=wire.MAX_FRAME))
            return verify(policy_sha256=settings['policy_sha256'], handles=handles)
        value = verify_maintenance(policy_sha256=settings['policy_sha256'], handles=handles)
        original = wire.private_file(DEFAULT_RECORD, limit=wire.MAX_FRAME)
        if wire.decode(original) != value:
            raise wire.CapacityError('Capacity seal changed before promotion')
        observed = status(value['socket'])
        timestamp = observed.get('observed_monotonic')
        if (type(timestamp) not in (int, float) or not math.isfinite(timestamp)
                or not 0 <= time.monotonic() - timestamp <= 2
                or observed.get('mode') != 'sealed-maintenance' or observed.get('boot_id') != wire.boot_id()
                or observed.get('activation_id') != value['activation_id']
                or observed.get('compatibility_healthy') is not True or observed.get('recovering') is not False
                or type(observed.get('charged_count')) is not int or observed['charged_count'] != 0
                or wire.resources(observed.get('charged_resources')) != Resources()):
            raise wire.CapacityError('Prior-boot promotion requires fresh healthy drained maintenance state')
        epoch = wire.integer(observed.get('epoch'), minimum=1)
        archive = DEFAULT_RECORD.with_name(f'cutover.schema2.{value["activation_id"]}.json')
        _archive_seal(archive, original)
        # Revalidate bound bytes and handles after archive/status I/O, before ACTIVE publication.
        if verify_maintenance(policy_sha256=settings['policy_sha256'], handles=handles) != value:
            raise wire.CapacityError('Capacity seal changed during promotion')
        value = {**value, 'schema': 3, 'state': 'active', 'activation_proof': dict(
            kind='prior-boot-volume-migration', original_seal_sha256=value['migration_archive_sha256'],
            migrated_seal_sha256=hashlib.sha256(original).hexdigest(),
            promotion_boot_id=wire.boot_id(), broker_epoch=epoch)}
        _prior_boot_evidence(value)
        _save(DEFAULT_RECORD, value)
    return value


def migrate_volume_seal(config):
    """@cc [owner:fontanierh,label:safety] forward-volume-seal-migration
    Only an explicitly requested schema-1 SEALED record MAY migrate, under all three exclusive
    lane handles after a positive boot change. All old pins except transient device numbers MUST
    match. The old record MUST be archived without replacement. Ordinary activation of the new
    stable-volume seal MUST require a further OS boot; only explicit schema3 promotion MAY
    preserve the earlier closure by revalidating both archived seals. Migration itself MUST NOT
    unseal, replace lanes or activate capacity.
    """
    from .safety.render_lock import lock_paths
    settings = _policy(config)
    if os.environ.get('ATELIER_RENDER_LOCK'):
        raise wire.CapacityError('A cutover cannot migrate overridden legacy lane paths')
    paths = lock_paths()
    big = paths['big']
    with ExitStack() as stack:
        admission = stack.enter_context(big.with_name(f'{big.stem}.admission{big.suffix}').open('a+'))
        fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = read()
        if value is None or value['schema'] != 1 or value['state'] != 'sealed':
            raise wire.CapacityError('Volume migration requires exactly a schema-1 sealed cutover')
        if value['policy_sha256'] != settings['policy_sha256']:
            raise wire.CapacityError('Capacity cutover policy differs from the reviewed broker policy')
        boot = wire.boot_id()
        if boot == value['seal_boot_id']:
            raise wire.CapacityError('Volume migration requires a verified new OS boot after the old seal')
        _check_paths(value)
        original = wire.private_file(DEFAULT_RECORD, limit=wire.MAX_FRAME)
        if wire.decode(original) != value:
            raise wire.CapacityError('Capacity cutover changed during migration')
        pins = {}
        for name, path in paths.items():
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            handle = stack.enter_context(os.fdopen(fd, 'rb'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            old_pin = _pin(path, os.fstat(fd), volume=False)
            if not _same_seal(old_pin, value['locks'][name]) or old_pin['mode'] != 0o400:
                raise wire.CapacityError('Legacy capacity lane inode, seal or change identity was modified')
            pins[name] = _pin(path, os.fstat(fd), fd=fd)
            if {k: v for k, v in pins[name].items() if k != 'volume_uuid'} != old_pin:
                raise wire.CapacityError('Capacity lane changed while observing its volume')
            _write_denied(path)
            if _pin(path, os.lstat(path)) != pins[name]:
                raise wire.CapacityError('Capacity lane changed during migration')
        # Recheck every held inode after acquiring the complete exclusion set.
        for name, path in paths.items():
            if _pin(path, os.lstat(path)) != pins[name]:
                raise wire.CapacityError('Capacity lane changed during migration')
        if wire.private_file(DEFAULT_RECORD, limit=wire.MAX_FRAME) != original:
            raise wire.CapacityError('Capacity cutover changed during migration')
        archive = DEFAULT_RECORD.with_name(f'cutover.schema1.{value["activation_id"]}.json')
        _archive_seal(archive, original)
        value.update(schema=2, seal_boot_id=boot, locks=pins, migration_archive_sha256=hashlib.sha256(original).hexdigest())
        _save(DEFAULT_RECORD, value)
    return value
