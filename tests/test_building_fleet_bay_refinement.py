"""Waiting-bay preflags refine only through a whole fixed-heading sweep."""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_routes as routes


class WaitingBayRefinementTests(unittest.TestCase):
    def navigation(self,polygon):
        n=routes.Navigation.__new__(routes.Navigation)
        n.mesh=SimpleNamespace(scene={'linear_tessellation_deflection_mm':0.,'maximum_float32_error_mm':0.})
        n.envelope={'length_mm':2.,'width_mm':2.};n.reserve=1.;n.navigation_margin_mm=.1;n.height=2.;n.config={}
        n.topological={'EG':{'excluded_areas':[]}};n.polygons={'EG':{}};n.homes={};n.waiting_bay_polygons={'EG':[polygon]}
        return n

    def check(self,n,floor=True,native=()):
        bank=SimpleNamespace(covers=lambda *a,**k:{'passed':floor})
        with patch.object(routes.nav,'native_rectangle_collisions',return_value=list(native)),\
                patch('building_fleet_floor.floor_support',return_value=bank)as support:
            return n._straight_hits('EG',[0.,0.],[10.,0.]),support

    def test_square_corner_preflag_is_refined_by_complete_physical_sweep(self):
        n=self.navigation([[11.8,1.8],[12.,1.8],[12.,2.],[11.8,2.]])
        hits,support=self.check(n)
        self.assertEqual(hits,[]);self.assertTrue(support.called)
        self.assertGreater(routes.swept_rectangle_bay_clearance([0.,0.],[10.,0.],0.,2.,2.,n.waiting_bay_polygons['EG'][0]),1.1)

    def test_physical_contact_and_clearance_boundary_remain_reserved_hits(self):
        for dx,dy in((0.,0.),(.4,.5),(.66,.88)):
            n=self.navigation([[11+dx,1+dy],[12+dx,1+dy],[12+dx,2+dy],[11+dx,2+dy]])
            hits,support=self.check(n)
            self.assertEqual(hits,['ReservedLiftWaitingBay.EG.0']);self.assertFalse(support.called)

    def test_mesh_and_source_contact_margin_are_not_dropped(self):
        polygon=[[11.8,1.8],[12.,1.8],[12.,2.],[11.8,2.]]
        n=self.navigation(polygon);n.mesh.scene['linear_tessellation_deflection_mm']=.1
        hits,_=self.check(n);self.assertEqual(hits,['ReservedLiftWaitingBay.EG.0'])

    def test_refined_bay_never_skips_floor_or_native_obstacles(self):
        polygon=[[11.8,1.8],[12.,1.8],[12.,2.],[11.8,2.]]
        hits,support=self.check(self.navigation(polygon),floor=False)
        self.assertEqual(hits,['NativeFloorSupportR1']);self.assertTrue(support.called)
        hits,support=self.check(self.navigation(polygon),native=['NativeWall'])
        self.assertEqual(hits,['NativeWall']);self.assertFalse(support.called)

    def test_distance_covers_between_endpoints_and_large_rotated_translations(self):
        polygon=[[4.9,-.1],[5.1,-.1],[5.1,.1],[4.9,.1]]
        self.assertLess(routes.swept_rectangle_bay_clearance([0.,0.],[10.,0.],0.,2.,2.,polygon),0.)
        for angle,origin in((.71,[1e9,-1e9]),(math.pi,[-200.,300.])):
            c,s=math.cos(angle),math.sin(angle)
            transform=lambda p:[origin[0]+c*p[0]-s*p[1],origin[1]+s*p[0]+c*p[1]]
            far=[[11.8,1.8],[12.,1.8],[12.,2.],[11.8,2.]]
            self.assertGreater(routes.swept_rectangle_bay_clearance(transform([0,0]),transform([10,0]),angle,2.,2.,[transform(p)for p in far]),1.1)
            boundary=[[11.66,1.88],[12.,1.88],[12.,2.],[11.66,2.]]
            self.assertLessEqual(routes.swept_rectangle_bay_clearance(transform([0,0]),transform([10,0]),angle,2.,2.,[transform(p)for p in boundary]),1.1)


if __name__=='__main__':unittest.main()
