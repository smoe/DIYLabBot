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
        self.assertEqual(set(stops), {'phd', 'lab', 'microscopy', 'kitchen3008', 'kitchen', 'atrium', 'seating', 'seminar'})
        for stop in stops.values():
            self.assertTrue(all(math.isfinite(v) for v in stop['eye_mm']+stop['target_mm']))
            self.assertGreater(math.dist(stop['eye_mm'], stop['target_mm']), 100)
            if stop['scene'] == 'building':
                anchor = stop['anchor']
                if anchor['kind'] == 'seminar':
                    room = self.program['seminar_room']
                    self.assertEqual((stop['level_id'], room['area_id']), ('EG', 'R0_010'))
                    self.assertEqual(floor.point_membership(stop['eye_mm'][:2], room['room_interior_polygon_mm']), 1)
                    continue
                areas = ([self.program['microscopy']['area']] if anchor['kind'] == 'microscopy'
                         else [self.program['kitchenette']['area']] if anchor['kind'] == 'kitchenette'
                         else [self.building['atrium_access']['corridor_area']] if anchor['kind'] == 'access_entry'
                         else anchor.get('areas', [anchor.get('area')]))
                point = [v/self.parameters['display_scale'] for v in stop['eye_mm'][:2]]
                self.assertTrue(any(floor.point_membership(point, floor.outline(self.plan, area)) == 1 for area in areas))
        self.assertLess(stops['phd']['target_mm'][1], stops['phd']['eye_mm'][1])
        self.assertLess(stops['kitchen']['target_mm'][0], stops['kitchen']['eye_mm'][0])
        self.assertLess(stops['seating']['target_mm'][1], stops['seating']['eye_mm'][1])
        target = [value/self.parameters['display_scale'] for value in stops['seating']['target_mm'][:2]]
        self.assertEqual(floor.point_membership(target, floor.outline(self.plan, 'NorthCore')), 1)

    def test_window_hinges_follow_native_seminar_sashes(self):
        room = self.program['seminar_room']
        sashes = room['window_front']['sashes']
        objects = {obj['id']: obj for obj in self.program['objects'] if obj.get('mechanism') == 'window'}
        self.assertEqual(set(objects), {sash['id']+'.Hinge' for sash in sashes})
        for sash in sashes:
            obj = objects[sash['id']+'.Hinge']
            self.assertEqual(obj['level_id'], 'EG')
            self.assertEqual(obj['initial_state'], 'closed')
            self.assertEqual(obj['reference_state'], 'closed')
            self.assertEqual(obj['moving_body_ids'], sash['moving_body_ids'])
            self.assertEqual(obj['states'], {'closed': 0, 'open': sash['angle_deg']})
            self.assertEqual(obj['joint']['origin_mm'], sash['origin_mm'])
            self.assertNotIn(sash['fixed_frame_body_id'], obj['moving_body_ids'])

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
        self.assertEqual(self.program['hidden_body_ids'], {'building': ['ConceptExchange']})

    def test_interior_wall_display_policy_preserves_native_glass_materials(self):
        self.assertEqual(self.program['rendering']['opacity_by_role'],
                         {'concept_storey_wall': 1, 'circulation_wall_bridge': 1})
        changed = copy.deepcopy(self.source)
        changed['rendering']['opacity_by_role']['concept_front_glass'] = 1
        with self.assertRaisesRegex(ValueError, 'architectural opacity policy'):
            walkthrough.validate(changed)

    def test_lab_occupies_its_building_room_on_the_same_third_floor(self):
        lab = next(stop for stop in self.program['stops'] if stop['id'] == 'lab')
        building = next(stop for stop in self.program['stops'] if stop['id'] == 'phd')
        self.assertEqual(lab['scene'], 'building')
        self.assertEqual(lab['anchor']['areas'], ['R3_003'])
        self.assertEqual(lab['eye_mm'][2], building['eye_mm'][2])
        self.assertEqual(set(self.program['scene_sources']), {'building'})
        self.assertFalse(self.program['qualification']['lab_to_building_registered'])
        self.assertEqual(len(self.program['laboratories'][0]['device_instances']), 17)
        self.assertTrue(self.program['isolation']['body_ids'])
        self.assertTrue(self.program['topology'])

    def test_basic_labs_have_native_hood_controls_and_do_not_change_l01_isolation(self):
        basic = [lab for lab in self.program['laboratories'] if lab.get('furnishing_profile')]
        self.assertEqual(len(basic), 14)
        self.assertEqual(self.program['isolation']['laboratory_id'], 'Lab3003')
        for lab in basic:
            self.assertFalse(set(lab['body_ids']) & set(self.program['isolation']['body_ids']))
            controls = [obj for obj in self.program['objects'] if obj['id'].startswith(lab['id']+'.Hood01.')]
            self.assertEqual(len(controls), 4)
            sash = next(obj for obj in controls if obj['joint']['type'] == 'prismatic')
            self.assertEqual(sash['joint']['axis'], [0, 0, 1])
            self.assertEqual(sash['states'], {'closed': 0, 'open': 500})
            self.assertIn(lab['room'], sash['label'])
            self.assertTrue(all(set(obj['moving_body_ids']) <= set(lab['body_ids']) for obj in controls))

    def test_stale_reference_and_false_qualification_are_rejected(self):
        changed = copy.deepcopy(self.source)
        changed['sources']['building']['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
            walkthrough.validate(changed)
        changed = copy.deepcopy(self.source)
        changed['qualification']['collision_checked'] = True
        with self.assertRaisesRegex(ValueError, 'does not qualify'):
            walkthrough.validate(changed)

    def test_isolated_room_keeps_the_real_window_glass_and_frames(self):
        interface = stack.interfaces(self.building, self.parameters)
        laboratory = self.program['laboratories'][0]
        area = next(value for value in self.plan['areas'] if value['id'] == laboratory['area'])
        walls = {edge['wall'] for edge in area['boundary']}
        windows = [window for window in interface['exterior']['side_window_groups']
                   if window['level_id'] == laboratory['level_id'] and window['wall'] in walls]
        self.assertTrue(windows)
        for window in windows:
            self.assertTrue({window['glass_body'], window['frame_body']} <= set(self.program['isolation']['body_ids']))

    def test_functional_arm_supports_are_kept_separate_from_the_seventeen_devices(self):
        import export_building_walkthrough_freecad as export
        bindings = export.native_equipment_bindings(self.program['laboratories'])
        devices = [device for laboratory, device in bindings if not device.get('supporting_device_id')]
        supports = [device for laboratory, device in bindings if device.get('supporting_device_id')]
        self.assertEqual(len(devices), 17)
        self.assertEqual({device['supporting_device_id'] for device in supports}, {'ArmA', 'ArmB', 'ArmC'})
        for support in supports:
            owner = next(device for device in devices if device['id'] == support['supporting_device_id'])
            self.assertEqual(support['transform'], owner['transform'])

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

    def test_interaction_reach_is_a_bounded_source_assumption(self):
        self.assertEqual(self.program['interaction']['reach_mm'],self.source['interaction']['reach']['value'])
        for value in (True, float('nan'), 0, 4001):
            changed=copy.deepcopy(self.source);changed['interaction']['reach']['value']=value
            with self.subTest(value=value), self.assertRaises(ValueError): walkthrough.validate(changed)
        changed=copy.deepcopy(self.source);changed['interaction']['reach']['unit']='m'
        with self.assertRaises(ValueError): walkthrough.validate(changed)

    def test_source_matches_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        Draft202012Validator(json.loads(walkthrough.SCHEMA.read_text())).validate(self.source)


if __name__ == '__main__':
    unittest.main()
