"""Run explicit synthetic TR01 station transfers in the shared task journal."""
import argparse
import json
from pathlib import Path

from lab_station_transport import Journal, TaskError, TransportRunner, resolve_store, run_demo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store')
    parser.add_argument('--world-id', required=True, help='Persistent synthetic world; init never resets it')
    parser.add_argument('--actions', help='JSONL actions with actor_id, command and command arguments')
    parser.add_argument('command', choices=['init', 'status', 'resume', 'demo'])
    args = parser.parse_args(argv)
    try:
        with Journal(resolve_store(args.store)) as journal:
            if args.command in {'init','demo'}:
                runner = TransportRunner.init(journal, args.world_id)
            elif args.command == 'resume':
                runner = TransportRunner.open(journal, args.world_id, resume=True)
            else:
                runner = TransportRunner(journal, args.world_id, None)
            if args.command == 'status' and args.actions:
                raise TaskError('status is read-only')
            if args.command == 'demo':
                if args.actions:
                    raise TaskError('Demo generates its own explicit synthetic inputs')
                report = run_demo(runner)
            else:
                if args.actions:
                    for line in Path(args.actions).read_text().splitlines():
                        action = json.loads(line)
                        command = action.pop('command')
                        if command not in {'accept','intent','confirm','reconcile'}:
                            raise TaskError('Unsupported session command')
                        getattr(runner, command)(action.pop('actor_id'), **action)
                report = runner.report()
            print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (TaskError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
