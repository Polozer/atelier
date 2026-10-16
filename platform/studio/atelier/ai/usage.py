"""Capture numeric Codex usage and summarize explicit paid-operation receipts without provider calls."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys

MAX_BYTES = 4 * 1024**2
PRICING = dict(model='gpt-6.1-sol', checked='2026-10-16', currency='USD',
               input_per_million='2.00', cached_input_per_million='0.10', output_per_million='10.00',
               source='https://developers.openai.com/api/docs/models/gpt-6.1-sol',
               assumption='Standard short-context rates; cache-write surcharges, regional premiums and taxes excluded')


def numeric_usage(value):
    """Only documented numeric counters reach the paid receipt; absent details stay unknown."""
    if type(value) is not dict:
        raise ValueError('Missing usage object')
    keys = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'cache_write_tokens')
    result = {}
    for key in keys:
        item = value.get(key)
        if item is None and key in keys[3:]:
            result[key] = None
        elif type(item) is int and 0 <= item <= 2**63-1:
            result[key] = item
        else:
            raise ValueError('Invalid usage counter')
    if result['cached_input_tokens'] > result['input_tokens']:
        raise ValueError('Cached input exceeds total input')
    if result['reasoning_output_tokens'] is not None and result['reasoning_output_tokens'] > result['output_tokens']:
        raise ValueError('Reasoning exceeds total output')
    return result


def price(usage, model):
    """Reported input/output include cached/reasoning subsets: neither subset is charged twice."""
    if model != PRICING['model']:
        return None
    value = numeric_usage(usage)
    amount = ((value['input_tokens']-value['cached_input_tokens']) * Decimal(PRICING['input_per_million'])
              + value['cached_input_tokens'] * Decimal(PRICING['cached_input_per_million'])
              + value['output_tokens'] * Decimal(PRICING['output_per_million'])) / 1000000
    return dict(usd=str(amount), kind='list-price estimate', pricing=dict(PRICING))


def _write(path, value, *, exclusive=False):
    path = Path(path)
    if exclusive:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
            out.write(json.dumps(value) + '\n')
            out.flush()
            os.fsync(out.fileno())
        return
    temporary = path.with_suffix(path.suffix + '.pending')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        out.write(json.dumps(value) + '\n')
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def capture(path, source, output):
    """@cc [owner:fontanierh,label:security] numeric-review-usage
    Capture MUST retain only validated numeric usage counters, never model/tool text or credentials.
    Missing, malformed or interrupted usage MUST remain explicitly unknown/partial, never zero spend.
    The trusted collector MUST NOT execute reviewed code or retry a paid operation.
    """
    record = dict(schema=1, source='codex exec --json turn.completed', status='missing', turns=[], invalid_events=0,
                  failed_turns=0, started_turns=0)
    _write(path, record, exclusive=True)
    oversized = False
    while chunk := source.readline(MAX_BYTES+1):
        output.write(chunk)
        output.flush()
        if oversized or len(chunk) > MAX_BYTES:
            oversized = not chunk.endswith(b'\n')
            continue
        event = None
        try:
            event = json.loads(chunk)
            if type(event) is not dict:
                continue
            if event.get('type') == 'turn.started':
                record['started_turns'] += 1
                record['status'] = 'partial' if record['turns'] else 'missing'
                _write(path, record)
            elif event.get('type') == 'turn.completed':
                if len(record['turns']) >= 100:
                    raise ValueError('Usage turn limit exceeded')
                record['turns'].append(numeric_usage(event.get('usage')))
                record['status'] = 'reported'
                _write(path, record)
            elif event.get('type') == 'turn.failed':
                record['failed_turns'] += 1
                record['status'] = 'partial' if record['turns'] else 'missing'
                _write(path, record)
        except (ValueError, TypeError):
            # Non-JSON action progress is allowed. Only malformed *usage* is a coverage error.
            if isinstance(event, dict) and event.get('type') == 'turn.completed':
                record['invalid_events'] += 1
                record['status'] = 'partial' if record['turns'] else 'invalid'
                _write(path, record)
    if record['invalid_events'] or record['failed_turns'] or record['started_turns'] > len(record['turns']):
        record['status'] = 'partial' if record['turns'] else 'invalid' if record['invalid_events'] else 'missing'
        _write(path, record)
    return record


def load_capture(path, model):
    """Missing evidence never prevents finalizing the paid ledger as uncertain or completed."""
    try:
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('Invalid usage receipt')
        record = json.loads(path.read_text())
        if (record.get('schema') != 1 or record.get('status') not in ('reported', 'partial', 'missing', 'invalid')
                or type(record.get('turns')) is not list or len(record['turns']) > 100):
            raise ValueError('Invalid usage receipt')
        turns = [numeric_usage(turn) for turn in record['turns']]
        total = {key: (sum(turn[key] for turn in turns) if turns and all(turn[key] is not None for turn in turns)
                       else None) for key in numeric_usage(dict(input_tokens=0, cached_input_tokens=0, output_tokens=0))}
        return dict(status=record['status'], source='codex exec --json', turns=len(turns), tokens=total,
                    cost=price(total, model) if turns else None)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return dict(status='unavailable', source='codex exec --json', tokens=None, cost=None)


def summarize(paths):
    """Read explicit receipts; CI submitted/final copies and identical copied receipts count once."""
    selected = {}
    unreadable = 0
    for path in paths:
        try:
            path = Path(path)
            if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                raise ValueError('Invalid receipt')
            record = json.loads(path.read_text())
            if type(record) is not dict or 'status' not in record:
                raise ValueError('Not a paid receipt')
            key = (('review', str(record['id'])) if record.get('operation') == 'code-contract-review' and 'id' in record
                   else ('task', str(record['task_id'])) if record.get('task_id')
                   else ('content', hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()))
            old = selected.get(key)
            if old is None or (record.get('finished_at', '') > old.get('finished_at', '')):
                selected[key] = record
        except (OSError, ValueError, TypeError):
            unreadable += 1
    models = {}
    for record in selected.values():
        model = record.get('model', record.get('requested_model', 'tripo' if record.get('task_id') else 'unclassified'))
        if type(model) is not str or not re.fullmatch(r'[a-zA-Z0-9/_.-]{1,100}', model):
            model = 'unclassified'
        row = models.setdefault(model, dict(operations=0, priced=0, unknown_cost=0, partial_usage=0,
                                           token_operations=0, input_tokens=0, output_tokens=0,
                                           estimated_usd=Decimal(0), credits=Decimal(0)))
        row['operations'] += 1
        usage = record.get('usage')
        if type(usage) is dict and usage.get('source') == 'codex exec --json':
            if usage.get('status') != 'reported':
                row['partial_usage'] += 1
            cost = usage.get('cost')
            try:
                amount = Decimal(str(cost['usd']))
                if cost.get('kind') != 'list-price estimate' or not amount.is_finite() or amount < 0:
                    raise ValueError('Invalid estimate')
                row['estimated_usd'] += amount
                row['priced'] += 1
            except (InvalidOperation, TypeError, KeyError, ValueError):
                row['unknown_cost'] += 1
            counters = usage.get('tokens')
        else:
            row['unknown_cost'] += 1
            counters = usage
        if (type(counters) is dict and all(type(counters.get(key)) is int and 0 <= counters[key] <= 2**63-1
                                          for key in ('input_tokens', 'output_tokens'))):
            row['token_operations'] += 1
            row['input_tokens'] += counters['input_tokens']
            row['output_tokens'] += counters['output_tokens']
        credits = record.get('credits_consumed')
        if type(credits) in (int, float) and Decimal(str(credits)).is_finite() and credits >= 0:
            row['credits'] += Decimal(str(credits))
    for row in models.values():
        row['estimated_usd'], row['credits'] = str(row['estimated_usd']), str(row['credits'])
    return dict(operations=len(selected), unreadable=unreadable, models=models,
                scope='Only supplied receipts; estimates exclude unknown costs. Credits are not USD.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('capture').add_argument('path', type=Path)
    summary = commands.add_parser('summary')
    summary.add_argument('paths', type=Path, nargs='+')
    args = parser.parse_args(argv)
    if args.action == 'capture':
        capture(args.path, sys.stdin.buffer, sys.stdout.buffer)
    else:
        print(json.dumps(summarize(args.paths), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
