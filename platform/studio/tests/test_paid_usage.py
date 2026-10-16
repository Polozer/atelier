"""Usage accounting preserves exact counters and makes incomplete cost coverage explicit."""
import io
import json
import os
import shlex
import subprocess
import sys

import pytest

from atelier.ai import usage
from atelier import contract_review
from test_contract_review import REQUEST, REVIEW


TOKENS = dict(input_tokens=1000, cached_input_tokens=600, output_tokens=200, reasoning_output_tokens=150)


def event(tokens=TOKENS):
    return json.dumps(dict(type='turn.completed', usage=tokens)).encode()+b'\n'


def test_numeric_collector_never_persists_model_text_and_keeps_output_unchanged(tmp_path):
    source = b'{"type":"item.completed","item":{"text":"private tool text"}}\n'+event()
    output = io.BytesIO()
    path = tmp_path/'usage.json'
    usage.capture(path, io.BytesIO(source), output)
    assert output.getvalue() == source
    assert 'private' not in path.read_text()
    assert os.stat(path).st_mode & 0o777 == 0o600
    result = usage.load_capture(path, 'gpt-6.1-sol')
    assert result['status'] == 'reported' and result['turns'] == 1
    assert result['tokens'] == {**TOKENS, 'cache_write_tokens': None}
    # Cached input is a subset, reasoning is included in output; neither is charged twice.
    assert result['cost']['usd'] == '0.00286'
    assert result['cost']['kind'] == 'list-price estimate'
    assert 'cache-write' in result['cost']['pricing']['assumption']
    with pytest.raises(FileExistsError):
        usage.capture(path, io.BytesIO(event()), io.BytesIO())


@pytest.mark.parametrize('value', [None, {}, {**TOKENS, 'cached_input_tokens': 1001},
    {**TOKENS, 'output_tokens': True}, {**TOKENS, 'reasoning_output_tokens': 201},
    {**TOKENS, 'input_tokens': -1}, {**TOKENS, 'output_tokens': '200'}])
def test_malformed_usage_is_explicitly_invalid_without_zero_cost(tmp_path, value):
    path = tmp_path/'usage.json'
    usage.capture(path, io.BytesIO(event(value)), io.BytesIO())
    result = usage.load_capture(path, 'gpt-6.1-sol')
    assert result['status'] == 'invalid' and result['cost'] is None


@pytest.mark.parametrize('source,status', [(b'', 'missing'),
    (event()+b'{"type":"turn.failed"}\n', 'partial'), (event()+event({}), 'partial'),
    (b'{"type":"turn.started"}\n'+event()+b'{"type":"turn.started"}\n', 'partial')])
def test_interrupted_and_partial_usage_is_not_reported_as_complete(tmp_path, source, status):
    path = tmp_path/'usage.json'
    usage.capture(path, io.BytesIO(source), io.BytesIO())
    assert usage.load_capture(path, 'gpt-6.1-sol')['status'] == status


def test_missing_reasoning_detail_stays_unknown(tmp_path):
    path = tmp_path/'usage.json'
    value = {key: item for key, item in TOKENS.items() if key != 'reasoning_output_tokens'}
    usage.capture(path, io.BytesIO(event(value)), io.BytesIO())
    result = usage.load_capture(path, 'gpt-6.1-sol')
    assert result['tokens']['reasoning_output_tokens'] is None
    assert result['cost']['usd'] == '0.00286'


def test_pipeline_keeps_failed_cli_exit_and_already_reported_usage(tmp_path):
    path = tmp_path/'usage.json'
    code = f'import sys; sys.stdout.buffer.write({event()!r}); sys.stdout.flush(); sys.exit(7)'
    command = (f'set -o pipefail; {shlex.quote(sys.executable)} -c {shlex.quote(code)} | '
               f'{shlex.quote(sys.executable)} -m atelier.ai.usage capture {shlex.quote(str(path))}')
    result = subprocess.run(['/bin/bash', '-c', command], capture_output=True, timeout=5)
    assert result.returncode == 7 and result.stdout == event()
    assert usage.load_capture(path, 'gpt-6.1-sol')['tokens']['input_tokens'] == 1000


def test_large_unrelated_event_is_forwarded_but_never_retained(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, 'MAX_BYTES', 256)
    source = b'not-json'+b'x'*500+b'\n'+event()
    output = io.BytesIO()
    path = tmp_path/'usage.json'
    usage.capture(path, io.BytesIO(source), output)
    assert output.getvalue() == source
    assert json.loads(path.read_text())['turns'][0]['input_tokens'] == 1000


def test_final_review_receipt_contains_usage_even_when_review_failed(tmp_path, monkeypatch):
    from atelier.ai import ledger
    capture = tmp_path/'usage.json'
    usage.capture(capture, io.BytesIO(event()), io.BytesIO())
    path = tmp_path/'ledger.json'
    ledger.begin(path, REQUEST)
    for key, value in dict(REVIEW_REQUEST=json.dumps(REQUEST), ACTUAL_REQUEST=json.dumps(REQUEST),
        REVIEW_RESULT=json.dumps(REVIEW), REVIEW_OUTCOME='failure', REVIEW_USAGE_PATH=str(capture),
        GITHUB_OUTPUT=str(tmp_path/'output'), GITHUB_STEP_SUMMARY=str(tmp_path/'summary')).items():
        monkeypatch.setenv(key, value)
    contract_review.main(['finish', str(path)])
    record = json.loads(path.read_text())
    assert record['status'] == 'submission_uncertain' and record['completed'] is False
    assert record['usage']['tokens']['input_tokens'] == 1000
    assert '$0.00286 USD' in (tmp_path/'summary').read_text()


def test_summary_deduplicates_ci_receipts_and_separates_unknown_cost_and_credits(tmp_path):
    capture = tmp_path/'usage.json'
    usage.capture(capture, io.BytesIO(event()), io.BytesIO())
    known = usage.load_capture(capture, 'gpt-6.1-sol')
    records = [dict(operation='code-contract-review', id='1', model='gpt-6.1-sol', status='submitted'),
        dict(operation='code-contract-review', id='1', model='gpt-6.1-sol', status='done',
             finished_at='2026-10-16', usage=known),
        dict(operation='code-contract-review', id='2', model='gpt-6.1-sol', status='submission_uncertain'),
        dict(task_id='task-3', status='success', credits_consumed=12),
        dict(requested_model='gpt-image-2.5-sunburst', status='done', usage=dict(input_tokens=10, output_tokens=20))]
    paths = []
    for i, record in enumerate(records):
        path = tmp_path/f'{i}.json'; path.write_text(json.dumps(record)); paths.append(path)
    result = usage.summarize(paths)
    assert result['operations'] == 4
    row = result['models']['gpt-6.1-sol']
    assert (row['priced'], row['unknown_cost'], row['estimated_usd']) == (1, 1, '0.00286')
    assert (row['input_tokens'], row['output_tokens']) == (1000, 200)
    assert result['models']['tripo']['credits'] == '12'
    assert result['models']['gpt-image-2.5-sunburst']['unknown_cost'] == 1
    assert result['models']['gpt-image-2.5-sunburst']['input_tokens'] == 10
