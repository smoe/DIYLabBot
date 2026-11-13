"""The storage gallery is a source-bound state plan, independent of either CAD."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import kit_storage_model as storage
import render_model_gallery as gallery


class StorageGalleryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.entry = {'id': 'storage', 'title': 'S01',
                      'sources': ['model/kit-storage-s01.shared.json', 'model/furnishings/kit-storage-s01.json'],
                      'image': 'images/storage.svg', 'render': {'kind': 'diagram', 'view': 'kit_storage'},
                      'documentation': 'docs/synthetic-storage-s01.md'}
        for name, value in [('DIRECTORY', self.directory), ('CATALOG', self.directory / 'catalog.json'),
                            ('PROVENANCE', self.directory / 'provenance.json')]:
            change = patch.object(gallery, name, value); change.start(); self.addCleanup(change.stop)
        change = patch.object(gallery, 'expected_model_sources', return_value=set(self.entry['sources']))
        change.start(); self.addCleanup(change.stop)

    def prepare(self):
        with patch('subprocess.run', side_effect=AssertionError('State plan must not execute a CAD')):
            record = gallery.render_entry(self.entry, None)
        gallery.CATALOG.write_text(json.dumps({'entries': [self.entry]}))
        gallery.PROVENANCE.write_text(json.dumps({'images': [record], 'catalog_sha256': gallery.sha(gallery.CATALOG),
                                                 'visual_review': {'passed': True}}))
        (self.directory / 'README.md').write_text(self.entry['image'] + '\n' +
                                                '\n'.join('../../' + p for p in self.entry['sources']))
        return record

    def test_one_referenced_carrier_is_present_in_each_alternative_state_without_cad(self):
        record = self.prepare()
        spec = storage.load(); data = storage.interfaces(spec, storage.parameters(spec))
        text = ''.join(ET.parse(self.directory / self.entry['image']).getroot().itertext())
        self.assertEqual(text.count(data['carrier']['id']), len(data['static_cases']))
        for location in data['locations'].values():
            self.assertIn(location['id'], text)
        self.assertFalse(record['real_inventory_managed'])
        self.assertFalse(record['transport_trajectory_implemented'])
        self.assertIn('model/extraction-kit-station.shared.json', record['dependency_files_sha256'])
        self.assertIn('scripts/kit_storage_model.py', record['producer_files_sha256'])
        self.assertIn('scripts/extraction_kit_station.py', record['producer_files_sha256'])
        self.assertLess(record['bytes'], 14000)
        with contextlib.redirect_stdout(io.StringIO()): gallery.check()

    def test_changed_projection_provider_invalidates_the_gallery_evidence(self):
        self.prepare()
        original = gallery.sha
        def changed(path):
            return '0' * 64 if Path(path) == ROOT / 'scripts/kit_storage_model.py' else original(path)
        with patch.object(gallery, 'sha', side_effect=changed), \
                self.assertRaisesRegex(ValueError, 'Image producer changed'):
            gallery.check()


if __name__ == '__main__':
    unittest.main()
