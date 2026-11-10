"""Actual curve data must satisfy source limits even when copied audits say yes."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cf01_unload_validation as validation

compiler=validation.compiler
motion=validation.motion
FIELDS=motion.FIELDS


def fixture():
    """Small numerical fixture; it is not a native or operational motion proof."""
    definition=compiler.load();scene=compiler.pickup.load();spec=compiler.pickup.cf.load();p=compiler.pickup.cf.parameters(spec)
    arm=compiler.pickup.arm_source(scene);expanded=compiler.pickup.cf.expanded(spec,p)
    duration=12.;q=[math.radians(v) for v in compiler.pickup.robot.home(arm)]
    station=compiler.pickup.cf.pose(spec,p,'closed');names=[j['id'] for j in expanded['joints']]
    samples=sorted(copy.deepcopy(compiler.load_batch()['samples']),key=lambda s:s['rack_slot'])
    for sample in samples:sample.update(tube_body=f"Tube{sample['rotor_slot']:02d}",cap_body=f"ClosedCap{sample['rotor_slot']:02d}")
    program={'format':compiler.FORMAT,'duration_s':duration,'limits':copy.deepcopy(definition['limits']),'scene':scene,
             'arm':{'joint_names':[j['id'].lower() for j in arm['joints']],
                    'limits_rad':[[math.radians(v) for v in j['limits_deg']] for j in arm['joints']],
                    'points':motion.from_positions([0.,duration],[q,q])},
             'station':{'joint_names':names,'units':[j['unit'] for j in expanded['joints']],
                        'points':compiler._generic(motion.from_positions([0.,duration],[[station[n] for n in names]]*2))},
             'jaw':{'joint_names':['jaw_gap'],'units':['mm'],
                    'points':compiler._generic(motion.from_positions([0.,duration],[[scene['gripper']['open_gap_mm']]]*2))},
             'samples':samples,'selected_samples':definition['selected_samples'],
             'segment_audits':[{'passed':True,'claimed_velocity_rad_s':.1}]}
    set_transfers(program,[(1.,2.),(4.,5.),(7.,8.)])
    return program


def set_transfers(program,intervals):
    scene=compiler.pickup.load();spec=compiler.pickup.cf.load();p=compiler.pickup.cf.parameters(spec)
    source=compiler.pickup.cf.expanded(spec,p);kin=compiler.pickup.Kinematics(compiler.pickup.arm_source(scene),scene)
    arm=motion.Curve(program['arm']['points']);station=motion.Curve(compiler._canonical(program['station']['points']))
    program['events']=[];program['transfers']=[]
    for identity,(start,end) in zip(program['selected_samples'],intervals):
        sample=next(s for s in program['samples'] if s['id']==identity)
        values=dict(zip(program['station']['joint_names'],motion.evaluate(station,start)[FIELDS[0]]))
        rotor=compiler.pickup.rigid_from_cf(source,'RotorGroup',values)
        axis=compiler.pickup.cf.pocket(spec,p,1)[1]
        lift=compiler.pickup.placement([v*values['TubeLift'] for v in axis],0.)
        raised=compiler.pickup.robot.multiply(lift,rotor)
        first=kin.tool([math.degrees(v) for v in motion.evaluate(arm,start)[FIELDS[0]]])
        last=kin.tool([math.degrees(v) for v in motion.evaluate(arm,end)[FIELDS[0]]])
        attachment=compiler.pickup.robot.multiply(compiler.pickup.robot.inverse(first),raised)
        program['transfers'].append({'sample_id':identity,'rotor_slot':sample['rotor_slot'],'rack_slot':sample['rack_slot'],
                                    'gripped_s':start,'support_s':end,'attachment_matrix':attachment,
                                    'seated_matrix':compiler.pickup.robot.multiply(last,attachment)})
        program['events'].extend([{'time_s':start,'kind':'owner','sample_id':identity,'owner':'gripper'},
                                  {'time_s':end,'kind':'owner','sample_id':identity,'owner':'rack'}])


def scalar_arm(program,scalar,coefficients,offset=1.):
    initial=program['arm']['points'][0][FIELDS[0]]
    points=[{'time_s':0.,FIELDS[0]:initial[:],FIELDS[1]:[0.]*6,FIELDS[2]:[0.]*6}]
    for point in scalar:
        points.append({'time_s':offset+point['time_s'],
                       FIELDS[0]:[p+c*point[FIELDS[0]][0] for p,c in zip(initial,coefficients)],
                       FIELDS[1]:[c*point[FIELDS[1]][0] for c in coefficients],
                       FIELDS[2]:[c*point[FIELDS[2]][0] for c in coefficients]})
    points.append({**copy.deepcopy(points[-1]),'time_s':program['duration_s']})
    program['arm']['points']=points
    return offset,offset+scalar[-1]['time_s']


class DynamicsValidationTests(unittest.TestCase):
    def test_resting_fake_program_is_rejected_despite_copied_good_audits(self):
        with self.assertRaisesRegex(ValueError,'actual geometric portions'):
            validation.validate_program(fixture())

    def test_twenty_five_radians_per_second_is_rejected_despite_copied_good_audits(self):
        program=fixture();q=program['arm']['points'][0][FIELDS[0]]
        program['arm']['points'].insert(1,{'time_s':1.5,FIELDS[0]:q[:],FIELDS[1]:[25.,0.,0.,0.,0.,0.],FIELDS[2]:[0.]*6})
        with self.assertRaisesRegex(ValueError,'Arm .*limit'):validation.validate_program(program)

    def test_loaded_velocity_between_loaded_and_empty_caps_is_rejected(self):
        program=fixture();scalar=motion.rest_to_rest(2.,.75,.5,2.)
        start,end=scalar_arm(program,scalar,[1.,0.,0.,0.,0.,0.])
        set_transfers(program,[(start,end),(8.,9.),(10.,11.)])
        with self.assertRaisesRegex(ValueError,'Loaded arm .*velocity_rad_s'):validation.validate_program(program)

    def test_sample_rotation_limit_is_checked_even_when_each_joint_is_below_its_cap(self):
        program=fixture();scene=compiler.pickup.load();kin=compiler.pickup.Kinematics(compiler.pickup.arm_source(scene),scene)
        q=program['arm']['points'][0][FIELDS[0]];jets=compiler.sample_motion.KinematicJets(kin)
        def magnitude(sign):
            state={'time_s':0.,FIELDS[0]:q,FIELDS[1]:[.4,0.,0.,0.,0.,sign*.4],FIELDS[2]:[0.]*6,FIELDS[3]:[0.]*6}
            return math.sqrt(sum(v*v for v in jets.evaluate(state)['angular_velocity_rad_s']))
        sign=max([-1.,1.],key=magnitude)
        scalar=motion.rest_to_rest(1.,.4,.2,1.)
        start,end=scalar_arm(program,scalar,[1.,0.,0.,0.,0.,sign])
        set_transfers(program,[(start,end),(8.,9.),(10.,11.)])
        with self.assertRaisesRegex(ValueError,'Carried sample .*motion limit'):validation.validate_program(program)

    def test_station_and_jaw_changes_are_rejected_before_sample_fk(self):
        for channel,coordinate,value in [('station','Lid',100.),('jaw','jaw_gap',300.)]:
            program=fixture();track=program[channel];middle=copy.deepcopy(track['points'][0]);middle['time_s']=6.
            middle['v'][track['joint_names'].index(coordinate)]=value;track['points'].insert(1,middle)
            with self.subTest(channel=channel),self.assertRaisesRegex(ValueError,'Station|Jaw'):validation.validate_program(program)

    def test_declared_limits_channel_units_and_ownership_cannot_override_current_source(self):
        for mutation in ['limits','units','owner','attachment']:
            program=fixture()
            if mutation=='limits':program['limits']['arm_loaded']['velocity_rad_s']=25.
            elif mutation=='units':program['station']['units'][0]='rad'
            elif mutation=='owner':program['events'][0]['time_s']+=.1
            else:program['transfers'][0]['attachment_matrix'][0][3]+=1.
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validation.validate_program(program)

    def test_actual_command_start_requires_rest_brake_workspace_and_correct_lid_mode(self):
        program=fixture();names=program['station']['joint_names'];p=compiler.pickup.cf.parameters(compiler.pickup.cf.load())
        curve=motion.Curve(compiler._canonical(program['station']['points']))
        for mutation in ['velocity','acceleration','brake','workspace','lift','lid','open_index']:
            state={'station':dict.fromkeys(names,0.),'workspace_clear':True,
                   'station_state':{'v':[0.]*len(names),'a':[0.]*len(names)}}
            command='index'
            if mutation in ('velocity','acceleration'):state['station_state']['v' if mutation=='velocity' else 'a'][0]=.1
            elif mutation=='brake':state['station']['BrakeUpper']=.1
            elif mutation=='workspace':state['workspace_clear']=False
            elif mutation=='lift':state['station']['Lift']=.1
            elif mutation=='lid':state['station']['Lid']=105.
            else:command='index_open_lid'
            program['events']=[{'time_s':0.,'kind':'station_command_started','command':command,'sample_id':'Sample01'}]
            with self.subTest(mutation=mutation),patch.object(compiler,'ProgramEvaluator',return_value=lambda t:state),self.assertRaises(ValueError):
                validation._station_commands(program,curve,compiler.load(),p)


class CurrentProgramIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_UNLOAD_DYNAMICS_TESTS')=='1',
                         'Explicit actual-program interval-FK check; build finish performs the same validation')
    def test_source_current_program_artifact_is_revalidated(self):
        path=ROOT/'exports/generated/cf01-unload-demo/program.json'
        if not path.is_file():self.skipTest('Requires a locally compiled unloading program, no CAD rebuild needed')
        result=validation.validate_program(json.loads(path.read_text()))
        self.assertTrue(result['passed']);self.assertGreater(result['duration_s'],0.)
        self.assertEqual(len(result['loaded_transfers']),3)
        self.assertTrue(all(t['actual_geometry']['no_stop']['passed'] for t in result['loaded_transfers']))


class NoStopContractTests(unittest.TestCase):
    class Jets:
        bridges=[];tool=[1.,0.,0.]
    route={'stop_speed_mm_s':.01,'stop_joint_speed_rad_s':1e-6}

    def check(self,points):
        curve=motion.Curve(points)
        return validation.no_stop(curve,curve.times[0],curve.times[-1],self.Jets(),[[0.,0.,0.]],self.route)

    def test_real_polynomial_quiet_bands_are_only_at_the_two_endpoints(self):
        points=motion.from_positions([0.,1.,2.],[[0.],[.5],[1.]])
        result=self.check(points)
        self.assertEqual(len(result['quiet_intervals_s']),2)
        self.assertEqual(result['quiet_intervals_s'][0][0],0.)
        self.assertEqual(result['quiet_intervals_s'][-1][-1],2.)
        self.assertLess(result['quiet_sample_speed_upper_bound_mm_s'],self.route['stop_speed_mm_s'])

    def test_inserted_resting_knot_is_rejected(self):
        points=motion.from_positions([0.,1.,2.],[[0.],[.5],[1.]])
        points[1][FIELDS[1]]=[0.];points[1][FIELDS[2]]=[0.]
        with self.assertRaisesRegex(ValueError,'intermediate stop|resting PVA'):self.check(points)

    def test_interior_stop_without_a_resting_knot_is_rejected(self):
        # In the middle interval q=(u-.5)^3: v=0 at u=.5 although both knot
        # velocities are .75. Endpoint-only or knot-only checks miss that stop.
        points=[{'time_s':t,FIELDS[0]:[p],FIELDS[1]:[v],FIELDS[2]:[a]}
                for t,p,v,a in [(0.,-1.,0.,0.),(1.,-.125,.75,-3.),(2.,.125,.75,3.),(3.,1.,0.,0.)]]
        self.assertTrue(all(point[FIELDS[1]][0]>.1 for point in points[1:-1]))
        self.assertAlmostEqual(motion.evaluate(points,1.5)[FIELDS[1]][0],0.)
        with self.assertRaisesRegex(ValueError,'intermediate stop'):self.check(points)

    def test_duplicate_loaded_positions_are_rejected_even_with_nonzero_knot_velocity(self):
        points=motion.from_positions([0.,1.,2.],[[0.],[.5],[1.]])
        points.insert(2,{**copy.deepcopy(points[1]),'time_s':1.1})
        with self.assertRaisesRegex(ValueError,'repeated joint positions'):self.check(points)

    def test_c2_check_does_not_claim_continuous_jerk(self):
        points=motion.from_positions([0.,1.,3.],[[0.],[.5],[1.]])
        curve=motion.Curve(points);result=validation._c2(curve,'test')
        self.assertTrue(all(error<1e-7 for error in result.values()))
        self.assertNotAlmostEqual(motion.evaluate(curve,1.,side='left')[FIELDS[3]][0],
                                  motion.evaluate(curve,1.,side='right')[FIELDS[3]][0])


class ActualGeometryContractTests(unittest.TestCase):
    def make(self):
        from cf01_unload_path import LoadedPath
        definition=json.loads(compiler.SOURCE.read_text());scene=compiler.pickup.load()
        spec=compiler.pickup.cf.load();p=compiler.pickup.cf.parameters(spec)
        goals=compiler.pickup.targets(scene,spec,p);path=LoadedPath(goals,spec['rotor']['tilt_from_vertical_deg'],definition['routes'])
        progress=motion.scale(motion.rest_to_rest(1.,1.,2.,10.),1.,offset=1.)
        end=progress[-1]['time_s'];arm=motion.Curve([{'time_s':0.,FIELDS[0]:[0.],FIELDS[1]:[0.],FIELDS[2]:[0.]},
                                                 *progress,{**copy.deepcopy(progress[-1]),'time_s':end+1.}])
        def first(predicate):
            left=1.;right=None
            for index in range(1,257):
                t=1.+(end-1.)*index/256
                if predicate(motion.evaluate(progress,t)[FIELDS[0]][0]):right=t;break
                left=t
            self.assertIsNotNone(right)
            for _ in range(64):
                middle=(left+right)/2;u=motion.evaluate(progress,middle)[FIELDS[0]][0]
                if predicate(u):right=middle
                else:left=middle
            return right
        transfer={'gripped_s':1.,'seated_s':end,'support_s':end+.25,'rack_slot':scene['rack']['selected_slot'],
                  'path_progress_points':progress,'axial_end_s':first(lambda u:u>=path.boundaries[0]),
                  'vertical_start_s':first(lambda u:u>=path.boundaries[1]),
                  'removed_confirmed_s':first(lambda u:sum((x-y)*v for x,y,v in zip(path.pose(u)['position'],path.start,path.axis))>=path.removed_distance_mm),
                  'clear_s':first(lambda u:path.pose(u)['position'][0]<=path.clearance_x_mm)}
        transfer['extracted_s']=transfer['removed_confirmed_s']
        class Kin:
            def __init__(self):self.mutation=None
            def tool(self,q):
                u=math.radians(q[0]);pose=path.pose(u)
                tool=compiler.pickup.tool_target(pose['position'],pose['tilt'],scene['gripper'].get('roll_about_tube_deg',0.))
                if self.mutation=='axial' and 0<u<path.boundaries[0]:tool[0][3]+=.2
                if self.mutation=='vertical' and path.boundaries[1]<u<1:tool[0][3]+=.2
                return tool
        return {'scene':scene},transfer,arm,Kin(),definition,spec,p

    def check(self,values):
        program,transfer,arm,kin,definition,spec,p=values
        return validation._actual_transfer(program,transfer,arm,kin,None,[],definition,spec,p,{'passed':True})

    def test_fk_reference_and_event_crossings_are_recomputed_between_knots(self):
        result=self.check(self.make())
        self.assertTrue(result['passed']);self.assertLess(result['maximum_path_deviation_mm'],1e-9)
        self.assertGreater(result['path_checks'],4)

    def test_forged_removed_and_clear_confirmations_are_rejected(self):
        for key in ['removed_confirmed_s','clear_s']:
            values=self.make();values[1][key]+=.001
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'actual FK first crossing'):self.check(values)

    def test_invalid_axial_exit_and_vertical_entry_are_rejected(self):
        for kind in ['axial','vertical']:
            values=self.make();values[3].mutation=kind
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'path tolerance|axial exit|vertical entry'):self.check(values)


if __name__=='__main__':unittest.main()
