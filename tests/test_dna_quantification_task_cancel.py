"""Goal cancellation cannot reopen retired tasks or release root resources."""
import copy
import unittest
from unittest import mock

import test_dna_quantification_execution as execution_fixtures

from dna_quantification_demo import ACTOR
from dna_quantification_tasks import MockTaskWorker
from manual_tasks import TaskError


class DnaTaskCancellationTests(unittest.TestCase):
    setUp = execution_fixtures.DnaQuantificationExecutionTests.setUp
    tearDown = execution_fixtures.DnaQuantificationExecutionTests.tearDown
    ready_nd = execution_fixtures.DnaQuantificationExecutionTests.ready_nd

    def intended(self):
        context_id = self.ready_nd()
        self.backend._claim(self.flow.stage(context_id))
        worker = MockTaskWorker('SYN.Cancel.Agent', boot_id='SYN.Cancel.Boot')
        goal = self.flow.task_goal(context_id,
            {'kind': 'agent', 'agent_id': worker.agent_id}, worker.agent_id)
        self.flow.intend_task(ACTOR, goal)
        return goal, worker

    def snapshot(self):
        return self.flow.state, self.journal.history(self.flow.run_id), self.journal.owners()

    def assert_rejected_without_event(self, goal_id):
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.cancel_task(ACTOR, goal_id)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_goal_is_rejected_without_an_event(self):
        self.assert_rejected_without_event('SYN.Unknown.Goal')

    def test_unknown_goal_in_existing_port_is_rejected_without_an_event(self):
        self.intended()
        self.assert_rejected_without_event('SYN.Unknown.Goal')

    def test_cancel_intended_goal_holds_custody_and_resources(self):
        goal, _ = self.intended()
        before = self.flow.state
        owners = self.journal.owners()
        self.flow.cancel_task(ACTOR, goal['goal_id'])
        state = self.flow.state
        self.assertEqual(state['task_port']['goals'][goal['goal_id']]['status'], 'cancel_requested')
        self.assertEqual(state['task_port']['pending_goal_id'], goal['goal_id'])
        self.assertEqual(state['status'], 'held')
        self.assertEqual(state['recovery_required'], 'task_cancel_requires_observation')
        self.assertEqual(state['inventory'], before['inventory'])
        self.assertEqual(state['bookings'], before['bookings'])
        self.assertEqual(state['resources'], before['resources'])
        self.assertEqual(self.journal.owners(), owners)
        self.assertIn('agent:SYN.Cancel.Agent', owners)

    def test_cancel_dispatched_goal_preserves_pending_hold(self):
        goal, worker = self.intended()
        with mock.patch.object(self.flow, 'record_task_claim', side_effect=TaskError('Injected claim boundary')):
            with self.assertRaisesRegex(TaskError, 'Injected claim boundary'):
                self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        self.assertEqual(self.flow.state['task_port']['goals'][goal['goal_id']]['status'], 'dispatched')
        before = self.flow.state
        owners = self.journal.owners()
        self.flow.cancel_task(ACTOR, goal['goal_id'])
        self.assertEqual(self.flow.state['task_port']['pending_goal_id'], goal['goal_id'])
        self.assertEqual(self.flow.state['status'], 'held')
        self.assertEqual(self.flow.state['inventory'], before['inventory'])
        self.assertEqual(self.flow.state['bookings'], before['bookings'])
        self.assertEqual(self.journal.owners(), owners)

    def test_cancel_claimed_goal_rejects_late_claim_and_keeps_holds(self):
        goal, worker = self.intended()
        claim = self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        self.flow.cancel(ACTOR, 'Explicit root cancellation with an open worker task')
        owners = self.journal.owners()
        self.flow.cancel_task(ACTOR, goal['goal_id'])
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertEqual(self.journal.owners(), owners)
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.record_task_claim(ACTOR, goal['goal_id'], claim)
        self.assertEqual(self.snapshot(), before)
        self.assert_rejected_without_event(goal['goal_id'])

    def test_observed_goal_is_rejected_without_an_event(self):
        goal, worker = self.intended()
        self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        self.flow.observe_task(ACTOR, goal['goal_id'], {
            'sample_id': goal['sample_id'], 'vessel_id': goal['vessel_id'],
            'location': {'kind': 'agent', 'agent_id': worker.agent_id}})
        self.assert_rejected_without_event(goal['goal_id'])

    def reconciled(self, outcome):
        goal, worker = self.intended()
        self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        observations = self.flow.inventory_observations()
        if outcome == 'performed':
            observations[0]['location'] = {'kind': 'agent', 'agent_id': worker.agent_id}
        self.flow.reconcile(ACTOR, observations, workspace_clear=True,
            task_resolution={'goal_id': goal['goal_id'], 'outcome': outcome})
        self.assertEqual(self.flow.state['task_port']['goals'][goal['goal_id']]['status'],
                         'reconciled_' + outcome)
        self.assertIsNone(self.flow.state['task_port']['pending_goal_id'])
        return goal

    def test_reconciled_performed_goal_is_rejected_without_an_event(self):
        self.assert_rejected_without_event(self.reconciled('performed')['goal_id'])

    def test_reconciled_not_performed_goal_is_rejected_without_an_event(self):
        self.assert_rejected_without_event(self.reconciled('not_performed')['goal_id'])

    def test_uncertain_goal_is_rejected_without_an_event(self):
        goal, _ = self.intended()
        self.flow.mark_task_uncertain(ACTOR, goal['goal_id'], 'Explicit unknown task outcome')
        self.assert_rejected_without_event(goal['goal_id'])

    def test_open_record_without_pending_binding_is_rejected_without_an_event(self):
        goal, _ = self.intended()
        state, revision = self.journal.get_current(self.flow.run_id)
        state = copy.deepcopy(state)
        state['task_port']['pending_goal_id'] = None
        self.journal.append(self.flow.run_id, revision, 'test_pending_binding_loss',
            {'evidence': 'synthetic_input'}, state)
        self.assert_rejected_without_event(goal['goal_id'])


if __name__ == '__main__':
    unittest.main()
