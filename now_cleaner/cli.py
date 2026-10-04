from __future__ import annotations

import argparse
import json
from pathlib import Path

from .store import Store, default_destination
from . import engine


def main(argv=None):
    parser = argparse.ArgumentParser(description='NOW Cleaner module workflow')
    parser.add_argument('--state-dir', type=Path, help='Override local inventory location (testing/portable use)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    create = commands.add_parser('create')
    create.add_argument('name')
    create.add_argument('--destination', type=Path)
    create.add_argument('--mode', choices=['local', 'drive'], default='local')
    create.add_argument('--notebook', default='')
    create.add_argument('--limit', type=int, default=50)
    create.add_argument('--reserved', type=int, default=15)
    review = commands.add_parser('preview')
    review.add_argument('module')
    review.add_argument('inputs', nargs='+', type=Path)
    review.add_argument('--full', action='store_true')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('token')
    prepare.add_argument('--decisions', type=Path, help='JSON keyed by preview item key: group, candidate, rename, remove or skip')
    apply = commands.add_parser('apply')
    apply.add_argument('token')
    apply.add_argument('--approve-warnings', action='store_true')
    sync = commands.add_parser('sync')
    sync.add_argument('module')
    history = commands.add_parser('history')
    history.add_argument('module')
    connect = commands.add_parser('connect')
    connect.add_argument('client_json', type=Path)
    commands.add_parser('disconnect')
    probe = commands.add_parser('probe')
    probe.add_argument('--update', action='store_true')
    confirm = commands.add_parser('confirm-probe')
    confirm.add_argument('--doc', action='store_true')
    confirm.add_argument('--pdf', action='store_true')
    args = parser.parse_args(argv)
    store = Store(args.state_dir)
    try:
        if args.command == 'list':
            result = store.modules()
        elif args.command == 'create':
            result = store.save_module(args.name, args.destination or default_destination(), args.notebook, args.mode, args.limit, args.reserved)
        elif args.command == 'preview':
            result = engine.preview(store, args.module, args.inputs, args.full)
        elif args.command == 'prepare':
            decisions = json.loads(args.decisions.read_text()) if args.decisions else {}
            result = engine.prepare(store, args.token, decisions)
        elif args.command == 'apply':
            if len(args.token) != 32 or any(c not in '0123456789abcdef' for c in args.token):
                raise ValueError('Invalid preview token')
            candidate = json.loads((store.state / 'previews' / args.token / 'prepared.json').read_text())
            if candidate['warnings'] and not args.approve_warnings:
                raise ValueError('Review prepared warnings and pass --approve-warnings to acknowledge them')
            result = engine.apply(store, args.token)
        elif args.command == 'history':
            result = store.history(args.module)
        else:
            from . import drive
            if args.command == 'connect':
                drive.connect(store, args.client_json)
                result = 'Connected; synthetic sync verification is still required'
            elif args.command == 'disconnect':
                drive.disconnect(store)
                result = 'Credentials removed; Drive files were not deleted'
            elif args.command == 'probe':
                result = drive.probe(store, args.update)
            elif args.command == 'confirm-probe':
                drive.confirm_probe(store, args.doc, args.pdf)
                result = 'Recorded your manual verification for this Google account'
            else:
                result = drive.sync(store, args.module)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        # HTTP exceptions can contain uploaded content or credentials: never echo them.
        message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else 'Operation failed. Local files are safe; check setup or retry.'
        print(message)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
