"""Network continuation retains confirmed operations and separates worker custody."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_quantification import Workflow
from dna_quantification_demo import ACTOR, run_synthetic
from dna_quantification_execution import NetworkSyntheticBackend, SyntheticHandling
from dna_quantification_tasks import MockTaskWorker
from manual_tasks import Journal, TaskError
from qubit_manual import calibration_binding


class DnaQuantificationExecutionTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-execution-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.journal = Journal(self.folder / 'root.sqlite3')
        self.flow = Workflow.create(self.journal, run_id='SYN.DNA.EXECUTION')
        # Phase A continuation can reuse the old synthetic person handling.
        self.backend = NetworkSyntheticBackend(handling=SyntheticHandling())

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def ready_nd(self, backend=None):
        backend = backend or self.backend
        backend.accept_rack(self.flow)
        self.flow.choose_dilution(backend.actor_id, 'DNA01', 'none')
        return self.flow.state['active_context_id']

    def ready_qubit(self):
        context = self.ready_nd()
        self.backend.run_context(self.flow, context)
        return self.flow.state['active_context_id']

    def prepare_standards(self, context_id, *, measure=True, approve=True):
        handle = self.flow.stage(context_id)
        self.backend._claim(handle)
        standards = handle.state['definition']['protocol']['assay']['standards']
        identities = [self.backend._prepare_if_needed(handle, 'standard', standard['id']) for standard in standards]
        if measure:
            self.backend._incubate_remaining(self.flow, handle, identities)
            for identity in identities:
                self.backend._measure_qubit(handle, identity)
            if approve:
                state = handle.state
                handle.act('approve_calibration', ACTOR, binding=calibration_binding(state),
                    standard_measurements={standard['id']: self.backend._active_preparation(handle, 'standard', standard['id'])['measurement_id']
                                           for standard in standards},
                    confirmed=True, reason='Explicit synthetic test approval')
        return handle

    def reopen(self, *, pending_resolution=None, blank=False, calibration=False, **data):
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)
        self.flow.reconcile(ACTOR, self.flow.inventory_observations(), workspace_clear=True,
            pending_resolution=pending_resolution, blank_still_valid=blank,
            calibration_still_valid=calibration, **data)

    def test_performed_nanodrop_reconciliation_continues_without_a_second_withdrawal(self):
        context = self.ready_nd()
        self.assertFalse(self.backend.run_context(self.flow, context, 'measurement_intent'))
        pending = copy.deepcopy(self.flow.stage(context).state['pending_measurement'])
        self.reopen(pending_resolution={'outcome': 'performed', 'intent_id': pending['intent_id'],
                    'observed_sample_id': 'DNA01', 'volume_ul': 1.5, 'cleaned': True})
        run_synthetic(self.flow, backend=self.backend)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(set(report['contexts'][context]['local']['measurements']), {pending['measurement_id']})
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)

    def test_existing_accepted_raw_report_is_not_regenerated_or_imported_again(self):
        context = self.ready_nd(); handle = self.flow.stage(context)
        self.backend._claim(handle)
        handle.act('blank', ACTOR, reference_id='SYN.Test.Blank', cleaned=True)
        self.backend._take(handle, 'DNA01')
        measurement_id = handle.state['planned_measurements']['DNA01']
        handle.act('begin_measurement', ACTOR, sample_id='DNA01', measurement_id=measurement_id)
        handle.act('confirm_measurement', ACTOR, intent_id=handle.state['pending_measurement']['intent_id'],
                   observed_sample_id='DNA01', volume_ul=1.5, cleaned=True)
        self.backend._place(handle, 'DNA01')
        other = NetworkSyntheticBackend({'nanodrop': 77, 'qubit': 48}, handling=SyntheticHandling())
        raw = other.nanodrop_report(self.flow, context)
        handle.import_content(raw, ACTOR, 'preserved-original.csv')
        original_imports = copy.deepcopy(handle.state['imports'])
        self.reopen()
        run_synthetic(self.flow, backend=self.backend)
        local = self.flow.state['contexts'][context]['local']
        self.assertEqual(local['imports'], original_imports)
        self.assertEqual(local['results'][measurement_id]['metrics']['concentration']['value'], 77)
        self.assertEqual(self.journal.artifact(next(iter(original_imports))), raw)
        self.assertTrue(self.flow.report()['passed'])

    def test_pending_device_operation_cannot_be_implicitly_confirmed(self):
        context = self.ready_nd()
        self.backend.run_context(self.flow, context, 'measurement_intent')
        before = self.flow.state; history = self.journal.history(self.flow.run_id)
        with self.assertRaisesRegex(TaskError, 'reconciliation'):
            self.backend.run_context(self.flow, context)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.history(self.flow.run_id), history)

    def test_prepared_standards_incubate_only_the_remaining_minimum(self):
        context = self.ready_qubit()
        self.prepare_standards(context, measure=False)
        self.flow.advance_time(ACTOR, 50)
        self.reopen()
        run_synthetic(self.flow, backend=self.backend)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['logical_time_s'], 240)
        self.assertEqual(len(report['contexts'][context]['local']['preparations']), 3)

    def test_reconciled_standard_measurement_is_not_repeated(self):
        context = self.ready_qubit()
        self.assertFalse(self.backend.run_context(self.flow, context, 'measurement_intent'))
        pending = copy.deepcopy(self.flow.stage(context).state['pending_operation'])
        self.reopen(pending_resolution={'outcome': 'performed', 'intent_id': pending['intent_id'],
                    'observed_vessel_id': pending['vessel_id'], 'returned_to_holder': True})
        run_synthetic(self.flow, backend=self.backend)
        report = self.flow.report(); local = report['contexts'][context]['local']
        self.assertTrue(report['passed'])
        self.assertEqual(len(local['measurements']), 3)
        self.assertIn(pending['measurement_id'], local['measurements'])
        self.assertEqual(len(local['preparations']), 3)
        self.assertEqual(report['logical_time_s'], 240)

    def test_performed_qubit_sample_preparation_does_not_debit_original_again(self):
        context = self.ready_qubit(); handle = self.prepare_standards(context)
        self.backend._take(handle, 'DNA01')
        preparation_id = self.backend._begin_preparation(handle, 'sample', 'DNA01')
        pending = copy.deepcopy(handle.state['pending_operation'])
        self.reopen(pending_resolution={'outcome': 'performed', 'intent_id': pending['intent_id'],
                    'observed_vessel_id': pending['vessel_id'], 'observed_sample_id': 'DNA01',
                    'volume_ul': 2, 'assay_total_volume_ul': 200, 'mixed': True}, calibration=True)
        run_synthetic(self.flow, backend=self.backend)
        report = self.flow.report(); local = report['contexts'][context]['local']
        self.assertTrue(report['passed'])
        self.assertEqual(len(local['preparations']), 3)
        self.assertEqual(local['active_preparations']['sample:DNA01'], preparation_id)
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)

    def test_invalidated_calibration_is_not_automatically_approved_again(self):
        context = self.ready_qubit(); self.prepare_standards(context)
        self.reopen(calibration=False)
        before = self.flow.state; events = self.journal.history(self.flow.run_id)
        with self.assertRaisesRegex(TaskError, 'invalidated'):
            self.backend.run_context(self.flow, context)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.history(self.flow.run_id), events)
        self.assertEqual(before['contexts'][context]['local']['calibration']['status'], 'invalidated_by_observation')

    def test_expired_calibration_is_not_reused_for_a_new_sample_measurement(self):
        context = self.ready_qubit(); self.prepare_standards(context)
        self.flow.advance_time(ACTOR, 1000)
        before = self.flow.state
        with self.assertRaisesRegex(TaskError, 'unexpired calibration'):
            self.backend.run_context(self.flow, context)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(before['bookings']), 1)

    def test_worker_claim_alone_changes_neither_custody_consumption_nor_responsibility(self):
        context = self.ready_nd(); handle = self.flow.stage(context)
        self.backend._claim(handle)
        worker = MockTaskWorker('SYN.Robot01', boot_id='SYN.Boot01')
        goal = self.flow.task_goal(context, {'kind': 'agent', 'agent_id': worker.agent_id}, worker.agent_id)
        self.flow.intend_task(ACTOR, goal)
        before = self.flow.state
        claim = self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        after = self.flow.state
        self.assertEqual(after['inventory'], before['inventory'])
        self.assertEqual(after['bookings'], {})
        self.assertEqual(after['actor_id'], ACTOR)
        self.assertEqual(claim['evidence'], 'worker_claim')
        observation = {'sample_id': 'DNA01', 'vessel_id': 'SYN.DNA.Tube01',
                       'location': {'kind': 'agent', 'agent_id': worker.agent_id}}
        with self.assertRaisesRegex(TaskError, 'not a custody observation'):
            self.flow.observe_task(ACTOR, goal['goal_id'], observation, evidence='worker_claim')
        self.flow.observe_task(ACTOR, goal['goal_id'], observation, evidence='synthetic_person_input')
        canonical = self.flow.state['inventory']['vessels']['SYN.DNA.Tube01']
        self.assertEqual(canonical['location'], observation['location'])
        self.assertEqual(self.flow.stage(context).state['samples']['DNA01']['location'], {'kind': 'operator', 'actor_id': ACTOR})
        self.assertEqual(self.flow.state['contexts'][context]['executing_agent_id'], worker.agent_id)
        self.assertEqual(self.flow.report()['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 40)
        self.assertEqual(self.flow.state['bookings'], {})

    def test_default_network_backend_uses_observed_task_transfers_with_distinct_agent(self):
        backend = NetworkSyntheticBackend(executing_agent_id='SYN.Robot01')
        run_synthetic(self.flow, backend=backend)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['actor_id'] if 'actor_id' in report else self.flow.state['actor_id'], ACTOR)
        self.assertEqual(report['executing_agent_id'], 'SYN.Robot01')
        self.assertEqual(len(report['task_port']['goals']), 4)
        self.assertEqual({g['status'] for g in report['task_port']['goals'].values()}, {'observed'})
        self.assertEqual({g['claim']['evidence'] for g in report['task_port']['goals'].values()}, {'worker_claim'})
        self.assertEqual({g['observation_evidence'] for g in report['task_port']['goals'].values()}, {'synthetic_backend'})
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['location']['kind'], 'rack')
        self.assertEqual(self.journal.owners(), {})
        self.assertFalse(report['robot_motion_executed'])

    def test_pending_worker_task_and_cancel_keep_resources_until_explicit_observation(self):
        context = self.ready_nd(); self.backend._claim(self.flow.stage(context))
        worker = MockTaskWorker('SYN.Robot01')
        goal = self.flow.task_goal(context, {'kind': 'agent', 'agent_id': worker.agent_id}, worker.agent_id)
        self.flow.intend_task(ACTOR, goal)
        self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        with self.assertRaisesRegex(TaskError, 'pending worker task'):
            NetworkSyntheticBackend().run_context(self.flow, context)
        self.flow.cancel(ACTOR, 'Explicit synthetic cancellation before custody observation')
        with self.assertRaises(TaskError):
            self.flow.finish_cancel(ACTOR, self.flow.inventory_observations(), workspace_clear=True)
        self.assertIn('agent:SYN.Robot01', self.flow.state['resources'])
        self.assertTrue(self.journal.owners())
        self.flow.reconcile(ACTOR, self.flow.inventory_observations(), workspace_clear=True,
                            task_resolution={'goal_id': goal['goal_id'], 'outcome': 'not_performed'})
        self.flow.finish_cancel(ACTOR, self.flow.inventory_observations(), workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertEqual(self.journal.owners(), {})


if __name__ == '__main__':
    unittest.main()
