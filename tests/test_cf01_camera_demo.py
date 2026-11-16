import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_cf01_camera_demo as demo
import camera_revision


class CameraDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mesh = demo.read_mesh(demo.BASE.with_suffix('.html'))
        cls.current = copy.deepcopy(cls.mesh)
        cls.current['robot_parameters'] = demo.robot_spec.parameters(demo.robot_spec.load(
            demo.ROOT / 'model/robot.json', cls.mesh['scene']['robot_parameter_overrides_mm']))

    def test_frames_use_long_link_variant_and_existing_mounts(self):
        scene, tip = demo.camera_metadata(self.current)
        self.assertEqual(scene['group'], 'Arm.L1_Turret')
        self.assertEqual(tip['group'], 'Arm.L6_BareFlange')
        self.assertEqual(tip['optical_frame']['p'], [54, -55, 780])
        self.assertEqual(scene['optical_frame']['p'], [80, -150, 370])
        self.assertFalse(tip['calibration_verified'])

    def test_mismatched_variant_or_camera_mount_is_rejected(self):
        altered = copy.deepcopy(self.current)
        altered['robot_parameters']['upper_len'] = 200
        with self.assertRaisesRegex(ValueError, 'variant'):
            demo.camera_metadata(altered)
        altered = copy.deepcopy(self.current)
        next(b for b in altered['bodies'] if b['id'] == 'Arm.C_tip_lens_ENVELOPE')['group'] = 'Arm.L1_Turret'
        with self.assertRaisesRegex(ValueError, 'different link'):
            demo.camera_metadata(altered)

    @unittest.skipUnless(demo.SCENE_REPORT.is_file(), 'Requires the native CF01 camera-scene check')
    def test_camera_revision_preserves_motion_and_all_non_camera_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'demo.html'
            report = demo.build(target)
            actual = demo.read_mesh(target)
            self.assertEqual(len(actual.pop('camera_views')), 2)
            non_camera = lambda mesh: [b for b in mesh['bodies'] if b['role'] not in ('camera_envelope', 'camera_mount')]
            self.assertEqual(non_camera(actual), non_camera(self.mesh))
            self.assertEqual(actual['unload_program'], self.mesh['unload_program'])
            self.assertEqual(report['compiled_program_canonical_sha256'], demo.canonical(self.mesh['unload_program']))
            self.assertEqual(json.loads(target.with_suffix('.provenance.json').read_text()), report)

    def test_unchecked_geometry_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'check.json'
            path.write_text(json.dumps({'passed': False, 'preview_only': True}))
            with self.assertRaisesRegex(ValueError, 'passed native'):
                demo.build(Path(directory) / 'demo.html', path)


class CameraRevisionTests(unittest.TestCase):
    def test_only_camera_changes_allow_non_camera_geometry_reuse(self):
        current = json.loads((demo.ROOT / 'model/robot.json').read_text())
        previous = copy.deepcopy(current)
        previous['parameters']['cam_tip_front_z']['expression'] = '46'
        with tempfile.TemporaryDirectory() as directory:
            old, new = [Path(directory) / name for name in ('old.json', 'new.json')]
            old.write_text(json.dumps(previous)); new.write_text(json.dumps(current))
            self.assertTrue(camera_revision.verify(old, new, demo.sha(old))['non_camera_source_equal'])
            current['parameters']['upper_len']['expression'] = '221'
            new.write_text(json.dumps(current))
            with self.assertRaisesRegex(ValueError, 'Non-camera arm'):
                camera_revision.verify(old, new, demo.sha(old))
            with self.assertRaisesRegex(ValueError, 'geometry pin'):
                camera_revision.verify(old, new, '0' * 64)

    def test_camera_parameter_cannot_change_retained_geometry(self):
        spec = json.loads((demo.ROOT / 'model/robot.json').read_text())
        spec['parameters']['upper_len']['expression'] = 'cam_tip_range'
        with self.assertRaisesRegex(ValueError, 'outside camera operations'):
            camera_revision.unchanged_arm(spec)


if __name__ == '__main__':
    unittest.main()
