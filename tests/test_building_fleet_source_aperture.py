"""A checked world's aperture reuse keeps source pins and all native frames."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_lift_checks as checks


class CheckedApertureTests(unittest.TestCase):
    def setUp(self):
        self.source = checks.model.load()
        self.building = checks.model.reference(self.source, 'building')
        self.parameters = checks.stack.parameters(self.building)
        self.plan, _ = checks.stack.templates(self.building)
        declaration = self.building['circulation']['elevator']
        opening = next(row for row in self.plan['openings'] if row['id'] == declaration['reference_opening'])
        walls = {row['id']: row for row in self.plan['walls']}
        wall = walls[opening['wall']]
        a, b = [self.plan['vertices'][wall[key]] for key in ('start', 'end')]
        scale = self.parameters['display_scale']
        self.interval = sorted((a[1] + t*(b[1]-a[1]))*scale for t in opening['interval'])
        ports = []
        for index, level in enumerate(self.building['levels']):
            for side, value in declaration['sides'].items():
                wall = walls[value['wall']]
                x = self.plan['vertices'][wall['start']][0]*scale
                ports.append({'level_id': level['id'], 'side': side, 'wall': value['wall'],
                    'plane_x_mm': x, 'height_mm': self.parameters['door_height_mm'],
                    'wall_thickness_mm': self.parameters['display_thickness'],
                    'z_mm': (index-1)*self.parameters['floor_pitch_mm'],
                    'cabin_entry_mm': [x, sum(self.interval)/2, 0.]})
        self.lift = {'reference_level': declaration['cabin_level'], 'ports': ports}
        mesh = object.__new__(checks.navigation.NativeMesh)
        mesh.export = Path('/unused/checked-world')
        mesh.manifest = {'elevator': copy.deepcopy(self.lift)}
        self.nav = SimpleNamespace(config=self.source, mesh=mesh)
        ref = self.source['sources']['building']
        self.report = {'source_files_sha256': {ref['path']: ref['sha256']}}

    def reader(self):
        return patch.object(checks.walkthrough_world, 'read',
            return_value=(self.report, {'elevator': copy.deepcopy(self.lift)}, {}))

    def test_checked_world_matches_original_canonical_expression_without_furnishings(self):
        with self.reader(), patch.object(checks.stack, 'load', side_effect=AssertionError('Full layout rebuilt')):
            source, interval, opening = checks._source_aperture(checked_navigation=self.nav)
        self.assertEqual(source, self.source)
        self.assertEqual([v.hex() for v in interval], [v.hex() for v in self.interval])
        self.assertEqual(opening, self.building['circulation']['elevator']['reference_opening'])

    def test_standalone_caller_keeps_complete_source_validation(self):
        with patch.object(checks.stack, 'load', return_value=self.building) as load:
            self.assertEqual(checks._source_aperture()[1], self.interval)
        load.assert_called_once()

    def test_world_reverification_failure_and_changed_building_pin_fail_closed(self):
        with patch.object(checks.walkthrough_world, 'read', side_effect=ValueError('Stale walkthrough source')):
            with self.assertRaisesRegex(ValueError, 'Stale'):
                checks._source_aperture(checked_navigation=self.nav)
        self.report['source_files_sha256'] = {}
        with self.reader(), self.assertRaisesRegex(ValueError, 'exact current building'):
            checks._source_aperture(checked_navigation=self.nav)

    def test_unchecked_or_source_mismatched_navigation_is_rejected(self):
        for nav in (SimpleNamespace(config={}, mesh=self.nav.mesh),
                    SimpleNamespace(config=self.source, mesh=SimpleNamespace())):
            with self.subTest(nav=nav), self.assertRaisesRegex(ValueError, 'source-matched'):
                checks._source_aperture(checked_navigation=nav)

    def test_native_frame_change_missing_side_and_changed_reference_are_rejected(self):
        for change in (lambda p: p[0].update(height_mm=p[0]['height_mm']+1),
                       lambda p: p[0].update(wall='Unknown'),
                       lambda p: p[0].update(plane_x_mm=p[0]['plane_x_mm']+1),
                       lambda p: p.pop()):
            lift = copy.deepcopy(self.lift)
            change(lift['ports'])
            with self.subTest(change=change), self.assertRaises(ValueError):
                checks._check_native_aperture(self.building, self.plan, self.parameters, self.interval, lift)
        building = copy.deepcopy(self.building)
        building['circulation']['elevator']['reference_opening'] = 'Missing'
        with self.assertRaises((ValueError, StopIteration)):
            checks._check_native_aperture(building, self.plan, self.parameters, self.interval, self.lift)


if __name__ == '__main__':
    unittest.main()
