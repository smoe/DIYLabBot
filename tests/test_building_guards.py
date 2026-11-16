"""Shared profile, source preservation and inclined guard geometry contracts."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_guards as guards
import relative_floorplan as floor


class BuildingGuardTests(unittest.TestCase):
    def setUp(self):
        self.exterior = json.loads((ROOT/'model/building-stack.shared.json').read_text())['exterior']
        self.profile = guards.profile_from_exterior(self.exterior)

    def segment(self, start, end, **kwargs):
        return guards.compile_segment(self.profile, 'Guard', start, end,
                                      component='TestStair', **kwargs)

    def test_profile_references_the_existing_atrium_values_without_mutating_source(self):
        before = copy.deepcopy(self.exterior)
        self.assertEqual(self.profile, {
            'height_mm': 1100, 'post_mm': 40, 'bar_mm': 16,
            'bar_fractions': [.15, .35, .55, .75],
            'max_post_spacing_mm': 1600, 'color': '#424A50'})
        changed = copy.deepcopy(self.exterior)
        changed.update(guard_height_mm=1200.5, guard_bar_mm=12.5, frame_color='#123456')
        profile = guards.profile_from_exterior(changed)
        self.assertIs(type(profile['height_mm']), float)
        self.assertEqual(profile['height_mm'], 1200.5)
        self.assertEqual(profile['bar_mm'], 12.5)
        self.assertEqual(profile['color'], '#123456')
        profile['bar_fractions'].append(.9)
        self.assertEqual(self.exterior, before)
        self.assertNotIn(.9, changed['guard_bar_fractions'])

    def test_horizontal_atrium_ids_order_and_rectangles_remain_exact(self):
        result = self.segment([0, 0, 1000], [1000, 0, 1000])
        expected = ['Guard_Post0', 'Guard_Handrail', 'Guard_Post1',
                    'Guard_Bar0', 'Guard_Bar1', 'Guard_Bar2', 'Guard_Bar3']
        self.assertEqual(result['interface']['body_ids'], expected)
        self.assertEqual([body['id'] for body in result['bodies']], expected)
        by_name = {op['body']: op for op in result['operations']}
        self.assertEqual(by_name['Guard_Post0']['shape'], {
            'kind': 'polygon_prism', 'plane': 'XY',
            'points': [[-20., -20.], [20., -20.], [20., 20.], [-20., 20.]],
            'offset': 1000, 'depth': 1100, 'fixed': True})
        self.assertEqual(by_name['Guard_Handrail']['shape'], {
            'kind': 'polygon_prism', 'plane': 'XY',
            'points': [[-20., -20.], [1020., -20.], [1020., 20.], [-20., 20.]],
            'offset': 2084, 'depth': 16, 'fixed': True})
        bar = by_name['Guard_Bar0']['shape']
        self.assertEqual(bar['points'], [[-20., -8.], [1020., -8.], [1020., 8.], [-20., 8.]])
        self.assertEqual((bar['offset'], bar['depth']), (1165, 16))
        for body, op in zip(result['bodies'], result['operations']):
            self.assertEqual(body['appearance'], {'color': '#424A50', 'opacity': 1})
            self.assertEqual((op['id'], op['action']), (body['id']+'_Profile', 'create'))

    def test_rotated_and_reversed_horizontal_members_have_positive_profiles(self):
        for start, end in [([120, 240, 2500], [3120, 4240, 2500]),
                           ([3120, 4240, 2500], [120, 240, 2500])]:
            result = self.segment(start, end)
            self.assertEqual(len(result['interface']['posts']), 5)
            for op in result['operations']:
                self.assertEqual(op['shape']['plane'], 'XY')
                self.assertGreater(floor.signed_area(op['shape']['points']), 0)
            self.assertEqual(result['interface']['start_mm'], start)
            self.assertEqual(result['interface']['end_mm'], end)

    def test_inclined_spacing_is_bounded_in_three_dimensions(self):
        result = self.segment([0, 100, 0], [1000, 100, 4000])
        points = [post['pitchline_mm'] for post in result['interface']['posts']]
        self.assertEqual(len(points), math.ceil(math.sqrt(17000000)/1600)+1)
        self.assertEqual(points[0], [0, 100, 0])
        self.assertEqual(points[-1], [1000, 100, 4000])
        for a, b in zip(points, points[1:]):
            self.assertLessEqual(math.dist(a, b), self.profile['max_post_spacing_mm']+1e-9)

    def test_signed_inclines_keep_the_actual_normal_bar_section_and_top_pitchline(self):
        for start, end in [([0, 100, 0], [3000, 100, 2000]),
                           ([3000, 100, 0], [0, 100, 2000]),
                           ([0, 100, 2000], [3000, 100, 0])]:
            result = self.segment(start, end)
            dx, dz = end[0]-start[0], end[2]-start[2]
            length = math.hypot(dx, dz)
            rails = [op for op in result['operations'] if '_Post' not in op['body']]
            self.assertEqual(len(rails), 5)
            for op in rails:
                shape = op['shape']
                self.assertEqual(shape['plane'], 'XZ')
                self.assertGreater(floor.signed_area(shape['points']), 0)
                normal_section = floor.signed_area(shape['points'])/(length*(1+40/abs(dx)))
                self.assertAlmostEqual(normal_section, 16)
                offsets = [z-(start[2]+(x-start[0])*dz/dx) for x, z in shape['points']]
                if op['body'].endswith('_Handrail'):
                    self.assertAlmostEqual(max(offsets), 1100)
                    self.assertEqual(shape['depth'], 40)
                else:
                    index = int(op['body'].rsplit('_Bar', 1)[1])
                    self.assertAlmostEqual(min(offsets), self.profile['height_mm']*self.profile['bar_fractions'][index])
                    self.assertEqual(shape['depth'], 16)
            self.assertEqual(result['interface']['bar_section_mm'], 16)
            self.assertEqual(result['interface']['bar_section_basis'], 'normal_to_pitchline')

    def test_shared_flat_and_inclined_corner_posts_are_emitted_once(self):
        registry = {}
        first = guards.compile_segment(self.profile, 'Flight', [0, 0, 0], [3000, 0, 2000],
                                       component='Stair', post_registry=registry, post_embed_mm=6.25)
        second = guards.compile_segment(self.profile, 'Landing', [3000, 0, 2000], [3000, 400, 2000],
                                        component='Stair', post_registry=registry, post_embed_mm=6.25)
        prior = first['interface']['posts'][-1]
        reused = second['interface']['posts'][0]
        self.assertFalse(reused['new'])
        self.assertEqual(reused['body_id'], prior['body_id'])
        self.assertNotIn(reused['body_id'], {body['id'] for body in second['bodies']})
        self.assertEqual(reused['base_mm'], [3000, 0, 1993.75])
        self.assertEqual(reused['pitchline_mm'], [3000, 0, 2000])
        self.assertEqual(reused['top_mm'], [3000, 0, 3100])
        all_ids = [body['id'] for result in (first, second) for body in result['bodies']]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_component_and_profile_changes_do_not_reuse_unrelated_posts(self):
        registry = {}
        guards.compile_segment(self.profile, 'First', [0, 0, 0], [1000, 0, 0],
                               component='FirstStair', post_registry=registry)
        second = guards.compile_segment(self.profile, 'Second', [1000, 0, 0], [1000, 1000, 0],
                                        component='SecondStair', post_registry=registry)
        self.assertTrue(second['interface']['posts'][0]['new'])
        changed = {**self.profile, 'color': '#ffffff'}
        third = guards.compile_segment(changed, 'Third', [1000, 0, 0], [1000, 1000, 0],
                                       component='FirstStair', post_registry=registry)
        self.assertTrue(third['interface']['posts'][0]['new'])

    def test_actual_support_changes_only_post_feet_and_height(self):
        start, end = [0, 0, 1000], [1000, 0, 1000]
        before = copy.deepcopy([start, end, self.profile])
        received = []
        def support(point):
            self.assertIs(type(point), tuple)
            received.append(point)
            return point[2]+125
        result = self.segment(start, end, post_embed_mm=6.25, post_support_z=support)
        self.assertEqual([start, end, self.profile], before)
        self.assertEqual(received, [(0, 0, 1000), (1000, 0, 1000)])
        by_id = {op['body']: op['shape'] for op in result['operations']}
        for post in result['interface']['posts']:
            self.assertEqual(post['support_z_mm'], 1125)
            self.assertEqual(post['base_mm'][2], 1118.75)
            self.assertEqual(post['top_mm'][2], 2100)
            self.assertEqual(by_id[post['body_id']]['offset'], 1118.75)
            self.assertEqual(by_id[post['body_id']]['depth'], 981.25)
        ordinary = self.segment(start, end, post_embed_mm=6.25)
        self.assertEqual([op for op in result['operations'] if '_Post' not in op['body']],
                         [op for op in ordinary['operations'] if '_Post' not in op['body']])

    def test_invalid_or_failed_support_is_atomic_and_cannot_mutate_pitchline(self):
        registry = {}
        self.segment([0, 0, 0], [1000, 0, 0], post_registry=registry)
        before = copy.deepcopy(registry)
        def fail(point):
            raise RuntimeError('Synthetic missing support')
        def mutate(point):
            point[2] = 500
            return 500
        for callback in (42, lambda point: None, lambda point: True,
                         lambda point: float('nan'), lambda point: float('inf'),
                         lambda point: point[2]+1100, fail, mutate):
            with self.subTest(callback=callback), self.assertRaises(ValueError):
                self.segment([2000, 0, 0], [3000, 0, 0], post_registry=registry,
                             post_support_z=callback)
            self.assertEqual(registry, before)
        count = 0
        def later_failure(point):
            nonlocal count
            count += 1
            return point[2] if count == 1 else float('nan')
        with self.assertRaises(ValueError):
            self.segment([2000, 0, 0], [3000, 0, 100], post_registry=registry,
                         post_support_z=later_failure)
        self.assertEqual(count, 2)
        self.assertEqual(registry, before)

    def test_invalid_profiles_geometry_and_embed_are_rejected_without_registry_effects(self):
        for field, value in [('height_mm', True), ('post_mm', float('nan')),
                             ('bar_mm', -1), ('max_post_spacing_mm', float('inf')),
                             ('bar_fractions', [.5, .5]), ('bar_fractions', [False]),
                             ('color', 'grey')]:
            changed = {**self.profile, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                guards.validate_profile(changed)
        registry = {}
        self.segment([0, 0, 0], [1000, 0, 0], post_registry=registry)
        original = copy.deepcopy(registry)
        for start, end, embed in [([0, 0, 0], [0, 0, 100], 0),
                                  ([0, 0, 0], [1000, 500, 100], 0),
                                  ([0, False, 0], [1000, 0, 0], 0),
                                  ([0, 0, 0], [1000, 0, 0], -1),
                                  ([0, 0, 0], [1000, 0, 0], True)]:
            with self.subTest(start=start, end=end, embed=embed), self.assertRaises(ValueError):
                self.segment(start, end, post_registry=registry, post_embed_mm=embed)
            self.assertEqual(registry, original)


if __name__ == '__main__':
    unittest.main()
