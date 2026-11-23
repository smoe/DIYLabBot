"""Reuse a checked map without removing native clearance or start membership."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_clearance as clearance
import building_fleet_floor as floors
import building_fleet_model as model
from building_fleet_routes import Navigation


class CheckedNavigationTests(unittest.TestCase):
    def setUp(self):
        self.source = model.load()
        self.mesh = SimpleNamespace(manifest={
            'levels': [{'id': 'EG', 'z_mm': 0}],
            'objects': [{'id': 'cabin', 'moving_body_ids': []}],
            'elevator': {'object_id': 'cabin'}},
            scene={'groups': [], 'linear_tessellation_deflection_mm': 0,
                   'maximum_float32_error_mm': 0})
        self.bank = SimpleNamespace(triangles=[])
        self.grid = SimpleNamespace(resolution_mm=self.source['geometry']['grid_step_mm'],
            floor_support=self.bank, cell=lambda point: 0, blocked=bytearray([0]))
        self.topology = {'EG': {'plan': {'areas': []}, 'excluded_areas': [], 'display_scale': 1}}
        self.navigation = Navigation.__new__(Navigation)
        self.navigation.mesh = self.mesh
        self.navigation.config = copy.deepcopy(self.source)
        self.navigation.height = 2 + self.source['geometry']['height_reserve_mm']
        self.navigation.topological = self.topology
        self.navigation.grids = {'EG': self.grid}
        self.envelope = {'min': [-1, -1, 0], 'max': [1, 1, 2], 'height_mm': 2}

    def certificate(self, navigation):
        with patch.dict(clearance._TOPOLOGY_CACHE, {}, clear=True), patch.object(floors, 'floor_support', return_value=self.bank), patch.object(
                clearance.geometry, 'vehicle_envelope', return_value=self.envelope):
            return clearance.ClearanceCertificate(self.mesh, 'EG', self.source,
                checked_navigation=navigation)

    def test_exact_map_reuse_keeps_the_initial_closed_solid_check(self):
        with patch.object(clearance.nav, 'topology', side_effect=AssertionError('unrelated rebuild')), \
                patch.object(clearance.nav, 'build_grid', side_effect=AssertionError('duplicate raster')):
            certificate = self.certificate(self.navigation)
        self.assertIs(certificate.start_grid, self.grid)
        self.grid.blocked[0] = 1
        curve = SimpleNamespace(times=[0], evaluate=lambda time: {clearance.floor.F[0]: [0, 0, 0]})
        self.assertEqual(certificate.check(curve),
            {'passed': False, 'reason': 'initial_pose_not_proven_outside_closed_projected_solids'})

    def test_foreign_source_mesh_height_grid_or_topology_is_rejected(self):
        mutations = [
            lambda nav: setattr(nav, 'mesh', copy.copy(self.mesh)),
            lambda nav: nav.config['geometry'].__setitem__('height_reserve_mm', 999),
            lambda nav: setattr(nav, 'height', nav.height + 1),
            lambda nav: setattr(nav, 'topological', {}),
            lambda nav: setattr(nav, 'grids', {}),
            lambda nav: setattr(nav, 'grids', {'EG': SimpleNamespace(
                resolution_mm=1, floor_support=self.bank)}),
            lambda nav: setattr(nav, 'grids', {'EG': SimpleNamespace(
                resolution_mm=self.grid.resolution_mm, floor_support=object())}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                nav = copy.copy(self.navigation)
                nav.config = copy.deepcopy(self.navigation.config)
                mutate(nav)
                with self.assertRaisesRegex(ValueError, 'source/world-matched'):
                    self.certificate(nav)
        with self.assertRaisesRegex(ValueError, 'source/world-matched'):
            self.certificate(SimpleNamespace())

    def test_standalone_certificate_keeps_its_original_derivation(self):
        with patch.dict(clearance._TOPOLOGY_CACHE, {}, clear=True), patch.object(floors, 'floor_support', return_value=self.bank), patch.object(
                clearance.geometry, 'vehicle_envelope', return_value=self.envelope), patch.object(
                clearance.nav, 'topology', return_value=self.topology), patch.object(
                clearance.nav, 'build_grid', return_value=self.grid) as build:
            certificate = clearance.ClearanceCertificate(self.mesh, 'EG', self.source)
        self.assertIs(certificate.start_grid, self.grid)
        self.assertIs(build.call_args.kwargs['support_config'], self.source)


if __name__ == '__main__':
    unittest.main()
