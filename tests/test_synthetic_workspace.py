"""Unbounded workspace ownership, exact scene preservation and ordered mock batch."""
from pathlib import Path
import copy
import json
import math
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import synthetic_workspace as workspace
import centrifuge_robot_pickup as pickup
from cf01_rack_batch import load,validate,Runner,BatchError,synthetic_feedback


class SyntheticWorkspaceTests(unittest.TestCase):
    def assertGeometryClose(self,actual,expected,path='scene'):
        # Tolerance covers numerical evaluation, not a change in construction intent.
        if type(expected) in (int,float):
            self.assertTrue(math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-8),path)
        elif isinstance(expected,dict):
            self.assertEqual(set(actual),set(expected),path)
            for key in expected:self.assertGeometryClose(actual[key],expected[key],path+'.'+key)
        elif isinstance(expected,list):
            self.assertEqual(len(actual),len(expected),path)
            for i,(a,b) in enumerate(zip(actual,expected)):self.assertGeometryClose(a,b,path+'['+str(i)+']')
        else:self.assertEqual(actual,expected,path)

    def test_generic_workspace_does_not_require_cf01_devices(self):
        read=workspace.read
        def fixture(ref):
            value=read(ref)
            if value.get('format')=='solidcraftbot.equipment-layout/1':value['instances']=[]
            return value
        with patch.object(workspace,'read',side_effect=fixture):
            self.assertEqual(workspace.load()['devices'],{})
            with self.assertRaisesRegex(ValueError,'CF01 workspace requires'):pickup.load()

    def test_exportable_scene_has_no_internal_context_or_duplicate_leading_sources(self):
        scene=pickup.load()
        self.assertNotIn('_workspace',json.dumps(scene))
        self.assertEqual(set(json.loads(pickup.SOURCE.read_text())['sources']),{'protocol'})
        self.assertEqual(pickup.arm_source(scene)['format'],'solidcraftbot.robot/1')

    def test_equipment_overrides_use_common_parameter_validation(self):
        scene=pickup.load()
        for overrides in [{'missing_parameter':1},{'upper_len':-1},{'elbow_z':300}]:
            scene['robot_parameter_overrides_mm']=overrides
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):pickup.arm_source(scene)

    def test_unbounded_space_has_no_finite_room_or_shell_and_one_reference_surface(self):
        w=workspace.load()
        self.assertEqual(w['environment']['extent'],'unbounded')
        self.assertEqual(w['environment']['geometry'],'none')
        self.assertNotIn('dimensions',w['environment'])
        self.assertEqual(len(w['bench']['bodies']),1)
        frame=w['frames']['SYN.Bench.Worktop']
        self.assertEqual([frame[i][3] for i in range(3)],[-50,-50,0])
        self.assertEqual(set(w['devices']),{'Arm','CF01','Rack'})

    def test_unbounded_unknown_and_large_finite_room_are_not_interchangeable(self):
        read=workspace.read
        for changes in [{'extent':None},{'extent':'finite'},{'dimensions':[100000,100000,100000]}]:
            def fixture(ref):
                d=read(ref)
                if d['format']=='solidcraftbot.synthetic-environment/1':d.update(changes)
                return d
            with self.subTest(changes=changes),patch.object(workspace,'read',side_effect=fixture),self.assertRaises(ValueError):workspace.load()

    def test_previous_positions_dimensions_and_all_motion_samples_are_preserved(self):
        expected=json.loads((workspace.ROOT/'tests/fixtures/cf01-before-workspace.json').read_text())
        scene=pickup.load()
        self.assertEqual(scene['rack']['slot_order'],'row_major')
        for key in ['bench_surface','arm_fixture','rack','robot_parameter_overrides_mm']:
            actual=scene[key]
            if key=='rack':actual={k:v for k,v in actual.items() if k!='slot_order'}
            self.assertGeometryClose(actual,expected[key],key)
        self.assertGeometryClose(pickup.trajectory(scene)['samples'],expected['samples'],'samples')

    def test_leading_scene_has_references_instead_of_duplicate_bank_and_device_coordinates(self):
        scene=json.loads(pickup.SOURCE.read_text());self.assertIn('environment',scene)
        self.assertNotIn('bench_surface',scene);self.assertNotIn('position_mm',scene['arm_fixture']);self.assertNotIn('position_mm',scene['rack'])
        self.assertNotIn('robot_parameter_overrides_mm',scene)
        scene['bench_surface']={}
        with self.assertRaisesRegex(ValueError,'must come from'):workspace.materialize_scene(scene)


class OrderedBatchTests(unittest.TestCase):
    def assertConserved(self,report):
        expected=sorted(report['initial_order'])
        for event in report['trace']:
            state=event['inventory'];ids=[x for x in state['rack']+state['rotor']+[state['gripper']] if x is not None]
            self.assertEqual(sorted(ids),expected,event['sequence'])

    def test_both_local_contracts_complete_spin_and_restore_original_order(self):
        for transport in ['ros2','sila2']:
            with self.subTest(transport=transport):
                report=Runner(transport=transport).run()
                self.assertTrue(report['passed']);self.assertTrue(report['order_restored']);self.assertTrue(report['spin_completed'])
                self.assertEqual(report['initial_order'],report['final_order']);self.assertConserved(report)
                stages=[r['stage'] for r in report['trace']]
                self.assertEqual(stages.count('gripper_to_rotor'),12);self.assertEqual(stages.count('gripper_to_original_rack_slot'),12)
                self.assertLess(stages.index('braking'),stages.index('spin_complete'));self.assertLess(stages.index('spin_complete'),stages.index('rotor_to_gripper'))
                self.assertFalse(report['network_executed']);self.assertFalse(report['hardware_executed']);self.assertFalse(report['transporter_executed'])

    def test_permuted_rotor_mapping_does_not_change_rack_sample_order(self):
        data=load()
        for i,sample in enumerate(data['samples']):sample['rotor_slot']=(i+5)%12+1
        data['samples'].reverse()
        report=Runner(data).run();self.assertTrue(report['order_restored']);self.assertConserved(report)
        returned=[r for r in report['trace'] if r['stage']=='gripper_to_original_rack_slot']
        self.assertEqual([r['rack_slot'] for r in returned],list(range(1,13)))
        self.assertEqual([r['rack_place_id'] for r in returned],[p['id'] for p in report['rack_places']])
        self.assertEqual([s['rack_place_id'] for s in report['sample_mapping']],[p['id'] for p in report['rack_places']])
        self.assertEqual(report['rack_places'][-1],{'id':'CF01.OutputRack.Slot12','slot':12,'row':2,'column':3})

    def test_missing_confirmation_or_wrong_identity_halts_without_false_success(self):
        for event,changes in [('rack_ready',{'rack_present':False}),('pick_rack',{'grasp_confirmed':False}),('seat_rotor',{'released_confirmed':False}),('place_rack',{'sample_id':'WrongSample'})]:
            def feedback(name,sample):
                result=synthetic_feedback(name,sample)
                if name==event:result.update(changes)
                return result
            runner=Runner(feedback=feedback)
            with self.subTest(event=event),self.assertRaises(BatchError) as failure:runner.run()
            report=failure.exception.report;self.assertFalse(report['passed']);self.assertFalse(report['order_restored']);self.assertConserved(report)
            if event=='place_rack':self.assertEqual(report['inventory']['gripper'],'Sample01');self.assertIsNone(report['inventory']['rack'][0])

    def test_unbalanced_fictitious_load_is_refused_by_existing_station_protocol(self):
        data=load();data['samples'][0]['mass_g']=2.5
        with self.assertRaises(BatchError) as failure:Runner(data).run()
        report=failure.exception.report;self.assertFalse(report['spin_completed']);self.assertFalse(report['order_restored']);self.assertConserved(report)
        self.assertEqual(report['inventory']['rotor'][0],'Sample01')

    def test_owner_timeout_does_not_continue_loading_or_claim_completion(self):
        runner=Runner()
        def feedback(event,sample):
            if event=='seat_rotor':runner.now+=runner.sim.spec['handling']['owner_timeout_s']+1
            return synthetic_feedback(event,sample)
        runner.feedback=feedback
        with self.assertRaises(BatchError) as failure:runner.run()
        report=failure.exception.report;self.assertFalse(report['passed']);self.assertFalse(report['spin_completed']);self.assertConserved(report)
        self.assertEqual(report['inventory']['gripper'],'Sample01')

    def test_robot_timeout_during_return_preserves_held_sample(self):
        def feedback(event,sample):
            if event=='place_rack':raise TimeoutError('Rack seating confirmation timed out')
            return synthetic_feedback(event,sample)
        with self.assertRaises(BatchError) as failure:Runner(feedback=feedback).run()
        self.assertEqual(failure.exception.report['inventory']['gripper'],'Sample01');self.assertFalse(failure.exception.report['order_restored']);self.assertConserved(failure.exception.report)

    def test_feedback_failures_always_produce_failed_report_and_contract_stop(self):
        for response in [None,ConnectionError('Disconnected'),KeyError('Missing field'),TypeError('Bad response')]:
            def feedback(event,sample):
                if event=='pick_rack':
                    if isinstance(response,Exception):raise response
                    return response
                return synthetic_feedback(event,sample)
            runner=Runner(feedback=feedback)
            with self.subTest(response=response),self.assertRaises(BatchError) as failure:runner.run()
            report=failure.exception.report
            self.assertFalse(report['passed']);self.assertFalse(report['order_restored'])
            self.assertEqual(report['trace'][-1]['stage'],'failed')
            self.assertIn('stop',[e['stage'] for e in report['trace']]);self.assertConserved(report)

    def test_return_confirmation_and_identity_failures(self):
        for event,changes in [('pick_rack',{'sample_id':'Wrong'}),('take_rotor',{'sample_id':'Wrong'}),('take_rotor',{'grasp_confirmed':False}),('withdraw',{'workspace_clear':False})]:
            def feedback(name,sample):
                result=synthetic_feedback(name,sample)
                if name==event:result.update(changes)
                return result
            with self.subTest(event=event,changes=changes),self.assertRaises(BatchError) as failure:Runner(feedback=feedback).run()
            self.assertFalse(failure.exception.report['order_restored']);self.assertConserved(failure.exception.report)

    def test_station_index_and_world_inventory_disagreement_are_detected(self):
        for defect in ['index','identity','mass']:
            runner=Runner();original=runner.command
            def command(name,**args):
                result=original(name,**args)
                if name=='index' and defect=='index':runner.sim.indexed_slot=2
                if name=='present_tube' and defect=='identity':runner.world['rotor'][0]='Wrong'
                if name=='confirm_seated' and defect=='mass':runner.sim.slots[1]['mass_g']=3
                return result
            runner.command=command
            with self.subTest(defect=defect),self.assertRaises(BatchError) as failure:runner.run()
            self.assertFalse(failure.exception.report['passed']);self.assertFalse(failure.exception.report['order_restored'])

    def test_spin_stop_encoder_and_brake_fault_prevent_return(self):
        for defect in ['stop','encoder','brake']:
            runner=Runner();advance=runner.advance
            def fail_advance(seconds):
                if runner.now==0:
                    if defect=='stop':runner.sim.execute('stop')
                    elif defect=='encoder':runner.sim.encoder_healthy=False
                    else:runner.sim.brake_engage_confirmed=False
                advance(seconds)
            runner.advance=fail_advance
            with self.subTest(defect=defect),self.assertRaises(BatchError) as failure:runner.run()
            report=failure.exception.report;self.assertFalse(report['spin_completed']);self.assertFalse(report['order_restored'])
            self.assertNotIn('rotor_to_gripper',[e['stage'] for e in report['trace']]);self.assertConserved(report)

    def test_duplicate_ids_slots_and_wrong_return_policy_are_rejected(self):
        for defect in ['id','rack_slot','rotor_slot','policy','nan']:
            data=load()
            if defect in ['id','rack_slot','rotor_slot']:data['samples'][1][defect]=data['samples'][0][defect]
            elif defect=='policy':data['return_policy']='first_empty_slot'
            else:data['samples'][0]['mass_g']=float('nan')
            with self.subTest(defect=defect),self.assertRaises(ValueError):validate(data)


if __name__=='__main__':unittest.main()
