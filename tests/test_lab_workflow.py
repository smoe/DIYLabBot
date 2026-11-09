"""Public integrated workflow behavior, accounting and interrupted CF01 recovery."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError, inventory_observations
from nanodrop_manual import Workflow as NanoDrop
from lab_workflow import Workflow
from lab_workflow_ledger import original_location
from lab_workflow_sources import SOURCE
from cf01_rack_batch import BatchError
from run_lab_workflow import ACTOR, run_demo, run_nanodrop, run_qubit
from run_nanodrop_manual import synthetic_report as nanodrop_report
from run_qubit_manual import next_preparation, begin_preparation, confirm_preparation, prepare_standards


class IntegratedWorkflowTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='lab-workflow-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.path = self.folder / 'workflow.sqlite3'
        self.journal = Journal(self.path)
        self.flow = Workflow.create(self.journal, run_id='SYN.LAB.TEST')

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def ready_cf01(self, flow=None):
        flow = flow or self.flow
        flow.accept_rack(ACTOR, observations=flow.inventory_observations())
        for sample in flow.state['definition']['manifest']['samples']:
            flow.confirm_mass(ACTOR, sample['vessel_id'], mass_g=2.0, content_revision=0)

    def cf01(self, flow=None, transport='ros2'):
        flow = flow or self.flow
        self.ready_cf01(flow)
        return flow.run_cf01(ACTOR, transport=transport)

    def start_nd(self):
        self.cf01()
        self.flow.handover(ACTOR, observations=self.flow.inventory_observations(),
                           workspace_clear=True, arm_clear=True, gripper_empty=True)
        stage = self.flow.stage('nanodrop')
        stage.act('claim', ACTOR)
        stage.act('blank', ACTOR, reference_id='SYN.Blank', cleaned=True)
        return stage

    def begin_nd(self, stage, sample_id='Sample01'):
        sample = stage.state['samples'][sample_id]
        stage.act('take', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                  rack_id='Rack', place_id=sample['original_place_id'])
        stage.act('begin_measurement', ACTOR, sample_id=sample_id,
                  measurement_id=stage.state['planned_measurements'][sample_id])
        return stage.state['pending_measurement']['intent_id']

    def confirm_nd(self, stage, intent, sample_id='Sample01', **changes):
        stage.act('confirm_measurement', ACTOR, **{
            'intent_id': intent, 'observed_sample_id': sample_id,
            'volume_ul': 1.5, 'cleaned': True, **changes})

    def return_nd(self, stage, sample_id='Sample01'):
        stage.act('place', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                  rack_id='Rack', place_id=stage.state['samples'][sample_id]['original_place_id'])

    def reconcile_nd(self, stage, **changes):
        stage.act('reconcile', ACTOR, **{
            'observations': inventory_observations(stage.state),
            'workspace_clear': False, 'blank_still_valid': True, **changes})

    def abort_inputs(self, flow=None):
        flow = flow or self.flow
        state = flow.state
        observations = [{'vessel_id': sample['vessel_id'], 'sample_id': sample['sample_id'],
                         'location': original_location(state, sample['sample_id'])}
                        for sample in state['definition']['manifest']['samples']]
        return {'observations': observations, 'rotor_empty': list(range(1, 13)),
                'gripper_empty': True, 'standstill_confirmed': True, 'parking_brake_held': True,
                'lift_parked': True, 'arm_clear': True, 'workspace_clear': True,
                'retire_attempt': True, 'reason': 'Explicit synthetic complete inventory and stop observation'}

    def test_full_twelve_vessel_workflow_has_one_balance_and_independent_stage_results(self):
        run_demo(self.flow)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertTrue(report['order_restored'])
        self.assertEqual(len(report['samples']), 12)
        self.assertEqual(len(report['bookings']), 24)
        self.assertEqual(len(report['stages']['nanodrop']['results']), 12)
        self.assertEqual(len(report['stages']['qubit']['results']), 14)
        self.assertEqual(report['samples']['Sample01']['remaining_volume_ul'], 36.5)
        self.assertEqual(report['samples']['Sample03']['withdrawn_volume_ul'], 3.5)
        self.assertIsNone(report['samples']['Sample03']['remaining_volume_ul'])
        self.assertEqual({b['outcome'] for b in report['bookings'].values()}, {'performed'})
        self.assertEqual({b['stage_id'] for b in report['bookings'].values()}, {'nanodrop', 'qubit'})
        self.assertEqual({s['location']['rack_id'] for s in report['samples'].values()}, {'Rack'})
        for index, sample in enumerate(report['samples'].values(), 1):
            self.assertEqual(sample['location']['place_id'], 'Slot%02d' % index)
            self.assertEqual(sample['content_revision'], 2)
            self.assertFalse(sample['mass_confirmation_valid'])
        original = {sample['vessel_id'] for sample in report['samples'].values()}
        derived = {key for key, vessel in report['inventory']['vessels'].items() if vessel['origin'] != 'original'}
        self.assertEqual(len(derived), 14)
        self.assertFalse(original & derived)
        self.assertTrue(all(report['inventory']['vessels'][key]['location'] == {'kind': 'discarded'} for key in derived))
        self.assertNotIn('samples', report['stages']['nanodrop'])
        self.assertNotIn('samples', report['stages']['qubit'])
        self.assertEqual(self.journal.owners(), {})
        for flag in ['network_executed', 'hardware_executed', 'robot_motion_executed',
                     'calibration_curve_computed', 'real_export_validated', 'cross_run_volume_ledger',
                     'active_cf01_job_resume_supported']:
            self.assertFalse(report[flag], flag)

    def test_sila2_stage_preserves_vessel_mapping_without_consumption(self):
        report = self.cf01(transport='sila2')
        self.assertTrue(report['passed'])
        state = self.flow.state
        self.assertEqual(state['active_stage'], 'nanodrop')
        self.assertEqual(state['bookings'], {})
        self.assertGreater(state['logical_time_s'], 0)
        self.assertEqual(state['stages']['cf01']['view']['inventory']['rack'],
                         ['Tube%02d' % i for i in range(1, 13)])
        self.assertTrue(all(v['mass_confirmation_valid'] for v in state['inventory']['vessels'].values()))
        self.assertEqual(self.flow.report()['samples']['Sample01']['remaining_volume_ul'], 40)

    def test_negative_station_reply_keeps_root_ownership_and_following_stages_held(self):
        self.ready_cf01()
        def configure(runner):
            dispatch = runner.bridge.dispatch
            def negative(transport, name, fields):
                result = dispatch(transport, name, fields)
                return {'success': False} if name == 'confirm_seated' else result
            runner.bridge.dispatch = negative
        with self.assertRaisesRegex(BatchError, 'Station acknowledgement'):
            self.flow.run_cf01(ACTOR, configure=configure)
        state = self.flow.state
        self.assertEqual(state['active_stage'], 'cf01')
        self.assertEqual(state['status'], 'held')
        self.assertEqual(state['stages']['cf01']['view']['ownership'], 'unresolved')
        self.assertEqual(state['stages']['cf01']['view']['pending_handoff']['vessel_id'], 'Tube01')
        self.assertEqual(state['stages']['cf01']['view']['inventory']['gripper'], 'Tube01')
        self.assertEqual(state['stages']['cf01']['view']['world_inventory']['rotor'][0], 'Tube01')
        self.assertTrue(self.journal.owners())
        with self.assertRaises(TaskError):
            self.flow.stage('nanodrop').act('claim', ACTOR)
        self.assertFalse(self.flow.report()['order_restored'])

    def test_originals_remain_reserved_through_every_stage_transition(self):
        run_demo(self.flow)
        history = self.journal.history(self.flow.run_id)
        reserved = {'rack:Rack', 'workspace:SYN.NanoDrop.WorkArea'} | {'vessel:Tube%02d' % i for i in range(1, 13)}
        active = [event for event in history if event['state']['status'] not in {'created', 'completed', 'cancelled'}]
        self.assertTrue(active)
        self.assertTrue(all(reserved <= set(event['state']['resources']) for event in active))
        self.assertEqual(history[-1]['state']['resources'], [])

    def test_standalone_runner_cannot_reuse_originals_under_another_rack_id(self):
        self.ready_cf01()
        standalone = NanoDrop.create(self.journal, run_id='SYN.ND.CONFLICT')
        with self.assertRaisesRegex(TaskError, 'vessel:Tube01'):
            standalone.act('rack_ready', ACTOR, observations=inventory_observations(standalone.state))
        self.assertEqual(standalone.state['resources'], [])
        self.assertTrue(all(owner == self.flow.run_id for owner in self.journal.owners().values()))

    def test_foreign_sample_vessel_and_wrong_original_place_reject_initial_inventory(self):
        for defect in ['vessel', 'place']:
            flow = Workflow.create(self.journal, run_id='SYN.LAB.BAD.' + defect)
            observations = flow.inventory_observations()
            if defect == 'vessel':
                observations[0]['vessel_id'] = observations[1]['vessel_id']
            else:
                observations[0]['location']['place_id'] = 'Slot02'
            with self.subTest(defect=defect), self.assertRaises(ObservationError):
                flow.accept_rack(ACTOR, observations=observations)
            self.assertFalse(flow.report()['passed'])
            self.assertEqual(flow.state['resources'], [])

    def test_same_confirmation_cannot_debit_twice_or_accept_stale_intent(self):
        stage = self.start_nd()
        intent = self.begin_nd(stage)
        self.confirm_nd(stage, intent)
        revision = self.journal.get_current(self.flow.run_id)[1]
        with self.assertRaises(TaskError):
            self.confirm_nd(stage, intent)
        self.assertEqual(self.journal.get_current(self.flow.run_id)[1], revision)
        self.assertEqual(self.flow.report()['samples']['Sample01']['remaining_volume_ul'], 38.5)
        self.assertEqual(len(self.flow.state['bookings']), 1)

    def test_unknown_outcome_can_be_resolved_later_without_estimated_upper_bound(self):
        stage = self.start_nd()
        intent = self.begin_nd(stage)
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)
        stage = self.flow.stage('nanodrop')
        self.reconcile_nd(stage, pending_resolution={'intent_id': intent, 'outcome': 'unknown'})
        report = self.flow.report()
        self.assertEqual(report['bookings'][intent]['outcome'], 'unknown')
        self.assertIsNone(report['bookings'][intent]['actual_volume_ul'])
        self.assertIsNone(report['samples']['Sample01']['remaining_volume_ul'])
        with self.assertRaises(TaskError):
            self.flow.stage('qubit').act('claim', ACTOR)
        self.reconcile_nd(stage, pending_resolution={
            'intent_id': intent, 'outcome': 'performed', 'observed_sample_id': 'Sample01',
            'volume_ul': 2.5, 'cleaned': True, 'deviation_reason': 'Explicit synthetic larger withdrawal'})
        self.assertEqual(self.flow.report()['samples']['Sample01']['remaining_volume_ul'], 37.5)
        self.assertEqual(len(self.flow.state['bookings']), 1)
        self.assertEqual(self.flow.state['bookings'][intent]['actual_volume_ul'], 2.5)

    def test_not_performed_resolution_uses_new_intent_without_changing_initial_balance(self):
        stage = self.start_nd()
        old = self.begin_nd(stage)
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)
        stage = self.flow.stage('nanodrop')
        self.reconcile_nd(stage, pending_resolution={'intent_id': old, 'outcome': 'not_performed'})
        stage.act('begin_measurement', ACTOR, sample_id='Sample01',
                  measurement_id=stage.state['planned_measurements']['Sample01'])
        new = stage.state['pending_measurement']['intent_id']
        self.assertNotEqual(old, new)
        with self.assertRaises(TaskError):
            self.confirm_nd(stage, old)
        self.confirm_nd(stage, new)
        self.assertEqual(self.flow.state['bookings'][old]['actual_volume_ul'], 0)
        self.assertEqual(self.flow.report()['samples']['Sample01']['remaining_volume_ul'], 38.5)

    def test_importing_identical_bytes_is_a_noop_and_stage_release_preserves_balances(self):
        stage = self.start_nd()
        for sample_id in stage.state['samples']:
            intent = self.begin_nd(stage, sample_id)
            self.confirm_nd(stage, intent, sample_id)
            self.return_nd(stage, sample_id)
        content = nanodrop_report(stage.state)
        stage.import_content(content, ACTOR)
        revision = self.journal.get_current(self.flow.run_id)[1]
        stage.import_content(content, ACTOR)
        self.assertEqual(self.journal.get_current(self.flow.run_id)[1], revision)
        self.assertEqual(self.journal.artifact(digest(content)), content)
        stage.act('review_results', ACTOR, decision='accepted', reason='Synthetic decision')
        stage.act('release', ACTOR, workspace_clear=True)
        self.assertEqual(self.flow.state['active_stage'], 'qubit')
        self.assertEqual(self.flow.stage('qubit').state['samples']['Sample01']['remaining_volume_ul'], 38.5)
        self.assertEqual(len(self.flow.state['stages']['nanodrop']['results']), 12)
        self.assertTrue(self.journal.owners())
        with self.assertRaises(TaskError):
            stage.act('claim', ACTOR)

    def test_qb_chamber_is_rejected_as_a_preparation_holder(self):
        self.cf01()
        run_nanodrop(self.flow)
        self.flow.handover(ACTOR, observations=self.flow.inventory_observations(),
                           workspace_clear=True, arm_clear=True, gripper_empty=True)
        stage = self.flow.stage('qubit')
        stage.act('claim', ACTOR)
        tube = next_preparation(stage.state) + '.Tube'
        with self.assertRaisesRegex(TaskError, 'measurement chamber'):
            stage.act('begin_preparation', ACTOR, kind='standard', target_id='SYN.StandardLow',
                      vessel_id=tube, observed_vessel_id=tube, empty_tube_confirmed=True,
                      holder_id='SYN.Qubit401', place_id='Chamber')
        self.assertEqual(stage.state['preparations'], {})

    def test_qb_performed_reconciliation_requires_the_recorded_return_place(self):
        self.cf01()
        run_nanodrop(self.flow)
        self.flow.handover(ACTOR, observations=self.flow.inventory_observations(),
                           workspace_clear=True, arm_clear=True, gripper_empty=True)
        stage = self.flow.stage('qubit')
        stage.act('claim', ACTOR)
        prepare_standards(stage)
        stage.act('take', ACTOR, sample_id='Sample01', observed_sample_id='Sample01', rack_id='Rack', place_id='Slot01')
        pending = begin_preparation(stage, 'sample', 'Sample01')
        confirm_preparation(stage)
        stage.act('place', ACTOR, sample_id='Sample01', observed_sample_id='Sample01', rack_id='Rack', place_id='Slot01')
        self.flow.advance_time(ACTOR, 2)
        preparation = stage.state['preparations'][pending['preparation_id']]
        tube = pending['vessel_id']
        holder = copy.deepcopy(stage.state['derived_vessels'][tube]['location'])
        stage.act('begin_measurement', ACTOR, preparation_id=preparation['id'],
                  measurement_id=preparation['measurement_id'], observed_vessel_id=tube,
                  calibration_id=stage.state['calibration']['id'])
        intent = stage.state['pending_operation']['intent_id']
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)
        stage = self.flow.stage('qubit')
        resolution = {'intent_id': intent, 'outcome': 'performed', 'observed_vessel_id': tube, 'returned_to_holder': True}
        for wrong in [{'kind': 'logical', 'holder_id': 'SYN.Qubit401', 'place_id': 'Chamber'},
                      {'kind': 'logical', 'holder_id': holder['holder_id'], 'place_id': 'P12'}]:
            observations = inventory_observations(stage.state)
            next(item for item in observations if item['vessel_id'] == tube)['location'] = wrong
            with self.subTest(wrong=wrong), self.assertRaises(ObservationError):
                stage.act('reconcile', ACTOR, observations=observations, workspace_clear=False,
                          calibration_still_valid=True, pending_resolution=resolution)
            self.assertNotIn(preparation['measurement_id'], stage.state['measurements'])
        observations = inventory_observations(stage.state)
        next(item for item in observations if item['vessel_id'] == tube)['location'] = holder
        stage.act('reconcile', ACTOR, observations=observations, workspace_clear=False,
                  calibration_still_valid=True, pending_resolution=resolution)
        self.assertEqual(len(stage.state['measurements']), 3)
        self.assertIsNone(stage.state['pending_operation'])
        self.assertEqual(self.flow.report()['samples']['Sample01']['remaining_volume_ul'], 36.5)
        self.assertEqual(len(self.flow.state['bookings']), 13)

    def test_consumption_invalidates_total_mass_and_stale_confirmation_is_rejected(self):
        self.cf01()
        run_nanodrop(self.flow)
        with self.assertRaisesRegex(TaskError, 'Fresh total vessel mass'):
            Workflow.cf01_profile(self.flow.state)
        with self.assertRaisesRegex(TaskError, 'revision is stale'):
            self.flow.confirm_mass(ACTOR, 'Tube01', 2.0, content_revision=0)
        self.assertEqual(self.flow.report()['samples']['Sample01']['content_revision'], 1)

    def test_reconciled_clearance_does_not_replace_an_explicit_handover_to_the_actor(self):
        self.cf01()
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)
        stage = self.flow.stage('nanodrop')
        self.reconcile_nd(stage, workspace_clear=True, blank_still_valid=False)
        with self.assertRaisesRegex(TaskError, 'Explicit handover'):
            stage.act('claim', ACTOR)
        self.flow.handover(ACTOR, observations=self.flow.inventory_observations(),
                           workspace_clear=True, arm_clear=True, gripper_empty=True)
        with self.assertRaisesRegex(TaskError, 'this actor'):
            stage.act('claim', 'SYN.OtherOperator')
        stage.act('claim', ACTOR)
        self.assertEqual(stage.state['actor_id'], ACTOR)

    def test_earlier_csv_or_cf01_artifact_corruption_blocks_final_release(self):
        for damaged_stage in ['nanodrop', 'cf01']:
            with self.subTest(damaged_stage=damaged_stage), Journal(self.folder / (damaged_stage + '.sqlite3')) as store:
                flow = Workflow.create(store, run_id='SYN.LAB.CORRUPT.' + damaged_stage)
                dispatch = flow.stage_act
                def corrupt_before_release(stage_id, command, actor_id, artifact=None, **data):
                    if stage_id == 'qubit' and command == 'release':
                        previous = flow.state['stages'][damaged_stage]
                        checksum = (next(iter(previous['imports'])) if damaged_stage == 'nanodrop'
                                    else previous['report_artifact_sha256'])
                        store.connection.execute('UPDATE artifacts SET content=? WHERE sha256=?',
                                                 (b'corrupted original artifact', checksum))
                        store.connection.commit()
                    return dispatch(stage_id, command, actor_id, artifact=artifact, **data)
                with patch.object(flow, 'stage_act', side_effect=corrupt_before_release), self.assertRaisesRegex(TaskError, 'corrupt artifact'):
                    run_demo(flow)
                self.assertNotEqual(flow.state['status'], 'completed')
                self.assertTrue(store.owners())

    def test_integrated_and_standalone_run_formats_are_not_interchangeable(self):
        standalone = NanoDrop.create(self.journal, run_id='SYN.ND.FORMAT')
        with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
            Workflow(self.journal, standalone.run_id)
        with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
            NanoDrop(self.journal, self.flow.run_id, None)

    def test_later_stage_cannot_withdraw_more_than_the_previous_stage_left(self):
        with tempfile.TemporaryDirectory(prefix='lab-source-test-', dir=ROOT / 'model') as folder:
            profile = json.loads(SOURCE.read_text())
            manifest = json.loads((ROOT / profile['manifest']['source']).read_text())
            manifest['samples'][0]['initial_volume_ul'] = 3
            source = Path(folder) / 'manifest.json'
            source.write_text(json.dumps(manifest))
            profile['manifest'] = {'source': str(source.relative_to(ROOT)), 'source_sha256': digest(source.read_bytes())}
            flow = Workflow.create(self.journal, source=profile, run_id='SYN.LAB.LOWVOLUME')
            self.cf01(flow)
            run_nanodrop(flow)
            with self.assertRaisesRegex(TaskError, 'Insufficient'):
                run_qubit(flow)
            self.assertEqual(flow.report()['samples']['Sample01']['remaining_volume_ul'], 1.5)
            self.assertFalse(any(b['stage_id'] == 'qubit' for b in flow.state['bookings'].values()))

    def test_root_clock_and_deadline_do_not_reset_at_stage_boundaries(self):
        self.ready_cf01()
        self.flow.advance_time(ACTOR, 3)
        initial_deadline = self.flow.state['deadline_s']
        self.flow.run_cf01(ACTOR)
        cf_time = self.flow.state['logical_time_s']
        self.assertGreater(cf_time, 3)
        run_nanodrop(self.flow)
        self.assertEqual(self.flow.state['logical_time_s'], cf_time)
        self.assertEqual(self.flow.state['deadline_s'], initial_deadline)
        self.flow.advance_time(ACTOR, initial_deadline)
        self.assertEqual(self.flow.state['recovery_required'], 'workflow_deadline_exceeded')
        self.assertTrue(self.journal.owners())

    def test_stale_session_source_and_clock_changes_prevent_resume(self):
        self.ready_cf01()
        other = Workflow.open(self.journal, self.flow.run_id, resume=True)
        with self.assertRaisesRegex(TaskError, 'Stale'):
            self.flow.advance_time(ACTOR, 1)
        other.close()
        with patch('lab_workflow.digest', return_value='0' * 64), self.assertRaisesRegex(TaskError, 'Pinned source changed'):
            Workflow.open(self.journal, self.flow.run_id)
        state, revision = self.journal.get_current(self.flow.run_id)
        state['clock_mode'] = 'wall_clock'
        self.journal.append(self.flow.run_id, revision, 'test_clock_corruption', {}, state)
        with self.assertRaisesRegex(TaskError, 'clock mode changed'):
            Workflow.open(self.journal, self.flow.run_id)

    def test_unstarted_cf01_can_reconcile_without_resetting_the_workflow_clock(self):
        self.ready_cf01()
        self.flow.advance_time(ACTOR, 2)
        deadline = self.flow.state['deadline_s']
        self.flow.close()
        self.flow = Workflow.open(self.journal, self.flow.run_id)
        values = {key: value for key, value in self.abort_inputs().items()
                  if key not in {'retire_attempt', 'reason'}}
        self.flow.reconcile_initial_cf01(ACTOR, **values)
        self.assertEqual(self.flow.state['logical_time_s'], 2)
        self.assertEqual(self.flow.state['deadline_s'], deadline)
        self.flow.run_cf01(ACTOR)
        self.assertEqual(self.flow.state['active_stage'], 'nanodrop')
        with self.assertRaisesRegex(TaskError, 'unstarted CF01'):
            self.flow.reconcile_initial_cf01(ACTOR, **values)

    def test_abort_requires_complete_synthetic_evidence_and_never_claims_cf01_success(self):
        self.ready_cf01()
        self.flow.cancel(ACTOR, 'Explicit synthetic cancellation')
        with self.assertRaises(ObservationError):
            self.flow.finish_cf01_abort(ACTOR, **{**self.abort_inputs(), 'rotor_empty': list(range(1, 12))})
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertTrue(self.journal.owners())
        self.flow.cancel(ACTOR, 'Renewed explicit abort after incomplete observation')
        with self.assertRaisesRegex(TaskError, 'synthetic operator'):
            self.flow.finish_cf01_abort(ACTOR, **self.abort_inputs(), evidence='hardware_status')
        self.flow.finish_cf01_abort(ACTOR, **self.abort_inputs())
        report = self.flow.report()
        self.assertEqual(report['status'], 'cancelled')
        self.assertFalse(report['passed'])
        self.assertEqual(report['stages']['cf01']['abort_reconciliation']['evidence'], 'synthetic_operator_confirmation')
        self.assertEqual(self.journal.owners(), {})

    def test_hard_cf01_process_exit_keeps_root_held_until_explicit_abort(self):
        path = self.folder / 'crash.sqlite3'
        script = '''
import os,sys
from manual_tasks import Journal
from lab_workflow import Workflow
from run_lab_workflow import ACTOR
j=Journal(sys.argv[1]);f=Workflow.create(j,run_id='SYN.LAB.CRASH')
f.accept_rack(ACTOR,observations=f.inventory_observations())
for sample in f.state['definition']['manifest']['samples']:
    f.confirm_mass(ACTOR,sample['vessel_id'],2.0,0)
def configure(runner):
    checkpoint=runner._checkpoint
    def crash(kind,payload,view):
        checkpoint(kind,payload,view)
        pending=view.get('pending_handoff')
        if kind=='robot_observed' and pending and pending['event']=='seat_rotor':os._exit(23)
    runner._checkpoint=crash
f.run_cf01(ACTOR,configure=configure)
'''
        result = subprocess.run([sys.executable, '-B', '-c', 'import sys;sys.path.insert(0,"scripts");' + script, str(path)],
                                cwd=ROOT, text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 23, result.stderr)
        with Journal(path) as store:
            with self.assertRaisesRegex(TaskError, 'explicit resume'):
                Workflow.open(store, 'SYN.LAB.CRASH')
            with patch('lab_workflow.Runner', side_effect=AssertionError('No simulator recreation')) as runner:
                flow = Workflow.open(store, 'SYN.LAB.CRASH', resume=True)
                self.assertEqual(flow.state['recovery_required'], 'cf01_context_lost')
                self.assertEqual(flow.state['stages']['cf01']['view']['world_inventory']['rotor'][0], 'Tube01')
                with self.assertRaises(TaskError):
                    flow.run_cf01(ACTOR)
                runner.assert_not_called()
            self.assertTrue(store.owners())
            flow.cancel(ACTOR, 'Interrupted CF01 attempt retired explicitly')
            flow.finish_cf01_abort(ACTOR, **self.abort_inputs(flow))
            self.assertEqual(flow.state['status'], 'cancelled')
            self.assertFalse(flow.report()['passed'])
            self.assertEqual(store.owners(), {})

    def test_cli_runs_a_complete_demo_and_reads_the_same_report(self):
        path = self.folder / 'cli.sqlite3'
        args = [sys.executable, '-B', str(ROOT / 'scripts/run_lab_workflow.py'), '--store', str(path)]
        result = subprocess.run(args + ['demo', '--run-id', 'SYN.LAB.CLI'], cwd=ROOT,
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'completed')
        result = subprocess.run(args + ['report', 'SYN.LAB.CLI'], cwd=ROOT,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(Path(json.loads(result.stdout)['report']).read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(report['samples']['Sample01']['remaining_volume_ul'], 36.5)
        self.assertEqual(len(report['stages']['qubit']['results']), 14)
        self.assertFalse(report['network_executed'])


if __name__ == '__main__':
    unittest.main()
