"""Contiguous per-action planner receipts at the original nominal PVA knots."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_background as bg
import building_fleet_model as model
from building_fleet_control import F,preparation_digest
from building_fleet_geometry import vehicle_envelope
from building_fleet_motion import Path as MotionPath
import tr01_floor_motion as floor


class IntervalPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=model.load()
        # More than three quanta on a single analytic S-curve.
        curve=floor.motion.Curve(floor.motion.rest_to_rest(6000.,200.,100.,400.))
        times=sorted(set(curve.times)|{i/4 for i in range(1,int(curve.times[-1]*4))})
        points=[{'time_s':t,**{field:curve.evaluate(t)[field] for field in F[:3]}} for t in times]
        cls.program={'points':[{'pose_mm_rad':[0.,0.,0.]}],'scalar_clock':points}

    def setUp(self):
        envelope=vehicle_envelope()
        homes={'BF01':{'level':'EG','pose_mm_rad':[0.,0.,0.]},
               'BF02':{'level':'EG','pose_mm_rad':[0.,10000.,0.]}}
        nav=SimpleNamespace(radius=envelope['radius_mm'],envelope=envelope,homes=homes,reserve=20.,
            portals={'EG':[]},mesh=SimpleNamespace(manifest={'objects':[]}))
        self.curves=[]
        def geometry(action,curve,observed):
            self.curves.append(curve.points)
            return {'passed':True}
        self.context={'source':self.source,'source_binding':'a'*64,'nav':nav,
            'catalog':SimpleNamespace(spans=lambda level,path:[]),'geometry_checks':geometry}
        action={'level':'EG','points_mm':[[0.,0.],[6000.,0.]],'corner_trim_mm':100.,
            'zone_segments':[],'reverse':False,'markers':[],'terminal':{'kind':'inspection_pass'},'prefetch_level':'EG'}
        self.full={'format':bg.FORMAT,'kind':'full_route','request_id':'1','source_binding':'a'*64,
            'vehicle_id':'BF01','action':action,'fence':{'generation':1,'level':'EG',
                'own_narrow_grant':{'resource':'A','status':'granted'},'action_sha256':preparation_digest(action)},
            'observed':{'time_s':.35,'own_grants_at_start':{'lift':{},'waiting_place':{}}},
            'own_pose_mm_rad':[0.,0.,0.],'zone_caps':[[0.,300.]],'rolling_horizon_mm':200.}
        self.compiler=patch.object(bg,'compile_motion',return_value=copy.deepcopy(self.program)).start()
        self.addCleanup(patch.stopall)

    def extension(self,result):
        return {**copy.deepcopy(self.full),'kind':'route_interval','request_id':'2',
            'program_sha256':result['interval']['program_sha256'],'start_knot':result['interval']['end_knot']}

    def test_only_contiguous_original_knots_reuse_one_compilation_and_static_grants(self):
        first=bg.prepare_route(self.full,self.context)
        scalar=first['program']['scalar_clock']
        expected=bg.Controller(MotionPath(self.full['action']['points_mm'],100.),self.source,self.full['zone_caps'],
            radius_mm=self.context['nav'].radius,motion_program=first['program'],
            prepared_nominal=bg.PreparedNominal(self.source,MotionPath(self.full['action']['points_mm'],100.),
                self.full['zone_caps'],first['program'],first['nominal_proof'],6000.))
        absolute=bg._absolute_curve(expected,expected.nominal_clock,0.,.35)
        result=first;request=self.full;previous=0;sections=0
        while True:
            interval=result['interval'];end=interval['end_knot']
            self.assertEqual(interval['start_knot'],previous)
            self.assertEqual(result['receipt']['interval_sha256'],bg._interval_binding(request,interval))
            self.assertTrue(result['receipt']['geometry']['passed'])
            self.assertTrue(result['receipt']['fixed_home']['passed'])
            self.assertEqual(self.curves[-1],absolute.points[previous:end+1])
            self.assertEqual(interval['end_mm'],scalar[end][F[0]][0])
            if sections:self.assertLessEqual(end-previous,32)
            sections+=1
            if end==len(scalar)-1:break
            previous=end;request=self.extension(result)
            request['fence']['own_narrow_grant']={'resource':'B','status':'granted'}
            result=bg.prepare_route(request,self.context)
        self.assertGreater(sections,2)
        self.assertEqual(self.compiler.call_count,1)
        self.assertEqual(bg.prepare_route(self.extension(result),self.context)['status'],'interval_rejected')

    def test_stale_foreign_gap_and_failed_native_proof_do_not_extend(self):
        first=bg.prepare_route(self.full,self.context)
        request=self.extension(first)
        for mutation in (lambda r:r.update(start_knot=r['start_knot']+1),
                         lambda r:r.update(start_knot=0),lambda r:r.update(program_sha256='b'*64),
                         lambda r:r['fence'].update(generation=2),lambda r:r.update(vehicle_id='BF02'),
                         lambda r:r['observed']['own_grants_at_start'].update(lift={'slot':2}),
                         lambda r:r['observed']['own_grants_at_start'].update(waiting_place={'slot':1})):
            wrong=copy.deepcopy(request);mutation(wrong)
            self.assertEqual(bg.prepare_route(wrong,self.context)['status'],'interval_rejected')
        self.context['geometry_checks']=lambda *args:{'passed':False,'reason':'test floor rejection'}
        failed=bg.prepare_route(request,self.context);self.assertEqual(failed['status'],'interval_rejected')
        self.assertIn('floor rejection',failed['reason'])
        self.assertEqual(self.context['rolling_nominals']['BF01']['end_knot'],request['start_knot'])
        self.context['geometry_checks']=lambda *args:self.fail('Repeated rejected interval')
        self.assertEqual(bg.prepare_route(request,self.context)['status'],'interval_rejected')
        self.assertEqual(self.compiler.call_count,1)

    def test_lift_and_missing_fixed_home_proof_fail_closed(self):
        lift=copy.deepcopy(self.full);lift['action']['lift_phase']={'kind':'boarding'}
        lift['fence']['action_sha256']=preparation_digest(lift['action'])
        self.assertEqual(bg.prepare_route(lift,self.context)['status'],'interval_rejected')
        self.compiler.assert_not_called()
        with patch.object(bg,'fixed_home_curve_proof',return_value={'passed':False}):
            failed=bg.prepare_route(self.full,self.context)
        self.assertEqual(failed['status'],'interval_rejected')
        self.assertIn('fixed-home',failed['reason'])

    def test_connector_joins_within_verified_horizon_and_preserves_nominal_suffix(self):
        full=bg.prepare_route(self.full,self.context)
        request={**self.full,'kind':'continuation','program':full['program'],
            'program_sha256':full['program_sha256'],'nominal_proof':full['nominal_proof'],
            'horizon_mm':full['interval']['end_mm'],
            'anchor':{'time_s':1.,'progress_mm':200.,'velocity_mm_s':0.,'acceleration_mm_s2':0.}}
        result=bg.prepare_route(request,self.context)
        self.assertTrue(result['proof']['passed'])
        self.assertLessEqual(result['proof']['join_progress_mm'],request['horizon_mm'])
        self.assertEqual(result['clock'][-1][F[0]][0],5800.)
        request['horizon_mm']=201.
        self.assertEqual(bg.prepare_route(request,self.context)['status'],'no_checked_connector')
        request['horizon_mm']=6000.
        self.assertIn('exceeds',bg.prepare_route(request,self.context)['reason'])
