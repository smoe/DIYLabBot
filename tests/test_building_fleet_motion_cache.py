"""Exact-input reuse must retain the authoritative polynomial proof results."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_motion as motion


def curve(count=4):
    F = motion.F
    return motion.floor.motion.Curve([
        {'time_s': i*.125,
         F[0]: [100.*i, (-1.)**i*20., .05*i],
         F[1]: [100., 10.*i, .1], F[2]: [5.*i, -2., .01*i]}
        for i in range(count)])


def direct_dynamics(value, radius):
    result = {kind: dict.fromkeys(('velocity', 'acceleration', 'jerk'), 0.)
              for kind in ('linear', 'angular', 'carried_points')}
    for a, b in zip(value.points, value.points[1:]):
        proof = motion.floor.dynamics([a, b], radius)
        for kind in result:
            for key, number in proof[kind].items():
                result[kind][key] = max(result[kind][key], number)
    return result


class ExactProofCacheTests(unittest.TestCase):
    def setUp(self):
        motion._cached_interval_dynamics.cache_clear()
        motion._cached_extrema_window.cache_clear()

    def test_dynamics_equal_authoritative_results_and_repeat_avoids_root_work(self):
        value = curve()
        expected = direct_dynamics(value, 329.)
        checker = motion.floor.dynamics
        with patch.object(motion.floor, 'dynamics', wraps=checker) as checked:
            first = motion.episode_dynamics(value, 329.)
            self.assertEqual(checked.call_count, 3)
            second = motion.episode_dynamics(copy.deepcopy(value), 329.)
            self.assertEqual(checked.call_count, 3)
        for kind in expected:
            self.assertEqual(first[kind], expected[kind])
            self.assertEqual(second[kind], expected[kind])
        first['linear']['jerk'] = -1
        self.assertEqual(motion.episode_dynamics(value, 329.)['linear'], expected['linear'])

    def test_dynamics_keys_cover_point_bits_types_signed_zero_and_radius(self):
        value = curve(2)
        motion.episode_dynamics(value, 329.)
        variants = []
        changed = copy.deepcopy(value)
        changed.points[1][motion.F[0]][0] = math.nextafter(changed.points[1][motion.F[0]][0], math.inf)
        variants.append((changed, 329.))
        changed = copy.deepcopy(value)
        changed.points[0][motion.F[0]][0] = -0.
        variants.append((changed, 329.))
        changed = copy.deepcopy(value)
        changed.points[0][motion.F[1]][0] = 100
        variants.append((changed, 329.))
        variants.extend([(value, math.nextafter(329., math.inf)), (value, 329)])
        for expected_misses, (changed, radius) in enumerate(variants, 2):
            expected = direct_dynamics(changed, radius)
            actual = motion.episode_dynamics(changed, radius)
            self.assertEqual(motion._cached_interval_dynamics.cache_info().misses, expected_misses)
            for kind in expected:
                self.assertEqual(actual[kind], expected[kind])

    def test_invalid_mutated_point_cannot_reuse_previously_accepted_proof(self):
        value = curve(2)
        motion.episode_dynamics(value, 329.)
        value.points[0]['time_s'] = False
        with self.assertRaises(ValueError):
            motion.episode_dynamics(value, 329.)

    def test_extrema_reuse_includes_both_closed_knot_sides_and_all_orders(self):
        value = curve()
        at = value.times[1]
        for order in range(4):
            expected = motion.floor.extrema(value, at, at, order)
            first = motion.interval_extrema(value, at, at, order)
            second = motion.interval_extrema(copy.deepcopy(value), at, at, order)
            self.assertEqual(first, expected)
            self.assertEqual(second, expected)
        self.assertEqual(motion._cached_extrema_window.cache_info().hits, 4)
        first['min'][0] = -1e99
        self.assertEqual(motion.interval_extrema(value, at, at, 3),
                         motion.floor.extrema(value, at, at, 3))

    def test_extrema_keys_cover_coefficients_time_window_types_and_zero_bits(self):
        value = curve()
        start, end = value.times[0], value.times[1]
        motion.interval_extrema(value, start, end, 1)
        variants = []
        changed = copy.deepcopy(value)
        changed.segments[0][0][3] = math.nextafter(changed.segments[0][0][3], math.inf)
        variants.append((changed, start, end, 1))
        changed = copy.deepcopy(value)
        changed.segments[0][0][0] = -0.
        variants.append((changed, start, end, 1))
        changed = copy.deepcopy(value)
        changed.segments[0][0][0] = 0
        variants.append((changed, start, end, 1))
        variants.extend([(value, math.nextafter(start, math.inf), end, 1),
                         (value, start, math.nextafter(end, -math.inf), 1),
                         (value, start, end, 2)])
        for expected_misses, (changed, a, b, order) in enumerate(variants, 2):
            self.assertEqual(motion.interval_extrema(changed, a, b, order),
                             motion.floor.extrema(changed, a, b, order))
            self.assertEqual(motion._cached_extrema_window.cache_info().misses, expected_misses)

    def test_large_extrema_windows_do_not_fill_unbounded_cache_keys(self):
        value = curve(12)
        self.assertEqual(motion.interval_extrema(value), motion.floor.extrema(value))
        self.assertEqual(motion._cached_extrema_window.cache_info().currsize, 0)
        self.assertEqual(motion._cached_extrema_window.cache_info().maxsize, 16384)
        self.assertEqual(motion._cached_interval_dynamics.cache_info().maxsize, 16384)


if __name__ == '__main__':
    unittest.main()
