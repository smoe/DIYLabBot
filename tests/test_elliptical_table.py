"""White table profile, approximation error and real support containment."""
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
import relative_floorplan as floor
import tube_carrier_model as portable


class EllipticalTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT/'model/furniture/social.catalog.json').read_text())
        cls.definition = cls.catalog['types']['oval_table']

    def test_white_elliptical_outline_keeps_nominal_bounds_and_area(self):
        parts = furniture.parts_for(self.catalog, 'oval_table')
        top = parts[0]
        self.assertEqual(top['color'], '#ffffff')
        self.assertEqual(top['shape']['kind'], 'polygon_prism')
        self.assertTrue(all(part['action'] == 'create' for part in parts))
        points = top['shape']['points']
        self.assertEqual([min(p[i] for p in points) for i in (0, 1)], [-750, -400])
        self.assertEqual([max(p[i] for p in points) for i in (0, 1)], [750, 400])
        # A circular-end stadium does not follow this ellipse equation.
        for x, y in points:
            self.assertAlmostEqual((x/750)**2+(y/400)**2, 1, places=12)
        area = floor.signed_area(points)
        self.assertGreater(area, .999*math.pi*750*400)
        self.assertLess(area, math.pi*750*400)

    def test_every_arc_is_within_the_declared_chord_error(self):
        variants = ({}, {'length': 2000, 'width': 1000, 'leg_inset_x': 400, 'leg_inset_y': 150},
                    {'length': 2400, 'width': 1200, 'leg_inset_x': 500, 'leg_inset_y': 250})
        for overrides in variants:
            with self.subTest(overrides=overrides):
                dimensions = seating.oval_dimensions(self.definition, overrides)
                a, b = dimensions['length']/2, dimensions['width']/2
                points = seating.oval_parts(self.definition, overrides)[0]['shape']['points']
                maximum = 0
                for index, (p, q) in enumerate(zip(points, points[1:]+points[:1])):
                    start = math.atan2(p[1]/b, p[0]/a) % (2*math.pi)
                    end = math.atan2(q[1]/b, q[0]/a) % (2*math.pi)
                    if end <= start: end += 2*math.pi
                    vector = [q[i]-p[i] for i in (0, 1)]
                    denominator = sum(value*value for value in vector)
                    for fraction in (1/8, 1/4, 3/8, 1/2, 5/8, 3/4, 7/8):
                        theta = start+fraction*(end-start)
                        curve = [a*math.cos(theta), b*math.sin(theta)]
                        t = max(0, min(1, sum((curve[i]-p[i])*vector[i] for i in (0, 1))/denominator))
                        closest = [p[i]+t*vector[i] for i in (0, 1)]
                        maximum = max(maximum, math.dist(curve, closest))
                self.assertLessEqual(maximum, self.definition['max_chord_deviation_mm']+1e-8)

    def test_support_rectangles_are_inside_the_emitted_top_not_just_its_box(self):
        parts = seating.oval_parts(self.definition)
        polygon = parts[0]['shape']['points']
        for part in parts[1:]:
            shape = part['shape']; x, y, _ = shape['origin']; w, d, _ = shape['size']
            for point in ([x, y], [x+w, y], [x+w, y+d], [x, y+d]):
                self.assertGreaterEqual(floor.point_membership(point, polygon), 0)
        # These old corner stations fit the bounding rectangle but miss the
        # elliptical cap.  They must not produce unsupported table legs.
        with self.assertRaisesRegex(ValueError, 'support extends beyond'):
            seating.oval_parts(self.definition, {'leg_inset_x': 150, 'leg_inset_y': 50})

    def test_invalid_profile_accuracy_or_recipe_is_rejected(self):
        for value in (True, float('nan'), 0, .01, 5):
            definition = copy.deepcopy(self.definition)
            definition['max_chord_deviation_mm'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                seating.oval_parts(definition)
        definition = copy.deepcopy(self.definition)
        definition['recipe'] = 'stadium_table'
        with self.assertRaisesRegex(ValueError, 'elliptical-table'):
            seating.oval_parts(definition)

    def test_shared_placement_and_solidcraft_lowering_use_the_same_closed_profile(self):
        placed = furniture.instantiate(self.catalog, 'oval_table', 'Table', 'Furniture', [20, 30, 100], 23)
        source = {'components': [{'id': 'Furniture', 'grounded': True}],
                  'bodies': placed['bodies'], 'operations': placed['operations'], 'joints': []}
        class Provider:
            SOURCE = ROOT/'model/furniture/social.catalog.json'
            expanded = staticmethod(lambda spec, p: source)
            samples = staticmethod(lambda spec, p: [])
            pose = staticmethod(lambda spec, p: {})
        commands = portable.solidcraft_commands({'id': 'EllipseTable', 'status': 'synthetic_fixture', 'parameters': {}}, {}, provider=Provider)
        top = placed['operations'][0]['shape']
        sketch = next(command for command in commands if command['command'] == 'sketch.line')
        self.assertEqual(sketch['params']['points'], top['points'])
        self.assertTrue(sketch['params']['closed'])
        self.assertEqual(sum(command['command'] == 'solid.extrude' for command in commands), 5)
        self.assertEqual(len(placed['bodies']), 5)
        self.assertEqual(top['offset'], 810)
        self.assertEqual(top['depth'], 35)

    def test_catalog_schema_accepts_the_declared_approximation(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        schema = json.loads((ROOT/'model/social-furniture-catalog.schema.json').read_text())
        Draft202012Validator(schema).validate(self.catalog)


if __name__ == '__main__':
    unittest.main()
