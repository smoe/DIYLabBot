"""Static route support, through-parking, and source-derived envelope checks."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_navigation as nav
import building_fleet_routes as routes
import building_fleet_sim as sim
import tr01_camera_model as camera


def grid(width=8000,height=9000):
    result=nav.ClearanceGrid({'min':[0,0,0],'max':[width,height,0]},100)
    result.raster([[0,0],[width,0],[width,height],[0,height]],True)
    return result.finalize()


class EnvelopeTests(unittest.TestCase):
    def test_physical_closed_empty_vehicle_retains_bumper_and_cover(self):
        envelope=routes.vehicle_envelope()
        self.assertEqual(envelope['length_mm'],512)
        self.assertEqual(envelope['width_mm'],412)
        self.assertEqual(envelope['height_mm'],866)
        self.assertAlmostEqual(envelope['radius_mm'],math.hypot(256,206))

    def test_illustrative_view_cone_never_inflates_physical_vehicle(self):
        source=camera.expanded(camera.load());original=routes.vehicle_envelope(source)
        for op in source['operations']:
            if op['body'].endswith('_View'):op['shape']['height']*=10
        self.assertEqual(routes.vehicle_envelope(source),original)


class ParkingTests(unittest.TestCase):
    def test_rows_allow_forward_departure_and_same_yaw_rear_arrival(self):
        g=grid();polygon=[[0,0],[8000,0],[8000,9000],[0,9000]];radius=math.hypot(256,206);reserve=85
        rows=routes.depot_rows(g,polygon,512,412,radius,reserve)
        self.assertGreaterEqual(sum(len(row['points'])for row in rows),20)
        homes=[p for row in rows for p in row['points']]
        for row in rows:
            d=row['distance_mm']
            for point in row['points']:
                self.assertTrue(g.line_free([point[0],point[1]-d],[point[0],point[1]+d],radius+reserve))
                # The entire forward through-bay sweep remains separated from
                # every other parked footprint, rather than just parked poses.
                sweep={'pose_mm':[point[0],point[1],math.pi/2],'footprint_mm':[512+2*d,412]}
                for other in homes:
                    if other==point:continue
                    parked={'pose_mm':[*other,math.pi/2],'footprint_mm':[512,412]}
                    self.assertGreaterEqual(sim.polygon_distance(sim.footprint(sweep),sim.footprint(parked))+1e-6,reserve)
            for a,b in zip(row['aisle_loop_mm'],row['aisle_loop_mm'][1:]):
                self.assertTrue(g.line_free(a,b,radius+reserve))
                for other in homes:
                    self.assertGreaterEqual(sim.point_segment_distance(other,a,b)-2*radius+1e-6,reserve)

    def test_missing_depot_support_cannot_be_replaced_by_corridor_space(self):
        g=grid(3000,3000)
        polygon=[[100,100],[500,100],[500,500],[100,500]]
        self.assertEqual(routes.depot_rows(g,polygon,512,412,329,85),[])
        with self.assertRaisesRegex(ValueError,'Depot free area'):
            routes.home_slots(g,polygon,20,329,85)


class InspectionTests(unittest.TestCase):
    def test_inspection_is_positive_area_closed_loop_in_supported_room(self):
        g=grid(4000,4000);polygon=[[0,0],[4000,0],[4000,4000],[0,4000]]
        points=routes.inspection_loop(g,polygon,329,85)
        self.assertEqual(points[0],points[-1]);self.assertEqual(len(set(map(tuple,points))),4)
        for a,b in zip(points,points[1:]):self.assertTrue(g.line_free(a,b,414))

    def test_area_search_cannot_cut_through_an_adjacent_room(self):
        n=routes.Navigation.__new__(routes.Navigation);g=grid(5000,5000)
        # U-shaped source room: the geometrically short straight line crosses
        # the neighbour in the missing upper middle, which must be avoided.
        polygon=[[0,0],[5000,0],[5000,5000],[3500,5000],[3500,1800],[1500,1800],[1500,5000],[0,5000]]
        n.grids={'EG':g};n.polygons={'EG':{'room':polygon}};n.radius=100;n.reserve=50;n._area_routes={}
        points=n._area_route('EG','room',[700,4000],[4300,4000])
        self.assertGreater(len(points),2)
        for a,b in zip(points,points[1:]):
            for i in range(21):self.assertTrue(nav.point_in_polygon([a[k]+(b[k]-a[k])*i/20 for k in range(2)],polygon))


class RightLaneTests(unittest.TestCase):
    def test_reverse_queries_get_own_right_lane_not_reversed_forward_lane(self):
        n=routes.Navigation.__new__(routes.Navigation);n.radius=math.hypot(256,206);n.reserve=85
        n.envelope={'length_mm':512,'width_mm':412};n.homes={};n._route_cache={}
        polygon=[[0,0],[10000,0],[10000,6000],[0,6000]]
        n.polygons={'EG':{'C':polygon}}
        n.topological={'EG':{'excluded_areas':[],'plan':{'areas':[{'id':'C','kind':'corridor'}]}}}
        n.config={'motion':{'zone_velocity_mm_s':300},'geometry':{'grid_step_mm':50}}
        n._straight_hits=lambda level,a,b:[]  # Independent spacious corridor fixture.
        result={'level':'EG','points_mm':[[1000,3000],[9000,3000]],'resources':[],'zone_segments':[],
                'portal_certificates':[],'curve_qualified':False}
        forward=n._remember_route(('EG',(1000,3000),(9000,3000)),result)
        backward=n._own_right(copy.deepcopy(n._route_cache['EG',(9000,3000),(1000,3000)]))
        self.assertEqual(len(forward['right_lane_segments']),1)
        self.assertEqual(len(backward['right_lane_segments']),1)
        a=forward['right_lane_segments'][0]['start_index'];b=backward['right_lane_segments'][0]['start_index']
        self.assertLess(forward['points_mm'][a][1],3000)
        self.assertGreater(backward['points_mm'][b][1],3000)
        self.assertAlmostEqual(backward['points_mm'][b][1]-forward['points_mm'][a][1],412+85)
        self.assertTrue(forward['bottleneck_spans'])
        self.assertFalse(any(r['start_index']<=a and r['end_index']>=a+1 for r in forward['bottleneck_spans']))
        self.assertFalse(forward['curve_qualified'])


class WaitingBayTests(unittest.TestCase):
    def test_ordinary_road_hub_is_outside_parked_waiting_envelopes(self):
        n=routes.Navigation.__new__(routes.Navigation);n.radius=329;n.reserve=85
        n.envelope={'length_mm':512,'width_mm':412};n.waits={'EG':[[3500,3000,0],[3500,4500,0]]}
        n.grids={'EG':grid(8000,9000)}
        n.polygons={'EG':{'C':[[0,0],[8000,0],[8000,9000],[0,9000]]}}
        n.topological={'EG':{'landing_neighbors':{'P':['C'], 'Q':['C']}}}
        n.config={'lift':{'route_sides':{'EG':'inward'}}}
        from types import SimpleNamespace
        n.mesh=SimpleNamespace(manifest={'elevator':{'ports':[
            {'id':'P','active':True,'level_id':'EG','side':'inward',
             'cabin_entry_mm':[1000,3750,0],'exit_eye_mm':[2500,3750,0]},
            {'id':'Q','active':True,'level_id':'EG','side':'outward',
             'cabin_entry_mm':[1000,3750,0],'exit_eye_mm':[500,3750,0]}]}})
        n._derive_waiting_bays();hub=n.road_hubs['EG']
        self.assertTrue(all(p[2]==math.pi for p in n.waits['EG']))
        for poly in n.waiting_bay_polygons['EG']:
            self.assertFalse(nav.point_in_polygon(hub,poly))
            self.assertGreaterEqual(min(sim.point_segment_distance(hub,a,b)for a,b in zip(poly,poly[1:]+poly[:1])),414)


if __name__=='__main__':unittest.main()
