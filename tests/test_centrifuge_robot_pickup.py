"""Robot motion, actual six-axis FK, rigid ownership handoff and closure guards."""
import copy
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import centrifuge_robot_pickup as pickup
import centrifuge_model as cf
import robot_spec as robot


class PickupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene=pickup.load();cls.data=pickup.trajectory(cls.scene);cls.arm=pickup.arm_source(cls.scene);cls.kin=pickup.Kinematics(cls.arm,cls.scene)

    def test_all_six_joint_limits_and_tip_position(self):
        self.assertEqual(len(self.arm['joints']),6)
        self.assertLess(self.data['maximum_tip_position_error_mm'],.05)
        for sample in self.data['samples']:
            for angle,(lo,hi) in zip(sample['joints_deg'],self.kin.limits):self.assertTrue(lo<=angle<=hi)

    def test_cached_fk_matches_original_robot_model(self):
        for t in [0,17.5,20.5,24.5,28.5,42]:
            sample=pickup.interpolate(self.data['samples'],t);expected=robot.forward(self.arm,sample['joints_deg']);actual=self.kin.forward(sample['joints_deg'])
            for name in expected:
                target=robot.multiply(self.kin.base,expected[name])
                for p in [[0,0,0],[19,0,0],[0,23,31]]:self.assertLess(math.dist(robot.transform(target,p),robot.transform(actual[name],p)),1e-7)

    def test_no_jump_when_tube_changes_owner(self):
        t=self.scene['checks']['attachment_time_s'];s=pickup.interpolate(self.data['samples'],t);m=pickup.matrices(self.scene,self.data,s)
        spec=cf.load();p=cf.parameters(spec);old=pickup.rigid_from_cf(cf.expanded(spec,p),'PresentedTube',s['station'])
        for v in [[0,0,0],[0,-80,220],[0,-54,257]]:self.assertLess(math.dist(robot.transform(m['PresentedTube'],v),robot.transform(old,v)),1e-7)

    def test_carried_tube_is_rigidly_attached_until_lid_locked(self):
        relatives=[]
        for t in [21.5,22.5,24.5,28.5,35,42]:
            sample=pickup.interpolate(self.data['samples'],t);m=pickup.matrices(self.scene,self.data,sample)
            relatives.append(robot.multiply(robot.inverse(m['Tool']),m['PresentedTube']))
        for value in relatives[1:]:
            self.assertLess(max(abs(value[i][j]-relatives[0][i][j]) for i in range(4) for j in range(4)),1e-8)

    def test_lid_waits_for_full_withdrawal_and_empty_lift(self):
        for sample in self.data['samples']:
            if 14.5<=sample['time_s']<=30.5:self.assertEqual(sample['station']['Lid'],105)
            if sample['time_s']>30.5:
                self.assertTrue(sample['workspace_clear']);self.assertIn(sample['tube_owner'],('gripper','rack'));self.assertEqual(sample['station']['Lift'],0)
        self.assertEqual(self.data['samples'][-1]['station']['Lid'],0)

    def test_bad_handoff_or_early_closure_is_rejected(self):
        bad=copy.deepcopy(self.scene);next(k for k in bad['timeline'] if k['time_s']==bad['checks']['attachment_time_s'])['jaw']='open'
        with self.assertRaises(ValueError):pickup.validate(bad)
        bad=copy.deepcopy(self.scene);bad['checks']['robot_clear_confirmed_s']=35
        with self.assertRaises(ValueError):pickup.validate(bad)
        bad=copy.deepcopy(self.scene);next(k for k in bad['timeline'] if k['time_s']==41)['workspace_clear']=False
        with self.assertRaises(ValueError):pickup.validate(bad)

    def test_tip_is_extracted_above_chamber_before_lateral_withdrawal(self):
        spec=cf.load();p=cf.parameters(spec);bottom,_=cf.pocket(spec,p,1)
        sample=pickup.interpolate(self.data['samples'],self.scene['checks']['extraction_time_s']);m=pickup.matrices(self.scene,self.data,sample)
        self.assertGreater(robot.transform(m['PresentedTube'],bottom)[2]-p['chamber_top'],self.scene['checks']['clearance_margin_mm'])

    def test_gripper_gap_and_shoulder_leave_cap_clear(self):
        spec=cf.load();p=cf.parameters(spec);closed=pickup.interpolate(self.data['samples'],21.5)
        self.assertEqual(closed['jaw_gap_mm'],2*p['tube_radius'])
        parts=pickup.gripper_parts(self.scene,p);self.assertEqual(len(parts),6)
        stem=next(b['shape'] for b in parts if b['id']=='RightFingerStem')
        self.assertGreater(stem['origin'][0]+closed['jaw_gap_mm']/2,7)

    def test_protocol_blocks_retract_and_close_until_robot_withdraws(self):
        trace=pickup.mock_transfer_trace();self.assertTrue(trace['passed'])
        blocked={p['blocked']:p['error'] for p in trace['trace'] if 'blocked' in p}
        self.assertEqual(blocked['premature transfer'],'UnconfirmedTransfer')
        self.assertEqual(blocked['retract_lift'],'WorkspaceOccupied');self.assertEqual(blocked['close_lid'],'WorkspaceOccupied')

    def test_bench_mount_and_link_variant_share_geometry_and_anchors(self):
        self.assertEqual(self.scene['arm_fixture']['position_mm'][2],0)
        self.assertNotIn('pedestal_size_mm',self.scene['arm_fixture'])
        base=robot.load();bp=robot.parameters(base);vp=robot.parameters(self.arm)
        self.assertEqual((vp['upper_len'],vp['fore_len']),(280,250))
        # Both CAD compilers use the same expressions, including distal offsets.
        for index,j in enumerate(self.arm['joints'][2:],2):
            actual=robot.frame(j,vp)[2][3]-robot.frame(j,bp)[2][3]
            self.assertAlmostEqual(actual,80 if index<4 else 155)

    def test_no_ik_branch_flip_during_rack_transfer(self):
        for a,b in zip(self.data['samples'],self.data['samples'][1:]):
            self.assertLess(max(abs(x-y) for x,y in zip(a['joints_deg'],b['joints_deg'])),10)
        spec=cf.load();p=cf.parameters(spec)
        for sample in self.data['samples']:
            residual=self.kin.residual(sample['joints_deg'],pickup.target_at(self.scene,spec,p,sample['time_s']))
            self.assertLess(math.sqrt(sum(v*v for v in residual[:3])),.05)
            self.assertLess(math.degrees(math.sqrt(sum(v*v for v in residual[3:]))/100),.05)

    def test_joint_interpolation_stays_inside_transport_target(self):
        audit=pickup.interpolation_audit(self.scene,self.data)
        self.assertTrue(audit['passed'])
        self.assertLess(audit['maximum_position_deviation_mm'],1)
        self.assertLess(audit['maximum_orientation_deviation_deg'],.1)

    def test_arm_continues_after_clearance_while_original_lid_motion_runs(self):
        clear=self.scene['checks']['robot_clear_confirmed_s']
        self.assertEqual(clear,29.5)
        self.assertEqual(self.data['duration_s'],47.5)
        after_clear=pickup.interpolate(self.data['samples'],29.75)
        at_clear=pickup.interpolate(self.data['samples'],clear)
        self.assertGreater(max(abs(a-b) for a,b in zip(after_clear['joints_deg'],at_clear['joints_deg'])),.01)
        for t in (32,35,39):
            before=pickup.interpolate(self.data['samples'],t)
            after=pickup.interpolate(self.data['samples'],t+.25)
            self.assertGreater(before['station']['Lid'],0)
            self.assertLess(before['station']['Lid'],105)
            self.assertGreater(max(abs(a-b) for a,b in zip(before['joints_deg'],after['joints_deg'])),.01)
            self.assertEqual(before['station']['Lift'],0)
            self.assertEqual(pickup.tube_owner(self.scene,t),'gripper')
        self.assertEqual(pickup.interpolate(self.data['samples'],41)['station']['Lid'],0)
        self.assertEqual(pickup.interpolate(self.data['samples'],42)['station']['LatchLeft'],0)

    def test_channel_keys_preserve_move_durations_without_copied_intermediate_angles(self):
        robot_keys=pickup.channel_keys(self.scene,'robot_pose')
        self.assertEqual([(k['time_s'],k['robot_pose']) for k in robot_keys if k['time_s']>=29.5],
            [(29.5,'withdrawn'),(33.5,'upright'),(37.5,'rack_approach'),
             (41.5,'rack_seated'),(43.5,'rack_seated'),(47.5,'rack_approach')])
        self.assertNotIn('station_pose',next(k for k in self.scene['timeline'] if k['time_s']==33.5))
        self.assertNotIn('robot_pose',next(k for k in self.scene['timeline'] if k['time_s']==41))
        spec=cf.load();p=cf.parameters(spec)
        station=pickup.protocol.at_time(pickup.station_frames(self.scene,spec,p),35.5)['values']
        self.assertEqual(station['Lid'],55)
        self.assertAlmostEqual(pickup.interpolate(self.data['samples'],43)['jaw_gap_mm'],16.4)

    def test_unrelated_confirmation_does_not_insert_an_actor_motion_anchor(self):
        changed=copy.deepcopy(self.scene)
        changed['timeline'].append({'time_s':34,'phase':'Repeated synthetic clearance','workspace_clear':True})
        changed['timeline'].sort(key=lambda k:k['time_s'])
        pickup.validate(changed)
        spec=cf.load();p=cf.parameters(spec)
        for t in (33.75,34,34.5,35.5):
            self.assertEqual(pickup.target_at(changed,spec,p,t),pickup.target_at(self.scene,spec,p,t))
        self.assertEqual(pickup.station_frames(changed,spec,p),pickup.station_frames(self.scene,spec,p))

    def test_sparse_semantics_and_channel_initialization_are_explicit(self):
        for defect in ('undeclared','unknown','missing_initial','coordinate_without_pose'):
            bad=copy.deepcopy(self.scene)
            if defect=='undeclared':bad.pop('timeline_semantics')
            elif defect=='unknown':bad['timeline_semantics']='unknown'
            elif defect=='missing_initial':bad['timeline'][0].pop('jaw')
            else:next(k for k in bad['timeline'] if k['time_s']==33.5)['coordinates']={'Lid':80}
            with self.subTest(defect=defect),self.assertRaises(ValueError):pickup.validate(bad)

    def test_closure_and_retraction_keep_clearance_and_parked_pusher_guards(self):
        for defect in ('lost_clearance','raised_pusher','early_retraction'):
            bad=copy.deepcopy(self.scene)
            if defect=='lost_clearance':next(k for k in bad['timeline'] if k['time_s']==33.5)['workspace_clear']=False
            elif defect=='raised_pusher':next(k for k in bad['timeline'] if k['time_s']==30.5)['coordinates']={'Lift':'park_gap'}
            else:next(k for k in bad['timeline'] if k['time_s']==28.5)['station_pose']='open'
            with self.subTest(defect=defect),self.assertRaises(ValueError):pickup.validate(bad)

    def test_parallel_station_motion_cannot_weaken_support_or_ownership(self):
        for defect in ('early_rack_owner','early_open','moving_at_handoff','owner_back_to_station'):
            bad=copy.deepcopy(self.scene)
            if defect=='early_rack_owner':next(k for k in bad['timeline'] if k['time_s']==41.5)['tube_owner']='rack'
            elif defect=='early_open':next(k for k in bad['timeline'] if k['time_s']==41.5)['jaw']='open'
            elif defect=='moving_at_handoff':next(k for k in bad['timeline'] if k['time_s']==43.5)['robot_pose']='rack_approach'
            else:bad['timeline'][-1]['tube_owner']='station'
            with self.subTest(defect=defect),self.assertRaises(ValueError):pickup.validate(bad)

    def test_all_twelve_rack_approach_and_seated_endpoints_are_reachable(self):
        spec=cf.load();p=cf.parameters(spec);seed=self.scene['ik_seed_deg']
        for slot in range(1,13):
            scene=copy.deepcopy(self.scene)
            for name in ['rack_approach','rack_seated']:scene['poses'][name]['rack_slot']=slot
            goals=pickup.targets(scene,spec,p)
            for name in ['rack_approach','rack_seated']:
                seed=self.kin.inverse(goals[name],seed)
                self.assertLess(math.sqrt(sum(v*v for v in self.kin.residual(seed,goals[name])[:3])),.05)

    def test_unknown_variant_parameter_is_rejected(self):
        with self.assertRaises(ValueError):robot.load(parameter_overrides={'misspelled_link_length':300})

    def test_rack_handoff_has_no_jump_and_tube_stays_when_empty_gripper_withdraws(self):
        evaluate=pickup.SceneEvaluator(self.scene,self.data);t=self.scene['checks']['rack_handoff_time_s']
        sample=pickup.interpolate(self.data['samples'],t);at=evaluate(sample)
        held=robot.multiply(at['Tool'],evaluate.attachment)
        for row in range(4):
            for col in range(4):self.assertAlmostEqual(held[row][col],at['PresentedTube'][row][col],places=9)
        final=evaluate(pickup.interpolate(self.data['samples'],self.data['duration_s']))
        self.assertEqual(at['PresentedTube'],final['PresentedTube'])
        self.assertGreater(math.dist(robot.transform(at['Tool'],[0,0,0]),robot.transform(final['Tool'],[0,0,0])),100)
        spec=cf.load();p=cf.parameters(spec);bottom,_=cf.pocket(spec,p,1)
        rack=pickup.rack_geometry(self.scene,p);expected=robot.transform(rack['frame'],rack['slots'][0]['tube_bottom_mm'])
        self.assertLess(math.dist(robot.transform(final['PresentedTube'],bottom),expected),.01)

    def test_rack_confirmation_precedes_release_and_bad_support_is_rejected(self):
        support=self.scene['checks']['rack_handoff_time_s'];release=self.scene['checks']['release_complete_time_s']
        self.assertEqual(pickup.tube_owner(self.scene,support-.25),'gripper')
        self.assertEqual(pickup.tube_owner(self.scene,support),'rack')
        self.assertEqual(pickup.interpolate(self.data['samples'],support)['jaw_gap_mm'],10.8)
        self.assertEqual(pickup.interpolate(self.data['samples'],release)['jaw_gap_mm'],22)
        bad=copy.deepcopy(self.scene);next(k for k in bad['timeline'] if k['time_s']==support)['rack_seated']=False
        with self.assertRaises(ValueError):pickup.validate(bad)
        bad=copy.deepcopy(self.scene);next(k for k in bad['timeline'] if k['time_s']==support)['robot_pose']='rack_approach'
        with self.assertRaises(ValueError):pickup.validate(bad)

    def test_rack_entry_accommodates_one_mm_lateral_transport_error(self):
        spec=cf.load();p=cf.parameters(spec);rack=pickup.rack_geometry(self.scene,p)
        self.assertEqual(rack['capacity'],12)
        radial_slack=self.scene['rack']['bore_radius_mm']-p['tube_radius']
        self.assertGreater(radial_slack,self.scene['transport_requirement']['position_target_mm'])
        self.assertGreater(self.scene['rack']['entry_radius_mm'],self.scene['rack']['bore_radius_mm'])
        # Seated fingers end above the guide; tube bottom bears on base, not cap.
        pad=self.scene['gripper'];grip=rack['slots'][0]['grip_mm'][2]
        lowest_pad=grip-pad['finger_pad_start_mm']-pad['finger_pad_size_mm'][2]
        self.assertGreater(lowest_pad-self.scene['rack']['guide_bottom_mm']-self.scene['rack']['guide_thickness_mm'],5)


if __name__=='__main__':unittest.main()
