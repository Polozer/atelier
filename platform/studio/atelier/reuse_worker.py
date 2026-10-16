"""Owned child for the guarded reuse launcher; includes no independent lock or admission."""
import argparse

from . import reuse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('copy', 'abandon'))
    parser.add_argument('game')
    parser.add_argument('target')
    parser.add_argument('source', nargs='?')
    parser.add_argument('--invocation', required=True)
    args = parser.parse_args()
    if args.action == 'copy':
        if args.source is None:
            parser.error('copy requires a donor checkout')
        return reuse._copy(args.game, args.source, args.target, operation_id=args.invocation)
    if args.source is not None:
        parser.error('abandon has no donor checkout')
    return reuse._abandon(args.game, args.target)


if __name__ == '__main__':
    raise SystemExit(main())
