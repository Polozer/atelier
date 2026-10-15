"""Durable compatibility barrier for full capacity admission.

Legacy launchers open the existing lane files for writing. Sealing those same inodes
refuses fresh legacy opens, but cannot revoke a preopened descriptor. Full activation
therefore requires an authoritative new OS boot after the seal, never a process scan.
"""
from contextlib import ExitStack
from dataclasses import asdict
import ctypes
import errno
import fcntl
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from . import capacity_protocol as wire

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
                        'socket', 'disk_pool', 'locks', 'total', 'reserve', 'protocol'))
    if (type(value['schema']) is not int or value['schema'] not in (1, 2)
            or type(value['protocol']) is not int or value['protocol'] != PROTOCOL
            or value['state'] not in ('preparing', 'sealed', 'active')):
        raise wire.CapacityError('Unsupported capacity cutover record')
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
                    + (('volume_uuid',) if value['schema'] == 2 else ()))
        if not Path(wire.text(item['path'], maximum=4096)).is_absolute():
            raise wire.CapacityError('Capacity lane path must be absolute')
        for key in ('device', 'inode', 'ctime_ns', 'mode'):
            wire.integer(item[key])
        if value['schema'] == 2:
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
    write-open denial and a positive OS boot change after sealing. Missing observations,
    a process scan or an operator assertion MUST NOT establish closure of preopened FDs.
    No failure MAY unseal the lane files or fall back to legacy admission.
    """
    return _verify_seal(path, policy_sha256=policy_sha256, active=active, handles=handles)


def verify_maintenance(path=None, *, policy_sha256=None, handles=None):
    """@cc [owner:fontanierh,label:safety] sealed-exclusive-maintenance
    Maintenance MUST require a schema2 SEALED record from the current boot and unchanged stable
    lane identities with actual write denial. It MUST NOT claim closure of preopened descriptors
    or full activation. Every maintenance job MUST hold all three lane mutexes exclusively.
    """
    if not isinstance(policy_sha256, str) or len(policy_sha256) != 64 or any(
            c not in '0123456789abcdef' for c in policy_sha256):
        raise wire.CapacityError('Maintenance requires the original sealed policy digest')
    return _verify_seal(path, policy_sha256=policy_sha256, active=False, handles=handles, maintenance=True)


def _verify_seal(path, *, policy_sha256, active, handles, maintenance=False):
    if Path(path or DEFAULT_RECORD) != DEFAULT_RECORD or os.environ.get('ATELIER_RENDER_LOCK'):
        raise wire.CapacityError('Full capacity requires the fixed machine compatibility paths')
    value = read(path)
    if value is None or value['state'] != ('active' if active else 'sealed'):
        raise wire.CapacityError('Capacity cutover is not active' if active else 'Capacity cutover is not sealed')
    if value['schema'] != 2:
        raise wire.CapacityError('Legacy cutover seal requires explicit volume migration and another OS boot')
    if policy_sha256 is not None and value['policy_sha256'] != policy_sha256:
        raise wire.CapacityError('Capacity cutover policy differs from the reviewed broker policy')
    same_boot = wire.boot_id() == value['seal_boot_id']
    if maintenance and not same_boot:
        raise wire.CapacityError('Maintenance requires a verified current-boot seal')
    if not maintenance and same_boot:
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


def migrate_volume_seal(config):
    """@cc [owner:fontanierh,label:safety] forward-volume-seal-migration
    Only an explicitly requested schema-1 SEALED record MAY migrate, under all three exclusive
    lane handles after a positive boot change. All old pins except transient device numbers MUST
    match. The old record MUST be archived without replacement and the new stable-volume seal
    MUST require a further OS boot. Migration MUST NOT unseal, replace lanes or activate capacity.
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
        try:
            fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if wire.private_file(archive, limit=wire.MAX_FRAME) != original:
                raise wire.CapacityError('Existing capacity seal archive differs from the original') from None
            fd = os.open(archive, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_mode & 0o077
                        or info.st_size != len(original) or os.read(fd, wire.MAX_FRAME + 1) != original):
                    raise wire.CapacityError('Existing capacity seal archive changed during validation')
                after = os.fstat(fd)
                current = os.lstat(archive)
                if ((info.st_dev, info.st_ino, info.st_ctime_ns) !=
                        (after.st_dev, after.st_ino, after.st_ctime_ns)
                        or (after.st_dev, after.st_ino, after.st_ctime_ns) !=
                        (current.st_dev, current.st_ino, current.st_ctime_ns)):
                    raise wire.CapacityError('Existing capacity seal archive changed during validation')
                os.fsync(fd)
            finally:
                os.close(fd)
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
        directory = os.open(archive.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        value.update(schema=2, seal_boot_id=boot, locks=pins)
        _save(DEFAULT_RECORD, value)
    return value
