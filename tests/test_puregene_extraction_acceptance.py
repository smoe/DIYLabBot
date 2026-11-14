"""Whole-flow and process-restart checks for synthetic Puregene extraction."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from puregene_extraction_sources import load
from puregene_extraction_workflow import PuregeneWorkflow
from dneasy_extraction_workflow import DNeasyWorkflow
from manual_tasks import Journal, TaskError


class PuregeneExtractionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='puregene-cli-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'workflows.sqlite3'

    def command(self, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_puregene_extraction.py'),
                                 '--store', str(self.store), *args], cwd=ROOT, capture_output=True,
                                text=True, timeout=240)
        self.assertEqual(result.returncode, code, result.stderr[-8000:] or result.stdout[:2000])
        return json.loads(result.stdout)

    @staticmethod
    def ancestors(inventory, identity):
        found = set()
        def visit(current):
            for parent in inventory[current]['parents']:
                if parent not in found:
                    found.add(parent); visit(parent)
        visit(identity)
        return found

    def test_complete_cli_retains_product_and_has_no_false_protein_ipa_ancestry(self):
        run = 'SYN.Puregene.CLI.Full'
        report = self.command('demo', '--run-id', run)
        self.assertEqual(report['status'], 'completed')
        self.assertTrue(report['passed'])
        for flag in ('hardware_executed', 'network_executed', 'biochemical_protocol_executed',
                     'sop_qualified', 'fragment_size_qualified', 'safety_function_qualified'):
            self.assertIs(report[flag], False, flag)
        definition = load(); execution = definition['execution']
        sample = next(iter(execution['samples'].values()))
        product = sample['product_material_id']
        inventory = report['inventory']['materials']
        self.assertEqual(inventory[product]['disposition'], 'retained')
        self.assertEqual(inventory[product]['vessel_id'], sample['product_vessel_id'])
        self.assertEqual(report['remaining'][product]['value'], 99)
        protein = next(identity for identity in inventory if identity.endswith('.protein_pellet'))
        ipa = sample['reagent_bindings']['Isopropanol']
        self.assertNotIn(ipa, self.ancestors(inventory, protein))
        self.assertIn(ipa, self.ancestors(inventory, product))
        self.assertIn(sample['input_material_id'], self.ancestors(inventory, product))
        self.assertIsNone(inventory[protein]['initial_quantity']['value'])
        dna_draws = [item for booking in report['bookings'].values() for item in booking['actual_inputs']
                     if item['material_id'] == product]
        self.assertEqual(dna_draws, [{'material_id': product, 'quantity': {'value': 1.0, 'unit': 'uL'}}])
        with Journal(self.store) as journal:
            for checksum in report['imports']:
                raw = json.loads(journal.artifact(checksum))
                self.assertEqual(raw['format'], 'solidcraftbot.synthetic-tapestation-report/1')
            state = journal.state(run)[0]
            self.assertEqual(state['resources'], [])
            self.assertEqual(state['process']['cursor'], len(execution['steps']))
            overnight = next(operation for operation in state['process']['operations'].values()
                             if operation['request']['identity']['id'] == 'overnight_hydration')
            self.assertEqual(overnight['confirmation']['observations']['duration_s'],
                             execution['settings']['overnight_fixture_s'])

    def test_restart_between_aspiration_and_dispense_keeps_the_actual_materials(self):
        run = 'SYN.Puregene.CLI.Transfer'
        self.command('demo', '--run-id', run, '--pause-after', 'aspirate_dna_supernatant')
        definition = load(); sample_id, sample = next(iter(definition['execution']['samples'].items()))
        with Journal(self.store) as journal:
            before = journal.history(run)
            state = journal.state(run)[0]
            inventory = state['inventory']['materials']
            supernatant = next(identity for identity in inventory if identity.endswith('.dna_supernatant'))
            protein = next(identity for identity in inventory if identity.endswith('.protein_pellet'))
            charge = next(identity for identity in inventory if identity.endswith('.ipa_charge'))
            self.assertEqual(inventory[supernatant]['vessel_id'], sample['fraction_vessels']['transfer_tip'])
            self.assertEqual(inventory[protein]['vessel_id'], sample['input_vessel_id'])
            self.assertEqual(inventory[charge]['vessel_id'], sample['fraction_vessels']['precipitation'])
            self.assertFalse(any(identity.endswith('.dna_ipa_composite') for identity in inventory))
            observations = PuregeneWorkflow(journal, run, None).inventory_observations()
        self.command('status', run)
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), before)
        resumed = self.command('resume', run)
        self.assertEqual(resumed['state']['inventory'], state['inventory'])
        session = resumed['session']
        args = {'sample_id': sample_id, 'phase_id': 'dispense_into_isopropanol', 'intent_id': 'ExplicitDispense'}
        self.command('act', run, '--session', session, '--actor', 'SYN.Puregene.Operator',
                     '--action', 'begin_phase', '--data', json.dumps(args), code=1)
        self.command('act', run, '--session', session, '--actor', 'SYN.Puregene.Operator',
                     '--action', 'reconcile', '--data', json.dumps({
                         'observations': observations, 'workspace_clear': True}))
        result = self.command('act', run, '--session', session, '--actor', 'SYN.Puregene.Operator',
                              '--action', 'begin_phase', '--data', json.dumps(args))
        self.assertEqual(result['bookings']['ExplicitDispense']['outcome'], 'intent')
        self.assertEqual(result['inventory']['materials'][supernatant]['vessel_id'],
                         sample['fraction_vessels']['transfer_tip'])
        self.assertFalse(any(identity.endswith('.dna_ipa_composite') for identity in result['inventory']['materials']))

    def test_create_does_not_execute_or_allow_the_dneasy_adapter_to_open_puregene(self):
        run = 'SYN.Puregene.CLI.Created'
        created = self.command('create', '--run-id', run)
        self.assertEqual(created['state']['status'], 'created')
        self.assertEqual(created['state']['bookings'], {})
        self.assertEqual(created['state']['process']['cursor'], 0)
        with Journal(self.store) as journal:
            before = journal.history(run)
            with self.assertRaises(TaskError): DNeasyWorkflow(journal, run, None)
        self.command('create', '--run-id', 'SYN.Puregene.CLI.DuplicateStock', code=1)
        with Journal(self.store) as journal:
            self.assertEqual(journal.history(run), before)
            with self.assertRaises(TaskError): journal.state('SYN.Puregene.CLI.DuplicateStock')


if __name__ == '__main__':
    unittest.main()
