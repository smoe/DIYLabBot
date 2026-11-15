"""Analytic IK, interval motion and continuous-clearance regression controls."""
import copy
import itertools
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import h02_arm_pickup as m
import sample_motion


class ArmPickupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.program=m.Program()

    def test_reach_joint_limits_and_synthetic_derivative_limits_are_continuous(self):
        report=self.program.audit();self.assertTrue(report['passed']);self.assertEqual(report['arm_overrides'],{})
        for phase in report['phases']:
            self.assertLess(phase['maximum_FK_residual'],1e-7)
            for name,value in phase['maximum_joint_derivatives'].items():self.assertLessEqual(value,phase['limits'][name])
            for actual,j in zip(phase['joint_ranges_deg'],self.program.arm['joints']):
                self.assertGreaterEqual(actual[0],j['limits_deg'][0]);self.assertLessEqual(actual[1],j['limits_deg'][1])

    def test_limit_driven_timing_attains_acceleration_and_jerk_caps(self):
        report=self.program.scalar_audit();self.assertLess(report['duration_s'],9)
        self.assertAlmostEqual(self.program.durations['approach'],3.7)
        for phase in report['phases']:
            self.assertAlmostEqual(phase['maximum_derivatives']['acceleration_mm_s2'],20,places=7)
            self.assertAlmostEqual(phase['maximum_derivatives']['jerk_mm_s3'],100,places=6)
            curve=self.program.curves[phase['phase']]
            for t in curve.times[1:-1]:
                left=m.motion.evaluate(curve,t,side='left');right=m.motion.evaluate(curve,t,side='right')
                for field in m.motion.FIELDS[:3]:self.assertAlmostEqual(left[field][0],right[field][0],places=7)
            for i in range(1,100):self.assertGreater(abs(m.motion.evaluate(curve,curve.times[-1]*i/100)[m.motion.FIELDS[1]][0]),0)

    def test_exact_branch_matches_shared_fk_and_tool_derivatives(self):
        for phase in ['approach','extraction']:
            for u in [0,.01,.2,.5,.8,.99,1]:
                state=self.program.state(phase,u);expected=m.motion.evaluate(self.program.curves[phase],u*self.program.durations[phase])
                fk=sample_motion.evaluate(self.program.kin,state['joint_state'])
                for index,name in enumerate(sample_motion.LINEAR):
                    self.assertAlmostEqual(fk[name][0],0,places=8);self.assertAlmostEqual(fk[name][1],0,places=8)
                    self.assertAlmostEqual(fk[name][2],expected[m.motion.FIELDS[index]][0],places=8)
                if 0<u<1:
                    self.assertGreater(abs(state['joint_state']['velocities_rad_s'][2]),0)

    def test_interval_joint_hulls_contain_actual_states_and_derivatives(self):
        for phase in self.program.curves:
            for a,b in [(0,1),(.12,.37),(.51,.6),(.999,1)]:
                bounds,_=self.program.ranges(phase,a,b)
                for n in range(11):
                    state=self.program.state(phase,a+(b-a)*n/10)
                    for index,f in enumerate(m.motion.FIELDS):
                        for q,actual in zip(bounds,state['joint_state'][f]):
                            interval=m.interval(q.d[index]);self.assertGreaterEqual(actual,interval.lo-1e-10);self.assertLessEqual(actual,interval.hi+1e-10)

    def test_all_point_rigid_link_bound_contains_interior_corner_motion(self):
        for index,link in enumerate(self.program.links[1:],1):
            origin=self.program.origins[index-1]
            record={'id':link,'group':link,'kind':'arm','local_bbox':{'min':[v-25 for v in origin],'max':[v+35 for v in origin]}}
            for a,b in [(0,1),(.2,.4),(.5,.501)]:
                bound=self.program.delta('extraction',a,b,record)
                mid=self.program.kin.forward(self.program.state('extraction',(a+b)/2)['joints_deg'])[link]
                for u in [a,a+(b-a)*.13,(a+b)/2,b]:
                    frame=self.program.kin.forward(self.program.state('extraction',u)['joints_deg'])[link]
                    for point in itertools.product(*zip(record['local_bbox']['min'],record['local_bbox']['max'])):
                        self.assertLessEqual(math.dist(m.robot.transform(mid,point),m.robot.transform(frame,point)),bound+1e-9)

    def test_unreachable_layout_and_unsupported_frame_are_rejected(self):
        definition=copy.deepcopy(self.program.definition);definition['arm_fixture']['position_mm'][1]=-1000
        with self.assertRaises(ValueError):m.Program(definition).audit()
        definition=copy.deepcopy(self.program.definition);definition['arm_fixture']['position_mm'][0]=1
        with self.assertRaises(ValueError):m.Program(definition)

    def test_each_cad_backend_resolves_only_its_own_executable(self):
        import build_h02_arm_pickup as builder
        for backend,required,foreign in [('freecad','freecad_python','solidcraft_cli'),('solidcraft','solidcraft_cli','freecad_python')]:
            def resolve(parser,options,required=()):
                self.assertEqual(tuple(required),(expected,))
                self.assertFalse(hasattr(options,foreign))
                setattr(options,expected,'/verified/tool')
            expected=required
            with mock.patch.object(builder.tool_paths,'resolve_tool_arguments',side_effect=resolve),mock.patch.object(builder,'build',return_value=True) as build:
                self.assertTrue(builder.main(['--backend',backend,'--no-render']))
                self.assertEqual(getattr(build.call_args.args[0],required),'/verified/tool')

    def test_held_sample_is_not_moved_before_grasp(self):
        for phase in ['approach','closure']:
            for u in [0,.5,1]:self.assertEqual(self.program.state(phase,u)['coordinates']['TubeZ'],0)
        for u in [0,.2,.6,1]:
            c=self.program.state('extraction',u)['coordinates'];self.assertEqual(c['TubeZ'],c['ToolZ']);self.assertEqual(c['JawLeft'],0)

    def fake(self,max_depth=4):
        definition={'clearance_mm':{'self':.5,'arm_tool':.5,'environment':1},'continuous_audit':{'max_depth':max_depth,'numeric_guard_mm':1e-5},
            'support_plane':{'origin_mm':[-100,-100,-1],'size_mm':[200,200,1]}}
        p=types.SimpleNamespace(definition=definition,links=['Base','Link'],curves={'extraction':None},delta=lambda *args:20)
        records=[{'id':'moving','group':'Link','kind':'arm'},{'id':'fixed','group':'Ground','kind':'fixture'}]
        return p,records

    def test_midpath_collision_is_detected_with_clear_endpoints(self):
        p,records=self.fake()
        def provider(requests):
            result=[]
            for phase,u,width in requests:
                x=20*(2*u-1)**2
                boxes={'moving':{'min':[x,0,10],'max':[x+1,1,11]},'fixed':{'min':[0,0,10],'max':[1,1,11]}}
                result.append({'boxes':boxes,'fk_error_mm':0,'distance':lambda a,b,box=boxes:m.bbox_distance(box[a],box[b])})
            return result
        self.assertGreater(provider([('extraction',0,0)])[0]['distance']('moving','fixed'),1)
        self.assertGreater(provider([('extraction',1,0)])[0]['distance']('moving','fixed'),1)
        report=m.certify(p,records,provider);self.assertFalse(report['passed']);self.assertIn('collisions_or_margin_failures',report['failures'][0])

    def test_unresolved_bounds_and_nonfinite_native_results_fail_closed(self):
        p,records=self.fake(max_depth=0)
        def provider(requests):
            return [{'boxes':{r['id']:{'min':[0,0,10],'max':[1,1,11]} for r in records},'fk_error_mm':0,
                     'coarse_lower_bounds_only':True,'distance':lambda a,b:0} for request in requests]
        self.assertFalse(m.certify(p,records,provider)['passed'])
        def invalid(requests):
            result=provider(requests)
            for frame in result:frame['fk_error_mm']=float('nan')
            return result
        with self.assertRaises(ValueError):m.certify(p,records,invalid)


if __name__=='__main__':unittest.main()
