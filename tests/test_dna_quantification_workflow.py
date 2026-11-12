"""Sequential synthetic DNA assays preserve input lineage and range decisions."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_quantification import SOURCE, Workflow
from dna_quantification_demo import ACTOR, SyntheticBackend, run_synthetic
from manual_tasks import Journal, TaskError


class DnaQuantificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-workflow-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.journal = Journal(self.folder / 'workflow.sqlite3')
        self.flow = Workflow.create(self.journal, run_id='SYN.DNA.TEST')

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def attempt(self, index=-1, flow=None):
        return list((flow or self.flow).state['attempts'].values())[index]

    def raw_artifacts(self, flow=None):
        return {checksum: self.journal.artifact(checksum)
                for context in (flow or self.flow).state['contexts'].values()
                for checksum in context['local']['imports']}

    def assert_closed_inventory(self, report):
        self.assertEqual(report['resources'], [])
        self.assertEqual(self.journal.owners(), {})
        for vessel in report['inventory']['vessels'].values():
            if vessel['kind'] == 'original':
                self.assertEqual(vessel['location'], vessel['home'])
                self.assertTrue(vessel['return_confirmation'])
            else:
                self.assertEqual(vessel['location'], {'kind': 'discarded'})

    def test_normal_pair_uses_independent_device_values_and_one_original_balance(self):
        run_synthetic(self.flow)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['logical_time_s'], 240)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual({b['source_vessel_id'] for b in report['bookings'].values()}, {'SYN.DNA.Tube01'})
        self.assertEqual({b['actual_volume_ul'] for b in report['bookings'].values()}, {1.5, 2})
        evaluations = self.attempt()['evaluations']
        self.assertEqual(evaluations['nanodrop']['root_original_concentration']['value'], 50)
        self.assertEqual(evaluations['qubit']['root_original_concentration']['value'], 48)
        self.assertEqual(evaluations['qubit']['measured_value'], 96)
        for flag in ['network_executed', 'hardware_executed', 'robot_motion_executed',
                     'real_export_qualified', 'cross_run_volume_ledger']:
            self.assertFalse(report[flag], flag)
        self.assert_closed_inventory(report)
        self.assertEqual(len(self.raw_artifacts()), 2)

    def test_f10_and_f20_consume_original_once_and_preserve_raw_factor_50(self):
        for index, (preset, factor) in enumerate([('1+9', 10), ('1+19', 20)]):
            with self.subTest(preset=preset):
                # Isolate the factor cases in separate synthetic roots.
                flow = self.flow if index == 0 else Workflow.create(self.journal, run_id='SYN.DNA.F20')
                run_synthetic(flow, initial_dilution=preset)
                report = flow.report(); attempt = self.attempt(flow=flow)
                self.assertTrue(report['passed'])
                self.assertEqual(attempt['external_factor'], factor)
                original = report['inventory']['vessels']['SYN.DNA.Tube01']
                self.assertEqual(original['remaining_volume_ul'], 38)
                original_bookings = [b for b in report['bookings'].values()
                                     if b['source_vessel_id'] == original['id']]
                self.assertEqual(len(original_bookings), 1)
                self.assertEqual(original_bookings[0]['actual_volume_ul'], 2)
                self.assertEqual(len(report['bookings']), 3)
                stock = report['inventory']['vessels'][attempt['input_vessel_id']]
                self.assertEqual(stock['initial_volume_ul'], 2 * factor)
                self.assertEqual(stock['disposed_remaining_volume_ul'], 2 * factor - 3.5)
                for device, original_value in [('nanodrop', 50), ('qubit', 48)]:
                    evaluation = attempt['evaluations'][device]
                    self.assertAlmostEqual(evaluation['selected_input_concentration']['value'], original_value / factor)
                    self.assertAlmostEqual(evaluation['root_original_concentration']['value'], original_value)
                nd = attempt['results']['nanodrop']
                self.assertEqual(nd['raw_cells']['Factor'], '50')
                self.assertEqual(nd['metrics']['factor']['value'], 50)
                self.assertIn(b',50,', self.journal.artifact(nd['artifact_sha256']))
                self.assert_closed_inventory(report)

    def test_qubit_above_range_retries_pair_and_retains_old_ids_artifacts_and_consumption(self):
        backend = SyntheticBackend({'nanodrop': 50, 'qubit': 500})
        run_synthetic(self.flow, backend=backend)
        first = self.attempt()
        old_raw = self.raw_artifacts()
        self.assertEqual(first['evaluations']['qubit']['status'], 'above_range')
        self.assertEqual(set(first['contexts']), {'nanodrop', 'qubit'})
        self.assertEqual({o['key'] for o in self.flow.options()}, {'1+9', '1+19'})
        run_synthetic(self.flow, after_range='1+9', backend=backend)
        report = self.flow.report(); second = self.attempt()
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['attempts']), 2)
        self.assertEqual(report['attempts'][first['id']]['status'], 'superseded')
        self.assertEqual(report['attempts'][first['id']]['results'], first['results'])
        self.assertTrue(set(first['contexts'].values()).isdisjoint(second['contexts'].values()))
        self.assertEqual(second['evaluations']['qubit']['root_original_concentration']['value'], 500)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 34.5)
        self.assertEqual(len(report['bookings']), 5)
        for checksum, raw in old_raw.items():
            self.assertEqual(self.journal.artifact(checksum), raw)
        self.assertEqual(len(self.raw_artifacts()), 4)
        self.assert_closed_inventory(report)

    def test_nanodrop_above_range_stops_before_qubit_then_retries_fresh_pair(self):
        backend = SyntheticBackend({'nanodrop': 30000, 'qubit': 48})
        run_synthetic(self.flow, backend=backend)
        first = self.attempt()
        self.assertEqual(self.flow.state['status'], 'awaiting_choice')
        self.assertIsNone(self.flow.state['active_context_id'])
        self.assertEqual(set(first['contexts']), {'nanodrop'})
        self.assertEqual(len(self.flow.state['bookings']), 1)
        run_synthetic(self.flow, after_range='1+9', backend=backend)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['bookings']), 4)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)
        self.assertEqual(set(self.attempt()['contexts']), {'nanodrop', 'qubit'})

    def test_low_nanodrop_still_runs_qubit_and_never_automatically_dilutes_further(self):
        backend = SyntheticBackend({'nanodrop': 0.5, 'qubit': 0.5})
        run_synthetic(self.flow, after_range='1+9', backend=backend)
        attempt = self.attempt(); report = self.flow.report()
        self.assertEqual(report['status'], 'awaiting_decision')
        self.assertFalse(report['passed'])
        self.assertEqual(attempt['evaluations']['nanodrop']['status'], 'below_range')
        self.assertEqual(attempt['evaluations']['qubit']['status'], 'in_range')
        self.assertEqual(len(report['attempts']), 1)
        self.assertEqual(self.flow.options(), [])
        self.assertEqual(report['dilutions'], {})
        with self.assertRaises(TaskError):
            self.flow.accept_result(ACTOR, 'DNA01')

    def test_both_low_has_no_further_dilution_option(self):
        run_synthetic(self.flow, after_range='1+19',
                      backend=SyntheticBackend({'nanodrop': 0.5, 'qubit': 0.01}))
        self.assertEqual({e['status'] for e in self.attempt()['evaluations'].values()}, {'below_range'})
        self.assertEqual(self.flow.options(), [])
        self.assertFalse(self.flow.report()['passed'])
        self.assertEqual(len(self.flow.state['attempts']), 1)

    def test_qubit_reported_original_is_not_assay_corrected_twice(self):
        run_synthetic(self.flow, initial_dilution='1+9',
                      backend=SyntheticBackend(qubit_report_original=True))
        attempt = self.attempt(); result = attempt['results']['qubit']
        self.assertTrue(self.flow.report()['passed'])
        self.assertEqual(result['raw_cells']['Original Concentration'], '4.8')
        self.assertEqual(result['metrics']['original_concentration']['value'], 4.8)
        self.assertEqual(attempt['evaluations']['qubit']['root_original_concentration']['value'], 48)

    def test_two_sample_mixed_inputs_follow_rack_order_and_restore_original_places(self):
        # Deliberately reverse the manifest list: queue order comes from rack slots.
        profile = json.loads(SOURCE.read_text(encoding='utf-8'))
        profile['samples'] = [dict(profile['samples'][0], id='DNA02', vessel_id='SYN.DNA.Tube02', rack_slot=7),
                              profile['samples'][0]]
        source = self.folder / 'two-samples.json'
        source.write_text(json.dumps(profile), encoding='utf-8')
        flow = Workflow.create(self.journal, source=source, run_id='SYN.DNA.TWO')
        backend = SyntheticBackend()
        backend.accept_rack(flow)
        self.assertEqual(flow.state['current_sample_id'], 'DNA01')
        flow.choose_dilution(ACTOR, 'DNA01', '1+9')
        backend.confirm_dilution(flow)
        run_synthetic(flow, initial_dilution='none', backend=backend)
        report = flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual([a['sample_id'] for a in report['attempts'].values()], ['DNA01', 'DNA02'])
        self.assertEqual([a['preset'] for a in report['attempts'].values()], ['1+9', 'none'])
        originals = {v['sample_id']: v for v in report['inventory']['vessels'].values() if v['kind'] == 'original'}
        self.assertEqual(originals['DNA01']['remaining_volume_ul'], 38)
        self.assertEqual(originals['DNA02']['remaining_volume_ul'], 36.5)
        self.assertEqual(originals['DNA01']['location']['place_id'], 'Slot01')
        self.assertEqual(originals['DNA02']['location']['place_id'], 'Slot07')
        self.assertEqual(report['logical_time_s'], 480)
        self.assert_closed_inventory(report)

    def test_interrupted_dilution_intent_is_not_replayed_by_synthetic_backend(self):
        run_synthetic(self.flow, initial_dilution='1+9', pause_after='dilution_intent')
        before = self.flow.state
        self.assertTrue(before['pending_dilution'])
        self.assertEqual(len(before['bookings']), 1)
        self.assertEqual(next(iter(before['bookings'].values()))['outcome'], 'intent')
        self.assertIsNone(self.flow.report()['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'])
        events = len(self.journal.history(self.flow.run_id))
        with self.assertRaisesRegex(TaskError, 'not replayed'):
            run_synthetic(self.flow)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), events)

    def test_interrupted_measurement_does_not_repeat_or_assume_withdrawal(self):
        run_synthetic(self.flow, pause_after='measurement_intent')
        before = self.flow.state
        self.assertEqual(len(before['bookings']), 1)
        self.assertEqual(next(iter(before['bookings'].values()))['outcome'], 'intent')
        self.assertEqual(self.attempt()['results'], {})
        events = len(self.journal.history(self.flow.run_id))
        with self.assertRaisesRegex(TaskError, 'fresh device context'):
            run_synthetic(self.flow)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), events)

    def test_unimplemented_backend_fails_before_reserving_or_confirming_anything(self):
        before = self.flow.state
        with self.assertRaisesRegex(TaskError, 'SyntheticBackend'):
            run_synthetic(self.flow, backend=object())
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.owners(), {})


if __name__ == '__main__':
    unittest.main()
