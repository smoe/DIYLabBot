"""Same-origin Python delivery retains pinned original runtime bytes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_building_fleet_browser as bundle


class OriginalCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=bundle.ROOT / 'exports')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.files = {}
        for name in (*sorted(bundle.PYTHON_CORE_FILES), 'NOTICE'):
            raw = ('original-file-' + name).encode()
            (self.directory / name).write_bytes(raw)
            self.files[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        self.source = copy.deepcopy(bundle.load_browser_source())

    def descriptor(self, files=None):
        value = {'format': 'solidcraftbot.building-fleet-python-core/1',
            'version': self.source['runtime']['version'], 'files': self.files if files is None else files}
        path = self.directory / 'descriptor.json'
        path.write_bytes(bundle.json_bytes(value))
        self.source['sources']['python_core'] = {'path': path.relative_to(bundle.ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_pack_copies_unchanged_files_outside_the_engine_archive(self):
        self.descriptor()
        core = bundle.collect_python_core(self.source, self.directory)
        files = bundle.FileSet()
        files.add(self.directory / 'descriptor.json')
        output = self.directory / 'output'
        manifest = bundle.pack(files, self.source, {'browser_source': (self.directory / 'descriptor.json').relative_to(bundle.ROOT).as_posix()}, output, python_core=core)
        self.assertEqual(manifest['python_core']['source'], self.source['sources']['python_core'])
        self.assertEqual(manifest['python_core']['files'], self.files)
        for name in self.files:
            self.assertEqual((output / core['directory'] / name).read_bytes(),
                             (self.directory / name).read_bytes())
        self.assertTrue((output / 'runtime.zip').is_file())

    def test_missing_core_member_or_altered_original_is_rejected(self):
        reduced = copy.deepcopy(self.files)
        reduced.pop('pyodide.asm.wasm')
        self.descriptor(reduced)
        with self.assertRaisesRegex(ValueError, 'original Python'):
            bundle.collect_python_core(self.source, self.directory)
        self.descriptor()
        (self.directory / 'pyodide.asm.wasm').write_bytes(b'changed runtime')
        with self.assertRaisesRegex(ValueError, 'Stale runtime'):
            bundle.collect_python_core(self.source, self.directory)

    def test_changed_descriptor_is_rejected_before_collecting_runtime(self):
        self.descriptor()
        (self.directory / 'descriptor.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Changed, missing'):
            bundle.collect_python_core(self.source, self.directory)


if __name__ == '__main__':
    unittest.main()
