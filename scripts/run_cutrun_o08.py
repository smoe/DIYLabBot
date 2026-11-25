"""Inspect and record synthetic O08 results for a manual CUT&RUN fixture run."""

import json
from pathlib import Path
import sqlite3

from cutrun_o08_results import normalize_export, read_plan
from cutrun_o08_workflow import CutRunO08Workflow
from manual_tasks import Journal, TaskError, digest
from manual_workflow import resolve_store
from run_cutrun_manual import Parser, read_json, runtime_path


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--store', type=Path)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    inspect = commands.add_parser('inspect', help='Normalize a fixture without a journal')
    inspect.add_argument('--plan', type=Path, required=True)
    inspect.add_argument('--export', type=Path, required=True)
    commands.add_parser('report', help='Read the archived O08 evidence').add_argument('run_id')
    for name in ('bind', 'import'):
        command = commands.add_parser(name)
        command.add_argument('run_id')
        command.add_argument('--session', required=True)
        command.add_argument('--actor', required=True)
        command.add_argument('--observation', type=Path, required=True)
        if name == 'bind':
            command.add_argument('--plan', type=Path, required=True)
        else:
            command.add_argument('--export', type=Path, required=True)
            command.add_argument('--plan-id', required=True)
    try:
        args = parser.parse_args(argv)
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (TaskError, ValueError, OSError, OverflowError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


def execute(args):
    if args.command == 'inspect':
        raw = args.plan.read_bytes()
        return normalize_export(args.export.read_bytes(), read_plan(raw), digest(raw))
    store = runtime_path(resolve_store(args.store))
    if not store.is_file():
        raise TaskError('Existing manual fixture journal required')
    with Journal(store) as journal:
        flow = CutRunO08Workflow(journal, args.run_id, getattr(args, 'session', None))
        if args.command == 'report':
            return flow.o08_report()
        observation = read_json(args.observation)
        if args.command == 'bind':
            raw = args.plan.read_bytes()
            plan = read_plan(raw)
            state = flow.act('bind_o08_plan', args.actor, artifact=raw, observation=observation,
                             file_name=args.plan.name)
            return state['manual']['o08_plans'][plan['plan_id']]
        raw = args.export.read_bytes()
        state = flow.act('import_o08_export', args.actor, artifact=raw, observation=observation,
                         plan_id=args.plan_id, file_name=args.export.name)
        return state['manual']['o08_plans'][args.plan_id]['exports'][digest(raw)]


if __name__ == '__main__':
    raise SystemExit(main())
