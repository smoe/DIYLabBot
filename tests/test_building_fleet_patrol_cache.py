"""Static graph reuse must fail closed before any simulated motion starts."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_patrol_cache as cache


def bank_hash(routes):
    return hashlib.sha256(json.dumps(routes, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


class SourceGraph:
    def __init__(self, nav, progress=None):
        self.hubs = copy.deepcopy(nav.road_hubs)
        self.endpoints = {'EG': {(10, 0)}}
        self.centreline = {}
        self.repairs = {}
        self.sealed = False

    def add_endpoint(self, level, point):
        if self.sealed:
            raise ValueError('Planner must precede graph sealing')
        self.endpoints[level].add(tuple(point))

    def base_routes(self):
        return list(self.centreline.values()) + list(self.repairs.values())


class SourcePlanner:
    def __init__(self, source, nav, graph):
        graph.add_endpoint('EG', [4, 0])

    def prepared_routes(self):
        return [{'kind': 'source-derived-private-approach'}]


class StaticGraphCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'exports/building-fleet/new-derivation'
        self.out.mkdir(parents=True)
        self.resource = self.root / 'exports/building-fleet/resources'
        self.resource.mkdir()
        self.source = {'test_source': 'original'}
        self.world = self.out / 'world-build-report.json'
        self.world.write_text('{"world":"current"}\n')
        self.navigation_report = self.out / 'navigation-report.json'
        self.navigation_report.write_text('{"static":"navigation"}\n')
        self.resource_report = self.resource / 'cache-report.json'
        self.resource_report.write_text('{"static":"resources"}\n')
        nav_source = self.root / 'model/navigation-source.json'
        nav_source.parent.mkdir()
        nav_source.write_text('{"geometry":"original"}\n')
        (self.root / 'scripts').mkdir()
        for name in cache.GENERATORS:
            (self.root / 'scripts' / name).write_text('# original ' + name + '\n')
        self.nav = SimpleNamespace(config=self.source,
            mesh=SimpleNamespace(world_report_path=self.world),
            road_hubs={'EG': [10, 0]},
            homes={'BF01': {'level': 'EG', 'departure_xy_mm': [0, 0], 'arrival_xy_mm': [1, 0]}},
            inspections={('EG', 'inspection'): {'points_mm': [[2, 0], [3, 0]]}},
            _cache_pins=lambda: {'model/navigation-source.json': cache.model.digest(nav_source)})
        self.root_patch = patch.object(cache.model, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        for dependency, value in [('RouteGraph', SourceGraph), ('MissionPlanner', SourcePlanner)]:
            patcher = patch.object(cache, dependency, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        validator = patch.object(cache.model, 'validate', side_effect=lambda source: source)
        validator.start()
        self.addCleanup(validator.stop)
        self.resource_loader = patch.object(cache.ResourceCatalog, 'from_cache', return_value='checked-catalog')
        self.load_catalog = self.resource_loader.start()
        self.addCleanup(self.resource_loader.stop)
        self.pins = cache._mandatory_pins(self.nav)
        centres = [{'level': 'EG', 'start': [i, 0], 'end': [10, 0],
                    'route': {'level': 'EG', 'points_mm': [[i, 0], [10, 0]], 'curve_qualified': False}}
                   for i in range(5)]
        repairs = [{'level': 'EG', 'start': [0, 0], 'end': [1, 0],
                    'route': {'level': 'EG', 'points_mm': [[0, 0], [1, 0]], 'curve_qualified': False}}]
        routes = [row['route'] for row in centres + repairs] + SourcePlanner.prepared_routes(None)
        self.data = {'format': 'solidcraftbot.building-fleet-route-graph-cache/1',
            'source_files_sha256': self.pins, 'world_report': self.ref(self.world),
            'navigation_input': self.ref(self.navigation_report),
            'resource_input': self.ref(self.resource_report), 'sealed': True,
            'hubs': {'EG': [10, 0]}, 'endpoints': {'EG': [[i, 0] for i in range(5)] + [[10, 0]]},
            'centreline': centres, 'repairs': repairs, 'routes': routes,
            'route_bank_sha256': bank_hash(routes), 'qualification': cache.QUALIFICATION,
            'scope': 'Static-only test derivation'}
        self.report = {'format': 'solidcraftbot.building-fleet-static-preparation/1',
            'passed': True, 'source_files_sha256_start': self.pins,
            'source_files_sha256_end': self.pins, 'engine_model_time_s': 0,
            'route_count': len(routes), 'centreline_count': len(centres), 'repair_count': len(repairs),
            'qualification': {'static_preparation_only': True, 'motion_executed': False,
                              'full_fleet_qualified': False, 'hardware_executed': False}}
        self.write_evidence()

    def ref(self, path):
        return {'path': str(path.relative_to(self.root)), 'sha256': cache.model.digest(path),
                'bytes': path.stat().st_size}

    def write_evidence(self):
        graph_path = self.out / 'route-graph.json'
        graph_path.write_text(json.dumps(self.data, allow_nan=False) + '\n')
        self.report['route_graph'] = self.ref(graph_path)
        self.report_path = self.out / 'report.json'
        self.report_path.write_text(json.dumps(self.report, allow_nan=False) + '\n')

    def restore(self):
        return cache.prepare_cached(self.source, self.nav, self.report_path, self.resource)

    def test_restores_source_endpoints_graph_and_checked_resource_bank(self):
        graph, catalog, planner = self.restore()
        self.assertTrue(graph.sealed)
        self.assertEqual(graph.endpoints['EG'], {(i, 0) for i in range(5)} | {(10, 0)})
        self.assertEqual(catalog, 'checked-catalog')
        self.assertIsInstance(planner, SourcePlanner)
        self.load_catalog.assert_called_once()
        self.assertEqual(bank_hash(self.load_catalog.call_args.args[1]), self.data['route_bank_sha256'])

    def test_missing_mandatory_pin_is_rejected_even_with_consistent_report(self):
        self.pins.pop('scripts/building_fleet_geometry_checks.py')
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'mandatory'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_json_row_order_does_not_change_source_derived_bank_order(self):
        self.data['centreline'].reverse()
        self.write_evidence()
        graph, _, _ = self.restore()
        self.assertEqual([key[1] for key in graph.centreline], [(i, 0) for i in range(5)])

    def test_changed_graph_bytes_are_rejected_before_reconstruction(self):
        with (self.out / 'route-graph.json').open('a') as stream:
            stream.write(' ')
        with self.assertRaisesRegex(ValueError, 'altered'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_current_generator_change_rejects_authentic_old_graph(self):
        (self.root / 'scripts/building_fleet_missions.py').write_text('# changed planner\n')
        with self.assertRaisesRegex(ValueError, 'mandatory'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_source_endpoint_mismatch_rejects_rehashed_graph(self):
        self.data['endpoints']['EG'].remove([4, 0])
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'current source endpoints'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_missing_hub_connection_is_rejected(self):
        self.data['centreline'].pop()
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'every source hub'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_duplicate_route_is_not_silently_overwritten(self):
        self.data['centreline'].append(copy.deepcopy(self.data['centreline'][0]))
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'Unique'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_changed_reconstructed_bank_hash_is_rejected(self):
        self.data['route_bank_sha256'] = '0' * 64
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'complete route bank'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_recorded_bank_cannot_diverge_from_restored_graph(self):
        self.data['routes'].append({'unregistered': 'extra route'})
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'complete route bank'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_other_world_or_resource_cache_is_rejected(self):
        other = self.out / 'other-world.json'
        other.write_text('{"world":"other"}\n')
        self.data['world_report'] = self.ref(other)
        self.write_evidence()
        with self.assertRaisesRegex(ValueError, 'another navigation world'):
            self.restore()
        self.load_catalog.assert_not_called()

    def test_input_mutation_during_resource_restore_is_rejected(self):
        def mutate(*args):
            (self.root / 'scripts/building_fleet_runner.py').write_text('# raced\n')
            return 'checked-catalog'
        self.load_catalog.side_effect = mutate
        with self.assertRaisesRegex(ValueError, 'changed during reconstruction'):
            self.restore()


if __name__ == '__main__':
    unittest.main()
