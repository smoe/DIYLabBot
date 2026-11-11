"""Independent-backend selection and fail-closed K01 native evidence checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_extraction_kit_station as build


class KitBuildTests(unittest.TestCase):
    def body(self):
        return {'body': 'Box', 'volume_mm3': 100., 'world_center_of_mass_mm': [1., 2., 3.],
                'bbox': {'min': [0., 0., 0.], 'max': [2., 4., 6.]}}

    def interference(self):
        return [{'checked': 2, 'count': 0, 'interferences': [], 'unchecked': [], 'truncated': False,
                 'budget_exceeded': False, 'pairs_not_checked': 0, 'skipped_pairs': 0}]

    def test_each_backend_requires_only_its_own_runtime(self):
        self.assertEqual(build.required_tools('freecad'), {'freecad_python'})
        self.assertEqual(build.required_tools('solidcraft'), {'solidcraft_cli'})
        self.assertEqual(build.required_tools('both'), {'freecad_python', 'solidcraft_cli'})
        with self.assertRaises(ValueError):
            build.required_tools('mesh')
        for backend, expected in [('freecad', {'freecad_python'}), ('solidcraft', {'solidcraft_cli'})]:
            with self.subTest(backend=backend), patch.object(build.tool_paths, 'resolve_tool_arguments') as resolve, \
                    patch.object(build, 'build', return_value={}) as run:
                build.main(['--backend', backend, '--no-render'])
                self.assertEqual(resolve.call_args.kwargs['required'], expected)
                self.assertEqual(set(vars(resolve.call_args.args[1])), expected)
                self.assertEqual(run.call_args.args[0].backend, backend)

    def test_unselected_runtime_is_not_even_discovered(self):
        for backend, selected, other in [('freecad', 'default_freecad_python', 'default_solidcraft_cli'),
                                          ('solidcraft', 'default_solidcraft_cli', 'default_freecad_python')]:
            with self.subTest(backend=backend), patch.object(build.tool_paths, selected, return_value='/selected/tool') as own, \
                    patch.object(build.tool_paths, other, side_effect=AssertionError('Unselected CAD runtime touched')), \
                    patch.object(build, 'build', return_value={}):
                build.main(['--backend', backend, '--no-render'])
                own.assert_called_once_with()

    def test_source_pin_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'ROOT', Path(directory)):
            path = Path(directory)/'source.json'
            path.write_text('{}')
            pins = {'source.json': build.robot_spec.digest(path)}
            build.verify_pins(pins)
            path.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                build.verify_pins(pins)
            with self.assertRaises(ValueError):
                build.verify_pins({})

    def test_generated_artifact_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'model.sc'
            path.write_bytes(b'native')
            hashes = {'solidcraft': build.robot_spec.digest(path)}
            build.verify_artifacts({'solidcraft': path}, hashes)
            path.write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError, 'artifact changed'):
                build.verify_artifacts({'solidcraft': path}, hashes)

    def test_interference_must_cover_all_bodies_without_unchecked_pairs(self):
        self.assertTrue(build.check_solidcraft_interference(self.interference(), 2)['passed'])
        for key, value in [('unchecked', [{'a': 'Box', 'b': 'Lid'}]), ('checked', 1), ('count', 1),
                           ('truncated', True), ('budget_exceeded', True), ('pairs_not_checked', 1),
                           ('skipped_pairs', 1), ('interferences', [{'a': 'Box', 'b': 'Lid'}])]:
            with self.subTest(field=key):
                results = self.interference()
                results[0][key] = value
                self.assertFalse(build.check_solidcraft_interference(results, 2)['passed'])
        with self.assertRaises(ValueError):
            build.check_solidcraft_interference([{}], 2)

    def test_cross_cad_comparison_detects_geometry_changes_and_duplicate_ids(self):
        first = self.body()
        self.assertTrue(build.compare([first], [first])[0]['passed'])
        for field, value in [('volume_mm3', 101.), ('world_center_of_mass_mm', [2., 2., 3.]),
                             ('bbox', {'min': [0., 0., 0.], 'max': [3., 4., 6.]})]:
            other = copy.deepcopy(first)
            other[field] = value
            self.assertFalse(build.compare([first], [other])[0]['passed'])
        with self.assertRaises(ValueError):
            build.compare([first, first], [first])

    def test_body_validation_rejects_open_duplicate_missing_and_nonfinite(self):
        body = {'name': 'Box', 'closed': True, 'volume_mm3': 100., 'center_of_mass': [1., 2., 3.],
                'bbox': {'min': [0., 0., 0.], 'max': [2., 4., 6.]}}
        source = {'bodies': [{'id': 'Box'}]}
        self.assertEqual(len(build.measurements({'bodies': [body]}, source, backend='solidcraft')), 1)
        for mutation in ({'closed': False}, {'volume_mm3': float('nan')}, {'volume_mm3': 0}, {'name': 'Other'}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                build.measurements({'bodies': [{**body, **mutation}]}, source, backend='solidcraft')
        with self.assertRaises(ValueError):
            build.measurements({'bodies': [body, body]}, source, backend='solidcraft')

    def test_empty_interface_evidence_is_not_a_pass(self):
        with patch.object(build.model, 'check_interface_geometry', return_value=[]), self.assertRaises(ValueError):
            build.interface_checks({}, {}, [])


class KitNativeEvidenceTests(unittest.TestCase):
    def test_available_native_evidence_is_source_current_and_honest_about_backends(self):
        path = ROOT/'cad/extraction-kit-station/shared-build-report.json'
        if not path.exists():
            self.skipTest('Build the independent native K01 backends to inspect CAD evidence')
        report = json.loads(path.read_text(encoding='utf-8'))
        self.assertTrue(report['passed'])
        self.assertEqual(report['format'], build.FORMAT)
        self.assertEqual({c['id'] for c in report['cases']}, build.CASES)
        self.assertEqual(report['cross_cad_checked'], report['backends'] == 'both')
        build.verify_pins(report['source_files_sha256'])
        for case in report['cases']:
            self.assertTrue(case['passed'])
            self.assertEqual(case['cross_cad_checked'], report['backends'] == 'both')
            build.verify_artifacts({k: ROOT/v for k, v in case['files'].items()}, case['artifact_sha256'])
            if report['backends'] == 'both':
                self.assertTrue(case['body_comparisons'])
                self.assertTrue(all(c['passed'] for c in case['body_comparisons']))
                self.assertLess(case['maximum_step_xor_mm3'], .001)
            else:
                self.assertIsNone(case['body_comparisons'])
                self.assertIsNone(case['maximum_step_xor_mm3'])


if __name__ == '__main__':
    unittest.main()
