"""Persisted DNA intents require explicit recovery without replay or release."""
import copy
import subprocess
import sys
import unittest
from unittest import mock

import test_dna_quantification_workflow as workflow_fixtures

from dna_quantification import Workflow
from dna_quantification_demo import ACTOR, SyntheticBackend, run_synthetic
from manual_tasks import Journal, TaskError
from manual_workflow import ObservationError


ROOT = workflow_fixtures.ROOT
ORIGINAL = 'SYN.DNA.Tube01'


class DnaQuantificationRecoveryTests(unittest.TestCase):
    setUp = workflow_fixtures.DnaQuantificationWorkflowTests.setUp
    tearDown = workflow_fixtures.DnaQuantificationWorkflowTests.tearDown

    def pending_dilution(self, preset='1+9'):
        run_synthetic(self.flow, initial_dilution=preset, pause_after='dilution_intent')
        return copy.deepcopy(self.flow.state['pending_dilution'])

    @staticmethod
    def performed(pending):
        return {'outcome': 'performed', 'intent_id': pending['intent_id'],
                'observed_source_vessel_id': pending['source_vessel_id'],
                'observed_target_vessel_id': pending['target_vessel_id'],
                'sample_volume_ul': pending['planned_sample_volume_ul'],
                'diluent_volume_ul': pending['planned_diluent_volume_ul'],
                'mixed': True, 'source_returned': True}

    def resolve(self, outcome, pending, flow=None):
        flow = flow or self.flow
        resolution = (self.performed(pending) if outcome == 'performed' else
                      {'intent_id': pending['intent_id'], 'outcome': outcome})
        return flow.reconcile(ACTOR, flow.inventory_observations(), workspace_clear=True,
                              pending_resolution=resolution)

    def reopen(self):
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)

    def snapshot(self, flow=None):
        flow = flow or self.flow
        return flow.state, self.journal.history(flow.run_id), self.journal.owners()

    def test_performed_after_reopen_is_debited_once_and_pair_uses_confirmed_stock(self):
        pending = self.pending_dilution()
        prefix = self.journal.history(self.flow.run_id)
        owners = self.journal.owners()
        self.reopen()
        self.assertEqual(self.flow.state['status'], 'held')
        self.assertEqual(self.journal.owners(), owners)
        self.resolve('performed', pending)
        state = self.flow.state
        self.assertIsNone(state['pending_dilution'])
        self.assertEqual(state['inventory']['vessels'][ORIGINAL]['content_revision'], 1)
        stock = state['inventory']['vessels'][pending['target_vessel_id']]
        self.assertEqual((stock['initial_volume_ul'], stock['external_factor']), (20, 10))
        self.assertEqual(stock['location'], stock['home'])
        context = state['contexts'][state['active_context_id']]
        self.assertEqual(context['source_vessel_id'], stock['id'])
        self.assertEqual(context['local']['status'], 'ready')
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.resolve('performed', pending)
        self.assertEqual(self.snapshot(), before)
        run_synthetic(self.flow)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 38)
        self.assertEqual(report['inventory']['vessels'][stock['id']]['disposed_remaining_volume_ul'], 16.5)
        self.assertEqual(len(report['bookings']), 3)
        self.assertEqual(self.journal.history(self.flow.run_id)[:len(prefix)], prefix)

    def test_not_performed_keeps_original_and_requires_new_intent_for_retry(self):
        pending = self.pending_dilution()
        self.reopen()
        self.resolve('not_performed', pending)
        state = self.flow.state
        original = state['inventory']['vessels'][ORIGINAL]
        self.assertEqual(original['content_revision'], 0)
        self.assertFalse(original['mass_confirmation_valid'])
        self.assertEqual(self.flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 40)
        self.assertEqual(state['bookings'][pending['intent_id']]['outcome'], 'not_performed')
        target = state['inventory']['vessels'][pending['target_vessel_id']]
        self.assertEqual((target['content_state'], target['initial_volume_ul']), ('empty', 0))
        before = self.snapshot()
        run_synthetic(self.flow)
        self.assertEqual(self.snapshot(), before)
        self.flow.dispose_material(ACTOR, target['id'], observed_vessel_id=target['id'],
                                   reason='Explicit synthetic empty-tube disposal')
        self.flow.choose_dilution(ACTOR, 'DNA01', '1+9')
        retry = self.flow.state['pending_dilution']
        self.assertNotEqual(retry['intent_id'], pending['intent_id'])
        self.assertNotEqual(retry['target_vessel_id'], pending['target_vessel_id'])
        SyntheticBackend().confirm_dilution(self.flow)
        run_synthetic(self.flow)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 38)
        self.assertEqual(report['bookings'][pending['intent_id']]['outcome'], 'not_performed')
        self.assertEqual(report['bookings'][retry['intent_id']]['outcome'], 'performed')

    def test_unknown_keeps_reservations_and_blocks_driver_until_explicit_resolution(self):
        pending = self.pending_dilution('1+19')
        owners = self.journal.owners()
        self.reopen()
        self.resolve('unknown', pending)
        state = self.flow.state
        self.assertEqual(state['status'], 'held')
        self.assertEqual(state['recovery_required'], 'dilution_outcome_unknown')
        self.assertEqual(state['pending_dilution'], pending)
        self.assertEqual(state['bookings'][pending['intent_id']]['outcome'], 'unknown')
        self.assertIsNone(self.flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'])
        self.assertEqual(self.journal.owners(), owners)
        before = self.snapshot()
        with self.assertRaises(TaskError):
            run_synthetic(self.flow)
        self.assertEqual(self.snapshot(), before)
        self.resolve('performed', pending)
        self.assertEqual(self.flow.state['bookings'][pending['intent_id']]['actual_volume_ul'], 2)
        self.assertEqual(self.flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 38)

    def test_recovery_checks_both_vessel_ids_and_declared_home_rack_places(self):
        pending = self.pending_dilution()
        owners = self.journal.owners()
        cases = ['source_identity', 'target_identity', 'sample_identity',
                 'source_rack', 'source_slot', 'target_rack', 'target_slot',
                 'target_held', 'extra_location_key']
        for case in cases:
            with self.subTest(case=case):
                observations = self.flow.inventory_observations()
                by_id = {item['vessel_id']: item for item in observations}
                resolution = self.performed(pending)
                source = by_id[pending['source_vessel_id']]
                target = by_id[pending['target_vessel_id']]
                if case == 'source_identity':
                    resolution['observed_source_vessel_id'] = pending['target_vessel_id']
                elif case == 'target_identity':
                    resolution['observed_target_vessel_id'] = pending['source_vessel_id']
                elif case == 'sample_identity':
                    target['sample_id'] = 'OTHER.DNA'
                elif case == 'target_held':
                    target['location'] = {'kind': 'operator', 'actor_id': ACTOR}
                elif case == 'extra_location_key':
                    target['location']['unexpected'] = 'not-a-home-place'
                else:
                    item = source if case.startswith('source') else target
                    field = 'rack_id' if case.endswith('rack') else 'place_id'
                    item['location'][field] = 'OTHER.' + case
                events = len(self.journal.history(self.flow.run_id))
                with self.assertRaises(ObservationError):
                    self.flow.reconcile(ACTOR, observations, workspace_clear=True,
                                        pending_resolution=resolution)
                state = self.flow.state
                self.assertEqual(state['status'], 'held')
                self.assertEqual(state['pending_dilution'], pending)
                self.assertEqual(state['bookings'][pending['intent_id']]['outcome'], 'intent')
                self.assertEqual(state['inventory']['vessels'][ORIGINAL]['content_revision'], 0)
                self.assertEqual(self.journal.owners(), owners)
                self.assertEqual(len(self.journal.history(self.flow.run_id)), events + 1)
        self.resolve('performed', pending)
        self.assertEqual(self.flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 38)

    def test_explicit_resume_invalidates_old_writer_and_does_not_replay_intent(self):
        pending = self.pending_dilution()
        old = self.flow
        with self.assertRaisesRegex(TaskError, 'explicit resume'):
            Workflow.open(self.journal, old.run_id)
        self.flow = Workflow.open(self.journal, old.run_id, resume=True)
        self.assertNotEqual(self.flow.session, old.session)
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'Stale DNA session'):
            old.confirm_dilution(ACTOR, **{key: value for key, value in self.performed(pending).items()
                                         if key != 'outcome'})
        with self.assertRaisesRegex(TaskError, 'Stale DNA session'):
            old.close()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.flow.state['pending_dilution'], pending)

    def test_cancel_unknown_then_performed_never_starts_a_device_context(self):
        pending = self.pending_dilution()
        self.flow.cancel(ACTOR, 'Synthetic stop during dilution')
        owners = self.journal.owners()
        self.resolve('unknown', pending)
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertTrue(self.flow.state['cancel_requested'])
        self.resolve('performed', pending)
        state = self.flow.state
        self.assertEqual(state['status'], 'cancelling')
        self.assertIsNone(state['active_context_id'])
        self.assertEqual(state['contexts'], {})
        self.assertEqual(state['attempts'][pending['attempt_id']]['status'], 'cancelled_after_dilution')
        self.assertEqual(self.flow.options(), [])
        self.assertEqual(self.journal.owners(), owners)
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.choose_dilution(ACTOR, 'DNA01', 'none')
        with self.assertRaises(TaskError):
            run_synthetic(self.flow)
        self.assertEqual(self.snapshot(), before)
        observations = self.flow.inventory_observations()
        next(item for item in observations if item['vessel_id'] == pending['target_vessel_id'])['location'] = {'kind': 'discarded'}
        self.flow.finish_cancel(ACTOR, observations, workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertFalse(self.flow.report()['passed'])
        self.assertEqual(self.flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 38)
        self.assertEqual(self.journal.owners(), {})

    def test_cancel_persists_across_reopen_and_deadline_without_releasing_resources(self):
        pending = self.pending_dilution()
        self.flow.cancel(ACTOR, 'Synthetic persisted stop')
        owners = self.journal.owners()
        self.flow.advance_time(ACTOR, self.flow.state['deadline_s'])
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertEqual(self.journal.owners(), owners)
        self.reopen()
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertTrue(self.flow.state['cancel_requested'])
        self.resolve('unknown', pending)
        self.flow.advance_time(ACTOR, 1)
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertEqual(self.journal.owners(), owners)
        self.resolve('not_performed', pending)
        self.assertIsNone(self.flow.state['active_context_id'])
        observations = self.flow.inventory_observations()
        next(item for item in observations if item['vessel_id'] == pending['target_vessel_id'])['location'] = {'kind': 'discarded'}
        self.flow.finish_cancel(ACTOR, observations, workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertEqual(self.flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 40)
        self.assertEqual(self.journal.owners(), {})

    def test_observation_rejection_during_cancellation_preserves_stop(self):
        pending = self.pending_dilution()
        self.flow.cancel(ACTOR, 'Synthetic identity uncertainty')
        resolution = self.performed(pending)
        resolution['observed_target_vessel_id'] = 'OTHER.TUBE'
        with self.assertRaises(ObservationError):
            self.flow.reconcile(ACTOR, self.flow.inventory_observations(), True,
                                pending_resolution=resolution)
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertTrue(self.flow.state['cancel_requested'])
        self.resolve('performed', pending)
        self.assertIsNone(self.flow.state['active_context_id'])
        self.assertEqual(self.flow.state['contexts'], {})

    def test_deadline_hold_retains_rack_vessels_and_instruments(self):
        SyntheticBackend().accept_rack(self.flow)
        owners = self.journal.owners()
        self.flow.advance_time(ACTOR, self.flow.state['deadline_s'])
        self.assertEqual(self.flow.state['status'], 'held')
        self.assertEqual(self.flow.state['recovery_required'], 'deadline_exceeded')
        self.assertEqual(self.journal.owners(), owners)
        self.assertTrue(any(resource.startswith('instrument:') for resource in owners))
        self.assertTrue(any(resource.startswith('vessel:') for resource in owners))
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.choose_dilution(ACTOR, 'DNA01', '1+9')
        with self.assertRaises(TaskError):
            run_synthetic(self.flow)
        self.assertEqual(self.snapshot(), before)

    def test_failed_durable_intent_does_not_call_backend_or_create_booking(self):
        backend = SyntheticBackend()
        backend.accept_rack(self.flow)
        before = self.snapshot()
        error = OSError('Injected synthetic journal write failure before intent')
        with mock.patch.object(self.journal, 'append', side_effect=error), \
             mock.patch.object(backend, 'confirm_dilution') as confirm, \
             mock.patch.object(backend, 'run_context') as run_context:
            with self.assertRaises(OSError) as raised:
                run_synthetic(self.flow, initial_dilution='1+9', backend=backend)
            self.assertIs(raised.exception, error)
            confirm.assert_not_called()
            run_context.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.flow.state['bookings'], {})
        self.assertEqual(self.flow.state['attempts'], {})
        self.assertEqual(set(self.flow.state['inventory']['vessels']), {ORIGINAL})

    def test_changed_source_fingerprint_blocks_transition_and_reopen_without_file_edits(self):
        SyntheticBackend().accept_rack(self.flow)
        before = self.snapshot()
        changed = copy.deepcopy(self.flow.state['definition'])
        source = next(iter(changed['source_files_sha256']))
        changed['source_files_sha256'][source] = '0' * 64
        with mock.patch('dna_quantification.load', return_value=changed):
            with self.assertRaisesRegex(TaskError, 'sources/clock changed'):
                self.flow.choose_dilution(ACTOR, 'DNA01', '1+9')
            with self.assertRaisesRegex(TaskError, 'sources/clock changed'):
                Workflow.open(self.journal, self.flow.run_id, resume=True)
        self.assertEqual(self.snapshot(), before)

    def test_second_run_cannot_acquire_held_resources_and_does_not_partially_reserve(self):
        SyntheticBackend().accept_rack(self.flow)
        owners = self.journal.owners()
        other = Workflow.create(self.journal, run_id='SYN.DNA.OVERLAP')
        before = self.snapshot(other)
        with self.assertRaisesRegex(TaskError, 'Resource reserved'):
            SyntheticBackend().accept_rack(other)
        self.assertEqual(self.snapshot(other), before)
        self.assertEqual(other.state['status'], 'created')
        self.assertEqual(other.state['resources'], [])
        self.assertEqual(self.journal.owners(), owners)

    def test_process_crash_after_intent_requires_resume_and_explicit_outcome(self):
        database = self.folder / 'crashed.sqlite3'
        child = """
import os, sys
sys.path.insert(0, sys.argv[2])
from dna_quantification import Workflow
from dna_quantification_demo import ACTOR, SyntheticBackend
from manual_tasks import Journal
journal = Journal(sys.argv[1])
flow = Workflow.create(journal, run_id='SYN.DNA.CRASH')
SyntheticBackend().accept_rack(flow)
flow.choose_dilution(ACTOR, 'DNA01', '1+19')
os._exit(23)
"""
        result = subprocess.run([sys.executable, '-B', '-c', child, str(database), str(ROOT / 'scripts')],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 23, result.stderr)
        journal = Journal(database)
        try:
            before, _ = journal.get_current('SYN.DNA.CRASH')
            pending = before['pending_dilution']
            self.assertEqual(journal.history('SYN.DNA.CRASH')[-1]['kind'], 'dilution_selected')
            owners = journal.owners()
            with self.assertRaisesRegex(TaskError, 'explicit resume'):
                Workflow.open(journal, 'SYN.DNA.CRASH')
            flow = Workflow.open(journal, 'SYN.DNA.CRASH', resume=True)
            self.assertEqual(flow.state['status'], 'held')
            self.assertEqual(flow.state['pending_dilution'], pending)
            self.assertEqual(journal.owners(), owners)
            events = len(journal.history(flow.run_id))
            with self.assertRaises(TaskError):
                run_synthetic(flow)
            self.assertEqual(len(journal.history(flow.run_id)), events)
            self.resolve('performed', pending, flow=flow)
            self.assertEqual(flow.report()['inventory']['vessels'][ORIGINAL]['remaining_volume_ul'], 38)
            self.assertEqual(flow.state['inventory']['vessels'][pending['target_vessel_id']]['initial_volume_ul'], 40)
            self.assertEqual(flow.state['bookings'][pending['intent_id']]['outcome'], 'performed')
        finally:
            journal.close()


if __name__ == '__main__':
    unittest.main()
