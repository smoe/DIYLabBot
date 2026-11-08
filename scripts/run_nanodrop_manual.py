"""Run a purely synthetic NanoDrop task; all persistent output stays in exports/."""
import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path

from manual_tasks import Journal, TaskError
from nanodrop_manual import ROOT, SOURCE, Workflow, inventory_observations

DEFAULT_STORE = ROOT / 'exports/manual-workflows/nanodrop.sqlite3'
DEMO_ACTOR = 'SYN.Operator01'


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
            'active_blank': state['active_blank'],
            'pending_measurement': state['pending_measurement'],
            'planned_measurements': state['planned_measurements'],
            'samples': flow.report()['samples'], 'resources': state['resources'],
            'imports': {key: {k: r[k] for k in ['file_name', 'status', 'issues']}
                        for key, r in state['imports'].items()}}


def synthetic_report(state):
    """Fictitious report in intentionally reversed measurement order."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['Application:', state['definition']['protocol']['method']])
    writer.writerow(['Serial Number:', state['definition']['profile']['instrument']['serial_number']])
    writer.writerow(['Sample Name', 'ng/µL', 'A260/A280', 'A260/A230', 'A260', 'Factor', 'Warnings'])
    for index, name in enumerate(reversed(list(state['planned_measurements'].values())), 1):
        writer.writerow([name, 20 + index, 1.8, 2.0, 0.4 + index / 100, 50, 'SYNTHETIC TEST DATA'])
    return stream.getvalue().encode('utf-8')


def run_demo(flow, pause_after_intent=False):
    """Only this explicit demo manufactures positive SYNTHETIC observations."""
    actor = DEMO_ACTOR
    flow.act('rack_ready', actor, observations=inventory_observations(flow.state))
    flow.act('workspace_clear', actor, confirmed=True)
    flow.act('claim', actor)
    flow.act('blank', actor, reference_id='SYN.Blank.Buffer01', cleaned=True)
    for sample_id, sample in flow.state['samples'].items():
        flow.act('take', actor, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=sample['location']['rack_id'], place_id=sample['original_place_id'])
        flow.act('begin_measurement', actor, sample_id=sample_id,
                 measurement_id=flow.state['planned_measurements'][sample_id])
        if pause_after_intent:
            return
        flow.act('confirm_measurement', actor,
                 intent_id=flow.state['pending_measurement']['intent_id'],
                 observed_sample_id=sample_id,
                 volume_ul=flow.state['definition']['profile']['parameters']['sample_volume_ul'],
                 cleaned=True)
        flow.act('place', actor, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=flow.state['definition']['profile']['rack']['id'],
                 place_id=sample['original_place_id'])
    content = synthetic_report(flow.state)
    file = output_path(flow.journal.path.parent / flow.run_id / 'synthetic-report.csv')
    file.write_bytes(content)
    flow.import_file(file, actor)
    flow.act('review_results', actor, decision='accepted', reason='Explicit synthetic demo decision; no real QC qualification')
    flow.act('release', actor, workspace_clear=True)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['demo', 'create']:
        child = sub.add_parser(name)
        child.add_argument('--profile', type=Path, default=SOURCE)
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
                    flow = Workflow.create(journal, args.profile, args.run_id)
                    if args.command == 'demo':
                        run_demo(flow, args.pause_after_intent)
                    print(json.dumps(work_card(flow), ensure_ascii=False))
                elif args.command == 'session':
                    flow = Workflow.open(journal, args.run_id, resume=args.resume)
                    session(flow, args.actions)
                elif args.command == 'artifact':
                    file = output_path(args.out)
                    file.write_bytes(journal.artifact(args.sha256))
                    print(json.dumps({'artifact': str(file), 'sha256': args.sha256}))
                else:
                    flow = Workflow(journal, args.run_id, None)
                    if args.command == 'status':
                        print(json.dumps(work_card(flow), ensure_ascii=False))
                    else:
                        file = output_path(args.out or journal.path.parent / args.run_id / 'report.json')
                        file.write_text(json.dumps(flow.report(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                        print(json.dumps({'report': str(file), 'passed': flow.report()['passed']}))
            finally:
                if flow is not None:
                    flow.close()
    except (TaskError, ValueError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
