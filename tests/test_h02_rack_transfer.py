"""Continuous transfer, source references, load-dependent limits and handoff."""
import copy
import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import h02_rack_transfer as m


class RackTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.p=m.Program()

    def test_full_curve_joint_and_sample_limits(self):
        report=self.p.audit();self.assertTrue(report['passed']);self.assertTrue(report['continuous_loaded_transport'])
        self.assertEqual(report['loaded_scalar_limits'],{'velocity_mm_s':1500,'acceleration_mm_s2':9806.65,'jerk_mm_s3':5000})
        self.assertIsNone(report['performance_acceptance']['human_reference_s'])
        self.assertFalse(report['global_time_optimality_proved'])

    def test_empty_approach_and_withdrawal_use_robot_limits(self):
        old=m.base.Program();self.assertLess(self.p.durations['approach'],old.durations['approach']);self.assertLess(self.p.durations['withdraw'],old.durations['extraction'])
        for phase in ['approach','withdraw']:
            self.assertFalse(self.p.phase_reports[phase]['loaded'])
            for value,key in zip(self.p.phase_reports[phase]['bounds']['joint'],['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3']):self.assertLessEqual(value,self.p.limits['arm_empty'][key])

    def test_exact_ik_attachment_and_fixed_orientation(self):
        for phase in self.p.curves:
            for u in [0,.013,.2,.5,.773,1]:
                state=self.p.state(phase,u);target=m.base.pickup.tool_target(state['tool_position_mm'],0,-state['tool_yaw_deg'])
                self.assertLess(max(abs(v) for v in self.p.kin.residual(state['joints_deg'],target)),1e-7)
                if phase=='extraction':
                    self.assertEqual(state['coordinates']['TubeY'],state['coordinates']['ToolY']);self.assertEqual(state['coordinates']['TubeZ'],state['coordinates']['ToolZ']);self.assertEqual(state['coordinates']['JawLeft'],0)

    def test_no_stop_inside_complete_loaded_path(self):
        for i in range(1,200):
            state=self.p.state('extraction',i/200)
            self.assertGreater(math.hypot(*state['tool_pva']['velocity_mm_s']),1e-7)
        for left,right,points in self.p.route.pieces:
            # All corner control-edge tangents lie in the same quadrant,
            # with nonzero edges, so positive Bernstein weights cannot cancel.
            edges=[[b[k]-a[k] for k in [1,2]] for a,b in zip(points,points[1:])]
            self.assertTrue(any(math.hypot(*e)>0 for e in edges))
            for k in [0,1]:self.assertFalse(any(e[k]>0 for e in edges) and any(e[k]<0 for e in edges))

    def test_c2_clock_and_spatial_joins(self):
        for curve in self.p.curves.values():
            for t in curve.times[1:-1]:
                a=m.motion.evaluate(curve,t,side='left');b=m.motion.evaluate(curve,t,side='right')
                for f in m.motion.FIELDS[:3]:self.assertAlmostEqual(a[f][0],b[f][0],places=7)
        for boundary in [v[1] for v in self.p.route.pieces[:-1]]:
            a=self.p.route.evaluate(m.J(boundary-1e-7,1));b=self.p.route.evaluate(m.J(boundary+1e-7,1))
            for x,y in zip(a,b):
                for order in range(3):self.assertAlmostEqual(x.d[order],y.d[order],places=5)

    def test_native_rack_parts_and_all_neighbors_reference_existing_geometry(self):
        parts=self.p.extra_parts('V20');ids=[b['id'] for b in parts];self.assertEqual(len(ids),len(set(ids)));self.assertEqual(len(parts),28)
        self.assertEqual(len([b for b in parts if b['role']=='occupied_rack_tube']),11)
        envelope=next(b for b in parts if b['id']=='CarriedEnvelope');self.assertTrue(envelope['hidden']);self.assertEqual(envelope['group'],'Tube')

    def test_seat_before_release_and_stationary_tube_after_handoff(self):
        held=self.p.state('extraction',1);release=self.p.state('release',0)
        self.assertEqual(held['tube_owner'],'gripper');self.assertEqual(release['tube_owner'],'rack')
        self.assertEqual(held['sample_id'],release['sample_id']);self.assertTrue(release['rack_place_id'].endswith('Slot01'))
        for phase in ['release','withdraw']:
            for u in [0,.3,1]:
                state=self.p.state(phase,u);self.assertAlmostEqual(state['coordinates']['TubeY'],self.p.seat[1]);self.assertAlmostEqual(state['coordinates']['TubeZ'],self.p.seat[2]-self.p.z0)
        self.assertEqual(self.p.at_time(self.p.total_duration),('withdraw',1.0))

    def test_occupied_destination_and_missing_support_evidence_rejected(self):
        d=copy.deepcopy(self.p.transfer);d['rack_instance']['occupied_slots'].append(1)
        with self.assertRaises(ValueError):m.Program(d)
        d=copy.deepcopy(self.p.transfer);d['events']['rack_support_confirmation']=None
        with self.assertRaises(ValueError):m.Program(d)

    def test_interval_hulls_contain_interior_pva(self):
        for phase in self.p.curves:
            for a,b in [(0,.1),(.31,.36),(.94,1)]:
                q,y,z,s=self.p._bounds(phase,a,b)
                for u in [a,(a+b)/2,b]:
                    state=self.p.state(phase,u)
                    for n,f in enumerate(m.motion.FIELDS):
                        for bound,actual in zip(q,state['joint_state'][f]):
                            interval=m.base.interval(bound.d[n]);self.assertGreaterEqual(actual,interval.lo-1e-7);self.assertLessEqual(actual,interval.hi+1e-7)

    def test_source_rejects_nonphysical_caps_and_invalid_slot(self):
        for key,value in [('velocity_mm_s',0),('acceleration_mm_s2',float('inf')),('jerk_mm_s3',-1)]:
            d=copy.deepcopy(self.p.transfer);d['sample_caps'][key]=value
            with self.assertRaises(ValueError):m.Program(d)
        d=copy.deepcopy(self.p.transfer);d['rack_instance']['selected_slot']=0
        with self.assertRaises(ValueError):m.Program(d)

    def test_native_pose_enclosures_and_solver_rejections(self):
        import h02_native_pose_boxes as native
        pose={'origin':[3,4,5],'x':[0,1,0],'y':[-1,0,0],'z':[0,0,1]}
        matrix=native.pose_matrix(pose)
        box=native.transformed({'min':[0,0,0],'max':[1,2,3]},matrix)
        self.assertEqual(box,{'min':[1,4,5],'max':[3,5,8]})
        with self.assertRaises(ValueError):native.pose_matrix({**pose,'z':[0,0,-1]})
        with self.assertRaises(ValueError):native.update({},[{'positions':[],'values':{},'stopped_by_contact':True}])


if __name__=='__main__':unittest.main()
