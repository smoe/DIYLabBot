"""Compare batched whole-polynomial proofs with the original Git checker."""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_fleet_clearance as c

_legacy_namespace = dict(vars(c))
exec(compile((ROOT/'tests/fixtures/building_fleet_clearance_check_586ff76.py').read_text(),
             'building_fleet_clearance_check_586ff76.py', 'exec'), _legacy_namespace)
legacy_check = _legacy_namespace['check']


def rectangle(x0, y0, x1, y1):
    return [[[x0, y0], [x1, y0], [x1, y1]], [[x0, y0], [x1, y1], [x0, y1]]]


def certificate(floors=None, obstacles=(), length=.2, width=.1, reserve=.1):
    value = c.ClearanceCertificate.__new__(c.ClearanceCertificate)
    value.L, value.W = length, width
    value.radius = math.hypot(length, width)
    value.reserve, value.mesh_error = reserve, 0.
    value.lift_context = None
    value.level = 'EG'
    floors = rectangle(-100, -100, 100, 100) if floors is None else floors
    value.floor_bank = SimpleNamespace(covers=lambda xy, yaw, L, W, **kwargs:
        c.floor_union_covers(floors, xy, yaw, L, W))
    value.obstacles = list(obstacles)
    value.obstacle_names = ['fixture-obstacle-'+str(index) for index in range(len(obstacles))]
    value.obstacle_index = c.PolygonIndex(value.obstacles)
    value.obstacle_ids = {id(poly): index for index, poly in enumerate(value.obstacles)}
    value.start_grid = SimpleNamespace(cell=lambda xy: 0, blocked=bytearray([0]))
    return value


def linear_curve(count=97, start=-4., step=.1):
    return c.floor.motion.Curve(c.floor.canonical([
        {'time_s': i*.1, 'pose_mm_rad': [start+i*step, 0., 0.],
         'velocity_mm_rad_s': [step/.1, 0., 0.], 'acceleration_mm_rad_s2': [0., 0., 0.]}
        for i in range(count)]))


class PolynomialPartitionTests(unittest.TestCase):
    def assert_same_outcome(self, curve, factory, max_depth=24):
        original = legacy_check(factory(), curve, max_depth)
        current = factory().check(curve, max_depth)
        self.assertEqual(current['passed'], original['passed'])
        if not original['passed']:
            self.assertEqual(current['reason'], original['reason'])
            if 'time_s' in original:
                self.assertEqual(current['time_s'], original['time_s'])
        return original, current

    def test_safe_whole_curve_has_closed_complete_coverage_with_fewer_proofs(self):
        curve = linear_curve()
        original, current = self.assert_same_outcome(curve, certificate)
        self.assertTrue(current['passed'])
        self.assertEqual(original['evaluations'], 96)
        self.assertEqual(current['evaluations'], 3)
        spans = sorted(row['time_s'] for row in current['intervals'])
        self.assertEqual(spans[0][0], curve.times[0])
        self.assertEqual(spans[-1][1], curve.times[-1])
        self.assertTrue(all(a[1] == b[0] for a, b in zip(spans, spans[1:])))
        self.assertTrue(all(at in curve.times for span in spans for at in span))
        self.assertTrue(all(row['clearance_lower_mm'] >= current['minimum_clearance_mm']
                            and row['floor_support'] for row in current['intervals']))

    def test_coarse_midpoint_contact_refines_to_the_original_wall_rejection(self):
        wall = [[-.05, -20.], [.05, -20.], [.05, 20.], [-.05, 20.]]
        original, current = self.assert_same_outcome(linear_curve(),
            lambda: certificate(obstacles=[wall]))
        self.assertFalse(current['passed'])
        self.assertEqual(current['reason'], 'midpoint_mesh_or_exclusion_clearance')

    def test_native_floor_hole_cannot_be_hidden_by_coarse_endpoint_coverage(self):
        floors = rectangle(-100, -100, -.2, 100)+rectangle(.2, -100, 100, 100)
        original, current = self.assert_same_outcome(linear_curve(), lambda: certificate(floors=floors))
        self.assertFalse(current['passed'])
        self.assertIn('floor_union', current['reason'])

    def test_failed_coarse_inflation_keeps_the_full_original_midpoint_depth_budget(self):
        narrow = rectangle(-100, -.4, 100, .4)
        original, current = self.assert_same_outcome(linear_curve(),
            lambda: certificate(floors=narrow), max_depth=0)
        self.assertTrue(current['passed'])
        self.assertGreater(current['interval_partition']['original_knot_splits'], 0)
        self.assertTrue(all(row['depth'] == 0 for row in current['intervals']))

    def test_between_node_yaw_overshoot_retains_original_floor_rejection(self):
        points = [{'time_s': float(i), 'pose_mm_rad': [.01*i, 0., 0.],
                   'velocity_mm_rad_s': [.01, 0., 6.4*(-1.)**i],
                   'acceleration_mm_rad_s2': [0., 0., 0.]} for i in range(65)]
        curve = c.floor.motion.Curve(c.floor.canonical(points))
        floors = rectangle(-100, -1.2, 100, 1.2)
        original, current = self.assert_same_outcome(curve,
            lambda: certificate(floors=floors, length=2., width=.5, reserve=0.))
        self.assertFalse(current['passed'])

    def test_internal_knot_and_discontinuous_jerk_remain_inside_full_polynomial_enclosures(self):
        F = c.floor.F
        points = [{'time_s': i*.125,
                   F[0]: [float(i), .05*(-1.)**i, .01*(-1.)**i],
                   F[1]: [8., 0., 0.], F[2]: [0., .5*(-1.)**i, .1*(-1.)**i]}
                  for i in range(65)]
        curve = c.floor.motion.Curve(points)
        original, current = self.assert_same_outcome(curve, certificate)
        self.assertTrue(current['passed'])
        for span in current['intervals']:
            a, b = span['time_s']
            bounds = c._extrema(curve, a, b)
            for knot in (at for at in curve.times if a <= at <= b):
                for side in ('left', 'right'):
                    pose = curve.evaluate(knot, side=side)[F[0]]
                    for index, coordinate in enumerate(pose):
                        self.assertLessEqual(bounds['min'][index], coordinate+1e-12)
                        self.assertGreaterEqual(bounds['max'][index], coordinate-1e-12)

    def test_single_interval_fallback_and_initial_membership_gate_are_unchanged(self):
        curve = linear_curve(2)
        original, current = self.assert_same_outcome(curve, certificate)
        self.assertEqual(current['intervals'], original['intervals'])
        def blocked():
            value = certificate()
            value.start_grid.blocked[0] = 1
            return value
        original, current = self.assert_same_outcome(linear_curve(), blocked)
        self.assertFalse(current['passed'])
        self.assertEqual(current, original)


if __name__ == '__main__':
    unittest.main()
