"""Portable live bundles retain real bytes, source pins and a new-world contract."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
bundle = importlib.import_module('build_building_fleet_browser')


class BrowserBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = bundle.load_browser_source()

    def write(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def files(self):
        self.write('scripts/engine.py', b'LIMIT = 3\n')
        self.write('model/room.json', b'{"dimension":42}\n')
        self.write('cad/source.FCStd', bytes(range(256)))
        files = bundle.FileSet(self.root)
        for name in ('scripts/engine.py', 'model/room.json', 'cad/source.FCStd'):
            files.add(name)
        return files

    def test_archive_rejects_escape_and_action_recordings(self):
        for name in ('/tmp/a', '../a', 'a/../../b', 'a\\b', './a', 'a//b',
                     'exports/program.json', 'exports/partial-program.json',
                     'exports/commands.jsonl', 'exports/own-controller-observations.jsonl.gz'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bundle.archive_name(name)

    def test_input_source_pin_and_post_collection_mutation_fail(self):
        path = self.write('scripts/engine.py', b'LIMIT = 3\n')
        files = bundle.FileSet(self.root)
        with self.assertRaises(ValueError):
            files.add(path, '0' * 64)
        files.add(path)
        path.write_bytes(b'LIMIT = 300\n')
        with self.assertRaises(ValueError):
            files.verify()

    def test_symbolic_or_external_input_is_not_packaged(self):
        target = self.write('scripts/engine.py', b'pass\n')
        link = self.root / 'linked.py'
        link.symlink_to(target)
        files = bundle.FileSet(self.root)
        with self.assertRaises(ValueError):
            files.add(link)
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / 'outside.py'
            external.write_bytes(b'pass\n')
            with self.assertRaises(ValueError):
                files.add(external)

    def test_recorded_program_content_is_rejected_under_an_innocent_name(self):
        path = self.write('model/not-a-recording.json', json.dumps({
            'format': 'solidcraftbot.building-fleet-program/1',
            'complete': False, 'trajectories': []}).encode())
        with self.assertRaises(ValueError):
            bundle.FileSet(self.root).read(path)

    def test_archive_is_deterministic_and_keeps_every_original_byte(self):
        files = self.files()
        inputs = {'browser_source': 'model/browser.json', 'profile': 'model/patrol.json'}
        browser = self.write('model/browser.json', bundle.json_bytes(self.source))
        files.add(browser)
        first = bundle.pack(files, self.source, inputs, self.root / 'first')
        second = bundle.pack(files, self.source, inputs, self.root / 'second')
        self.assertEqual(first, second)
        self.assertEqual((self.root / 'first/runtime.zip').read_bytes(),
                         (self.root / 'second/runtime.zip').read_bytes())
        with zipfile.ZipFile(self.root / 'first/runtime.zip') as zipped:
            self.assertEqual(set(zipped.namelist()), set(files.files))
            self.assertEqual(zipped.namelist(), sorted(zipped.namelist()))
            for name in zipped.namelist():
                raw = zipped.read(name)
                self.assertEqual(raw, (self.root / name).read_bytes())
                self.assertEqual(first['files'][name], {
                    'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        self.assertEqual(first['archive']['sha256'],
                         hashlib.sha256((self.root / 'first/runtime.zip').read_bytes()).hexdigest())

    def test_manifest_uses_the_leading_runtime_and_new_session(self):
        files = self.files()
        inputs = {'browser_source': 'model/browser.json', 'profile': 'model/patrol.json'}
        files.add(self.write(inputs['browser_source'], bundle.json_bytes(self.source)))
        manifest = bundle.pack(files, self.source, inputs, self.root / 'out')
        self.assertEqual(manifest['runtime'], self.source['runtime'])
        self.assertEqual(manifest['session'], self.source['session'])
        self.assertFalse(manifest['session']['recording_fallback'])
        self.assertFalse(manifest['qualification']['native_full_program_verified'])
        self.assertEqual(manifest['bootstrap_path'], bundle.BOOTSTRAP)
        self.assertEqual(manifest['root_dir'], '/project')
        self.assertEqual(manifest['browser_config']['sha256'],
                         files.files[inputs['browser_source']]['sha256'])

    def test_source_rejects_stale_profile_and_recording_fallback(self):
        for field in ('profile', 'session', 'runtime', 'qualification'):
            changed = copy.deepcopy(self.source)
            if field == 'profile':
                changed['sources']['patrol']['sha256'] = '0' * 64
            elif field == 'session':
                changed['session']['recording_fallback'] = True
            elif field == 'runtime':
                changed['runtime']['loader_module_url'] = 'https://example.invalid/runtime.mjs'
            else:
                changed['qualification']['full_mission_coverage_verified'] = True
            with patch.object(bundle.model, 'read_json', return_value=changed):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    bundle.load_browser_source()


if __name__ == '__main__':
    unittest.main()
