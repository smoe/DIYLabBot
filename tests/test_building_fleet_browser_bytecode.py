"""Optional import artifacts remain tied to their unchanged readable sources."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import build_building_fleet_browser as bundle


class CheckedImportCacheTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('python3.14'), 'Optional CPython 3.14 compiler is not installed')
    def test_checked_source_hash_and_original_readable_file_are_both_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'scripts/building_fleet_fixture.py'
            source.parent.mkdir();source.write_bytes(b'value = 7\n')
            files=bundle.FileSet(root);name=files.add(source)
            with patch.object(bundle,'ROOT',root):
                result=bundle.prepare_bytecode(files,root/'out',shutil.which('python3.14'))
            self.assertEqual(result['cache_tag'],'cpython-314')
            row=result['sources'][name];artifact=root/row['artifact'];raw=artifact.read_bytes()
            self.assertEqual(raw[:4].hex(),result['magic_number_hex'])
            self.assertEqual(int.from_bytes(raw[4:8],'little'),3)
            self.assertEqual(row['source_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertIn(name,files.files);files.verify()
            source.write_bytes(b'value = 8\n')
            with self.assertRaisesRegex(ValueError,'Stale runtime input'):
                files.verify()


if __name__=='__main__':unittest.main()
