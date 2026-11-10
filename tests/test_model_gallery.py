"""Gallery coverage distinguishes geometry from versioned transport profiles."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import render_model_gallery as gallery


class ModelGalleryCoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve()
        self.models=self.root/'model'
        self.models.mkdir()
        self.gallery=self.root/'docs/models'
        (self.gallery/'images').mkdir(parents=True)
        (self.root/'README.md').write_text('Test documentation\n',encoding='utf-8')
        self.write_source('robot.json',{'format':'test.robot/1'})
        image=self.gallery/'images/robot.svg'
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><text x="10" y="30">Robot</text></svg>\n',encoding='utf-8')
        catalog={'entries':[{'id':'robot','image':'images/robot.svg',
                            'sources':['model/robot.json'],'documentation':'README.md',
                            'render':{'kind':'diagram'}}]}
        catalog_path=self.gallery/'catalog.json'
        catalog_path.write_text(json.dumps(catalog)+'\n',encoding='utf-8')
        source_hash=gallery.sha(self.models/'robot.json')
        provenance={'images':[{'id':'robot','image':'images/robot.svg',
                              'image_sha256':gallery.sha(image),
                              'source_files_sha256':{'model/robot.json':source_hash},
                              'dependency_files_sha256':{'model/robot.json':source_hash}}],
                    'visual_review':{'passed':True},'catalog_sha256':gallery.sha(catalog_path)}
        (self.gallery/'provenance.json').write_text(json.dumps(provenance)+'\n',encoding='utf-8')
        (self.gallery/'README.md').write_text('images/robot.svg ../../model/robot.json\n',encoding='utf-8')
        for name,value in [('ROOT',self.root),('DIRECTORY',self.gallery),
                           ('CATALOG',catalog_path),('PROVENANCE',self.gallery/'provenance.json')]:
            replacement=patch.object(gallery,name,value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def write_source(self,name,value):
        path=self.models/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value)+'\n',encoding='utf-8')

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            gallery.check()
        return json.loads(output.getvalue())

    def test_existing_transport_profile_needs_no_separate_geometry_image(self):
        profile=json.loads((ROOT/'model/cf01-sila2.shared.json').read_text(encoding='utf-8'))
        self.write_source('cf01-sila2.shared.json',profile)
        self.assertTrue(self.check()['passed'])

    def test_unknown_geometry_source_still_requires_an_image(self):
        self.write_source('new-station.shared.json',{'format':'test.geometry/1','bodies':[]})
        with self.assertRaisesRegex(ValueError,'Model source without image: .*new-station.shared.json'):
            self.check()

    def test_transport_name_does_not_exempt_unknown_format_or_version(self):
        for format_name in ['test.network/1','solidcraftbot.cf01-sila2/2']:
            with self.subTest(format=format_name):
                self.write_source('cf01-sila2-network.shared.json',{'format':format_name})
                with self.assertRaisesRegex(ValueError,'Model source without image: .*cf01-sila2-network.shared.json'):
                    self.check()

    def test_composition_layers_keep_their_image_requirement(self):
        self.write_source('equipment/profile.json',{'format':'solidcraftbot.cf01-sila2/1'})
        with self.assertRaisesRegex(ValueError,'Model source without image: .*equipment/profile.json'):
            self.check()


class ExistingModelGalleryTests(unittest.TestCase):
    def test_repository_gallery_checks_without_rendering_or_artifact_changes(self):
        paths=[gallery.CATALOG,gallery.PROVENANCE,gallery.DIRECTORY/'README.md']
        paths.extend((gallery.DIRECTORY/'images').glob('*'))
        before={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
        with patch.object(gallery,'input_for',side_effect=AssertionError('Coverage check requested CAD input')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                gallery.check()
        self.assertTrue(json.loads(output.getvalue())['passed'])
        self.assertEqual(before,{path:hashlib.sha256(path.read_bytes()).hexdigest() for path in before})


if __name__=='__main__':
    unittest.main()
