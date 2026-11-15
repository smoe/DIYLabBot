"""Owner kitchen union, exterior-window placement and modeled entrance clearance."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import atrium_seating as geometry
import building_furnishings as furniture
import building_stack as stack
import relative_floorplan as floor


class KitchenWindowPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = stack.load(); cls.p = stack.parameters(cls.spec)
        cls.plan = stack.templates(cls.spec)[0]
        cls.data = stack.interfaces(cls.spec, cls.p)
        cls.expanded = stack.expanded(cls.spec, cls.p)
        cls.plans = {level['id']: stack.level_plan(cls.spec, level['id'])
                     for level in cls.data['levels'] if level['id'].startswith('OG')}
        cls.ref = cls.spec['sources']['furnishings']
        cls.source = furniture.read(cls.ref)
        cls.catalog = furniture.read(cls.source['catalog'])
        cls.kitchen = next(room for room in cls.source['rooms'] if room['id'] == 'Kitchen1008')
        cls.result = furniture.compile(cls.ref, cls.plan, cls.p, cls.data['levels'], cls.plans)
        cls.room = next(room for room in cls.result['rooms'] if room['id'] == 'Kitchen1008')
        cls.anchor = cls.room['window_anchor']

    def compile_source(self, source):
        original = furniture.read
        with patch.object(furniture, 'read', side_effect=lambda ref: source if ref == self.ref else original(ref)):
            return furniture.compile(self.ref, self.plan, self.p, self.data['levels'], self.plans)

    def kitchen_operations(self, result=None):
        return [op for op in (result or self.result)['operations'] if op['body'].startswith('Kitchen1008_')]

    def boundary_planes(self):
        # These are the actual outside edges of the now unpartitioned union.
        names = {'W005', 'W006', 'W009', 'W018', 'W019', 'W028', 'W030', 'W046'}
        areas = [area for area in self.plan['areas'] if area['id'] in self.kitchen['template_areas']]
        uses = {}
        for area in areas:
            for edge in area['boundary']:
                uses.setdefault(edge['wall'], []).append(edge['direction'])
        self.assertEqual({name for name, directions in uses.items() if len(directions) == 1}, names)
        walls = {wall['id']: wall for wall in self.plan['walls']}
        result = []
        for name in sorted(names):
            wall = walls[name]; a, b = [self.plan['vertices'][wall[key]] for key in ('start', 'end')]
            length = math.dist(a, b); tangent = [(b[i]-a[i])/length for i in (0, 1)]
            inward = [uses[name][0]*value for value in (-tangent[1], tangent[0])]
            origin = [a[i]*self.p['display_scale']+inward[i]*self.p['display_thickness']/2 for i in (0, 1)]
            result.append((name, origin, inward))
        return result

    @staticmethod
    def minimum_distance(shape, origin, inward, translation=(0, 0)):
        if shape['kind'] == 'polygon_prism':
            return min(sum((point[i]+translation[i]-origin[i])*inward[i] for i in (0, 1))
                       for point in shape['points'])
        radius = max(shape['radius'], shape.get('top_radius', shape['radius']))
        return sum((shape['origin'][i]+translation[i]-origin[i])*inward[i] for i in (0, 1))-radius

    def test_unpartitioned_kitchen_reaches_outside_window_on_og1_only(self):
        self.assertEqual(self.kitchen['template_areas'], ['R3_008A', 'R3_008B', 'R3_009'])
        names = {body['id'] for body in self.expanded['bodies']}
        for wall in ('W017', 'W027'):
            self.assertNotIn('OG1__Wall_'+wall, names)
            self.assertTrue({'OG2__Wall_'+wall, 'OG3__Wall_'+wall} <= names)
        self.assertEqual(next(room for room in self.source['rooms'] if room['id'] == 'Office3009')['template_areas'], ['R3_009'])
        self.assertEqual({room['room'] for room in self.result['rooms']}, {'1.008', '1.002', '2.002', '3.002', '3.009'})
        windows = {(item['level_id'], item['wall']) for item in self.data['exterior']['side_window_groups']}
        self.assertIn(('OG1', 'W005'), windows)
        self.assertNotIn(('OG2', 'W005'), windows)
        self.assertNotIn(('OG3', 'W005'), windows)
        self.assertNotIn('W005', self.spec['exterior']['side_window_walls'])

    def test_tabletops_are_adjacent_to_actual_exterior_window_inner_face(self):
        _, origin, inward = next(plane for plane in self.boundary_planes() if plane[0] == 'W005')
        tops = [op for op in self.kitchen_operations() if op['body'] in self.anchor['table_body_ids']]
        self.assertEqual(len(tops), 2)
        gap = min(self.minimum_distance(op['shape'], origin, inward) for op in tops)
        self.assertAlmostEqual(gap, 100*self.room['presentation_scale'], places=7)
        self.assertAlmostEqual(gap, self.anchor['table_gap_mm'], places=7)
        self.assertEqual(self.anchor['nominal_table_gap_mm'], 100)
        self.assertEqual((self.anchor['area_id'], self.anchor['wall_id']), ('R3_009', 'W005'))
        self.assertFalse(self.anchor['dimensions_measured'])
        self.assertFalse(self.anchor['placement_qualified'])

    def test_entire_recipe_moves_once_and_other_rooms_remain_identical(self):
        source = copy.deepcopy(self.source)
        next(room for room in source['rooms'] if room['id'] == 'Kitchen1008').pop('window_anchor')
        previous = self.compile_source(source)
        self.assertEqual([op for op in previous['operations'] if not op['body'].startswith('Kitchen1008_')],
                         [op for op in self.result['operations'] if not op['body'].startswith('Kitchen1008_')])
        delta = self.anchor['translation_mm']
        for a, b in zip(self.kitchen_operations(previous), self.kitchen_operations()):
            self.assertEqual((a['id'], a['body'], a['action']), (b['id'], b['body'], b['action']))
            before, after = copy.deepcopy(a['shape']), copy.deepcopy(b['shape'])
            if before['kind'] == 'polygon_prism':
                for p, q in zip(before.pop('points'), after.pop('points')):
                    for axis in (0, 1):self.assertAlmostEqual(q[axis]-p[axis], delta[axis], places=7)
            else:
                p, q = before.pop('origin'), after.pop('origin')
                for axis in (0, 1):self.assertAlmostEqual(q[axis]-p[axis], delta[axis], places=7)
                self.assertEqual(p[2], q[2])
            self.assertEqual(before, after)
        old_room = next(room for room in previous['rooms'] if room['id'] == 'Kitchen1008')
        self.assertEqual(old_room['presentation_scale'], self.room['presentation_scale'])

    def test_all_positive_furniture_stays_inside_real_union_inner_wall_planes(self):
        positive = [op for op in self.kitchen_operations() if op['action'] != 'cut']
        self.assertGreater(len(positive), 0)
        for wall, origin, inward in self.boundary_planes():
            for op in positive:
                with self.subTest(wall=wall, body=op['body']):
                    self.assertGreaterEqual(self.minimum_distance(op['shape'], origin, inward), -1e-7)

    def test_tangential_containment_is_minimal_and_preserves_window_gap(self):
        tangent = self.anchor['tangential_translation_mm']
        self.assertGreater(math.hypot(*tangent), 0)
        self.assertAlmostEqual(sum(tangent[i]*self.anchor['inward'][i] for i in (0, 1)), 0, places=8)
        # A one-percent step back toward the uncorrected recipe violates a
        # real inner wall plane. The fitted recipe itself is checked above.
        smaller = [-.01*value for value in tangent]
        positive = [op for op in self.kitchen_operations() if op['action'] != 'cut']
        violations = [self.minimum_distance(op['shape'], origin, inward, smaller)
                      for _, origin, inward in self.boundary_planes() for op in positive]
        self.assertLess(min(violations), -.1)

    def test_modeled_entrance_leaf_and_full_sweep_envelope_clear_furniture(self):
        identity = self.data['exterior']['door_leaves']['OG1__D3_008A']
        leaf = next(op['shape'] for op in self.expanded['operations'] if op['body'] == identity and op['action'] == 'create')
        opening = next(item for item in self.plan['openings'] if item['id'] == 'D3_008A')
        wall = next(item for item in self.plan['walls'] if item['id'] == opening['wall'])
        a, b = [self.plan['vertices'][wall[key]] for key in ('start', 'end')]
        hinge = [(a[i]+opening['interval'][0]*(b[i]-a[i]))*self.p['display_scale'] for i in (0, 1)]
        radius = max(math.dist(hinge, point) for point in leaf['points'])
        swept = {'min': [hinge[0]-radius, hinge[1]-radius, leaf['offset']],
                 'max': [hinge[0]+radius, hinge[1]+radius, leaf['offset']+leaf['depth']]}
        static = geometry.operation_bounds(leaf)
        for op in self.kitchen_operations():
            if op['action'] == 'cut':continue
            bounds = geometry.operation_bounds(op['shape'])
            for label, envelope in (('shown leaf', static), ('full-circle leaf envelope', swept)):
                self.assertFalse(all(min(bounds['max'][i], envelope['max'][i])-max(bounds['min'][i], envelope['min'][i]) > 1e-7
                                     for i in range(3)), (label, op['body']))
        # This is the modeled leaf and a conservative static rotation bound,
        # not measured hardware, a door controller or a real walking route.

    def test_invalid_window_references_and_parameters_are_rejected(self):
        changes = [
            ('area_id', 'R3_003'), ('wall_id', 'W017'), ('wall_id', 'Missing'),
            ('table_instances', ['Missing']), ('table_instances', ['TableA', 'TableA']),
            ('table_instances', ['Fridge']), ('table_gap_mm', True), ('table_gap_mm', float('nan')),
            ('table_gap_mm', -1), ('basis', 'measured'), ('unsupported', 1),
        ]
        for key, value in changes:
            source = copy.deepcopy(self.source)
            next(room for room in source['rooms'] if room['id'] == 'Kitchen1008')['window_anchor'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):self.compile_source(source)

    def test_disconnected_union_and_infeasible_fit_are_rejected(self):
        source = copy.deepcopy(self.source)
        next(room for room in source['rooms'] if room['id'] == 'Kitchen1008')['template_areas'].append('R3_016')
        with self.assertRaisesRegex(ValueError, 'convex room union'):self.compile_source(source)
        source = copy.deepcopy(self.source)
        next(room for room in source['rooms'] if room['id'] == 'Kitchen1008')['window_anchor']['table_gap_mm'] = 10000
        with self.assertRaisesRegex(ValueError, 'cannot fit'):self.compile_source(source)

    def test_window_anchor_requires_constructed_glazing_on_that_level(self):
        source = copy.deepcopy(self.spec)
        source['exterior'].pop('side_window_walls_by_level')
        with self.assertRaisesRegex(ValueError, 'constructed exterior window'):
            stack.interfaces(source, stack.parameters(source))


if __name__ == '__main__':
    unittest.main()
