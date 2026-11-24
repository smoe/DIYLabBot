"""Independent export checks reject dishonest summaries and between-node errors.

Small fixtures exercise individual mathematical contracts. They are never
exported as a complete/native-qualified fleet or supplied to the HTML builder.
"""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_checks as checks
import building_fleet_model as model
import building_fleet_comm as comm
import building_fleet_motion as motion
from check_building_fleet_freecad import Trajectory,LiftTimeline


def point(t,x,y=0,yaw=0,vx=0,vy=0):
    return {'time_s':t,'pose_mm_rad':[x,y,yaw],'velocity_mm_rad_s':[vx,vy,0],
            'acceleration_mm_rad_s2':[0,0,0]}


def trajectory(identity,points,mode='driving',**fields):
    lift=LiftTimeline({'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','ports':[]},[])
    e={'start_s':points[0]['time_s'],'end_s':points[-1]['time_s'],'level_id':'EG','mode':mode,
       'attached_cabin':False,'points':points,**fields}
    return Trajectory({'vehicle_id':identity,'episodes':[e]},{'EG':{'z_mm':0}},lift)


def legacy_scan_source(source):
    """Keep recorded short-range stopping cases tied to their original assumptions."""
    source = copy.deepcopy(source)
    source['sensor'].pop('synthetic_scan', None)
    source['sensor']['basis'] = 'referenced_E5_no_override'
    source['motion']['empty_linear_limits']['velocity_mm_s'] = 1000
    return model.validate(source)


class ExportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=model.load()

    def test_actual_between_node_dynamics_ignore_summary_flags(self):
        car=trajectory('BF01',[point(0,0),point(1,1500)])
        with self.assertRaisesRegex(ValueError,'source limit'):
            checks.check_exported_motion([car],self.source,330)

    def test_motion_and_requantized_no_stop_positive(self):
        car=trajectory('BF01',[point(0,0,vx=100),point(2,200,vx=100)])
        dynamic,no_stop=checks.check_exported_motion([car],self.source,330)
        self.assertTrue(dynamic['passed']);self.assertTrue(no_stop['passed'])
        self.assertAlmostEqual(dynamic['maxima']['linear']['velocity'],100)
        self.assertEqual(dynamic['polynomial_intervals'],2)

    def test_non_grid_times_and_invented_holds_rejected(self):
        car=trajectory('BF01',[point(.0004,0,vx=100),point(1.0004,100,vx=100)])
        with self.assertRaisesRegex(ValueError,'1ms'):checks.check_exported_motion([car],self.source,330)
        car=trajectory('BF01',[point(0,0),point(1,0)],mode='hold',hold_reason='demo_pause',hold_condition='a prettier scene')
        with self.assertRaisesRegex(ValueError,'functional hold'):checks.check_exported_motion([car],self.source,330)

    def test_resource_history_exclusivity_and_terminal_release(self):
        rows=[{'vehicle_id':'BF01','resource':'R','event':'passage_granted','time_s':0},
              {'vehicle_id':'BF01','resource':'R','event':'passage_released','time_s':1}]
        self.assertEqual(checks.check_resource_history(rows,2,{'BF01'})[('BF01','R')],[(0,1)])
        with self.assertRaisesRegex(ValueError,'Terminal'):checks.check_resource_history(rows[:1],2,{'BF01'})
        rows.insert(1,{'vehicle_id':'BF02','resource':'R','event':'passage_granted','time_s':.5})
        with self.assertRaisesRegex(ValueError,'Overlapping'):checks.check_resource_history(rows,2,{'BF01','BF02'})

    def test_resource_occupancy_between_knots_requires_live_window(self):
        car=trajectory('BF01',[point(0,-100,vx=200),point(1,100,vx=200)])
        catalog={'regions':[{'level':'EG','resource':'R','polygon':[[-10,-10],[10,-10],[10,10],[-10,10]]}],'room_polygons':[],'room_guard_mm':0}
        with self.assertRaisesRegex(ValueError,'exclusive resource'):checks.check_resource_occupancy([car],catalog,{})
        self.assertTrue(checks.check_resource_occupancy([car],catalog,{('BF01','R'):[(0,1)]})['passed'])
        car.episodes[0]['lift_phase']='alighting'
        with self.assertRaisesRegex(ValueError,'exclusive resource'):
            checks.check_resource_occupancy([car],catalog,{})

    def test_waiting_bay_ungranted_reentry_is_not_hidden_between_nodes(self):
        car=trajectory('BF01',[point(0,-100,vx=200),point(1,100,vx=200)])
        nav=NS(waits={'EG':[[0,0,0]]},waiting_bay_polygons={'EG':[[[-10,-10],[10,-10],[10,10],[-10,10]]]},
               envelope={'length_mm':4,'width_mm':4},radius=math.sqrt(8),reserve=1)
        with self.assertRaisesRegex(ValueError,'without its own live grant'):
            checks.check_waiting_occupancy([car],nav,[],1)
        events=[{'event':'waiting_granted','vehicle_id':'BF01','level':'EG','slot':0,'role':'start','time_s':0},
                {'event':'waiting_released','vehicle_id':'BF01','level':'EG','slot':0,'role':'start','time_s':1}]
        self.assertTrue(checks.check_waiting_occupancy([car],nav,events,1)['passed'])
        events[-1]['time_s']=.5
        with self.assertRaisesRegex(ValueError,'without its own live grant'):checks.check_waiting_occupancy([car],nav,events,1)

    def test_pair_collision_at_midpoint_cannot_use_endpoint_clearance(self):
        first=trajectory('BF01',[point(0,-100,vx=200),point(1,100,vx=200)])
        second=trajectory('BF02',[point(0,100,vx=-200),point(1,-100,vx=-200)])
        nav=NS(envelope={'length_mm':4,'width_mm':4,'height_mm':4},reserve=1,radius=math.sqrt(8))
        with self.assertRaisesRegex(ValueError,'collide'):checks.check_pair_clearance([first,second],nav,1)

    def test_actual_moving_room_witness_and_received_event_required(self):
        car=trajectory('BF01',[point(0,0,vx=100),point(1,100,vx=100)])
        source={'missions':{'targets':[{'level':'EG','area':'A','minimum_visits':1,'basis':'plan_label'}]}}
        nav=NS(polygons={'EG':{'A':[[20,-10],[80,-10],[80,10],[20,10]]}})
        event={'seq':1,'vehicle_id':'BF01','sent_s':.5,'received_s':.6,'delivered_late':False,'kind':'event',
               'payload':{'event':'inspection_completed','details':{'level':'EG','area':'A','mission_id':'M'}}}
        p={'received_messages':[event],'inspection_witnesses':[{'vehicle_id':'BF01','level':'EG','area':'A','time_s':.5,'mission_id':'M'}]}
        self.assertEqual(checks.check_coverage(p,[car],nav,source)[0]['visits'],1)
        event['payload']['details']['mission_id']='forged'
        with self.assertRaisesRegex(ValueError,'exact mission-bound'):checks.check_coverage(p,[car],nav,source)
        event['payload']['details']['mission_id']='M'
        p['received_messages']=[]
        with self.assertRaisesRegex(ValueError,'received completion'):checks.check_coverage(p,[car],nav,source)
        p['received_messages']=[event];p['inspection_witnesses'][0]['time_s']=.1
        with self.assertRaisesRegex(ValueError,'outside'):checks.check_coverage(p,[car],nav,source)

    def test_canonical_geometry_callback_and_full_episode_coverage_required(self):
        car=trajectory('BF01',[point(0,0,vx=100),point(1,100,vx=100)])
        with self.assertRaisesRegex(ValueError,'callback required'):
            checks._geometry_result(None,{},self.source,None,[car],car.lift)
        claim=lambda *args:{name:{'passed':True,'covered_episodes':[]}for name in('support','collision','lift')}
        with self.assertRaisesRegex(ValueError,'every actual exported episode'):
            checks._geometry_result(claim,{},self.source,None,[car],car.lift)

    def test_source_closed_door_travel_required(self):
        door={'id':'D','mechanism':'lift_door','states':{'closed':0,'open':100},'duration_s':.65}
        port={'id':'P','active':True,'level_id':'EG','z_mm':0,'door_object_ids':['D']}
        upstairs={'id':'Q','active':True,'level_id':'OG3','z_mm':12000,'door_object_ids':['D']}
        manifest={'objects':[door],'elevator':{'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','ports':[port,upstairs],'speed_mm_s':1200}}
        schedule=[{'kind':'travel','start_s':0,'end_s':18.75,'from_z_mm':0,'to_z_mm':12000,'to_level':'OG3'}]
        lift=checks.timeline_from_manifest(manifest,schedule)
        with self.assertRaisesRegex(ValueError,'open door'):checks.check_lift_schedule(schedule,manifest,lift)

    def test_current_pin_closure_includes_checker_floor_and_depot(self):
        pins=checks.source_pins(self.source)
        for name in('building_fleet_checks.py','building_fleet_support.py','building_fleet_floor.py','building_fleet_depot.py'):
            self.assertEqual(pins['scripts/'+name],model.digest(model.ROOT/'scripts'/name))

    def test_exact_final_home_and_rest_required(self):
        car=trajectory('BF01',[point(0,0),point(2,0)],mode='hold',hold_reason='home',hold_condition='observed_final_home')
        home={'level':'EG','area':'A','pose_mm_rad':[0,0,0]};nav=NS(homes={'BF01':home})
        p={'duration_s':2,'homes':nav.homes}
        self.assertTrue(checks.check_homes([car],nav,p)['passed'])
        bad=copy.deepcopy(p);bad['homes']['BF01']['pose_mm_rad'][0]=.1
        with self.assertRaisesRegex(ValueError,'layout'):checks.check_homes([car],nav,bad)

    def test_received_radio_and_original_capture_pose_recomputed(self):
        car=trajectory('BF01',[point(0,0),point(4,0)],mode='hold',hold_reason='home',hold_condition='observed_final_home')
        cfg=self.source;channel=comm.Channel(cfg['communication']['latency_s'],cfg['missions']['seed'],max(cfg['communication']['latency_s']))
        records={}
        for i in range(31):
            at=round(i*.1,3)
            if at==.3:channel.emit('BF01','event',{'event':'obstacle_detected','details':{'anonymous_return_count':0}},at)
            if at==.4:channel.set_connected('BF01',False,at)
            if at==1.4:channel.set_connected('BF01',True,at)
            if i%10==0:channel.emit('BF01','heartbeat',{'pose_mm':[0,0,0],'level':'EG','area':'A','mode':'home','speed_mm_s':0},at)
            if i%5==0 and i:
                ref='BF01-camera-'+str(i);captured=round(at-.1,3)
                records[ref]={'captured_s':captured,'pose_xyz_mm':[0,0,0],'yaw_rad':0,'level_id':'EG'}
                channel.emit('BF01','perception',{'captured_s':captured,'pose_mm':[0,0,0],'level':'EG','scan':{'return_count':0,'nearest_mm':None,'bearing_rad':None},'camera_ref':ref},at)
        messages=channel.deliver(4);p={'duration_s':4,'received_messages':messages,'camera_captures':records}
        nav=NS(polygons={'EG':{'A':[[-10,-10],[10,-10],[10,10],[-10,10]]}})
        report=checks.check_telemetry(p,[car],cfg,nav);self.assertTrue(report['passed']);self.assertGreater(report['late_messages'],0)
        p['camera_captures'][next(iter(records))]['pose_xyz_mm'][0]=1
        with self.assertRaisesRegex(ValueError,'original own localization'):checks.check_telemetry(p,[car],cfg,nav)


    def test_operating_lanes_use_source_perception_gap_instead_of_only_static_reserve(self):
        nav=NS(reserve=85,navigation_margin_mm=1,cabin_interior_mm={'min':[0,0,0],'max':[2000,1600,2500]},
               envelope={'length_mm':512,'width_mm':412})
        lanes,gap=checks.operating_cabin_lanes(nav,self.source)
        sensor=model.resolved_sensor(self.source, for_layout=True)
        expected=max(nav.reserve,sensor['clearance_mm']+sensor['range_error_mm']+
            sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))+
            self.source['geometry']['localization_tolerance_mm'])+nav.navigation_margin_mm
        self.assertEqual(gap,expected);self.assertEqual(len(lanes),2)
        self.assertAlmostEqual(lanes[1]['pose_mm'][1]-lanes[0]['pose_mm'][1],412+gap)
        self.assertGreater(gap,nav.reserve)

    def test_actual_source_room_zone_ignores_forged_fast_pathcap(self):
        polygon=[[-100,-100],[100,-100],[100,100],[-100,100]]
        nav=NS(topological={'EG':{'plan':{'areas':[{'id':'A','kind':'room'}]},'excluded_areas':[]}},
            polygons={'EG':{'A':polygon}},cabin_interior_mm={'min':[1000,1000,0],'max':[2000,2000,2500]},
            portals={'EG':[]},radius=2,reserve=1,navigation_margin_mm=0,
            mesh=NS(manifest={'objects':[],'elevator':{'ports':[],'cabin_bounds_mm':{'min':[1000,1000,0],'max':[2000,2000,2500]}}}))
        fast=trajectory('BF01',[point(0,-80,vx=400),point(.4,80,vx=400)])
        with self.assertRaisesRegex(ValueError,'source zone cap'):
            checks.check_source_zones({'room_route_object_ids':[]},[fast],nav,self.source)
        nav.radius=30
        beside=trajectory('BF01',[point(0,125,y=-80,vy=400),point(.4,125,y=80,vy=400)])
        with self.assertRaisesRegex(ValueError,'source zone cap'):
            checks.check_source_zones({'room_route_object_ids':[]},[beside],nav,self.source)
        nav.radius=2
        slow=trajectory('BF01',[point(0,-80,vx=200),point(.8,80,vx=200)])
        self.assertTrue(checks.check_source_zones({'room_route_object_ids':[]},[slow],nav,self.source)['passed'])

    def test_door_roots_bind_actual_crossings_to_freeze_set(self):
        door={'id':'D','mechanism':'room_door','level_id':'EG','opening_id':'O','reference_state':'closed','initial_state':'open'}
        portal={'opening':'O','centre_mm':[0,0],'normal':[1,0],'tangent':[0,1],'opening_width_mm':100}
        nav=NS(topological={'EG':{'plan':{'areas':[]},'excluded_areas':[]}},polygons={'EG':{}},
            cabin_interior_mm={'min':[1000,1000,0],'max':[2000,2000,2500]},portals={'EG':[portal]},
            radius=2,reserve=1,navigation_margin_mm=0,
            mesh=NS(manifest={'objects':[door],'elevator':{'ports':[],'cabin_bounds_mm':{'min':[1000,1000,0],'max':[2000,2000,2500]}}}))
        car=trajectory('BF01',[point(0,-100,vx=200),point(1,100,vx=200)])
        with self.assertRaisesRegex(ValueError,'shared freeze set'):
            checks.check_source_zones({'room_route_object_ids':[]},[car],nav,self.source)
        result=checks.check_source_zones({'room_route_object_ids':['D']},[car],nav,self.source)
        self.assertEqual(result['actual_route_door_ids'],['D'])

    def test_external_report_is_exact_byte_bound_and_fails_without_geometry(self):
        # This isolated negative test mocks unrelated rows; it can only emit a
        # failed report and is never supplied to native/browser qualification.
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports')as directory:
            path=Path(directory)/'negative-only.json'
            p={'duration_s':600,'resource_catalog':{},'resource_events':[],'waiting_events':[],
               'compile_checks':{'everything_passed':True}}
            path.write_text(json.dumps(p)+'\n')
            positive={'passed':True,'scope':'isolated unrelated-row test stub'}
            with ExitStack()as stack:
                stack.enter_context(patch.object(checks,'_context',return_value=([],None)))
                stack.enter_context(patch.object(checks,'check_coverage',return_value=[]))
                stack.enter_context(patch.object(checks,'check_exported_motion',return_value=(copy.deepcopy(positive),copy.deepcopy(positive))))
                for name in('check_homes','check_source_zones','check_resource_occupancy','check_waiting_occupancy','check_depot','check_telemetry','check_lift_program','check_perception'):
                    stack.enter_context(patch.object(checks,name,return_value=copy.deepcopy(positive)))
                result=checks.check_program(path,self.source,NS(radius=1,homes={}),resource_catalog={})
            self.assertEqual(result['format'],checks.FORMAT);self.assertFalse(result['passed'])
            self.assertEqual(result['program']['sha256'],model.digest(path))
            self.assertEqual(set(result['checks']),set(checks.CHECKS))
            self.assertFalse(result['checks']['support']['passed'])
            self.assertFalse(result['checks']['collision']['passed'])
            self.assertFalse(result['checks']['lift']['passed'])
            self.assertNotIn('compile_checks',result)

    def test_raw_own_inputs_recompute_actual_stops_and_reject_forged_gap(self):
        self.assert_raw_own_input_replay()

    def test_capped_raw_own_inputs_recompute_actual_stops_and_reject_forged_gap(self):
        self.assert_raw_own_input_replay([{'point_index':1,'maximum_trim_mm':100}])

    def test_raw_own_inputs_replay_braking_fallback_and_fresh_clear_restart(self):
        self.assert_raw_own_input_replay(obstruction=True)

    def assert_raw_own_input_replay(self,corner_trim_caps=None,obstruction=False):
        from building_fleet_control import Controller
        from building_fleet_runner import EvidenceWriter
        from building_fleet_geometry import vehicle_envelope
        envelope=vehicle_envelope();source=legacy_scan_source(self.source) if obstruction else self.source
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports')as directory:
            writer=EvidenceWriter(Path(directory)/'own.jsonl.gz')
            points=[[0,0],[1500,0],[1500,1500]]if corner_trim_caps is not None else[[0,0],[3000,0]]
            options={'corner_trim_caps':corner_trim_caps}if corner_trim_caps is not None else{}
            car=Controller(motion.Path(points,250,**options),source,zone_caps=[(0,300)])
            path_id=writer.route({'points_mm':points,'corner_trim_mm':250,'reverse':False,**options},[(0,300)])
            scans=[];latest=None
            steps=120 if obstruction else 24
            for step in range(steps):
                at=round(step*.05,3)
                if step%2==0:
                    returns=[[0.,1500.-car.pose()[0]]]if obstruction and at<3.5 else[]
                    scans.append({'captured_s':at,'returns_local_mm':returns})
                    writer.write('scan',vehicle_id='BF01',captured_s=at,pose_mm_rad=car.pose(),level='EG',z_mm=0,returns_local_mm=returns)
                available=[row for row in scans if row['captured_s']+.1<=at+1e-8]
                latest=available[-1]if available else None
                own={'progress_mm':car.y,'velocity_mm_s':car.v,'acceleration_mm_s2':car.a}
                end=round(at+.05,3)
                decision=car.decide(at,latest,step_end_s=end)
                writer.write('decision',vehicle_id='BF01',time_s=at,path_id=path_id,**own,
                    zone_cap_mm_s=car._zone_cap_at(car.y),captured_s=latest['captured_s']if latest else None,
                    own_grant_permits=True,selected_stop_clock=writer.clock(car._checked_brake()),
                    step_end_s=car.step_end_s,continuation_stop_clock=writer.clock(car.continuation_stop_clock),
                    own_conditional_home_map_grant={'status':'none'},decision=decision,mode=car.mode,
                    observation_range_margin_mm=car.perception_audit['minimum_range_margin_mm'])
                car.advance(at,end)
            evidence=writer.close();car_trajectory=trajectory('BF01',car.recorded,leg_id='pure-trace-test')
            nav=NS(config=source,radius=envelope['radius_mm'],envelope=envelope,
                   homes={'BF01':{'level':'EG','area':'R0_004','pose_mm_rad':[0,0,0]}},
                   mesh=NS(manifest={'elevator':{'ports':[]}}))
            catalog={'aliases':{'EG.room.'+area:'R'+area for area in source['depot']['areas']}}
            program={'own_input_evidence':evidence,'received_messages':[],'perception_checks':{'passed':True}}
            with patch('building_fleet_runner.native_scan_geometry',return_value=({'EG':[]},{},{})):
                proof=checks.check_perception(program,[car_trajectory],source,nav,catalog,{})
            self.assertTrue(proof['passed']);self.assertGreater(proof['checked_selected_stops'],0)
            self.assertGreater(proof['checked_continuations'],0)
            self.assertEqual(proof['driving_decision_coverage'],steps)
            if obstruction:
                self.assertTrue(any(p['mode']=='braking'for p in car.recorded))
                self.assertGreaterEqual(sum(e['event']=='resumed'for e in car.events),2)
            trace_path=model.ROOT/evidence['path']
            rows=[json.loads(line)for line in gzip.decompress(trace_path.read_bytes()).decode().splitlines()]
            moving=next(row for row in reversed(rows)if row['kind']=='decision'and row['velocity_mm_s']>0)
            original_continuation=moving.pop('continuation_stop_clock')
            trace_path.write_bytes(gzip.compress(('\n'.join(json.dumps(row,separators=(',',':'))for row in rows)+'\n').encode(),mtime=0))
            evidence['sha256']=model.digest(trace_path)
            with patch('building_fleet_runner.native_scan_geometry',return_value=({'EG':[]},{},{})):
                with self.assertRaisesRegex(ValueError,'declared own state'):
                    checks.check_perception(program,[car_trajectory],source,nav,catalog,{})
            moving['continuation_stop_clock']=original_continuation
            decision=next(row for row in reversed(rows)if row['kind']=='decision')
            decision['decision']['observed_gap_mm']-=1
            trace_path.write_bytes(gzip.compress(('\n'.join(json.dumps(row,separators=(',',':'))for row in rows)+'\n').encode(),mtime=0))
            evidence['sha256']=model.digest(trace_path)
            with patch('building_fleet_runner.native_scan_geometry',return_value=({'EG':[]},{},{})):
                with self.assertRaisesRegex(ValueError,'independent anonymous-input replay'):
                    checks.check_perception(program,[car_trajectory],source,nav,catalog,{})

    def test_own_path_corner_caps_are_reconstructed_and_bound_to_original_bytes(self):
        import hashlib
        data={'points_mm':[[0,0],[1000,0],[1000,1000]],'corner_trim_mm':250,
              'zone_caps':[[0,300]],'reverse':False}
        def record(payload):
            return {'kind':'own_path','id':hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),**payload}
        legacy=record(data);_,old=checks._own_path_bank_row(legacy,{'velocity':1000})
        self.assertEqual(old['path'].pieces,motion.Path(data['points_mm'],250).pieces)
        capped=record({**data,'corner_trim_caps':[{'point_index':1,'maximum_trim_mm':30}]})
        _,new=checks._own_path_bank_row(capped,{'velocity':1000})
        self.assertNotEqual(capped['id'],legacy['id'])
        self.assertEqual(new['path'].pieces,motion.Path(data['points_mm'],250,corner_trim_caps=capped['corner_trim_caps']).pieces)
        self.assertNotEqual(new['path'].pieces,old['path'].pieces)
        changed=copy.deepcopy(capped);changed['corner_trim_caps'][0]['maximum_trim_mm']=31
        with self.assertRaisesRegex(ValueError,'identity'):checks._own_path_bank_row(changed,{'velocity':1000})
        for caps in (None,{},[{'point_index':0,'maximum_trim_mm':30}],
                     [{'point_index':1,'maximum_trim_mm':251}],
                     [{'point_index':1,'maximum_trim_mm':30,'peer_position':[0,0]}]):
            with self.assertRaises(ValueError):checks._own_path_bank_row(record({**data,'corner_trim_caps':caps}),{'velocity':1000})
        with self.assertRaisesRegex(ValueError,'unexpected controller knowledge'):
            checks._own_path_bank_row(record({**data,'peer_positions':[]}),{'velocity':1000})


if __name__=='__main__':unittest.main()
