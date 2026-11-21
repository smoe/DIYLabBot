"""Source-zone coverage for private routes and continuous corridor transitions."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model
from building_fleet_motion import Path as MotionPath
from building_fleet_control import Controller,F
from building_fleet_runner import zone_caps
import building_fleet_zones as zones


class ZoneTests(unittest.TestCase):
    def test_source_regions_include_rooms_doors_and_only_active_lift_port(self):
        nav=SimpleNamespace(topological={'EG':{'plan':{'areas':[{'id':'R','kind':'room'},{'id':'C','kind':'corridor'}]}}},
            polygons={'EG':{'R':[[0,0],[100,0],[100,100],[0,100]]}},
            portals={'EG':[{'opening':'D','centre_mm':[0,50],'tangent':[0,1],'opening_width_mm':100}]},
            mesh=SimpleNamespace(manifest={'elevator':{'cabin_bounds_mm':{'min':[200,0,0],'max':[400,200,2500]},
                'ports':[{'id':'active','active':True,'level_id':'EG','exit_eye_mm':[100,100,0]},
                         {'id':'closed','active':False,'level_id':'EG','exit_eye_mm':[500,100,0]}]}}))
        result=zones.source_regions(nav,'EG')
        self.assertEqual([(r['kind'],r['id'])for r in result],[('room','R'),('door','D'),('lift','active')])
        self.assertEqual(min(p[0]for p in result[-1]['polygon_mm']),100)

    def test_full_body_door_overlap_is_slow_before_the_centre_reaches_the_plane(self):
        path=MotionPath([[0,0],[1000,0]])
        windows=zones.progress_windows(path,[{'polygon_mm':[[500,-1000],[500,1000]]}],100,300)
        self.assertEqual(len(windows),1);start,end,cap=windows[0]
        self.assertLessEqual(start,400);self.assertGreaterEqual(end,600);self.assertEqual(cap,300)
        self.assertGreater(start,300);self.assertLess(end,700)

    def test_private_room_route_without_node_zones_has_source_speed_cap(self):
        source=model.load();path=MotionPath([[0,0],[3000,0]])
        windows=zones.progress_windows(path,[{'polygon_mm':[[-1000,-1000],[4000,-1000],[4000,1000],[-1000,1000]]}],414,300)
        caps=zone_caps(source,path,[[0,0],[3000,0]],[],250,windows)
        car=Controller(path,source,zone_caps=caps)
        maxima=car.nominal_clock_proof['dynamics']['zone_velocity_maxima_mm_s']
        self.assertLessEqual(maxima['300'],300*(1+1e-6))

    def test_corridor_keeps_higher_speed_with_smooth_nonzero_zone_boundaries(self):
        source=model.load();points=[[0,0],[12000,0]];path=MotionPath(points)
        windows=zones.progress_windows(path,[{'polygon_mm':[[5000,-1000],[7000,-1000],[7000,1000],[5000,1000]]}],414,300)
        caps=zone_caps(source,path,points,[],250,windows)
        car=Controller(path,source,zone_caps=caps)
        self.assertGreater(car.nominal_clock_proof['dynamics']['linear']['velocity'],300)
        self.assertLessEqual(car.nominal_clock_proof['dynamics']['zone_velocity_maxima_mm_s']['300'],300*(1+1e-6))
        self.assertTrue(car.nominal_clock_proof['dynamics'])
        for at,_ in caps[1:-1]:
            lo,hi=0,car.nominal_clock.times[-1]
            for _ in range(40):
                mid=(lo+hi)/2
                if car.nominal_clock.evaluate(mid)[F[0]][0]<at:lo=mid
                else:hi=mid
            self.assertGreater(car.nominal_clock.evaluate((lo+hi)/2)[F[1]][0],1)


if __name__=='__main__':unittest.main()
