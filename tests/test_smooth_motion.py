"""Actual quintic extrema, C2 joins and independent rigid-body derivative checks."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion
import sample_motion


def point(t, p, v, a):
    return {'time_s': t, 'positions_rad': p,
            'velocities_rad_s': v, 'accelerations_rad_s2': a}


def identity():
    return [[1., 0., 0., 0.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]]


def simple_kin(length=100.):
    return SimpleNamespace(base=identity(), frames=[identity() for _ in range(6)],
                           flange=[length, 0., 0.], length=0.)


class QuinticTests(unittest.TestCase):
    def test_rest_quintic_has_exact_hidden_velocity_acceleration_and_jerk_maxima(self):
        points = motion.from_positions([0., 1.], [[0.], [1.]])
        middle = motion.evaluate(points, .5)
        self.assertAlmostEqual(middle['positions_rad'][0], .5)
        self.assertAlmostEqual(middle['velocities_rad_s'][0], 1.875)
        self.assertAlmostEqual(middle['accelerations_rad_s2'][0], 0.)
        self.assertAlmostEqual(middle['jerks_rad_s3'][0], -30.)
        extrema = motion.bounds(points)
        self.assertAlmostEqual(extrema['positions_rad']['min'][0], 0.)
        self.assertAlmostEqual(extrema['positions_rad']['max'][0], 1.)
        self.assertAlmostEqual(extrema['velocities_rad_s']['max_abs'][0], 1.875)
        self.assertAlmostEqual(extrema['accelerations_rad_s2']['max_abs'][0], 10 * math.sqrt(3) / 3)
        self.assertAlmostEqual(extrema['jerks_rad_s3']['max_abs'][0], 60.)

    def test_position_peak_between_endpoints_and_midpoint_is_not_missed(self):
        # p(u)=u²(1-u)³ has its maximum at u=2/5, not a sample or midpoint.
        points = [point(0., [0.], [0.], [2.]), point(1., [0.], [0.], [0.])]
        extrema = motion.bounds(points)
        self.assertAlmostEqual(extrema['positions_rad']['max'][0], .03456, places=13)
        self.assertGreater(extrema['positions_rad']['max'][0], motion.evaluate(points, .5)['positions_rad'][0])

    def test_opposite_endpoint_velocities_can_overshoot_equal_positions(self):
        points = [point(0., [0.], [4.], [0.]), point(1., [0.], [-4.], [0.])]
        self.assertAlmostEqual(motion.bounds(points)['positions_rad']['max'][0], 1.25)

    def test_recursive_root_isolation_retains_repeated_quartic_roots(self):
        roots = motion.real_roots([.03515625, -.375, 1.375, -2., 1.])
        self.assertEqual(len(roots), 2)
        for actual, expected in zip(roots, [.25, .75]):
            self.assertAlmostEqual(actual, expected, places=13)

    def test_nonuniform_local_fit_reproduces_quadratic_derivatives(self):
        times = [0., .3, 1.2, 2.]
        points = motion.from_positions(times, [[3 * t * t + 2 * t - 1] for t in times], rest_endpoints=False)
        for p, t in zip(points, times):
            self.assertAlmostEqual(p['velocities_rad_s'][0], 6 * t + 2)
            self.assertAlmostEqual(p['accelerations_rad_s2'][0], 6.)

    def test_quintics_share_pva_but_bounds_include_both_knot_jerks(self):
        points = motion.from_positions([0., .4, 1.3, 2.], [[0., .2], [.6, -.1], [.4, .7], [1., 0.]])
        limits = motion.bounds(points)
        different_jerks = False
        for p in points[1:-1]:
            left = motion.evaluate(points, p['time_s'], side='left')
            right = motion.evaluate(points, p['time_s'], side='right')
            for field in motion.FIELDS[:3]:
                self.assertEqual(left[field], right[field])
                self.assertEqual(right[field], p[field])
            for i, (a, b) in enumerate(zip(left['jerks_rad_s3'], right['jerks_rad_s3'])):
                different_jerks |= abs(a - b) > 1e-6
                self.assertGreaterEqual(limits['jerks_rad_s3']['max_abs'][i], max(abs(a), abs(b)) - 1e-10)
        self.assertTrue(different_jerks)

    def test_endpoint_stops_and_outside_holds_are_explicit(self):
        points = motion.from_positions([1., 2., 3.], [[0.], [1.], [.5]])
        for p in (points[0], points[-1]):
            self.assertEqual(p['velocities_rad_s'], [0.])
            self.assertEqual(p['accelerations_rad_s2'], [0.])
        for t, position in [(0., 0.), (4., .5)]:
            state = motion.evaluate(points, t)
            self.assertEqual(state['positions_rad'], [position])
            self.assertTrue(all(state[field] == [0.] for field in motion.FIELDS[1:]))

    def test_time_scaling_preserves_curve_and_correct_derivative_powers(self):
        points = motion.from_positions([0., .7, 1.5], [[0., .1], [.4, -.2], [.2, .3]])
        before = copy.deepcopy(points)
        scaled = motion.scale(points, 2.5, 7.)
        self.assertEqual(points, before)
        for t in [.0, .2, .7, 1., 1.5]:
            original = motion.evaluate(points, t)
            changed = motion.evaluate(scaled, 7 + 2.5 * t)
            for order, field in enumerate(motion.FIELDS):
                for a, b in zip(original[field], changed[field]):
                    self.assertAlmostEqual(b, a / 2.5 ** order, places=10)
        original, changed = motion.bounds(points), motion.bounds(scaled)
        for order, field in enumerate(motion.FIELDS):
            for a, b in zip(original[field]['max_abs'], changed[field]['max_abs']):
                self.assertAlmostEqual(b, a / 2.5 ** order, places=10)

    def test_septic_has_zero_endpoint_derivatives_and_known_peaks(self):
        for u in (0., 1.):
            self.assertEqual(motion.septic(u), u)
            self.assertEqual([motion.septic(u, order) for order in (1, 2, 3)], [0., 0., 0.])
        self.assertAlmostEqual(motion.septic(.5), .5)
        self.assertAlmostEqual(motion.septic(.5, 1), 35 / 16)
        self.assertAlmostEqual(motion.septic((5 - math.sqrt(5)) / 10, 2), 84 * math.sqrt(5) / 25)
        self.assertAlmostEqual(motion.septic(.5, 3), -52.5)

    def test_invalid_curves_and_scaling_fail_without_nan_sentinels(self):
        valid = motion.from_positions([0., 1.], [[0.], [1.]])
        for defect in ('missing', 'dimension', 'nan', 'time'):
            bad = copy.deepcopy(valid)
            if defect == 'missing':bad[0].pop('velocities_rad_s')
            elif defect == 'dimension':bad[1]['accelerations_rad_s2'] = [0., 0.]
            elif defect == 'nan':bad[0]['positions_rad'][0] = math.nan
            else:bad[1]['time_s'] = 0.
            with self.subTest(defect=defect), self.assertRaises(ValueError):motion.bounds(bad)
        for factor in (0., -1., math.inf, True):
            with self.subTest(factor=factor), self.assertRaises(ValueError):motion.scale(valid, factor)
        with self.assertRaises(ValueError):motion.evaluate(valid, math.nan)
        with self.assertRaises(ValueError):motion.septic(.5, 4)

    def test_scalar_scurve_short_full_acceleration_and_cruise_respect_limits(self):
        for distance in (.01, 1., 30., 100., -30.):
            points = motion.rest_to_rest(distance, 10., 2., 4.)
            self.assertEqual(points[0]['positions_rad'], [0.])
            self.assertEqual(points[-1]['positions_rad'], [distance])
            for p in (points[0], points[-1]):
                self.assertEqual(p['velocities_rad_s'], [0.])
                self.assertEqual(p['accelerations_rad_s2'], [0.])
            limits = motion.bounds(points)
            for field, limit in [('velocities_rad_s', 10.), ('accelerations_rad_s2', 2.), ('jerks_rad_s3', 4.)]:
                self.assertLessEqual(limits[field]['max_abs'][0], limit + 1e-8)
            for p in points[1:-1]:
                left = motion.evaluate(points, p['time_s'], side='left')
                right = motion.evaluate(points, p['time_s'], side='right')
                for field in motion.FIELDS[:3]:self.assertEqual(left[field], right[field])
        self.assertAlmostEqual(motion.rest_to_rest(.01, 10., 2., 4.)[-1]['time_s'], 4 * (.01 / 8) ** (1 / 3))
        self.assertAlmostEqual(motion.rest_to_rest(100., 10., 2., 4.)[-1]['time_s'], 15.5)

    def test_scalar_scurve_velocity_limited_before_full_acceleration(self):
        points = motion.rest_to_rest(2., .2, 3., 4.)
        limits = motion.bounds(points)
        self.assertAlmostEqual(limits['velocities_rad_s']['max_abs'][0], .2)
        self.assertLess(limits['accelerations_rad_s2']['max_abs'][0], 3.)
        self.assertLessEqual(limits['jerks_rad_s3']['max_abs'][0], 4. + 1e-8)
        self.assertAlmostEqual(points[-1]['time_s'], 10 + 2 * math.sqrt(.2 / 4))

    def test_lid_scurve_honors_ten_degree_per_second_source_setting(self):
        points = motion.rest_to_rest(105., 10., 30., 300.)
        limits = motion.bounds(points)
        self.assertLessEqual(limits['velocities_rad_s']['max_abs'][0], 10. + 1e-10)
        self.assertLess(points[-1]['time_s'], 12.)
        self.assertGreater(points[-1]['time_s'], 10.5)
        mirrored = motion.rest_to_rest(-105., 10., 30., 300.)
        self.assertAlmostEqual(points[-1]['time_s'], mirrored[-1]['time_s'])
        for t in (0., .1, 3., points[-1]['time_s']):
            for field in motion.FIELDS:
                self.assertAlmostEqual(motion.evaluate(points,t)[field][0], -motion.evaluate(mirrored,t)[field][0], places=9)

    def test_scalar_scurve_rejects_invalid_limits_and_zero_movement(self):
        for args in [(0., 1., 1., 1.), (1., 0., 1., 1.), (1., 1., -1., 1.),
                     (1., 1., 1., math.nan), (1., True, 1., 1.)]:
            with self.subTest(args=args), self.assertRaises(ValueError):motion.rest_to_rest(*args)


class FKJetTests(unittest.TestCase):
    def test_rigid_rotation_contains_tangential_centripetal_and_jerk_terms(self):
        q, velocity, acceleration, jerk = .3, .4, -.2, .1
        state = {field: [value, 0., 0., 0., 0., 0.]
                 for field, value in zip(motion.FIELDS, (q, velocity, acceleration, jerk))}
        result = sample_motion.evaluate(simple_kin(), state, [[20., 0., 0.]])
        for actual, length in [(result, 100.), (result['points'][0], 120.)]:
            c, s = math.cos(q), math.sin(q)
            expected = {
                'position_mm': [length * c, length * s, 0.],
                'velocity_mm_s': [-length * s * velocity, length * c * velocity, 0.],
                'acceleration_mm_s2': [-length * c * velocity ** 2 - length * s * acceleration,
                                         -length * s * velocity ** 2 + length * c * acceleration, 0.],
                'jerk_mm_s3': [length * s * velocity ** 3 - 3 * length * c * velocity * acceleration - length * s * jerk,
                                -length * c * velocity ** 3 - 3 * length * s * velocity * acceleration + length * c * jerk, 0.]}
            for field, values in expected.items():
                for a, b in zip(actual[field], values):self.assertAlmostEqual(a, b, places=10)
        for field, value in zip(sample_motion.ANGULAR, (velocity, acceleration, jerk)):
            for a, b in zip(result[field], [0., 0., value]):self.assertAlmostEqual(a, b, places=12)

    def test_real_pickup_frames_match_independent_fk_and_finite_differences(self):
        import centrifuge_robot_pickup as pickup
        scene = pickup.load();kin = pickup.Kinematics(pickup.arm_source(scene), scene)
        q = [.2, -.3, .6, .1, -.5, .4]
        v = [.4, -.2, .1, .3, -.25, .15]
        a = [.1, .2, -.12, .05, .08, -.06]
        j = [-.3, .25, .1, -.15, .2, .12]
        state = dict(zip(motion.FIELDS, [q, v, a, j]))
        local = [12., -7., 36.]
        result = sample_motion.evaluate(kin, state, [local])
        def transform(t):
            angles = [math.degrees(x + w * t + aa * t * t / 2 + jj * t ** 3 / 6)
                      for x, w, aa, jj in zip(q, v, a, j)]
            return kin.tool(angles)
        def at(t):
            return pickup.robot.transform(transform(t), local)
        h = .003
        values = {k: at(k * h) for k in (-2, -1, 0, 1, 2)}
        self.assertLess(math.dist(result['points'][0]['position_mm'], values[0]), 1e-10)
        for i in range(3):
            derivatives = [
                (values[-2][i] - 8 * values[-1][i] + 8 * values[1][i] - values[2][i]) / (12 * h),
                (-values[2][i] + 16 * values[1][i] - 30 * values[0][i] + 16 * values[-1][i] - values[-2][i]) / (12 * h * h),
                (values[2][i] - 2 * values[1][i] + 2 * values[-1][i] - values[-2][i]) / (2 * h ** 3)]
            for field, expected, tolerance in zip(sample_motion.LINEAR[1:], derivatives, [1e-5, 1e-4, .03]):
                self.assertAlmostEqual(result['points'][0][field][i], expected, delta=tolerance)
        # Independent matrix finite differences also cover noncommuting axes;
        # the production evaluator instead propagates world joint-axis jets.
        rotations = {k: transform(k * h) for k in (-2, -1, 0, 1, 2)}
        rd = [[[rotations[0][i][k] for k in range(3)] for i in range(3)]]
        for order in (1, 2, 3):
            matrix = []
            for i in range(3):
                row = []
                for k in range(3):
                    z = {n: rotations[n][i][k] for n in rotations}
                    row.append((z[-2] - 8*z[-1] + 8*z[1] - z[2]) / (12*h) if order == 1
                               else (-z[2] + 16*z[1] - 30*z[0] + 16*z[-1] - z[-2]) / (12*h*h) if order == 2
                               else (z[2] - 2*z[1] + 2*z[-1] - z[-2]) / (2*h**3))
                matrix.append(row)
            rd.append(matrix)
        def times_transpose(a, b):
            return [[sum(a[i][k] * b[n][k] for k in range(3)) for n in range(3)] for i in range(3)]
        for order, field in enumerate(sample_motion.ANGULAR, 1):
            matrix = times_transpose(rd[order], rd[0])
            if order == 3:
                cross = times_transpose(rd[2], rd[1])
                matrix = [[matrix[i][k] + cross[i][k] for k in range(3)] for i in range(3)]
            expected = [(matrix[2][1] - matrix[1][2])/2, (matrix[0][2] - matrix[2][0])/2,
                        (matrix[1][0] - matrix[0][1])/2]
            for actual, approximate in zip(result[field], expected):
                self.assertAlmostEqual(actual, approximate, delta=2e-5)

    def test_rigid_base_rotates_vectors_without_changing_motion_norms(self):
        kin = simple_kin()
        state = {field: [value] + [0.] * 5 for field, value in zip(motion.FIELDS, [.2, .3, -.1, .4])}
        expected = sample_motion.evaluate(kin, state, [[5., 8., 9.]])
        kin.base = [[1., 0., 0., 10.], [0., 0., -1., 20.], [0., 1., 0., 30.], [0., 0., 0., 1.]]
        actual = sample_motion.evaluate(kin, state, [[5., 8., 9.]])
        for field in (*sample_motion.LINEAR[1:], *sample_motion.ANGULAR):
            self.assertAlmostEqual(math.dist(actual[field], [0., 0., 0.]), math.dist(expected[field], [0., 0., 0.]), places=10)
        self.assertEqual(actual['angular_velocity_rad_s'][0], 0.)
        self.assertAlmostEqual(actual['angular_velocity_rad_s'][1], -.3)

    def test_interval_bounds_enclose_dense_analytic_samples_and_knot_sides(self):
        times = [0., .4, .9, 1.5]
        positions = [[0.] * 6, [.2, -.1, .05, .1, -.05, .12],
                     [.1, .15, -.1, .05, .1, -.1], [.3, .1, .05, 0., -.1, .1]]
        points = motion.from_positions(times, positions)
        model = sample_motion.KinematicJets(simple_kin())
        locals = [[0., 0., 0.], [15., -7., 30.]]
        enclosure = sample_motion.bounds(model, points, locals, subdivisions=2)
        self.assertEqual(enclosure['scope'], 'conservative_numeric_interval')
        self.assertFalse(enclosure['formal_floating_point_certificate'])
        curve = motion.Curve(points)
        for t in sorted(set([times[-1] * i / 80 for i in range(81)] + times)):
            for side in ('left', 'right'):
                result = model.evaluate(curve.evaluate(t, side), locals)
                for index, sample in enumerate(result['points']):
                    for field in sample_motion.LINEAR[1:]:
                        self.assertLessEqual(math.dist(sample[field], [0., 0., 0.]), enclosure['points'][index][field] + 1e-8)
                for field in sample_motion.ANGULAR:
                    self.assertLessEqual(math.dist(result[field], [0., 0., 0.]), enclosure[field] + 1e-8)

    def test_interval_fk_time_scaling_matches_derivative_powers(self):
        points = motion.from_positions([0., 1.], [[0.] * 6, [.2, -.1, 0., 0., .1, .05]])
        kin = simple_kin()
        original = sample_motion.bounds(kin, points, [[10., 0., 5.]])
        scaled = sample_motion.bounds(kin, motion.scale(points, 3., 7.), [[10., 0., 5.]])
        for order, field in enumerate(sample_motion.LINEAR[1:], 1):
            self.assertAlmostEqual(scaled[field], original[field] / 3 ** order, places=8)
        for order, field in enumerate(sample_motion.ANGULAR, 1):
            self.assertAlmostEqual(scaled[field], original[field] / 3 ** order, places=8)

    def test_invalid_fk_derivatives_and_nonrigid_frames_are_rejected(self):
        state = {field: [0.] * 6 for field in motion.FIELDS}
        state['jerks_rad_s3'][0] = math.nan
        with self.assertRaises(ValueError):sample_motion.evaluate(simple_kin(), state)
        kin = simple_kin();kin.base[0][0] = 2.
        with self.assertRaises(ValueError):sample_motion.KinematicJets(kin)


if __name__ == '__main__':
    unittest.main()
