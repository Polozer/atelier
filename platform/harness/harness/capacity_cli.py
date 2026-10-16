"""Capacity CLI configuration and dispatch; Studio only mounts the subcommand."""


def configure(sub):
    p = sub.add_parser('capacity', help='inspect capacity or run the supervised admission broker')
    p.add_argument('action', choices=['plan', 'history', 'shadow', 'probe', 'serve', 'status', 'reconcile',
                                    'supervise', 'prepare-cutover', 'activate-cutover', 'migrate-volume-seal', 'promote-prior-boot'])
    p.add_argument('path', help='snapshot, guard directory, experiment database, broker config, or status socket')
    p.add_argument('--state', help='explicit absolute simulation database path (shadow only)')
    p.add_argument('--request-id', help='request whose preserved terminal receipt is attested (reconcile only)')
    p.add_argument('--preserved-terminal', help='preserved original aggregate terminal JSON (reconcile only; requires --request-id)')
    p.add_argument('--json', action='store_true')


def main(args):
    if ((args.request_id is None) != (args.preserved_terminal is None)
            or (args.request_id is not None and args.action != 'reconcile')):
        raise SystemExit('--request-id and --preserved-terminal must be used together with capacity reconcile')
    if args.action == 'shadow':
        if not args.state:
            raise SystemExit('capacity shadow requires --state with an explicit absolute simulation database path')
        from atelier.harness.capacity_service import main as shadow_main
        return shadow_main(args.state, args.path)
    if args.state:
        raise SystemExit('--state is only supported by capacity shadow')
    if args.action in ('prepare-cutover', 'activate-cutover', 'migrate-volume-seal', 'promote-prior-boot'):
        from atelier.harness import capacity_compat
        operation = {'prepare-cutover': capacity_compat.prepare, 'activate-cutover': capacity_compat.activate,
                     'migrate-volume-seal': capacity_compat.migrate_volume_seal,
                     'promote-prior-boot': capacity_compat.promote_prior_boot}[args.action]
        operation(args.path)
        print('Legacy lanes sealed; a verified new OS boot is required before ordinary activation.'
              if args.action in ('prepare-cutover', 'migrate-volume-seal')
              else 'Full capacity compatibility barrier activated; clients still require broker admission.')
        return 0
    if args.action == 'serve':
        from atelier.harness.capacity_broker import main as serve_main
        return serve_main(args.path)
    if args.action == 'supervise':
        from atelier.harness.capacity_supervision import install
        return install(args.path)
    if args.action in ('status', 'reconcile'):
        import json
        from atelier.harness.capacity_client import reconcile, status
        result = (reconcile(args.path, request_id=args.request_id, preserved_terminal=args.preserved_terminal)
                  if args.action == 'reconcile' else status(args.path))
        print(json.dumps(result, indent=2))
        return 0
    if args.action == 'probe':
        from atelier.harness.capacity_probe import main as probe_main
        return probe_main(args.path)
    if args.action == 'history':
        from atelier.harness.capacity_history import show
        return show(args.path, as_json=args.json)
    from atelier.harness import capacity
    return capacity.main(args.path, as_json=args.json)
