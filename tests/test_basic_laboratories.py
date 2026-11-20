"""Owner-confirmed room use and referenced, unscaled laboratory furnishings."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import basic_laboratories as basic
import building_laboratories as labs
import building_stack as stack
import lab_room_model as room
import relative_floorplan as floor


class BasicLaboratoriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = json.loads(stack.SOURCE.read_text())
        cls.p = stack.parameters(cls.stack)
        cls.source = labs.validate(labs.read(cls.stack['sources']['laboratories']))
        cls.profile = basic.load(cls.source['basic_profile'])
        cls.reference = room.load()
        cls.plans = {level: stack.level_plan(cls.stack, level) for level in ('EG', 'OG1', 'OG2', 'OG3')}
        cls.designs, cls.built = {}, {}
        for index, item in enumerate(cls.source['basic_laboratories']):
            cls.designs[item['id']] = basic.layout(cls.profile, item, cls.plans[item['level']], cls.p, cls.reference)
            cls.built[item['id']] = basic.compile_instance(cls.source['basic_profile'], cls.profile, item,
                cls.plans[item['level']], cls.p, index*cls.p['floor_pitch_mm'], cls.reference)

    def test_room_assignments_and_explicit_non_laboratories(self):
        selected = {(v['level'], v['area']) for v in self.source['laboratories']+self.source['basic_laboratories']}
        expected = {('EG', 'R0_'+v) for v in ('001', '003', '015')}
        expected |= {(level, 'R3_'+v) for level in ('OG1', 'OG2', 'OG3') for v in ('001', '003', '015', '016')}
        self.assertEqual(selected, expected)
        excluded = {(v['level'], v['area']): v['usage'] for v in self.source['excluded_rooms']}
        self.assertFalse(selected & set(excluded))
        for level in ('OG1', 'OG2', 'OG3'):
            self.assertEqual(excluded[level, 'R3_004'], 'office')
            for name in ('005', '010', '014'):
                self.assertEqual(excluded[level, 'R3_'+name], 'storage')
        self.assertEqual(excluded['EG', 'R0_014A'], 'storage')
        self.assertEqual(excluded['EG', 'R0_002'], 'non_laboratory')

    def test_schema_and_pinned_references(self):
        import jsonschema
        jsonschema.validate(self.profile, json.loads((ROOT/'model/basic-laboratory-furnishings.schema.json').read_text()))
        jsonschema.validate(self.source, json.loads(labs.SCHEMA.read_text()))
        paths = basic.dependencies(self.source['basic_profile'])
        self.assertIn(ROOT/'scripts/basic_laboratories.py', paths)
        self.assertIn(ROOT/'model/furniture/laboratory.catalog.json', paths)
        changed = copy.deepcopy(self.profile)
        changed['hood_source']['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
            basic.validate(changed)

    def test_invalid_dimensions_and_conflicting_use_are_rejected(self):
        for name, value in [('fit_increment', 0), ('island_search_step', float('nan')), ('compact_aisle', 400)]:
            changed = copy.deepcopy(self.profile)
            changed['parameters'][name]['value'] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                basic.validate(changed)
        changed = copy.deepcopy(self.source)
        changed['basic_laboratories'][0]['level'] = 'OG1'
        changed['basic_laboratories'][0]['area'] = 'R3_004'
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            labs.validate(changed)

    def test_sinks_use_nearest_usable_lift_corner_and_adjacent_hood(self):
        for identity, design in self.designs.items():
            with self.subTest(room=identity):
                wet, hood = [next(f for f in design['fixtures'] if f['kind'] == kind) for kind in ('wet', 'hood')]
                minimum = self.reference['parameters']['wet_length']['range'][0]+design['wall_margin_mm']
                usable = [c for c in design['corner_candidates'] if c['usable_wall_length_mm'] >= minimum]
                self.assertEqual(design['corner'], min(usable, key=lambda c: (c['distance_to_lift_mm'], c['point_mm'])))
                self.assertLessEqual(basic.separation(wet['polygon_mm'], hood['polygon_mm']), 200)
                self.assertGreaterEqual(basic.separation(wet['polygon_mm'], hood['polygon_mm']), 50-1e-6)
                self.assertLessEqual(wet['corner_setback_mm'], design['wall_margin_mm']+self.profile['parameters']['maximum_corner_setback']['value'])

    def test_all_footprints_are_inside_actual_room_and_clear_of_doors(self):
        for identity, design in self.designs.items():
            for fixture in design['fixtures']:
                with self.subTest(room=identity, fixture=fixture['id']):
                    self.assertTrue(basic.fits(fixture['polygon_mm'], design['outline'], design['wall_margin_mm']))
                    for door in design['keepouts']:
                        self.assertGreater(basic.separation(fixture['polygon_mm'], door['polygon']), 0)
                    for other in design['fixtures']:
                        if other is fixture or fixture['kind'] == other['kind'] == 'island':
                            continue  # Two halves deliberately share their back edge.
                        self.assertGreater(basic.separation(fixture['polygon_mm'], other['polygon_mm']), 0)
                        self.assertGreater(basic.separation(fixture['access_polygon_mm'], other['polygon_mm']), 0)

    def test_double_benches_keep_opposite_fronts_and_declared_aisles(self):
        missing = []
        for identity, design in self.designs.items():
            islands = [f for f in design['fixtures'] if f['kind'] == 'island']
            if not islands:
                missing.append(identity)
                self.assertTrue(any('No central double bench' in note for note in design['notes']))
                continue
            self.assertEqual({f['front'] for f in islands}, {'negative_x', 'positive_x'})
            self.assertEqual(len(islands), 2)
            self.assertAlmostEqual(basic.separation(*[f['polygon_mm'] for f in islands]), 0)
            for island in islands:
                for other in design['fixtures']:
                    if other['kind'] != 'island':
                        self.assertGreaterEqual(basic.separation(island['polygon_mm'], other['polygon_mm'])+1e-6,
                                                design['settings']['minimum_aisle'])
        self.assertEqual(missing, [])

    def test_compact_sizes_are_explicit_and_within_reference_ranges(self):
        for design in self.designs.values():
            for name in ('bench_depth', 'window_bench_depth', 'island_half_width'):
                low, high = self.reference['parameters'][name]['range']
                self.assertLessEqual(low, design['reference_parameters'][name])
                self.assertLessEqual(design['reference_parameters'][name], high)
            if design['compact']:
                self.assertEqual(design['settings']['minimum_aisle'], self.profile['parameters']['compact_aisle']['value'])
                self.assertTrue(any('Compact' in note for note in design['notes']))

    def test_each_room_retains_window_and_side_benches(self):
        for identity, design in self.designs.items():
            kinds = {f['kind'] for f in design['fixtures']}
            with self.subTest(room=identity):
                self.assertTrue({'wet', 'hood', 'window', 'side'} <= kinds)

    def test_many_labs_share_one_door_graph_per_floor(self):
        compiled = labs.compile(self.stack['sources']['laboratories'], self.plans, self.p,
            [{'id': name, 'z_mm': index*self.p['floor_pitch_mm']} for index, name in enumerate(self.plans)])
        self.assertEqual(len(compiled['laboratories']), 15)
        identities = [edge['id'] for edge in compiled['topology']]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual({edge['level_id'] for edge in compiled['topology']}, set(self.plans))
        equipped = [lab for lab in compiled['laboratories'] if lab.get('layout_source')]
        self.assertEqual([lab['id'] for lab in equipped], ['Lab3003'])
        self.assertEqual(equipped[0]['layout_source'], self.source['laboratories'][0]['layout_source'])

    def test_world_ids_joints_and_catalog_roles_are_preserved(self):
        ids, operations, joints = set(), set(), set()
        for identity, built in self.built.items():
            bodies = {b['id']: b for b in built['bodies']}
            self.assertEqual(len(bodies), len(built['bodies']))
            self.assertFalse(set(bodies) & ids)
            ids.update(bodies)
            for operation in built['operations']:
                self.assertNotIn(operation['id'], operations)
                operations.add(operation['id'])
                self.assertIn(operation['body'], bodies)
                json.dumps(operation['shape'], allow_nan=False)
            moving = set()
            for joint in built['joints']:
                self.assertNotIn(joint['id'], joints)
                joints.add(joint['id'])
                self.assertFalse(set(joint['moving_body_ids']) & moving)
                moving.update(joint['moving_body_ids'])
                self.assertTrue(set(joint['moving_body_ids']) <= set(bodies))
                self.assertAlmostEqual(math.hypot(*joint['axis']), 1)
                self.assertAlmostEqual(math.hypot(*joint['front']), 1)
            hood_joints = [j for j in built['joints'] if j.get('equipment_asset')]
            self.assertEqual(len(hood_joints), 4)
            self.assertEqual({j['equipment_role'] for j in hood_joints}, {'vertical_sash', 'hinged_cabinet_door'})
            self.assertTrue(built['interface']['native_equipment_included'])
            self.assertFalse(built['interface']['device_instances'])
            self.assertTrue(all(b['role'] != 'concept_social_furniture' for b in bodies.values()))

    def test_room_translation_moves_bodies_and_joint_frames_without_scaling(self):
        item = next(v for v in self.source['basic_laboratories'] if v['id'] == 'Lab1001')
        plan = copy.deepcopy(self.plans[item['level']])
        for point in plan['vertices'].values():
            point[0] += .01
            point[1] -= .02
        before = basic.compile_instance(self.source['basic_profile'], self.profile, item, self.plans[item['level']], self.p, 0)
        after = basic.compile_instance(self.source['basic_profile'], self.profile, item, plan, self.p, 321)
        self.assertEqual([b['id'] for b in before['bodies']], [b['id'] for b in after['bodies']])
        expected = [.01*self.p['display_scale'], -.02*self.p['display_scale'], 321]
        for a, b in zip(before['joints'], after['joints']):
            for axis in range(3):
                self.assertAlmostEqual(b['origin_mm'][axis]-a['origin_mm'][axis], expected[axis], places=6)
            self.assertEqual(a['axis'], b['axis'])

    def test_concave_boundary_crossing_is_rejected_even_if_vertices_are_inside(self):
        outline = [[0, 0], [100, 0], [100, 100], [60, 100], [60, 40], [40, 40], [40, 100], [0, 100]]
        crossing = [[10, 60], [90, 60], [90, 90], [10, 90]]
        self.assertTrue(all(floor.point_membership(p, outline) == 1 for p in crossing))
        self.assertFalse(basic.fits(crossing, outline, 1))


if __name__ == '__main__':
    unittest.main()
