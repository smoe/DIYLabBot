"""A correct HTML hash alone must not allow an obsolete Pages snapshot."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import check_walkthrough_publication as publication


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.program = {key: [] for key in ('objects', 'interaction', 'stops', 'levels', 'settings', 'rendering', 'hidden_body_ids')}
        self.program['objects'] = [{'id': 'Kitchen1008.Microwave.Door', 'moving_body_ids': ['Door', 'Window', 'Handle']}]
        self.program['source_files_sha256'] = {'model/current.json': 'a'*64}
        self.payload = copy.deepcopy(self.program)
        for name in ('scripts/build_building_walkthrough.py', 'scripts/export_building_walkthrough_freecad.py',
                     'scripts/building_walkthrough_viewer.html', 'scripts/walkthrough_interaction.js'):
            self.payload['source_files_sha256'][name] = hashlib.sha256((publication.ROOT/name).read_bytes()).hexdigest()
        self.payload['scenes'] = {'building': {'groups': [{'id': 'Computer_MonitorScreen'}, {'id': 'Door'}]}}

    def verify(self, payload, mutate_manifest=None):
        html = ('<script id="walkthrough-data" type="application/json">'+json.dumps(payload)+'</script>').encode()
        manifest = {'html': {'sha256': hashlib.sha256(html).hexdigest(), 'bytes': len(html)},
                    'source_files_sha256': copy.deepcopy(payload['source_files_sha256'])}
        if mutate_manifest:
            mutate_manifest(manifest)
        return publication.check(html, manifest, self.program, {'Computer_MonitorScreen', 'Door'})

    def test_current_snapshot_passes(self):
        self.assertTrue(self.verify(self.payload)['passed'])

    def test_old_or_missing_interaction_is_rejected_even_with_valid_html_hash(self):
        for objects in ([], [{'id': 'Kitchen1008.Fridge.Door'}]):
            payload = copy.deepcopy(self.payload); payload['objects'] = objects
            with self.subTest(objects=objects), self.assertRaisesRegex(ValueError, 'objects'):
                self.verify(payload)

    def test_missing_equipment_or_duplicate_body_is_rejected(self):
        for groups in ([{'id': 'Door'}], [{'id': 'Door'}, {'id': 'Door'}]):
            payload = copy.deepcopy(self.payload); payload['scenes']['building']['groups'] = groups
            with self.subTest(groups=groups), self.assertRaisesRegex(ValueError, 'body coverage'):
                self.verify(payload)

    def test_old_source_or_renderer_is_rejected(self):
        for name in ('model/current.json', 'scripts/walkthrough_interaction.js'):
            payload = copy.deepcopy(self.payload); payload['source_files_sha256'][name] = '0'*64
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Stale published source'):
                self.verify(payload)

    def test_manifest_tampering_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.verify(self.payload, lambda m: m['html'].update(sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'manifest'):
            self.verify(self.payload, lambda m: m['source_files_sha256'].update({'model/current.json': '0'*64}))


if __name__ == '__main__':
    unittest.main()
