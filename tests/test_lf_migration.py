"""Migration keeps historical bytes/build evidence while repairing active pins."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from migrate_lf_line_endings import plan, digest, GALLERY


class LFMigrationTests(unittest.TestCase):
    def test_transitive_pins_and_build_evidence_have_distinct_meanings(self):
        leaf = b'{"dimension": 12}\r\n'
        parent = ('{"source_sha256":"' + digest(leaf) + '"}\n').encode()
        record = {'id': 'example', 'source_files_sha256': {'model/leaf.json': digest(leaf)},
                  'dependency_files_sha256': {'model/parent.json': digest(parent)},
                  'build_source_sha256': digest(leaf), 'image_sha256': 'f' * 64}
        gallery = (json.dumps({'images': [record]}, indent=2) + '\n').encode()
        changed, report = plan({'model/leaf.json': leaf, 'model/parent.json': parent, GALLERY: gallery}, 'baseline')
        after = json.loads(changed[GALLERY])['images'][0]
        self.assertEqual(json.loads(changed['model/parent.json'])['source_sha256'], digest(changed['model/leaf.json']))
        self.assertEqual(after['dependency_files_sha256']['model/parent.json'], digest(changed['model/parent.json']))
        self.assertEqual(after['build_source_sha256'], record['build_source_sha256'])
        self.assertEqual(after['image_sha256'], record['image_sha256'])
        self.assertIn('line_ending_equivalence', after)
        self.assertEqual(len(report['files']), 3)

    def test_frozen_originals_and_fixtures_stay_byte_identical(self):
        data = b'fixture\r\n'
        paths = ['docs/media/example.html', 'model/history/old.json', 'tests/fixtures/qubit-4/input.csv',
                 'cad/vendor/part/vendor-document-1.pdf', 'cad/vendor/part/vendor-model-1.step']
        changed, report = plan({p: data for p in paths}, 'baseline')
        self.assertEqual(changed, {})
        self.assertEqual(report['preserved_files_sha256'], {p: digest(data) for p in paths})

    def test_full_hash_tokens_change_but_revision_names_do_not(self):
        leaf = b'dimension\r\n'; old = digest(leaf)
        note = (old + '\n' + old[:12] + '\n' + '0' + old + '0\n').encode()
        changed, _ = plan({'model/leaf.txt': leaf, 'docs/note.md': note}, 'baseline')
        lines = changed['docs/note.md'].decode().splitlines()
        self.assertEqual(lines, [digest(leaf.replace(b'\r\n', b'\n')), old[:12], '0' + old + '0'])

    def test_already_normalized_input_has_no_changes(self):
        self.assertEqual(plan({'model/input.json': b'{"dimension":12}\n'}, 'baseline')[0], {})
