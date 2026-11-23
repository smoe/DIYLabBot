"""Lossless visual partitioning and unchanged opt-out presentation."""
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_progressive_presentation as progressive


def fixture():
    vertices = [0., 0., 0., 10., 0., 0., 0., 10., 0., 0., 0., 4250.]
    indices = [0, 1, 2, 0, 2, 3, 1, 2, 3]
    groups = []
    for i, level in enumerate(['EG', None, 'OG1']):
        groups.append({'id': 'Body'+str(i), 'level_id': level,
            'role': 'wall', 'color': [0.2, 0.3, 0.4], 'opacity': 1.,
            'bounds_mm': {'min': [0, 0, 0], 'max': [10, 10, 4250]},
            'index_start': i*3, 'index_count': 3})
    return {'levels': [{'id': 'EG', 'z_mm': 0}, {'id': 'OG1', 'z_mm': 4250}],
        'stops': [{'id': 'camera-wall', 'level_id': 'EG'}], 'default_stop': 'old',
        'scenes': {'building': {'positions_base64': base64.b64encode(struct.pack('<12f', *vertices)).decode(),
            'normals_base64': base64.b64encode(struct.pack('<12f', *([0., 0., 1.]*4))).decode(),
            'indices_base64': base64.b64encode(struct.pack('<9I', *indices)).decode(),
            'vertex_count': 4, 'index_count': 9, 'groups': groups}}}


def triangles(scene, group):
    positions = base64.b64decode(scene['positions_base64'])
    normals = base64.b64decode(scene['normals_base64'])
    indices = base64.b64decode(scene['indices_base64'])
    result = bytearray()
    for offset in range(group['index_start']*4, (group['index_start']+group['index_count'])*4, 4):
        i = struct.unpack_from('<I', indices, offset)[0]
        result.extend(positions[i*12:i*12+12])
        result.extend(normals[i*12:i*12+12])
    return bytes(result)


class ProgressivePresentationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for the browser initialization boundary')
    def test_native_viewer_waits_for_actual_engine_ready_once(self):
        root = Path(__file__).resolve().parents[1]
        html = progressive.attach((root/'scripts/building_walkthrough_viewer.html').read_text())
        source = html.rsplit('<script>', 1)[1].split('</script>', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'viewer.js'
            target.write_text(source)
            result = subprocess.run([shutil.which('node'), str(root/'tests/check_walkthrough_startup_gate.cjs'),
                                     str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_complete_triangle_union_and_source_unchanged(self):
        source = fixture()
        original = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as d:
            value = progressive.derive(source, d, world_report_sha256='a'*64)
            self.assertEqual(source, original)
            initial = value['scenes']['building']
            self.assertEqual(initial['index_count'], 6)
            self.assertEqual(value['default_stop'], 'camera-wall')
            chunks = [initial]
            for ref in value['progressive_geometry']['chunks']:
                raw = (Path(d)/ref['url']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['sha256'])
                self.assertEqual(len(raw), ref['bytes'])
                decoded = gzip.decompress(raw)
                self.assertEqual(len(decoded), ref['decoded_bytes'])
                chunks.append(json.loads(decoded))
            actual = {}
            for chunk in chunks:
                for group in chunk['groups']:
                    if not group.get('pending_geometry'):
                        self.assertNotIn(group['id'], actual)
                        actual[group['id']] = triangles(chunk, group)
            full = source['scenes']['building']
            self.assertEqual(actual, {g['id']: triangles(full, g) for g in full['groups']})
            self.assertEqual(sum(c['index_count'] for c in chunks), full['index_count'])

    def test_deferred_bodies_keep_identity_and_zero_draws(self):
        with tempfile.TemporaryDirectory() as d:
            value = progressive.derive(fixture(), d, world_report_sha256='a'*64)
        pending = value['scenes']['building']['groups'][-1]
        self.assertEqual(pending['id'], 'Body2')
        self.assertEqual(pending['index_count'], 0)
        self.assertEqual(pending['pending_index_count'], 3)
        self.assertTrue(pending['pending_geometry'])
        self.assertEqual(pending['index_start'], 6)

    def test_invalid_native_partition_fails(self):
        data = fixture()
        data['scenes']['building']['groups'][1]['index_start'] = 0
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(ValueError, 'partition'):
            progressive.derive(data, d, world_report_sha256='a'*64)

    def test_unknown_level_fails(self):
        data = fixture()
        data['scenes']['building']['groups'][0]['level_id'] = 'unknown'
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(ValueError, 'Known source levels'):
            progressive.derive(data, d, world_report_sha256='a'*64)

    def test_original_triangle_order_winding_and_normals_retained(self):
        scene = fixture()['scenes']['building']
        part = progressive.packed(scene, {'Body2'})
        self.assertEqual(triangles(scene, scene['groups'][2]), triangles(part, part['groups'][0]))
        self.assertEqual(part['vertex_count'], 3)


if __name__ == '__main__':
    unittest.main()
