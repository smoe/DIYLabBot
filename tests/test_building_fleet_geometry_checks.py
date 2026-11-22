"""No broad shaft or waiting-bay exceptions at the geometry boundary."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_geometry_checks import GeometryChecks
from building_fleet_lift_geometry import PortSupportContext
import building_fleet_geometry_checks as geometry_checks


class BoundaryTests(unittest.TestCase):
    def fixture(self):
        checker=object.__new__(GeometryChecks);checker.source={'fixture':'source'}
        checker.nav=SimpleNamespace(waits={'EG':[[100,0,0],[200,0,0]]},
            waiting_bay_polygons={'EG':[[[90,-10],[110,-10],[110,10],[90,10]],[[190,-10],[210,-10],[210,10],[190,10]]]})
        names=['ExcludedArea.LiftCore','ExcludedArea.R3_028','BenchSafety.DNA']
        polys=[[[i,0],[i+1,0],[i+1,1],[i,1]]for i in range(3)]
        checker.base={'EG':SimpleNamespace(obstacles=polys,obstacle_names=names,lift_context=None)};checker.variants={}
        return checker

    def test_only_typed_matching_context_can_remove_the_shaft_mask(self):
        checker=self.fixture()
        with self.assertRaisesRegex(ValueError,'typed'):checker.certificate('EG',context=SimpleNamespace())
        context=object.__new__(PortSupportContext);context.level='EG';context.source=copy.deepcopy(checker.source)
        cert=checker.certificate('EG',context=context)
        self.assertNotIn('ExcludedArea.LiftCore',cert.obstacle_names)
        self.assertIn('ExcludedArea.R3_028',cert.obstacle_names);self.assertIn('BenchSafety.DNA',cert.obstacle_names)
        self.assertIn('ExcludedArea.LiftCore',checker.base['EG'].obstacle_names)
        self.assertIn('ExcludedArea.LiftCore',checker.certificate('EG').obstacle_names)

    def test_only_own_source_waiting_slot_is_exempted(self):
        checker=self.fixture()
        grant={'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':[100,0,0],'role':'start'}}
        self.assertEqual(checker.own_slot(grant,'EG'),0)
        cert=checker.certificate('EG',0)
        self.assertNotIn('ReservedLiftWaitingBay.EG.0',cert.obstacle_names)
        self.assertIn('ReservedLiftWaitingBay.EG.1',cert.obstacle_names)
        grant['waiting_place']['pose_mm']=[101,0,0]
        with self.assertRaisesRegex(ValueError,'source pose'):checker.own_slot(grant,'EG')

    def test_partial_or_foreign_grant_has_no_waiting_exception(self):
        checker=self.fixture()
        for grant in ({},{'waiting_place':{'status':'waiting'}},{'waiting_place':{'status':'granted','level':'OG3','slot':0}}):
            self.assertIsNone(checker.own_slot(grant,'EG'))

    def test_conditional_successor_is_not_physical_permission(self):
        checker=self.fixture()
        grant={'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':[100,0,0],
                               'role':'lookahead_destination'}}
        for arrival in(False,True):
            with self.assertRaisesRegex(ValueError,'conditional'):
                checker.own_slot(grant,'EG',allow_arrival=arrival)
        grant['waiting_place']['role']='destination'
        with self.assertRaisesRegex(ValueError,'alighting'):checker.own_slot(grant,'EG')
        self.assertEqual(checker.own_slot(grant,'EG',allow_arrival=True),0)

    def test_exported_roles_need_observed_activation_and_promotion(self):
        checker=self.fixture()
        def event(kind,t,role,slot=0):
            return {'event':kind,'vehicle_id':'BF01','time_s':t,'level':'EG','slot':slot,'role':role}
        events=[event('waiting_granted',0,'lookahead_destination'),
                event('waiting_role_activated',1,'destination'),
                event('waiting_promoted',2,'start'),event('waiting_released',3,'start')]
        for t in(0,.5,1,1.5):self.assertIsNone(checker.exported_slot(events,'BF01',t,'EG'))
        self.assertIsNone(checker.exported_slot(events,'BF01',.5,'EG',allow_arrival=True))
        self.assertEqual(checker.exported_slot(events,'BF01',1,'EG',allow_arrival=True),0)
        self.assertEqual(checker.exported_slot(events,'BF01',2,'EG'),0)
        self.assertIsNone(checker.exported_slot(events,'BF01',3,'EG'))
        self.assertIsNone(checker.exported_slot(events,'BF02',2,'EG'))
        with self.assertRaisesRegex(ValueError,'actual arrival'):
            checker.exported_slot([events[0],events[2]],'BF01',2,'EG')
        with self.assertRaisesRegex(ValueError,'successor'):
            checker.exported_slot([events[1]],'BF01',2,'EG')

    def test_cabin_attachment_rejects_motion_even_between_fixed_endpoints(self):
        checker=self.fixture()
        def point(t,x,v=0):return {'time_s':t,'pose_mm_rad':[x,0,0],
            'velocity_mm_rad_s':[v,0,0],'acceleration_mm_rad_s2':[0,0,0]}
        for middle in(point(.5,1),point(.5,0,1)):
            episode={'start_s':0,'end_s':1,'points':[point(0,0),middle,point(1,0)]}
            with self.assertRaisesRegex(ValueError,'fixed local'):
                checker.attached_support(episode,SimpleNamespace())

    def test_parked_cabin_support_cannot_use_a_closed_gap_as_an_edge_waiver(self):
        checker=self.fixture();checker.source=geometry_checks.model.load()
        z=3
        def slab(a,b):return [[[a,-100,z],[b,-100,z],[b,100,z]],[[a,-100,z],[b,100,z],[a,100,z]]]
        actual=SimpleNamespace(scene={'maximum_float32_error_mm':0,'groups':[{'id':'LiftCabinFloorFinish'}]},
            triangles=lambda g:slab(-100,-4)+slab(4,100))
        checker.nav.mesh=object();checker.certificate=lambda *a:SimpleNamespace(L=20,W=20,reserve=0,mesh_error=0)
        episode={'level_id':'EG','start_s':0,'end_s':1,'points':[
            {'time_s':t,'pose_mm_rad':[0,0,0],'velocity_mm_rad_s':[0,0,0],
             'acceleration_mm_rad_s2':[0,0,0]}for t in(0,1)]}
        with patch.object(geometry_checks,'posed_mesh',return_value=actual),patch.object(
                geometry_checks,'source_surface_contract',return_value={'height_offset_mm':3}):
            with self.assertRaisesRegex(ValueError,'bridged edge'):
                checker.attached_support(episode,SimpleNamespace(values=lambda t:{},z=lambda t:0))


if __name__=='__main__':unittest.main()
