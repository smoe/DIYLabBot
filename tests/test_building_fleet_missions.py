"""Mission identity, own-state privacy and continuous composition contracts."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_missions import MissionPlanner, inspection_variants, waypoint_progress, _path


class Grid:
    def line_free(self, a, b, radius): return True


class Graph:
    def __init__(self): self.sealed = False; self.endpoints = set()
    def add_endpoint(self, level, p): self.endpoints.add((level, tuple(p)))
    def route(self, level, a, b):
        if math.dist(a, b) < 1e-8:
            return {'points_mm': [list(a)], 'zone_segments': []}
        return {'points_mm': [list(a), list(b)], 'zone_segments': []}


def fixture():
    source = {'geometry': {'localization_tolerance_mm': 10}, 'lift': {'maximum_capacity': 2}}
    envelope = {'length_mm': 512., 'width_mm': 412., 'radius_mm': math.hypot(256, 206)}
    ports = [{'id': 'EG.in', 'level_id': 'EG', 'active': True, 'side': 'inward',
              'plane_x_mm': 2580., 'wall_thickness_mm': 180.,
              'cabin_entry_mm': [1200., 1000., 1600.], 'exit_eye_mm': [3000., 1000., 1600.]},
             {'id': 'OG.out', 'level_id': 'OG3', 'active': True, 'side': 'outward',
              'plane_x_mm': -180., 'wall_thickness_mm': 180.,
              'cabin_entry_mm': [1200., 1000., 5850.], 'exit_eye_mm': [-600., 1000., 5850.]}]
    nav = SimpleNamespace(
        corner_trim_mm=250, homes={'BF01': {'level': 'EG', 'area': 'depot', 'pose_mm_rad': [5500., 4000., math.pi/2],
                        'departure_xy_mm': [5500., 5000.], 'arrival_xy_mm': [5500., 3000.]}},
        mesh=SimpleNamespace(manifest={'elevator': {'ports': ports}}), sensor={
            'clearance_mm': 75, 'range_error_mm': 15, 'range_mm': 2200, 'angular_step_deg': 2},
        reserve=85., radius=envelope['radius_mm'], envelope=envelope, navigation_margin_mm=3.,
        cabin_interior_mm={'min': [0., 0., 0.], 'max': [2400., 2000., 2240.]},
        waits={'EG': [[3500., 500., math.pi]], 'OG3': [[-1000., 500., 0.]]},
        road_hubs={'EG': [4500., 1000.], 'OG3': [-2000., 1000.]},
        waiting_bay_polygons={'EG': [[[3244., 294.], [3756., 294.], [3756., 706.], [3244., 706.]]],
                              'OG3': [[[-1256., 294.], [-744., 294.], [-744., 706.], [-1256., 706.]]]},
        grids={'EG': Grid(), 'OG3': Grid()}, level_z={'EG': 0., 'OG3': 4250.},
        inspections={('EG', 'room'): {'points_mm': [[6000., 6000.], [7000., 6000.], [7000., 7000.], [6000., 7000.], [6000., 6000.]]},
                     ('OG3', 'lab'): {'points_mm': [[-6000., 6000.], [-5000., 6000.], [-5000., 7000.], [-6000., 7000.], [-6000., 6000.]]}},
        _straight_hits=lambda level, a, b: [])
    graph = Graph(); planner = MissionPlanner(source, nav, graph)
    return planner, nav, graph


def own(nav, **changes):
    row = {'vehicle_id': 'BF01', 'pose_mm_rad': list(nav.homes['BF01']['pose_mm_rad']),
           'level': 'EG', 'z_mm': 0., 'phase': 'home', 'aboard': False,
           'home': True, 'mission_pending': False}
    row.update(changes)
    return row


def mission(mid, level='EG', area='room'):
    return {'mission_id': mid, 'vehicle_id': 'BF01', 'assigned_s': 0.,
            'goal': {'kind': 'inspection_pass', 'level': level, 'area': area, 'basis': 'plan_label'}}


class MissionTests(unittest.TestCase):
    def test_lift_approach_keeps_the_straight_final_heading_and_checks_the_chord(self):
        planner, _, _ = fixture()
        points = [[14000,14800],[14425,15175],[14367,15325],[13625,15325]]
        checked = []

        def shortcut(level, start, end):
            checked.append((level,start,end))
            return True

        planner.graph.shortcut_clear = shortcut
        smooth = planner._smooth_lift_wait_approach('EG',points,[],[],[])
        self.assertEqual(smooth, [points[0],*points[2:]])
        self.assertEqual(checked, [('EG',points[0],points[2])])
        self.assertEqual(_path(smooth,250).evaluate(_path(smooth,250).length)[0][2], math.pi)
        for zones,marks,caps in (
            ([{'end_index':1}],[],[]),
            ([],[{'point_index':1}],[]),
            ([],[],[{'point_index':1}]),
        ):
            self.assertEqual(planner._smooth_lift_wait_approach('EG',points,zones,marks,caps),points)
        planner.graph.shortcut_clear = lambda *args: False
        self.assertEqual(planner._smooth_lift_wait_approach('EG',points,[],[],[]),points)

    def test_source_loop_phase_changes_preserve_fixed_connector(self):
        loop = {'points_mm': [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}
        variants = inspection_variants(loop)
        self.assertEqual(len(variants), 4)
        self.assertTrue(all(row[0] == row[-1] for row in variants))
        fixed = {'points_mm': [[0, 0], [0, 10], [10, 10], [10, 20]], 'connector_source': 'source.json'}
        self.assertEqual(inspection_variants(fixed), [fixed['points_mm']])

    def test_repeated_xy_completion_has_later_monotone_actual_progress(self):
        points = [[0, -1000], [0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0], [0, -2000]]
        path = _path(points, 250); progress = waypoint_progress(path, points)
        self.assertGreater(progress[5], progress[1]+3000)
        self.assertEqual(progress[-1], path.length)
        self.assertEqual(progress, sorted(progress))

    def test_assignment_is_idempotent_and_rejects_foreign_or_conflicting(self):
        planner, _, _ = fixture(); item = mission('m1')
        self.assertTrue(planner.receive_assignment('BF01', item))
        self.assertFalse(planner.receive_assignment('BF01', copy.deepcopy(item)))
        changed = copy.deepcopy(item); changed['assigned_s'] = 1
        with self.assertRaises(ValueError): planner.receive_assignment('BF01', changed)
        changed = mission('m2'); changed['vehicle_id'] = 'BF02'
        with self.assertRaises(ValueError): planner.receive_assignment('BF01', changed)

    def test_closed_own_snapshot_refuses_world_or_peer_state(self):
        planner, nav, _ = fixture()
        with self.assertRaises(ValueError): planner.next_action(own(nav, peer_positions=[]), 0, {})
        invalid = own(nav); invalid['pose_mm_rad'][0] = float('nan')
        with self.assertRaises(ValueError): planner.next_action(invalid, 0, {})

    def test_unfenced_successor_ends_continuous_inspection_at_provisional_home(self):
        planner, nav, _ = fixture(); planner.receive_assignment('BF01', mission('m1'))
        request=planner.next_action(own(nav),0,{})
        self.assertEqual(request['kind'],'request_mission')
        planner.on_action_result('BF01',request,{'status':'pending_admission'},0)
        action = planner.next_action(own(nav), .05, {})
        self.assertEqual(action['kind'], 'drive')
        self.assertEqual(action['terminal']['kind'],'capacity_home')
        self.assertEqual(action['points_mm'][-1],nav.homes['BF01']['pose_mm_rad'][:2])
        self.assertEqual([m['event']for m in action['markers']],['inspection_completed'])
        self.assertLess(action['markers'][0]['progress_mm'],_path(action['points_mm'],250).length)
        self.assertFalse(planner.states['BF01']['done'])

    def test_wait_grant_precedes_private_bay_approach_and_chain_is_one_drive(self):
        planner, nav, _ = fixture()
        planner.receive_assignment('BF01', mission('m1'))
        planner.receive_assignment('BF01', mission('m2', 'OG3', 'lab'))
        self.assertEqual(planner.next_action(own(nav), 0, {})['kind'], 'request_wait')
        grants = {'waiting_place': {'status': 'granted', 'level': 'EG', 'slot': 0,
                                  'pose_mm': nav.waits['EG'][0]}}
        action = planner.next_action(own(nav), .1, grants)
        self.assertEqual(action['kind'], 'drive')
        self.assertEqual(action['terminal']['kind'], 'lift_wait')
        self.assertEqual(action['points_mm'][-1], nav.waits['EG'][0][:2])
        self.assertEqual([m['event'] for m in action['markers']], ['inspection_completed'])
        self.assertGreater(action['markers'][0]['progress_mm'], 0)
        self.assertLess(action['markers'][0]['progress_mm'], _path(action['points_mm'], 250).length)
        self.assertEqual(action['prefetch_level'], 'OG3')
        with self.assertRaises(ValueError): planner.next_action(own(nav), .2, grants)

    def test_available_successor_is_requested_before_committing_a_capacity_home_leg(self):
        planner,nav,_=fixture();planner.receive_assignment('BF01',mission('m1'))
        request=planner.next_action(own(nav),0,{})
        self.assertEqual(request['kind'],'request_mission')
        self.assertIsNone(planner.states['BF01']['active'])
        planner.on_action_result('BF01',request,{'status':'pending'},0)
        self.assertEqual(planner.next_action(own(nav,mission_pending=True),.05,{})['kind'],'hold')
        planner.receive_assignment('BF01',{**mission('m2','OG3','lab'),'source_level':'EG','booking_id':'booking-1'})
        grant={'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':nav.waits['EG'][0],'role':'start'}}
        action=planner.next_action(own(nav),.1,grant)
        self.assertEqual(action['terminal']['kind'],'lift_wait')
        self.assertEqual(action['points_mm'][-1],nav.waits['EG'][0][:2])

    def test_capacity_wait_retains_owned_bay_and_retries_without_final_completion(self):
        planner,nav,_=fixture()
        planner.receive_assignment('BF01',mission('m1'))
        grant={'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':nav.waits['EG'][0],'role':'start'}}
        request=planner.next_action(own(nav),0,grant)
        planner.on_action_result('BF01',request,{'status':'pending_admission'},0)
        action=planner.next_action(own(nav),.05,grant)
        self.assertEqual(action['terminal'],{'kind':'capacity_wait','level':'EG','slot':0})
        details=action['markers'][0]['details']
        planner.on_event('BF01','inspection_completed',details,1)
        planner.on_action_result('BF01',action,{'status':'arrived'},2)
        observed=own(nav,pose_mm_rad=nav.waits['EG'][0][:],home=False,phase='capacity_wait')
        request=planner.next_action(observed,2,grant)
        self.assertEqual(request['kind'],'request_mission')
        planner.on_action_result('BF01',request,{'status':'pending_admission'},2)
        self.assertFalse(planner.states['BF01']['requested']);self.assertFalse(planner.states['BF01']['done'])
        self.assertEqual(planner.next_action(observed,3,grant)['kind'],'request_mission')

    def test_fenced_foreign_successor_calls_from_capacity_wait_without_redundant_loop(self):
        planner,nav,_=fixture();planner.states['BF01']['terminal']={'kind':'capacity_wait','level':'EG','slot':0}
        item={**mission('m1','OG3','lab'),'source_level':'EG','booking_id':'booking-1'}
        planner.receive_assignment('BF01',item)
        observed=own(nav,pose_mm_rad=nav.waits['EG'][0][:],home=False,phase='capacity_wait')
        grant={'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':nav.waits['EG'][0],'role':'start'}}
        action=planner.next_action(observed,0,grant)
        self.assertEqual(action,{'kind':'call_lift','from_level':'EG','to_level':'OG3','mission_id':'m1','booking_id':'booking-1'})

    def test_foreign_production_assignment_requires_fenced_booking(self):
        planner,_,_=fixture()
        item={**mission('m1','OG3','lab'),'source_level':'EG','booking_id':None}
        with self.assertRaises(ValueError):planner.receive_assignment('BF01',item)

    def test_only_active_drive_marker_can_complete_own_inspection(self):
        planner, nav, _ = fixture(); planner.receive_assignment('BF01', mission('m1'))
        details = {'mission_id': 'm1', 'level': 'EG', 'area': 'room', 'basis': 'plan_label'}
        with self.assertRaises(ValueError): planner.on_event('BF01', 'inspection_completed', details, 1)
        planner.receive_assignment('BF01', mission('m2', 'OG3', 'lab'))
        grants = {'waiting_place': {'status': 'granted', 'level': 'EG', 'slot': 0, 'pose_mm': nav.waits['EG'][0]}}
        action = planner.next_action(own(nav), 0, grants)
        planner.on_event('BF01', 'inspection_completed', details, 1)
        self.assertIn('m1', planner.states['BF01']['completed'])
        with self.assertRaises(ValueError): planner.on_action_result('BF01', action, {'status': 'assumed'}, 2)
        planner.on_action_result('BF01', action, {'status': 'arrived'}, 2)

    def test_home_flag_alone_cannot_complete_wrong_pose(self):
        planner, nav, _ = fixture()
        home = {'mission_id': 'return', 'vehicle_id': 'BF01', 'assigned_s': 0.,
                'goal': {'kind': 'home', **copy.deepcopy(nav.homes['BF01'])}}
        planner.receive_assignment('BF01', home)
        self.assertEqual(planner.next_action(own(nav), 0, {})['kind'], 'complete')
        with self.assertRaises(ValueError):
            altered = copy.deepcopy(home); altered['mission_id'] = 'foreignhome'; altered['goal']['pose_mm_rad'][0] += 1
            planner.receive_assignment('BF01', altered)
        self.assertFalse(planner._home_observed(own(nav, pose_mm_rad=[1., 2., 0.])))

    def test_completion_result_cannot_forge_home_observation(self):
        planner, _, _ = fixture()
        with self.assertRaises(ValueError):
            planner.on_action_result('BF01', {'kind': 'complete', 'mission_id': 'invented'}, {'status': 'accepted'}, 1)

    def test_queued_lift_grant_waits_without_inventing_a_cabin_slot(self):
        planner, nav, _ = fixture()
        grant = {'status': 'waiting', 'start_port': 'EG.in', 'destination_port': 'OG.out'}
        result = planner._board(own(nav, home=False, phase='lift_wait'), grant)
        self.assertEqual(result['kind'], 'hold')
        self.assertIsNone(planner.states['BF01']['active'])

    def test_new_drive_cannot_spin_at_its_initial_rest_pose(self):
        planner, _, _ = fixture()
        with self.assertRaises(ValueError):
            planner._drive('BF01', 'EG', [[0., 0.], [1000., 0.]], [], [],
                           {'kind': 'lift_wait'}, initial_yaw=math.pi/2)

    def test_same_side_reverse_exit_uses_own_destination_bay_gear_stop(self):
        planner, nav, _ = fixture()
        port = copy.deepcopy(planner.ports['EG']); port.update(id='KG.in', level_id='KG')
        planner.ports['KG'] = port
        nav.waits['KG'] = copy.deepcopy(nav.waits['EG'])
        nav.level_z['KG'] = -4250.
        lane = planner.cabin_lanes_override[0]['pose_mm']
        observed = own(nav, level='KG', z_mm=-4250., aboard=True, home=False,
                       phase='aboard', pose_mm_rad=[lane[0], lane[1], math.pi])
        lift = {'status': 'assigned', 'slot': 0, 'start_port': 'EG.in', 'destination_port': 'KG.in',
                'boarding_ready': False, 'exit_ready': True}
        with self.assertRaises(ValueError):planner._alight(observed, {'lift': lift})
        action = planner._alight(observed, {'lift': lift, 'waiting_place': {
            'status': 'granted', 'level': 'KG', 'slot': 0, 'pose_mm': nav.waits['KG'][0]}})
        self.assertTrue(action['reverse'])
        self.assertEqual(action['terminal'], {'kind': 'same_side_exit_stop', 'level': 'KG', 'slot': 0})
        self.assertEqual(action['points_mm'][-1], nav.waits['KG'][0][:2])
        self.assertEqual(action['markers'][0]['event'], 'lift_exited')
        self.assertEqual(action['port_id'], 'KG.in')
        self.assertAlmostEqual(_path(action['points_mm'], 250).evaluate(0)[0][2], 0.)

    def test_cabin_lane_clearance_matches_perception_and_ports_are_ready(self):
        planner, nav, _ = fixture()
        self.assertGreater(planner.passing_gap_mm, 175)
        self.assertEqual(len(planner.cabin_lanes_override), 2)
        grant = {'status': 'assigned', 'slot': 0, 'start_port': 'EG.in', 'destination_port': 'OG.out',
                 'cabin_pose_mm': planner.cabin_lanes_override[0]['pose_mm'],
                 'boarding_ready': False, 'exit_ready': False}
        at_wait = own(nav, pose_mm_rad=nav.waits['EG'][0], home=False, phase='lift_wait')
        self.assertEqual(planner._board(at_wait, grant)['kind'], 'hold')
        grant['boarding_ready'] = True
        action = planner._board(at_wait, grant)
        self.assertTrue(action['allow_lift']); self.assertEqual(action['lift_phase']['kind'], 'boarding')
        self.assertFalse(action['reverse']); self.assertEqual(action['terminal']['kind'], 'cabin_park')
        start_yaw = _path(action['points_mm'], 250).evaluate(0)[0][2]
        self.assertAlmostEqual(abs(start_yaw), math.pi)


if __name__ == '__main__': unittest.main()
