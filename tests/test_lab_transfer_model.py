"""Oriented tube endpoints, axial insertion and reversible sample ownership."""
from pathlib import Path
import copy
import json
import math
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import lab_transfer_motion as model
import lab_layout_model as layout


class LabTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=model.load();cls.ls=layout.load(validate_builds=False);cls.d=model.data(cls.s,cls.ls)
        cached=os.environ.get('SOLIDCRAFTBOT_L01_PROGRAM')
        cls.t=json.loads(Path(cached).read_text()) if cached else model.compile(cls.s,cls.ls)
        model.verify_sources(cls.t,cls.s,cls.ls)
        cls.ev=model.Evaluator(cls.t,cls.s,cls.ls,cls.d)

    def test_oriented_ik_matches_actual_arm_flange_and_tool_offset(self):
        for name,(point,axis) in self.d['targets'].items():
            q=self.t['poses'][name];actual,z=model.tcp(self.d,q,self.s)
            self.assertLess(math.dist(actual,point),0.0001)
            self.assertLess(math.dist(axis,z),0.0001)
            for v,j in zip(q,self.d['arm']['joints']):self.assertTrue(j['limits_deg'][0]<=v<=j['limits_deg'][1])

    def test_axial_insertion_has_no_radial_drift(self):
        axis=self.d['cf_axis'];seat=self.d['targets']['cf_seat'][0]
        keys=[k for k in self.t['keyframes'] if k['id']=='cf_insert']
        self.assertGreaterEqual(len(keys),20)
        for key in keys:
            point,z=model.tcp(self.d,key['q'],self.s);delta=[x-y for x,y in zip(point,seat)];along=sum(x*y for x,y in zip(delta,axis))
            self.assertLess(math.dist(delta,[v*along for v in axis]),0.0001)
            self.assertLess(math.dist(axis,z),0.0001)

    def test_actual_axial_curve_keeps_its_boundary_tangents_inside_the_source_tolerances(self):
        stages={stage['id']:stage for stage in self.s['sequence']}
        for identity in self.s['motion']['cartesian_stages']:
            start=min(e['time_s'] for e in self.t['events'] if e['phase']==identity)
            end=max(k['time_s'] for k in self.t['keyframes'] if k['id']==identity)
            target,axis=self.d['targets'][stages[identity]['arm_pose']]
            times={start+(end-start)*i/128 for i in range(129)}|{t for t in self.ev.arm.times if start<=t<=end}
            for t in times:
                point,z=model.tcp(self.d,self.ev(t)['q'],self.s);delta=[a-b for a,b in zip(point,target)];along=sum(a*b for a,b in zip(delta,axis))
                with self.subTest(stage=identity,time_s=t):
                    self.assertLessEqual(math.dist(delta,[v*along for v in axis]),self.s['checks']['tcp_error_mm'])
                    self.assertLessEqual(math.degrees(math.acos(max(-1,min(1,sum(a*b for a,b in zip(z,axis)))))),self.s['checks']['axis_error_deg'])

    def test_sample_is_continuous_at_grasp_release_and_returns_to_source(self):
        for key in self.t['keyframes']:
            if key['id'] not in ['vehicle_grasp','cf_release','return_grasp','vehicle_release']:continue
            if key['time_s']<0.001:continue
            before=self.ev(key['time_s']-0.00001)
            after=self.ev(key['time_s']+0.00001)
            self.assertLess(math.dist(before['sample_bottom'],after['sample_bottom']),0.01)
        start=model.at_time(self.t,0,self.s,self.ls,self.d);end=model.at_time(self.t,self.t['duration_s'],self.s,self.ls,self.d)
        self.assertEqual(start['sample_owner'],end['sample_owner'])
        self.assertEqual(start['sample_bottom'],end['sample_bottom'])

    def test_lid_moves_only_with_arm_parked_and_sample_seated(self):
        for a,b in zip(self.t['keyframes'],self.t['keyframes'][1:]):
            if a['cf']['Lid']==b['cf']['Lid']:continue
            for frame in (a,b):self.assertLess(max(abs(x-y) for x,y in zip(frame['q'],self.t['poses']['park'])),1e-9)
            self.assertEqual(b['sample_owner'],'CF01');self.assertEqual(b['cf']['TubeLift'],0)
            self.assertEqual(b['cf']['Rotor'],0)

    def test_unreachable_oriented_point_is_rejected(self):
        self.assertEqual(model.oriented_solutions(self.d,self.s,[0,0,5000],[0,0,1]),[])

    def test_oriented_bound_separation_is_conservative(self):
        matrix=layout.matrix({'xyz':[0,0,0],'yaw_deg':45},{})
        a=model.obb(matrix,[-10,-0.1,-1],[10,0.1,1])
        other=layout.matrix({'xyz':[-0.3,0.3,0],'yaw_deg':45},{})
        b=model.obb(other,[-10,-0.1,-1],[10,0.1,1])
        self.assertFalse(model.boxes_overlap(a,b))
        self.assertTrue(model.boxes_overlap(a,a))

    def test_loaded_and_empty_transports_have_only_quiet_endpoint_bands(self):
        self.assertEqual(sum(segment['loaded'] for segment in self.t['segments']),2)
        self.assertEqual(len(self.t['segments']),6)
        for segment in self.t['segments']:
            self.assertTrue(segment['no_stop']['passed'])
            self.assertEqual(len(segment['no_stop']['quiet_intervals_s']),2)
            for point in self.t['arm']['points']:
                if segment['start_s']+1e-5<point['time_s']<segment['end_s']-1e-5:
                    self.assertGreater(math.sqrt(sum(v*v for v in point[model.FIELDS[1]])),1e-6)

    def test_narrow_lid_passage_keeps_the_retained_source_joint_connection_knots(self):
        a=self.t['poses']['transit'];b=self.t['poses']['cf_pre'];delta=[y-x for x,y in zip(a,b)]
        denominator=sum(v*v for v in delta)
        start=next(e['time_s'] for e in self.t['events'] if e['phase']=='orient_before_lid')
        end=next(e['time_s'] for e in self.t['events'] if e['phase']=='pass_inside_lid')
        knots=[p for p in self.t['arm']['points'] if start-1e-8<=p['time_s']<=end+1e-8]
        self.assertGreater(len(knots),2)
        for point in knots:
            q=[math.degrees(v) for v in point[model.FIELDS[0]]];u=sum((x-y)*v for x,y,v in zip(q,a,delta))/denominator
            self.assertLess(max(abs(x-(y+u*v)) for x,y,v in zip(q,a,delta)),1e-8)
            self.assertGreaterEqual(u,-1e-8);self.assertLessEqual(u,1+1e-8)

    def test_inside_lid_uses_source_bound_lateral_reference_and_keeps_its_endpoints(self):
        keys=[k for k in self.t['keyframes'] if k['id']=='pass_inside_lid']
        self.assertEqual(len(keys),self.s['motion']['lid_passage']['reference_points']-1)
        start=self.d['targets']['cf_pre'][0];end=self.d['targets']['cf_side'][0];curve=model.lid_passage_curve(self.s['motion']['lid_passage'])
        for i,key in enumerate(keys,1):
            u=i/len(keys);expected=[a+(b-a)*u for a,b in zip(start,end)]
            expected[1]+=model.motion.evaluate(curve,u)[model.FIELDS[0]][0]
            point,_=model.tcp(self.d,key['q'],self.s);self.assertLess(math.dist(point,expected),.0001)
        for identity in model.CF_REFERENCE_STAGES:self.assertIn(identity,self.s['motion']['retained_stages'])

    def test_arm_and_station_are_c2_and_respect_source_bound_joint_caps(self):
        for curve in (self.ev.arm,self.ev.station):
            for time_s in curve.times[1:-1]:
                a=model.motion.evaluate(curve,time_s,side='left');b=model.motion.evaluate(curve,time_s,side='right')
                for field in model.FIELDS[:3]:self.assertLess(max(abs(x-y) for x,y in zip(a[field],b[field])),1e-8)
        for segment in self.t['segments']:
            caps=self.t['limits']['arm_loaded' if segment['loaded'] else 'arm_empty']
            for field,key in zip(model.FIELDS[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')):
                self.assertLessEqual(max(segment['joint_bounds'][field]['max_abs']),caps[key]*(1+1e-8))
            if segment['loaded']:self.assertLessEqual(model._sample_factor(segment['sample_bounds'],self.t['limits']),1+1e-8)

    def test_pusher_retracts_only_after_carried_envelope_clearance_without_arm_rest(self):
        segment=next(s for s in self.t['segments'] if 'park_pusher' in s['stage_ids'])
        event=next(e for e in self.t['events'] if e['phase']=='park_pusher')
        self.assertEqual(event['time_s'],segment['pusher_clear_s']);self.assertTrue(event['workspace_clear'])
        frame=self.ev(event['time_s']);self.assertEqual(frame['sample_owner'],'arm')
        self.assertGreater(math.sqrt(sum(v*v for v in frame['joint_state'][model.FIELDS[1]])),1e-6)
        jets=model.sample_motion.KinematicJets(model._kinematics(self.d,self.s))
        points=jets.evaluate(frame['joint_state'],points_mm=model.sample_points(self.d))['points']
        self.assertGreaterEqual(min(p['position_mm'][0] for p in points),self.d['targets']['transit'][0][0]-1e-7)
        before=self.ev(event['time_s']-1e-6);middle=self.ev((segment['pusher_clear_s']+segment['pusher_parked_s'])/2)
        self.assertGreater(before['cf']['TubeLift'],middle['cf']['TubeLift'])

    def test_mutated_curve_caps_and_station_contract_cannot_use_copied_audits(self):
        for mutation in ('velocity','limits','units','station_position','envelope'):
            program=copy.deepcopy(self.t)
            if mutation=='velocity':program['arm']['points'][2][model.FIELDS[1]][0]=25.
            elif mutation=='limits':program['limits']['arm_empty']['velocity_rad_s']=25.
            elif mutation=='units':program['station']['units'][0]='rad'
            elif mutation=='station_position':program['station']['points'][1]['p'][0]=1000.
            else:program['sample_envelope']['radius_mm']=6.4
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):model.validate_timeline(program,self.s,self.ls)

    def test_direct_construction_helpers_are_pinned_and_changes_reject_replay(self):
        original=model.robot.digest
        for name in ('centrifuge_model.py','centrifuge_mechanisms.py','sample_transport_model.py','robot_components.py','robot_cameras.py'):
            path=model.ROOT/'scripts'/name
            self.assertIn('scripts/'+name,self.t['sources_sha256'])
            def changed(value,selected=path):return '0'*64 if Path(value).resolve()==selected.resolve() else original(value)
            with self.subTest(helper=name),patch.object(model.robot,'digest',side_effect=changed),self.assertRaisesRegex(ValueError,'sources changed'):
                model.verify_sources(self.t,self.s,self.ls)

    def test_pusher_metadata_cannot_replace_actual_motion_or_vessel_clearance(self):
        jets=model.sample_motion.KinematicJets(model._kinematics(self.d,self.s))
        for mutation in ('metadata','early_motion'):
            program=copy.deepcopy(self.t);segment=next(v for v in program['segments'] if 'park_pusher' in v['stage_ids'])
            if mutation=='metadata':segment['pusher_clear_s']-=.1
            else:
                start,end=segment['pusher_clear_s'],segment['pusher_parked_s'];early=segment['start_s']+.1;shift=start-early
                for point in program['station']['points']:
                    if start-1e-8<=point['time_s']<=end+1e-8:point['time_s']-=shift
                for event in program['events']:
                    if event['phase']=='park_pusher':event['time_s']-=shift
                program['events'].sort(key=lambda e:e['time_s'])
                segment['pusher_clear_s']-=shift;segment['pusher_parked_s']-=shift
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'actual station motion|whole-vessel clearance'):
                model.validate_pusher_overlap(program,model.Evaluator(program,self.s,self.ls,self.d),self.d,self.s,jets)

    def test_sample_envelope_includes_actual_collar_and_cap_create_join_operations(self):
        envelope=model.sample_envelope(self.d)
        self.assertAlmostEqual(envelope['radius_mm'],7.)
        self.assertIn('TubeCollar01',envelope['source_operation_ids']);self.assertIn('Cap01',envelope['source_operation_ids'])
        bottom,axis=model.cf.pocket(self.d['cs'],self.d['cp'],1)
        for operation in self.d['ce']['operations']:
            if operation.get('body') not in ('Tube01','ClosedCap01') or operation.get('action') not in ('create','join'):continue
            shape=operation['shape'];start=sum((x-y)*z for x,y,z in zip(shape['origin'],bottom,axis));finish=start+shape['height']
            radii=[shape['radius'],shape['top_radius']] if shape['kind']=='cone' else [shape['radius']]
            self.assertGreaterEqual(envelope['radius_mm'],max(radii))
            self.assertLessEqual(envelope['axial_min_mm'],start+1e-9);self.assertGreaterEqual(envelope['axial_max_mm']+1e-9,finish)
        changed=copy.deepcopy(self.d)
        collar=next(o for o in changed['ce']['operations'] if o['id']=='TubeCollar01')
        collar['shape']['radius']=9.;collar['shape']['height']+=10.
        derived=model.sample_envelope(changed)
        self.assertAlmostEqual(derived['radius_mm'],9.);self.assertGreater(derived['axial_max_mm'],envelope['axial_max_mm'])
        self.assertEqual(len(model.sample_points(changed)),11)


class ContinuousDefinitionTests(unittest.TestCase):
    def test_stale_layout_or_limits_and_unimplemented_wait_contract_are_rejected(self):
        original=model.load()
        for kind in ('layout','limits','wait'):
            value=copy.deepcopy(original)
            if kind=='layout':value['motion']['layout_sha256']='0'*64
            elif kind=='limits':value['motion']['limits_reference']['source_sha256']='0'*64
            else:value['motion']['necessary_waits']['park_pusher']='presentation'
            with self.subTest(kind=kind),self.assertRaises(ValueError):model.validate_definition(value)

    def test_portable_schema_matches_the_implemented_source(self):
        from jsonschema import Draft202012Validator
        schema=json.loads(model.SCHEMA.read_text());Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(model.load())


class ContinuousFitTests(unittest.TestCase):
    def test_lateral_reference_is_c2_and_preserves_source_endpoint_tangents(self):
        settings=model.load()['motion']['lid_passage'];curve=model.lid_passage_curve(settings)
        for t in curve.times[1:-1]:
            a=model.motion.evaluate(curve,t,side='left');b=model.motion.evaluate(curve,t,side='right')
            for field in model.FIELDS[:3]:self.assertAlmostEqual(a[field][0],b[field][0],places=8)
        for t in (0.,1.):
            for field in model.FIELDS[:3]:self.assertAlmostEqual(model.motion.evaluate(curve,t)[field][0],0.,places=10)
        self.assertAlmostEqual(model.motion.evaluate(curve,.75)[model.FIELDS[0]][0],-50.)
    def test_narrow_passage_reference_derives_every_joint_knot_from_source_poses(self):
        stage={'id':'orient_before_lid','duration_s':4.}
        previous=[-20.,0.,12.,3.,4.,15.];target=[-10.,9.,-2.,3.,6.,15.]
        nodes=model.retained_joint_reference(stage,7.,previous,target,2.)
        self.assertEqual(nodes[-1]['q'],target);self.assertEqual(nodes[-1]['time_s'],11.)
        for i,node in enumerate(nodes,1):
            u=i/len(nodes)
            for actual,expected in zip(node['q'],[a+(b-a)*u for a,b in zip(previous,target)]):self.assertAlmostEqual(actual,expected,places=12)
            before=previous if i==1 else nodes[i-2]['q']
            self.assertLessEqual(max(abs(a-b) for a,b in zip(before,node['q'])),2.)

    def test_single_path_clock_is_monotone_and_spreads_endpoint_acceleration(self):
        clock=model._path_clock(10.,{'velocity_s1':1.,'acceleration_s2':2.,'jerk_s3':20.})
        self.assertEqual(clock(0.),0.);self.assertEqual(clock(10.),10.)
        values=[clock(i/10) for i in range(101)]
        self.assertTrue(all(a<b for a,b in zip(values,values[1:])))
        self.assertGreater(clock(.01),.01)
        self.assertAlmostEqual(clock(.01),10-clock(9.99),places=8)

    def test_position_tangent_damping_keeps_knots_and_c2_without_changing_limits(self):
        points=[model._point(0.,[0.]),model._point(1.,[1.],[5.]),model._point(2.,[1.1])]
        original=[p[model.FIELDS[0]][:] for p in points];joints=[{'limits_deg':[0.,70.]}]
        self.assertGreater(model.motion.bounds(points)[model.FIELDS[0]]['max'][0],math.radians(70.))
        result=model._limit_tangents(points,joints)
        self.assertGreater(result['iterations'],0);self.assertEqual(original,[p[model.FIELDS[0]] for p in points])
        self.assertLessEqual(model.motion.bounds(points)[model.FIELDS[0]]['max'][0],math.radians(70.)+1e-9)
        left=model.motion.evaluate(points,1.,side='left');right=model.motion.evaluate(points,1.,side='right')
        for field in model.FIELDS[:3]:self.assertAlmostEqual(left[field][0],right[field][0],places=9)
        self.assertEqual(joints,[{'limits_deg':[0.,70.]}])

    def test_damping_cannot_hide_an_out_of_bounds_source_pose(self):
        points=[model._point(0.,[0.]),model._point(1.,[2.])]
        with self.assertRaisesRegex(ValueError,'cannot be satisfied'):
            model._limit_tangents(points,[{'limits_deg':[0.,70.]}])


if __name__=='__main__':unittest.main()
