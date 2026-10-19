"""Bind optional successful whole-tree diagnostics to certified build action history."""
import json
import os
import re
import stat

from atelier.harness.safety.tree_observation import REPORT, identity


def read(folder, invocation, action):
    """@cc [owner:fontanierh,label:correctness] tree-history-is-not-sizing
    Only the exact successful launcher invocation MAY supply an observation to a successful
    action's history. Missing, malformed, stale or unbound observations MUST remain unknown.
    This history MUST NOT participate in fingerprints, eligibility, reservations or guard limits.
    Action fingerprints retain their existing tool/input scope; this receipt MUST NOT claim a
    complete transitive tool/environment calibration or automatically establish a smaller profile.
    """
    try:
        fd = os.open(folder / REPORT, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
                return None
            value = json.loads(stream.read(8193))
        expected = {'schema', 'invocation_id', 'cleanup_and_capacity_close', 'command_sha256',
                    'environment_sha256', 'tool_identity_scope', 'root', 'peak_bytes', 'limit_bytes',
                    'profile', 'profile_sha256'}
        if (not isinstance(value, dict) or set(value) != expected or type(value['schema']) is not int
                or value['schema'] != 1 or value['invocation_id'] != invocation
                or value['cleanup_and_capacity_close'] is not True
                or value['tool_identity_scope'] != 'action-fingerprint-required'):
            return None
        for digest in [action, value['command_sha256'], value['environment_sha256'], value['profile_sha256']]:
            if type(digest) is not str or re.fullmatch('[0-9a-f]{64}', digest) is None:
                return None
        if (type(value['root']) is not list or len(value['root']) != 2
                or any(type(v) is not int or v <= 0 for v in value['root'])
                or type(value['peak_bytes']) is not int or type(value['limit_bytes']) is not int
                or not 0 < value['peak_bytes'] <= value['limit_bytes']):
            return None
        profile = value['profile']
        if (type(profile) is not dict or set(profile) != {'phase', 'performance', 'resources'}
                or profile['phase'] not in ('job', 'game', 'compile') or type(profile['performance']) is not bool
                or type(profile['resources']) is not dict
                or set(profile['resources']) != {'memory_mib', 'cpu_millis', 'gpu_mib', 'temp_mib', 'io_slots'}
                or any(type(v) is not int or v < 0 for v in profile['resources'].values())
                or profile['resources']['memory_mib'] * 1024**2 < value['limit_bytes']
                or identity(profile) != value['profile_sha256']):
            return None
        return dict(value, action_fingerprint=action)
    except Exception:
        return None
