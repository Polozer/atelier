"""Repeated live volume checks must not grow ctypes' strongly retained type cache."""
import ctypes
from types import SimpleNamespace
import uuid

import pytest

from atelier.harness import capacity_compat as compat


@pytest.mark.parametrize('descriptor', [False, True])
def test_repeated_volume_reads_have_bounded_types_and_fresh_results(monkeypatch, tmp_path, descriptor):
    observations = [uuid.uuid4(), uuid.uuid4()]
    calls = []
    class Operation:
        def __call__(self, path, attributes, output, length, options):
            calls.append(path)
            value = observations[(len(calls) - 1) % 2]
            ctypes.memmove(output, (20).to_bytes(4, compat.sys.byteorder) + value.bytes, 20)
            return 0
    library = SimpleNamespace(getattrlist=Operation(), fgetattrlist=Operation())
    monkeypatch.setattr(compat.sys, 'platform', 'darwin')
    monkeypatch.setattr(compat.ctypes, 'CDLL', lambda *args, **kwargs: library)
    before = len(ctypes._pointer_type_cache)
    selector = 7 if descriptor else tmp_path
    results = [compat._volume_uuid(selector) for _ in range(256)]
    # The parent implementation adds one immortal Structure+pointer class pair per observation.
    assert len(ctypes._pointer_type_cache) - before <= 1
    assert len(calls) == 256
    assert results == [str(observations[i % 2]) for i in range(256)]  # No cached filesystem result.
