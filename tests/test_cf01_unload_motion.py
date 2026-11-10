"""Consecutive unloading preserves geometry, identity, guards and smooth curves."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cf01_unload_motion as unload
import cf01_unload_validation as dynamics


class UnloadDefinitionTests(unittest.TestCase):
    def test_motion_limits_remain_byte_identical_to_the_authorized_baseline(self):
        text=unload.SOURCE.read_text(encoding='utf-8');start=text.index('{',text.index('"limits"'))
        _,length=json.JSONDecoder().raw_decode(text[start:])
        self.assertEqual(hashlib.sha256(text[start:start+length].encode()).hexdigest(),
                         '0ef39bd99199957d4991a895108d895d1d3ff8f8bb5de50890b2460dce47099d')

    def test_requires_existing_source_pins_and_ordered_full_batch_prefix(self):
        original=unload.load()
        for mutation in ['pin','order','short','qualified','lid_speed','index_speed','route']:
            value=copy.deepcopy(original)
            if mutation=='pin':value['sources']['pickup']['source_sha256']='0'*64
            elif mutation=='order':value['selected_samples'][0:2]=reversed(value['selected_samples'][0:2])
            elif mutation=='short':value['selected_samples']=value['selected_samples'][:2]
            elif mutation=='qualified':value['limits']['qualified']=True
            elif mutation=='lid_speed':value['limits']['station_lid']['velocity_deg_s']=60
            elif mutation=='index_speed':value['limits']['station_rotor']['velocity_rpm']=3
            else:value['routes']['empty_return']='unimplemented'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):unload._validate(value)

    def test_source_change_between_load_and_snapshot_is_rejected(self):
        scene=unload.pickup.load();hashes=unload._hashes(scene)
        hashes[str(unload.pickup.SOURCE.relative_to(ROOT))]='0'*64
        with patch.object(unload,'_hashes',return_value=hashes),self.assertRaisesRegex(ValueError,'before unloading motion snapshot'):
            unload.compile()


class UnloadProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('SOLIDCRAFTBOT_UNLOAD_PROGRAM')
        cls.program=json.loads(Path(path).read_text()) if path else unload.compile()
        cls.scene=cls.program['scene']
        if (cls.program['source_files_sha256']!=unload._hashes(unload.pickup.load())
                or cls.program['definition']!=unload.load()):raise ValueError('Explicit cached test program is not source-current')
        cls.evaluate=unload.ProgramEvaluator(cls.program);cls.geometry=unload.SceneEvaluator(cls.scene,cls.program)
        cls.spec=unload.pickup.cf.load();cls.p=unload.pickup.cf.parameters(cls.spec)
        cls.kin=unload.pickup.Kinematics(unload.pickup.arm_source(cls.scene),cls.scene)
        cls.jets=unload.sample_motion.KinematicJets(cls.kin)

    def test_three_returns_are_an_observed_prefix_of_the_full_twelve_sample_run(self):
        evidence=self.program['evidence']
        self.assertTrue(evidence['full_batch_identity_order_passed']);self.assertTrue(evidence['full_batch_order_restored'])
        self.assertIn('Identity and return order only',evidence['scope'])
        self.assertEqual(evidence['selected_return_order'],['Sample01','Sample02','Sample03'])
        self.assertEqual(len(self.program['samples']),12)
        initial=evidence['prefix_records'][0]['inventory']
        self.assertEqual(initial['rotor'],[sample['id'] for sample in self.program['samples']])
        final=self.evaluate(self.program['duration_s'])
        self.assertEqual({name for name,owner in final['owners'].items() if owner=='rack'},set(evidence['selected_return_order']))
        self.assertEqual(sum(owner=='rotor' for owner in final['owners'].values()),9)
        self.assertNotIn('gripper',final['owners'].values())

    def test_original_sample_body_and_rack_identities_are_preserved(self):
        original={sample['id']:sample for sample in unload.load_batch()['samples']}
        self.assertEqual(set(original),{sample['id'] for sample in self.program['samples']})
        for sample in self.program['samples']:
            source=original[sample['id']]
            for key,value in source.items():self.assertEqual(sample[key],value)
            self.assertEqual(sample['tube_body'],f"Tube{source['rotor_slot']:02d}")
            self.assertEqual(sample['cap_body'],f"ClosedCap{source['rotor_slot']:02d}")
            self.assertEqual(sample['rack_location']['place_id'],f"Slot{source['rack_slot']:02d}")

    def test_each_sample_is_indexed_to_the_fixed_lift_and_visibly_elevated(self):
        expected_bottom,_=unload.pickup.cf.pocket(self.spec,self.p,1)
        _,axis=unload.pickup.cf.pocket(self.spec,self.p,1)
        for transfer in self.program['transfers']:
            with self.subTest(sample=transfer['sample_id']):
                docked=self.evaluate(transfer['docked_s']);raised=self.evaluate(transfer['presented_s'])
                bottom,_=unload.pickup.cf.pocket(self.spec,self.p,transfer['rotor_slot'])
                body=f"Tube{transfer['rotor_slot']:02d}"
                a=unload.pickup.robot.transform(self.geometry(docked)[body],bottom)
                b=unload.pickup.robot.transform(self.geometry(raised)[body],bottom)
                self.assertLess(math.dist(a,expected_bottom),1e-7)
                self.assertLess(math.dist([y-x for x,y in zip(a,b)],[v*self.p['lift_travel'] for v in axis]),1e-7)
                self.assertEqual(raised['owners'][transfer['sample_id']],'rotor')
                self.assertGreaterEqual(transfer['gripped_s']-transfer['presented_s'],.6)
                self.assertAlmostEqual(raised['station']['Rotor'],-30*(transfer['rotor_slot']-1))

    def test_first_index_is_closed_and_later_opt_in_indexes_keep_the_lid_open(self):
        commands=[event for event in self.program['events'] if event['kind']=='station_command_confirmed']
        opens=[event for event in commands if event['command']=='open_lid']
        closes=[event for event in commands if event['command']=='close_lid']
        self.assertEqual(len(opens),1);self.assertEqual(len(closes),1)
        self.assertEqual([event['command'] for event in commands if event['command'] in ('index','index_open_lid')],
                         ['index','index_open_lid','index_open_lid'])
        self.assertEqual(self.program['definition']['lid_policy'],'open_between_unloads')
        self.assertGreaterEqual(closes[0]['time_s'],self.program['transfers'][-1]['clear_s'])
        close_start=next(event['time_s'] for event in self.program['events']
                         if event['kind']=='station_command_started' and event['command']=='close_lid')
        station=unload.motion.Curve(unload._canonical(self.program['station']['points']))
        lid=self.program['station']['joint_names'].index('Lid')
        times={opens[0]['time_s'],close_start}
        times.update(point['time_s'] for point in station.points if opens[0]['time_s']<point['time_s']<close_start)
        ordered=sorted(times);times.update((a+b)/2 for a,b in zip(ordered,ordered[1:]))
        for time_s in times:
            state=unload.motion.evaluate(station,time_s)
            self.assertAlmostEqual(state[unload.FIELDS[0]][lid],105.,places=8)
            self.assertAlmostEqual(state[unload.FIELDS[1]][lid],0.,places=8)
            self.assertAlmostEqual(state[unload.FIELDS[2]][lid],0.,places=8)
        for index,transfer in enumerate(self.program['transfers']):
            state=self.evaluate(transfer['index_start_s'])
            self.assertTrue(state['workspace_clear'])
            for coordinate in ['Lift','TubeLift']:
                self.assertAlmostEqual(state['station'][coordinate],0.,places=8)
            self.assertAlmostEqual(state['station']['Lid'],105. if index else 0.,places=8)
            for coordinate in ['LatchLeft','LatchRight']:
                self.assertAlmostEqual(state['station'][coordinate],self.p['latch_travel'] if index else 0.,places=8)
            if index:self.assertGreaterEqual(transfer['index_start_s'],self.program['transfers'][index-1]['released_s'])
            for time_s in [transfer['index_start_s'],(transfer['index_start_s']+transfer['index_end_s'])/2,transfer['index_end_s']]:
                self.assertAlmostEqual(self.evaluate(time_s)['station']['Lid'],105. if index else 0.,places=8)
            removed=[event for event in self.program['events'] if event.get('command')=='confirm_removed' and event['sample_id']==transfer['sample_id']]
            self.assertEqual(len(removed),2)
            self.assertEqual(removed[-1]['time_s'],transfer['removed_confirmed_s'])
            self.assertLess(transfer['gripped_s'],transfer['removed_confirmed_s'])
            self.assertLess(transfer['removed_confirmed_s'],transfer['clear_s'])
            self.assertLess(transfer['clear_s'],transfer['seated_s'])
            self.assertLessEqual(transfer['seated_s'],transfer['support_s'])

    def test_clearance_is_reset_for_each_next_entry_without_stopping_the_loaded_arm(self):
        for transfer in self.program['transfers']:
            self.assertFalse(self.evaluate(transfer['gripped_s'])['workspace_clear'])
            self.assertFalse(self.evaluate(transfer['removed_confirmed_s'])['workspace_clear'])
            clear=self.evaluate(transfer['clear_s'])
            self.assertTrue(clear['workspace_clear'])
            self.assertGreater(math.sqrt(sum(v*v for v in clear['joint_state'][unload.FIELDS[1]])),
                               self.program['definition']['routes']['stop_joint_speed_rad_s'])

    def test_rack_tubes_remain_fixed_and_each_body_pair_has_one_transform(self):
        for transfer in self.program['transfers']:
            point=unload.pickup.cf.pocket(self.spec,self.p,transfer['rotor_slot'])[0]
            group=f"Tube{transfer['rotor_slot']:02d}"
            seated=unload.pickup.robot.transform(self.geometry(self.evaluate(transfer['support_s']))[group],point)
            final=self.geometry(self.evaluate(self.program['duration_s']))
            self.assertLess(math.dist(seated,unload.pickup.robot.transform(final[group],point)),1e-9)
            rack=unload.pickup.rack_geometry(self.scene,self.p)
            target=unload.pickup.robot.transform(rack['frame'],rack['slots'][transfer['rack_slot']-1]['tube_bottom_mm'])
            self.assertLess(math.dist(seated,target),.001)
        self.assertEqual(len({s['tube_body'] for s in self.program['samples']}),12)
        self.assertEqual(len({s['cap_body'] for s in self.program['samples']}),12)

    def test_unselected_tubes_keep_their_radius_and_rotate_with_each_index(self):
        unselected=[sample for sample in self.program['samples'] if sample['id'] not in self.program['selected_samples']]
        for index,transfer in enumerate(self.program['transfers']):
            before=self.geometry(self.evaluate(transfer['index_start_s']))
            after=self.geometry(self.evaluate(transfer['index_end_s']))
            angle=math.radians(-30. if index else 0.);c=math.cos(angle);s=math.sin(angle)
            for sample in unselected:
                point,_=unload.pickup.cf.pocket(self.spec,self.p,sample['rotor_slot'])
                a=unload.pickup.robot.transform(before[sample['tube_body']],point)
                b=unload.pickup.robot.transform(after[sample['tube_body']],point)
                self.assertAlmostEqual(math.hypot(*a[:2]),math.hypot(*b[:2]),places=7)
                expected=[c*a[0]-s*a[1],s*a[0]+c*a[1],a[2]]
                self.assertLess(math.dist(b,expected),1e-7,(sample['id'],index))

    def test_all_tube_envelopes_remain_continuous_at_event_sides(self):
        for time_s in {event['time_s'] for event in self.program['events']}:
            left=self.geometry(self.evaluate(time_s,side='left'))
            right=self.geometry(self.evaluate(time_s,side='right'))
            for sample in self.program['samples']:
                for point in unload.sample_reference_points(self.spec,self.p,sample['rotor_slot']):
                    a=unload.pickup.robot.transform(left[sample['tube_body']],point)
                    b=unload.pickup.robot.transform(right[sample['tube_body']],point)
                    self.assertLess(math.dist(a,b),.005,(time_s,sample['id']))

    def _point_state(self,sample,body,point):
        owner=sample['owners'][body['id']];matrix=self.geometry(sample)[body['tube_body']]
        position=unload.pickup.robot.transform(matrix,point)
        if owner=='rack':return position,[0.]*3,[0.]*3
        if owner=='gripper':
            transfer=next(t for t in self.program['transfers'] if t['sample_id']==body['id'])
            local=unload.pickup.robot.transform(transfer['attachment_matrix'],point)
            state=unload.sample_motion.evaluate(self.kin,sample['joint_state'],points_mm=[local])['points'][0]
            return state['position_mm'],state['velocity_mm_s'],state['acceleration_mm_s2']
        names=self.program['station']['joint_names'];s=sample['station_state']
        r=position[:];r[2]=0.;cross=[-r[1],r[0],0.]
        w=math.radians(s['v'][names.index('Rotor')]);alpha=math.radians(s['a'][names.index('Rotor')])
        velocity=[w*x for x in cross];acceleration=[alpha*x-w*w*y for x,y in zip(cross,r)]
        if sample['active_sample_id']==body['id']:
            axis=unload.pickup.cf.pocket(self.spec,self.p,1)[1];lift=names.index('TubeLift')
            velocity=[x+y*s['v'][lift] for x,y in zip(velocity,axis)]
            acceleration=[x+y*s['a'][lift] for x,y in zip(acceleration,axis)]
        return position,velocity,acceleration

    def test_every_envelope_point_has_one_sided_position_velocity_acceleration_continuity_at_handoffs(self):
        for transfer in self.program['transfers']:
            body=next(sample for sample in self.program['samples'] if sample['id']==transfer['sample_id'])
            for key in ['gripped_s','support_s']:
                left=self.evaluate(transfer[key],side='left');right=self.evaluate(transfer[key],side='right')
                self.assertNotEqual(left['owners'][body['id']],right['owners'][body['id']])
                for point in unload.sample_reference_points(self.spec,self.p,body['rotor_slot']):
                    a=self._point_state(left,body,point);b=self._point_state(right,body,point)
                    for order in range(3):self.assertLess(math.dist(a[order],b[order]),1e-7,(body['id'],key,order))

    def test_shared_polynomial_and_interval_bounds_respect_the_declared_synthetic_limits(self):
        limits=self.program['limits']
        for segment in self.program['segment_audits']:
            caps=limits['arm_loaded' if segment['loaded'] else 'arm_empty']
            for field,key in zip(unload.FIELDS[1:],['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3']):
                self.assertLessEqual(max(segment['joint_bounds'][field]['max_abs']),caps[key]*(1+1e-8))
            self.assertLessEqual(segment['maximum_target_deviation_mm'],.05)
            if segment['loaded']:
                self.assertEqual(segment['sample_bound_scope'],'conservative_numeric_interval')
                self.assertLessEqual(unload._sample_factor(segment['sample_bounds'],limits),1+1e-8)
        for audit in self.program['station_audits']:
            self.assertLessEqual(unload._sample_factor(audit['sample_bounds'],limits),1+1e-8)
        station_bounds=unload.motion.bounds(unload._canonical(self.program['station']['points']))
        names=self.program['station']['joint_names']
        self.assertLessEqual(station_bounds[unload.FIELDS[1]]['max_abs'][names.index('Lid')],10+1e-8)
        self.assertLessEqual(station_bounds[unload.FIELDS[1]]['max_abs'][names.index('Rotor')],12+1e-8)
        self.assertFalse(limits['qualified']);self.assertIsNone(limits['biological_tolerance'])

    def test_tracks_are_c2_and_do_not_teleport_between_samples(self):
        for track,generic in [(self.program['arm'],False),(self.program['station'],True),(self.program['jaw'],True)]:
            points=unload._canonical(track['points']) if generic else track['points'];curve=unload.motion.Curve(points)
            self.assertEqual(points[0]['time_s'],0.);self.assertEqual(points[-1]['time_s'],self.program['duration_s'])
            for point in points[1:-1]:
                left=unload.motion.evaluate(curve,point['time_s'],side='left');right=unload.motion.evaluate(curve,point['time_s'],side='right')
                for field in unload.FIELDS[:3]:
                    self.assertLess(max(abs(a-b) for a,b in zip(left[field],right[field])),1e-9)
        for previous,current in zip(self.program['transfers'],self.program['transfers'][1:]):
            self.assertGreaterEqual(self.evaluate(current['gripped_s'])['time_s'],previous['end_s'])

    def test_loaded_trip_has_one_curve_with_axial_exit_and_vertical_entry(self):
        for sample_id in self.program['selected_samples']:
            segments=[segment for segment in self.program['segment_audits'] if segment['sample_id']==sample_id]
            transit=[segment for segment in segments if segment['loaded']]
            self.assertEqual(len(transit),1)
            self.assertEqual(transit[0]['target'],'loaded_transfer')
            self.assertEqual(transit[0]['path_kind'],'axial_bezier7_vertical')
            self.assertFalse(any(segment['target']=='upright' for segment in segments))
            transfer=next(value for value in self.program['transfers'] if value['sample_id']==sample_id)
            self.assertEqual(transit[0]['start_s'],transfer['gripped_s'])
            self.assertEqual(transit[0]['end_s'],transfer['seated_s'])
            start=self.kin.tool(self.evaluate(transfer['gripped_s'])['joints_deg'])
            axial=self.kin.tool(self.evaluate(transfer['axial_end_s'])['joints_deg'])
            vertical=self.kin.tool(self.evaluate(transfer['vertical_start_s'])['joints_deg'])
            end=self.kin.tool(self.evaluate(transfer['seated_s'])['joints_deg'])
            _,axis=unload.pickup.cf.pocket(self.spec,self.p,1)
            distance=self.program['definition']['routes']['axial_exit_mm']
            self.assertLess(math.dist([axial[i][3]-start[i][3] for i in range(3)],[v*distance for v in axis]),.1)
            self.assertLess(math.hypot(end[0][3]-vertical[0][3],end[1][3]-vertical[1][3]),.1)
            self.assertAlmostEqual(vertical[2][3]-end[2][3],self.program['definition']['routes']['vertical_entry_mm'],delta=.1)

    def test_loaded_motion_has_only_two_quiet_endpoint_bands(self):
        curve=unload.motion.Curve(self.program['arm']['points']);route=self.program['definition']['routes']
        for transfer in self.program['transfers']:
            references=[unload.pickup.robot.transform(transfer['attachment_matrix'],point)
                        for point in unload.sample_reference_points(self.spec,self.p,transfer['rotor_slot'])]
            proof=dynamics.no_stop(curve,transfer['gripped_s'],transfer['seated_s'],self.jets,references,route)
            self.assertIsInstance(proof,dict)
            times={transfer['gripped_s'],transfer['seated_s']}
            knots=[point['time_s'] for point in curve.points if transfer['gripped_s']<=point['time_s']<=transfer['seated_s']]
            for a,b in zip(knots,knots[1:]):times.update(a+(b-a)*i/4 for i in range(5))
            quiet=[]
            for t in sorted(times):
                state=unload.motion.evaluate(curve,t);sample=self.jets.evaluate(state,points_mm=references)
                speed=max(math.sqrt(sum(v*v for v in point['velocity_mm_s'])) for point in sample['points'])
                joint_speed=math.sqrt(sum(v*v for v in state[unload.FIELDS[1]]))
                quiet.append(speed<=route['stop_speed_mm_s'] and joint_speed<=route['stop_joint_speed_rad_s'])
            runs=[i for i,value in enumerate(quiet) if value and (i==0 or not quiet[i-1])]
            self.assertTrue(quiet[0]);self.assertTrue(quiet[-1]);self.assertEqual(len(runs),2)

    def test_an_inserted_rest_island_in_the_loaded_curve_is_rejected(self):
        transfer=self.program['transfers'][0];curve=unload.motion.Curve(self.program['arm']['points'])
        middle=(transfer['gripped_s']+transfer['seated_s'])/2;half_width=(transfer['seated_s']-transfer['gripped_s'])/100
        position=unload.motion.evaluate(curve,middle)[unload.FIELDS[0]]
        points=[copy.deepcopy(point) for point in curve.points if not middle-half_width<=point['time_s']<=middle+half_width]
        points.extend(unload._point(t,position) for t in [middle-half_width,middle+half_width]);points.sort(key=lambda p:p['time_s'])
        references=[unload.pickup.robot.transform(transfer['attachment_matrix'],point)
                    for point in unload.sample_reference_points(self.spec,self.p,transfer['rotor_slot'])]
        with self.assertRaises(ValueError):
            dynamics.no_stop(unload.motion.Curve(points),transfer['gripped_s'],transfer['seated_s'],self.jets,references,
                             self.program['definition']['routes'])


if __name__=='__main__':unittest.main()
