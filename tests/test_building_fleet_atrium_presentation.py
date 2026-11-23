"""Monitor binding is opt-in presentation, never a physical-world rewrite."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_building_fleet_demo as fleet
import build_building_walkthrough as viewer
import walkthrough_world as world


class AtriumPresentationTests(unittest.TestCase):
    def test_opt_in_overlay_adds_presentation_pins_without_changing_world(self):
        with tempfile.TemporaryDirectory(dir=fleet.ROOT / 'exports') as directory:
            directory = Path(directory)
            physical_pins = {'scripts/walkthrough_world.py': fleet.native.digest(fleet.ROOT / 'scripts/walkthrough_world.py')}
            manifest = {'format': 'solidcraftbot.building-walkthrough/1',
                'source_files_sha256': physical_pins, 'stops': [], 'objects': []}
            bundle = {'format': fleet.native.FORMAT, 'source_files_sha256': physical_pins,
                'scenes': {'building': {'groups': []}}}
            (directory / 'native-mesh.json').write_text(json.dumps(bundle))
            report = world.write(directory, manifest, {})
            originals = {path: path.read_bytes() for path in directory.iterdir()}
            source = 'model/foyer-camera-wall.shared.json'
            overlay = {'camera_wall': {'test_only': True},
                'stop': {'id': 'camera-wall'},
                'source_files_sha256': {source: fleet.native.digest(fleet.ROOT / source)}}
            with patch.object(viewer, 'compile_monitor_overlay', return_value=overlay) as compile_overlay:
                normal, normal_pins = fleet.world_presentation(report)
                compile_overlay.assert_not_called()
                html, pins = fleet.world_presentation(report, include_monitor_overlay=True)
                compile_overlay.assert_called_once()
            def payload(markup):
                return json.loads(re.search(r'<script id="walkthrough-data" type="application/json">(.*?)</script>', markup, re.S)[1])
            self.assertNotIn('camera_wall', payload(normal))
            self.assertNotIn(source, normal_pins)
            self.assertEqual(payload(html)['camera_wall'], overlay['camera_wall'])
            self.assertEqual(payload(html)['stops'], [overlay['stop']])
            self.assertEqual(pins[source], overlay['source_files_sha256'][source])
            self.assertTrue(all(path.read_bytes() == content for path, content in originals.items()))


if __name__ == '__main__':
    unittest.main()
