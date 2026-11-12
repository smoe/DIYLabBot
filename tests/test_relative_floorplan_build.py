"""Synthetic display scale and native-proof guards; fixtures contain no real plan."""
import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_relative_floorplan as build


class RelativeBuildTests(unittest.TestCase):
    def opening_spec(self):
        return {'walls': [{'id': 'Synthetic', 'kind': 'wall'}],
                'openings': [{'id': 'SyntheticDoor', 'wall': 'Synthetic', 'kind': 'door'}]}

    def test_display_scale_is_explicit_and_positive_before_any_tool_resolution(self):
        for argv in ([], ['--display-scale', 'nan'], ['--display-scale', '-1'], ['--display-scale', '0']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(build.tool_paths, 'resolve_tool_arguments') as resolve, self.assertRaises(SystemExit):
                build.main(argv)
            resolve.assert_not_called()
        self.assertEqual(build.display_parameters(SimpleNamespace(display_scale=2., display_height=50.,
                         display_thickness=3., display_floor_depth=1.))['display_scale'], 2.)

    def test_backend_does_not_discover_the_other_runtime(self):
        for backend, own, other in [('freecad', 'default_freecad_python', 'default_solidcraft_cli'),
                                     ('solidcraft', 'default_solidcraft_cli', 'default_freecad_python')]:
            with patch.object(build.tool_paths, own, return_value='cad') as selected, \
                    patch.object(build.tool_paths, other, side_effect=AssertionError('Other CAD queried')), \
                    patch.object(build, 'build', return_value={}):
                build.main(['--display-scale', '2', '--backend', backend])
                selected.assert_called_once_with()

    def test_rotated_opening_probe_commands_target_only_its_wall(self):
        probe = {'id': 'SyntheticDoor', 'kind': 'polygon_prism', 'points_mm': [[0., 0.], [2., 2.], [1., 3.], [-1., 1.]],
                 'offset_mm': .01, 'depth_mm': 20., 'target_body': 'Wall_Synthetic'}
        with patch.object(build.model, 'interfaces', return_value={'opening_probes': [probe]}):
            self.assertEqual(build.opening_probes(self.opening_spec(), {}), [probe])
        commands = build.probe_commands(probe, 'Witness')
        self.assertEqual(commands[-1]['params']['bodies'], ['Witness', 'Wall_Synthetic'])
        self.assertEqual(commands[1]['params']['points'], probe['points_mm'])
        self.assertEqual(commands[0]['params']['offset'], .01)

    def test_opening_proof_geometry_is_finite_unique_and_positive(self):
        probe = {'id': 'SyntheticDoor', 'kind': 'polygon_prism', 'points_mm': [[0., 0.], [2., 0.], [2., 1.], [0., 1.]],
                 'offset_mm': .01, 'depth_mm': 20., 'target_body': 'Wall_Synthetic'}
        for probes in ([probe, probe], [{**probe, 'depth_mm': 0}], [{**probe, 'offset_mm': float('nan')}],
                       [{**probe, 'id': '../private'}], [{**probe, 'points_mm': [[0., float('inf')], [2., 0.], [2., 1.]]}]):
            with patch.object(build.model, 'interfaces', return_value={'opening_probes': probes}), self.assertRaises(ValueError):
                build.opening_probes(self.opening_spec(), {})

    def test_unknown_openings_cannot_gain_native_cut_evidence_and_known_ones_cannot_disappear(self):
        probe = {'id': 'SyntheticDoor', 'kind': 'polygon_prism', 'points_mm': [[0., 0.], [2., 0.], [2., 1.], [0., 1.]],
                 'offset_mm': .01, 'depth_mm': 20., 'target_body': 'Wall_Synthetic'}
        with patch.object(build.model, 'interfaces', return_value={'opening_probes': []}), self.assertRaises(ValueError):
            build.opening_probes(self.opening_spec(), {})
        spec = self.opening_spec()
        spec['openings'][0]['kind'] = 'unknown'
        with patch.object(build.model, 'interfaces', return_value={'opening_probes': [probe]}), self.assertRaises(ValueError):
            build.opening_probes(spec, {})
        with patch.object(build.model, 'interfaces', return_value={'opening_probes': []}):
            self.assertEqual(build.opening_probes(spec, {}), [])

    def test_comparison_error_names_cannot_be_read_as_building_millimetres(self):
        body = {'body': 'SyntheticWall', 'volume_mm3': 20., 'world_center_of_mass_mm': [1., 2., 3.],
                'bbox': {'min': [0., 0., 0.], 'max': [2., 4., 6.]}}
        check = build.comparison([body], [body])[0]
        self.assertTrue(check['passed'])
        self.assertIn('com_error_display_mm', check)
        self.assertNotIn('com_error_mm', check)
        self.assertIn('Synthetic display mm', build.UNIT_NOTICE)

    def test_original_images_and_private_output_paths_are_not_public_hash_inputs(self):
        private = ROOT/'exports/synthetic-private-original.jpg'
        with patch.object(build.model, 'source_dependencies', return_value=[private]), \
                self.assertRaisesRegex(ValueError, 'Non-public dependency'):
            build.source_snapshot({}, ROOT/'scripts/robot_spec.py')


class RelativeNativeEvidenceTests(unittest.TestCase):
    def test_existing_native_preview_is_source_bound_and_explicitly_nonmetric(self):
        path = ROOT/'cad/relative-floorplan/floor-f03.shared/shared-build-report.json'
        if not path.exists():
            self.skipTest('Build the explicit synthetic display preview to inspect native evidence')
        report = json.loads(path.read_text())
        self.assertTrue(report['passed'])
        self.assertFalse(report['metric_scale_known'])
        self.assertFalse(report['interference']['checked'])
        self.assertFalse(report['interference']['zero_interference_claimed'])
        self.assertEqual(report['cross_cad_checked'], report['backends'] == 'both')
        self.assertGreater(report['display_parameters']['display_scale'], 0)
        build.common.verify_pins(report['source_files_sha256'])
        build.common.verify_artifacts({key: ROOT/value for key, value in report['files'].items()}, report['artifact_sha256'])
        spec = build.model.load(ROOT/report['source'])
        self.assertEqual(report['representation']['declared_walls'], len(spec['walls']))
        self.assertEqual(report['representation']['constructed_wall_bodies'], sum(w['kind'] == 'wall' for w in spec['walls']))
        self.assertEqual(report['representation']['constructed_floor_bodies'], sum(a['kind'] not in {'unknown', 'void'} for a in spec['areas']))
        p = build.model.parameters(spec, report['display_parameters'])
        expected = {probe['id'] for probe in build.opening_probes(spec, p)}
        if report['backends'] in {'solidcraft', 'both'}:
            self.assertEqual({c['id'] for c in report['solidcraft_opening_checks']}, expected)
            self.assertTrue(all(c['passed'] for c in report['solidcraft_opening_checks']))
        if report['backends'] in {'freecad', 'both'}:
            native = json.loads((ROOT/report['files']['freecad_validation']).read_text())
            self.assertEqual({c['id'] for c in native['opening_checks']}, expected)
            self.assertTrue(all(c['passed'] for c in native['opening_checks']))
        if report['backends'] == 'both':
            self.assertTrue(all(c['passed'] for c in report['body_comparisons']))
            self.assertLess(report['maximum_step_xor_display_mm3'], .001)


if __name__ == '__main__':
    unittest.main()
