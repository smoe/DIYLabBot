"""Journal an entirely synthetic SK-Mel-29/H3K4me3 CUT&RUN process.

The demo emits invented observations, including quantities, temperature spans
and QC artifacts. It neither operates laboratory equipment nor reconstructs a
qualified SOP. Status/report are read-only; resume requires explicit time and
inventory reconciliation before ordinary phase work.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from cutrun_workflow import CutRunWorkflow
from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store
from run_material_lifecycle import Parser, report_path, runtime_path

ACTOR = 'SYN.CutRun.Operator'
REASON = 'Invented in-silico observation; no real biochemical operation, yield or measurement.'


def output_observations(state, intent_id):
    """Explicit demo fixture input, never called by the runtime validator."""
    booking = state['bookings'].get(intent_id)
    if not booking or not booking['request']['outputs']:
        return []
    operation = state['process']['operations'][intent_id]['operation']
    keys_by_phase = {'prepare_cells': ['reaction'], 'prepare_input': ['reaction'],
                     'isolate_product': ['supernatant', 'bead_remainder'],
                     'clarify_input': ['supernatant', 'bead_remainder'],
                     'bind_column': ['column', None], 'elute': ['eluate', 'residue']}
    volumes = state['definition']['execution']['bookkeeping_volumes_ul']
    return [{'material_id': output['material_id'],
             'quantity': {'value': None if key is None else volumes[key], 'unit': 'uL'}}
            for output, key in zip(booking['request']['outputs'], keys_by_phase[operation])]


def perform_phase(flow, branch_id):
    """Advance exactly one phase using explicit synthetic fixture observations."""
    state = flow.state
    branch = state['process']['branches'][branch_id]
    plan = next(item for item in state['definition']['preparation_plan']['branches'] if item['id'] == branch_id)
    step = plan['steps'][branch['cursor']]
    phase = step['operation']
    reaction_id = branch['reaction_id']
    intent_id = flow.run_id + '.' + branch_id.rsplit('.', 1)[-1] + '.' + phase
    if phase == 'stop_reaction':
        start = branch['activation']['contact']['max_s']
        digest = next(item for item in plan['steps'] if item['operation'] == 'activate_digest')['parameters']['duration_s']['value']
        wait = start + digest - state['logical_time_s']
        if wait > 0:
            flow.act('advance_time', ACTOR, seconds=wait)
        flow.act('begin_stop', ACTOR, branch_id=branch_id, reaction_id=reaction_id,
                 intent_id=intent_id, access=True, mixing_available=True)
        flow.act('advance_time', ACTOR, seconds=state['definition']['execution']['stop_service_s'])
        flow.act('observe_temperature', ACTOR, branch_id=branch_id, reaction_id=reaction_id,
                 start_s=branch['activation']['contact']['min_s'], end_s=flow.state['logical_time_s'],
                 temperature_deg_c=step['parameters']['temperature_deg_c']['value'])
        flow.act('confirm_stop', ACTOR, intent_id=intent_id, reaction_id=reaction_id,
                 actual_volume_ul=step['parameters']['volume_ul']['value'], mixed=True, reason=REASON)
        return
    if phase == 'activate_digest':
        flow.act('confirm_stop_readiness', ACTOR, branch_id=branch_id, reaction_id=reaction_id,
                 access=True, mixing_available=True)
    flow.act('begin_phase', ACTOR, branch_id=branch_id, reaction_id=reaction_id, operation=phase, intent_id=intent_id)
    started = flow.state['logical_time_s']
    duration = (state['definition']['execution']['activation_service_s'] if phase == 'activate_digest'
                else step['parameters'].get('duration_s', {}).get('value', 0))
    if duration:
        flow.act('advance_time', ACTOR, seconds=duration)
    if 'temperature_deg_c' in step['parameters'] and duration:
        flow.act('observe_temperature', ACTOR, branch_id=branch_id, reaction_id=reaction_id,
                 start_s=started, end_s=flow.state['logical_time_s'],
                 temperature_deg_c=step['parameters']['temperature_deg_c']['value'])
    if phase == 'activate_digest':
        observations = {'dose_ul': step['parameters']['volume_ul']['value'], 'mixed': True}
    else:
        observations = {'completed': True}
        if phase == 'isolate_product':
            observations['cleared'] = True
        if phase == 'check_input_size':
            observations['fragment_size_bp'] = 500
        outputs = output_observations(flow.state, intent_id)
        if outputs:
            observations['outputs'] = outputs
    flow.act('confirm_phase', ACTOR, intent_id=intent_id, reaction_id=reaction_id,
             observations=observations, reason=REASON)


def qc_record(flow, branch_id, method, *, below_detection_limit=False):
    state = flow.state
    plan = next((item for item in state['definition']['preparation_plan']['branches'] if item['id'] == branch_id), None)
    return {'run_id': state['run_id'], 'attempt_id': state['attempt_id'], 'branch_id': branch_id,
            'reaction_id': state['process']['branches'][branch_id]['reaction_id'] if plan else state['attempt_id'] + '.NTC',
            'material_id': plan['product_material_id'] if plan else None,
            'method': method, 'stage': 'purified_dna' if plan else 'pcr_no_template_control',
            'value': None if below_detection_limit else 2.5 if method == 'fluorometry' else 24.0,
            'unit': 'ng/uL' if method == 'fluorometry' else 'Cq', 'below_detection_limit': below_detection_limit}


def run_demo(journal, run_id=None, source=None):
    flow = CutRunWorkflow.create(journal, source=source, run_id=run_id)
    flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
    flow.act('workspace_clear', ACTOR, confirmed=True)
    flow.act('claim', ACTOR)
    for plan in flow.state['definition']['preparation_plan']['branches']:
        branch_id = plan['id']
        while flow.state['process']['branches'][branch_id]['cursor'] < len(plan['steps']):
            perform_phase(flow, branch_id)
        reaction_id = flow.state['process']['branches'][branch_id]['reaction_id']
        for method in flow.state['definition']['preparation_plan']['qc']['methods']:
            intent_id = flow.run_id + '.' + branch_id.rsplit('.', 1)[-1] + '.QC.' + method
            flow.act('begin_qc', ACTOR, branch_id=branch_id, reaction_id=reaction_id, intent_id=intent_id, method=method)
            volume = flow.state['definition']['preparation_plan']['qc']['aliquot_volumes_ul'][method]['value']
            flow.act('confirm_qc_withdrawal', ACTOR, intent_id=intent_id, reaction_id=reaction_id,
                     actual_volume_ul=volume, reason=REASON)
            flow.act('import_qc', ACTOR, artifact=json.dumps(qc_record(flow, branch_id, method), allow_nan=False).encode(),
                     file_name=branch_id + '.' + method + '.json')
    ntc_id = flow.state['definition']['preparation_plan']['qc']['ntc']['id']
    flow.act('import_qc', ACTOR, artifact=json.dumps(qc_record(flow, ntc_id, 'qpcr', below_detection_limit=True)).encode(), file_name='ntc.json')
    flow.act('review_qc', ACTOR, reason=REASON)
    for material_id, item in flow.state['inventory']['materials'].items():
        if item['disposition'] != 'consumed':
            flow.act('set_disposition', ACTOR, material_id=material_id, disposition='retained', reason=REASON)
    flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
    flow.act('release', ACTOR, workspace_clear=True)
    return flow.report()


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--store', type=Path)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    demo = sub.add_parser('demo'); demo.add_argument('--run-id'); demo.add_argument('--source', type=Path); demo.add_argument('--out', type=Path)
    for command in ('status', 'report', 'resume', 'act'):
        item = sub.add_parser(command)
        item.add_argument('run_id'); item.add_argument('--out', type=Path)
        if command == 'act':
            item.add_argument('--session', required=True)
            item.add_argument('--actor', required=True)
            item.add_argument('--action', required=True)
            item.add_argument('--data', default='{}', help='JSON observation arguments')
            item.add_argument('--artifact', type=Path)
    try:
        args = parser.parse_args(argv)
        target = report_path(args.out) if args.out else None
        store = runtime_path(resolve_store(args.store))
        if target == store:
            raise TaskError('Report must not overwrite the journal')
        if args.command != 'demo' and not store.is_file():
            raise TaskError('An existing journal is required')
        with Journal(store) as journal:
            if args.command == 'demo':
                result = run_demo(journal, args.run_id, args.source)
            elif args.command == 'resume':
                flow = CutRunWorkflow.open(journal, args.run_id, resume=True)
                result = {'run_id': args.run_id, 'session': flow.session, 'state': flow.state}
            elif args.command == 'act':
                data = json.loads(args.data)
                if not isinstance(data, dict):
                    raise TaskError('Action data must be a JSON object')
                artifact = None if args.artifact is None else args.artifact.read_bytes()
                flow = CutRunWorkflow(journal, args.run_id, args.session)
                result = flow.act(args.action, args.actor, artifact=artifact, **data)
            else:
                result = CutRunWorkflow(journal, args.run_id, None).report()
                if args.command == 'status':
                    result = {key: result[key] for key in ('run_id', 'attempt_id', 'mode', 'status', 'passed',
                        'pending_operation', 'protective_operations', 'recovery_required', 'clock', 'process')}
        content = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if target is not None:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(content)
        print(content, end='')
        return 0
    except (TaskError, ValueError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
