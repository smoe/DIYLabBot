"""Bitwise review of XY-only access; these fixtures are not fleet proofs."""
import math
from pathlib import Path
import random
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_model as model
import building_fleet_motion as motion


def binary64(values):
    return struct.pack('!' + 'd' * len(values), *values)


class LegacyPositionPath(motion.Path):
    """Retain the former full-evaluation XY access during construction."""
    def position(self, progress):
        return self.evaluate(progress)[0][:2]


def route_cases():
    routes = [
        ([[0., 0.], [1., 0.]], .1),
        ([[-0., -0.], [100., -0.], [1000., -0.]], 25.),
        ([[0., 0.], [1000., 0.], [1000., 1000.]], 250.),
        ([[0., 0.], [500., 350.], [1500., -120.], [700., -700.]], 120.),
        ([[0., 0.], [800., 0.], [800., 600.], [0., 600.], [0., 0.], [1000., -400.]], 100.),
        ([[1e9, -1e9], [1e9 + 1234.56789, -1e9 + 81.25],
          [1e9 + 2000.25, -1e9 + 1600.75], [1e9 - 20.5, -1e9 + 2300.125]], 130.),
    ]
    return [(points, trim) for points, trim in routes] + [
        (list(reversed(points)), trim) for points, trim in routes]


def queries(path):
    rng = random.Random(20261121)
    result = [-math.inf, -1e9, -1., -0., 0., path.length, path.length + 1., math.inf]
    before = 0.
    for end, piece in zip(path.ends, path.pieces):
        for knot in (before, end):
            result.extend((math.nextafter(knot, -math.inf), knot,
                           math.nextafter(knot, math.inf)))
        result.extend(before + piece['weight'] * u for u in (0., .125, 1/3, .5, .875, 1.))
        before = end
    result.extend(rng.uniform(-.1, 1.1) * path.length for _ in range(200))
    return result


class PositionAccessReview(unittest.TestCase):
    def test_xy_matches_full_evaluation_bitwise_at_knots_clips_and_curves(self):
        for points, trim in route_cases():
            path = motion.Path(points, trim)
            for progress in queries(path):
                with self.subTest(points=points, progress=progress):
                    actual = path.position(progress)
                    self.assertEqual(len(actual), 2)
                    self.assertEqual(binary64(actual), binary64(path.evaluate(progress)[0][:2]))

    def test_complete_sampling_grid_matches_former_full_evaluation(self):
        for points, trim in route_cases():
            path = motion.Path(points, trim)
            original = []
            for index, piece in enumerate(path.pieces):
                before = path.ends[index - 1] if index else 0
                count = max(1, math.ceil(piece['weight'] / 25))
                for i in range(count):
                    a = before + piece['weight'] * i / count
                    b = before + piece['weight'] * (i + 1) / count
                    original.append((a, b, path.evaluate(a)[0][:2], path.evaluate(b)[0][:2]))
            self.assertEqual(len(original), len(path.samples))
            for expected, actual in zip(original, path.samples):
                self.assertEqual(binary64(expected[:2]), binary64(actual[:2]))
                self.assertEqual(binary64(expected[2]), binary64(actual[2]))
                self.assertEqual(binary64(expected[3]), binary64(actual[3]))

    def test_reused_sample_endpoints_remain_independent_lists(self):
        path = motion.Path([[0., 0.], [1000., 0.], [1000., 1000.]])
        arrays = [xy for _, _, a, b in path.samples for xy in (a, b)]
        self.assertEqual(len({id(xy) for xy in arrays}), len(arrays))
        for (_, b, _, end), (a, _, start, _) in zip(path.samples, path.samples[1:]):
            if a == b:
                expected = binary64(start)
                end[0] += 123.
                self.assertEqual(binary64(start), expected)
                self.assertEqual(binary64(path.position(a)), expected)
                break
        else:
            self.fail('Fixture must exercise adjacent identical sample times')

    def test_first_derivative_validation_keeps_former_constructor_rejections(self):
        points = [[0., 0.], [1000., 0.], [0., .001]]
        for implementation in (motion.Path, LegacyPositionPath):
            with self.subTest(implementation=implementation.__name__):
                with self.assertRaisesRegex(ValueError, 'Non-cusped spatial route required'):
                    implementation(points)
        path = object.__new__(motion.Path)
        path.pieces = []; path.ends = []; path.length = 0.
        path._add([[0., 0., 0.], [1., 0., 0.], [0., 0., 0.]], 2.)
        for accessor in (path.position, path.evaluate):
            with self.assertRaisesRegex(ValueError, 'Non-cusped spatial route required'):
                accessor(1.)

    def test_xy_access_skips_only_unused_higher_derivative_evaluation(self):
        path = motion.Path([[0., 0.], [1000., 0.], [1000., 1000.]])
        progress = path.ends[0] + path.pieces[1]['weight'] / 3
        calls = []
        original = motion.CornerPath._bezier
        def record(controls, u):
            calls.append(controls)
            return original(controls, u)
        expected = binary64(path.evaluate(progress)[0][:2])
        with patch.object(path, 'evaluate', side_effect=AssertionError('Full PVA access is unnecessary')):
            with patch.object(motion.CornerPath, '_bezier', side_effect=record):
                self.assertEqual(binary64(path.position(progress)), expected)
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0], path.pieces[1]['controls'])
        self.assertIs(calls[1], path.pieces[1]['derivatives'][0])

    def test_full_motion_export_is_unchanged_by_position_only_construction(self):
        points = [[0., 0.], [3000., 0.], [3000., 3000.]]
        current = motion.Path(points)
        original = LegacyPositionPath(points)
        self.assertEqual(current.pieces, original.pieces)
        for progress in queries(current):
            self.assertEqual(current.pva(progress, 123.5, -45.25),
                             original.pva(progress, 123.5, -45.25))
        source = model.load()
        self.assertEqual(motion.compile_motion(current, source, 300),
                         motion.compile_motion(original, source, 300))


if __name__ == '__main__':
    unittest.main()
