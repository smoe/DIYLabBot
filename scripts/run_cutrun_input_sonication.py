"""Prepare and demonstrate the test-only S09 sonication adapter; no devices."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from cutrun_input_sonication_sources import compile_profile
from cutrun_input_sonication_workflow import InputSonicationWorkflow
from cutrun_input_sonication_demo import FixtureClock, FixtureSession, run_scenarios, validate_run_id
from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store

ROOT = Path(__file__).resolve().parents[1]


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TaskError(message)


def private_path(value):
    path = Path(value).resolve()
    exports = (ROOT / 'exports').resolve()
    if path == exports or not exports.is_relative_to(ROOT) or not path.is_relative_to(exports):
        raise TaskError('Fixture paths must stay inside this project exports/')
    return path


def write_new(path, value):
    path = private_path(path)
    if path.suffix != '.json':
        raise TaskError('A new JSON output file is required')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def check_output_parents(path):
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise TaskError('Output parent must be a directory: ' + str(parent))


def check_new_json(value):
    path = private_path(value)
    if path.suffix != '.json' or path.exists():
        raise TaskError('Choose a new JSON output inside exports/; existing files are preserved')
    check_output_parents(path)
    return path


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--store', type=Path)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    prepare = sub.add_parser('prepare');prepare.add_argument('--out', type=Path)
    prepare.add_argument('--require-complete', action='store_true')
    demo = sub.add_parser('demo', help='Three independent synthetic fixtures, including SIGKILL recovery')
    demo.add_argument('--directory', type=Path, required=True)
    demo.add_argument('--evidence-directory', type=Path)
    demo.add_argument('--render', action='store_true')
    demo.add_argument('--test-log', action='append', type=Path, default=[])
    begin = sub.add_parser('fixture-intent', help='Create an explicit fixture and persist its intent for process tests')
    begin.add_argument('--directory', type=Path, required=True);begin.add_argument('--run-id', required=True)
    begin.add_argument('--scenario-id', choices=['normal','restart','cancel'], default='normal')
    begin.add_argument('--wait', action='store_true')
    for name in ('status','report','resume','act'):
        command = sub.add_parser(name);command.add_argument('run_id');command.add_argument('--out', type=Path)
        if name in ('resume','act'):command.add_argument('--clock', type=Path, required=True)
        if name == 'act':
            command.add_argument('--session', required=True);command.add_argument('--actor', required=True)
            command.add_argument('--action', required=True);command.add_argument('--observation', type=Path, required=True)
            command.add_argument('--data', default='{}');command.add_argument('--artifact', type=Path)
    try:
        args = parser.parse_args(argv)
        if args.command == 'fixture-intent':
            validate_run_id(args.run_id)
        if getattr(args, 'out', None):
            check_new_json(args.out)
        if args.command == 'prepare':
            result = compile_profile()
            # Initial artifact bytes are intentionally not printed as JSON.
            result.pop('evidence_artifacts', None)
            if args.out:write_new(args.out, result)
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
            return 2 if args.require_complete and not result['synthetic_gate_readiness']['S09'] else 0
        if args.command == 'demo' and args.render and args.evidence_directory is None:
            raise TaskError('--render requires a new --evidence-directory')
        if args.command == 'demo':
            if args.evidence_directory is not None:
                evidence = private_path(args.evidence_directory)
                if (evidence.exists() or evidence == (ROOT/'exports/sonication-evidence').resolve()
                        or not evidence.is_relative_to((ROOT/'exports/sonication-evidence').resolve())):
                    raise TaskError('Choose a new evidence bundle under exports/sonication-evidence/')
                check_output_parents(evidence)
            if len({path.name for path in args.test_log}) != len(args.test_log) or any(not path.is_file() for path in args.test_log):
                raise TaskError('Test logs must be existing files with unique names')
        store = resolve_store(args.store)
        if args.store is not None:private_path(store)
        if args.command in ('demo','fixture-intent'):
            directory = private_path(args.directory)
            if directory.exists():raise TaskError('Choose a new fixture directory; existing fixtures are never reset')
            check_output_parents(directory)
        with Journal(store) as journal:
            if args.command == 'demo':
                scenarios = run_scenarios(journal, directory, store)
                result = {'mode': 'test_fixture_only', 'store': str(store),
                    'scenarios': [{'scenario_id': item['scenario_id'], 'run_id': item['run_id'],
                                   'status': item['report']['status']} for item in scenarios],
                    'hardware_executed': False, 'network_executed': False, 'ros_executed': False}
                if args.evidence_directory:
                    from sonication_evidence import export_bundle
                    inputs = export_bundle(journal, scenarios, private_path(args.evidence_directory),
                        test_logs={path.name:path for path in args.test_log})
                    result['evidence_input'] = str(inputs)
                    if args.render:
                        from render_sonication_evidence import render
                        result['manifest'] = str(render(inputs))
            elif args.command == 'fixture-intent':
                fixture = FixtureSession(journal, args.run_id, directory, args.scenario_id)
                fixture.prepare_input();fixture.begin()
                print(json.dumps({'run_id': args.run_id, 'intent_persisted': True,
                                  'sequence': fixture._last_sequence}), flush=True)
                if args.wait:sys.stdin.buffer.read(1)
                return 0
            elif args.command in ('status','report'):
                state = journal.state(args.run_id)[0]
                InputSonicationWorkflow._validate_format(state)
                flow = InputSonicationWorkflow(journal, args.run_id, None)
                result = flow.report() if args.command == 'report' else {
                    'run_id': args.run_id, 'status': state['status'], 'resources': state['resources'],
                    'recovery_required': state['recovery_required'], 'mode': 'test_fixture_only'}
            else:
                clock = FixtureClock(record=json.loads(args.clock.read_bytes()))
                if args.command == 'resume':
                    flow = InputSonicationWorkflow.open(journal, args.run_id, resume=True, clock=clock)
                    result = {'run_id': args.run_id, 'session': flow.session, 'recovery_required': flow.state['recovery_required']}
                else:
                    flow = InputSonicationWorkflow(journal, args.run_id, args.session, clock=clock)
                    result = flow.act(args.action, args.actor,
                        observation=json.loads(args.observation.read_bytes()),
                        artifact=None if args.artifact is None else args.artifact.read_bytes(),
                        **json.loads(args.data))
            if getattr(args,'out',None):write_new(args.out,result)
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (TaskError, OSError, ValueError, TypeError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
