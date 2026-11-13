import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import lab_station_transport as transport
from manual_tasks import Journal, TaskError
from manual_workflow import ObservationError


class StationTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'tasks.sqlite3'
        self.journal = Journal(self.path)
        self.runner = transport.TransportRunner.init(self.journal,'World01')
        self.n = 0

    def tearDown(self):
        self.journal.close(); self.temp.cleanup()

    def observation(self,runner=None,phase=None,leg=None):
        self.n += 1
        return transport.demo_observation((runner or self.runner).state,'Obs'+str(self.n),phase=phase,leg=leg)

    def accept(self):
        self.runner.accept('Actor',self.observation())

    def step(self,kind,runner=None,operation=None):
        runner = runner or self.runner
        operation = operation or 'Leg'+str(runner.state['leg'])+'.'+kind
        runner.intent('Actor',operation,kind)
        phase,leg = runner.after(runner.state)
        runner.confirm('Actor',operation,self.observation(runner,phase,leg))

    def test_complete_route_preserves_cargo_and_intent_receipts(self):
        initial = self.runner.state['definition']['cargo']
        report = transport.run_demo(self.runner)
        self.assertTrue(report['passed'])
        self.assertEqual(report['route'],['DNA','CF01','QC','TS01','DNA'])
        self.assertEqual(report['last_confirmed_arrangement']['cargo'],initial)
        self.assertEqual(initial['sample_id'],'SYN.Source01.DNAExtract')
        self.assertEqual(initial['cassette_place_id'],'B1_Tube01')
        self.assertEqual(initial['origin'],{'rack_id':'SYN.ExtractRack01','place_id':'P02'})
        self.assertEqual(len(report['operations']),12)
        events = self.journal.history(self.runner.run_id)
        for index,event in enumerate(events):
            if event['kind']=='operation_confirmed':
                self.assertTrue(events[index-1]['kind'].endswith('_intent'))
        self.assertEqual(report['resources'],[])
        self.assertFalse(report['robot_motion_executed'])
        self.assertFalse(report['instrument_processes_executed'])

    def test_out_of_sequence_and_reset_rejected(self):
        with self.assertRaises(TaskError):self.runner.intent('Actor','Travel','travel')
        self.accept()
        with self.assertRaises(TaskError):self.runner.intent('Actor','Unload','unload')
        with self.assertRaises(TaskError):transport.TransportRunner.init(self.journal,'World01')
        self.assertTrue(self.runner.state['resources'])

    def test_wrong_identity_holds_without_moving_and_retains_reservations(self):
        self.accept(); self.runner.intent('Actor','Load','load')
        wrong = self.observation(phase='loaded')
        wrong['cargo'] = copy.deepcopy(wrong['cargo']); wrong['cargo']['vessel_id']='Other'
        with self.assertRaises(ObservationError):self.runner.confirm('Actor','Load',wrong)
        state = self.runner.state
        self.assertEqual(state['phase'],'at_source'); self.assertEqual(state['status'],'held')
        self.assertIsNotNone(state['pending']); self.assertTrue(state['resources'])
        with self.assertRaises(TaskError):self.runner.confirm('Actor','Load',self.observation(phase='loaded'))
        self.runner.reconcile('Actor',self.observation(phase='loaded'),resolution='performed',operation_id='Load')
        self.assertEqual(self.runner.state['phase'],'loaded')

    def test_missing_or_false_holding_and_numeric_boolean_rejected(self):
        self.accept(); self.runner.intent('Actor','Load','load')
        for value in (False,1,None):
            obs = self.observation(phase='loaded'); obs['holding_confirmed']=value
            with self.assertRaises(ObservationError):
                if self.runner.state['status']=='held':
                    self.runner.reconcile('Actor',obs,resolution='performed',operation_id='Load')
                else:self.runner.confirm('Actor','Load',obs)
        self.assertEqual(self.runner.state['phase'],'at_source')

    def test_restart_with_pending_travel_never_assumes_arrival(self):
        self.accept(); self.step('load'); self.runner.intent('Actor','Travel','travel')
        stale = self.runner
        self.journal.close(); self.journal = Journal(self.path)
        with self.assertRaises(TaskError):transport.TransportRunner.open(self.journal,'World01')
        resumed = transport.TransportRunner.open(self.journal,'World01',resume=True)
        self.assertEqual(resumed.state['phase'],'loaded')
        self.assertTrue(resumed.report()['location_uncertain'])
        self.assertTrue(resumed.state['resources'])
        with self.assertRaises(TaskError):resumed.intent('Actor','Again','travel')
        stale.journal = self.journal
        with self.assertRaises(TaskError):stale.confirm('Actor','Travel',self.observation(resumed,'arrived'))
        resumed.reconcile('Actor',self.observation(resumed),resolution='not_performed',operation_id='Travel')
        self.step('travel',resumed,'RetryTravel')
        self.assertEqual(resumed.state['phase'],'arrived')

    def test_no_departure_without_explicit_station_release(self):
        self.accept(); self.runner.intent('Actor','Load','load')
        observation = self.observation(phase='loaded')
        del observation['station_release_confirmed']
        with self.assertRaises(ObservationError):self.runner.confirm('Actor','Load',observation)
        self.assertEqual(self.runner.state['phase'],'at_source')
        self.assertTrue(self.runner.state['resources'])

    def test_reused_observation_cannot_confirm_another_action(self):
        obs = self.observation(); self.runner.accept('Actor',obs)
        self.runner.intent('Actor','Load','load')
        obs.update(transport.arrangement(self.runner.state,'loaded'))
        with self.assertRaises(ObservationError):self.runner.confirm('Actor','Load',obs)

    def test_source_changes_block_resumption(self):
        from unittest.mock import patch
        with patch.object(transport,'verify_sources',side_effect=TaskError('Source changed')):
            with self.assertRaises(TaskError):transport.TransportRunner.open(self.journal,'World01',resume=True)

    def test_journal_failure_has_no_confirmation_or_next_effect(self):
        from unittest.mock import patch
        self.accept(); before = self.runner.state
        with patch.object(self.journal,'append',side_effect=TaskError('Disk full')):
            with self.assertRaises(TaskError):self.runner.intent('Actor','Load','load')
        self.assertEqual(self.runner.state,before)
        with self.assertRaises(TaskError):self.runner.confirm('Actor','Load',self.observation(phase='loaded'))


if __name__=='__main__':unittest.main()
