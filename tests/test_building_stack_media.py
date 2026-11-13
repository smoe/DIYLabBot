"""Check published proposal images and their evidence without local CAD caches."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT/'docs/media/building-stack.provenance.json'


class ProposalMediaTests(unittest.TestCase):
    def setUp(self):
        self.proof = json.loads(PROOF.read_text())

    def project(self, name):
        path = PurePosixPath(name)
        self.assertFalse(path.is_absolute())
        self.assertNotIn('..', path.parts)
        self.assertNotIn('\\', name)
        return ROOT/path

    def check_digest(self, name, digest):
        self.assertEqual(hashlib.sha256(self.project(name).read_bytes()).hexdigest(), digest, name)

    def test_public_evidence_binds_current_sources_and_producers(self):
        self.assertEqual(self.proof['format'], 'solidcraftbot.building-stack-media/1')
        sources = self.proof['source_files_sha256']
        self.assertIn('model/building-stack.shared.json', sources)
        self.assertIn('model/floor-f03.shared.json', sources)
        self.assertIn('model/environments/l01.geometry.json', sources)
        self.assertIn('scripts/render_building_stack_section.py', sources)
        self.assertIn('scripts/building_circulation.py', sources)
        for name, digest in sources.items():
            self.assertTrue(name.startswith(('model/', 'scripts/')), name)
            self.check_digest(name, digest)
        for name, digest in self.proof['documentation_files_sha256'].items():
            self.assertIn(name, {'docs/building-stack.md', 'docs/ground-floor-eg.md', 'docs/basement-kg.md', 'docs/building-exterior.md'})
            self.check_digest(name, digest)
        self.assertFalse(self.proof['original_photograph_included'])

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
