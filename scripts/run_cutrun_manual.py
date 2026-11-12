"""Prepare/read manual E4 records; no device commands or synthetic time advance."""
import json
from pathlib import Path
import sqlite3

from cutrun_manual_sources import compile_profile
from cutrun_manual_workflow import CutRunManualWorkflow
from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store
from run_material_lifecycle import Parser, runtime_path, report_path


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--store', type=Path)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    prepare = sub.add_parser('prepare', help='Read-only SOP binding/readiness report; does not create a store')
    prepare.add_argument('--profile', type=Path);prepare.add_argument('--original-pdf', type=Path)
    prepare.add_argument('--evidence-manifest', type=Path);prepare.add_argument('--out', type=Path)
    create = sub.add_parser('create', help='Create a manual capture with explicit actual identities')
    create.add_argument('--profile', type=Path);create.add_argument('--inventory', type=Path, required=True)
    create.add_argument('--original-pdf', type=Path);create.add_argument('--evidence-manifest', type=Path)
    create.add_argument('--run-id');create.add_argument('--out', type=Path)
    for name in ('status', 'report', 'resume', 'act'):
        item = sub.add_parser(name);item.add_argument('run_id');item.add_argument('--out', type=Path)
        if name == 'act':
            item.add_argument('--session', required=True);item.add_argument('--actor', required=True)
            item.add_argument('--action', required=True);item.add_argument('--observation', type=Path, required=True)
            item.add_argument('--data', default='{}');item.add_argument('--artifact', type=Path)
    try:
        args = parser.parse_args(argv)
        target = report_path(args.out) if args.out else None
        if args.command == 'prepare':
            evidence = read_json(args.evidence_manifest) if args.evidence_manifest else None
            result = compile_profile(args.profile, original_pdf=args.original_pdf, evidence_files=evidence)
            result.pop('evidence_artifacts')
        else:
            store = runtime_path(resolve_store(args.store))
            if target == store:
                raise TaskError('Report must not overwrite the journal')
            if args.command != 'create' and not store.is_file():
                raise TaskError('Existing manual journal required')
            with Journal(store) as journal:
                if args.command == 'create':
                    inventory = read_json(args.inventory)
                    if not isinstance(inventory, dict) or set(inventory) != {'materials', 'vessels', 'reactions', 'actors'}:
                        raise TaskError('Explicit materials, vessels, reactions and attributable actors required')
                    evidence = read_json(args.evidence_manifest) if args.evidence_manifest else None
                    flow = CutRunManualWorkflow.create(journal, args.profile, **inventory,
                        original_pdf=args.original_pdf, evidence_files=evidence, run_id=args.run_id)
                    result = {'run_id': flow.run_id, 'session': flow.session, 'state': flow.state}
                elif args.command == 'resume':
                    flow = CutRunManualWorkflow.open(journal, args.run_id, resume=True)
                    result = {'run_id': flow.run_id, 'session': flow.session, 'state': flow.state}
                elif args.command == 'act':
                    data = json.loads(args.data)
                    if not isinstance(data, dict):
                        raise TaskError('Action data must be a JSON object')
                    artifact = None if args.artifact is None else args.artifact.read_bytes()
                    flow = CutRunManualWorkflow(journal, args.run_id, args.session)
                    result = flow.act(args.action, args.actor, observation=read_json(args.observation), artifact=artifact, **data)
                else:
                    result = CutRunManualWorkflow(journal, args.run_id, None).report()
                    if args.command == 'status':
                        result = {key: result[key] for key in ('run_id', 'mode', 'status', 'capture_completed',
                            'reference_success', 'recovery_required', 'clock', 'current_clock_estimate',
                            'current_clock_estimate_is_uncommitted', 'open_requirements', 'stage_readiness')}
        content = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if target is not None:
            with target.open('x', encoding='utf-8') as stream:stream.write(content)
        print(content, end='')
        return 0
    except (TaskError, ValueError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
