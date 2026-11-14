"""Shared CLI for source-bound synthetic extraction and manual TapeStation QC.

Only demo invents positive observations. Status/report are read-only; resume
requires explicit inventory and pending-operation reconciliation.
"""
import json
from pathlib import Path
import sqlite3

from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store
from run_material_lifecycle import Parser, report_path, runtime_path
from tapestation_results import MAX_REPORT_BYTES


def run_cli(workflow_class, run_demo, description, argv=None):
    parser = Parser(description=description)
    parser.add_argument('--store', type=Path)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('create', 'demo'):
        item = sub.add_parser(name)
        item.add_argument('--run-id')
        item.add_argument('--profile', type=Path)
        item.add_argument('--out', type=Path)
        if name == 'demo':
            item.add_argument('--pause-after', help='Stop after the named phase, or before_confirm:PHASE_ID')
    for name in ('status', 'report', 'resume', 'act'):
        item = sub.add_parser(name)
        item.add_argument('run_id')
        item.add_argument('--out', type=Path)
        if name == 'act':
            item.add_argument('--session', required=True)
            item.add_argument('--actor', required=True)
            item.add_argument('--action', required=True)
            item.add_argument('--data', default='{}', help='Explicit synthetic observation arguments as JSON')
            item.add_argument('--artifact', type=Path)
    try:
        args = parser.parse_args(argv)
        target = report_path(args.out) if args.out else None
        store = runtime_path(resolve_store(args.store))
        if target == store:
            raise TaskError('A report must not overwrite the task journal')
        if args.command not in {'create', 'demo'} and not store.is_file():
            raise TaskError('An existing journal is required')
        artifact = None
        if args.command == 'act':
            data = json.loads(args.data)
            if not isinstance(data, dict):
                raise TaskError('Action data must be a JSON object')
            if args.artifact is not None:
                if args.artifact.stat().st_size > MAX_REPORT_BYTES:
                    raise TaskError('TapeStation report exceeds the bounded import size')
                with args.artifact.open('rb') as stream:
                    artifact = stream.read(MAX_REPORT_BYTES + 1)
                if len(artifact) > MAX_REPORT_BYTES:
                    raise TaskError('TapeStation report exceeds the bounded import size')
                if args.action != 'import_results':
                    raise TaskError('Artifacts are accepted only by the explicit result import command')
        with Journal(store) as journal:
            if args.command == 'demo':
                result = run_demo(journal, run_id=args.run_id, source=args.profile,
                                  pause_after=args.pause_after)
            elif args.command == 'create':
                flow = workflow_class.create(journal, source=args.profile, run_id=args.run_id)
                result = {'run_id': flow.run_id, 'session': flow.session, 'state': flow.state}
            elif args.command == 'resume':
                flow = workflow_class.open(journal, args.run_id, resume=True)
                result = {'run_id': args.run_id, 'session': flow.session, 'state': flow.state}
            elif args.command == 'act':
                flow = workflow_class(journal, args.run_id, args.session)
                result = flow.act(args.action, args.actor, artifact=artifact, **data)
            else:
                result = workflow_class(journal, args.run_id, None).report()
                if args.command == 'status':
                    result = {key: result[key] for key in (
                        'run_id', 'status', 'passed', 'pending_operation', 'recovery_required',
                        'resources', 'process') if key in result}
        content = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if target is not None:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(content)
        print(content, end='')
        return 0
    except (TaskError, ValueError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1
