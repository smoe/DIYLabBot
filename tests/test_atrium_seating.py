"""Shared oval recipe, source-bound alcove fit and static placement failures."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import atrium_seating as seating
import building_furnishings as furniture
import building_stack as stack
import relative_floorplan as floor


def source_fixture():
    source = json.loads((ROOT/'model/building-stack.shared.json').read_text())
    furnishings = json.loads((ROOT/source['sources']['furnishings']['source']).read_text())
    catalog = json.loads((ROOT/furnishings['catalog']['source']).read_text())
    group = next(group for group in furnishings['atrium_seating'] if group['anchor'] == 'AtriumAccess')
    plan = floor.load()
    # Independent fixture of the confirmed Kernbereich.  The raw trace remains
    # untouched; integration and preservation of the restrooms are tested separately.
    for area in plan['areas']:
        if area['id'] == 'NorthCore':
            area['kind'] = 'corridor'
    for wall in plan['walls']:
        if wall['id'] in ('W063', 'W065'):
            wall['kind'] = 'open_boundary'
    anchor = {'id': 'AtriumAccess', 'level_id': 'OG1', 'plan': plan,
              'area_refs': ['NorthCore'], 'entry_boundary_ids': ['W063'],
              'guard_boundary_ids': ['W065'], 'guard_post_mm': source['exterior']['guard_post_mm']}
    return catalog, group, anchor, stack.parameters(source)


class OvalTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.group, cls.anchor, cls.parameters = source_fixture()
        cls.definition = cls.catalog['types'][cls.group['table_type']]

    def test_size_variant_retains_body_ids_and_requested_elliptical_bounds(self):
        default = seating.oval_parts(self.definition)
        varied = seating.oval_parts(self.definition, {'length': 2000, 'width': 1000,
                                                     'leg_inset_x': 400, 'leg_inset_y': 150})
        bounds = seating.body_bounds([{'body': part['body'], 'action': part['action'], 'shape': part['shape']}
                                      for part in varied])
        top = bounds[self.definition['part_ids']['top']]
        self.assertEqual(top['min'][:2], [-1000, -500])
        self.assertEqual(top['max'][:2], [1000, 500])
        self.assertEqual(len(bounds), 5)
        self.assertEqual([part['body'] for part in default], [part['body'] for part in varied])
        self.assertEqual({part['shape']['kind'] for part in varied}, {'box', 'polygon_prism'})
        self.assertTrue(all(part['action'] == 'create' for part in varied))

    def test_invalid_or_unsupported_dimensions_do_not_create_geometry(self):
        for overrides in ({'leg_inset_x': 150, 'leg_inset_y': 50}, {'length': 1000, 'width': 1200}, {'height': True},
                          {'top_t': float('nan')}, {'leg_inset_x': 5000}, {'unknown': 1}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                seating.oval_parts(self.definition, overrides)
        wrong = copy.deepcopy(self.definition)
        wrong['parameters']['width']['unit'] = 'm'
        with self.assertRaisesRegex(ValueError, 'require mm'):
            seating.oval_parts(wrong)


class AtriumSeatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.group, cls.anchor, cls.parameters = source_fixture()

    def make(self, group=None, anchor=None, z=4250):
        return seating.compile(self.catalog, group or self.group, anchor or self.anchor, self.parameters, z)

    def test_one_unscaled_table_and_four_chairs_fit_with_declared_clearances(self):
        result = self.make()
        interface = result['interface']
        self.assertEqual((interface['table_count'], interface['chair_count']), (1, 4))
        self.assertEqual(interface['instance_scale'], 1)
        self.assertEqual(len(interface['instances']), 5)
        self.assertEqual(interface['positive_aabb_candidates'], 0)
        self.assertGreater(interface['inter_instance_body_pairs'], 0)
        self.assertTrue(interface['floor_contact_confirmed_in_source'])
        for role, actual in interface['static_clearance_mm'].items():
            required = self.group['clearances_mm']['wall' if role.startswith('wall') else role]
            self.assertGreaterEqual(actual+1e-7, required)
        self.assertTrue(all(body['role'] == 'concept_social_furniture' for body in result['bodies']))
        self.assertFalse(interface['dimensions_measured'])
        self.assertFalse(interface['swept_chair_access_checked'])

    def test_three_levels_reuse_exact_xy_geometry_and_only_change_datum_and_ids(self):
        built = []
        for index, level in enumerate(self.group['levels'], 1):
            anchor = copy.deepcopy(self.anchor)
            anchor['level_id'] = level
            built.append(self.make(anchor=anchor, z=4250*index))
        self.assertEqual(sum(item['interface']['table_count'] for item in built), 3)
        self.assertEqual(sum(item['interface']['chair_count'] for item in built), 12)
        for left, right in zip(built, built[1:]):
            self.assertEqual(len(left['bodies']), len(right['bodies']))
            for a, b in zip(left['interface']['instances'], right['interface']['instances']):
                self.assertEqual(a['origin_mm'][:2], b['origin_mm'][:2])
                self.assertEqual(b['origin_mm'][2]-a['origin_mm'][2], 4250)

    def test_rigidly_rotated_source_areas_rotate_seating_without_copying_world_positions(self):
        angle = math.radians(23)
        anchor = copy.deepcopy(self.anchor)
        for name, point in anchor['plan']['vertices'].items():
            x, y = point
            anchor['plan']['vertices'][name] = [math.cos(angle)*x-math.sin(angle)*y,
                                               math.sin(angle)*x+math.cos(angle)*y]
        original, rotated = self.make(), self.make(anchor=anchor)
        for a, b in zip(original['interface']['instances'], rotated['interface']['instances']):
            x, y = a['origin_mm'][:2]
            self.assertAlmostEqual(b['origin_mm'][0], math.cos(angle)*x-math.sin(angle)*y, places=5)
            self.assertAlmostEqual(b['origin_mm'][1], math.sin(angle)*x+math.cos(angle)*y, places=5)
            self.assertAlmostEqual(b['yaw_deg']-a['yaw_deg'], 23, places=5)

    def test_source_area_and_boundaries_must_be_open_and_referenced(self):
        closed = copy.deepcopy(self.anchor)
        next(wall for wall in closed['plan']['walls'] if wall['id'] == 'W065')['kind'] = 'wall'
        with self.assertRaisesRegex(ValueError, 'explicitly open'):
            self.make(anchor=closed)
        unknown = copy.deepcopy(self.anchor)
        next(area for area in unknown['plan']['areas'] if area['id'] == 'NorthCore')['kind'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'open corridor'):
            self.make(anchor=unknown)
        wrong = copy.deepcopy(self.anchor)
        wrong['area_refs'] = ['R3_011', 'CoreGap']
        with self.assertRaises(ValueError):
            self.make(anchor=wrong)

    def test_too_large_seating_rejects_the_source_instead_of_shrinking_furniture(self):
        group = copy.deepcopy(self.group)
        group['table_overrides_mm'] = {'length': 2400, 'leg_inset_x': 500, 'leg_inset_y': 200}
        with self.assertRaisesRegex(ValueError, 'Full-size seating does not fit'):
            self.make(group=group)

    def test_wrong_level_anchor_and_nonfinite_clearances_are_rejected(self):
        wrong = copy.deepcopy(self.anchor)
        wrong['level_id'] = 'EG'
        with self.assertRaisesRegex(ValueError, 'anchor or level'):
            self.make(anchor=wrong)
        for value in (True, float('inf'), -1):
            group = copy.deepcopy(self.group)
            group['clearances_mm']['entry'] = value
            with self.assertRaisesRegex(ValueError, 'entry clearance'):
                self.make(group=group)

    def test_template_schema_matches_the_actual_leading_source(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        Draft202012Validator(json.loads(seating.SCHEMA.read_text())).validate(self.group)


if __name__ == '__main__':
    unittest.main()
