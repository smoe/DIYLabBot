"""Record consolidated CUT&RUN recipe /2 observations on the shared manual journal."""

import json
from pathlib import Path
import sqlite3

from cutrun_input_sonication_workflow import SnapshotClock
from cutrun_manual_recipe_v2_sources import compile_profile
from cutrun_manual_recipe_v2_workflow import CutRunManualRecipeV2
from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store
from run_cutrun_manual import Parser, read_json, report_path, runtime_path


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--store', type=Path)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('prepare', 'create', 'status', 'report', 'resume', 'act'):
        command = commands.add_parser(name)
        command.add_argument('--out', type=Path)
        if name in {'prepare', 'create'}:
            command.add_argument('--profile', type=Path)
            command.add_argument('--sop-profile', type=Path)
            command.add_argument('--recipe-profile', type=Path)
            command.add_argument('--input-profile', type=Path)
            command.add_argument('--original-pdf', type=Path)
            command.add_argument('--evidence-manifest', type=Path)
        else:
            command.add_argument('run_id')
        if name in {'create', 'resume', 'act'}:
            command.add_argument('--test-clock', type=Path, help='Explicit clock observation for a fixture run')
        if name == 'create':
            command.add_argument('--inventory', type=Path, required=True)
            command.add_argument('--run-id')
        if name == 'act':
            command.add_argument('--session', required=True)
            command.add_argument('--actor', required=True)
            command.add_argument('--action', required=True)
            command.add_argument('--observation', type=Path, required=True)
            command.add_argument('--data', default='{}')
            command.add_argument('--artifact', type=Path)
    try:
        args = parser.parse_args(argv)
        target = report_path(args.out) if args.out else None
        result = execute(args, target)
        content = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if target is not None:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(content)
        print(content, end='')
        return 0
    except (TaskError, ValueError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


def execute(args, target):
    if args.command in {'prepare', 'create'}:
        selected = {'base_profile': args.profile, 'sop_profile': args.sop_profile,
                    'recipe_profile': args.recipe_profile, 'input_profile': args.input_profile}
        evidence = read_json(args.evidence_manifest) if args.evidence_manifest else None
        if args.command == 'prepare':
            result = compile_profile(selected, original_pdf=args.original_pdf, evidence_files=evidence)
            result.pop('evidence_artifacts')
            return result
    store = runtime_path(resolve_store(args.store))
    if target == store:
        raise TaskError('Report must not overwrite the journal')
    if args.command != 'create' and not store.is_file():
        raise TaskError('Existing manual journal required')
    file = getattr(args, 'test_clock', None)
    clock = None
    if file:
        sample = read_json(file)
        if not isinstance(sample, dict) or sample.get('source_kind') != 'test_clock':
            raise TaskError('--test-clock requires an explicitly identified test clock observation')
        clock = SnapshotClock(sample)
    with Journal(store) as journal:
        if args.command == 'create':
            inventory = read_json(args.inventory)
            if not isinstance(inventory, dict) or set(inventory) != {'materials', 'vessels', 'reactions', 'actors'}:
                raise TaskError('Explicit materials, vessels, reactions and attributable actors required')
            flow = CutRunManualRecipeV2.create(journal, selected, **inventory, run_id=args.run_id,
                clock=clock, original_pdf=args.original_pdf, evidence_files=evidence)
            return {'run_id': flow.run_id, 'session': flow.session, 'state': flow.state}
        if args.command == 'resume':
            flow = CutRunManualRecipeV2.open(journal, args.run_id, resume=True, clock=clock)
            return {'run_id': flow.run_id, 'session': flow.session, 'state': flow.state}
        if args.command == 'act':
            data = json.loads(args.data)
            if not isinstance(data, dict):
                raise TaskError('Action data must be a JSON object')
            flow = CutRunManualRecipeV2(journal, args.run_id, args.session, clock=clock)
            return flow.act(args.action, args.actor, observation=read_json(args.observation),
                            artifact=args.artifact.read_bytes() if args.artifact else None, **data)
        result = CutRunManualRecipeV2(journal, args.run_id, None).report()
        if args.command == 'status':
            return {key: result[key] for key in ('run_id', 'mode', 'status', 'capture_completed',
                'recovery_required', 'execution_ready', 'stage_readiness', 'open_requirements', 'clock')}
        return result


if __name__ == '__main__':
    raise SystemExit(main())
