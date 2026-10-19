"""Optional successful whole-tree diagnostics; never admission or output certificates."""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

REPORT = 'successful-tree-observation.json'


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def clear(folder):
    try:
        (Path(folder) / REPORT).unlink(missing_ok=True)
        return True
    except Exception:
        return False


def capture(aggregate, child, started, limit_bytes, admission):
    """Retain only bounded numeric/profile fields from an already judged successful tree."""
    try:
        if aggregate is None or child.returncode != 0 or not aggregate.receipt('child_exited'):
            return None
        if admission is None or admission.mode != 'capacity':
            return None
        fd = os.open(aggregate.report, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                return None
            value = json.loads(stream.read(1024 * 1024 + 1))
        if (value.get('owner'), value.get('owner_started'), value.get('limit_bytes'),
                value.get('state'), value.get('cleanup_complete'), value.get('processes'),
                value.get('footprint_bytes')) != (child.pid, started, limit_bytes, 'child_exited', True, [], 0):
            return None
        peak = value.get('peak_bytes')
        if type(peak) is not int or not 0 < peak <= limit_bytes:
            return None
        request = admission.request
        resources = request['resources']
        # No owner, purpose, paths, nonce or raw environment enters the observation.
        profile = dict(phase=request['phase'], performance=request['performance'],
                       resources={key: resources[key] for key in
                                  ('memory_mib', 'cpu_millis', 'gpu_mib', 'temp_mib', 'io_slots')})
        if any(type(v) is not int or v < 0 for v in profile['resources'].values()):
            return None
        if profile['resources']['memory_mib'] * 1024**2 < limit_bytes:
            return None
        return dict(root=[child.pid, started], peak_bytes=peak, limit_bytes=limit_bytes,
                    profile=profile, profile_sha256=identity(profile))
    except Exception:
        return None


def publish(folder, invocation, observation, command_sha256, environment_sha256):
    """@cc [owner:fontanierh,label:correctness] successful-tree-diagnostic-boundary
    Publish only after a successful guarded lifecycle returns through cleanup and capacity close.
    This diagnostic MUST NOT change admission, ceilings, build success or output certification.
    Raw argv/environment, owner/purpose and broker credentials MUST NOT be published. Missing or
    failed diagnostics MUST stay unknown. Consumers MUST bind the exact launcher invocation.
    The full environment digest is per-invocation provenance, not a reusable sizing key.
    """
    temporary = None
    try:
        if observation is None or command_sha256 is None or environment_sha256 is None:
            return
        value = dict(schema=1, invocation_id=invocation, cleanup_and_capacity_close=True,
                     command_sha256=command_sha256, environment_sha256=environment_sha256,
                     tool_identity_scope='action-fingerprint-required', **observation)
        path = Path(folder) / REPORT
        temporary = path.with_name('.' + REPORT + '.' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, allow_nan=False)
            stream.write('\n')
        temporary.replace(path)
    except Exception:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
