"""An explicitly discarded bad import must not retire measurement evidence."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_quantification import Workflow
from dna_quantification_demo import ACTOR, SyntheticBackend
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError


class DnaQuantificationImportTests(unittest.TestCase):
    def test_discarded_bad_import_allows_corrected_import_without_new_withdrawal(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-import-test-', dir=ROOT / 'exports') as folder:
            with Journal(Path(folder) / 'tasks.sqlite3') as journal:
                flow = Workflow.create(journal, run_id='SYN.DNA.IMPORT')
                backend = SyntheticBackend()
                backend.accept_rack(flow)
                flow.choose_dilution(ACTOR, 'DNA01', 'none')
                context_id = flow.state['active_context_id']
                handle = flow.stage(context_id)
                backend._claim(handle)
                handle.act('blank', ACTOR, reference_id='SYN.DNA.Blank01', cleaned=True)
                backend._take(handle, 'DNA01')
                handle.act('begin_measurement', ACTOR, sample_id='DNA01',
                           measurement_id=handle.state['planned_measurements']['DNA01'])
                handle.act('confirm_measurement', ACTOR,
                           intent_id=handle.state['pending_measurement']['intent_id'],
                           observed_sample_id='DNA01', volume_ul=1.5, cleaned=True)
                backend._place(handle, 'DNA01')
                bookings = flow.state['bookings']
                bad = b'Unqualified synthetic report bytes\n'
                handle.import_content(bad, ACTOR, 'bad.csv')
                self.assertEqual(handle.state['imports'][digest(bad)]['status'], 'quarantined')
                handle.act('discard_import', ACTOR, sha256=digest(bad),
                           reason='Explicitly rejected malformed synthetic import')
                good = backend.nanodrop_report(flow, context_id)
                handle.import_content(good, ACTOR, 'corrected.csv')

                flow.finish_context(ACTOR, context_id, workspace_clear=True)

                state = flow.state
                completed = state['contexts'][context_id]['local']
                self.assertEqual(completed['status'], 'completed')
                self.assertEqual(completed['imports'][digest(bad)]['status'], 'discarded')
                self.assertEqual(completed['imports'][digest(good)]['status'], 'accepted')
                self.assertEqual(journal.artifact(digest(bad)), bad)
                self.assertEqual(journal.artifact(digest(good)), good)
                self.assertEqual(state['bookings'], bookings)
                self.assertEqual(len(state['bookings']), 1)
                self.assertEqual(state['contexts'][state['active_context_id']]['device'], 'qubit')

    def test_restart_calibration_invalidation_blocks_finishing_qubit_context(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-calibration-test-', dir=ROOT / 'exports') as folder:
            with Journal(Path(folder) / 'tasks.sqlite3') as journal:
                flow = Workflow.create(journal, run_id='SYN.DNA.CALIBRATION')
                backend = SyntheticBackend()
                backend.accept_rack(flow)
                flow.choose_dilution(ACTOR, 'DNA01', 'none')
                backend.run_context(flow, flow.state['active_context_id'])
                context_id = flow.state['active_context_id']
                # Interrupt after the raw result import, before root acceptance.
                with mock.patch.object(flow, 'finish_context') as finish:
                    backend.run_context(flow, context_id)
                    finish.assert_called_once_with(ACTOR, context_id, workspace_clear=True)
                raw = {checksum: journal.artifact(checksum)
                       for checksum in flow.state['contexts'][context_id]['local']['imports']}
                flow.close()
                flow = Workflow.open(journal, flow.run_id)
                flow.reconcile(ACTOR, flow.inventory_observations(), workspace_clear=True,
                               calibration_still_valid=False)
                before = flow.state

                with self.assertRaisesRegex(TaskError, 'Calibration was not approved or was invalidated'):
                    flow.finish_context(ACTOR, context_id, workspace_clear=True)

                self.assertEqual(flow.state, before)
                self.assertEqual(flow.state['active_context_id'], context_id)
                self.assertEqual(len(flow.state['bookings']), 2)
                self.assertEqual(flow.state['contexts'][context_id]['local']['calibration']['status'],
                                 'invalidated_by_observation')
                for checksum, content in raw.items():
                    self.assertEqual(journal.artifact(checksum), content)

    def test_reconciliation_rejects_duplicate_holder_occupancy_with_extra_keys(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-place-test-', dir=ROOT / 'exports') as folder:
            with Journal(Path(folder) / 'tasks.sqlite3') as journal:
                flow = Workflow.create(journal, run_id='SYN.DNA.OCCUPANCY')
                backend = SyntheticBackend()
                backend.accept_rack(flow)
                flow.choose_dilution(ACTOR, 'DNA01', 'none')
                backend.run_context(flow, flow.state['active_context_id'])
                handle = flow.stage(flow.state['active_context_id'])
                backend._claim(handle)
                for standard in handle.state['definition']['protocol']['assay']['standards']:
                    backend._begin_preparation(handle, 'standard', standard['id'])
                    backend._confirm_preparation(handle)
                before = flow.state
                derived = list(handle.state['derived_vessels'])
                self.assertEqual(len(derived), 2)
                occupied = before['inventory']['vessels'][derived[0]]['location']
                observations = flow.inventory_observations()
                for item in observations:
                    if item['vessel_id'] == derived[1]:
                        item['location'] = {**occupied, 'unqualified_hint': 'same physical place'}

                with self.assertRaises(ObservationError):
                    flow.reconcile(ACTOR, observations, workspace_clear=True)

                after = flow.state
                self.assertEqual(after['status'], 'held')
                self.assertEqual(after['inventory'], before['inventory'])
                self.assertEqual(after['bookings'], before['bookings'])

    def test_actual_nanodrop_subminimum_volume_cannot_qualify_paired_results(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-volume-test-', dir=ROOT / 'exports') as folder:
            with Journal(Path(folder) / 'tasks.sqlite3') as journal:
                flow = Workflow.create(journal, run_id='SYN.DNA.MINIMUM')
                backend = SyntheticBackend()
                backend.accept_rack(flow)
                flow.choose_dilution(ACTOR, 'DNA01', 'none')
                context_id = flow.state['active_context_id']
                handle = flow.stage(context_id)
                backend._claim(handle)
                handle.act('blank', ACTOR, reference_id='SYN.DNA.Blank01', cleaned=True)
                backend._take(handle, 'DNA01')
                handle.act('begin_measurement', ACTOR, sample_id='DNA01',
                           measurement_id=handle.state['planned_measurements']['DNA01'])
                handle.act('confirm_measurement', ACTOR,
                           intent_id=handle.state['pending_measurement']['intent_id'],
                           observed_sample_id='DNA01', volume_ul=0.5, cleaned=True,
                           deviation_reason='Explicit synthetic subminimum withdrawal observation')
                backend._place(handle, 'DNA01')
                handle.import_content(backend.nanodrop_report(flow, context_id), ACTOR)
                flow.finish_context(ACTOR, context_id, workspace_clear=True)
                attempt = flow.state['attempts'][flow.state['active_attempt_id']]
                self.assertEqual(attempt['evaluations']['nanodrop']['status'], 'unknown')
                self.assertFalse(attempt['evaluations']['nanodrop']['quantifiable'])
                self.assertEqual(flow.report()['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 39.5)
                backend.run_context(flow, flow.state['active_context_id'])

                with self.assertRaises(TaskError):
                    flow.accept_result(ACTOR, 'DNA01')

                self.assertFalse(flow.report()['passed'])
                self.assertEqual({row['actual_volume_ul'] for row in flow.state['bookings'].values()}, {0.5, 2})

    def test_reconciled_cancellation_blocks_new_effects_and_normal_acceptance(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-cancel-guard-', dir=ROOT / 'exports') as folder:
            with Journal(Path(folder) / 'tasks.sqlite3') as journal:
                flow = Workflow.create(journal, run_id='SYN.DNA.CANCEL.GUARD')
                backend = SyntheticBackend()
                backend.accept_rack(flow)
                flow.choose_dilution(ACTOR, 'DNA01', 'none')
                context_id = flow.state['active_context_id']
                with mock.patch.object(flow, 'finish_context'):
                    backend.run_context(flow, context_id)
                handle = flow.stage(context_id)
                flow.cancel(ACTOR, 'Explicit synthetic cancellation before root acceptance')
                flow.reconcile(ACTOR, flow.inventory_observations(), workspace_clear=True,
                               blank_still_valid=True)
                before = copy.deepcopy(flow.state)
                self.assertTrue(before['cancel_requested'])
                self.assertIsNone(before['recovery_required'])
                operations = {
                    'take': lambda: backend._take(handle, 'DNA01'),
                    'begin_measurement': lambda: handle.act('begin_measurement', ACTOR, sample_id='DNA01',
                        measurement_id=handle.state['planned_measurements']['DNA01']),
                    'finish_context': lambda: flow.finish_context(ACTOR, context_id, workspace_clear=True),
                    'accept_result': lambda: flow.accept_result(ACTOR, 'DNA01'),
                    'complete': lambda: flow.complete(ACTOR, flow.inventory_observations(), workspace_clear=True),
                }
                for name, operation in operations.items():
                    with self.subTest(operation=name):
                        with self.assertRaisesRegex(TaskError, '[Cc]ancel'):
                            operation()
                        self.assertEqual(flow.state, before)


if __name__ == '__main__':
    unittest.main()
