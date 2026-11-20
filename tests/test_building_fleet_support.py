"""R1 closing must bridge bounded gaps without inventing open-edge support."""
from fractions import Fraction as Q
import math
import json
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_support as support


def rectangle(xmin, ymin, xmax, ymax):
    return [[[xmin, ymin], [xmax, ymin], [xmax, ymax]],
            [[xmin, ymin], [xmax, ymax], [xmin, ymax]]]


def gap_floor(width):
    return rectangle(-1000, -1000, 0, 1000)+rectangle(width, -1000, 1000, 1000)


class ClosingTests(unittest.TestCase):
    def test_eight_and_fifteen_mm_slots_pass_with_exact_width_audit(self):
        for width in (8., 15.):
            with self.subTest(width=width):
                result = support.support_covers(gap_floor(width), [width/2, 0], 0, 50, 100, 15,
                                                body_ids=['left']*2+['right']*2,
                                                curve_ref='leg-7')
                self.assertTrue(result['passed'])
                self.assertTrue(result['rule_applied'])
                self.assertEqual(result['original_missing_area_mm2'], width*200)
                self.assertEqual(len(result['applications']), 1)
                audit = result['applications'][0]
                self.assertAlmostEqual(audit['width_mm'], width)
                self.assertEqual(audit['adjacent_bodies'], ['left', 'right'])
                self.assertEqual(audit['curve_refs'], ['leg-7'])
                self.assertEqual(audit['bounds_mm']['min'], [0., -100.])
                self.assertEqual(audit['bounds_mm']['max'], [width, 100.])
                self.assertFalse(result['wheel_qualified'])

    def test_fifteen_point_five_and_historical_297_mm_fail(self):
        for width in (15.5, 297.):
            with self.subTest(width=width):
                result = support.support_covers(gap_floor(width), [width/2, 0], 0, 180, 20, 15)
                self.assertFalse(result['passed'])
                self.assertFalse(result['rule_applied'])
                self.assertEqual(result['applications'], [])
                self.assertTrue(result['unsupported_regions'])
                self.assertAlmostEqual(result['unsupported_regions'][0]['width_mm'], width)

    def test_open_edge_overhang_is_not_dilation(self):
        floor = rectangle(-1000, -1000, 0, 1000)
        for overhang in (7.5, .01):
            with self.subTest(overhang=overhang):
                result = support.support_covers(floor, [overhang-20, 0], 0, 20, 20, 15)
                self.assertFalse(result['passed'])
        # The exact original union remains authoritative at its closed edge.
        result = support.support_covers(floor, [-20, 0], 0, 20, 20, 15)
        self.assertTrue(result['passed'])
        self.assertFalse(result['rule_applied'])

    def test_rotated_rectangle_uses_the_same_disk_rule_and_reports_world_coordinates(self):
        angle = .31
        result = support.support_covers(gap_floor(8), [4, 0], angle, 40, 70, 15,
                                        body_ids=['left']*2+['right']*2)
        self.assertTrue(result['passed'])
        self.assertTrue(result['applications'])
        for application in result['applications']:
            self.assertAlmostEqual(application['width_mm'], 8, places=10)
            for polygon in application['polygons_mm']:
                self.assertTrue(all(-1e-10 <= point[0] <= 8+1e-10 for point in polygon))

    def test_convex_corner_cannot_gain_an_overhanging_support_fringe(self):
        floor = rectangle(-1000, -1000, 0, 0)
        result = support.support_covers(floor, [-10, -10], 0, 15, 15, 15)
        self.assertFalse(result['passed'])
        self.assertFalse(result['rule_applied'])

    def test_world_fraction_ulps_cannot_gain_open_edge_support(self):
        epsilon = Q(1, 2**60)
        floor = rectangle(-1000, -1000, 0, 1000)
        # A Float64 roundtrip would round the centre to-20 and lose this
        # unsupported fringe. WORLD rational affine products preserve it.
        result = support.support_covers(floor, [Q(-20)+epsilon, 0], 0, 20, 20, 15)
        self.assertFalse(result['passed'])
        self.assertGreater(result['missing_area_mm2'], 0)
        self.assertEqual(result['coordinate_method'],
                         'WORLD exact Fraction native coordinates and query affine products')

    def test_gap_one_rational_ulp_above_fifteen_never_closes(self):
        for epsilon, expected in ((Q(1, 2**45), False), (-Q(1, 2**45), True)):
            width = Q(15)+epsilon
            with self.subTest(epsilon=epsilon):
                result = support.support_covers(gap_floor(width), [width/2, 0], .17, 50, 30, 15)
                self.assertEqual(result['passed'], expected)

    def test_private_cache_patches_are_exact_world_cells_not_display_roundtrips(self):
        floor = gap_floor(8)
        result = support.support_covers(floor, [4, Q(1, 3)], .31, 40, 70, 15,
                                        return_exact_cells=True)
        self.assertTrue(result['passed'])
        patches = result.pop('_certified_patches')
        self.assertTrue(patches)
        self.assertTrue(all(type(v) is Q for poly in patches for p in poly for v in p))
        self.assertTrue(all(0 <= p[0] <= 8 for poly in patches for p in poly))
        # Display output is JSON-safe, but only the private rational geometry
        # is valid input to a provenance- and pose-fenced support cache.
        json.dumps(result, allow_nan=False)
        query = support.rectangle_query([4, Q(1, 3)], .31, 40, 70)
        self.assertTrue(support.polygon_union_covers([*floor, *patches], query)['passed'])
        angle = .31
        c, sn = Q(math.cos(angle)), Q(math.sin(angle))
        self.assertEqual(query[0], (Q(4)-40*c+70*sn, Q(1, 3)-40*sn-70*c))

    def test_solid_floor_fast_path_has_no_added_regions(self):
        result = support.support_covers(rectangle(-100, -100, 100, 100), [0, 0], .2, 30, 20, 15)
        self.assertTrue(result['passed'])
        self.assertFalse(result['rule_applied'])
        self.assertEqual(result['applications'], [])
        self.assertNotIn('closing_attempts', result)

    def test_zero_gap_policy_keeps_strict_old_floor_test(self):
        result = support.support_covers(gap_floor(8), [4, 0], 0, 50, 20, 0)
        self.assertFalse(result['passed'])
        self.assertFalse(result['rule_applied'])

    def test_degenerate_triangles_never_create_support(self):
        floor = gap_floor(8)+[[[0, 0], [100, 0], [200, 0]]]
        result = support.support_covers(floor, [4, 0], 0, 50, 20, 15)
        self.assertTrue(result['passed'])
        result = support.support_covers([floor[-1]], [0, 0], 0, 50, 20, 15)
        self.assertFalse(result['passed'])

    def test_invalid_coordinates_gap_and_identity_counts_fail(self):
        for gap in (True, -1, float('nan'), float('inf')):
            with self.subTest(gap=gap), self.assertRaises(ValueError):
                support.support_covers(gap_floor(8), [4, 0], 0, 30, 20, gap)
        with self.assertRaises(ValueError):
            support.support_covers(gap_floor(8), [4, 0], 0, 30, 20, 15, body_ids=['one'])


class ExactPolygonTests(unittest.TestCase):
    def test_exact_union_does_not_erase_tiny_holes_or_double_count_overlap(self):
        query = [[Q(-10), Q(-10)], [Q(10), Q(-10)], [Q(10), Q(10)], [Q(-10), Q(10)]]
        left = [[-20, -20], [0, -20], [0, 20], [-20, 20]]
        right = [[Q(1, 100000), -20], [20, -20], [20, 20], [Q(1, 100000), 20]]
        result = support.polygon_union_covers([left, left, right], query, missing_regions=True)
        self.assertFalse(result['passed'])
        self.assertEqual(result['missing_area_mm2'], .0002)
        self.assertEqual(sum(support._area(p) for p in result['_missing_cells']), Q(1, 5000))
        right = [[-1, -20], [20, -20], [20, 20], [-1, 20]]
        self.assertTrue(support.polygon_union_covers([left, right, left], query)['passed'])

    def test_triangle_union_covers_non_rectangular_convex_query(self):
        triangles = rectangle(-100, -100, 100, 100)
        query = [[-20, -30], [30, -10], [20, 40], [-40, 20]]
        result = support.polygon_union_covers(triangles, query, missing_regions=True)
        self.assertTrue(result['passed'])
        self.assertEqual(result['_missing_cells'], [])

    def test_convex_cell_merge_preserves_union_and_never_fills_a_concavity(self):
        triangles = [support._ccw(p) for p in rectangle(0, 0, 20, 10)]
        merged = support._merge_convex_cells(triangles)
        self.assertEqual(len(merged), 1)
        self.assertEqual(support._area(merged[0]), 200)
        same_side = [support._ccw([[0, 0], [20, 0], [10, 10]]),
                     support._ccw([[0, 0], [20, 0], [5, 5]])]
        self.assertEqual(len(support._merge_convex_cells(same_side)), 2)
        l_shape = [support._ccw(p) for p in rectangle(0, 0, 20, 10)+rectangle(0, 10, 10, 20)]
        merged = support._merge_convex_cells(l_shape)
        self.assertEqual(sum(support._area(p) for p in merged), 300)
        self.assertFalse(support.polygon_union_covers(merged,
            [[14, 14], [16, 14], [16, 16], [14, 16]])['passed'])

    def test_nonconvex_input_is_rejected_instead_of_changing_the_query(self):
        with self.assertRaisesRegex(ValueError, 'Convex'):
            support.polygon_union_covers(rectangle(-100, -100, 100, 100),
                [[-10, -10], [10, -10], [0, 0], [10, 10], [-10, 10]])

    def test_disk_enclosures_are_mathematically_inward_and_outward(self):
        rng = random.Random(42)
        for sides in (8, 16, 32):
            inner, outer, proof = support.disk_enclosures(7.5, sides)
            self.assertTrue(proof['inner_vertex_norms_within_disk'])
            self.assertTrue(proof['outer_halfplanes_contain_disk'])
            for point in inner:
                self.assertLessEqual(sum(v*v for v in point), Q(225, 4))
            for _ in range(100):
                # Independent geometric inclusion at many circle bearings.
                angle = rng.random()*2*math.pi
                point = [7.5*math.cos(angle), 7.5*math.sin(angle)]
                self.assertTrue(all(float(support._cross((b[0]-a[0], b[1]-a[1]),
                    (Q(point[0])-a[0], Q(point[1])-a[1]))) >= -1e-12
                    for a, b in zip(outer, outer[1:]+outer[:1])))
            self.assertGreaterEqual(support.query_padding_mm(15, sides), 15)


if __name__ == '__main__':
    unittest.main()
