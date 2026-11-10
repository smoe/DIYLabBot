"""Exact PVA validation and ROS serialization, without ROS or hardware execution."""
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion
from solidcraftbot_ros.protocol import scenario,message_point,duration_parts
import export_cf01_unload_ros2 as export


class WireContinuousMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=os.environ.get('SOLIDCRAFTBOT_UNLOAD_PROGRAM')
        if not source:raise unittest.SkipTest('Requires the new source-current compiled program')
        import cf01_unload_motion as compiler
        import cf01_unload_validation as validation
        cls.compiler=compiler;cls.validation=validation
        cls.program=json.loads(Path(source).read_text());cls.config=export.configuration(cls.program)
        cls.points=cls.config['scenarios'][0]['points'];cls.curve=motion.Curve(cls.points)
        scene=cls.program['scene'];spec=compiler.pickup.cf.load();p=compiler.pickup.cf.parameters(spec)
        cls.jets=compiler.sample_motion.KinematicJets(compiler.pickup.Kinematics(compiler.pickup.arm_source(scene),scene))
        cls.references={t['sample_id']:[compiler.pickup.robot.transform(t['attachment_matrix'],point)
            for point in compiler.sample_reference_points(spec,p,t['rotor_slot'])] for t in cls.program['transfers']}

    def test_quantized_ros_curves_keep_the_continuous_loaded_traversals(self):
        self.assertEqual(len(self.points),len(self.program['arm']['points']))
        self.assertTrue(self.config['nanosecond_quantization']['passed'])
        for transfer in self.program['transfers']:
            start=round(transfer['gripped_s']*1e9)/1e9;end=round(transfer['seated_s']*1e9)/1e9
            proof=self.validation.no_stop(self.curve,start,end,self.jets,self.references[transfer['sample_id']],self.program['definition']['routes'])
            self.assertTrue(proof['passed'])

    def test_an_inserted_wire_rest_is_not_hidden_by_quantization_audit(self):
        transfer=self.program['transfers'][0];points=copy.deepcopy(self.points)
        interior=[point for point in points if transfer['gripped_s']+.5<point['time_s']<transfer['seated_s']-.5]
        self.assertTrue(interior);point=interior[len(interior)//2]
        point['velocities_rad_s']=[0.]*6;point['accelerations_rad_s2']=[0.]*6
        with self.assertRaisesRegex(ValueError,'stop|resting'):
            self.validation.no_stop(motion.Curve(points),round(transfer['gripped_s']*1e9)/1e9,
                round(transfer['seated_s']*1e9)/1e9,self.jets,self.references[transfer['sample_id']],self.program['definition']['routes'])


def point(time,p=0,v=0,a=0):
    return {'time_s':time,'positions_rad':[p]*6,'velocities_rad_s':[v]*6,'accelerations_rad_s2':[a]*6}


def config(points):
    return {'joint_names':['j'+str(i) for i in range(6)],'limits_rad':[[-10,10]]*6,
            'mode':'mock','motion_limits':{'qualified':False,'velocity_rad_s':1,
                'acceleration_rad_s2':10,'jerk_rad_s3':100},
            'interpolation':{'method':'quintic','controller_interpolation':'splines','live_configuration_verified':False},
            'scenarios':[{'id':'synthetic','points':points}]}


class DerivativeProtocolTests(unittest.TestCase):
    def test_positions_only_legacy_validation_and_messages_are_unchanged(self):
        value={'joint_names':['j'+str(i) for i in range(6)],'limits_rad':[[-10,10]]*6,
               'velocity_limit_rad_s':.5,'scenarios':[{'id':'legacy','points':[
                   {'time_s':0,'positions_rad':[0]*6},{'time_s':1,'positions_rad':[.1]*6}]}]}
        self.assertIs(scenario(value,'legacy'),value['scenarios'][0])
        value['scenarios'][0]['points'][1]['positions_rad'][0]=1
        with self.assertRaisesRegex(ValueError,'mock velocity limit'):scenario(value,'legacy')

    def test_all_or_none_derivatives_and_finite_six_axis_vectors(self):
        for field in ['positions_rad','velocities_rad_s','accelerations_rad_s2']:
            for defect in [float('nan'),float('inf'),True,'1']:
                value=config([point(0),point(1,.1)])
                value['scenarios'][0]['points'][1][field][0]=defect
                with self.subTest(field=field,defect=defect),self.assertRaises(ValueError):scenario(value,'synthetic')
        value=config([point(0),point(1,.1)])
        del value['scenarios'][0]['points'][0]['velocities_rad_s']
        with self.assertRaisesRegex(ValueError,'supplied together'):scenario(value,'synthetic')
        value=config([point(0),point(1,.1)])
        value['scenarios'][0]['points'][1]['accelerations_rad_s2'].pop()
        with self.assertRaisesRegex(ValueError,'Six finite'):scenario(value,'synthetic')

    def test_nan_reordered_and_unrepresentable_times_are_rejected(self):
        for time in [float('nan'),float('inf'),-1,0,True,1e-13,1.0000000004]:
            value=config([point(0),point(time,.1)])
            with self.subTest(time=time),self.assertRaises(ValueError):scenario(value,'synthetic')
        for time in [float('nan'),float('inf'),-1]:
            with self.assertRaises(ValueError):duration_parts(time)

    def test_endpoint_derivatives_are_checked_even_if_positions_are_constant(self):
        for field in ['velocities_rad_s','accelerations_rad_s2']:
            value=config([point(0),point(1)])
            value['scenarios'][0]['points'][0][field][0]=1000
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Quintic interior'):scenario(value,'synthetic')

    def test_interior_velocity_acceleration_and_jerk_exceed_limits_despite_rest_knots(self):
        for limit,maximum in [('velocity_rad_s',.15),('acceleration_rad_s2',.4),('jerk_rad_s3',4)]:
            value=config([point(0),point(1,.1)])
            value['motion_limits'][limit]=maximum
            with self.subTest(limit=limit),self.assertRaisesRegex(ValueError,limit):scenario(value,'synthetic')

    def test_interior_position_overshoot_is_not_hidden_by_valid_endpoints(self):
        value=config([point(0,0,4),point(1,0,-4)])
        value['limits_rad']=[[-.1,.1]]*6
        value['motion_limits'].update(velocity_rad_s=100,acceleration_rad_s2=100,jerk_rad_s3=1000)
        with self.assertRaisesRegex(ValueError,'interior joint position'):scenario(value,'synthetic')

    def test_explicit_mock_limits_and_unverified_spline_contract_are_required(self):
        original=config([point(0),point(2,.1)])
        for change in ['no_contract','linear','verified','qualified','no_jerk','bad_limit']:
            value=copy.deepcopy(original)
            if change=='no_contract':value.pop('interpolation')
            elif change=='linear':value['interpolation']['controller_interpolation']='none'
            elif change=='verified':value['interpolation']['live_configuration_verified']=True
            elif change=='qualified':value['motion_limits']['qualified']=True
            elif change=='no_jerk':value['motion_limits'].pop('jerk_rad_s3')
            else:value['motion_limits']['acceleration_rad_s2']=float('nan')
            with self.subTest(change=change),self.assertRaises(ValueError):scenario(value,'synthetic')

    def test_message_stub_preserves_every_derivative_and_nanosecond_duration(self):
        def factory():return SimpleNamespace(positions=[],velocities=[],accelerations=[],time_from_start=SimpleNamespace(sec=0,nanosec=0))
        knot=point(1.123456789,.1,.2,.3)
        result=message_point(knot,factory)
        self.assertEqual(result.positions,knot['positions_rad'])
        self.assertEqual(result.velocities,knot['velocities_rad_s'])
        self.assertEqual(result.accelerations,knot['accelerations_rad_s2'])
        self.assertEqual((result.time_from_start.sec,result.time_from_start.nanosec),(1,123456789))
        result=message_point({'time_s':0,'positions_rad':[0]*6},factory)
        self.assertEqual((result.velocities,result.accelerations),([],[]))

    def test_derivative_config_dry_run_uses_the_same_validator_without_ros(self):
        value=config([point(0),point(2,.1)])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'program.json';path.write_text(json.dumps(value))
            result=subprocess.run([sys.executable,'-B','-m','solidcraftbot_ros.demo','--dry-run',
                '--config',str(path),'--scenario','synthetic'],cwd=ROOT,
                env={**os.environ,'PYTHONPATH':str(ROOT/'ros2_ws/src/solidcraftbot_ros')},
                capture_output=True,text=True,timeout=15,check=True)
        self.assertEqual(json.loads(result.stdout)['scenario'],value['scenarios'][0])


class UnloadExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous=export.previous
        cls.scene=previous.pickup.load();arm=previous.pickup.arm_source(cls.scene)
        pose=[math.radians(joint['home_deg']) for joint in arm['joints']]
        second=pose[:];second[0]+=.01
        points=motion.from_positions([0,2.0000000004],[pose,second])
        cls.program={'format':'solidcraftbot.cf01-unload-program/1','scene':cls.scene,
            'arm':{'points':points,'limits_rad':[[math.radians(v) for v in joint['limits_deg']] for joint in arm['joints']]},
            'source_files_sha256':previous.source_hashes(cls.scene),
            'robot_description_requirements':previous.robot_description_requirements(cls.scene,arm),
            'limits':{'qualified':False,
                'arm_loaded':{'velocity_rad_s':.5,'acceleration_rad_s2':2,'jerk_rad_s3':20},
                'arm_empty':{'velocity_rad_s':1,'acceleration_rad_s2':2,'jerk_rad_s3':20},'biological_tolerance':None}}

    def test_header_is_reused_without_computing_the_legacy_trajectory(self):
        with patch.object(export.previous.pickup,'trajectory',side_effect=AssertionError('Legacy trajectory must not run')):
            value=export.configuration(self.program)
        self.assertEqual(value['robot_description_requirements'],self.program['robot_description_requirements'])
        self.assertEqual(value['included_channels'],['six_arm_joints'])
        self.assertIn('gripper',value['excluded_channels'])
        self.assertEqual(value['interpolation']['controller_interpolation'],'splines')
        self.assertFalse(value['interpolation']['live_configuration_verified'])
        self.assertFalse(any(value['verification'].values()))
        self.assertEqual(value['motion_limits']['velocity_rad_s'],1)

    def test_nanosecond_knots_keep_pva_and_bound_actual_polynomial_change(self):
        value=export.configuration(self.program)
        actual=value['scenarios'][0]['points'];original=self.program['arm']['points']
        self.assertEqual(actual[-1]['time_s'],2)
        self.assertEqual(actual[-1]['positions_rad'],original[-1]['positions_rad'])
        self.assertEqual(actual[-1]['velocities_rad_s'],original[-1]['velocities_rad_s'])
        self.assertTrue(value['nanosecond_quantization']['passed'])
        for time in [0,.25,.5,1,1.75,2]:
            expected=motion.evaluate(original,time);wire=motion.evaluate(actual,time)
            for field in export.FIELDS:
                observed=max(abs(a-b) for a,b in zip(expected[field],wire[field]))
                self.assertLessEqual(observed,value['nanosecond_quantization']['maximum_error_bounds'][field]+1e-13)

    def test_quantization_collapsed_knots_and_nonrest_endpoints_are_rejected(self):
        for points in [[point(0),point(4e-10)], [point(0),point(1,0,.1)], [point(0,0,0,.1),point(1)],
                       [point(0),point(1,0,1e-13)]]:
            with self.assertRaisesRegex(ValueError,'collapses|rest velocity'):export.quantize(points)

    def test_shifted_internal_knot_preserves_c2_reference_with_nonzero_derivatives(self):
        program=copy.deepcopy(self.program)
        initial=program['arm']['points'][0]['positions_rad']
        middle=initial[:];middle[0]+=.01
        last=initial[:];last[0]+=.03
        reference=motion.from_positions([0,.7000000004,2.0000000003],[initial,middle,last])
        self.assertNotEqual(reference[1]['velocities_rad_s'][0],0)
        program['arm']['points']=reference
        value=export.configuration(program);wire=value['scenarios'][0]['points']
        for time in [.1,.6999999999,.7,.7000000004,.7000000005,1,1.9,2]:
            a=motion.evaluate(reference,time);b=motion.evaluate(wire,time)
            for field in export.FIELDS:
                observed=max(abs(x-y) for x,y in zip(a[field],b[field]))
                self.assertLessEqual(observed,value['nanosecond_quantization']['maximum_error_bounds'][field]+1e-12)

    def test_dense_moving_knots_are_resampled_instead_of_retimed_with_stale_jets(self):
        duration=.1000000004;reference=[]
        for i in range(257):
            u=i/256
            p=1+.01*(10*u**3-15*u**4+6*u**5)
            v=.01/duration*(30*u*u*(1-u)**2)
            a=.01/duration**2*(60*u*(1-u)*(1-2*u))
            reference.append(point(duration*u,p,v,a))
        copied=copy.deepcopy(reference)
        for knot in copied:knot['time_s']=round(knot['time_s']*1e9)/1e9
        with self.assertRaisesRegex(ValueError,'differs from compiled reference'):
            export.quantization_audit(reference,copied)
        wire=export.quantize(reference)
        audit=export.quantization_audit(reference,wire)
        self.assertTrue(audit['passed'])
        self.assertEqual(audit['tolerances'],{'positions_rad':1e-7,'velocities_rad_s':1e-6,'accelerations_rad_s2':1e-5})
        self.assertTrue(any(a['positions_rad']!=b['positions_rad'] for a,b in zip(reference,wire)))
        curve=motion.Curve(reference)
        for source,actual in zip(reference[1:-1],wire[1:-1]):
            expected=motion.evaluate(curve,actual['time_s'])
            for field in export.FIELDS:self.assertEqual(actual[field],expected[field])

    def test_stale_sources_and_changed_variant_tcp_or_joint_bounds_are_rejected(self):
        for defect in ['hash','tcp','scene','bounds','qualified']:
            program=copy.deepcopy(self.program)
            if defect=='hash':program['source_files_sha256']['model/robot.json']='0'*64
            elif defect=='tcp':program['robot_description_requirements']['tcp_position_in_parent_m'][2]+=.001
            elif defect=='scene':program['scene']['arm_fixture']['yaw_deg']+=1
            elif defect=='bounds':program['arm']['limits_rad'][0][1]+=.1
            else:program['limits']['qualified']=True
            with self.subTest(defect=defect),self.assertRaises(ValueError):export.configuration(program)

    def test_source_change_during_export_is_not_published_as_current(self):
        before=self.program['source_files_sha256']
        with patch.object(export,'pinned_sources',side_effect=[before,{**before,'changed':'value'}]):
            with self.assertRaisesRegex(ValueError,'changed during ROS export'):export.configuration(self.program)

    def test_cli_reads_a_compiled_program_without_ros_and_rejects_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'compiled.json';target=Path(directory)/'ros.json'
            source.write_text(json.dumps(self.program))
            result=subprocess.run([sys.executable,'-B','scripts/export_cf01_unload_ros2.py','--program',str(source),
                '--output',str(target)],cwd=ROOT,capture_output=True,text=True,timeout=15,check=True)
            self.assertFalse(json.loads(result.stdout)['ros_runtime_verified'])
            self.assertEqual(json.loads(target.read_text())['scenarios'][0]['id'],export.SCENARIO)
        with self.assertRaises(ValueError):json.loads('{"time_s":NaN}',parse_constant=export.reject_constant)


if __name__=='__main__':unittest.main()
