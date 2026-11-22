"""Shared port recipe and continuous own-bay exit interfaces, without CAD."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_port_paths import PortPaths
import building_fleet_port_paths as port_paths
from building_fleet_motion import Path as OwnPath
from test_building_fleet_missions import fixture,own


def setup():
    planner,nav,graph=fixture();helper=PortPaths.__new__(PortPaths)
    helper.nav=nav;helper.trim=planner.trim_mm;helper.ports=planner.ports;helper.source=planner.source;helper.sensor=nav.sensor
    centre=planner.ports['EG']['cabin_entry_mm'][1]
    half=(nav.cabin_interior_mm['max'][1]-nav.cabin_interior_mm['min'][1])/4
    helper.aperture=[centre-half,centre+half];helper.mesh_error=0.;helper.passing=planner.passing_gap_mm
    helper.band=(helper.aperture[1]-helper.aperture[0])/2-nav.radius-nav.reserve-nav.navigation_margin_mm
    helper.open_leaves={};helper.departures={}
    nav.mesh.manifest['objects']=[{'id':'fixture_cabin','joint':{'type':'prismatic','axis':[0,0,1]}}]
    for level,port in planner.ports.items():
        outside=1 if port['exit_eye_mm'][0]>port['plane_x_mm']else-1
        first=port['plane_x_mm']+outside*(port['wall_thickness_mm']/2+nav.radius+nav.reserve+nav.navigation_margin_mm)
        front=first-outside*(nav.radius+nav.reserve+nav.navigation_margin_mm)
        helper.open_leaves[level]=(first,{'scope':'Pure fixture leaf bound; no native proof',
            'fully_open_leaf_corridor_bound_x_mm':front})
        ident='fixture_door_'+level;port['door_object_ids']=[ident]
        nav.mesh.manifest['objects'].append({'id':ident,'parent_object_id':'fixture_cabin',
            'joint':{'type':'prismatic','axis':[0,1,0]}})
    planner.port_paths=helper
    return planner,nav,helper


class PortPathTests(unittest.TestCase):
    def test_board_and_reverse_share_identical_source_points_caps_and_headings(self):
        planner,nav,helper=setup()
        for level in planner.ports:
            for cabin in range(len(planner.cabin_lanes_override)):
                board=helper.boarding(level,0,cabin,planner.cabin_lanes_override)
                leave=helper.alighting(level,0,cabin,planner.cabin_lanes_override)
                self.assertEqual(leave['points_mm'],list(reversed(board['points_mm'])))
                self.assertEqual(leave['corner_trim_caps'],sorted([
                    {'point_index':len(board['points_mm'])-1-r['point_index'],'maximum_trim_mm':r['maximum_trim_mm']}
                    for r in board['corner_trim_caps']],key=lambda r:r['point_index']))
                self.assertEqual(leave['body_clear_waypoint_on_reverse'],len(board['points_mm'])-2)
                path=OwnPath(board['points_mm'],board['corner_trim_mm'],corner_trim_caps=board['corner_trim_caps'])
                self.assertAlmostEqual(math.remainder(path.evaluate(0)[0][2]-nav.waits[level][0][2],2*math.pi),0)

    def test_all_fixed_port_and_owned_wait_departures_are_prepared_before_runtime(self):
        planner,nav,helper=setup();routes=planner.prepared_routes()
        for level in nav.waits:
            departure=helper.waiting_departure(level,0)
            self.assertTrue(any(r['points_mm']==departure['points_mm']for r in routes))
            for cabin in range(len(planner.cabin_lanes_override)):
                board=helper.boarding(level,0,cabin,planner.cabin_lanes_override)
                self.assertTrue(any(r['points_mm']==board['points_mm']and r.get('corner_trim_caps')==board['corner_trim_caps']for r in routes))
        self.assertFalse(any(r.get('curve_qualified',False)for r in routes))

    def test_opposite_side_exit_passes_through_owned_bay_without_a_terminal_stop(self):
        planner,nav,helper=setup();cabin=0;lane=planner.cabin_lanes_override[cabin]['pose_mm']
        snapshot=own(nav,level='OG3',z_mm=4250.,aboard=True,home=False,pose_mm_rad=[*lane[:2],math.pi])
        grant={'status':'assigned','slot':0,'start_port':'EG.in','destination_port':'OG.out','exit_ready':True}
        waiting={'status':'granted','level':'OG3','slot':0,'pose_mm':nav.waits['OG3'][0],'role':'destination'}
        def captured(*args):return args
        with patch.object(planner,'_floor_leg',side_effect=captured):
            args=planner._alight(snapshot,{'lift':grant,'waiting_place':waiting})
        prefix=args[2];marks=args[3];caps=args[5]
        wait=nav.waits['OG3'][0][:2]
        self.assertIn(wait,prefix[1:-1]);self.assertIn(prefix[-1],[p[0]for p in planner.wait_approaches['OG3',0]])
        self.assertLess(marks[0]['point_index'],prefix.index(wait))
        self.assertEqual(marks[0]['details']['direction'],'forward')
        self.assertEqual(caps,helper.alighting('OG3',0,0,planner.cabin_lanes_override)['corner_trim_caps'])

    def test_capacity_departure_uses_the_shared_leaf_bound_and_static_hub(self):
        planner,nav,helper=setup();planner.states['BF01']['terminal']={'kind':'capacity_wait','level':'EG','slot':0}
        from test_building_fleet_missions import mission
        planner.receive_assignment('BF01',mission('local'))
        observed=own(nav,pose_mm_rad=nav.waits['EG'][0][:],home=False,phase='capacity_wait')
        with patch.object(planner,'_floor_leg',side_effect=lambda *a,**k:(a,k)):
            args,kwargs=planner.next_action(observed,0,{'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':nav.waits['EG'][0],'role':'start'}})
        self.assertEqual(args[2],helper.waiting_departure('EG',0)['points_mm'])
        self.assertEqual(args[2][-1],nav.road_hubs['EG'])

    def test_private_bay_sweep_preserves_unresolved_adjacent_float_intervals(self):
        _,nav,helper=setup();a=50000.;b=math.nextafter(a,math.inf)
        pieces=[{'weight':a},{'weight':b-a}]
        fake=SimpleNamespace(pieces=pieces,evaluate=lambda s:([0.,0.,0.],))
        bounds=lambda piece,**kwargs: {'linear':[0. if piece is pieces[0]else 2e11],'angular':[0.]}
        with patch.object(port_paths,'Path',return_value=fake),patch.object(port_paths,'spatial_bounds',side_effect=bounds),\
                patch.object(port_paths,'_rectangle_distance',return_value=nav.reserve+1.):
            self.assertFalse(helper._bay_sweep_clear([[0.,0.],[1.,0.]],[[]],nav.reserve))

    def test_departure_envelope_retains_sensing_uncertainty_and_preserves_board_corner(self):
        _,nav,helper=setup();before=copy.deepcopy(helper.open_leaves)
        for level,port in helper.ports.items():
            point,evidence=helper.departure_first_corner(level,nav.reserve+20)
            outside=1 if port['exit_eye_mm'][0]>port['plane_x_mm']else-1
            self.assertAlmostEqual(point,before[level][0]+outside*20)
            self.assertEqual(evidence['required_source_clearance_mm'],nav.reserve+20)
            self.assertIn('fixture_cabin',evidence['source_X_invariant_joint_ids'])
            self.assertEqual(helper.first_corner(level),before[level])
        nav.mesh.manifest['objects'][0]['joint']['axis']=[1,0,0]
        with self.assertRaisesRegex(ValueError,'not invariant'):
            helper.departure_first_corner('EG',nav.reserve+20)


if __name__=='__main__':unittest.main()
