"""CLI and full-flow acceptance of explicitly synthetic DNeasy/TapeStation data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dneasy_extraction_sources import load
from dneasy_extraction_workflow import DNeasyWorkflow
from dneasy_extraction_demo import ACTOR, REASON, actual_inputs, perform_phase, phase_observations
from manual_tasks import Journal, TaskError
import material_ledger as ledger


class DNeasyExtractionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dneasy-cli-acceptance-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'workflows.sqlite3'

    def command(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_dneasy_extraction.py'),
                                 '--store', str(self.store), *args], cwd=ROOT, capture_output=True,
                                text=True, timeout=180)
        self.assertEqual(result.returncode, code, result.stderr[-8000:] or result.stdout[:2000])
        return json.loads(result.stdout)

    def test_full_cli_preserves_eluate_lineage_consumption_and_raw_qc(self):
        run = 'SYN.DNeasy.CLI.Full'
        report = self.command('demo', '--run-id', run)
        self.assertTrue(report['passed'])
        self.assertEqual(report['status'], 'completed')
        self.assertTrue(report['synthetic_extraction_sequence_executed'])
        for flag in ('hardware_executed', 'network_executed', 'biochemical_protocol_executed',
                     'sop_qualified', 'fragment_size_qualified', 'safety_function_qualified'):
            self.assertIs(report[flag], False, flag)
        definition = load()
        sample = definition['execution']['samples']['DNA01']
        product = sample['product_material_id']
        inventory = report['inventory']['materials']
        self.assertNotIn('SYN.Source01.RNAAliquot', inventory)
        self.assertEqual(inventory[product]['vessel_id'], sample['elution_vessel_id'])
        self.assertEqual(inventory[product]['disposition'], 'retained')
        self.assertEqual(report['remaining'][product]['value'], 199)
        self.assertEqual(report['remaining'][product]['unit'], 'uL')
        ancestors = set()
        def visit(identity):
            for parent in inventory[identity]['parents']:
                if parent not in ancestors:
                    ancestors.add(parent); visit(parent)
        visit(product)
        self.assertIn(sample['input_material_id'], ancestors)
        qc = definition['execution']['qc']
        ladder = qc['ladder']['effect']['outputs'][0]['material_id']
        assay = qc['sample']['effect']['outputs'][0]['material_id']
        self.assertNotIn(product, inventory[ladder]['parents'])
        self.assertIn(product, inventory[assay]['parents'])
        for identity in (ladder, assay):
            self.assertEqual(inventory[identity]['disposition'], 'discarded')
        draws = [item for booking in report['bookings'].values() for item in booking['actual_inputs']
                 if item['material_id'] == product]
        self.assertEqual(draws, [{'material_id': product, 'quantity': {'value': 1.0, 'unit': 'uL'}}])
        self.assertEqual(len(report['imports']), 1)
        with Journal(self.store) as journal:
            history = journal.history(run)
            record = next(iter(report['imports'].values()))
            artifact = journal.artifact(next(iter(report['imports'])))
            original = json.loads(artifact)
            self.assertEqual(original['format'], 'solidcraftbot.synthetic-tapestation-report/1')
            self.assertIsNotNone(record['report'])
            state = journal.state(run)[0]
            self.assertEqual(state['resources'], [])
            self.assertEqual(state['process']['cursor'], len(definition['execution']['steps']))
        status = self.command('status', run)
        self.assertTrue(status['passed'])
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), history)

    def test_create_is_not_a_demo_and_cannot_reintroduce_issued_stock(self):
        run = 'SYN.DNeasy.CLI.Created'
        result = self.command('create', '--run-id', run)
        self.assertEqual(result['state']['status'], 'created')
        self.assertEqual(result['state']['process']['cursor'], 0)
        self.assertEqual(result['state']['bookings'], {})
        with Journal(self.store) as journal:
            before = journal.history(run)
        self.command('create', '--run-id', 'SYN.DNeasy.CLI.Other', code=1)
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), before)
            with self.assertRaises(TaskError):
                journal.state('SYN.DNeasy.CLI.Other')

    def test_deviating_actual_dose_remains_booked_through_controlled_abort(self):
        run = 'SYN.DNeasy.Acceptance.BadDose'
        with Journal(self.store) as journal:
            flow = DNeasyWorkflow.create(journal, run_id=run)
            flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('workspace_clear', ACTOR, confirmed=True)
            flow.act('claim', ACTOR)
            steps = flow.state['definition']['execution']['steps']
            perform_phase(flow, 'DNA01', steps[0])
            step = steps[1]
            flow.act('begin_phase', ACTOR, sample_id='DNA01', phase_id=step['id'], intent_id='BadDose')
            inputs = actual_inputs(flow.state, 'BadDose')
            pbs = flow.state['definition']['execution']['samples']['DNA01']['reagent_bindings']['PBS']
            next(item for item in inputs if item['material_id'] == pbs)['quantity']['value'] = 1
            flow.act('confirm_phase', ACTOR, intent_id='BadDose', actual_inputs=inputs,
                     actual_outputs=step['fixture_actual_outputs'], observations=phase_observations(step), reason=REASON)
            self.assertEqual(ledger.remaining(flow.state, pbs)['value'], 999)
            self.assertEqual(flow.state['bookings']['BadDose']['outcome'], 'performed')
            self.assertTrue(flow.state['process']['deviations'])
            flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
            with self.assertRaises(TaskError):
                perform_phase(flow, 'DNA01', steps[2])
            flow.act('cancel', ACTOR, reason=REASON)
            for identity, item in flow.state['inventory']['materials'].items():
                if item['disposition'] != 'consumed':
                    disposition = 'retained' if item['kind'] == 'reagent' else 'quarantined'
                    flow.act('set_disposition', ACTOR, material_id=identity, disposition=disposition, reason=REASON)
            flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('finish_cancel', ACTOR, workspace_clear=True)
            self.assertEqual(flow.state['status'], 'cancelled')
            self.assertEqual(flow.state['resources'], [])
            self.assertFalse(flow.report()['passed'])
            self.assertEqual(ledger.remaining(flow.state, pbs)['value'], 999)
            flow.close()

    def test_invalid_pause_does_not_introduce_a_fixture_and_reports_do_not_overwrite(self):
        run = 'SYN.DNeasy.CLI.InvalidPause'
        self.command('demo', '--run-id', run, '--pause-after', 'unknown_phase', code=1)
        self.command('create', '--run-id', run)
        target = self.directory / 'preserved.json'
        target.write_bytes(b'original evidence\n')
        with Journal(self.store) as journal:
            before = journal.history(run)
        self.command('report', run, '--out', str(target), code=1)
        self.assertEqual(target.read_bytes(), b'original evidence\n')
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), before)

    def test_cli_restart_retains_unknown_effect_and_reservations(self):
        run = 'SYN.DNeasy.CLI.Restart'
        report = self.command('demo', '--run-id', run, '--pause-after', 'before_confirm:resuspend_pbs')
        self.assertFalse(report['passed'])
        with Journal(self.store) as journal:
            before = journal.state(run)[0]
        intent = before['process']['phase_pending']['intent_id']
        resumed = self.command('resume', run)
        self.assertTrue(resumed['state']['recovery_required'])
        self.assertEqual(resumed['state']['bookings'], before['bookings'])
        session = resumed['session']
        result = self.command('act', run, '--session', session, '--actor', 'SYN.DNeasy.Operator',
                              '--action', 'resolve_effect', '--data', json.dumps({
                                  'intent_id': intent, 'outcome': 'unknown',
                                  'reason': 'Explicit synthetic uncertainty after process interruption'}))
        self.assertEqual(result['bookings'][intent]['outcome'], 'unknown')
        self.assertEqual(result['process']['phase_pending'], {'intent_id': intent})
        self.assertTrue(result['resources'])
        self.command('act', run, '--session', session, '--actor', 'SYN.DNeasy.Operator',
                     '--action', 'begin_phase', '--data', json.dumps({
                         'sample_id': 'DNA01', 'phase_id': 'resuspend_pbs', 'intent_id': 'InventedRetry'}), code=1)
        with Journal(self.store) as journal:
            state = journal.state(run)[0]
        self.assertNotIn('InventedRetry', state['bookings'])
        self.assertEqual(state['bookings'][intent]['outcome'], 'unknown')


if __name__ == '__main__':
    unittest.main()
