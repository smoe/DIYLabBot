"""The device's operator view cannot authorize physical agent handling."""
import copy
import unittest

import test_dna_quantification_execution as fixtures

from dna_quantification_demo import ACTOR
from dna_quantification_stages import build_adapter
from dna_quantification_tasks import MockTaskWorker
from manual_tasks import TaskError


class DnaAgentProjectionTests(unittest.TestCase):
    setUp = fixtures.DnaQuantificationExecutionTests.setUp
    tearDown = fixtures.DnaQuantificationExecutionTests.tearDown
    ready_nd = fixtures.DnaQuantificationExecutionTests.ready_nd

    def transfer(self, context, target):
        if self.flow.stage(context).state['actor_id'] is None:
            self.backend._claim(self.flow.stage(context))
        worker = MockTaskWorker('SYN.DNA.ProjectionAgent')
        goal = self.flow.task_goal(context, target, worker.agent_id)
        self.flow.intend_task(ACTOR, goal)
        self.flow.dispatch_task(ACTOR, goal['goal_id'], worker)
        self.flow.observe_task(ACTOR, goal['goal_id'], {
            'sample_id': goal['sample_id'], 'vessel_id': goal['vessel_id'],
            'location': target}, evidence='synthetic_backend')

    def snapshot(self):
        return (self.flow.state, self.journal.history(self.flow.run_id), self.journal.owners())

    def test_direct_take_after_observed_worker_return_is_eventless_and_keeps_rack_location(self):
        context = self.ready_nd()
        home = copy.deepcopy(self.flow.state['inventory']['vessels']['SYN.DNA.Tube01']['home'])
        self.transfer(context, {'kind': 'agent', 'agent_id': 'SYN.DNA.ProjectionAgent'})
        self.transfer(context, home)
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.stage(context).act('take', ACTOR, sample_id='DNA01', observed_sample_id='DNA01',
                rack_id=home['rack_id'], place_id=home['place_id'])
        self.assertEqual(self.snapshot(), before)

    def test_direct_place_cannot_turn_the_operator_view_into_agent_return_authority(self):
        context = self.ready_nd()
        self.transfer(context, {'kind': 'agent', 'agent_id': 'SYN.DNA.ProjectionAgent'})
        vessel = self.flow.state['inventory']['vessels']['SYN.DNA.Tube01']
        self.assertEqual(vessel['location']['kind'], 'agent')
        self.assertEqual(self.flow.stage(context).state['samples']['DNA01']['location'],
            {'kind': 'operator', 'actor_id': ACTOR})
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.flow.stage(context).act('place', ACTOR, sample_id='DNA01', observed_sample_id='DNA01',
                rack_id=vessel['home']['rack_id'], place_id=vessel['home']['place_id'])
        self.assertEqual(self.snapshot(), before)

    def test_detached_operator_setter_requires_the_explicit_task_observation_context(self):
        context = self.ready_nd()
        self.transfer(context, {'kind': 'agent', 'agent_id': 'SYN.DNA.ProjectionAgent'})
        self.transfer(context, self.flow.state['inventory']['vessels']['SYN.DNA.Tube01']['home'])
        state = self.flow.state
        before = copy.deepcopy(state)
        sample = build_adapter(self.flow, state, context).state['samples']['DNA01']
        with self.assertRaises(TaskError):
            sample['location'] = {'kind': 'operator', 'actor_id': ACTOR}
        self.assertEqual(state, before)


if __name__ == '__main__':
    unittest.main()
