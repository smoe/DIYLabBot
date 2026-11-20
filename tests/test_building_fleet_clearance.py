"""Exact floor union, seams, holes and actual between-node vehicle orientation."""
from pathlib import Path
import math
import sys
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import building_fleet_clearance as c


def rectangle(x0,y0,x1,y1):
    return [[[x0,y0],[x1,y0],[x1,y1]],[[x0,y0],[x1,y1],[x0,y1]]]


class ExactFloorUnionTests(unittest.TestCase):
    def test_shared_diagonal_and_adjacent_native_slabs_cover(self):
        triangles=rectangle(-5,-3,0,3)+rectangle(0,-3,5,3)
        result=c.floor_union_covers(triangles,[0,0],0,4,2)
        self.assertTrue(result['passed']);self.assertEqual(result['covered_area_mm2'],32)

    def test_overlap_and_nested_triangles_are_not_double_counted(self):
        triangles=rectangle(-5,-5,5,5)+rectangle(-2,-2,2,2)+rectangle(-5,-5,5,5)
        result=c.floor_union_covers(triangles,[0,0],0,3,3)
        self.assertTrue(result['passed']);self.assertEqual(result['covered_area_mm2'],36)

    def test_tiny_hole_cannot_be_erased_by_area_tolerance(self):
        h=.0001
        triangles=rectangle(-3,-3,-h,3)+rectangle(h,-3,3,3)+rectangle(-h,-3,h,-h)+rectangle(-h,h,h,3)
        result=c.floor_union_covers(triangles,[0,0],0,2,2)
        self.assertFalse(result['passed']);self.assertGreater(result['missing_area_mm2'],0)
        self.assertAlmostEqual(result['missing_area_mm2'],4*h*h,places=15)

    def test_disconnected_slabs_need_the_full_bridge(self):
        separate=rectangle(-4,-2,-.2,2)+rectangle(.2,-2,4,2)
        self.assertFalse(c.floor_union_covers(separate,[0,0],0,3,1)['passed'])
        self.assertTrue(c.floor_union_covers(separate+rectangle(-.3,-2,.3,2),[0,0],0,3,1)['passed'])

    def test_oriented_rectangle_does_not_require_a_disc_sized_floor(self):
        triangles=rectangle(-5,-1.2,5,1.2)
        self.assertTrue(c.floor_union_covers(triangles,[0,0],0,2,.5)['passed'])
        self.assertFalse(c.floor_union_covers(triangles,[0,0],math.pi/2,2,.5)['passed'])
        self.assertTrue(c.floor_union_covers(rectangle(-5,-5,5,5),[0,0],math.pi/4,2,.5)['passed'])

    def test_invalid_or_absent_floor_fails_closed(self):
        self.assertFalse(c.floor_union_covers([],[0,0],0,1,1)['passed'])
        for args in [([float('nan'),0],0,1,1),([0,0],0,-1,1)]:
            with self.assertRaises(ValueError):c.floor_union_covers([],*args)

    def test_polygon_index_does_not_omit_crossing_or_oversized_floor(self):
        polygons=[[[0,0],[20000,0],[20000,20000]],[[100,100],[200,100],[100,200]]]
        index=c.PolygonIndex(polygons,cell_mm=50)
        self.assertEqual(len(index.query([120,120],[140,140])),2)

    def test_actual_pva_yaw_overshoot_between_safe_endpoint_headings(self):
        checker=c.ClearanceCertificate.__new__(c.ClearanceCertificate)
        checker.L=2;checker.W=.5;checker.radius=math.hypot(2,.5);checker.reserve=0;checker.mesh_error=0
        checker.floor_index=c.PolygonIndex(rectangle(-5,-1.2,5,1.2));checker.distance=lambda xy,yaw:(500,'no_fixture_obstacles')
        checker.start_grid=SimpleNamespace(cell=lambda p:0,blocked=bytearray([0]))
        points=[{'time_s':t,'pose_mm_rad':[x,0,0],'velocity_mm_rad_s':[.1,0,w],'acceleration_mm_rad_s2':[0,0,0]}for t,x,w in [(0,0,6.4),(1,.1,-6.4)]]
        curve=c.floor.motion.Curve(c.floor.canonical(points))
        self.assertTrue(checker.support([0,0],0,0)['passed']);self.assertTrue(checker.support([.1,0],0,0)['passed'])
        result=checker.check(curve)
        self.assertFalse(result['passed']);self.assertIn('floor_union',result['reason'])


if __name__=='__main__':unittest.main()
