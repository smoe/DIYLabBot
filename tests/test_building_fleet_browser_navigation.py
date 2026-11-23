"""Strict portability boundary for redundant original route-bearing witnesses."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_browser_navigation as browser


def route():
    return {'level': 'EG', 'points_mm': [[0., 0.], [2., 1.]],
        'resources': [{'id': 'EG.original', 'start_index': 0, 'end_index': 1}],
        'zone_segments': [{'start_index': 0, 'end_index': 1, 'velocity_mm_s': 300}],
        'portal_certificates': [{'segment_index': 0,
            'certificate': 'fixed-yaw native triangle swept rectangle',
            'yaw_rad': math.atan2(1., 2.), 'reserve_mm': 85.}],
        'centreline_portal_certificates': [{'yaw_rad': 0.1}], 'curve_qualified': False}


class SourceBoundBearingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        root_patch = patch.object(browser.model, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        validation = patch.object(browser.model, 'validate', side_effect=lambda source: source)
        validation.start()
        self.addCleanup(validation.stop)
        self.write('model/source.json', {'source': 'unchanged'})
        self.pins = {'model/source.json': browser.model.digest(self.root/'model/source.json')}
        mandatory = patch.object(browser, '_mandatory_pins', return_value=self.pins)
        mandatory.start()
        self.addCleanup(mandatory.stop)
        self.directory = 'exports/building-fleet/fixture/'
        self.world = self.write(self.directory+'world.json', {'world': 'native fixture'})
        self.navigation = self.write(self.directory+'nav.json', {'map': 'fixture'})
        self.resource = self.write(self.directory+'resource.json', {'resources': 'fixture'})

    def write(self, name, value):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, separators=(',', ':')).encode()
        path.write_bytes(raw)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

    def binding(self, routes=None, *, missing_pins=False, bad_bank=False):
        routes = routes if routes is not None else [route()]
        pins = {} if missing_pins else self.pins
        data = {'format': 'solidcraftbot.building-fleet-route-graph-cache/1',
            'source_files_sha256': pins, 'world_report': self.world,
            'navigation_input': self.navigation, 'resource_input': self.resource,
            'sealed': True, 'hubs': {}, 'endpoints': {}, 'centreline': [], 'repairs': [],
            'routes': routes, 'route_bank_sha256': 'bad' if bad_bank else browser.ResourceCatalog.route_bank_hash(routes),
            'qualification': browser.QUALIFICATION, 'scope': 'fixture static only'}
        graph = self.write(self.directory+'graph.json', data)
        report = {'format': 'solidcraftbot.building-fleet-static-preparation/1',
            'passed': True, 'engine_model_time_s': 0,
            'qualification': {'static_preparation_only': True, 'motion_executed': False,
                'full_fleet_qualified': False, 'hardware_executed': False},
            'source_files_sha256_start': pins, 'source_files_sha256_end': pins,
            'route_graph': graph, 'route_count': len(routes)}
        report_ref = self.write(self.directory+'preparation.json', report)
        nav = object.__new__(browser.BrowserNavigation)
        nav.config = {}
        nav.mesh = SimpleNamespace(world_report_path=self.root/self.world['path'])
        nav.bind_source_metadata(self.root/report_ref['path'])
        return nav

    def checked(self, nav, fresh):
        with patch.object(browser.Navigation, '_own_right', return_value=copy.deepcopy(fresh)) as check:
            value = nav._own_right({'source_input': 'not a replacement geometry'})
            check.assert_called_once()
        return value

    def test_one_adjacent_bearing_restores_exact_bank_after_fresh_native_checks(self):
        original = route()
        nav = self.binding([original])
        fresh = copy.deepcopy(original)
        fresh['portal_certificates'][0]['yaw_rad'] = math.nextafter(
            fresh['portal_certificates'][0]['yaw_rad'], math.inf)
        self.assertNotEqual(browser.ResourceCatalog.route_bank_hash([fresh]),
                            browser.ResourceCatalog.route_bank_hash([original]))
        restored = self.checked(nav, fresh)
        self.assertEqual(restored, original)
        self.assertEqual(browser.ResourceCatalog.route_bank_hash([restored]),
                         browser.ResourceCatalog.route_bank_hash([original]))
        provenance = nav.browser_metadata_provenance()
        self.assertEqual(provenance['rebound_bearing_count'], 1)
        self.assertEqual(provenance['maximum_ulp_distance'], 1)
        self.assertTrue(provenance['fresh_native_sweeps_required'])
        self.assertNotEqual(provenance['examples'][0]['original_witness_hex'],
                            provenance['examples'][0]['fresh_checked_bearing_hex'])

    def test_more_than_one_adjacent_bearing_is_rejected(self):
        nav = self.binding()
        fresh = route()
        old = fresh['portal_certificates'][0]['yaw_rad']
        fresh['portal_certificates'][0]['yaw_rad'] = math.nextafter(math.nextafter(old, math.inf), math.inf)
        with self.assertRaisesRegex(ValueError, 'more than one'):
            self.checked(nav, fresh)
        self.assertEqual(nav.browser_metadata_provenance()['rebound_bearing_count'], 0)

    def test_any_other_bit_or_type_change_keeps_fresh_route_and_fails_original_bank(self):
        mutations = [
            lambda r: r['points_mm'][1].__setitem__(0, math.nextafter(2., math.inf)),
            lambda r: r['points_mm'][0].__setitem__(0, -0.),
            lambda r: r['points_mm'][1].__setitem__(0, 2),
            lambda r: r['resources'][0].__setitem__('id', 'EG.changed'),
            lambda r: r['portal_certificates'][0].__setitem__('reserve_mm', math.nextafter(85., math.inf)),
            lambda r: r['portal_certificates'][0].__setitem__('reserve_mm', 85),
            lambda r: r['centreline_portal_certificates'][0].__setitem__('yaw_rad', math.nextafter(.1, math.inf)),
        ]
        nav = self.binding()
        original = route()
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                fresh = route()
                fresh['portal_certificates'][0]['yaw_rad'] = math.nextafter(
                    fresh['portal_certificates'][0]['yaw_rad'], math.inf)
                mutate(fresh)
                result = self.checked(nav, fresh)
                self.assertEqual(result['portal_certificates'][0]['yaw_rad'].hex(),
                                 fresh['portal_certificates'][0]['yaw_rad'].hex())
                self.assertNotEqual(browser.geometry_signature(result), browser.geometry_signature(original))
                self.assertNotEqual(browser.ResourceCatalog.route_bank_hash([result]),
                                    browser.ResourceCatalog.route_bank_hash([original]))
        self.assertEqual(nav.browser_metadata_provenance()['rebound_bearing_count'], 0)

    def test_native_check_failure_is_propagated_before_any_metadata_reuse(self):
        nav = self.binding()
        with patch.object(browser.Navigation, '_own_right', side_effect=ValueError('native collision')) as check:
            with self.assertRaisesRegex(ValueError, 'native collision'):
                nav._own_right(route())
            check.assert_called_once()
        self.assertEqual(nav.browser_metadata_provenance()['matched_route_calls'], 0)

    def test_missing_source_pins_and_changed_bank_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'mandatory'):
            self.binding(missing_pins=True)
        with self.assertRaisesRegex(ValueError, 'route-bank hash'):
            self.binding(bad_bank=True)

    def test_ambiguous_original_witnesses_are_rejected(self):
        first = route()
        second = route()
        second['portal_certificates'][0]['yaw_rad'] = math.nextafter(
            second['portal_certificates'][0]['yaw_rad'], math.inf)
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.binding([first, second])

    def test_same_bearing_and_unknown_runtime_geometry_are_not_rewritten(self):
        nav = self.binding()
        self.assertEqual(self.checked(nav, route()), route())
        fresh = route()
        fresh['points_mm'] = [[30., 50.], [80., 100.]]
        result = self.checked(nav, fresh)
        self.assertEqual(result, fresh)
        self.assertEqual(nav.browser_metadata_provenance()['unknown_route_calls'], 1)

    def test_prepared_routes_without_portal_witnesses_remain_explicitly_distinct(self):
        prepared = {'level': 'EG', 'points_mm': [[0., 0.], [1., 2.]], 'resources': []}
        nav = self.binding([route(), prepared])
        self.assertEqual(nav.browser_metadata_provenance()['template_route_count'], 2)
        self.assertEqual(nav.browser_metadata_provenance()['bearing_template_geometry_count'], 1)
        self.assertNotEqual(browser.geometry_signature(prepared),
                            browser.geometry_signature({**prepared, 'portal_certificates': []}))

    def test_signed_zero_bearings_are_not_silently_equated(self):
        original = route()
        original['portal_certificates'][0]['yaw_rad'] = 0.
        nav = self.binding([original])
        fresh = copy.deepcopy(original)
        fresh['portal_certificates'][0]['yaw_rad'] = -0.
        with self.assertRaises(ValueError):
            self.checked(nav, fresh)


if __name__ == '__main__':
    unittest.main()
