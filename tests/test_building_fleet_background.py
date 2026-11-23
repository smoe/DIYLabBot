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
            checked.append((action,curve,observed));return {'passed':True,'native_checks':1}
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


if __name__=='__main__':unittest.main()
