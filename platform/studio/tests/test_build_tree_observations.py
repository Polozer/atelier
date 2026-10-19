"""Build history binds observations to the current action and launcher, without changing sizing."""
import json
import os
from types import SimpleNamespace

import pytest
from atelier import build,build_tree_observations as reader
from atelier.harness.safety import tree_observation as history


def sample(tmp_path):
    profile=dict(phase='job',performance=False,resources=dict(memory_mib=4096,cpu_millis=3000,gpu_mib=0,temp_mib=0,io_slots=0))
    value=dict(root=[7,70],peak_bytes=2*1024**3,limit_bytes=4*1024**3,profile=profile,profile_sha256=history.identity(profile))
    history.publish(tmp_path,'a'*32,value,'c'*64,'e'*64)
    return tmp_path/history.REPORT


def test_history_binds_action_invocation_and_retains_tree_peak(tmp_path):
    sample(tmp_path)
    result=reader.read(tmp_path,'a'*32,'f'*64)
    assert result['action_fingerprint']=='f'*64 and result['peak_bytes']==2*1024**3
    assert reader.read(tmp_path,'b'*32,'f'*64) is None
    # New successful-tree history is intentionally not read by existing eligibility.
    assert build.expected_peak_gib(tmp_path) is None
    (tmp_path/'step-peak.json').write_text(json.dumps({'peak_bytes':3*1024**3}))
    assert build.expected_peak_gib(tmp_path)==3


@pytest.mark.parametrize('change',[dict(invocation_id='old'),dict(cleanup_and_capacity_close=False),
    dict(command_sha256='raw argv'),dict(environment_sha256='raw secret'),dict(profile_sha256='0'*64),
    dict(root=[True,70]),dict(peak_bytes=True),dict(peak_bytes=5*1024**3),dict(extra='unexpected')])
def test_bad_history_remains_unknown(tmp_path,change):
    path=sample(tmp_path);value=json.loads(path.read_text());path.write_text(json.dumps(value|change))
    assert reader.read(tmp_path,'a'*32,'f'*64) is None


@pytest.mark.skipif(not hasattr(os,'mkfifo'),reason='POSIX nofollow/nonblocking inputs')
def test_history_reader_refuses_fifo_and_symlink_without_blocking(tmp_path):
    path=tmp_path/history.REPORT;os.mkfifo(path)
    assert reader.read(tmp_path,'a'*32,'f'*64) is None
    path.unlink();target=sample(tmp_path);raw=target.read_bytes();target.unlink()
    other=tmp_path/'other';other.write_bytes(raw);path.symlink_to(other)
    assert reader.read(tmp_path,'a'*32,'f'*64) is None

from test_build_cache import project  # noqa: F401 - isolated non-native action/cache fixture


def test_build_publication_keeps_keys_and_cache_bytes_and_refuses_failed_outputs(project,monkeypatch):
    p=project;p.step.heavy=True
    monkeypatch.setattr(build,'slot_request',lambda *_:('job',None))
    run=build.run_command
    def observed(*args,**kwargs):
        result=run(*args,**kwargs)
        folder=p.ctx.logs/'mesh.guard';folder.mkdir(exist_ok=True)
        sample(folder)
        (folder/'execution-timings.json').write_text(json.dumps(dict(schema=1,invocation_id='a'*32,
            admission_seconds=0,child_lifetime_seconds=1,execution_seconds=None)))
        return result
    monkeypatch.setattr(build,'run_command',observed)
    assert p.run()==0
    stamp=p.ctx.stamps/'mesh.json';record=json.loads(stamp.read_text());key=record['fingerprint']
    assert record['commands'][0]['whole_tree']['action_fingerprint']==key
    cache_bytes=p.store.action(key).read_bytes()
    monkeypatch.setattr(build,'run_command',run)
    assert p.run(force=True)==0
    record=json.loads(stamp.read_text())
    assert record['fingerprint']==key and 'whole_tree' not in record['commands'][0]
    assert p.store.action(key).read_bytes()==cache_bytes
    def missing(*args,**kwargs):
        result=observed(*args,**kwargs)
        p.step.products[1].paths[0].unlink()
        return result
    monkeypatch.setattr(build,'run_command',missing)
    assert p.run(force=True)==1 and not stamp.exists()
