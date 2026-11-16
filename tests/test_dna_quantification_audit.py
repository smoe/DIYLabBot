"""Audit identity and evidence for rejected, expired and worker-claim events."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_quantification import Workflow
from dna_quantification_tasks import MockTaskWorker
from manual_tasks import Journal, TaskError
from manual_workflow import ObservationError


class DNAQuantificationAuditTests(unittest.TestCase):
    ACTOR = 'SYN.DNA.AuditOperator'
    AGENT = 'SYN.DNA.AuditWorker'

    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-audit-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.journal = Journal(self.directory / 'local.sqlite3')
        self.addCleanup(self.journal.close)
        self.flow = Workflow.create(self.journal, run_id='SYN.DNA.Audit')

    def assert_no_material_effect(self, before, owners):
        after = self.flow.state
        self.assertEqual(after['inventory'], before['inventory'])
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertEqual(self.journal.owners(), owners)

    def test_rejected_initial_observation_records_the_actual_actor(self):
        before = self.flow.state
        self.assertIsNone(before['actor_id'])
        prefix = self.journal.history(self.flow.run_id)
        owners = self.journal.owners()
        with self.assertRaises(ObservationError):
            self.flow.accept_rack(self.ACTOR, [], workspace_clear=True,
                rack_on_table_confirmed=True)
        events = self.journal.history(self.flow.run_id)
        self.assertEqual(events[:-1], prefix)
        self.assertEqual(events[-1]['kind'], 'observation_rejected')
        self.assertEqual(events[-1]['payload']['actor_id'], self.ACTOR)
        self.assertEqual(events[-1]['payload']['evidence'], 'synthetic_input')
        self.assertIsNone(self.flow.state['actor_id'], 'Rejected observation must not claim the run')
        self.assertEqual(self.flow.state['recovery_required'], 'observation_mismatch')
        self.assert_no_material_effect(before, owners)

    def test_initial_deadline_rejection_records_the_actual_actor(self):
        state, revision = self.journal.get_current(self.flow.run_id)
        self.assertIsNone(state['actor_id'])
        # advance_time already records its own recovery hold. Seed the explicit
        # synthetic boundary needed to exercise the separate deadline audit
        # branch, then enter that branch through the public accept_rack API.
        state['logical_time_s'] = state['deadline_s']
        self.journal.append(self.flow.run_id, revision, 'synthetic_clock_boundary_fixture',
            {'evidence': 'test_fixture', 'reason': 'Expired clock before the first rack acceptance'}, state)
        before = self.flow.state
        owners = self.journal.owners()
        prefix = self.journal.history(self.flow.run_id)
        with self.assertRaisesRegex(TaskError, 'deadline'):
            self.flow.accept_rack(self.ACTOR, self.flow.inventory_observations(),
                workspace_clear=True, rack_on_table_confirmed=True)
        events = self.journal.history(self.flow.run_id)
        self.assertEqual(events[:-1], prefix)
        self.assertEqual(events[-1]['kind'], 'deadline_exceeded')
        self.assertEqual(events[-1]['payload']['actor_id'], self.ACTOR)
        self.assertEqual(events[-1]['payload']['evidence'], 'synthetic_input')
        self.assertIsNone(self.flow.state['actor_id'], 'Deadline rejection must not claim the run')
        self.assertEqual(self.flow.state['recovery_required'], 'deadline_exceeded')
        self.assert_no_material_effect(before, owners)

    def test_local_worker_claim_is_explicit_evidence_without_material_booking(self):
        self.flow.accept_rack(self.ACTOR, self.flow.inventory_observations(),
            workspace_clear=True, rack_on_table_confirmed=True)
        self.flow.choose_dilution(self.ACTOR, 'DNA01', 'none')
        goal = self.flow.task_goal(self.flow.state['active_context_id'],
            {'kind': 'agent', 'agent_id': self.AGENT}, self.AGENT, goal_id='audit-worker-goal')
        self.flow.intend_task(self.ACTOR, goal)
        before = copy.deepcopy(self.flow.state)
        owners = self.journal.owners()
        prefix = self.journal.history(self.flow.run_id)
        claim = self.flow.dispatch_task(self.ACTOR, goal['goal_id'],
            MockTaskWorker(self.AGENT, boot_id='audit-worker-boot'))
        events = self.journal.history(self.flow.run_id)
        self.assertEqual(events[:len(prefix)], prefix)
        self.assertEqual([event['kind'] for event in events[len(prefix):]],
            ['task.dispatched', 'task.claimed'])
        payload = events[-1]['payload']
        self.assertEqual(payload['actor_id'], self.ACTOR)
        self.assertEqual(payload['evidence'], 'worker_claim')
        self.assertEqual(payload['claim'], claim)
        self.assertEqual(claim['evidence'], 'worker_claim')
        self.assertFalse(claim['motion_executed'])
        after = self.flow.state
        self.assertEqual(after['task_port']['goals'][goal['goal_id']]['status'], 'claimed')
        self.assertIsNone(after['task_port']['goals'][goal['goal_id']]['root_observation'])
        self.assertEqual(after['task_port']['pending_goal_id'], goal['goal_id'])
        self.assertEqual(after['bookings'], {})
        self.assert_no_material_effect(before, owners)


if __name__ == '__main__':
    unittest.main()
