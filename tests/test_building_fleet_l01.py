import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_l01 as l01
import building_fleet_model as model


class ConnectorSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.definition=l01.definition()

    def test_connector_derived_and_all_work_bounds_preserved_without_scale(self):
        d=self.definition;source=model.read_json(l01.ROOT/'model/tr01-l01-workcell.protocol.json')
        self.assertGreater(d['strip_residual_after_reserve_mm'],0)
        self.assertAlmostEqual(d['local_points_xy_mm'][1][1],(d['open_exit_leaf_tip_y_mm']+d['island_front_y_mm'])/2)
        for area in d['work_areas']:
            self.assertEqual(area['source_bounds_xy_mm'],source['work_areas'][area['id']]['bounds_xy_mm'])
            self.assertEqual(area['scale'],1)
            self.assertEqual(area['state'],'occupied_or_unknown')
        self.assertEqual(d['local_points_xy_mm'][0][0],d['bound_lane_values_mm']['right'])
        self.assertEqual(d['local_points_xy_mm'][-1][0],d['bound_lane_values_mm']['left'])

    def test_source_rejects_extra_fields_or_changed_policy(self):
        source=l01.load();schema=model.read_json(l01.SCHEMA)
        changed=copy.deepcopy(source);changed['route']['reverse']=True
        with self.assertRaises(ValueError):model.validate_shape(changed,schema)
        changed=copy.deepcopy(source);changed['bench_exclusion']['scaling']=True
        with self.assertRaises(ValueError):model.validate_shape(changed,schema)
        changed=copy.deepcopy(source);changed['qualification']['native_curve_qualified']=True
        with self.assertRaises(ValueError):model.validate_shape(changed,schema)
        changed=copy.deepcopy(source);changed['extra']='ignored'
        with self.assertRaises(ValueError):model.validate_shape(changed,schema)

    def test_corner_path_is_connected_and_not_reversing(self):
        parts=l01.pieces(self.definition)
        self.assertEqual(len(parts),5)
        for a,b in zip(parts,parts[1:]):self.assertEqual(a[-1],b[0])
        for controls in parts:
            for u in [0,.125,.5,.875,1]:
                derivative=[[len(controls[:-1])*(b-a)for a,b in zip(x,y)]for x,y in zip(controls,controls[1:])]
                v=l01.CornerPath._bezier(derivative,u)
                self.assertGreater(v[0]**2+v[1]**2,0)


class FakeMesh:
    def __init__(self,supported=True):
        self.scene={'bounds_mm':{'min':[-2000,-2000,-10],'max':[3000,2000,300]},
                    'maximum_float32_error_mm':0.,'linear_tessellation_deflection_mm':0.,'groups':[]}
        if supported:self.scene['groups']=[{'id':'Floor','role':'concept_storey_slab','bounds_mm':{'min':[-2000,-2000,-10],'max':[3000,2000,0]}}]
    def bounds(self,group):return group['bounds_mm']
    def triangles(self,group):
        yield[[-2000,-2000,0],[3000,-2000,0],[3000,2000,0]]
        yield[[-2000,-2000,0],[3000,2000,0],[-2000,2000,0]]


class IntervalCertificateTests(unittest.TestCase):
    def definition(self,polygon=None):
        return{'vehicle':{'half_length_mm':50,'half_width_mm':30,'reserve_mm':10,'height_mm':100},
               'world_points_xyz_mm':[[-1000,0,0],[1000,0,0]],
               'work_areas':[]if polygon is None else[{'id':'untouched','world_polygon_mm':polygon}]}

    def test_continuous_straight_passes_and_between_endpoint_obstacle_fails(self):
        checker=l01.ClearanceCertificate(FakeMesh(),self.definition())
        self.assertTrue(checker.check([[-1000,0,0],[1000,0,0]])['passed'])
        blocked=l01.ClearanceCertificate(FakeMesh(),self.definition([[580,-50],[620,-50],[620,50],[580,50]]))
        self.assertFalse(blocked.check([[-1000,0,0],[1000,0,0]])['passed'])

    def test_missing_native_support_fails(self):
        checker=l01.ClearanceCertificate(FakeMesh(False),self.definition())
        self.assertFalse(checker.check([[-1000,0,0],[1000,0,0]])['passed'])

    def test_exported_yaw_is_checked_independently_of_xy_tangent(self):
        import tr01_floor_motion as floor
        def curve(yaw):
            points=[{'time_s':time,floor.F[0]:[x,0,yaw],floor.F[1]:[0,0,0],floor.F[2]:[0,0,0]}
                    for time,x in [(0.,-1000.),(10.,1000.)]]
            return floor.motion.Curve(points)
        definition=self.definition([[580,45],[620,45],[620,70],[580,70]])
        forward=l01.check_exported_motion(FakeMesh(),curve(0.),definition)
        sideways=l01.check_exported_motion(FakeMesh(),curve(__import__('math').pi/2),definition)
        self.assertTrue(forward['passed'])
        self.assertFalse(sideways['passed'])

    def test_polygon_rectangle_distance_is_not_bbox_only(self):
        triangle=[[100,0],[200,0],[100,100]]
        self.assertGreater(l01._rectangle_distance(triangle,[0,0],0,50,30),0)
        self.assertEqual(l01._rectangle_distance(triangle,[125,25],0,10,10),0)


if __name__=='__main__':unittest.main()
