"""Live selection changes occupants, never the reference map or its proof scope."""
import copy
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_browser_runtime as browser
import building_fleet_model as model
from building_fleet_patrol import PatrolWorldRunner
from building_fleet_runtime_cache import bind_active_fleet
from building_fleet_services import cabin_lanes
import run_building_fleet_patrol as local


def prepared_map(source):
    """Small scan-only fixture; no native or motion qualification is asserted."""
    envelope = {'length_mm': 512, 'width_mm': 412, 'height_mm': 700,
                'radius_mm': math.hypot(256, 206)}
    homes = {'BF%02d' % i: {'level': 'EG', 'area': 'R0_004' if i <= 10 else 'R0_013',
        'slot': i - 1, 'pose_mm_rad': [3000. * i, 0. if i <= 10 else 20000., 0.],
        'departure_xy_mm': [3000. * i + 1000., 0. if i <= 10 else 20000.],
        'arrival_xy_mm': [3000. * i - 1000., 0. if i <= 10 else 20000.]}
        for i in range(1, 21)}
    port = {'id': 'EG-inward', 'level_id': 'EG', 'z_mm': 0., 'active': True,
            'side': 'inward', 'plane_x_mm': -50000., 'door_object_ids': []}
    interior = {'min': [0., 0., 0.], 'max': [2000., 2000., 2200.]}
    elevator = {'object_id': 'Lift', 'ports': [port], 'speed_mm_s': 1000.,
                'reference_level': 'EG', 'reference_z_mm': 0.,
                'cabin_bounds_mm': interior}
    nav = SimpleNamespace(config=source, homes=homes, envelope=envelope,
        radius=envelope['radius_mm'], height=720., reserve=85., navigation_margin_mm=1.,
        level_z={'EG': 0.}, waits={'EG': [[-10000., 0., 0.], [-10000., 1000., 0.]]},
        cabin_interior_mm=interior, mesh=SimpleNamespace(manifest={
            'elevator': elevator, 'objects': []}),
        polygons={'EG': {'R0_004': [[0., -2000.], [33000., -2000.],
                    [33000., 2000.], [0., 2000.]],
            'R0_013': [[30000., 18000.], [64000., 18000.],
                    [64000., 22000.], [30000., 22000.]]}})
    graph = SimpleNamespace(navigation=nav, sealed=True, centreline={'fixture': 'unchanged'})
    aliases = {('EG', 'R0_004'): 'A', ('EG', 'R0_013'): 'B'}
    catalog = SimpleNamespace(nav=nav, room_alias=aliases, canonical={'A': 'A', 'B': 'B'},
                              resources={'A': 'room', 'B': 'room'})
    states = {identity: {'queue': [], 'seen': {}, 'completed': set(), 'active': None,
        'terminal': None, 'done': False, 'requested': False, 'admission_deferred': False,
        'home_confirmation': None} for identity in homes}
    planner = SimpleNamespace(source=source, nav=nav, graph=graph, states=states,
        port_paths=SimpleNamespace(nav=nav),
        cabin_lanes_override=cabin_lanes(interior, [512, 412], 250., maximum=2))
    class Geometry:
        def __init__(self):
            self.nav = nav
        def __call__(self, *_):
            return {'passed': True, 'scope': 'fixture only'}
    return {'nav': nav, 'graph': graph, 'catalog': catalog,
            'planner': planner, 'geometry_checks': Geometry()}


class ActiveFleetTests(unittest.TestCase):
    def setUp(self):
        self.source = model.load()
        self.profile = local.load_profile()

    def untimed_profile(self):
        profile = copy.deepcopy(self.profile)
        profile.pop('timing')
        for route in ('ground_boarding', 'ground_boarding_alternate', 'basement_alighting',
                      'basement_departure', 'basement_return'):
            profile['patrol'].pop(route, None)
        return profile

    def test_source_is_still_twenty_and_current_profile_explicitly_selects_six(self):
        self.assertEqual((self.source['fleet']['count'], self.source['depot']['slots']), (20, 20))
        self.assertEqual(self.profile['vehicle_count'], 6)
        self.assertEqual(model.active_vehicle_ids(self.source, self.profile),
                         tuple('BF%02d' % i for i in range(1, 7)))
        legacy = self.untimed_profile()
        legacy.pop('vehicle_count')
        with patch.object(local.model, 'read_json', return_value=legacy):
            self.assertEqual(local.load_profile(), legacy)
        expected = tuple('BF%02d' % i for i in range(1, 21))
        self.assertEqual(model.active_vehicle_ids(self.source, legacy), expected)
        explicit = {**legacy, 'vehicle_count': 20}
        self.assertEqual(model.active_vehicle_ids(self.source, explicit), expected)

    def test_bad_counts_fail_in_both_normal_profile_validators(self):
        for count in (True, 6., None, 0, 1, 5, 7, 21, '6'):
            with self.subTest(count=count):
                value = {**self.profile, 'vehicle_count': count}
                with self.assertRaises(ValueError):
                    model.active_vehicle_ids(self.source, value)
                with patch.object(local.model, 'read_json', return_value=value):
                    with self.assertRaises(ValueError):
                        local.load_profile()

    def test_active_adapter_preserves_static_geometry_and_original_home_bytes(self):
        original = prepared_map(self.source)
        before = copy.deepcopy(original['nav'].homes)
        active = bind_active_fleet(original, self.source, self.profile)
        expected = set(model.active_vehicle_ids(self.source, self.profile))
        self.assertEqual(set(active['nav'].homes), expected)
        self.assertEqual(set(active['planner'].states), expected)
        for identity in expected:
            self.assertEqual(json.dumps(active['nav'].homes[identity]), json.dumps(before[identity]))
        self.assertEqual(original['nav'].homes, before)
        self.assertEqual(len(original['planner'].states), 20)
        self.assertIs(active['nav'].config, self.source)
        self.assertIs(active['nav'].mesh, original['nav'].mesh)
        self.assertIs(active['nav'].polygons, original['nav'].polygons)
        self.assertIs(active['graph'].centreline, original['graph'].centreline)
        self.assertIs(active['graph'].navigation, active['nav'])
        self.assertIs(active['catalog'].nav, active['nav'])
        self.assertIs(active['planner'].nav, active['nav'])
        self.assertIs(active['planner'].port_paths.nav, active['nav'])
        self.assertIs(active['geometry_checks'].nav, active['nav'])
        active['nav'].homes['BF01']['pose_mm_rad'][0] = -1
        self.assertEqual(original['nav'].homes, before)

    def test_explicit_and_legacy_twenty_use_original_context_without_new_assumptions(self):
        original = prepared_map(self.source)
        # A historical state remains untouched; this selection is not a restart.
        original['planner'].states['BF20']['active'] = {'mission_id': 'existing'}
        for count in (None, 20):
            profile = self.untimed_profile()
            if count is None:
                profile.pop('vehicle_count')
            else:
                profile['vehicle_count'] = count
            self.assertIs(bind_active_fleet(original, self.source, profile), original)

    def test_six_cannot_hide_missing_homes_or_drop_an_existing_commitment(self):
        for mutate in (lambda p: p['nav'].homes.pop('BF20'),
                       lambda p: p['planner'].states['BF20'].update(requested=True),
                       lambda p: p['planner'].states['BF07']['queue'].append({'mission_id': 'old'})):
            original = prepared_map(self.source)
            mutate(original)
            with self.assertRaises(ValueError):
                bind_active_fleet(original, self.source, self.profile)

    def test_real_world_scan_loop_contains_only_active_occupants_and_received_cameras(self):
        for count in (6, 20):
            with self.subTest(count=count):
                prepared = prepared_map(self.source)
                profile = self.profile if count == 6 else {**self.untimed_profile(), 'vehicle_count': 20}
                engine = PatrolWorldRunner(self.source, prepared['nav'], prepared['graph'],
                    prepared['catalog'], prepared['planner'], profile,
                    geometry_checker=prepared['geometry_checks'],
                    scan_geometry=({'EG': []}, {(): [], ('inward',): []},
                                   {('EG', ()): [], ('EG', ('inward',)): []}),
                    zone_regions={'EG': []})
                expected = set(model.active_vehicle_ids(self.source, profile))
                self.assertEqual(set(engine.vehicles), expected)
                self.assertEqual(set(engine.truth()), expected)
                self.assertEqual(set(engine.dispatcher.homes), expected)
                self.assertEqual(set(engine.depot_maps), expected)
                self.assertEqual(set(engine.planner.states), expected)
                self.assertEqual(set(engine.geometry_checker.nav.homes), expected)
                self.assertEqual(len(prepared['nav'].homes), 20)
                home_map = engine.depot_maps['BF01']
                home_map.set_own_grant({'status': 'granted', 'resource': 'A'})
                # An inactive source slot is available space, not a known
                # occupied surface that may hide an anonymous return.
                origin = prepared['nav'].homes['BF01']['pose_mm_rad']
                at = prepared['nav'].homes['BF07']['pose_mm_rad'][0] - 256.
                self.assertEqual(home_map.matches(origin, [0., at - origin[0]]), count == 20)
                # No mission or native geometry is mocked as qualified. The
                # actual scanner, observation latency, radio and camera scenes
                # still run, while assignments are held outside this fixture.
                engine.idle_action = lambda identity: None
                for _ in range(23):
                    engine.step()
                snapshot = engine.snapshot()
                self.assertEqual(snapshot['vehicle_count'], count)
                self.assertEqual({s['id'] for s in snapshot['states']}, expected)
                self.assertEqual({f['vehicle_id'] for f in snapshot['camera_frames']}, expected)
                self.assertTrue(snapshot['startup_ready'])
                scans_per_vehicle = 23*4 if count==6 else len(range(0,23,engine.scan_step))
                self.assertEqual(engine.world.scans, count*scans_per_vehicle)
                for frame in snapshot['camera_frames']:
                    self.assertEqual({s['id'] for s in frame['states']}, expected)
                self.assertEqual({t['vehicle_id'] for t in snapshot['executed_window']['trajectories']}, expected)
                self.assertEqual({m['vehicle_id'] for m in engine.control_room.messages}, expected)

    def test_background_worker_refuses_inactive_requests_before_any_route_computation(self):
        context = bind_active_fleet(prepared_map(self.source), self.source, self.profile)
        context.update(source=self.source, source_binding='current-source')
        old = browser._planner_context
        browser._planner_context = context
        self.addCleanup(setattr, browser, '_planner_context', old)
        for kind in ('full_route', 'continuation', 'route_interval'):
            request = {'kind': kind, 'vehicle_id': 'BF07',
                       'source_binding': 'current-source'}
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, 'inactive vehicle'):
                    browser.prepare_job(json.dumps(request))

    def test_browser_planner_uses_the_same_active_map_as_the_world(self):
        prepared = prepared_map(self.source)
        config = {'fixture': 'same-profile'}
        old = browser._planner_context
        browser._planner_context = None
        self.addCleanup(setattr, browser, '_planner_context', old)
        with patch.object(browser, '_configuration', return_value=(
                {'static_runtime_cache': 'fixture-cache'}, self.source, self.profile, {})), \
                patch('building_fleet_runtime_cache.restore', return_value=prepared):
            ready = json.loads(browser.boot_planner(json.dumps(config)))
        self.assertEqual(ready, {'status': 'ready', 'vehicle_count': 6})
        self.assertEqual(set(browser._planner_context['nav'].homes),
                         set(model.active_vehicle_ids(self.source, self.profile)))
        self.assertEqual(len(prepared['nav'].homes), 20)


if __name__ == '__main__':
    unittest.main()
