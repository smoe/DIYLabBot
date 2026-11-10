"""Transport profiles are not geometry; model coverage remains conservative."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import render_model_gallery as gallery


class GalleryCoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        (self.root/'model').mkdir()

    def source(self,name,format):
        path=self.root/'model'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'format':format}))
        return 'model/'+name

    def expected(self):
        with patch.object(gallery,'ROOT',self.root):
            return gallery.expected_model_sources()

    def test_transport_exclusion_follows_format_not_filename(self):
        transport=self.source('renamed-contract.shared.json','solidcraftbot.cf01-sila2/1')
        geometry=self.source('cf01-sila2.shared.json','solidcraftbot.centrifuge/1')
        expected=self.expected()
        self.assertNotIn(transport,expected)
        self.assertIn(geometry,expected)
        self.assertIn('model/robot.json',expected)

    def test_unknown_shared_and_spatial_sources_still_require_images(self):
        required={self.source('new-device.shared.json','future.geometry/1')}
        for directory in ['environments','furniture','furnishings','equipment']:
            required.add(self.source(directory+'/new.json','future.layout/1'))
        self.assertTrue(required<=self.expected())

    def test_check_still_rejects_uncovered_geometry(self):
        source=self.source('unpictured.shared.json','future.geometry/1')
        page=self.root/'README.md';page.write_text('')
        with patch.object(gallery,'ROOT',self.root),patch.object(gallery,'DIRECTORY',self.root),\
             patch.object(gallery,'read',side_effect=[{'entries':[]},{'images':[]},{'format':'future.geometry/1'}]):
            with self.assertRaisesRegex(ValueError,'Model source without image:.*unpictured'):
                gallery.check()
