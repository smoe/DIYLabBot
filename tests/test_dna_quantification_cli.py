"""German CLI exposes choices and never silently enables synthetic execution."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal


class DnaQuantificationCliTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-cli-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.store = self.folder / 'tasks.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args, actor=None, expected=0):
        command = [sys.executable, str(ROOT / 'scripts/run_dna_quantification.py'), '--store', str(self.store)]
        if actor is not None:
            command += ['--actor', actor]
        result = subprocess.run(command + list(args), cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if expected == 0 else result

    def observations_file(self, report, name='observations.json'):
        path = self.folder / name
        observations = [{'vessel_id': key, 'sample_id': vessel.get('sample_id'), 'location': vessel['location']}
                        for key, vessel in report['inventory']['vessels'].items()]
        path.write_text(json.dumps({'observations': observations, 'workspace_clear': True}), encoding='utf-8')
        return str(path)

    def test_default_demo_and_read_only_report_keep_independent_results(self):
        card = self.command('demo', '--run-id', 'SYN.DNA.CLI')
        self.assertEqual(card['status'], 'completed')
        with Journal(self.store) as journal:
            events = len(journal.history('SYN.DNA.CLI'))
        report = self.command('report', 'SYN.DNA.CLI')
        status = self.command('status', 'SYN.DNA.CLI')
        self.assertTrue(report['passed'])
        self.assertEqual(status, card)
        evaluations = next(iter(report['attempts'].values()))['evaluations']
        self.assertEqual(evaluations['nanodrop']['root_original_concentration']['value'], 50)
        self.assertEqual(evaluations['qubit']['root_original_concentration']['value'], 48)
        with Journal(self.store) as journal:
            self.assertEqual(len(journal.history('SYN.DNA.CLI')), events)

    def test_run_requires_simulation_before_store_is_created(self):
        result = self.command('run', 'SYN.NOT.CREATED', expected=2)
        self.assertIn('--simulation', result.stderr)
        self.assertFalse(self.store.exists())

    def test_invalid_synthetic_concentration_fails_before_store_is_created(self):
        result = self.command('demo', '--qubit-concentration', 'nan', expected=1)
        self.assertIn('Finite nonnegative', result.stderr)
        self.assertFalse(self.store.exists())

    def test_above_range_output_offers_factor10_and20_then_explicit_retry(self):
        card = self.command('demo', '--run-id', 'SYN.DNA.HIGH', '--qubit-concentration', '500')
        self.assertEqual(card['status'], 'awaiting_choice')
        self.assertEqual({o['key'] for o in card['offered_dilutions']}, {'1+9', '1+19'})
        self.assertEqual({o['factor'] for o in card['offered_dilutions']}, {10, 20})
        self.assertTrue(all('1' in o['label'] for o in card['offered_dilutions']))
        report = self.command('report', 'SYN.DNA.HIGH')
        observation_input = self.observations_file(report)
        card = self.command('run', 'SYN.DNA.HIGH', '--simulation', '--reconcile-input', observation_input,
                            '--qubit-concentration', '500', '--after-range', '1+9')
        self.assertEqual(card['status'], 'completed')
        self.assertEqual(len(card['attempts']), 2)

    def test_created_rack_requires_explicit_reconciliation_then_table_acceptance(self):
        card = self.command('create', '--run-id', 'SYN.DNA.CREATED')
        self.assertFalse(card['rack_on_table'])
        self.assertEqual(card['offered_dilutions'], [])
        report = self.command('report', 'SYN.DNA.CREATED')
        card = self.command('run', 'SYN.DNA.CREATED', '--simulation',
                            '--reconcile-input', self.observations_file(report), actor='SYN.CLI.Actor')
        self.assertEqual(card['status'], 'completed')
        report = self.command('report', 'SYN.DNA.CREATED')
        self.assertEqual({c['local']['actor_id'] for c in report['contexts'].values()}, {'SYN.CLI.Actor'})

    def test_explicit_low_result_acceptance_can_close_but_does_not_pass(self):
        self.command('demo', '--run-id', 'SYN.DNA.LOW', '--nanodrop-concentration', '0.5')
        report = self.command('report', 'SYN.DNA.LOW')
        observation_input = self.observations_file(report)
        card = self.command('accept-result', 'SYN.DNA.LOW', '--reconcile-input', observation_input,
                            '--allow-unquantified', '--reason', 'Synthetic retention of low NanoDrop result')
        self.assertTrue(card['samples']['DNA01']['accepted_with_flags'])
        card = self.command('complete', 'SYN.DNA.LOW', '--reconcile-input', observation_input,
                            '--input', observation_input)
        self.assertEqual(card['status'], 'completed')
        self.assertFalse(self.command('report', 'SYN.DNA.LOW')['passed'])

    def test_cancel_intent_survives_separate_cli_process_before_finish(self):
        self.command('create', '--run-id', 'SYN.DNA.CANCEL')
        card = self.command('cancel', 'SYN.DNA.CANCEL', '--reason', 'Synthetic cancellation before table acceptance')
        self.assertEqual(card['status'], 'cancelling')
        report = self.command('report', 'SYN.DNA.CANCEL')
        card = self.command('finish-cancel', 'SYN.DNA.CANCEL', '--input', self.observations_file(report))
        self.assertEqual(card['status'], 'cancelled')
        self.assertEqual(card['resources'], [])


if __name__ == '__main__':
    unittest.main()
