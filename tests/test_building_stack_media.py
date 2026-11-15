"""Check published proposal images and their evidence without local CAD caches."""
import hashlib
import json
import copy
from pathlib import Path, PurePosixPath
import struct
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT/'docs/media/building-stack.provenance.json'
HISTORICAL_FIELDS = ('revision', 'source', 'source_sha256', 'source_files_sha256',
                     'native_build_report', 'native_summary', 'native_files', 'native_artifact_sha256')


class ProposalMediaTests(unittest.TestCase):
    def setUp(self):
        self.proof = json.loads(PROOF.read_text())
        self.current_ref = self.proof['current_front_access_correction']
        self.current = json.loads(self.project(self.current_ref['path']).read_text())

    def project(self, name):
        path = PurePosixPath(name)
        self.assertFalse(path.is_absolute())
        self.assertNotIn('..', path.parts)
        self.assertNotIn('\\', name)
        return ROOT/path

    def check_digest(self, name, digest):
        self.assertEqual(hashlib.sha256(self.project(name).read_bytes()).hexdigest(), digest, name)

    def check_reference(self, reference):
        self.project(reference['path'])
        self.assertRegex(reference['sha256'], r'^[0-9a-f]{64}$')
        self.assertIs(type(reference['bytes']), int)
        self.assertGreater(reference['bytes'], 0)

    def assert_current_scope(self, current):
        scope = current['native_scope']
        self.assertEqual(scope['build_backends'], 'freecad')
        self.assertIs(scope['full_building_cross_cad_checked'], False)
        self.assertIs(scope['full_building_cross_cad_check_repeated'], False)
        self.assertEqual(scope['new_site_bodies'], 5)
        self.assertNotIn('unchanged_building_brep_bodies', scope)
        self.assertEqual(scope['unchanged_building_geometry_bodies'], 1933)
        self.assertEqual(scope['semantically_unchanged_non_site_operations'], 2755)
        self.assertEqual(scope['reopened_non_site_bodies_checked'], 1933)
        self.assertEqual(scope['reopened_brep_byte_identical_bodies'], 1812)
        self.assertEqual(scope['reopened_brep_reserialized_xor_zero_bodies'], 121)
        self.assertEqual(scope['reopened_brep_maximum_xor_mm3'], 0)
        self.assertIs(scope['read_only_audit_inputs_stable'], True)
        self.assertIs(scope['read_only_audit_native_files_modified'], False)
        self.assertEqual(scope['exact_site_step_comparisons'], 5)
        self.assertEqual(scope['maximum_site_step_xor_mm3'], 0)
        self.assertEqual(scope['site_pair_checks'], 10)
        self.assertEqual(scope['front_band_continuity_checks'], 2)
        expected = dict.fromkeys([
            'metric_survey', 'transport', 'hardware', 'building_safety', 'load',
            'basement_modeled', 'roof_modeled', 'ground_floor_as_built', 'robot_navigation'], False)
        expected.update(basement_modeled=True, roof_modeled=True)
        self.assertEqual(current['qualification'], expected)
        self.assertIs(current['original_photographs_included'], False)
        self.assertTrue(current['limitations'])

    def test_public_evidence_binds_current_sources_and_producers(self):
        self.assertEqual(self.proof['format'], 'solidcraftbot.building-stack-media/1')
        self.assertEqual(self.current['format'], 'solidcraftbot.front-access-media/1')
        self.check_digest(self.current_ref['path'], self.current_ref['sha256'])
        self.assertEqual(self.project(self.current_ref['path']).stat().st_size, self.current_ref['bytes'])
        self.assertEqual(self.current_ref['image_ids'], ['overview', 'lab_3_003'])
        self.assertIs(self.current_ref['top_level_native_binding_is_historical'], True)
        # Original top-level pins describe their archived revision, rather than
        # silently being rebound to today's five-body site update.
        for name, digest in self.proof['source_files_sha256'].items():
            self.project(name)
            self.assertRegex(digest, r'^[0-9a-f]{64}$')
        sources = self.current['source_files_sha256']
        self.assertIn('model/building-stack.shared.json', sources)
        self.assertIn('model/floor-f03.shared.json', sources)
        self.assertIn('model/environments/l01.geometry.json', sources)
        self.assertIn('scripts/render_building_stack_highlight.py', sources)
        self.assertIn('scripts/building_circulation.py', sources)
        for name, digest in sources.items():
            self.assertTrue(name.startswith(('model/', 'scripts/')), name)
            self.check_digest(name, digest)
        current_docs = self.current['documentation_files_sha256']
        self.assertEqual(set(current_docs), {'docs/building-exterior.md'})
        for name, digest in self.proof['documentation_files_sha256'].items():
            self.assertIn(name, {'docs/building-stack.md', 'docs/ground-floor-eg.md', 'docs/basement-kg.md', 'docs/building-exterior.md', 'docs/building-alignment.md'})
            self.assertRegex(digest, r'^[0-9a-f]{64}$')
            if name in current_docs:
                self.assertEqual(digest, current_docs[name])
                self.check_digest(name, digest)
        self.assertFalse(self.proof['original_photograph_included'])

    def test_current_images_bind_the_scoped_freecad_proof_and_current_producers(self):
        self.assert_current_scope(self.current)
        self.check_reference(self.current['native_build_report'])
        self.check_reference(self.current['native_site_proof'])
        self.check_reference(self.current['native_readonly_audit'])
        self.assertIn('before saving', self.current['native_site_proof_scope'])
        self.assertEqual(self.current['source'], 'model/building-stack.shared.json')
        self.check_digest(self.current['source'], self.current['source_sha256'])
        declared = {item['id']: item for item in self.current['images']}
        self.assertEqual(set(declared), set(self.current_ref['image_ids']))
        for image in self.proof['images']:
            if image['id'] not in declared:
                continue
            current = declared[image['id']]
            for key in ('path', 'sha256', 'bytes', 'pixels', 'source', 'native_model',
                        'native_model_sha256', 'render_report', 'visual_review'):
                self.assertEqual(image[key], current[key], (image['id'], key))
            self.assertIn('FreeCAD', image['source'])
            self.assertIn('Chromium WebGL2', image['source'])
            self.assertNotIn('SolidCraft', image['source'])
            self.assertTrue(image['native_model'].endswith('.FCStd'))
            self.check_reference(image['render_report'])
            self.assertEqual(image['render_producers'], self.current['render_producers'])
            self.assertEqual(current['render_producers'], self.current['render_producers'])
            self.assertEqual(image['rendering']['engine'], 'Chromium WebGL2')
            self.assertEqual(image['rendering']['page_errors'], [])
            for producer in image['render_producers'].values():
                self.check_reference(producer)
            for name, digest in image['source_files_sha256'].items():
                self.project(name)
                self.assertRegex(digest, r'^[0-9a-f]{64}$')
                if name.startswith(('model/', 'scripts/')):
                    self.check_digest(name, digest)
            if 'producer' in image:
                self.check_digest(image['producer']['path'], image['producer']['sha256'])

    def test_historical_native_and_other_image_bindings_remain_historical(self):
        binding = self.current['historical_building_binding']
        self.assertEqual(binding['fields'], list(HISTORICAL_FIELDS))
        projection = {key: self.proof[key] for key in HISTORICAL_FIELDS}
        historical = [image for image in self.proof['images'] if image['id'] not in self.current_ref['image_ids']]
        self.assertEqual(binding['image_ids'], [image['id'] for image in historical])
        projection['historical_images'] = historical
        historical_docs = {name: digest for name, digest in self.proof['documentation_files_sha256'].items()
                           if name not in self.current['documentation_files_sha256']}
        self.assertEqual(binding['documentation_paths'], list(historical_docs))
        projection['historical_documentation_files_sha256'] = historical_docs
        digest = hashlib.sha256(json.dumps(projection, sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).encode()).hexdigest()
        self.assertEqual(digest, binding['sha256'])

    def test_current_site_scope_rejects_full_building_or_safety_escalation(self):
        for field, value in [('build_backends', 'both'),
                             ('full_building_cross_cad_checked', True),
                             ('full_building_cross_cad_check_repeated', True),
                             ('reopened_brep_byte_identical_bodies', 1933),
                             ('read_only_audit_native_files_modified', True)]:
            changed = copy.deepcopy(self.current)
            changed['native_scope'][field] = value
            with self.subTest(scope=field), self.assertRaises(AssertionError):
                self.assert_current_scope(changed)
        changed = copy.deepcopy(self.current)
        changed['qualification']['building_safety'] = True
        with self.assertRaises(AssertionError):
            self.assert_current_scope(changed)

    def test_proposal_views_and_circulation_detail_are_bound_and_visually_reviewed(self):
        images = self.proof['images']
        self.assertEqual({image['id'] for image in images}, {'overview', 'atrium', 'circulation', 'ground', 'basement', 'front_glass', 'roof', 'section_svg', 'section_png', 'ground_svg', 'lab_3_003'})
        self.assertEqual(len({image['path'] for image in images}), len(images))
        for image in images:
            path = self.project(image['path'])
            self.assertTrue(image['path'].startswith(('docs/media/', 'docs/models/images/')))
            self.check_digest(image['path'], image['sha256'])
            self.assertEqual(path.stat().st_size, image['bytes'])
            self.assertTrue(image['visual_review']['passed'])
            if path.suffix == '.png':
                data = path.read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', data[16:24])
                self.assertEqual([width, height], image['pixels'])
                self.assertGreaterEqual(width, 1280)
                self.assertGreaterEqual(height, 900)
            else:
                svg = ET.parse(path).getroot()
                tags = {element.tag.rsplit('}', 1)[-1] for element in svg.iter()}
                self.assertFalse(tags & {'image', 'script', 'foreignObject'})
                self.assertFalse(any('href' in key.lower() for element in svg.iter() for key in element.attrib))

    def test_highlight_identifies_the_source_room_without_geometry_or_furniture_changes(self):
        view = next(image for image in self.proof['images'] if image['id'] == 'lab_3_003')
        self.assertEqual(view['source_room']['level_id'], 'OG3')
        self.assertEqual(view['source_room']['area_id'], 'R3_003')
        self.assertEqual(view['source_room']['floor_body_id'], 'OG3__Area_R3_003')
        self.assertEqual(len(view['source_room']['wall_body_ids']), 5)
        self.assertTrue(view['native_model_unchanged'])
        self.assertFalse(view['geometry_added'])
        self.assertFalse(view['l01_furnishings_instantiated'])
        self.assertEqual({item['command'] for item in view['view_commands']},
                         {'browser.visibility', 'appearance.assign'})

    def test_native_summary_preserves_assumptions_and_qualification_limits(self):
        summary = self.proof['native_summary']
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['backends'], 'both')
        self.assertTrue(summary['cross_cad_checked'])
        self.assertEqual(self.proof['level_ids'], ['KG', 'EG', 'OG1', 'OG2', 'OG3'])
        self.assertEqual(self.proof['level_elevations_assumed_mm'], [-4250, 0, 4250, 8500, 12750])
        self.assertEqual(self.proof['ground_fill_levels'], ['EG'])
        self.assertEqual(self.proof['xy_calibration'], None)
        expected = dict.fromkeys([
            'metric_survey', 'transport', 'hardware', 'building_safety', 'load',
            'basement_modeled', 'roof_modeled', 'ground_floor_as_built', 'robot_navigation'], False)
        expected['roof_modeled'] = True
        expected['basement_modeled'] = True
        self.assertEqual(self.proof['qualification'], expected)
        self.assertEqual(self.proof['ground_cover_method'], 'union_filled')
        self.assertEqual(self.proof['ground_floor']['source'], 'model/ground-floor-eg.shared.json')

    def test_rotated_glass_roof_covers_all_corridors_without_changing_floor_apertures(self):
        roof = self.proof['roof']
        self.assertEqual(roof['axis'], 'X')
        self.assertEqual(roof['profile_axis'], 'Y')
        self.assertEqual(set(roof['covered_corridor_area_ids']),
                         {'C3_018', 'C3_019', 'C3_020', 'C3_021'})
        self.assertTrue(roof['native_corridor_roof_checks_passed'])
        self.assertTrue(roof['source_contour_derived'])
        self.assertFalse(roof['structural_qualified'])
        self.assertFalse(roof['weather_sealing_qualified'])
        self.assertFalse(roof['safety_qualified'])
        self.assertEqual(self.proof['ground_fill_levels'], ['EG'])

    def test_building_circulation_preserves_owner_door_rule_and_modeled_basement(self):
        circulation = self.proof['circulation']
        self.assertEqual(circulation['door_walls'], {'outward': 'W049', 'inward': 'W062'})
        self.assertEqual(circulation['doors_by_level'], {
            'KG': ['inward'], 'EG': ['outward', 'inward'], 'OG1': ['outward'],
            'OG2': ['outward'], 'OG3': ['outward']})
        self.assertEqual(circulation['deferred_stops'], [])
        self.assertEqual(circulation['stair_core_count'], 1)
        self.assertEqual(circulation['stair_connection_count'], 4)
        self.assertEqual(circulation['internal_area'], 'R3_028')
        self.assertEqual(circulation['external_area'], 'R3_017')
        self.assertEqual(circulation['external_served_extent'], {'from_level': 'EG', 'to_level': 'ROOF'})
        self.assertEqual(circulation['external_ground_exit_area'], 'ExternalStairGround')
        self.assertEqual(circulation['cabin_instance_count'], 1)
        self.assertTrue(circulation['native_scoped_checks_passed'])
        self.assertFalse(circulation['real_access_qualified'])


if __name__ == '__main__':
    unittest.main()
