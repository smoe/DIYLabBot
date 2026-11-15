"""Camera/source contracts; browser and native surface checks are separate."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_walkthrough as walkthrough
import building_stack as stack
import relative_floorplan as floor


class WalkthroughTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(walkthrough.SOURCE.read_text())
        cls.program = walkthrough.compile()
        cls.building = stack.load()
        cls.parameters = stack.parameters(cls.building)
        cls.plan = stack.templates(cls.building)[0]

    def test_all_requested_places_have_finite_interior_viewpoints(self):
        stops = {stop['id']: stop for stop in self.program['stops']}
        self.assertEqual(set(stops), {'phd', 'lab', 'kitchen', 'atrium', 'seating'})
        for stop in stops.values():
            self.assertTrue(all(math.isfinite(v) for v in stop['eye_mm']+stop['target_mm']))
            self.assertGreater(math.dist(stop['eye_mm'], stop['target_mm']), 100)
            if stop['scene'] == 'building':
                anchor = stop['anchor']
                areas = ([self.building['atrium_access']['corridor_area']] if anchor['kind'] == 'access_entry'
                         else anchor.get('areas', [anchor.get('area')]))
                point = [v/self.parameters['display_scale'] for v in stop['eye_mm'][:2]]
                self.assertTrue(any(floor.point_membership(point, floor.outline(self.plan, area)) == 1 for area in areas))
        self.assertLess(stops['phd']['target_mm'][1], stops['phd']['eye_mm'][1])
        self.assertLess(stops['kitchen']['target_mm'][0], stops['kitchen']['eye_mm'][0])
        self.assertLess(stops['seating']['target_mm'][1], stops['seating']['eye_mm'][1])
        target = [value/self.parameters['display_scale'] for value in stops['seating']['target_mm'][:2]]
        self.assertEqual(floor.point_membership(target, floor.outline(self.plan, 'NorthCore')), 1)

    def test_room_camera_follows_source_door_changes(self):
        plan = copy.deepcopy(self.plan)
        anchor = self.source['stops'][0]['anchor']
        opening = next(item for item in plan['openings'] if item['id'] == anchor['opening'])
        a, b = walkthrough.wall_endpoints(plan, opening['wall'])
        scale = self.parameters['display_scale']
        before = walkthrough.building_camera(anchor, plan, scale, 0, 1600)
        opening['interval'] = [value-.05 for value in opening['interval']]
        after = walkthrough.building_camera(anchor, plan, scale, 0, 1600)
        for axis in (0, 1):
            self.assertAlmostEqual(after[0][axis]-before[0][axis], -.05*(b[axis]-a[axis])*scale)

    def test_entry_must_belong_to_selected_room(self):
        anchor = copy.deepcopy(self.source['stops'][0]['anchor'])
        anchor['opening'] = 'D3_008A'
        with self.assertRaisesRegex(ValueError, 'bound the selected room'):
            walkthrough.building_camera(anchor, self.plan, self.parameters['display_scale'], 0, 1600)

    def test_camera_cannot_cross_out_of_its_room(self):
        anchor = copy.deepcopy(self.source['stops'][0]['anchor'])
        anchor['inset_mm'] = 50000
        with self.assertRaisesRegex(ValueError, 'outside its source area'):
            walkthrough.building_camera(anchor, self.plan, self.parameters['display_scale'], 0, 1600)

    def test_atrium_view_uses_existing_open_guard_and_does_not_hide_architecture(self):
        atrium = next(stop for stop in self.program['stops'] if stop['id'] == 'atrium')
        self.assertIn(atrium['anchor']['wall'], self.building['exterior']['guard_boundaries'])
        self.assertEqual(self.program['hidden_body_ids'], {'building': ['ConceptExchange'], 'lab': []})

    def test_interior_wall_display_policy_preserves_native_glass_materials(self):
        self.assertEqual(self.program['rendering']['opacity_by_role'],
                         {'concept_storey_wall': 1, 'circulation_wall_bridge': 1})
        changed = copy.deepcopy(self.source)
        changed['rendering']['opacity_by_role']['concept_front_glass'] = 1
        with self.assertRaisesRegex(ValueError, 'architectural opacity policy'):
            walkthrough.validate(changed)

    def test_lab_stays_in_separate_local_frame(self):
        lab = next(stop for stop in self.program['stops'] if stop['id'] == 'lab')
        building = next(stop for stop in self.program['stops'] if stop['id'] == 'phd')
        self.assertEqual(lab['scene'], 'lab')
        self.assertEqual(lab['eye_mm'][2], self.source['settings']['eye_height_mm'])
        self.assertGreater(building['eye_mm'][2]-lab['eye_mm'][2], 10000)
        self.assertFalse(self.program['qualification']['lab_to_building_registered'])
        self.assertNotIn('transform', self.program['scene_sources']['lab'])

    def test_stale_reference_and_false_qualification_are_rejected(self):
        changed = copy.deepcopy(self.source)
        changed['sources']['building']['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
            walkthrough.validate(changed)
        changed = copy.deepcopy(self.source)
        changed['qualification']['collision_checked'] = True
        with self.assertRaisesRegex(ValueError, 'does not qualify'):
            walkthrough.validate(changed)

    def test_camera_settings_and_ambiguous_stops_are_rejected(self):
        for value in (True, float('nan'), 0, 4001):
            changed = copy.deepcopy(self.source)
            changed['settings']['walk_speed_mm_s'] = value
            with self.assertRaisesRegex(ValueError, 'walk_speed_mm_s'):
                walkthrough.validate(changed)
        changed = copy.deepcopy(self.source)
        changed['stops'].append(copy.deepcopy(changed['stops'][0]))
        with self.assertRaisesRegex(ValueError, 'Unique viewpoints'):
            walkthrough.validate(changed)

    def test_compiler_pins_are_current_and_include_semantic_sources(self):
        pins = self.program['source_files_sha256']
        self.assertIn('model/furnishings/building-social.json', pins)
        self.assertIn('model/environments/l01.geometry.json', pins)
        self.assertIn('scripts/building_walkthrough.py', pins)
        for name, sha in pins.items():
            self.assertEqual(walkthrough.digest(walkthrough.ROOT/name), sha, name)

    def test_source_matches_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        Draft202012Validator(json.loads(walkthrough.SCHEMA.read_text())).validate(self.source)


if __name__ == '__main__':
    unittest.main()
