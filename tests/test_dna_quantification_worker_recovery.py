"""Persisted worker uncertainty needs observations after a real runtime restart."""
import copy
import json
import unittest
from unittest import mock

import test_dna_quantification_control as control_fixtures
import test_dna_quantification_execution as execution_fixtures

from dna_quantification_demo import ACTOR
from dna_quantification_tasks import MockTaskWorker
from dna_sila2_runtime import DNARuntime
from manual_tasks import Journal, TaskError


class DnaWorkerRuntimeRecoveryTests(unittest.TestCase):
    setUp = control_fixtures.DNAControlTests.setUp
    tearDown = control_fixtures.DNAControlTests.tearDown
    command = control_fixtures.DNAControlTests.command
    state = control_fixtures.DNAControlTests.state
    history = control_fixtures.DNAControlTests.history
    create = control_fixtures.DNAControlTests.create
    run_pair = control_fixtures.DNAControlTests.run_pair

    def owners(self):
        with Journal(self.runtime.journal_path) as journal:
            return journal.owners()

    def interrupt_at(self, status):
        self.create()

        def expire_at_worker_boundary():
            state = self.state()
            goal_id = state.get('task_port', {}).get('pending_goal_id')
            if goal_id and state['task_port']['goals'][goal_id]['status'] == status:
                raise PermissionError('Injected interruption after worker ' + status)

        dispatched = []
        original_dispatch = MockTaskWorker.dispatch

        def dispatch(worker, goal):
            dispatched.append(copy.deepcopy(goal))
            return original_dispatch(worker, goal)

        with mock.patch.object(MockTaskWorker, 'dispatch', dispatch):
            response = self.runtime.command('RunUntilDecision', {
                'request_identifier': 'interrupted-worker', 'run_identifier': self.run_id,
                'initial_dilution': 'none', 'after_range': '',
                'nanodrop_concentration': 50., 'qubit_concentration': 48.,
                'qubit_report_original': False}, 'network.operator', guard=expire_at_worker_boundary)
        self.assertEqual(response['error'], 'ReconciliationRequired')
        self.assertEqual(len(dispatched), 1)
        state = self.state()
        goal_id = state['task_port']['pending_goal_id']
        record = state['task_port']['goals'][goal_id]
        self.assertEqual(record['status'], status)
        self.assertEqual(record['goal'], dispatched[0])
        self.assertEqual(state['bookings'], {})
        self.assertEqual(state['inventory']['vessels']['SYN.DNA.Tube01']['location'],
                         state['inventory']['vessels']['SYN.DNA.Tube01']['home'])
        self.assertTrue(self.owners())
        return copy.deepcopy(record)

    def restart_and_resume(self, record, expected_status='held'):
        before = self.state()
        owners = self.owners()
        old_boot = self.runtime.boot_id
        self.runtime.close()
        self.runtime = DNARuntime(self.directory)
        self.assertNotEqual(self.runtime.boot_id, old_boot)
        history = self.history()
        with mock.patch.object(MockTaskWorker, 'dispatch') as dispatch:
            with self.assertRaisesRegex(TaskError, 'ResumeRun'):
                self.run_pair('before-explicit-resume')
            self.assertEqual(self.history(), history)
            self.command('ResumeRun', 'resume-worker', resume=True)
            dispatch.assert_not_called()
        state = self.state()
        goal_id = record['goal']['goal_id']
        current = state['task_port']['goals'][goal_id]
        self.assertEqual(current['status'], 'uncertain')
        self.assertEqual(current['goal'], record['goal'])
        self.assertEqual(current['claim'], record['claim'])
        self.assertEqual(current['worker_boot_id'], record['worker_boot_id'])
        self.assertEqual(state['task_port']['pending_goal_id'], goal_id)
        self.assertEqual(state['status'], expected_status)
        self.assertEqual(state['inventory'], before['inventory'])
        self.assertEqual(state['bookings'], before['bookings'])
        self.assertEqual(self.owners(), owners)

    @staticmethod
    def observations(record, outcome):
        goal = record['goal']
        location = ({'kind': 'agent', 'agent_id': goal['target_agent_id']}
                    if outcome == 'performed' else
                    {'kind': 'rack', 'rack_id': goal['source_rack_id'],
                     'place_id': goal['source_place_id']})
        return [{'vessel_id': 'SYN.DNA.Tube01', 'sample_id': 'DNA01', 'location': location}]

    def check_restart_resolution(self, status, outcome):
        record = self.interrupt_at(status)
        self.restart_and_resume(record)
        goal_id = record['goal']['goal_id']
        owners = self.owners()
        with mock.patch.object(MockTaskWorker, 'dispatch') as dispatch:
            self.command('ReconcileInventory', 'observe-worker-' + outcome,
                observation_json=json.dumps({'observations': self.observations(record, outcome),
                    'workspace_clear': True, 'task_resolution': {'goal_id': goal_id, 'outcome': outcome}}))
            dispatch.assert_not_called()
        state = self.state()
        self.assertEqual(state['bookings'], {})
        self.assertEqual(self.owners(), owners)
        if outcome == 'unknown':
            self.assertEqual(state['task_port']['goals'][goal_id]['status'], 'uncertain')
            self.assertEqual(state['task_port']['pending_goal_id'], goal_id)
            self.assertEqual(state['status'], 'held')
            self.assertEqual(state['recovery_required'], 'task_outcome_unknown')
            history = self.history()
            with mock.patch.object(MockTaskWorker, 'dispatch') as dispatch:
                with self.assertRaises(TaskError):
                    self.run_pair('still-unknown')
                dispatch.assert_not_called()
            self.assertEqual(self.history(), history)
            self.assertEqual(self.state(), state)
            return
        self.assertEqual(state['task_port']['goals'][goal_id]['status'], 'reconciled_' + outcome)
        self.assertIsNone(state['task_port']['pending_goal_id'])
        self.assertEqual(state['inventory']['vessels']['SYN.DNA.Tube01']['location'],
                         self.observations(record, outcome)[0]['location'])
        dispatched = []
        original_dispatch = MockTaskWorker.dispatch

        def dispatch(worker, goal):
            dispatched.append(copy.deepcopy(goal))
            return original_dispatch(worker, goal)

        with mock.patch.object(MockTaskWorker, 'dispatch', dispatch):
            self.run_pair('continue-observed-worker')
        self.assertTrue(dispatched)
        self.assertNotIn(goal_id, [goal['goal_id'] for goal in dispatched])
        report = self.runtime.report(self.run_id)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)
        self.assertEqual(self.owners(), {})

    def test_dispatched_restart_performed_is_observed_without_redispatch(self):
        self.check_restart_resolution('dispatched', 'performed')

    def test_dispatched_restart_not_performed_allows_only_a_new_goal(self):
        self.check_restart_resolution('dispatched', 'not_performed')

    def test_dispatched_restart_unknown_keeps_holds_and_blocks_dispatch(self):
        self.check_restart_resolution('dispatched', 'unknown')

    def test_claimed_restart_performed_is_observed_without_redispatch(self):
        self.check_restart_resolution('claimed', 'performed')

    def test_claimed_restart_not_performed_allows_only_a_new_goal(self):
        self.check_restart_resolution('claimed', 'not_performed')

    def test_claimed_restart_unknown_keeps_holds_and_blocks_dispatch(self):
        self.check_restart_resolution('claimed', 'unknown')

    def test_cancel_run_survives_restart_and_releases_only_after_full_reconciliation(self):
        record = self.interrupt_at('claimed')
        self.command('CancelRun', 'cancel-root', reason='Explicit cancellation with unresolved worker custody')
        self.restart_and_resume(record, expected_status='cancelling')
        owners = self.owners()
        history = self.history()
        with self.assertRaises(TaskError):
            self.command('FinishCancel', 'unresolved-task-cancel', observation_json=json.dumps({
                'observations': [], 'workspace_clear': True}))
        self.assertEqual(self.history(), history)
        self.assertEqual(self.state()['status'], 'cancelling')
        self.assertTrue(self.state()['cancel_requested'])
        self.assertEqual(self.owners(), owners)
        observations = self.observations(record, 'not_performed')
        self.command('ReconcileInventory', 'resolve-cancelled-worker', observation_json=json.dumps({
            'observations': observations, 'workspace_clear': True,
            'task_resolution': {'goal_id': record['goal']['goal_id'], 'outcome': 'not_performed'}}))
        self.assertEqual(self.state()['status'], 'cancelling')
        self.assertEqual(self.owners(), owners)
        result = self.command('FinishCancel', 'incomplete-cancel', observation_json=json.dumps({
            'observations': [], 'workspace_clear': True}))
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(self.state()['status'], 'cancelling')
        self.assertEqual(self.owners(), owners)
        # A rejected observation must be explicitly reconciled before release.
        self.command('ResumeRun', 'resume-after-incomplete-cancel', resume=True)
        self.command('ReconcileInventory', 'observe-cancelled-inventory', observation_json=json.dumps({
            'observations': observations, 'workspace_clear': True}))
        self.assertEqual(self.state()['status'], 'cancelling')
        self.assertEqual(self.owners(), owners)
        self.command('FinishCancel', 'finish-observed-cancel', observation_json=json.dumps({
            'observations': observations, 'workspace_clear': True}))
        self.assertEqual(self.state()['status'], 'cancelled')
        self.assertEqual(self.state()['resources'], [])
        self.assertEqual(self.state()['bookings'], {})
        self.assertEqual(self.owners(), {})


class DnaWorkerClaimRecoveryTests(unittest.TestCase):
    setUp = execution_fixtures.DnaQuantificationExecutionTests.setUp
    tearDown = execution_fixtures.DnaQuantificationExecutionTests.tearDown
    ready_nd = execution_fixtures.DnaQuantificationExecutionTests.ready_nd

    def intended(self):
        context_id = self.ready_nd()
        self.backend._claim(self.flow.stage(context_id))
        worker = MockTaskWorker('SYN.Recovery.Agent', boot_id='SYN.Recovery.Boot')
        goal = self.flow.task_goal(context_id,
            {'kind': 'agent', 'agent_id': worker.agent_id}, worker.agent_id)
        self.flow.intend_task(ACTOR, goal)
        return goal, worker

    def snapshot(self):
        return self.flow.state, self.journal.history(self.flow.run_id), self.journal.owners()

    def test_worker_dispatch_exception_holds_without_custody_or_consumption(self):
        goal, worker = self.intended()
        before = self.flow.state
        owners = self.journal.owners()
        with mock.patch.object(worker, 'dispatch', side_effect=RuntimeError('Injected worker dispatch failure')):
            with self.assertRaisesRegex(RuntimeError, 'Injected worker dispatch failure'):
                self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        state = self.flow.state
        self.assertEqual(state['task_port']['goals'][goal['goal_id']]['status'], 'uncertain')
        self.assertEqual(state['task_port']['goals'][goal['goal_id']]['uncertainty_reason'], 'worker_failure')
        self.assertEqual(state['task_port']['pending_goal_id'], goal['goal_id'])
        self.assertEqual(state['status'], 'held')
        self.assertEqual(state['recovery_required'], 'task_outcome_unknown')
        self.assertEqual(state['inventory'], before['inventory'])
        self.assertEqual(state['bookings'], before['bookings'])
        self.assertEqual(state['resources'], before['resources'])
        self.assertEqual(self.journal.owners(), owners)

    def test_restarted_worker_claim_is_rejected_without_an_event_or_custody_change(self):
        goal, worker = self.intended()
        with mock.patch.object(self.flow, 'record_task_claim', side_effect=TaskError('Injected claim boundary')):
            with self.assertRaisesRegex(TaskError, 'Injected claim boundary'):
                self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        restarted = MockTaskWorker(worker.agent_id, boot_id='SYN.Recovery.NewBoot')
        claim = restarted.dispatch(goal)
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.record_task_claim(ACTOR, goal['goal_id'], claim)
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_claim_is_rejected_without_an_event_or_custody_change(self):
        goal, worker = self.intended()
        claim = self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        conflict = {**claim, 'claim_id': 'SYN.Conflicting.Claim'}
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'Conflicting worker claim'):
            self.flow.record_task_claim(ACTOR, goal['goal_id'], conflict)
        self.assertEqual(self.snapshot(), before)

    def test_late_claim_after_reconciliation_cannot_reopen_a_goal(self):
        goal, worker = self.intended()
        claim = self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        self.flow.reconcile(ACTOR, self.flow.inventory_observations(), workspace_clear=True,
            task_resolution={'goal_id': goal['goal_id'], 'outcome': 'not_performed'})
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.record_task_claim(ACTOR, goal['goal_id'], claim)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
