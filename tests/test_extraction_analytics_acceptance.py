"""CLI, accounting and process-restart checks for integrated extraction QC."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError
from dneasy_extraction_workflow import DNeasyWorkflow
from puregene_extraction_workflow import PuregeneWorkflow
from extraction_analytics_workflow import ExtractionAnalyticsWorkflow
from extraction_analytics_demo import ACTOR


class ExtractionAnalyticsAcceptanceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='extraction-analytics-cli-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'workflows.sqlite3'

    def command(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_extraction_analytics.py'),
            '--store', str(self.store), *args], cwd=ROOT, capture_output=True,
            text=True, timeout=360)
        self.assertEqual(result.returncode, code, result.stderr[-8000:] or result.stdout[:2000])
        return json.loads(result.stdout)

    def action(self, run_id, session, action, data, code=0):
        return self.command('act', run_id, '--session', session, '--actor', ACTOR,
            '--action', action, '--data', json.dumps(data), code=code)

    def check_completed_family(self, family, remaining):
        run_id = 'SYN.ExtractionQC.CLI.' + family
        report = self.command('demo', '--profile', 'model/extraction-analytics.' + family + '.json',
                              '--run-id', run_id)
        self.assertTrue(report['passed'])
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['resources'], [])
        for flag in ('hardware_executed', 'network_executed', 'biochemical_protocol_executed',
                     'sop_qualified', 'fragment_size_qualified', 'safety_function_qualified',
                     'nanodrop_hardware_executed', 'qubit_hardware_executed'):
            self.assertIs(report[flag], False, flag)
        with Journal(self.store) as journal:
            state = journal.state(run_id)[0]
            spec = state['definition']['execution']['analytics']
            product = spec['product_material_id']
            materials = state['inventory']['materials']
            self.assertEqual(materials[product]['vessel_id'], spec['product_vessel_id'])
            self.assertEqual(materials[product]['disposition'], 'retained')
            self.assertEqual(state['inventory']['vessels'][spec['product_vessel_id']]['location'], spec['product_home'])
            self.assertEqual(report['remaining'][product]['value'], remaining)
            draws = [item['quantity']['value'] for row in state['bookings'].values()
                     for item in row.get('actual_inputs', []) if item['material_id'] == product]
            self.assertEqual(sorted(draws), [1, 1.5, 2])
            self.assertEqual(len([m for m in state['definition']['initial_materials'] if m['kind'] == 'sample']), 1)
            ws = spec['reagent_bindings']['working_solution']
            self.assertEqual(report['remaining'][ws]['value'], 422)
            for standard in spec['reagent_bindings']['standards'].values():
                self.assertEqual(report['remaining'][standard]['value'], 90)
            checksums = set(state['imports'])
            for device in ('nanodrop', 'qubit'):
                context = state['analytics']['stages'][device]
                local = context['local']
                self.assertEqual(local['status'], 'completed')
                self.assertEqual(local['result_review']['decision'], 'accepted')
                self.assertTrue(context['id'].startswith(run_id + '.'))
                checksums.update(local['imports'])
                for result in local['results'].values():
                    if result.get('sample_id') == spec['sample_id']:
                        source = result['extraction_source']
                        self.assertEqual(source['product_material_id'], product)
                        self.assertEqual(source['product_vessel_id'], spec['product_vessel_id'])
                        self.assertEqual(source['sample_id'], spec['sample_id'])
            qubit = state['analytics']['stages']['qubit']
            self.assertEqual(len(qubit['local']['preparations']), 3)
            self.assertEqual(qubit['local']['calibration']['status'], 'approved')
            for prep in qubit['local']['preparations'].values():
                material = materials[qubit['derived'][prep['vessel_id']]['material_id']]
                self.assertEqual(material['disposition'], 'discarded')
                self.assertIsNone(material['vessel_id'])
                source = product if prep['kind'] == 'sample' else spec['reagent_bindings']['standards'][prep['target_id']]
                self.assertEqual(set(material['parents']), {source, ws})
                if prep['kind'] == 'standard':
                    transfer = qubit['local']['transfers'][prep['transfer_id']]
                    self.assertEqual(transfer['source']['stock_id'], source)
            self.assertEqual(len(checksums), 3)
            for checksum in checksums:
                self.assertEqual(hashlib.sha256(journal.artifact(checksum)).hexdigest(), checksum)
            self.assertEqual(state['process']['qc']['review']['decision'], 'accept')

    def test_dneasy_cli_retains_product_and_all_three_independent_measurement_artifacts(self):
        self.check_completed_family('dneasy', 195.5)

    def test_puregene_cli_retains_product_and_all_three_independent_measurement_artifacts(self):
        self.check_completed_family('puregene', 95.5)

    def test_restart_keeps_one_pending_nanodrop_draw_and_requires_explicit_resolution(self):
        run = 'SYN.ExtractionQC.CLI.Restart'
        self.command('demo', '--run-id', run, '--pause-after', 'nanodrop_intent')
        with Journal(self.store) as journal:
            state = journal.state(run)[0]
            pending = state['analytics']['stages']['nanodrop']['local']['pending_measurement']
            product = state['definition']['execution']['analytics']['product_material_id']
            self.assertEqual(state['bookings'][pending['intent_id']]['outcome'], 'intent')
            before = journal.history(run)
        self.command('status', run)
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), before)
        resumed = self.command('resume', run)
        session = resumed['session']
        data = {'device': 'nanodrop', 'operation': 'confirm_measurement', 'arguments': {
            'intent_id': pending['intent_id'], 'observed_sample_id': pending['sample_id'],
            'volume_ul': 1.5, 'cleaned': True}}
        self.action(run, session, 'device_action', data, code=1)
        self.action(run, session, 'resolve_device', {'device': 'nanodrop',
            'pending_resolution': {'intent_id': pending['intent_id'], 'outcome': 'unknown'},
            'device_valid': True, 'reason': 'Explicit synthetic unknown measurement outcome'})
        with Journal(self.store) as journal:
            state = journal.state(run)[0]
            self.assertEqual(state['bookings'][pending['intent_id']]['outcome'], 'unknown')
            self.assertTrue(state['resources'])
        report = self.command('report', run)
        self.assertIsNone(report['remaining'][product]['value'])
        resolution = {**data['arguments'], 'outcome': 'performed'}
        self.action(run, session, 'resolve_device', {'device': 'nanodrop',
            'pending_resolution': resolution, 'device_valid': True,
            'reason': 'Explicit synthetic observation of completed draw and cleanup'})
        with Journal(self.store) as journal:
            state = journal.state(run)[0]
            self.assertEqual(state['bookings'][pending['intent_id']]['outcome'], 'performed')
            self.assertEqual(len(state['analytics']['stages']['nanodrop']['local']['measurements']), 1)
            observations = ExtractionAnalyticsWorkflow(journal, run, session).inventory_observations()
        self.action(run, session, 'reconcile', {'observations': observations, 'workspace_clear': True})
        report = self.command('report', run)
        self.assertEqual(report['remaining'][product]['value'], 198.5)
        self.assertFalse(report['passed'])
        self.assertIsNone(report['process']['qc']['request'])

    def test_create_is_unconfirmed_does_not_reseed_stock_and_rejects_standalone_engines(self):
        run = 'SYN.ExtractionQC.CLI.Created'
        result = self.command('create', '--run-id', run)
        self.assertEqual(result['state']['bookings'], {})
        self.assertEqual(result['state']['analytics']['stages'], {})
        with Journal(self.store) as journal:
            before = journal.history(run)
            for cls in (DNeasyWorkflow, PuregeneWorkflow):
                with self.assertRaises(TaskError): cls(journal, run, None)
        self.command('create', '--run-id', run + '.Duplicate', code=1)
        self.command('demo', '--run-id', run + '.BadPause', '--pause-after', 'not_a_phase', code=1)
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), before)
            for other in (run + '.Duplicate', run + '.BadPause'):
                with self.assertRaises(TaskError): journal.state(other)


if __name__ == '__main__':
    unittest.main()
