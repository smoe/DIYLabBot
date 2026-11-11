"""K01 has a small source-derived gallery plan, with separate native views."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import extraction_kit_station as station
import render_model_gallery as gallery


class KitGalleryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for name in ['model/extraction-kit-station.shared.json', 'model/extraction-kit-station.schema.json',
                     'model/extraction-automation.catalog.json', 'scripts/extraction_kit_station.py']:
            target = self.root / name;target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.directory = self.root / 'docs/models';self.directory.mkdir(parents=True)
        (self.root / 'docs/extraction-kit-station.md').write_text('Unit fixture documentation\n')
        for module, attribute, value in [(gallery, 'ROOT', self.root), (station, 'ROOT', self.root),
            (gallery, 'DIRECTORY', self.directory), (gallery, 'CATALOG', self.directory / 'catalog.json'),
            (gallery, 'PROVENANCE', self.directory / 'provenance.json')]:
            change = patch.object(module, attribute, value);change.start();self.addCleanup(change.stop)
        change = patch.object(gallery, 'expected_model_sources', return_value={'model/extraction-kit-station.shared.json'})
        change.start();self.addCleanup(change.stop)
        self.entry = {'id': 'k01', 'title': 'K01', 'sources': ['model/extraction-kit-station.shared.json'],
                      'image': 'images/k01.svg', 'render': {'kind': 'diagram', 'view': 'kit_station'},
                      'documentation': 'docs/extraction-kit-station.md'}

    def prepare(self):
        with patch('subprocess.run', side_effect=AssertionError('Diagram must not call CAD')):
            record = gallery.render_entry(self.entry, None)
        gallery.CATALOG.write_text(json.dumps({'entries': [self.entry]}))
        gallery.PROVENANCE.write_text(json.dumps({'images': [record], 'catalog_sha256': gallery.sha(gallery.CATALOG),
                                                 'visual_review': {'passed': True}}))
        (self.directory / 'README.md').write_text(self.entry['image'] + '\n../../' + self.entry['sources'][0])
        return record

    def test_roles_and_kit_names_come_from_the_pinned_source_without_cad(self):
        record = self.prepare()
        svg = ET.parse(self.directory / self.entry['image']).getroot()
        text = ''.join(svg.itertext())
        data = station.catalog(station.load(self.root / self.entry['sources'][0]))
        for kit in data['kits'].values():
            self.assertIn(kit['name'], text);self.assertIn(kit['catalog_number'], text)
        self.assertFalse(record['inventory_managed']);self.assertFalse(record['article_fit_qualified'])
        self.assertLess(record['bytes'], 14000)
        with contextlib.redirect_stdout(io.StringIO()):gallery.check()

    def test_changed_diagram_provider_invalidates_the_curated_record(self):
        self.prepare()
        with (self.root / 'scripts/extraction_kit_station.py').open('a') as file:file.write('\n# changed unit fixture\n')
        with self.assertRaisesRegex(ValueError, 'Image producer changed'):
            gallery.check()


if __name__ == '__main__':
    unittest.main()
