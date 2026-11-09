"""Shared local manual-workflow CLI; device adapters provide only their demo and card fields."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from manual_tasks import Journal, TaskError
from manual_workflow import ROOT, DEFAULT_STORE

def output_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to((ROOT / 'exports').resolve()):
        raise TaskError('Runtime output must be inside this project exports/ directory')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def work_card(flow):
    state = flow.state
    return {'run_id': flow.run_id, 'mode': 'synthetic_only', 'status': state['status'],
            'actor_id': state['actor_id'], 'recovery_required': state['recovery_required'],
            'sop': state['definition']['protocol']['sop'],
            'instrument': state['definition']['profile']['instrument'],
            'parameters': state['definition']['profile']['parameters'],
            'planned_measurements': state['planned_measurements'],
            'samples': flow.report_samples(state), 'resources': state['resources'],
            'imports': {key: {k: record[k] for k in ['file_name','status','issues']}
                        for key, record in state['imports'].items()},
            **flow.card_extra(state)}

def session(flow, actions=None):
    """One process per work session; restarting requires physical reconciliation."""
    print(json.dumps(work_card(flow), ensure_ascii=False))
    stream = open(actions, encoding='utf-8') if actions else sys.stdin
    try:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            if line == 'quit':
                break
            if line == 'status':
                print(json.dumps(work_card(flow), ensure_ascii=False))
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) - {'command', 'actor_id', 'data', 'file'}:
                    raise TaskError('Expected command, actor_id, data, and optional import file')
                command, actor = request['command'], request['actor_id']
                if command == 'import_results':
                    flow.import_file(request['file'], actor, **request.get('data', {}))
                else:
                    flow.act(command, actor, **request.get('data', {}))
                print(json.dumps(work_card(flow), ensure_ascii=False))
                if flow.state['status'] in {'completed', 'cancelled'}:
                    break
            except (TaskError, KeyError, TypeError, json.JSONDecodeError, OSError) as error:
                print(json.dumps({'error': str(error), 'run_id': flow.run_id}), file=sys.stderr)
                if actions or not sys.stdin.isatty():
                    raise TaskError(str(error)) from error
    finally:
        if actions:
            stream.close()

def run_cli(workflow, source, run_demo, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['demo', 'create']:
        child = sub.add_parser(name)
        child.add_argument('--profile', type=Path, default=source)
        child.add_argument('--run-id')
        if name == 'demo':
            child.add_argument('--pause-after-intent', action='store_true')
    for name in ['status', 'report', 'session']:
        child = sub.add_parser(name)
        child.add_argument('run_id')
        if name == 'session':
            child.add_argument('--resume', action='store_true', help='Invalidate an interrupted session; physical reconciliation is mandatory')
            child.add_argument('--actions', type=Path, help='JSONL synthetic confirmations, or interact through stdin')
        if name == 'report':
            child.add_argument('--out', type=Path)
    child = sub.add_parser('artifact')
    child.add_argument('sha256')
    child.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    flow = None
    try:
        with Journal(output_path(args.store)) as journal:
            try:
                if args.command in {'demo', 'create'}:
                    flow = workflow.create(journal, args.profile, args.run_id)
                    if args.command == 'demo':
                        run_demo(flow, args.pause_after_intent)
                    print(json.dumps(work_card(flow), ensure_ascii=False))
                elif args.command == 'session':
                    flow = workflow.open(journal, args.run_id, resume=args.resume)
                    session(flow, args.actions)
                elif args.command == 'artifact':
                    file = output_path(args.out)
                    file.write_bytes(journal.artifact(args.sha256))
                    print(json.dumps({'artifact': str(file), 'sha256': args.sha256}))
                else:
                    flow = workflow(journal, args.run_id, None)
                    if args.command == 'status':
                        print(json.dumps(work_card(flow), ensure_ascii=False))
                    else:
                        file = output_path(args.out or journal.path.parent / args.run_id / 'report.json')
                        report = flow.report()
                        file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                        print(json.dumps({'report': str(file), 'passed': report['passed']}))
            finally:
                if flow is not None:
                    flow.close()
    except (TaskError, ValueError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0
