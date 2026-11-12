"""Demonstrate synthetic material bookkeeping; never run a biochemical protocol.

The demo invents 100,000 cells per input, one issued 100-uL reagent aliquot,
5-uL reagent consumption, 30-uL products, unknown byproducts and 2-uL product
QC withdrawals. These are fixture observations, not recipes, measured yields,
or promises about extraction/CUT&RUN performance. Existing E1 steps are not run.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import uuid

from manual_tasks import Journal, TaskError
from manual_workflow import ROOT, resolve_store
from manual_workflow_cli import output_path
from material_workflow import MaterialWorkflow
from material_workflow_sources import PREPARATIONS

ACTOR = 'SYN.MaterialDemo.Operator'
FIXTURE_REASON = 'Invented fixture observation only; no biochemical operation or yield measurement occurred.'


def amount(value, unit='uL'):
    return {'value': value, 'unit': unit}


def fixture_declarations(domain, run_id):
    """Create explicit demo inputs; neither compiler invents these quantities."""
    if domain not in PREPARATIONS:
        raise TaskError('Explicit cutrun or extraction domain required')
    plan = PREPARATIONS[domain].compile_plan()
    materials, products, vessel_ids = [], [], set()
    if domain == 'cutrun':
        for branch in plan['branches']:
            materials.append({'id': branch['input_material_id'],
                'kind': 'sample' if branch['role'] == 'reference' else 'control',
                'vessel_id': branch['vessels']['input'], 'quantity': amount(100000, 'cells'),
                'origin_id': branch['id']})
            products.append({'input_id': branch['input_material_id'],
                'product_id': branch['product_material_id'], 'product_vessel_id': branch['vessels']['product'],
                'role': 'dna_product'})
            vessel_ids.update(branch['vessels'].values())
        vessel_ids.add(plan['qc']['ntc']['vessel_id'])
    else:
        for pair in plan['sample_pairs']:
            for analyte, process in pair['processes'].items():
                edge = process['lineage']
                materials.append({'id': edge['input_id'], 'kind': 'sample',
                    'vessel_id': edge['input_vessel_id'], 'quantity': amount(100000, 'cells'),
                    'origin_id': edge['origin_id']})
                products.append({'input_id': edge['input_id'], 'product_id': edge['product_id'],
                    'product_vessel_id': edge['product_vessel_id'], 'role': analyte + '_product'})
                vessel_ids.update(item['instance_id'] for item in process['item_bindings'].values())
    reagent_id, reagent_vessel = run_id + '.IssuedReagent', run_id + '.IssuedReagentTube'
    materials.append({'id': reagent_id, 'kind': 'reagent', 'vessel_id': reagent_vessel,
                      'quantity': amount(100), 'origin_id': run_id + '.FixtureIssue'})
    vessel_ids.add(reagent_vessel)
    for index, product in enumerate(products, 1):
        product['byproduct_id'] = run_id + '.Byproduct%02d' % index
        product['byproduct_vessel_id'] = run_id + '.ByproductTube%02d' % index
        vessel_ids.add(product['byproduct_vessel_id'])
    vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': run_id + '.FixtureRack',
               'place_id': 'P%03d' % index}} for index, identity in enumerate(sorted(vessel_ids), 1)]
    return materials, vessels, products, reagent_id


def run_demo(journal, domain, run_id=None):
    """Persist and confirm generic material primitives, not the E1 phase chain."""
    identity = run_id or 'SYN.MATERIAL.DEMO.' + domain + '.' + uuid.uuid4().hex[:12]
    materials, vessels, products, reagent_id = fixture_declarations(domain, identity)
    flow = MaterialWorkflow.create(journal, domain, materials=materials, vessels=vessels, run_id=identity)
    flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
    flow.act('workspace_clear', ACTOR, confirmed=True)
    flow.act('claim', ACTOR)
    for index, product in enumerate(products, 1):
        intent = identity + '.Transform%02d' % index
        inputs = [{'material_id': product['input_id'], 'quantity': amount(100000, 'cells'), 'consume_all': True},
                  {'material_id': reagent_id, 'quantity': amount(5), 'consume_all': False}]
        outputs = [{'material_id': product['product_id'], 'kind': 'product',
                    'vessel_id': product['product_vessel_id'], 'role': product['role']},
                   {'material_id': product['byproduct_id'], 'kind': 'byproduct',
                    'vessel_id': product['byproduct_vessel_id'], 'role': 'unknown_fixture_byproduct'}]
        flow.act('begin_effect', ACTOR, intent_id=intent, kind='transformation', inputs=inputs,
                 outputs=outputs, purpose='invented_fixture_material_transformation_not_biochemistry')
        flow.act('confirm_effect', ACTOR, intent_id=intent,
                 actual_inputs=[{'material_id': item['material_id'], 'quantity': item['quantity']} for item in inputs],
                 actual_outputs=[{'material_id': product['product_id'], 'quantity': amount(30)},
                                 {'material_id': product['byproduct_id'], 'quantity': amount(None)}],
                 reason=FIXTURE_REASON)
        intent = identity + '.ProductQC%02d' % index
        flow.act('begin_effect', ACTOR, intent_id=intent, kind='withdrawal',
                 inputs=[{'material_id': product['product_id'], 'quantity': amount(2), 'consume_all': False}],
                 outputs=[], purpose='invented_fixture_product_qc_withdrawal_no_analytical_assay')
        flow.act('confirm_effect', ACTOR, intent_id=intent,
                 actual_inputs=[{'material_id': product['product_id'], 'quantity': amount(2)}],
                 actual_outputs=[], reason=FIXTURE_REASON)
    for material_id, material in flow.state['inventory']['materials'].items():
        if material['disposition'] != 'consumed':
            flow.act('set_disposition', ACTOR, material_id=material_id, disposition='retained', reason=FIXTURE_REASON)
    flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
    flow.act('release', ACTOR, workspace_clear=True)
    return flow.report()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TaskError(message)


def runtime_path(value):
    """Reuse the shared output policy, including its resolved project boundary."""
    directory = (ROOT / 'exports').resolve()
    path = Path(value).resolve()
    if not directory.is_relative_to(ROOT.resolve()) or not path.is_relative_to(directory) or path == directory:
        raise TaskError('Runtime output must be inside this project exports/ directory')
    return output_path(path)


def report_path(value):
    path = Path(value).resolve()
    if path.suffix != '.json':
        raise TaskError('Material report output must be a new JSON file under exports/')
    path = runtime_path(path)
    if path.exists():
        raise TaskError('Material report output already exists; existing artifacts are preserved')
    return path


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--store', type=Path, help='Shared task-journal store; an explicit path must remain under exports/')
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    demo = sub.add_parser('demo', help='Invent and journal one explicitly synthetic material fixture')
    demo.add_argument('--domain', choices=sorted(PREPARATIONS), required=True)
    demo.add_argument('--run-id')
    demo.add_argument('--out', type=Path)
    report = sub.add_parser('report', help='Read and fully audit a stored material report')
    report.add_argument('run_id');report.add_argument('--out', type=Path)
    status = sub.add_parser('status', help='Read a compact material status without taking over its session')
    status.add_argument('run_id')
    try:
        args = parser.parse_args(argv)
        target = report_path(args.out) if getattr(args, 'out', None) is not None else None
        store = runtime_path(resolve_store(args.store))
        if target == store:
            raise TaskError('A report must not overwrite the task-journal store')
        if args.command != 'demo' and not store.is_file():
            raise TaskError('An existing material journal is required for report/status')
        with Journal(store) as journal:
            if args.command == 'demo':
                result = run_demo(journal, args.domain, args.run_id)
            else:
                # Constructing this read-only view does not open/resume a session.
                result = MaterialWorkflow(journal, args.run_id, None).report()
                if args.command == 'status':
                    result = {key: result[key] for key in ('run_id', 'domain', 'mode', 'status', 'passed',
                        'pending_operation', 'resources', 'recovery_required', 'biochemical_protocol_executed')}
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
