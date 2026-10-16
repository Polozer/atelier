"""Trusted CI ledger and result validation. Never imports or executes the reviewed checkout."""
import argparse
import json
import os
from pathlib import Path
import re

from .ai import ledger
from .ai import usage


MODEL = 'gpt-6.1-sol'
EFFORT = 'medium'


def request(value):
    required = {'id', 'pull_number', 'base_sha', 'head_sha'}
    if not isinstance(value, dict) or not required <= value.keys():
        raise ValueError('Missing review identity')
    if not re.fullmatch(r'\d+', str(value['id'])) or type(value['pull_number']) is not int or value['pull_number'] < 1:
        raise ValueError('Invalid review request')
    if any(not isinstance(value[key], str) or not re.fullmatch(r'[0-9a-f]{40}', value[key])
           for key in ('base_sha', 'head_sha')):
        raise ValueError('Invalid review commits')
    return {key: value[key] for key in sorted(required)}


def validate(expected, actual, review):
    """@cc [owner:fontanierh,label:correctness] exact-review-result
    A completed result MUST cover the expected head and base and contain a valid, nonempty summary.
    Missing or malformed output MUST NOT become an empty successful review. Findings are advisory.
    Owner notification bodies MAY be empty; violations MUST have an explanation.
    """
    if request(expected) != request(actual):
        raise ValueError('The reviewed commits differ from the requested commits')
    if not isinstance(review, dict) or set(review) != {'summary', 'comments'}:
        raise ValueError('Malformed review result')
    if not isinstance(review['summary'], str) or not review['summary'].strip():
        raise ValueError('Missing review summary')
    if not isinstance(review['comments'], list):
        raise ValueError('Missing review comments')
    violations = 0
    for comment in review['comments']:
        if not isinstance(comment, dict) or set(comment) != {'kind', 'path', 'line', 'side', 'body', 'recipients'}:
            raise ValueError('Malformed review comment')
        if comment['kind'] not in ('contract-change', 'violation') or comment['side'] not in ('LEFT', 'RIGHT'):
            raise ValueError('Unknown review finding')
        if (not isinstance(comment['path'], str) or not comment['path'] or
                type(comment['line']) is not int or comment['line'] < 1 or
                not isinstance(comment['body'], str) or
                not isinstance(comment['recipients'], list) or
                any(not isinstance(item, str) for item in comment['recipients'])):
            raise ValueError('Invalid review comment location or body')
        # Upstream ignores notification bodies and renders recipients as a cc line.
        if comment['kind'] == 'violation' and not comment['body'].strip():
            raise ValueError('Violations must explain the finding')
        violations += comment['kind'] == 'violation'
    return {'completed': True, 'violations': violations, 'comments': len(review['comments'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['begin', 'finish'])
    parser.add_argument('path', type=Path)
    args = parser.parse_args(argv)
    expected = request(json.loads(os.environ['REVIEW_REQUEST']))
    if args.action == 'begin':
        if os.environ.get('GITHUB_RUN_ATTEMPT') != '1':
            raise SystemExit('Paid reviews are never blindly rerun. Reconcile the previous run, then request r? cc.')
        ledger.begin(args.path, {'operation': 'code-contract-review', 'model': MODEL,
                                 'reasoning': EFFORT, **expected})
        return 0
    details = {}
    status = 'submission_uncertain'
    try:
        details = validate(expected, json.loads(os.environ.get('ACTUAL_REQUEST', '')),
                           json.loads(os.environ.get('REVIEW_RESULT', '')))
        if os.environ.get('REVIEW_OUTCOME') == 'success':
            status = 'done'
    except (ValueError, TypeError, KeyError) as error:
        details = {'completed': False, 'error_type': type(error).__name__}
    if status != 'done':
        details['completed'] = False
    details['usage'] = usage.load_capture(os.environ.get('REVIEW_USAGE_PATH', ''), MODEL)
    ledger.finish(args.path, status=status, result=details)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        counters = details['usage'].get('tokens')
        cost = details['usage'].get('cost')
        with open(summary, 'a') as output:
            output.write('\n### Paid contract review\n\n')
            if counters and cost:
                reasoning = counters['reasoning_output_tokens']
                detail = f'{reasoning} reasoning, included in output' if reasoning is not None else 'reasoning detail unreported'
                output.write(f"Reported tokens: {counters['input_tokens']} input "
                             f"({counters['cached_input_tokens']} cached), {counters['output_tokens']} output "
                             f"({detail}).\n\n")
                output.write(f"Standard list-price estimate: **${cost['usd']} USD**. "
                             f"Usage coverage: {details['usage']['status']}. "
                             f"{usage.PRICING['assumption']}. This is not an invoice.\n\n")
            else:
                output.write('Token usage/cost unavailable; do not count this run as zero spend.\n\n')
            output.write('Download final receipt artifacts and total them with '
                         '`uv run python -m atelier.ai.usage summary PATH/ledger.json ...`. '
                         'The total reports supplied-receipt coverage and unknown costs.\n')
    # Only a boolean reaches workflow control; model text is never interpreted as shell code.
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f"completed={str(details['completed']).lower()}\n")
        output.write(f"violations={details.get('violations', 0)}\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
