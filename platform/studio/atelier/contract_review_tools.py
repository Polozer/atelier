"""Pin the upstream review action's transitive actions without maintaining a fork of its code."""
import hashlib
from pathlib import Path
import re
import sys


# .github/actions/contract-review/action.yml at spolu/code-contracts commit
# 6d1b1a945d1fe02a43bac567341b77ccfdf3ae33. Update the revision, hash and reviewed pins together.
SOURCE_SHA256 = '25deeb8f8b39a747e1c466721b23a4a11cee59f4fc1ff5c69701d554a018bb72'
CODEX_VERSION = '0.162.1'
CODEX_ACTION_SHA256 = '448852e9e59565440bf25174b54bbf661bd66102be295af2e526fa09eaaf3bd7'
ACTION_PINS = {
    'actions/github-script@v7': 'actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3',  # v9.0.0, Node 24
    'actions/checkout@v5': 'actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09',
    'actions/setup-node@v4': 'actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1',  # v7.1.0, Node 24
    'openai/codex-action@v1': 'openai/codex-action@1d82a3dba7c7988ec71ecae1ed5b8e8db96495c5',
}


def prepare_codex(original):
    """Only the pinned action's invocation is piped through the trusted numeric collector."""
    if hashlib.sha256(original).hexdigest() != CODEX_ACTION_SHA256:
        raise ValueError('Codex action differs from the reviewed revision')
    source = original.decode()
    start = '        exec env -u NODE_OPTIONS NODE_OPTIONS=--disable-sigusr1 node --disable-sigusr1 '
    end = '            --codex-user "$CODEX_USER"\n'
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError('Codex action invocation changed')
    source = source.replace(start, '        set -o pipefail\n' + start.replace('exec env', 'env'))
    return source.replace(end, end.rstrip('\n') + ' | \\\n'
                          '          PYTHONPATH="$GITHUB_WORKSPACE/.ci-controller/platform/studio" '
                          'python3 -m atelier.ai.usage capture "$RUNNER_TEMP/paid-review/usage.json"\n')


def prepare(action, codex_action=None):
    """@cc [owner:fontanierh,label:security] immutable-review-toolchain
    Only the reviewed upstream action bytes may be adapted. Every referenced action and the Codex
    CLI/proxy version MUST be pinned before use. Checker dependency installation MUST disable lifecycle scripts
    and automatic package-manager caching.
    """
    action = Path(action)
    original = action.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError('Upstream review action differs from the reviewed revision')
    source = original.decode()
    for before, after in ACTION_PINS.items():
        if before not in source:
            raise ValueError(f'Missing expected upstream action: {before}')
        source = source.replace(before, after)
    source = source.replace('        npm ci\n', '        npm ci --ignore-scripts\n')
    node = '        node-version: ${{ steps.node-version.outputs.version }}\n'
    if source.count(node) != 1:
        raise ValueError('Upstream Node setup changed')
    source = source.replace(node, node + '        package-manager-cache: false\n')
    effort = '        effort: ${{ inputs.effort }}\n'
    if effort not in source or 'npm ci --ignore-scripts' not in source:
        raise ValueError('Upstream tool installation or model configuration changed')
    source = source.replace(effort, effort + f'        codex-version: {CODEX_VERSION}\n')
    for action_ref in re.findall(r'^\s*uses:\s*(\S+)', source, re.MULTILINE):
        if not re.fullmatch(r'[\w/-]+@[0-9a-f]{40}', action_ref):
            raise ValueError(f'Unpinned transitive action: {action_ref}')
    if codex_action is not None:
        codex_action = Path(codex_action)
        codex_source = prepare_codex(codex_action.read_bytes())
        ref = ACTION_PINS['openai/codex-action@v1']
        if source.count(ref) != 1:
            raise ValueError('Expected one pinned Codex action')
        source = source.replace(ref, './.review-codex')
        source = source.replace(f'        codex-version: {CODEX_VERSION}\n',
                                f'        codex-version: {CODEX_VERSION}\n        codex-args: \'["--json"]\'\n')
        codex_action.write_text(codex_source)
    action.write_text(source)


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        raise SystemExit('Usage: python -m atelier.contract_review_tools ACTION_YML [CODEX_ACTION_YML]')
    prepare(*sys.argv[1:])
