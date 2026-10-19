"""Successful-tree history is optional, redacted, and cannot survive a failed lifecycle."""
import json
from types import SimpleNamespace

import pytest

from atelier.harness.safety import guarded, tree_observation as history


def fixture(tmp_path):
    path=tmp_path/'tree.json'
    value=dict(owner=7,owner_started=70,limit_bytes=10*1024**3,peak_bytes=3*1024**3,
               state='child_exited',cleanup_complete=True,processes=[],footprint_bytes=0)
    path.write_text(json.dumps(value))
    child=SimpleNamespace(pid=7,returncode=0)
    monitor=SimpleNamespace(report=path,receipt=lambda state:state=='child_exited')
    session=SimpleNamespace(mode='capacity',request=dict(phase='job',performance=False,
        resources=dict(memory_mib=10240,cpu_millis=3000,gpu_mib=0,temp_mib=0,io_slots=0),
        owner='private-owner',purpose='private-purpose',nonce='private-nonce'))
    return value,child,monitor,session


def test_successful_capture_uses_whole_tree_peak_and_full_profile(tmp_path):
    _,child,monitor,session=fixture(tmp_path)
    result=history.capture(monitor,child,70,10*1024**3,session)
    assert result['peak_bytes']==3*1024**3 and result['profile']['resources']['cpu_millis']==3000
    assert result['profile_sha256']==history.identity(result['profile'])
    text=json.dumps(result)
    assert all(secret not in text for secret in ['private-owner','private-purpose','private-nonce'])


@pytest.mark.parametrize('change',[dict(owner=8),dict(owner_started=71),dict(state='memory_limit'),
    dict(cleanup_complete=False),dict(processes=[{'pid':7}]),dict(footprint_bytes=1),dict(peak_bytes=True),
    dict(peak_bytes=11*1024**3),dict(limit_bytes=4*1024**3)])
def test_incomplete_stopped_or_mismatched_tree_is_unknown(tmp_path,change):
    value,child,monitor,session=fixture(tmp_path)
    monitor.report.write_text(json.dumps(value|change))
    assert history.capture(monitor,child,70,10*1024**3,session) is None


def test_no_failed_or_unadmitted_capture(tmp_path):
    _,child,monitor,session=fixture(tmp_path)
    child.returncode=1
    assert history.capture(monitor,child,70,10*1024**3,session) is None
    child.returncode=0
    assert history.capture(monitor,child,70,10*1024**3,None) is None
    session.request['resources']['memory_mib']=4096
    assert history.capture(monitor,child,70,10*1024**3,session) is None


def test_publication_contains_only_environment_and_command_digests(tmp_path):
    _,child,monitor,session=fixture(tmp_path)
    value=history.capture(monitor,child,70,10*1024**3,session)
    history.publish(tmp_path,'a'*32,value,history.identity(['private-argv']),history.identity({'TOKEN':'private-key'}))
    result=json.loads((tmp_path/history.REPORT).read_text())
    assert result['cleanup_and_capacity_close'] is True
    assert all(s not in json.dumps(result) for s in ['private-argv','private-key','TOKEN'])


@pytest.mark.parametrize('failure',[RuntimeError('close uncertain'),SystemExit(143)])
def test_failed_lifecycle_clears_old_observation_and_never_publishes(tmp_path,monkeypatch,failure):
    path=tmp_path/history.REPORT;path.write_text('old')
    def run(*args,**kwargs):
        kwargs['_timings']['tree_observation']={'peak_bytes':123}
        raise failure
    monkeypatch.setattr(guarded,'_run',run)
    with pytest.raises(type(failure)):
        guarded.run(['unused'],tmp_path,lock=False)
    assert not path.exists()


def test_publication_occurs_only_after_run_cleanup_returns(tmp_path,monkeypatch):
    events=[]
    def run(*args,**kwargs):
        events.append('cleanup-and-close-returned')
        kwargs['_timings'].update(tree_observation={'peak_bytes':123},command_sha256='c'*64,environment_sha256='e'*64)
        return 0
    def publish(*args):events.append('publish')
    monkeypatch.setattr(guarded,'_run',run);monkeypatch.setattr(history,'publish',publish)
    assert guarded.run(['unused'],tmp_path,lock=False)==0
    assert events==['cleanup-and-close-returned','publish']


def test_unexpected_diagnostic_sink_failure_cannot_fail_a_completed_job(tmp_path,monkeypatch):
    monkeypatch.setattr(guarded,'_run',lambda *a,**kw:0)
    def fail(*args):raise TypeError('broken optional sink')
    monkeypatch.setattr(history,'publish',fail)
    assert guarded.run(['unused'],tmp_path,lock=False)==0
