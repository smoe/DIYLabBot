"""Proof/mesh boundary tests; no CAD runtime or original plan geometry needed."""
import base64
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import export_building_walkthrough_freecad as export
import build_building_walkthrough as builder


class PackedMeshTests(unittest.TestCase):
    def mesh(self):
        result = export.MeshBuilder()
        result.add('WallWithOpening', [(0, 0, 0), (10, 0, 0), (0, 10, 0), (10, 10, 0)],
                   [(0, 1, 2), (1, 3, 2)], {'color': [.2, .4, .6], 'opacity': .75},
                   role='fixture_wall', level_id='FixtureFloor')
        return result

    def test_little_endian_indexed_arrays_preserve_native_triangles_and_ranges(self):
        data = self.mesh().result()
        self.assertEqual(data['vertex_count'], 4)
        self.assertEqual(data['index_count'], 6)
        positions = struct.unpack('<12f', base64.b64decode(data['positions_base64']))
        normals = struct.unpack('<12f', base64.b64decode(data['normals_base64']))
        indices = struct.unpack('<6I', base64.b64decode(data['indices_base64']))
        self.assertEqual(positions, (0., 0., 0., 10., 0., 0., 0., 10., 0., 10., 10., 0.))
        self.assertEqual(normals, (0., 0., 1.)*4)
        self.assertEqual(indices, (0, 1, 2, 1, 3, 2))
        self.assertEqual(data['groups'][0]['level_id'], 'FixtureFloor')
        self.assertEqual(data['groups'][0]['index_start'], 0)
        self.assertEqual(data['groups'][0]['index_count'], 6)
        self.assertEqual(data['groups'][0]['bounds_mm'], {'min': [0, 0, 0], 'max': [10, 10, 0]})

    def test_sharp_edges_retain_distinct_normals_and_second_group_offsets(self):
        mesh = self.mesh()
        mesh.add('RightAngle', [(20, 0, 0), (20, 10, 0), (20, 0, 10), (30, 0, 0)],
                 [(0, 1, 2), (0, 2, 3)], {'color': [1, 0, 0], 'opacity': 1}, role='fixture_corner')
        data = mesh.result()
        self.assertEqual(data['vertex_count'], 10)
        self.assertEqual(data['groups'][1]['index_start'], 6)
        self.assertEqual(data['index_count'], 12)
        self.assertEqual(data['bounds_mm']['max'], [30, 10, 10])

    def test_invalid_and_empty_native_surfaces_are_rejected(self):
        for points, triangles in [([], []), ([(0, 0, 0)]*3, [(0, 1, 2)]),
                                  ([(0, 0, 0), (1, 0, 0), (0, 1, float('nan'))], [(0, 1, 2)]),
                                  ([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, -1)])]:
            with self.subTest(points=points), self.assertRaises(ValueError):
                export.MeshBuilder().add('Invalid', points, triangles, {'color': [1, 1, 1], 'opacity': 1}, role='fixture')
        mesh = self.mesh()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            mesh.add('WallWithOpening', [(0, 0, 0)]*3, [(0, 1, 2)], {'color': [1, 1, 1], 'opacity': 1}, role='fixture')

    def test_float32_precision_loss_is_measured(self):
        mesh = export.MeshBuilder()
        mesh.add('Offset', [(12345.678901, 0, 0), (12346.678901, 0, 0), (12345.678901, 1, 0)],
                 [(0, 1, 2)], {'color': [1, 1, 1], 'opacity': 1}, role='fixture')
        self.assertGreater(mesh.result()['maximum_float32_error_mm'], 0)
        self.assertLess(mesh.result()['maximum_float32_error_mm'], .001)

    def test_native_face_segments_keep_sharp_boundaries_and_complete_coverage(self):
        reference = SimpleNamespace(Topology=([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
                                             [(0, 1, 2), (0, 3, 1)]),
                                    countSegments=lambda: 2, getSegment=lambda i: [[0], [1]][i], CountFacets=2)
        native = SimpleNamespace(Faces=[object(), object()])
        native.cleaned = lambda: native
        calls = []
        adapter = SimpleNamespace(meshFromShape=lambda **kwargs: calls.append(kwargs) or reference)
        points, faces, normals = export.native_face_mesh(native, 1., .35, adapter)
        self.assertEqual(len(faces), 2)
        self.assertEqual(len(points), 6)
        self.assertEqual(normals[:3], [(0., 0., 1.)]*3)
        self.assertEqual(normals[3:], [(0., 1., 0.)]*3)
        self.assertEqual(calls[0]['AngularDeflection'], .35)
        self.assertTrue(calls[0]['Segments'])
        reference.getSegment = lambda i: [0]
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            export.native_face_mesh(native, 1., .35, adapter)


class CheckedNativeReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name, content in [('model/fixture.json', '{}\n'), ('native.FCStd', 'fixture-native'), ('proof.json', 'fixture-proof')]:
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.report = {'format': export.REPORT_FORMATS['building'], 'passed': True,
                       'source': 'model/fixture.json', 'source_sha256': export.digest(self.root/'model/fixture.json'),
                       'source_files_sha256': {'model/fixture.json': export.digest(self.root/'model/fixture.json')},
                       'files': {'freecad': 'native.FCStd', 'freecad_validation': 'proof.json'},
                       'artifact_sha256': {'freecad': export.digest(self.root/'native.FCStd'),
                                           'freecad_validation': export.digest(self.root/'proof.json')},
                       'backends': 'both', 'cross_cad_checked': True, 'freecad_checks_passed': True}

    def write(self, report=None):
        path = self.root/'report.json'
        path.write_text(json.dumps(self.report if report is None else report))
        return path

    def test_successful_current_proof_is_accepted(self):
        self.assertEqual(export.checked_report(self.write(), 'building', self.root), self.report)

    def test_independent_freecad_proof_does_not_require_another_cad(self):
        report = {**self.report, 'backends': 'freecad', 'cross_cad_checked': False}
        self.assertEqual(export.checked_report(self.write(report), 'building', self.root), report)

    def test_solidcraft_only_proof_cannot_stand_in_for_native_freecad_shapes(self):
        report = {**self.report, 'backends': 'solidcraft', 'freecad_checks_passed': None}
        with self.assertRaisesRegex(ValueError, 'FreeCAD building proof'):
            export.checked_report(self.write(report), 'building', self.root)

    def test_source_and_native_artifact_changes_block_cached_mesh_reuse(self):
        for name in ['model/fixture.json', 'native.FCStd', 'proof.json']:
            with self.subTest(changed=name):
                path = self.root/name
                before = path.read_bytes()
                path.write_bytes(before+b'changed')
                with self.assertRaisesRegex(ValueError, 'Changed or missing'):
                    export.checked_report(self.write(), 'building', self.root)
                path.write_bytes(before)

    def test_failed_foreign_or_incomplete_proofs_are_rejected(self):
        for changes in [{'passed': False}, {'passed': 'true'}, {'format': 'unrelated/1'},
                        {'freecad_checks_passed': False},
                        {'artifact_sha256': {'freecad': self.report['artifact_sha256']['freecad']}},
                        {'source_sha256': '0'*64}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                export.checked_report(self.write({**self.report, **changes}), 'building', self.root)

    def test_dependency_cannot_escape_the_project(self):
        with self.assertRaisesRegex(ValueError, 'project-local'):
            export.verify_pins({'../foreign.json': '0'*64}, self.root)


class NativeMaterialTests(unittest.TestCase):
    def test_saved_native_material_is_used_instead_of_unchecked_context_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fixture.FCStd'
            document = ET.fromstring('<Document><ObjectData><Object name="NativeObject"><Properties>'
                '<Property name="SourceBody"><String value="StableBody" /></Property>'
                '</Properties></Object></ObjectData></Document>')
            gui = ET.fromstring('<Document><ViewProviderData><ViewProvider name="NativeObject"><Properties>'
                '<Property name="ShapeAppearance"><MaterialList file="material" version="3" /></Property>'
                '</Properties></ViewProvider></ViewProviderData></Document>')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Document.xml', ET.tostring(document))
                archive.writestr('GuiDocument.xml', ET.tostring(gui))
                archive.writestr('material', struct.pack('<5I2f3I', 1, 0, 0x4080c0ff, 0, 0, .9, .25, 0, 0, 0))
            self.assertEqual(export.native_styles(path), {'StableBody': {'color': [64/255, 128/255, 192/255], 'opacity': .75}})


class StandalonePageTests(unittest.TestCase):
    def test_another_valid_native_source_cannot_replace_the_requested_building(self):
        from unittest.mock import patch
        program = {'scene_sources': {'building': {'source': 'model/requested.json', 'source_sha256': 'a'*64}},
                   'equipment_source': {'source_sha256': 'b'*64}}
        args = SimpleNamespace(building_report=None, rebuild_building=False, no_rebuild=True)
        foreign = {'source': 'model/foreign.json', 'source_sha256': 'a'*64}
        def report(path, name):
            return foreign if name == 'building' else {'source_sha256': 'b'*64}
        with patch.object(builder, 'reports_from_program', return_value={'building': Path('building.json'), 'lab': Path('lab.json')}), \
                patch.object(export, 'checked_report', side_effect=report):
            with self.assertRaisesRegex(ValueError, 'requested walkthrough source'):
                builder.ensure_reports(program, args)

    def test_model_labels_cannot_close_the_embedded_data_script(self):
        template = '<script type="application/json">__WALKTHROUGH_DATA__</script>'
        rendered = builder.embed_html(template, {'label': '</script><script>alert(1)</script>\u2028'})
        self.assertEqual(rendered.count('</script>'), 1)
        data = rendered.removeprefix('<script type="application/json">').removesuffix('</script>')
        self.assertEqual(json.loads(data), {'label': '</script><script>alert(1)</script>\u2028'})

    def test_template_and_conflicting_source_versions_fail_closed(self):
        for template in ['missing token', '__WALKTHROUGH_DATA____WALKTHROUGH_DATA__']:
            with self.assertRaises(ValueError):
                builder.embed_html(template, {})
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            builder.merge_pins({'source': 'a'}, {'source': 'b'})


if __name__ == '__main__':
    unittest.main()
