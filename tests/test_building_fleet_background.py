"""Real scalar/PVA worker boundaries, without native CAD startup costs."""
import copy
import json
from pathlib import Path as FilePath
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(FilePath(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model
import building_fleet_background as background
from building_fleet_control import (Controller,PreparedNominal,preparation_digest,F,
    bind_prepared_perception_limit,perception_cache_input_sha256,source_perception_limit,
    bind_prepared_scalar_stops,scalar_stop_cache_input_sha256,_qualified_scalar_stop)
from building_fleet_motion import Path,compile_motion
from building_fleet_runner import WorldRunner
from building_fleet_services import ResourceServices
from building_fleet_starter import RollingController
import tr01_floor_motion as floor


class BackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=model.load();cls.path=Path([[0,0],[6000,0]],100)
        cls.program=compile_motion(cls.path,cls.source,300,zone_caps=[(0,300)])
        cls.car=Controller(cls.path,cls.source,[(0,300)],motion_program=cls.program)
        cls.program['scalar_clock']=copy.deepcopy(cls.car.nominal_clock.points)

    def source_context(self):
        source=copy.deepcopy(self.source);source['depot']['level']='not-test-level'
        checked=[]
        def geometry(action,curve,observed):
            checked.append((action,curve,observed))
            grants = observed.get('own_grants_at_start') or observed['own_grants']
            return {'passed': True, 'native_checks': 1, 'own_waiting_slot': grants.get('waiting_place', {}).get('slot')}
        return {'source':source,'nav':SimpleNamespace(radius=self.car.radius,
                portals={'EG':[]},mesh=SimpleNamespace(manifest={'objects':[]})),
                'catalog':SimpleNamespace(spans=lambda level,path:[]),
                'geometry_checks':geometry,'source_binding':'a'*64},checked

    def request(self,kind='full_route'):
        action={'level':'EG','points_mm':[[0,0],[6000,0]],'corner_trim_mm':100,
            'zone_segments':[],'reverse':False,'markers':[],'terminal':{'kind':'inspection_pass'},'prefetch_level':'EG'}
        return {'format':background.FORMAT,'kind':kind,'request_id':'1','source_binding':'a'*64,
                'vehicle_id':'BF01','action':action,'fence':{'action_sha256':preparation_digest(action)},
                'zone_caps':[(0,300)],'own_pose_mm_rad':[0.,0.,0.],
                'observed':{'vehicle_id':'BF01','time_s':0.,'phase':'test','own_grants':{}},
                'program':self.program,'program_sha256':preparation_digest(self.program),
                'nominal_proof':self.car.nominal_clock_proof}

    def rolling(self):
        short=Path([[0,0],[1000,0]],100)
        program=compile_motion(short,self.source,300,zone_caps=[(0,300)])
        return RollingController(self.path,self.source,[(0,300)],motion_program=program,certified_horizon_mm=1000)

    def test_full_worker_runs_actual_geometry_and_returns_exact_checked_program(self):
        context,checked=self.source_context();request=self.request()
        result=background.prepare_route(request,context)
        self.assertEqual(len(checked),1);self.assertTrue(result['receipt']['geometry']['passed'])
        self.assertEqual(result['program_sha256'],preparation_digest(result['program']))
        self.assertEqual(checked[0][1].times[-1],result['program']['scalar_clock'][-1]['time_s'])
        self.assertEqual(result['fence'],request['fence'])
        self.assertNotIn('peer',repr(request))

    def test_wrong_source_and_mutated_action_fail_before_planning(self):
        context,checked=self.source_context();request=self.request();request['source_binding']='b'*64
        with self.assertRaises(ValueError):background.prepare_route(request,context)
        request=self.request();request['action']['points_mm'][1][0]+=1
        with self.assertRaises(ValueError):background.prepare_route(request,context)
        self.assertFalse(checked)

    def test_worker_checks_post_release_sections_without_access_to_the_old_bay(self):
        context, checked = self.source_context()
        context['nav'].homes = {'BF01': {}}
        full = self.request()
        full['action']['points_mm'] = [[0, 0], [1000, 0], [1000, 1000], [2000, 1000],
                                       [2000, 2000], [3000, 2000], [3000, 3000], [4000, 3000]]
        full['action'].update(terminal={'kind': 'home'}, markers=[{
            'event': 'waiting_place_released', 'details': {'level': 'EG', 'slot': 0}, 'progress_mm': 75.,
        }])
        original = {'waiting_place': {'status': 'granted', 'level': 'EG', 'slot': 0, 'role': 'start'},
                    'lift': {'status': 'none'}}
        full['fence'].update(action_sha256=preparation_digest(full['action']), level='EG', generation=1,
                             own_grants=original)
        full['observed'].update(own_grants=original, own_grants_at_start=original)
        full['rolling_horizon_mm'] = 100.
        first = background.prepare_route(full, context)
        self.assertNotIn('status', first)
        self.assertGreater(first['interval']['end_mm'], 75.)
        effective = {'waiting_place': {'status': 'none'}, 'lift': {'status': 'none'}}
        tail = first['receipt']['released_bay_tail']
        self.assertTrue(tail['geometry']['passed'])
        self.assertIsNone(tail['geometry']['own_waiting_slot'])
        self.assertEqual(tail['own_grants'], effective)
        self.assertEqual([call[2]['own_grants_at_start'] for call in checked], [original, effective])
        self.assertAlmostEqual(checked[1][1].points[0][F[0]][0], 75., places=5)
        scope = {'leg_id': 1, 'marker_mm': 75., 'own_grants': effective}
        section = {**full, 'kind': 'route_interval', 'request_id': '2',
                   'start_knot': first['interval']['end_knot'], 'program_sha256': first['program_sha256'],
                   'post_release': scope}
        checked.clear()
        result = background.prepare_route(section, context)
        self.assertNotIn('status', result)
        self.assertEqual(result['receipt']['post_release'], scope)
        self.assertIsNone(result['receipt']['geometry']['own_waiting_slot'])
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0][2]['own_grants_at_start'], effective)
        self.assertEqual(full['observed']['own_grants_at_start'], original)
        interval = result['interval']
        unscoped = {key: value for key, value in section.items() if key != 'post_release'}
        self.assertEqual(result['receipt']['interval_sha256'], background._interval_binding(section, interval))
        self.assertNotEqual(result['receipt']['interval_sha256'], background._interval_binding(unscoped, interval))

    def test_phase_wall_times_do_not_change_route_or_admission_receipt(self):
        context,_=self.source_context();request=self.request()
        original=background.prepare_route(request,context)
        timings={}
        measured=background.prepare_route(request,context,phase_complete=timings.__setitem__)
        self.assertEqual(measured,original)
        self.assertEqual(set(timings),{'path_setup','perception_limit','compile_motion',
            'nominal_retiming','cartesian_curve','native_geometry','spans_and_door_markers'})
        self.assertTrue(all(value>=0 for value in timings.values()))

    def test_prepared_factory_skips_duplicate_proof_but_rejects_changed_values(self):
        token=PreparedNominal(self.source,self.path,[(0,300)],self.program,self.car.nominal_clock_proof,self.path.length)
        with patch.object(Controller,'_bounded_start_clock',side_effect=AssertionError('duplicate whole proof')):
            car=Controller(self.path,self.source,[(0,300)],motion_program=self.program,prepared_nominal=token)
        self.assertEqual(car.nominal_clock.points,self.car.nominal_clock.points)
        altered=copy.deepcopy(self.program);altered['scalar_clock'][1][F[1]][0]+=.001
        with self.assertRaises(ValueError):Controller(self.path,self.source,[(0,300)],motion_program=altered,prepared_nominal=token)

    def test_pinned_pure_perception_receipt_is_detached_and_exact_input_bound(self):
        result=source_perception_limit(self.source,self.car.radius)
        receipt={'input_sha256':perception_cache_input_sha256(self.source,self.car.radius),'result':copy.deepcopy(result)}
        bind_prepared_perception_limit(self.source,self.car.radius,receipt)
        receipt['result']['velocity_mm_s']=0
        with patch('building_fleet_control.qualified_perception_limit',side_effect=AssertionError('duplicate pure derivation')):
            self.assertEqual(source_perception_limit(self.source,self.car.radius),result)
        wrong=copy.deepcopy(receipt);wrong['input_sha256']='0'*64
        with self.assertRaises(ValueError):bind_prepared_perception_limit(self.source,self.car.radius,wrong)
        changed=copy.deepcopy(self.source);changed['geometry']['localization_tolerance_mm']+=.001
        with self.assertRaises(ValueError):bind_prepared_perception_limit(changed,self.car.radius,receipt)

    def test_pinned_launch_stop_preload_is_exact_and_leaves_dynamic_catalogue_separate(self):
        import math
        inputs=[200.,0.,500.,1000.,700.]
        expected=_qualified_scalar_stop(*inputs)
        row={'inputs':inputs[:],'input_sha256':scalar_stop_cache_input_sha256(*inputs),'result':copy.deepcopy(expected)}
        bind_prepared_scalar_stops([row]);row['result']['distance_mm']=-1
        with patch('building_fleet_control._scalar_stop_catalogue',side_effect=AssertionError('new dynamic derivation')):
            self.assertEqual(_qualified_scalar_stop(*inputs),expected)
            changed=inputs[:];changed[0]=math.nextafter(inputs[0],math.inf)
            with self.assertRaises(AssertionError):_qualified_scalar_stop(*changed)
        row['input_sha256']='0'*64
        with self.assertRaises(ValueError):bind_prepared_scalar_stops([row])
        row={'inputs':inputs,'input_sha256':scalar_stop_cache_input_sha256(*inputs),'result':copy.deepcopy(expected)}
        row['result']['dynamics']['jerk']=1001
        with self.assertRaises(ValueError):bind_prepared_scalar_stops([row])

    def test_starter_moves_then_waits_without_arrival_or_path_identity_change(self):
        car=self.rolling();path=car.path;moved=False
        for k in range(125):
            now=round(k*.05,3);end=round(now+.05,3)
            car.decide(now,{'captured_s':now,'returns_local_mm':[]},step_end_s=end)
            car.advance(now,end);moved|=car.y>1
            self.assertIs(car.path,path);self.assertLessEqual(car.y,1000.00001)
            self.assertNotEqual(car.mode,'arrived')
            if car.continuation_stop_clock is not None:
                bound=floor.motion.bounds(car.continuation_stop_clock)[F[0]]['max'][0]
                self.assertLessEqual(car._fallback['origin_mm']+bound,1000.00001)
        self.assertTrue(moved);self.assertEqual(car.mode,'waiting');self.assertEqual(car.reason,'await_checked_continuation')
        self.assertEqual(car.y,1000.);self.assertEqual(car.goal,6000.)

    def test_depot_prefix_keeps_original_bend_and_requires_full_resource_coverage(self):
        path=Path([[0,0],[1000,0],[1000,1400],[1500,1400]],200,
                  corner_trim_caps=[{'point_index':1,'maximum_trim_mm':90}])
        def spans(level,prefix):
            return [{'resource':'owned','start_progress_mm':0.,'end_progress_mm':prefix.length}]
        catalog=SimpleNamespace(spans=spans)
        short,_=background._owned_departure_bend(path,catalog,'EG','owned')
        self.assertEqual(short.ends,path.ends[:3])
        self.assertEqual(short.samples,[s for s in path.samples if s[0]<short.length])
        for at in (0,path.ends[0],(path.ends[0]+path.ends[1])/2,path.ends[1],short.length-1):
            self.assertEqual(short.evaluate(at)[:3],path.evaluate(at)[:3])
        self.assertEqual(short.pva(short.length,0,0),path.pva(short.length,0,0))
        self.assertIsNone(background._owned_departure_bend(path,catalog,'EG','another'))
        catalog.spans=lambda level,prefix:[{**spans(level,prefix)[0],'end_progress_mm':prefix.length-1}]
        self.assertIsNone(background._owned_departure_bend(path,catalog,'EG','owned'))

    def test_curved_prefix_requires_checked_rejoin_after_an_intermediate_stop(self):
        car=self.rolling()
        car.path=Path([[0,0],[400,0],[400,800],[0,800]],100)
        car.certified_horizon_mm=car.path.ends[2]
        car.y=(car.path.ends[0]+car.path.ends[1])/2
        with patch.object(car,'_bounded_start_clock',side_effect=AssertionError('unproved curved restart')):
            car._goal_plan(5.)
        self.assertIsNone(car.plan)
        self.assertEqual((car.mode,car.reason),('waiting','await_checked_continuation'))

    def test_moving_anchor_leaves_room_to_decelerate_after_a_subdivided_cruise(self):
        car=self.rolling()
        car.mode='driving';car.plan_kind='rolling_prefix';car.v=120.
        car.plan_origin=0.;car.plan_start=1.
        car.plan=floor.motion.Curve([background.local.point(t,120*t,120.,0.) for t in (0.,3.,7.,8.)])
        car.now=2.
        anchor=car.continuation_anchor()
        self.assertEqual(anchor,{'time_s':5.,'progress_mm':480.,'velocity_mm_s':120.,'acceleration_mm_s2':0.})
        car.now=3.
        self.assertEqual(car.continuation_anchor(),anchor)

    def test_early_nominal_cannot_replace_the_brakeable_depot_bend(self):
        car=self.rolling()
        car.path=Path([[0,0],[300,0],[300,600],[0,600]],100)
        car.certified_horizon_mm=car.path.ends[2]
        self.assertIsNone(car.continuation_anchor())
        car.mode='driving';car.plan_kind='rolling_prefix';car.v=100.;car.now=.1
        car.plan_origin=0.;car.plan_start=0.
        car.plan=floor.motion.Curve([background.local.point(t,100*t,100.,0.) for t in (0.,4.,8.)])
        anchor=car.continuation_anchor()
        self.assertGreaterEqual(anchor['progress_mm'],car.path.ends[1])
        car.mode='waiting';car.v=0.;car.y=300.;car.plan=None
        self.assertEqual(car.continuation_anchor()['progress_mm'],car.y)

    def test_wait_before_starter_horizon_preserves_actual_reason(self):
        car=self.rolling()
        for start,end,permitted,reason in (
                (0.,.05,True,'fresh_clear_observation'),
                (.05,.1,False,'resource_wait')):
            scan={'captured_s':start,'returns_local_mm':[]}
            decision=car.decide(start,scan,grant_permits=permitted,step_end_s=end)
            self.assertEqual(decision['reason'],reason)
            car.advance(start,end)
            self.assertEqual((car.y,car.mode,car.reason),(0.,'waiting',reason))
            self.assertEqual(car.recorded[-1]['hold_reason'],reason)

    def test_starter_rejects_stop_outside_certified_horizon(self):
        car=self.rolling();car.y=999.;car.v=100.;car.a=0.
        clock=floor.motion.Curve([background.local.point(0,0,100,0),background.local.point(1,50,0,0)])
        self.assertFalse(car._valid_stop_clock(clock,999.))

    def test_ordinary_controller_cannot_mistake_a_partial_horizon_for_arrival(self):
        short=Path([[0,0],[1000,0]],100)
        program=compile_motion(short,self.source,300,zone_caps=[(0,300)])
        with self.assertRaises(ValueError):
            Controller(self.path,self.source,[(0,300)],motion_program=program,certified_horizon_mm=1000)

    def test_moving_C2_connector_keeps_source_suffix_and_requires_observed_anchor(self):
        context,checked=self.source_context();request=self.request('continuation')
        request['anchor']={'time_s':1.,'progress_mm':100.,'velocity_mm_s':100.,'acceleration_mm_s2':0.}
        request['observed']['time_s']=1.
        result=background.prepare_route(request,context)
        self.assertTrue(result['proof']['passed']);self.assertEqual(len(checked),1)
        clock=result['clock'];self.assertEqual(clock[0][F[1]],[100.]);self.assertEqual(clock[0][F[2]],[0.])
        self.assertEqual(clock[-1][F[0]],[5900.])
        car=self.rolling();car.now=1.;car.y=100.;car.v=100.;car.a=0.
        fallback=object();car._fallback=fallback
        wrong={**result['anchor'],'progress_mm':100.01}
        self.assertFalse(car.commit_continuation(clock,self.program['scalar_clock'],wrong,result['proof']))
        self.assertTrue(car.commit_continuation(clock,self.program['scalar_clock'],result['anchor'],result['proof']))
        self.assertIs(car._fallback,fallback);self.assertFalse(car.awaiting_continuation)
        self.assertEqual(car.certified_horizon_mm,car.goal)

    def test_late_static_rest_connector_rebases_only_identical_rest(self):
        context,_=self.source_context();request=self.request('continuation')
        request['anchor']={'time_s':1.,'progress_mm':1000.,'velocity_mm_s':0.,'acceleration_mm_s2':0.}
        result=background.prepare_route(request,context)
        car=self.rolling();car.now=3.;car.y=1000.;car.v=car.a=0.
        self.assertFalse(car.commit_continuation(result['clock'],self.program['scalar_clock'],result['anchor'],result['proof']))
        self.assertTrue(car.commit_continuation(result['clock'],self.program['scalar_clock'],result['anchor'],result['proof'],allow_static_rest_rebase=True))
        self.assertEqual(car.plan_start,3.)

    def test_original_endpoint_roundoff_keeps_existing_goal_tolerance(self):
        car=self.rolling();car.now=1.;car.y=1000.;car.v=car.a=0.
        context,_=self.source_context();request=self.request('continuation')
        request['anchor']={'time_s':1.,'progress_mm':1000.,'velocity_mm_s':0.,'acceleration_mm_s2':0.}
        result=background.prepare_route(request,context)
        result['clock'][-1][F[0]][0]-=1e-10
        self.assertTrue(car.commit_continuation(result['clock'],self.program['scalar_clock'],result['anchor'],result['proof']))


class FenceTests(unittest.TestCase):
    def engine(self):
        row={'level':'EG','action':{'kind':'drive'},'done':False,'driver':None,'pose_mm_rad':[0.,0.,0.],
             'preparation_generation':1}
        engine=SimpleNamespace(vehicles={'BF01':row},now=0.,own_grants=lambda identity:{'waiting_place':{'status':'none'}},
            resources=SimpleNamespace(own_grants=lambda identity:{'status':'granted','resource':'own-token'}),
            geometry_context=lambda identity,phase:{'vehicle_id':identity,'phase':phase,'time_s':0.})
        return engine

    def test_request_is_detached_idempotent_result_and_generation_fenced(self):
        engine=self.engine();manager=background.BackgroundPreparation(engine,'a'*64)
        request=manager._request('BF01',engine.vehicles['BF01']['action'],[],'full_route')
        drained=manager.drain();drained[0]['action']['kind']='mutated'
        self.assertEqual(manager.jobs['1']['action']['kind'],'drive');self.assertEqual(manager.drain(),[])
        self.assertTrue(manager._current(request));engine.vehicles['BF01']['preparation_generation']=2
        self.assertFalse(manager._current(request))
        result=background._checked_result(request,program={},program_sha256=preparation_digest({}),receipt={'geometry':{'passed':True}})
        answer=manager.accept(result);self.assertFalse(answer['accepted']);self.assertEqual(answer['status'],'stale_own_fence')
        self.assertEqual(manager.accept(result)['status'],'invalid_receipt')

    def test_foreign_worker_or_corrupt_receipt_cannot_install(self):
        engine=self.engine();manager=background.BackgroundPreparation(engine,'a'*64)
        request=manager._request('BF01',engine.vehicles['BF01']['action'],[],'full_route')
        result=background._checked_result(request,program={});result['source_binding']='b'*64
        self.assertEqual(manager.accept(result)['status'],'invalid_receipt')
        self.assertIn('1',manager.jobs)
        result=background._checked_result(request,program={});result['program']['points']=['changed']
        self.assertEqual(manager.accept(result)['status'],'invalid_receipt')

    def test_inner_worker_json_must_keep_float_types_and_signed_zero(self):
        value={'zero':0.0,'negative_zero':-0.0,'integer':0}
        preserved=json.loads(json.dumps(value))
        self.assertEqual(preparation_digest(value),preparation_digest(preserved))
        self.assertNotEqual(preparation_digest(value),preparation_digest({'zero':0,'negative_zero':0,'integer':0}))

    def interval_manager(self, count=1):
        e=self.engine()
        template=e.vehicles['BF01']
        grants={'waiting_place':{'status':'none'},'lift':{'status':'none'}}
        e.own_grants=lambda identity:copy.deepcopy(grants)
        e.geometry_context=lambda identity,phase:{'vehicle_id':identity,'phase':phase,'time_s':e.now,
                                                   'own_grants_at_start':copy.deepcopy(grants)}
        e.source={'depot':{'level':'EG'}}
        e.geometry_checks=[];e.depot_checks=[]
        manager=background.BackgroundPreparation(e,'a'*64)
        program={'scalar_clock':[background.local.point(t,100.*t,100. if t<3 else 0.,0.) for t in range(4)]}
        nominal={'program':program,'program_sha256':preparation_digest(program)}
        for index in range(1,count+1):
            vehicle=f'BF{index:02d}'
            row=copy.deepcopy(template)
            row.update(action={'level':'EG'},action_context=copy.deepcopy(grants),leg_id=index)
            e.vehicles[vehicle]=row
            driver=object.__new__(RollingController)
            driver.goal=300.;driver.certified_horizon_mm=100.;driver.joined_nominal=True
            driver.awaiting_continuation=True;driver.mode='waiting';row['driver']=driver
            full=manager._request(vehicle,row['action'],[],'full_route',rolling_horizon_mm=50.)
            manager.jobs.pop(full['request_id'])
            manager.full[vehicle]=(full,nominal)
            manager.intervals[vehicle]={'end_knot':1,'horizon_mm':100.}
        manager.drain()
        return manager

    def interval_receipt(self, request):
        first=request['start_knot']
        interval={'start_knot':first,'end_knot':first+1,'start_mm':100.*first,'end_mm':100.*(first+1),
                  'program_sha256':request['program_sha256']}
        receipt={'interval_sha256':background._interval_binding(request,interval),
                 'geometry':{'passed':True},'fixed_home':{'passed':True}}
        if 'post_release' in request:
            receipt['post_release'] = copy.deepcopy(request['post_release'])
            receipt['geometry']['own_waiting_slot'] = None
        else:
            for mark in request['action'].get('markers', []):
                if (mark['event'] == 'waiting_place_released'
                        and interval['start_mm'] < mark['progress_mm'] <= interval['end_mm']):
                    original = request['observed']['own_grants_at_start']
                    receipt['geometry']['own_waiting_slot'] = original['waiting_place']['slot']
                    receipt['released_bay_tail'] = {
                        'geometry': {'passed': True, 'own_waiting_slot': None},
                        'fixed_home': {'passed': True},
                        'own_grants': {**original, 'waiting_place': {'status': 'none'}},
                    }
        return interval,receipt

    def interval_case(self):
        manager=self.interval_manager()
        full,nominal=manager.full['BF01']
        request=manager._followup(full,'route_interval',start_knot=1,
                                  program_sha256=nominal['program_sha256'],brake_headroom_mm=50.)
        manager.drain()
        return manager,request,*self.interval_receipt(request),manager.engine.vehicles['BF01']['driver']

    def return_bay_manager(self, marker_mm=75.):
        manager = self.interval_manager(count=6)
        engine = manager.engine
        engine.resources = ResourceServices({}, {'EG': [[0., 0., 0.], [0., 40., 0.]]})
        engine.resources.request_waiting_place('BF01', 'EG')
        for identity, row in engine.vehicles.items():
            row['aboard'] = False
            if identity != 'BF01':
                row['driver'] = None
                manager.full.pop(identity)
                manager.intervals.pop(identity)
        engine.lift = SimpleNamespace(own_grant=lambda identity: {'status': 'none'})
        engine.own_grants = lambda identity: WorldRunner.own_grants(engine, identity)
        engine.geometry_context = lambda identity, phase: {
            'vehicle_id': identity, 'phase': phase, 'time_s': engine.now,
            'own_grants': engine.own_grants(identity),
            'own_grants_at_start': copy.deepcopy(engine.vehicles[identity]['action_context']),
        }
        engine.nav = SimpleNamespace(reserve=5., waiting_bay_polygons={'EG': [
            [[-15., -15.], [15., -15.], [15., 15.], [-15., 15.]],
            [[-15., 25.], [15., 25.], [15., 55.], [-15., 55.]],
        ]})
        engine.truth = lambda: {
            identity: {'pose_mm': row['pose_mm_rad'], 'footprint_mm': [20., 20.]}
            for identity, row in engine.vehicles.items()
        }
        engine.planner = SimpleNamespace(on_event=lambda *args: None)
        engine.event = lambda *args: None
        row = engine.vehicles['BF01']
        marker = {'event': 'waiting_place_released', 'details': {'level': 'EG', 'slot': 0},
                  'progress_mm': marker_mm}
        row.update(action_context=engine.own_grants('BF01'), markers=[copy.deepcopy(marker)],
                   action={'kind': 'drive', 'level': 'EG', 'terminal': {'kind': 'home'}, 'markers': [marker]},
                   pose_mm_rad=[0., 0., 0.])
        row['driver'].y = 0.
        _, nominal = manager.full['BF01']
        full = manager._request('BF01', row['action'], [], 'full_route', rolling_horizon_mm=100.)
        manager.jobs.pop(full['request_id'])
        manager.full['BF01'] = (full, nominal)
        manager.drain()
        return manager

    def observed_return_bay_release(self, manager, position_mm=80., progress_mm=80., time_s=1.):
        engine = manager.engine
        row = engine.vehicles['BF01']
        engine.now = time_s
        row['driver'].y = progress_mm
        row['pose_mm_rad'][0] = position_mm
        WorldRunner.process_markers(engine, 'BF01')

    def return_bay_interval(self, manager):
        full, nominal = manager.full['BF01']
        request = manager._followup(full, 'route_interval', start_knot=1,
                                    program_sha256=nominal['program_sha256'], brake_headroom_mm=50.)
        self.assertEqual(manager.drain(), [request])
        interval, receipt = self.interval_receipt(request)
        return request, background._checked_result(request, interval=interval, receipt=receipt)

    def test_waiting_bay_release_requires_observed_footprint_clearance(self):
        manager = self.return_bay_manager()
        with self.assertRaisesRegex(RuntimeError, 'physical footprint has not cleared'):
            self.observed_return_bay_release(manager, position_mm=0.)
        self.assertEqual(manager.engine.own_grants('BF01')['waiting_place']['status'], 'granted')
        self.assertEqual(manager.engine.resources.waiting_events, [])

    def test_unobserved_booking_release_still_rejects_prepared_route_interval(self):
        manager = self.return_bay_manager()
        request, result = self.return_bay_interval(manager)
        manager.engine.resources.release_waiting_place('BF01', 1.)
        self.assertEqual(manager.accept(result)['status'], 'stale_geometry_context')
        self.assertNotIn(request['request_id'], manager.jobs)
        self.assertEqual(manager.snapshot()['failures'], {'BF01': 'stale_geometry_context'})
        self.assertEqual(manager.intervals['BF01']['horizon_mm'], 100.)

    def test_waiting_bay_release_does_not_relax_full_route_fence(self):
        manager = self.return_bay_manager()
        original, _ = manager.full['BF01']
        manager.jobs[original['request_id']] = original
        self.observed_return_bay_release(manager)
        result = background._checked_result(original)
        self.assertEqual(manager.accept(result)['status'], 'stale_geometry_context')
        self.assertEqual(manager.intervals['BF01']['horizon_mm'], 100.)

    def test_post_release_intervals_accept_before_and_after_submission(self):
        for release_before_submission in (False, True):
            with self.subTest(release_before_submission=release_before_submission):
                manager = self.return_bay_manager()
                original, _ = manager.full['BF01']
                row = manager.engine.vehicles['BF01']
                if release_before_submission:
                    self.observed_return_bay_release(manager)
                request, result = self.return_bay_interval(manager)
                self.assertEqual(request['fence'], original['fence'])
                self.assertEqual(request['observed']['own_grants_at_start'], original['fence']['own_grants'])
                self.assertEqual(result['receipt']['post_release'], {
                    'leg_id': row['leg_id'], 'marker_mm': 75.,
                    'own_grants': {'waiting_place': {'status': 'none'}, 'lift': {'status': 'none'}},
                })
                if not release_before_submission:
                    self.observed_return_bay_release(manager)
                self.assertEqual(row['waiting_bay_release'], {
                    'leg_id': row['leg_id'], 'generation': row['preparation_generation'], 'marker_mm': 75.,
                    'grant': original['fence']['own_grants']['waiting_place'], 'time_s': 1., 'progress_mm': 80.,
                })
                self.assertTrue(manager.accept(result)['accepted'])
                self.assertEqual(row['driver'].certified_horizon_mm, 200.)
                self.assertEqual(manager.snapshot()['failures'], {})
                self.assertEqual(manager.snapshot()['stale'], 0)
                self.assertFalse(manager.accept(result)['accepted'])

    def test_release_does_not_allow_scope_to_reach_behind_the_marker(self):
        manager = self.return_bay_manager(marker_mm=125.)
        driver = manager.engine.vehicles['BF01']['driver']
        driver.joined_nominal = False
        driver.certified_horizon_mm = 150.
        request, result = self.return_bay_interval(manager)
        self.assertNotIn('post_release', request)
        self.observed_return_bay_release(manager, position_mm=130., progress_mm=130.)
        self.assertEqual(manager.accept(result)['status'], 'stale_geometry_context')
        self.assertEqual(manager.intervals['BF01']['horizon_mm'], 100.)

    def test_post_release_proof_rejects_unrelated_grant_and_leg_changes(self):
        for change in ('lift', 'new_bay', 'same_bay', 'different_leg', 'old_generation', 'wrong_event_grant'):
            with self.subTest(change=change):
                manager = self.return_bay_manager()
                request, result = self.return_bay_interval(manager)
                self.assertIn('post_release', request)
                self.observed_return_bay_release(manager)
                engine = manager.engine
                row = engine.vehicles['BF01']
                if change == 'lift':
                    engine.lift.own_grant = lambda identity: {'status': 'assigned', 'slot': 0}
                elif change in ('new_bay', 'same_bay'):
                    if change == 'new_bay':
                        engine.resources.request_waiting_place('BF02', 'EG')
                    engine.resources.request_waiting_place('BF01', 'EG')
                elif change == 'different_leg':
                    row['leg_id'] += 1
                elif change == 'old_generation':
                    row['waiting_bay_release']['generation'] -= 1
                else:
                    row['waiting_bay_release']['grant']['slot'] += 1
                self.assertEqual(manager.accept(result)['status'], 'stale_geometry_context')
                self.assertEqual(manager.snapshot()['failures'], {'BF01': 'stale_geometry_context'})
                self.assertEqual(row['driver'].certified_horizon_mm, 100.)

    def test_post_release_interval_needs_effective_grants_in_the_proof(self):
        for change in ('missing', 'old_grant', 'old_geometry_slot', 'missing_geometry_slot'):
            with self.subTest(change=change):
                manager = self.return_bay_manager()
                request, valid = self.return_bay_interval(manager)
                self.observed_return_bay_release(manager)
                receipt = copy.deepcopy(valid['receipt'])
                if change == 'missing':
                    receipt.pop('post_release')
                elif change == 'old_grant':
                    receipt['post_release']['own_grants'] = request['fence']['own_grants']
                elif change == 'old_geometry_slot':
                    receipt['geometry']['own_waiting_slot'] = 0
                else:
                    receipt['geometry'].pop('own_waiting_slot')
                result = background._checked_result(request, interval=valid['interval'], receipt=receipt)
                self.assertEqual(manager.accept(result)['status'], 'invalid_interval_proof')
                self.assertEqual(manager.intervals['BF01']['horizon_mm'], 100.)

    def test_crossing_interval_requires_released_bay_tail(self):
        for change in (None, 'missing', 'old_geometry_slot', 'old_grant'):
            with self.subTest(change=change):
                manager = self.return_bay_manager(marker_mm=125.)
                request, valid = self.return_bay_interval(manager)
                self.assertNotIn('post_release', request)
                receipt = copy.deepcopy(valid['receipt'])
                if change == 'missing':
                    receipt.pop('released_bay_tail')
                elif change == 'old_geometry_slot':
                    receipt['released_bay_tail']['geometry']['own_waiting_slot'] = 0
                elif change == 'old_grant':
                    receipt['released_bay_tail']['own_grants'] = request['fence']['own_grants']
                result = background._checked_result(request, interval=valid['interval'], receipt=receipt)
                answer = manager.accept(result)
                self.assertEqual(answer['status'], 'ready' if change is None else 'invalid_interval_proof')
                self.assertEqual(manager.intervals['BF01']['horizon_mm'], 200. if change is None else 100.)

    def connector_receipt(self, manager, vehicle):
        driver=manager.engine.vehicles[vehicle]['driver']
        driver.joined_nominal=False;driver.certified_horizon_mm=50.
        driver.mode='driving';driver.y=0.;driver._fallback=None
        driver._rest_connector=None;driver.plan=None;driver.profile_checks=[]
        anchor={'time_s':1.,'progress_mm':50.,'velocity_mm_s':100.,'acceleration_mm_s2':0.}
        full,nominal=manager.full[vehicle]
        request=manager._followup(full,'continuation',anchor=anchor,horizon_mm=100.,
                                  program_sha256=nominal['program_sha256'])
        manager.continuations[vehicle]={'request_id':request['request_id']}
        proof={'passed':True,'anchor':anchor,'join_progress_mm':100.,'suffix_program_sha256':request['program_sha256'],
               'receipt':{'geometry':{'passed':True},'fixed_home':{'passed':True}}}
        if 'post_release' in request:
            proof['receipt']['post_release'] = copy.deepcopy(request['post_release'])
            proof['receipt']['geometry']['own_waiting_slot'] = None
        clock=[background.local.point(0.,0.,100.,0.)]
        clock.extend(background.local.point(p['time_s']-.5,p[F[0]][0]-50.,p[F[1]][0],p[F[2]][0])
                     for p in nominal['program']['scalar_clock'][1:])
        return background._checked_result(request,anchor=anchor,clock=clock,proof=proof)

    def test_post_release_connector_stays_valid_when_grant_changes_before_commit(self):
        for release_before_accept in (False, True):
            with self.subTest(release_before_accept=release_before_accept):
                manager = self.return_bay_manager(marker_mm=40.)
                driver = manager.engine.vehicles['BF01']['driver']
                result = self.connector_receipt(manager, 'BF01')
                manager.drain()
                self.assertEqual(result['proof']['receipt']['post_release']['marker_mm'], 40.)
                if release_before_accept:
                    self.observed_return_bay_release(manager, position_mm=45., progress_mm=45., time_s=.5)
                self.assertTrue(manager.accept(result)['accepted'])
                if not release_before_accept:
                    self.observed_return_bay_release(manager, position_mm=45., progress_mm=45., time_s=.5)
                manager.engine.now = driver.now = 1.
                driver.y, driver.v, driver.a = 50., 100., 0.
                manager.before_tick()
                self.assertTrue(driver.joined_nominal)
                self.assertEqual(driver.certified_horizon_mm, 100.)
                self.assertEqual(manager.statistics['continuations'], 1)
                self.assertEqual(manager.statistics['stale'], 0)

    def test_intervals_extend_before_anchor_and_commit_uses_latest_contiguous_horizon(self):
        manager=self.interval_manager()
        driver=manager.engine.vehicles['BF01']['driver']
        result=self.connector_receipt(manager,'BF01')
        manager.drain()
        manager.engine.now=.1
        self.assertTrue(manager.accept(result)['accepted'])
        for at,expected_end in ((.25,200.),(.5,300.)):
            manager.engine.now=at;manager.before_tick()
            request,=manager.drain()
            self.assertEqual(request['kind'],'route_interval')
            self.assertEqual(manager.continuations['BF01'],result)
            interval,receipt=self.interval_receipt(request)
            section=background._checked_result(request,interval=interval,receipt=receipt)
            self.assertTrue(manager.accept(section)['accepted'])
            self.assertEqual(manager.intervals['BF01']['horizon_mm'],expected_end)
            self.assertEqual(driver.certified_horizon_mm,50.)
        manager.engine.now=driver.now=1.
        driver.y,driver.v,driver.a=50.,100.,0.
        manager.before_tick()
        self.assertTrue(driver.joined_nominal)
        self.assertEqual(driver.certified_horizon_mm,300.)
        self.assertEqual(manager.statistics['continuations'],1)
        self.assertFalse(manager.accept(section)['accepted'])
        self.assertEqual(len(manager.engine.geometry_checks),2)

    def test_connector_cannot_claim_a_join_beyond_its_original_request(self):
        manager=self.interval_manager()
        result=self.connector_receipt(manager,'BF01')
        manager.drain()
        request=manager.jobs[result['request_id']]
        proof=dict(result['proof'],join_progress_mm=200.)
        wrong=background._checked_result(request,anchor=result['anchor'],clock=result['clock'],proof=proof)
        self.assertEqual(manager.accept(wrong)['status'],'invalid_connector')
        self.assertNotIn('BF01',manager.continuations)
        self.assertEqual(manager.engine.vehicles['BF01']['driver'].certified_horizon_mm,50.)

    def test_waiting_connector_never_uses_rejected_foreign_or_gapped_interval(self):
        for change in ('rejected','foreign','gap','new_generation'):
            with self.subTest(change=change):
                manager=self.interval_manager()
                result=self.connector_receipt(manager,'BF01')
                manager.drain();manager.engine.now=.1
                self.assertTrue(manager.accept(result)['accepted'])
                manager.before_tick()
                request,=manager.drain()
                interval,receipt=self.interval_receipt(request)
                valid=background._checked_result(request,interval=interval,receipt=receipt)
                manager.engine.now=.5
                if change=='rejected':
                    wrong=background._checked_result(request,status='interval_rejected',reason='native_obstruction')
                elif change=='foreign':
                    wrong={**valid,'source_binding':'b'*64}
                elif change=='gap':
                    interval['start_knot']+=1
                    receipt['interval_sha256']=background._interval_binding(request,interval)
                    wrong=background._checked_result(request,interval=interval,receipt=receipt)
                else:
                    manager.engine.vehicles['BF01']['preparation_generation']+=1
                    wrong=valid
                self.assertFalse(manager.accept(wrong)['accepted'])
                self.assertFalse(manager.accept(valid)['accepted'])
                if change!='new_generation':
                    self.assertNotIn('BF01',manager.continuations)
                    self.assertIn('BF01',manager.snapshot()['failures'])
                    if change=='rejected':self.assertEqual(manager.failures['BF01'],'native_obstruction')
                    manager.engine.now=1.;manager.before_tick()
                    self.assertEqual(manager.drain(),[])
                self.assertEqual(manager.intervals['BF01']['end_knot'],1)
                self.assertEqual(manager.engine.vehicles['BF01']['driver'].certified_horizon_mm,50.)

    def test_twenty_waiting_anchors_have_at_most_one_outstanding_job_each(self):
        manager=self.interval_manager(count=20)
        responses=[self.connector_receipt(manager,vid) for vid in manager.engine.vehicles]
        self.assertEqual(len(manager.drain()),20)
        manager.engine.now=.05;manager.before_tick()
        self.assertEqual(manager.drain(),[])
        manager.engine.now=.1
        for response in responses:self.assertTrue(manager.accept(response)['accepted'])
        manager.engine.now=.2;manager.before_tick()
        jobs=manager.drain()
        self.assertEqual({j['kind'] for j in jobs},{'route_interval'})
        self.assertEqual({j['vehicle_id'] for j in jobs},set(manager.engine.vehicles))
        self.assertEqual(len(jobs),20)
        manager.engine.now=.3;manager.before_tick()
        self.assertEqual(manager.drain(),[])
        self.assertEqual(len(manager.jobs),20)

    def test_passage_grant_change_accepts_current_section_only_once(self):
        manager,request,interval,receipt,driver=self.interval_case()
        manager.engine.resources.own_grants=lambda identity:{'status':'waiting','resource':'another'}
        result=background._checked_result(request,interval=interval,receipt=receipt)
        self.assertTrue(manager.accept(result)['accepted'])
        self.assertEqual(driver.certified_horizon_mm,200.)
        self.assertEqual(len(manager.engine.geometry_checks),1)
        self.assertFalse(manager.accept(result)['accepted'])

    def test_rewrapped_proofs_and_changed_action_grants_cannot_expand_horizon(self):
        for change in ('gap','rollback','foreign_proof','geometry','fixed_home','null_geometry',
                       'missing_fixed_home','bad_hash','lift','waiting_place','bench'):
            with self.subTest(change=change):
                manager,request,interval,receipt,driver=self.interval_case()
                if change=='gap':interval.update(start_knot=2,start_mm=200.)
                elif change=='rollback':interval.update(start_knot=0,start_mm=0.)
                elif change=='foreign_proof':interval.update(end_knot=3,end_mm=300.)
                elif change in ('geometry','fixed_home'):receipt[change]['passed']=False
                elif change=='null_geometry':receipt['geometry']=None
                elif change=='missing_fixed_home':del receipt['fixed_home']
                elif change in ('lift','waiting_place','bench'):
                    manager.engine.vehicles['BF01']['action_context'][change]={'slot':1}
                result=background._checked_result(request,interval=interval,receipt=receipt)
                if change=='bad_hash':result['result_sha256']='invalid'
                self.assertFalse(manager.accept(result)['accepted'])
                self.assertNotIn(request['request_id'],manager.jobs)
                self.assertIn('BF01',manager.snapshot()['failures'])
                self.assertEqual(driver.certified_horizon_mm,100.)
                self.assertEqual(manager.intervals['BF01']['end_knot'],1)
                manager.before_tick()
                self.assertEqual(manager.drain(),[])


if __name__=='__main__':unittest.main()
