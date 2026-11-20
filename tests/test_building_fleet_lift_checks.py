"""Independent negative floor-support geometry fixtures; no service waiver."""
import math
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_lift_checks as checks
import building_fleet_navigation as navigation


class Scene:
    def __init__(self, faces=()):
        self.manifest = {'elevator': {'reference_level': 'EG', 'reference_z_mm': 0,
                                    'cabin_bounds_mm': {'min': [0, -20, -1],
                                                        'max': [100, 20, 10]}}}
        self.faces = list(faces)
        self.scene = {'groups': [{'id': 'body_' + str(i), 'role': 'any_native_role',
                                  'triangle': face} for i, face in enumerate(faces)]}

    def bounds(self, group):
        triangle = group['triangle']
        return {'min': [min(p[k] for p in triangle) for k in range(3)],
                'max': [max(p[k] for p in triangle) for k in range(3)]}

    def triangles(self, group):
        return iter([group['triangle']])


PORT = {'id': 'port', 'active': True, 'level_id': 'EG', 'z_mm': 0,
        'side': 'inward', 'plane_x_mm': 180}


class SupportBarrierTests(unittest.TestCase):
    def test_empty_full_aperture_strip_rejects(self):
        result = checks._contact_strip(Scene(), PORT, [-10, 10], 20)
        self.assertFalse(result['passed'])
        self.assertTrue(result['rejection_proven'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['missing_strip_mm'], {'x': [110, 120], 'y': [-10, 10]})
        self.assertEqual(result['coverage']['missing_area_mm2'], 200)

    def test_finish_at_three_mm_prevents_empty_barrier_claim(self):
        faces = [[[110, -10, 3], [120, -10, 3], [120, 10, 3]],
                 [[110, -10, 3], [120, 10, 3], [110, 10, 3]]]
        result = checks._contact_strip(Scene(faces), PORT, [-10, 10], 20)
        self.assertFalse(result['passed'])  # A floor witness is not a stage proof.
        self.assertFalse(result['rejection_proven'])
        self.assertEqual(result['status'], 'unproven')
        self.assertTrue(result['coverage']['passed'])

    def test_any_contact_face_role_is_overincluded(self):
        # A slanted nonfloor face must not be silently dropped by role or normal.
        face = [[110, -10, 0], [120, -10, 20], [120, 10, 20]]
        result = checks._contact_strip(Scene([face]), PORT, [-10, 10], 20)
        self.assertFalse(result['rejection_proven'])
        self.assertGreater(result['coverage']['covered_area_mm2'], 0)
        self.assertFalse(result['passed'])

    def test_faces_outside_contact_band_do_not_create_floor(self):
        for z in (-1, 21):
            with self.subTest(z=z):
                face = [[110, -10, z], [120, -10, z], [120, 10, z]]
                result = checks._contact_strip(Scene([face]), PORT, [-10, 10], 20)
                self.assertTrue(result['rejection_proven'])

    def test_wrong_port_state_and_nonfinite_source_fail_closed(self):
        for change in ({'active': False}, {'level_id': 'OG1'}, {'z_mm': 1},
                       {'side': 'unknown'}, {'plane_x_mm': 80}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                checks._contact_strip(Scene(), dict(PORT, **change), [-10, 10], 20)
        for aperture, height in (([0, 0], 20), ([-10, math.inf], 20), ([-10, 10], 0)):
            with self.subTest(aperture=aperture, height=height), self.assertRaises(ValueError):
                checks._contact_strip(Scene(), PORT, aperture, height)

    def test_outward_side_uses_actual_minimum_cabin_edge(self):
        port = dict(PORT, side='outward', plane_x_mm=-80)
        result = checks._contact_strip(Scene(), port, [-10, 10], 20)
        self.assertEqual(result['missing_strip_mm']['x'], [-20, -10])
        self.assertTrue(result['rejection_proven'])

    def test_unchecked_mesh_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source-pinned'):
            checks.support_barrier(Scene(), 'port')


class PinTests(unittest.TestCase):
    def fixture(self, root):
        export = root / 'exports' / 'walkthrough'
        export.mkdir(parents=True)
        (root / 'source.json').write_text('{}')
        files = {'html': 'index.html', 'native_mesh': 'native-mesh.json',
                 'manifest': 'manifest.json'}
        for name in files.values():
            (export / name).write_text('{}')
        report = {'format': 'solidcraftbot.building-walkthrough-build/1',
                  'passed': True, 'files': files,
                  'source_files_sha256': {'source.json': checks.model.digest(root / 'source.json')},
                  'artifact_sha256': {key: checks.model.digest(export / name)
                                      for key, name in files.items()}}
        (export / 'build-report.json').write_text(json.dumps(report))
        mesh = object.__new__(navigation.NativeMesh)
        mesh.export = export
        return mesh

    def test_consumed_local_bundle_tamper_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            mesh = self.fixture(root)
            with patch.object(checks, 'ROOT', root):
                checks._verify_export(mesh)
                (mesh.export / 'native-mesh.json').write_text('{"changed":true}')
                with self.assertRaisesRegex(ValueError, 'consumed walkthrough artifact'):
                    checks._verify_export(mesh)

    def test_changed_source_rejects_before_support_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            mesh = self.fixture(root)
            (root / 'source.json').write_text('{"changed":true}')
            with patch.object(checks, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Stale walkthrough source'):
                checks._verify_export(mesh)


class CurrentNativeRegression(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_BF01_CURRENT_GEOMETRY_TESTS') == '1',
                         'Opt-in current pinned native export; fixture tests are independent')
    def test_current_reference_lift_port_is_not_supported(self):
        export = os.environ.get('SOLIDCRAFTBOT_FLEET_WALKTHROUGH_EXPORT',
                                'exports/building-walkthrough/pages-master-80abbc7')
        mesh = navigation.NativeMesh(checks.ROOT / export)
        result = checks.support_barrier(mesh, 'LiftPort_EG_inward')
        self.assertFalse(result['passed'])
        self.assertTrue(result['rejection_proven'])
        self.assertEqual(result['projected_contact_triangle_count'], 0)
        self.assertGreater(result['strip_width_mm'], 37)
        self.assertEqual(result['source_opening_id'], 'DLift')


if __name__ == '__main__':
    unittest.main()
