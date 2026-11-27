"""Bounded policy and adapter checks; no native fleet qualification claimed."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_patrol import PatrolDispatcher, PatrolWorldRunner, PatrolStorageLimit


def source():
    return {'missions': {'seed': 20261120, 'minimum_duration_s': 600,
                        'maximum_duration_s': 7200,
                        'targets': [{'level': 'EG', 'area': area, 'weight': 1,
                                     'minimum_visits': 1, 'kind': 'inspection_pass',
                                     'basis': 'test_fixture'} for area in ('A', 'B', 'C')]},
            'motion': {'empty_linear_limits': {'velocity_mm_s': 1000,
                                              'acceleration_mm_s2': 500,
                                              'jerk_mm_s3': 1000},
                       'zone_velocity_mm_s': 300}}


def dispatcher():
    return PatrolDispatcher(source(), {'BF01': {'level': 'EG'}, 'BF02': {'level': 'EG'}})


class PatrolDispatchTests(unittest.TestCase):
    def test_patrol_retains_source_and_never_returns_automatically(self):
        config = source()
        before = copy.deepcopy(config)
        d = PatrolDispatcher(config, {'BF01': {'level': 'EG'}})
        d.last_visit.update({('EG', 'A'): 30., ('EG', 'B'): 10., ('EG', 'C'): 20.})
        mission = d.assign('BF01', 'EG', 7201.)
        self.assertEqual(mission['goal']['area'], 'B')
        self.assertFalse(d.ready_to_return(999999.))
        self.assertEqual(config, before)

    def test_only_received_acknowledged_completion_refreshes_coverage(self):
        d = dispatcher()
        mission = d.assign('BF01', 'EG', 0.)
        self.assertTrue(all(row['last_visit_s'] is None for row in d.coverage()))
        with self.assertRaises(ValueError):
            d.receive_completion('BF01', mission['mission_id'])
        d.clock_s = 5.
        d.acknowledge('BF01', mission['mission_id'])
        d.receive_completion('BF01', mission['mission_id'])
        d.clock_s = 100.
        self.assertFalse(d.receive_completion('BF01', mission['mission_id']))
        key = ('EG', mission['goal']['area'])
        self.assertEqual(d.last_visit[key], 5.)

    def test_request_identity_and_single_vehicle_reservation_are_idempotent(self):
        d = dispatcher()
        job = d.request_job(('EG', 'A'), ('EG', 'B'), 'process-1', 0.)
        self.assertEqual(job['status'], 'queued')
        d.recruit('process-1', [{'vehicle_id': 'BF01', 'eta_s': 40.},
                                {'vehicle_id': 'BF02', 'eta_s': 5.}], 1.)
        d.recruit('process-1', [{'vehicle_id': 'BF01', 'eta_s': 0.}], 2.)
        repeated = d.request_job({'level': 'EG', 'area': 'A'},
                                 {'level': 'EG', 'area': 'B'}, 'process-1', 99.)
        self.assertEqual(repeated['vehicle_id'], 'BF02')
        self.assertEqual(repeated['created_s'], 0.)
        self.assertEqual(len(d.jobs), 1)
        with self.assertRaises(ValueError):
            d.request_job(('EG', 'A'), ('EG', 'C'), 'process-1', 100.)
        d.request_job(('EG', 'B'), ('EG', 'C'), 'process-2', 2.)
        next_job = d.recruit('process-2', [{'vehicle_id': 'BF02', 'eta_s': 1.},
                                          {'vehicle_id': 'BF01', 'eta_s': 2.}], 2.)
        self.assertEqual(next_job['vehicle_id'], 'BF01')

    def test_jobs_yield_no_extra_patrol_until_received_delivery_then_rejoin(self):
        d = dispatcher()
        d.request_job(('EG', 'A'), ('EG', 'B'), 'p', 0.)
        self.assertIsNone(d.assign('BF01', 'EG', 0.))
        d.recruit('p', [{'vehicle_id': 'BF01', 'eta_s': 5.}], 0.)
        pickup = d.assign('BF01', 'EG', 1.)
        delivery = d.assign('BF01', 'EG', 2.)
        self.assertEqual(pickup['goal']['area'], 'A')
        self.assertEqual(delivery['goal']['area'], 'B')
        self.assertIsNone(d.assign('BF01', 'EG', 3.))
        d.clock_s = 4.
        d.acknowledge('BF01', pickup['mission_id'])
        d.acknowledge('BF01', delivery['mission_id'])
        with self.assertRaises(ValueError):
            d.receive_completion('BF01', delivery['mission_id'])
        self.assertNotIn(delivery['mission_id'], d.completed)
        d.receive_completion('BF01', pickup['mission_id'])
        self.assertEqual(d.jobs['p']['status'], 'pickup_observed')
        d.clock_s = 5.
        d.receive_completion('BF01', delivery['mission_id'])
        self.assertEqual(d.jobs['p']['status'], 'completed')
        self.assertNotIn('BF01', d.vehicle_jobs)
        self.assertFalse(d.receive_completion('BF01', delivery['mission_id']))
        self.assertEqual(d.jobs['p']['completed_s'], 5.)
        self.assertEqual(d.assign('BF01', 'EG', 6.)['goal']['kind'], 'inspection_pass')

    def test_foreign_job_cannot_issue_without_its_own_endpoint_fence(self):
        config = source()
        config['missions']['targets'][1]['level'] = 'OG3'
        d = PatrolDispatcher(config, {'BF01': {'level': 'EG'}})
        d.request_job(('OG3', 'B'), ('EG', 'A'), 'p', 0.)
        d.recruit('p', [{'vehicle_id': 'BF01', 'eta_s': 5.}], 0.)
        self.assertIsNone(d.assign('BF01', 'EG', 1., admissible_levels={'EG'},
                                   book_goal=lambda *args: self.fail('Must not book excluded floor')))
        self.assertIsNone(d.assign('BF01', 'EG', 1., admissible_levels={'OG3'},
                                   book_goal=lambda *args: None))
        self.assertEqual(d.counter, 0)
        mission = d.assign('BF01', 'EG', 1., admissible_levels={'OG3'},
                           book_goal=lambda mid, goal: {'booking_id': 'own-fence'})
        self.assertEqual(mission['booking_id'], 'own-fence')
        self.assertEqual(d.jobs['p']['pickup_mission_id'], mission['mission_id'])


class LiveAdapterTests(unittest.TestCase):
    def runner(self):
        r = object.__new__(PatrolWorldRunner)
        r.source = source()
        r.dispatcher = dispatcher()
        r.vehicles = {identity: {'driver': None, 'aboard': False,
            'mission_pending': False, 'phase': 'home', 'pose_mm_rad': [x, 0, 0],
            'z_mm': 0, 'level': 'EG', 'episodes': [], 'capture_seq': 0}
            for identity, x in (('BF01', 100), ('BF02', 1000))}
        r.planner = SimpleNamespace(states={identity: {'active': None,
            'completed': set(), 'queue': [], 'terminal': None} for identity in r.vehicles},
            variants={('EG', 'A'): [[[2000, 0], [2100, 0]]]}, trim_mm=10.)
        r.resources = SimpleNamespace(active_bookings={}, next_bookings={})
        r.lift = SimpleNamespace(own_grant=lambda identity: {'status': 'none'})
        r.nav = SimpleNamespace(inspections={('EG', 'A'): {}},
                                 homes={identity: {'departure_xy_mm': [x, 0]}
                                        for identity, x in (('BF01', 100), ('BF02', 1000))})
        r.own = lambda identity: {'home': False, 'level': 'EG',
                                  'pose_mm_rad': r.vehicles[identity]['pose_mm_rad']}
        r.paused = False
        r.now = 0.
        r.step_index = 0
        r.dt = .05
        r.control_room = SimpleNamespace(messages=[])
        r._deferred_patrol = {}
        r._startup_ready = True
        r._camera_frames = {}
        return r

    def test_open_lift_corridor_is_retained_only_for_the_booked_owner(self):
        r = self.runner()
        r.dt = .4
        r.source = {'depot': {'level': 'EG'}}
        r.lift.requests = {}
        lift = {'phase':'idle', 'level':'EG', 'doors_open':True, 'door_open_fraction':1.}
        r.lift_snapshot = lambda: lift
        grant = {'status':'granted', 'level':'EG', 'slot':0, 'booking_id':'booking-1'}
        r.resources.holds = {'BF01':'corridor'}
        r.resources.own_waiting_grants = lambda identity: {'start':grant}
        r.vehicles['BF01']['action'] = {'terminal':{'kind':'lift_wait', 'slot':0,
                                                    'booking_id':'booking-1'}}
        self.assertTrue(r.keeps_cabin_corridor('BF01','corridor'))
        self.assertFalse(r.keeps_cabin_corridor('BF02','corridor'))
        lift['door_open_fraction'] = .8
        self.assertFalse(r.keeps_cabin_corridor('BF01','corridor'))
        lift['door_open_fraction'] = 1.
        r.departures = SimpleNamespace(keeps_corridor=lambda *_:True)
        self.assertFalse(r.keeps_cabin_corridor('BF01','corridor'))

    def test_six_vehicle_timing_uses_short_steps_for_lift_activity(self):
        r = self.runner()
        r.source = {'depot': {'level': 'EG'}}
        r.dt = .4
        r.lift.phase = 'idle'
        r.lift.requests = {}
        for row in r.vehicles.values():
            row['action'] = None
        r._remember_lift_phase = lambda: None
        intervals = []

        def advance(end):
            intervals.append(round(end-r.now,3))
            r.now = end

        r.advance_world = advance
        r._step_once = r._advance_tick
        self.assertEqual(r.step(), .4)
        self.assertEqual(intervals, [.4])
        r.lift.requests['BF01'] = {}
        self.assertEqual(r.step(), .8)
        self.assertEqual(intervals[1:], [.05]*8)
        r.lift.requests.clear()
        r.vehicles['BF01']['level'] = 'OG1'
        self.assertEqual(r.step(), 1.2)
        self.assertEqual(intervals[9:], [.05]*8)
        r.vehicles['BF01']['level'] = 'EG'
        self.assertEqual(r.step(), 1.6)
        self.assertEqual(intervals[-1], .4)

    def test_bid_uses_actual_map_route_instead_of_euclidean_distance(self):
        r = self.runner()
        def route(level, start, end):
            # BF01 is closer in a straight line, but must follow a long detour.
            points = ([start, [100, 10000], [2000, 10000], end]
                      if start[0] == 100 else [start, end])
            return {'points_mm': points}
        r.graph = SimpleNamespace(route=route)
        bids = [r.own_bid(identity, ('EG', 'A')) for identity in r.vehicles]
        self.assertTrue(all(bid is not None for bid in bids))
        self.assertGreater(bids[0]['eta_s'], bids[1]['eta_s'])
        r.request_job(('EG', 'A'), ('EG', 'B'), 'process')
        r.recruit_pending()
        self.assertEqual(r.dispatcher.jobs['process']['vehicle_id'], 'BF02')

    def test_snapshot_distinguishes_planning_horizon_from_depot_queue(self):
        from building_fleet_services import ResourceServices
        r = self.runner()
        r.resources = ResourceServices({'depot': 'room'})
        r.resources.request('BF02', 'depot', 0.)
        r.resources.request('BF01', 'depot', .05)
        r.vehicles['BF01'].update(hold_reason='resource_wait', hold_condition='own_depot_departure_grant')
        driver = SimpleNamespace(mode='waiting', reason='await_checked_continuation', y=800., goal=1500.,
                                 certified_horizon_mm=800., awaiting_continuation=True)
        r.vehicles['BF02'].update(driver=driver, phase='driving')
        waiting, stopped = r._states()
        self.assertEqual((waiting['requested_resource'], waiting['queue_position'], waiting['resource_holder']),
                         ('depot', 1, 'BF02'))
        self.assertEqual(waiting['hold_condition'], 'own_depot_departure_grant')
        self.assertEqual((stopped['mode'], stopped['controller_mode'], stopped['hold_reason']),
                         ('driving', 'waiting', 'await_checked_continuation'))
        self.assertEqual((stopped['progress_mm'], stopped['own_route_horizon_mm'], stopped['goal_mm']),
                         (800., 800., 1500.))
        driver.mode = 'driving'
        self.assertIsNone(r._states()[1]['hold_reason'])
        self.assertNotIn('resource_holder', r._states(diagnostics=False)[0])

    def test_driving_aboard_pending_and_foreign_booked_vehicles_are_ineligible(self):
        r = self.runner()
        self.assertTrue(r.eligible('BF01'))
        for field, value in (('driver', object()), ('aboard', True), ('mission_pending', True)):
            old = r.vehicles['BF01'][field]
            r.vehicles['BF01'][field] = value
            self.assertFalse(r.eligible('BF01'))
            r.vehicles['BF01'][field] = old
        r.resources.active_bookings['BF01'] = 'foreign-mission'
        self.assertFalse(r.eligible('BF01'))
        r.resources.active_bookings.clear()
        r.planner.states['BF01']['queue'] = [{'mission_id': 'uncompleted',
            'goal': {'kind': 'inspection_pass', 'level': 'OG3'}}]
        self.assertFalse(r.eligible('BF01'))
        r.planner.states['BF01']['completed'].add('uncompleted')
        self.assertTrue(r.eligible('BF01'))

    def test_received_unstarted_local_patrol_is_deferred_then_resumed_identically(self):
        r = self.runner()
        old = r.dispatcher.assign('BF01', 'EG', 0.)
        r.dispatcher.acknowledge('BF01', old['mission_id'])
        state = r.planner.states['BF01']
        state['queue'] = [copy.deepcopy(old)]
        state['seen'] = {old['mission_id']: copy.deepcopy(old)}
        r.request_job(('EG', 'A'), ('EG', 'B'), 'process-after-patrol')
        r.own_bid = lambda identity, pickup: ({'vehicle_id': identity, 'eta_s': 1.}
                                             if identity == 'BF01' else None)
        self.assertTrue(r.eligible('BF01'))
        r.recruit_pending()
        self.assertEqual(state['queue'], [])
        self.assertEqual(r._deferred_patrol['BF01'], [old])
        self.assertEqual(state['seen'][old['mission_id']], old)
        self.assertIn(old['mission_id'], r.dispatcher.acks)
        self.assertEqual(r.dispatcher.missions[old['mission_id']], old)
        for stage in ('pickup', 'delivery'):
            mission = r.dispatcher.assign('BF01', 'EG', 1.)
            r.dispatcher.acknowledge('BF01', mission['mission_id'])
            r.dispatcher.receive_completion('BF01', mission['mission_id'])
        r._restore_local_patrol()
        self.assertEqual(state['queue'], [old])
        self.assertIn(old['mission_id'], r.dispatcher.acks)
        self.assertNotIn(old['mission_id'], r.dispatcher.completed)
        self.assertEqual(len(r.dispatcher.missions), 3)

    def test_startup_waits_once_for_twenty_actual_received_frames(self):
        r = self.runner()
        r._startup_ready = False
        template = copy.deepcopy(r.vehicles['BF01'])
        r.vehicles = {'BF%02d' % i: copy.deepcopy(template) for i in range(1, 21)}
        r._camera_frames = {identity: {} for identity in list(r.vehicles)[:-1]}
        r.deliver_messages = lambda now: None
        calls = []
        r.recruit_pending = lambda: calls.append('recruit')
        r.idle_action = lambda identity: calls.append(identity)
        r.observe = lambda step: calls.append('observe')
        r.advance_world = lambda end: setattr(r, 'now', end)
        r.step()
        self.assertEqual(calls, ['observe'])
        self.assertFalse(r._startup_ready)
        self.assertEqual(r.now, .05)
        # The last delivered frame releases this once-only readiness gate.
        r._camera_frames = {identity: {} for identity in r.vehicles}
        calls.clear()
        r.step()
        self.assertTrue(r._startup_ready)
        self.assertEqual(calls, ['recruit', *r.vehicles, 'observe'])
        r._camera_frames.clear()
        calls.clear()
        r.step()
        self.assertEqual(calls, ['recruit', *r.vehicles, 'observe'])

    def test_independent_startup_releases_only_own_received_vehicle(self):
        r=self.runner();r.profile={'patrol':{'startup':'own_received_camera_frame'}}
        r._startup_ready=False;r._startup_seen_frames=set();r._camera_frames={'BF02':{}}
        r.deliver_messages=lambda now:None
        calls=[];r.recruit_pending=lambda:calls.append('recruit')
        r.idle_action=lambda identity:calls.append(identity)
        r.observe=lambda step:calls.append('observe');r.advance_world=lambda end:setattr(r,'now',end)
        self.assertFalse(r.eligible('BF01'));self.assertTrue(r.eligible('BF02'))
        r.step();self.assertEqual(calls,['recruit','BF02','observe']);self.assertFalse(r._startup_ready)
        r._camera_frames['BF01']={};calls.clear();r.step()
        self.assertTrue(r._startup_ready);self.assertEqual(calls,['recruit','BF01','BF02','observe'])
        # Later radio blackout does not restart the once-only readiness gate.
        r._camera_frames.clear();calls.clear();r.step()
        self.assertEqual(calls,['recruit','BF01','BF02','observe'])

    def test_unreceived_vehicle_cannot_request_a_mission_or_enter_idle_planning(self):
        r=self.runner();r.profile={'patrol':{'startup':'own_received_camera_frame'}}
        with patch('building_fleet_patrol.WorldRunner.request_mission',return_value={'status':'pending'})as mission:
            with patch('building_fleet_patrol.WorldRunner.idle_action')as idle:
                self.assertEqual(r.request_mission('BF01','EG',0.)['status'],'pending_own_camera')
                r.idle_action('BF01');mission.assert_not_called();idle.assert_not_called()
                self.assertEqual(r.vehicles['BF01']['hold_condition'],'first_actual_own_perception_delivery')
                r._camera_frames['BF01']={}
                r.request_mission('BF01','EG',0.);r.idle_action('BF01')
                mission.assert_called_once_with('BF01','EG',0.);idle.assert_called_once_with('BF01')

    def test_cross_floor_process_returns_with_new_fence_before_restoring_local_intent(self):
        r = self.runner()
        original = r.dispatcher.assign('BF01', 'EG', 0., admissible_levels={'EG'},
                                       book_goal=lambda *args: None)
        r.dispatcher.acknowledge('BF01', original['mission_id'])
        r._deferred_patrol['BF01'] = [copy.deepcopy(original)]
        r.vehicles['BF01']['level'] = 'OG3'
        r._restore_local_patrol()
        self.assertEqual(r.planner.states['BF01']['queue'], [])
        self.assertEqual(r.dispatcher.missions[original['mission_id']], original)
        self.assertIsNone(original['booking_id'])
        returned = r.dispatcher.assign('BF01', 'OG3', 10., admissible_levels={'EG'},
            book_goal=lambda mid, goal: {'booking_id': 'new-return-fence'})
        self.assertNotEqual(returned['mission_id'], original['mission_id'])
        self.assertEqual(returned['source_level'], 'OG3')
        self.assertEqual(returned['booking_id'], 'new-return-fence')
        r.vehicles['BF01']['level'] = 'EG'
        r._restore_local_patrol()
        self.assertEqual(r.planner.states['BF01']['queue'], [original])
        self.assertIn(original['mission_id'], r.dispatcher.acks)
        self.assertNotIn('BF01', r.dispatcher.resume_targets)

    def test_denied_home_departure_token_defers_curve_preparation(self):
        r = self.runner()
        r.planner.states['BF01']['queue'] = [{'mission_id': 'local'}]
        r.nav.homes['BF01'].update(level='EG', area='Depot')
        r.depot_aliases = {('EG', 'Depot'): 'source-depot-resource'}
        r.own = lambda identity: {'home': True}
        requested = []
        r.resources.request = lambda identity, resource, now: (
            requested.append((identity, resource, now)) or {'status': 'waiting'})
        r.drain_resource_events = lambda: None
        with patch('building_fleet_patrol.WorldRunner.idle_action') as base:
            r.idle_action('BF01')
            base.assert_not_called()
        self.assertEqual(requested, [('BF01', 'source-depot-resource', 0.)])
        self.assertEqual(r.vehicles['BF01']['hold_condition'], 'own_depot_departure_grant')
        r.own = lambda identity: {'home': False}
        with patch('building_fleet_patrol.WorldRunner.idle_action') as base:
            r.idle_action('BF01')
            base.assert_called_once_with('BF01')

    def test_exact_base_loop_order_and_pause_do_not_advance_model_time(self):
        r = self.runner()
        calls = []
        r.deliver_messages = lambda at: calls.append(('deliver', at))
        r.recruit_pending = lambda: calls.append(('recruit', r.now))
        r.idle_action = lambda identity: calls.append(('idle', identity))
        r.observe = lambda step: calls.append(('observe', step))
        def advance(end):
            calls.append(('advance', end))
            r.now = end
        r.advance_world = advance
        self.assertEqual(r.step(), .05)
        self.assertEqual(calls, [('deliver', 0.), ('recruit', 0.), ('idle', 'BF01'),
                                 ('idle', 'BF02'), ('observe', 0), ('advance', .05)])
        r.set_paused(True)
        self.assertEqual(r.step(), .05)
        self.assertEqual(len(calls), 6)

    def test_storage_failure_is_visible_and_preserves_controller_records(self):
        r = self.runner()
        r.control_room.messages = [None]*3
        with patch('building_fleet_patrol._MAX_MESSAGES', 3):
            with self.assertRaises(PatrolStorageLimit):
                r.step()
        self.assertEqual(r.control_room.messages, [None]*3)
        self.assertEqual(r.now, 0.)

    def test_received_camera_retains_original_peers_and_lift_through_blackout(self):
        r = self.runner()
        r.sensor = {'stale_after_s': .5, 'latency_s': .1}
        r._scene_history = {}
        r._capture_scenes = {}
        r._camera_frames = {}
        r.camera_captures = {}
        r._lift_state = lambda: {'z_mm': 0., 'door_values': {'door': 1.}}
        def capture(world, step):
            world.vehicles['BF01']['capture_seq'] = 1
            world.camera_captures['BF01-camera-1'] = {'captured_s': 0.,
                'pose_xyz_mm': [100, 0, 0], 'yaw_rad': 0., 'level_id': 'EG'}
        with patch('building_fleet_patrol.WorldRunner.observe', capture):
            r.observe(0)
        message = {'kind': 'perception', 'vehicle_id': 'BF01',
                   'received_s': 10., 'payload': {'camera_ref': 'BF01-camera-1'}}
        r.uplink = SimpleNamespace(pending=[], buffer={'BF01': [message]})
        r.vehicles['BF02']['pose_mm_rad'][0] = 9000
        r._lift_state = lambda: {'z_mm': 4000., 'door_values': {'door': 0.}}
        with patch('building_fleet_patrol.WorldRunner.deliver_messages', lambda *args: None):
            r.deliver_messages(5.)
        self.assertIn('BF01-camera-1', r._capture_scenes)
        self.assertFalse(r._camera_frames)
        r.uplink.buffer.clear()
        def deliver(world, now):
            world.control_room.messages.append(message)
        with patch('building_fleet_patrol.WorldRunner.deliver_messages', deliver):
            r.deliver_messages(10.)
        frame = r._camera_frames['BF01']
        self.assertEqual(frame['captured_s'], 0.)
        self.assertEqual(frame['received_s'], 10.)
        self.assertEqual(frame['states'][1]['pose_xyz_mm'][0], 1000)
        self.assertEqual(frame['lift']['z_mm'], 0.)
        self.assertEqual(frame['lift']['door_values']['door'], 1.)

    def test_executed_window_reuses_exact_knots_without_prediction(self):
        r = self.runner()
        r.now = 1.05
        r.nav.level_z = {'EG': 0.}
        r._lift_discontinuity_s = -float('inf')
        r._scene_history = {.05: {'lift': {'z_mm': 0., 'door_values': {'door': 1.}}}}
        r._live_lift_rows = {}
        points = [{'time_s': round(i*.05, 3), 'pose_mm_rad': [i*.5, 0., 0.],
                   'velocity_mm_rad_s': [10., 0., 0.],
                   'acceleration_mm_rad_s2': [0., 0., 0.]} for i in range(22)]
        for vehicle in r.vehicles.values():
            vehicle['episodes'] = [{'mode': 'driving', 'level_id': 'EG',
                'attached_cabin': False, 'start_s': 0., 'end_s': 1.05, 'points': points}]
        window = r.executed_window()
        self.assertEqual((window['start_s'], window['end_s']), (.05, 1.05))
        for trajectory in window['trajectories']:
            exported = trajectory['episodes'][0]['points']
            self.assertEqual(exported, points[1:])
            self.assertLessEqual(exported[-1]['time_s'], r.now)
        window['trajectories'][0]['episodes'][0]['points'][0]['pose_mm_rad'][0] = 999
        self.assertEqual(points[1]['pose_mm_rad'][0], .5)
        r._lift_discontinuity_s = .5
        self.assertIsNone(r.executed_window())

    def test_window_lift_rows_keep_original_quintic_door_endpoints(self):
        r = self.runner()
        r.now = .5
        r._live_lift_rows = {}
        r.lift = SimpleNamespace(phase='closing_passengers', phase_started=.1,
            door_duration=2., level='EG', ports={'P': {'level_id': 'EG', 'door_object_ids': ['door']}})
        r.nav.mesh = SimpleNamespace(manifest={'objects': [{'id': 'door',
            'mechanism': 'lift_door', 'states': {'open': 900., 'closed': 0.}}]})
        r._remember_lift_phase()
        row = next(iter(r._live_lift_rows.values()))
        self.assertEqual(row['start_s'], .1)
        self.assertEqual(row['end_s'], 2.1)
        self.assertEqual(row['from_values'], {'door': 900.})
        self.assertEqual(row['target_values'], {'door': 0.})


if __name__ == '__main__':
    unittest.main()
