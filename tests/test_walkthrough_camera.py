"""Camera contact regressions without native CAD or a network connection."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_walkthrough as walkthrough


class CameraNavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed for native-mesh camera maths')
    def test_continuous_native_mesh_contacts(self):
        result = subprocess.run(['node', str(ROOT/'tests/check_walkthrough_camera.cjs')],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_rejects_invalid_camera_envelopes_before_build(self):
        original = json.loads((ROOT/'model/building-walkthrough.shared.json').read_text())
        for field, value in [('camera_radius_mm', -1), ('contact_margin_mm', 0),
                             ('max_contact_iterations', 1), ('max_slides', 0), ('basis', 'measured')]:
            source = copy.deepcopy(original)
            source['navigation'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                walkthrough.validate(source)


if __name__ == '__main__':
    unittest.main()
