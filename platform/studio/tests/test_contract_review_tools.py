import hashlib

import pytest

from atelier import contract_review_tools as tools


def fixture_action(tmp_path, monkeypatch, extra=''):
    source = ''.join(f'      uses: {ref}\n' for ref in tools.ACTION_PINS)
    source += ('        node-version: ${{ steps.node-version.outputs.version }}\n'
               '        npm ci\n        effort: ${{ inputs.effort }}\n' + extra)
    action = tmp_path / 'action.yml'; action.write_text(source)
    monkeypatch.setattr(tools, 'SOURCE_SHA256', hashlib.sha256(source.encode()).hexdigest())
    return action


def test_transitive_actions_and_cli_are_pinned_before_use(tmp_path, monkeypatch):
    action = fixture_action(tmp_path, monkeypatch)
    tools.prepare(action)
    value = action.read_text()
    assert all(ref in value for ref in tools.ACTION_PINS.values())
    assert 'npm ci --ignore-scripts' in value
    assert '        package-manager-cache: false\n' in value
    assert f'codex-version: {tools.CODEX_VERSION}' in value


def test_unreviewed_upstream_bytes_are_rejected_without_rewriting(tmp_path):
    action = tmp_path / 'action.yml'; action.write_text('changed upstream action')
    with pytest.raises(ValueError, match='differs'): tools.prepare(action)
    assert action.read_text() == 'changed upstream action'


def test_added_mutable_action_is_rejected(tmp_path, monkeypatch):
    action = fixture_action(tmp_path, monkeypatch, '      uses: example/action@main\n')
    original = action.read_text()
    with pytest.raises(ValueError, match='Unpinned'): tools.prepare(action)
    assert action.read_text() == original


def test_usage_collector_adapts_only_pinned_codex_invocation(tmp_path, monkeypatch):
    outer = fixture_action(tmp_path, monkeypatch)
    source = ('        exec env -u NODE_OPTIONS NODE_OPTIONS=--disable-sigusr1 node --disable-sigusr1 '
              '"$ACTION_PATH/dist/main.js" run-codex-exec \\\n'
              '            --codex-user "$CODEX_USER"\n')
    inner = tmp_path/'codex.yml'; inner.write_text(source)
    monkeypatch.setattr(tools, 'CODEX_ACTION_SHA256', hashlib.sha256(source.encode()).hexdigest())
    tools.prepare(outer, inner)
    assert 'uses: ./.review-codex' in outer.read_text()
    assert 'codex-args: \'["--json"]\'' in outer.read_text()
    assert 'set -o pipefail' in inner.read_text()
    assert 'python3 -m atelier.ai.usage capture "$RUNNER_TEMP/paid-review/usage.json"' in inner.read_text()
    assert 'env -u NODE_OPTIONS NODE_OPTIONS=--disable-sigusr1 node --disable-sigusr1' in inner.read_text()


def test_unreviewed_codex_bytes_leave_both_actions_unchanged(tmp_path, monkeypatch):
    outer = fixture_action(tmp_path, monkeypatch)
    before = outer.read_text()
    inner = tmp_path/'codex.yml'; inner.write_text('unexpected action')
    with pytest.raises(ValueError, match='Codex action differs'):
        tools.prepare(outer, inner)
    assert outer.read_text() == before and inner.read_text() == 'unexpected action'
