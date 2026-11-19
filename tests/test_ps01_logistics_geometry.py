"""Exact supported IK, shared receiver geometry and fail-closed motion bindings."""
import copy
import json
import math
import itertools
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ps01_logistics_geometry as geometry
import ps01_logistics_motion as motion
import analytics_concept
from ps01_logistics_validation import Program


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.scene=geometry.Scene()

    def test_both_supported_handoffs_are_reachable_with_exact_upright_tool(self):
        scene=self.scene
        for station in scene.stations:
            kin=scene.kin(station);seed=scene.arms[station+'.PS01TransferArm']['joints_deg']
            for frame in (scene.load_frame(station),*(scene.frames[station+'.'+p] for p in ('InfeedRack','InfeedTips','Outfeed'))):
                point=geometry.s.robot.transform(frame,[0,0,scene.hp['foot_h']])
                q=motion.upright_ik(kin,point,seed);actual=kin.tool(q);target=motion.tool_target(point,0,90)
                self.assertLess(max(abs(actual[i][3]-point[i]) for i in range(3)),1e-7)
                self.assertLess(max(abs(actual[i][j]-target[i][j]) for i in range(3) for j in range(3)),1e-9)
                self.assertTrue(all(lo<=v<=hi for v,(lo,hi) in zip(q,kin.limits)))

    def test_one_receiver_retains_pin_clearances_and_neighbor_load(self):
        scene=self.scene;parts={p['id']:p for p in scene.car_parts}
        self.assertIn('B2_Tube24',parts);self.assertNotIn('B1_Tube01',parts)
        self.assertEqual(len(parts['LT01ReceiverBase']['cuts']),len(scene.vehicle_spec['cassette_interface']['pin_pattern_mm']))
        for body in ('Carrier.Stock10','Carrier.Stock200','Carrier.Stock1000','Carrier.Plate01','Carrier.Rack01'):
            corners=[geometry.part_bounds(p) for p in scene.payloads[body]]
            height=max(p['max'][2] for p in corners)
            inside_top=scene.cover['cuts'][0]['origin'][2]+scene.cover['cuts'][0]['size'][2]
            self.assertGreater(inside_top,scene.car_surface[2]+height)

    def test_port_instances_move_without_copying_or_mutating_original_setup(self):
        scene=self.scene;before=copy.deepcopy(scene.context['handling']['frames'])
        self.assertEqual(scene.frames['PS01.InfeedRack'][1][3],-300)
        self.assertEqual(scene.context['handling']['frames']['PS01.InfeedRack'][1][3],330)
        self.assertEqual(scene.context['handling']['frames'],before)
        self.assertEqual(scene.frames['RF02.InfeedRack'][0][3]-scene.frames['PS01.InfeedRack'][0][3],1400)

    def test_native_primitive_commands_preserve_tr01_wheel_axis(self):
        scene=self.scene
        wheel=next(p for p in scene.car_parts if p['shape'].get('axis') not in (None,[0,0,1]))
        commands,_=analytics_concept.primitive_commands('AxisWitness',[wheel],geometry.s.robot.identity())
        actual=next(c for c in commands if c['command']=='solid.cylinder')['params']['axis']
        self.assertEqual(actual,wheel['shape']['axis'])

    def test_empty_motion_export_preserves_continuity_and_limits(self):
        scene=self.scene;spec=motion.load();a=scene.park('PS01')
        b=geometry.s.robot.transform(scene.frames['PS01.Outfeed'],[0,0,scene.hp['foot_h']])
        points=motion.path(scene,'PS01',a,b,empty_start=True,spec=spec)
        compiled=motion.curve(scene,'PS01',points,[],False,spec)
        restored=json.loads(json.dumps(compiled))
        self.assertTrue(restored['no_stop']['passed'])
        caps=geometry.s.bound(spec['arm_limits'])['limits']['arm_empty']
        actual=motion.motion.bounds(restored['points'])
        for field,key in zip(motion.F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')):
            self.assertLessEqual(max(actual[field]['max_abs']),caps[key])
        for node in (restored['points'][0],restored['points'][-1]):
            self.assertEqual(node[motion.F[1]],[0.]*6)
            self.assertEqual(node[motion.F[2]],[0.]*6)

    def test_relative_collision_bound_cancels_upstream_motion_and_encloses_suffix(self):
        scene=self.scene;kin=scene.kin('PS01')
        links=[v['id'] for v in geometry.s.robot.expanded(kin.arm)['links']]
        q=motion.upright_ik(kin,scene.park('PS01'),scene.arms['PS01.PS01TransferArm']['joints_deg'])
        anchor={'id':'Anchor','kind':'arm','station':'PS01','link':links[2]}
        tool={'id':'Tool','kind':'tool','station':'PS01','jaw_sign':0,
              'local_bbox':{'min':[-30,-30,-175],'max':[30,30,0]}}
        witness=object.__new__(Program);witness.scene=scene;witness.link_ids={'PS01':links}
        witness.data={'load':{'station':'PS01'}};witness.metadata={'test':('load','approach')}
        witness.records={'Anchor':anchor,'Tool':tool}
        witness.state=lambda *args:{'joints':{'PS01':q},'gaps':{'PS01':scene.hp['open_gap']}}
        for joint in (0,4):
            low=[math.radians(x) for x in q];high=low[:];low[joint]-=.1;high[joint]+=.1
            witness.ranges=lambda *args:{'min':low,'max':high}
            bound=witness.relative_excursion({'a':'Anchor','b':'Tool'},'test',0,1)
            mid=geometry.s.robot.multiply(geometry.s.robot.inverse(kin.forward(q)[links[2]]),kin.tool(q))
            observed=0.
            for delta in [-.1,-.05,0,.05,.1]:
                shifted=q[:];shifted[joint]+=math.degrees(delta)
                actual=geometry.s.robot.multiply(geometry.s.robot.inverse(kin.forward(shifted)[links[2]]),kin.tool(shifted))
                for corner in itertools.product(*zip(tool['local_bbox']['min'],tool['local_bbox']['max'])):
                    observed=max(observed,math.dist(geometry.s.robot.transform(actual,corner),geometry.s.robot.transform(mid,corner)))
            self.assertLessEqual(observed,bound+1e-7)
            if joint==0:self.assertLess(bound,1e-6)
            else:self.assertGreater(observed,1.)

    def test_sliding_support_plane_is_preserved_but_a_crossing_is_not_certified(self):
        witness=object.__new__(Program)
        witness.data={'load':{'station':'PS01'}};witness.metadata={'slide':('load','close')}
        witness.definition={'continuous_audit':{'numeric_guard_mm':1e-5}}
        witness.records={'Base':{'id':'Base','kind':'sample'},'Lip':{'id':'Lip','kind':'tool','station':'PS01','jaw_sign':1}}
        nodes=motion.motion.rest_to_rest(24,50,200,2000);witness.curves={'slide':motion.motion.Curve(nodes)}
        witness.ranges=lambda *args:motion.motion.bounds(nodes)[motion.F[0]]
        witness.tool_frame=lambda *args:geometry.s.robot.identity()
        frame={'fk_error_mm':0.,'boxes':{'Base':{'min':[0,0,0],'max':[10,10,2]},
                'Lip':{'min':[0,0,-2],'max':[10,10,0]}},'distance':lambda *args:0.}
        pair={'a':'Base','b':'Lip','category':'seating_contact'}
        bound=witness.translation_sweep_bound(pair,'slide',0,1,frame)
        self.assertAlmostEqual(bound,-1e-5)
        frame['boxes']['Lip']['max'][2]=.1
        self.assertIsNone(witness.translation_sweep_bound(pair,'slide',0,1,frame))

    def test_partition_suggestions_preserve_full_intervals_and_recheck_native_frames(self):
        from audit_ps01_logistics_solidcraft import certify_partitioned
        calls=[];bounds=[]
        records=[{'id':'A','kind':'fixture','group':'A'},{'id':'B','kind':'fixture','group':'B'}]
        pairs=[{'a':'A','b':'B','category':'environment','required_mm':.1}]
        program=SimpleNamespace(curves={'path':None},links=['base'],
            definition={'continuous_audit':{'numeric_guard_mm':1e-5,'max_depth':4},
                        'support_plane':{'origin_mm':[-10,-10,0],'size_mm':[20,20,1]}},
            collision_pairs=lambda items:(pairs,[]),
            delta=lambda phase,a,b,record:bounds.append((phase,a,b)) or 0.,
            pair_bound=lambda *args:None)
        def provider(requests):
            calls.extend(requests)
            return [{'boxes':{'A':{'min':[0,0,0],'max':[1,1,1]},'B':{'min':[3,0,0],'max':[4,1,1]}},
                     'distance':lambda *args:2.,'fk_error_mm':0.} for _ in requests]
        suggestion={'passed':True,'maximum_depth':1,'continuous_intervals':[
            {'phase':'path','interval':span,'minimum_margin_beyond_required_mm':.5} for span in ([0,.3],[.3,1])]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'partition.json';path.write_text(json.dumps(suggestion))
            report=certify_partitioned(program,records,provider,path)
        self.assertTrue(report['passed'])
        self.assertEqual([r['interval'] for r in report['continuous_intervals']],[[0,.3],[.3,1.]])
        self.assertEqual(calls,[('path',.15,.3),('path',.65,.7)])
        self.assertEqual(set(bounds),{('path',0.,.3),('path',.3,1.)})


if __name__=='__main__':unittest.main()
