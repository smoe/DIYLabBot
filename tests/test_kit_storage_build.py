"""Fail-closed native support, access and independent-backend S01 evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_kit_storage as build


class StorageBuildTests(unittest.TestCase):
    def geometry(self):
        return [{'body': 'Carrier', 'bbox': {'min': [0., 0., 10.], 'max': [20., 30., 30.]}},
                {'body': 'Support', 'bbox': {'min': [-1., -1., 0.], 'max': [21., 31., 10.]}}]

    def contract(self):
        return {'carrier_body': 'Carrier', 'support_body': 'Support', 'contact_z_mm': 10.,
                'footprint_bbox_mm': {'min': [0., 0., 10.], 'max': [20., 30., 10.]}}

    def test_backend_never_discovers_the_other_cad_runtime(self):
        for backend, own, other in [('freecad', 'default_freecad_python', 'default_solidcraft_cli'),
                                     ('solidcraft', 'default_solidcraft_cli', 'default_freecad_python')]:
            with self.subTest(backend=backend), patch.object(build.tool_paths, own, return_value='native-tool') as called, \
                    patch.object(build.tool_paths, other, side_effect=AssertionError('Other CAD requested')), \
                    patch.object(build, 'build', return_value={}):
                build.main(['--backend', backend, '--no-render'])
                called.assert_called_once_with()

    def test_full_footprint_contact_requires_both_actual_half_volumes(self):
        with patch.object(build.model, 'interfaces', return_value={'support': self.contract()}):
            contract = build.support_geometry({}, {}, self.geometry())
        self.assertTrue(contract['passed'])
        self.assertEqual(contract['expected_half_volume_mm3'], 60.)
        self.assertTrue(build.support_volumes(contract, {'Carrier': 60., 'Support': 60.})['passed'])
        for volumes in ({'Carrier': 30., 'Support': 60.}, {'Carrier': 61., 'Support': 60.},
                        {'Carrier': 60.}, {'Carrier': float('nan'), 'Support': 60.}):
            self.assertFalse(build.support_volumes(contract, volumes)['passed'])

    def test_gap_penetration_and_partial_overhang_are_rejected(self):
        for target, edge, axis, value in [('Carrier', 'min', 2, 10.1), ('Carrier', 'min', 2, 9.9),
                                          ('Support', 'max', 2, 9.), ('Support', 'max', 0, 19.)]:
            geometry = copy.deepcopy(self.geometry())
            next(b for b in geometry if b['body'] == target)['bbox'][edge][axis] = value
            with patch.object(build.model, 'interfaces', return_value={'support': self.contract()}):
                self.assertFalse(build.support_geometry({}, {}, geometry)['passed'])

    def test_incomplete_or_foreign_native_support_intersection_is_rejected(self):
        result = {'checked': 2, 'count': 1, 'interferences': [{'a': 'Carrier', 'b': 'Witness', 'volume_mm3': 60.}],
                  'unchecked': [], 'truncated': False, 'budget_exceeded': False, 'pairs_not_checked': 0, 'skipped_pairs': 0}
        self.assertEqual(build.support_intersection(result, 'Carrier', 'Witness'), 60.)
        for change in ({'unchecked': [{}]}, {'count': 0}, {'checked': 1}, {'truncated': True},
                       {'interferences': [{'a': 'Other', 'b': 'Witness', 'volume_mm3': 60.}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                build.support_intersection({**result, **change}, 'Carrier', 'Witness')

    def test_access_margins_expand_all_axes_and_invalid_geometry_fails(self):
        probe = {'id': 'CarrierAccess', 'frame_id': 'CarrierApproach', 'kind': 'box',
                 'origin_mm': [0., 1., 2.], 'size_mm': [10., 20., 30.], 'minimum_clearance_mm': 2.}
        with patch.object(build.model, 'interfaces', return_value={'native_clearance_probes': [probe]}):
            actual = build.probe_boxes({}, {})[0]
        self.assertEqual(actual['audit_origin_mm'], [-2., -1., 0.])
        self.assertEqual(actual['audit_size_mm'], [14., 24., 34.])
        for probes in ([], [probe, probe], [{**probe, 'minimum_clearance_mm': 0}], [{**probe, 'size_mm': [float('nan'), 1., 1.]}]):
            with patch.object(build.model, 'interfaces', return_value={'native_clearance_probes': probes}), self.assertRaises(ValueError):
                build.probe_boxes({}, {})

    def test_source_and_artifact_drift_rejected_by_shared_pure_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'native.sc'
            path.write_bytes(b'first')
            digest = build.common.robot_spec.digest(path)
            build.common.verify_artifacts({'scene': path}, {'scene': digest})
            with patch.object(build.common, 'ROOT', Path(directory)):
                build.common.verify_pins({'native.sc': digest})
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                build.common.verify_artifacts({'scene': path}, {'scene': digest})
            with patch.object(build.common, 'ROOT', Path(directory)), self.assertRaises(ValueError):
                build.common.verify_pins({'native.sc': digest})


class StorageNativeEvidenceTests(unittest.TestCase):
    def test_current_native_scene_proof_preserves_support_and_complete_access_coverage(self):
        path = ROOT/'cad/kit-storage-s01/shared-build-report.json'
        if not path.exists():
            self.skipTest('Build native S01 scenes to inspect their evidence')
        report = json.loads(path.read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(report['format'], build.FORMAT)
        self.assertEqual({c['id'] for c in report['cases']}, build.CASES)
        self.assertEqual(report['cross_cad_checked'], report['backends'] == 'both')
        build.common.verify_pins(report['source_files_sha256'])
        for case in report['cases']:
            self.assertTrue(case['passed'])
            build.common.verify_artifacts({k: ROOT/v for k, v in case['files'].items()}, case['artifact_sha256'])
            spec = build.model.materialize(build.model.load(), case['id'])
            expected = {p['id'] for p in build.probe_boxes(spec, build.model.parameters(spec))}
            for backend in ('solidcraft', 'freecad'):
                if report['backends'] not in {backend, 'both'}:
                    continue
                proof = (case['solidcraft_checks'] if backend == 'solidcraft'
                         else json.loads((ROOT/case['files']['freecad_validation']).read_text()))
                self.assertTrue(proof['support']['passed'])
                self.assertTrue(proof['access']['passed'])
                self.assertEqual({c['id'] for c in proof['access']['checks']}, expected)
                self.assertTrue(all(c['passed'] and len(c['native_bodies_checked']) == case['body_count'] for c in proof['access']['checks']))
            if report['backends'] == 'both':
                self.assertTrue(all(c['passed'] for c in case['body_comparisons']))
                self.assertLess(case['maximum_step_xor_mm3'], .001)
            else:
                self.assertIsNone(case['body_comparisons'])
                self.assertIsNone(case['maximum_step_xor_mm3'])


if __name__ == '__main__':
    unittest.main()
