"""T2 acceptance against the existing twelve-vessel laboratory operations.

The prerequisite database is produced by one real local CF01 mock run. Each
case receives an isolated copy of that completely journaled test-world prefix;
no fabricated successful stage or inventory snapshot is injected. These copies
are test fixtures, not supported production inventory continuation.
"""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from async_transport_adapters import HumanTeleportMock, RobotTeleportMock
from lab_transport_workflow import TransportWorkflow
from lab_workflow import Workflow
from lab_workflow_ledger import original_location, remaining
from manual_tasks import Journal, TaskError, digest
from manual_workflow import inventory_observations
from nanodrop_manual import Workflow as NanoDrop
from run_lab_workflow import ACTOR, run_nanodrop, run_qubit
from run_nanodrop_manual import synthetic_report as nanodrop_report


class LabTransportAcceptanceTests(unittest.TestCase):
    RUN = 'SYN.Lab.Transport.Acceptance'

    @classmethod
    def setUpClass(cls):
        (ROOT / 'exports').mkdir(exist_ok=True)
        cls.fixture = tempfile.TemporaryDirectory(prefix='lab-transport-acceptance-', dir=ROOT / 'exports')
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.folder = Path(cls.fixture.name)
        cls.prerequisite = cls.folder / 'cf01-prefix.sqlite3'
        with Journal(cls.prerequisite) as journal:
            flow = TransportWorkflow.create(journal, run_id=cls.RUN)
            flow.accept_rack(ACTOR, observations=flow.inventory_observations())
            for sample in flow.state['definition']['manifest']['samples']:
                flow.confirm_mass(ACTOR, sample['vessel_id'], mass_g=2.0, content_revision=0)
            report = flow.run_cf01(ACTOR)
            if not report['passed']:
                raise AssertionError('The real prerequisite CF01 mock did not pass')
            cls.session = flow.session
            cls.prerequisite_state = flow.state
            cls.prerequisite_events = len(journal.history(cls.RUN))

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.folder)
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'workflow.sqlite3'
        shutil.copyfile(self.prerequisite, self.path)
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.flow = TransportWorkflow(self.journal, self.RUN, session=self.session)
        self.counter = 0

    def request_id(self, prefix='Acceptance'):
        self.counter += 1
        return prefix + '.' + str(self.counter)

    def prepare(self, route='CF01ToNanoDrop', job='CF01.Out'):
        return self.flow.prepare_transport(ACTOR, route, job, self.request_id('Prepare'))

    def dispatch(self, job='CF01.Out', robot=False, reverse=False):
        kind = RobotTeleportMock if robot else HumanTeleportMock
        adapter = kind('AgentRobot' if robot else 'AgentHuman',
                       order=('delivery_accept', 'delivery_release', 'pickup_accept', 'pickup_release')
                       if reverse else None)
        result = self.flow.dispatch_transport(job, adapter, ACTOR, self.request_id('Dispatch'))
        self.assertFalse(result['replayed'])
        return result['batch']

    def deliver_cf01(self):
        self.prepare()
        batch = self.dispatch()
        self.flow.ingest_transport(batch)
        return batch

    def handover(self):
        return self.flow.handover(ACTOR, observations=self.flow.inventory_observations(),
                                  workspace_clear=True, arm_clear=True, gripper_empty=True)

    def assert_receiver_blocked(self, stage_id):
        self.assertFalse(self.flow.state['stages'][stage_id]['rack_ready'])
        revision = self.journal.get_current(self.RUN)[1]
        with self.assertRaises(TaskError):
            self.handover()
        with self.assertRaises(TaskError):
            self.flow.stage(stage_id).act('claim', ACTOR)
        self.assertEqual(self.journal.get_current(self.RUN)[1], revision)

    def test_cf01_completion_waits_for_transport_without_duplicating_inventory(self):
        state = self.flow.state
        self.assertEqual(state['stages']['cf01']['status'], 'completed')
        self.assertEqual(set(state['inventory']), {'vessels'})
        self.assertEqual(len(state['inventory']['vessels']), 12)
        self.assertEqual(state['definition']['rack_instance'], 'Rack')
        self.assertEqual(state['bookings'], {})
        self.assertNotIn('inventory', state['transport'])
        self.assertNotIn('initial_materials', state['definition']['transport'])
        self.assert_receiver_blocked('nanodrop')
        self.assertFalse(self.flow.report()['passed'])
        self.assertTrue({'rack:Rack', 'vessel:Tube01', 'vessel:Tube12'} <= set(state['resources']))

    def test_worker_claim_and_three_reverse_receipts_cannot_open_receiver(self):
        original_inventory = copy.deepcopy(self.flow.state['inventory'])
        self.prepare()
        batch = self.dispatch(reverse=True)
        self.assert_receiver_blocked('nanodrop')
        for message in batch[:-1]:
            self.flow.ingest_transport([message])
            self.assert_receiver_blocked('nanodrop')
            self.assertEqual(self.flow.state['inventory'], original_inventory)
        self.assertEqual(self.flow.state['transport']['jobs']['CF01.Out']['phase'], 'pickup_pending')
        self.flow.ingest_transport([batch[-1]])
        self.assertTrue(self.flow.state['stages']['nanodrop']['rack_ready'])
        self.assertEqual(self.flow.state['transport']['jobs']['CF01.Out']['phase'], 'completed')
        self.assertEqual(self.flow.state['inventory'], original_inventory)
        self.handover()
        self.flow.stage('nanodrop').act('claim', ACTOR)

    def test_same_owner_cannot_prepare_another_job_for_the_bound_rack(self):
        self.prepare()
        before = self.flow.state
        revision = self.journal.get_current(self.RUN)[1]
        with self.assertRaises(TaskError):
            self.prepare(job='CF01.Duplicate')
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.get_current(self.RUN)[1], revision)
        self.assertEqual(self.flow.state['transport_bindings'], {'CF01ToNanoDrop': 'CF01.Out'})
        self.assertEqual(set(self.flow.state['transport']['jobs']), {'CF01.Out'})

    def test_mass_observation_cannot_bypass_active_transport_payload_claim(self):
        self.prepare()
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.flow.confirm_mass(ACTOR, 'Tube01', mass_g=2.0, content_revision=0)
        self.assertEqual(self.flow.state, before)

    def test_legacy_runner_cannot_reclaim_inflight_originals_under_another_rack(self):
        self.prepare()
        self.dispatch()
        before = self.flow.state
        profile = json.loads(NanoDrop.SOURCE.read_bytes())
        profile['instrument']['id'] = 'SYN.NanoDrop.OtherInstrument'
        profile['workspace']['id'] = 'SYN.NanoDrop.OtherWorkArea'
        other = NanoDrop.create(self.journal, source=profile, run_id='SYN.NanoDrop.ForeignOwner')
        with self.assertRaisesRegex(TaskError, 'vessel:Tube01'):
            other.act('rack_ready', ACTOR, observations=inventory_observations(other.state))
        self.assertEqual(self.flow.state, before)
        self.assertEqual(other.state['resources'], [])
        self.assertEqual(self.journal.owners()['vessel:Tube01'], self.RUN)

    def test_transport_rejects_an_open_nanodrop_withdrawal_and_held_original(self):
        self.deliver_cf01()
        run_nanodrop(self.flow, pause_after_intent=True)
        before = self.flow.state
        self.assertEqual(before['inventory']['vessels']['Tube01']['location']['kind'], 'operator')
        self.assertEqual(len(before['bookings']), 1)
        self.assertEqual(next(iter(before['bookings'].values()))['outcome'], 'intent')
        with self.assertRaises(TaskError):
            self.prepare('NanoDropToQubit', 'NanoDrop.Out')
        self.assertEqual(self.flow.state, before)
        self.assertNotIn('NanoDrop.Out', self.flow.state['transport']['jobs'])

    def test_independent_clock_commit_does_not_drop_inflight_job_or_valid_receipts(self):
        self.prepare()
        batch = self.dispatch()
        before = self.flow.state
        with Journal(self.path) as second:
            other = TransportWorkflow(second, self.RUN, session=self.session)
            other.advance_time(ACTOR, seconds=1)
        updated = self.flow.state
        self.assertEqual(updated['logical_time_s'], before['logical_time_s'] + 1)
        self.assertEqual(updated['transport'], before['transport'])
        self.assertEqual(updated['resources'], before['resources'])
        self.flow.ingest_transport(batch)
        self.assertEqual(self.flow.state['transport']['jobs']['CF01.Out']['phase'], 'completed')
        self.assertTrue(self.flow.state['stages']['nanodrop']['rack_ready'])

    def test_late_conflict_of_completed_transport_blocks_new_sample_work(self):
        batch = self.deliver_cf01()
        self.handover()
        self.flow.stage('nanodrop').act('claim', ACTOR)
        message = copy.deepcopy(batch[1])
        message['request_id'] = 'LateConflict.Request'
        message['args']['observation'].update(observation_id='LateConflict.Observation', manifest_sha256='0' * 64)
        self.flow.ingest_transport([message])
        before = self.flow.state
        self.assertEqual(before['transport']['jobs']['CF01.Out']['control'], 'held')
        with self.assertRaises(TaskError):
            self.flow.stage('nanodrop').act('take', ACTOR, sample_id='Sample01', observed_sample_id='Sample01',
                                           rack_id='Rack', place_id='Slot01')
        self.assertEqual(self.flow.state, before)
        self.assertFalse(self.flow.report()['passed'])
        self.assertTrue({'rack:Rack', 'vessel:Tube01'} <= set(before['resources']))

    def test_legacy_workflow_cannot_be_silently_opened_as_t2(self):
        path = self.path.parent / 'legacy.sqlite3'
        with Journal(path) as journal:
            old = Workflow.create(journal, run_id='SYN.Lab.Legacy')
            before = journal.history(old.run_id)
            with self.assertRaises(TaskError):
                TransportWorkflow.open(journal, old.run_id, resume=True)
            self.assertEqual(journal.history(old.run_id), before)

    def test_full_workflow_imports_while_transport_waits_and_retains_one_balance(self):
        """One full CF01/ND/Qubit run; all prerequisite states come from real handlers."""
        first_batch = self.deliver_cf01()
        first_manifest = copy.deepcopy(self.flow.state['transport']['jobs']['CF01.Out']['manifest'])
        self.assertTrue(all(item['content_revision'] == 0 for item in first_manifest))
        held_batches = []
        original_content = []

        def depart_before_import(flow):
            self.assertIs(flow, self.flow)
            state = flow.state
            self.assertEqual(state['active_stage'], 'nanodrop')
            self.assertEqual(state['stages']['nanodrop']['status'], 'working')
            self.assertEqual(len(state['bookings']), 12)
            self.assertTrue(all(b['outcome'] == 'performed' for b in state['bookings'].values()))
            self.assertTrue(all(v['location'] == original_location(state, v['sample_id'])
                                for v in state['inventory']['vessels'].values()))
            self.assertEqual(remaining(state, 'Sample01'), 38.5)
            self.assertIsNone(remaining(state, 'Sample03'))
            original_content.append(nanodrop_report(flow.stage('nanodrop').state))
            self.prepare('NanoDropToQubit', 'NanoDrop.Out')
            held_batches.append(self.dispatch(job='NanoDrop.Out', robot=True, reverse=True))
            before = flow.state
            with self.assertRaises(TaskError):
                flow.stage('nanodrop').act('take', ACTOR, sample_id='Sample01', observed_sample_id='Sample01',
                                           rack_id='Rack', place_id='Slot01')
            with self.assertRaises(TaskError):
                flow.confirm_mass(ACTOR, 'Tube01', mass_g=2.0, content_revision=1)
            self.assertEqual(flow.state, before)

        run_nanodrop(self.flow, before_import=depart_before_import)
        self.assertEqual(len(held_batches), 1)
        state = self.flow.state
        self.assertEqual(state['stages']['nanodrop']['status'], 'completed')
        self.assertEqual(state['stages']['nanodrop']['result_review']['decision'], 'accepted')
        self.assertEqual(state['transport']['jobs']['NanoDrop.Out']['phase'], 'pickup_pending')
        self.assertEqual(state['transport']['jobs']['CF01.Out']['manifest'], first_manifest)
        self.assertTrue(all(v['content_revision'] == 1 for v in state['inventory']['vessels'].values()))
        self.assertEqual(self.journal.artifact(digest(original_content[0])), original_content[0])
        self.assert_receiver_blocked('qubit')
        self.assertFalse(self.flow.report()['passed'])
        for message in held_batches[0][:-1]:
            self.flow.ingest_transport([message])
            self.assert_receiver_blocked('qubit')
        self.flow.ingest_transport([held_batches[0][-1]])
        self.assertTrue(self.flow.state['stages']['qubit']['rack_ready'])
        run_qubit(self.flow)
        report = self.flow.report()
        state = self.flow.state
        self.assertTrue(report['passed'])
        self.assertTrue(report['existing_workflow_integrated'])
        self.assertTrue(report['transport_passed'])
        self.assertEqual(report['execution_mode'], 'teleportation_mock')
        self.assertEqual(report['transport_time_s'], 0)
        self.assertTrue(report['order_restored'])
        self.assertEqual(len(report['bookings']), 24)
        self.assertEqual(len(report['samples']), 12)
        self.assertEqual(report['samples']['Sample01']['remaining_volume_ul'], 36.5)
        self.assertIsNone(report['samples']['Sample03']['remaining_volume_ul'])
        self.assertEqual(report['samples']['Sample03']['withdrawn_volume_ul'], 3.5)
        self.assertEqual({b['stage_id'] for b in report['bookings'].values()}, {'nanodrop', 'qubit'})
        self.assertTrue(all(s['content_revision'] == 2 for s in report['samples'].values()))
        for index, sample in enumerate(report['samples'].values(), 1):
            self.assertEqual(sample['location'], {'kind': 'rack', 'rack_id': 'Rack', 'place_id': 'Slot%02d' % index})
        self.assertEqual(len(report['stages']['qubit']['results']), 14)
        self.assertEqual(set(state['transport_bindings']), {'CF01ToNanoDrop', 'NanoDropToQubit'})
        self.assertTrue(all(j['phase'] == 'completed' and j['control'] == 'active'
                            for j in state['transport']['jobs'].values()))
        self.assertTrue({'rack:Rack', 'vessel:Tube01', 'vessel:Tube12'} <= set(state['resources']))
        self.assertNotIn('agent:AgentHuman', state['resources'])
        self.assertNotIn('agent:AgentRobot', state['resources'])
        for flag in ['network_executed', 'hardware_executed', 'robot_motion_executed',
                     'calibration_curve_computed', 'real_export_validated', 'cross_run_volume_ledger',
                     'active_cf01_job_resume_supported']:
            self.assertFalse(report[flag], flag)
        # Even a historically successful biological run must expose a newly
        # conflicting transport receipt and retain its permanent base holds.
        late = copy.deepcopy(first_batch[1])
        late['request_id'] = 'AfterCompletion.Conflict.Request'
        late['args']['observation'].update(observation_id='AfterCompletion.Conflict.Observation',
                                           manifest_sha256='0' * 64)
        self.flow.ingest_transport([late])
        self.assertFalse(self.flow.report()['passed'])
        self.assertTrue(any(event['state']['status'] == 'completed' for event in self.journal.history(self.RUN)))
        self.assertIn('rack:Rack', self.journal.owners())


if __name__ == '__main__':
    unittest.main()
