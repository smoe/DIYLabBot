"""Run one explicit, durable synthetic storage fixture; no motion or stock API."""
import argparse
import json

from kit_storage_workflow import Journal, StorageRunner, TaskError, resolve_store, run_demo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', help='Existing shared task-journal store, or an explicit private fixture store')
    parser.add_argument('--fixture-id', required=True, help='Persistent synthetic test-world identity; init never resets it')
    parser.add_argument('command', choices=['init', 'status', 'resume', 'demo'])
    args = parser.parse_args(argv)
    try:
        with Journal(resolve_store(args.store)) as journal:
            if args.command in {'init', 'demo'}:
                runner = StorageRunner.init(journal, args.fixture_id)
            elif args.command == 'resume':
                runner = StorageRunner.open(journal, args.fixture_id, resume=True)
            else:
                runner = StorageRunner(journal, args.fixture_id, None)
            result = run_demo(runner) if args.command == 'demo' else runner.report()
            if args.command in {'init', 'resume'}:
                runner.close()
                result = runner.report()
            print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (TaskError, OSError, ValueError) as error:
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
