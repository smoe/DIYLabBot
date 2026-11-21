"""Independent analytic checks for the bounded trigonometric load optimizer."""

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from joint_load_math import build_trig_model, maximize_absolute


class JointLoadMathTests(unittest.TestCase):
    def assertEncloses(self, result, expected):
        self.assertLessEqual(result["lower_bound"], expected + 1e-10)
        self.assertGreaterEqual(result["upper_bound"], expected - 1e-10)

    def test_sinusoid_has_known_interior_extremum(self):
        model = build_trig_model(lambda q: 2 + 3 * math.cos(math.radians(q[0]))
                                 + 4 * math.sin(math.radians(q[0])), 1)
        result = maximize_absolute(model, [[-180, 180]], tolerance=1e-6)
        self.assertEncloses(result, 7.0)
        self.assertTrue(result["converged"])
        self.assertAlmostEqual(result["witness_deg"][0], math.degrees(math.atan2(4, 3)), places=8)
        self.assertLess(result["gap"], 1e-6)

    def test_bounded_box_endpoint_is_the_maximum(self):
        model = build_trig_model(lambda q: math.sin(math.radians(q[0])), 1)
        result = maximize_absolute(model, [[10, 30]], tolerance=1e-9)
        self.assertEncloses(result, 0.5)
        self.assertAlmostEqual(result["witness_deg"][0], 30.0)
        self.assertTrue(result["converged"])

    def test_product_cancellation_and_independent_reconstruction(self):
        def objective(q):
            x, y = map(math.radians, q)
            return math.sin(x) * math.cos(y) - math.cos(x) * math.sin(y)
        model = build_trig_model(objective, 2)
        result = maximize_absolute(model, [[-20, 30], [-10, 25]], tolerance=1e-6)
        # sin(x-y) is increasing throughout [-45, 40] degrees.
        expected = math.sin(math.radians(45))
        self.assertEncloses(result, expected)
        self.assertTrue(result["converged"])
        self.assertAlmostEqual(result["witness_deg"][0], -20.0)
        self.assertAlmostEqual(result["witness_deg"][1], 25.0)

    def test_cell_cap_reports_an_unresolved_global_gap(self):
        model = build_trig_model(lambda q: math.cos(math.radians(q[0] + q[1])), 2)
        result = maximize_absolute(model, [[-170, 170], [-170, 170]], tolerance=1e-12, max_cells=1)
        self.assertEncloses(result, 1.0)
        self.assertFalse(result["converged"])
        self.assertEqual(result["evaluated_cells"], 1)
        self.assertGreater(result["gap"], 0.1)
        self.assertIn("not_formal_interval_certificate", result["bound_status"])

    def test_four_dimensional_tensor_has_an_independent_norm_bound(self):
        def objective(q):
            a, b, c, d = map(math.radians, q)
            return (0.7 + 1.2 * math.cos(a) * math.sin(b) * math.cos(c) * math.sin(d)
                    - 0.4 * math.sin(a) * math.cos(d))
        model = build_trig_model(objective, 4)
        result = maximize_absolute(model, [[-60, 80], [-70, 90], [-40, 50], [-20, 95]],
                                   tolerance=0.01)
        # For every a,b,c the varying part's d-amplitude is at most
        # sqrt(1.2^2*cos(a)^2 + 0.4^2*sin(a)^2) <= 1.2. It reaches
        # 1.2 at a=c=0, b=d=90 degrees, inside this box.
        self.assertEncloses(result, 1.9)
        self.assertTrue(result["converged"])
        self.assertAlmostEqual(objective(result["witness_deg"]), result["witness_value"])

    def test_zero_width_and_zero_function(self):
        model = build_trig_model(lambda q: 0.0, 2)
        result = maximize_absolute(model, [[13, 13], [-5, -5]], tolerance=1e-8)
        self.assertEncloses(result, 0.0)
        self.assertTrue(result["converged"])
        self.assertEqual(result["witness_deg"], [13.0, -5.0])

    def test_discarded_small_coefficients_remain_in_error_budget(self):
        model = build_trig_model(lambda q: 1 + 1e-13 * math.cos(math.radians(q[0])), 1)
        self.assertGreater(model["coefficient_error_bound"], 0)
        result = maximize_absolute(model, [[-180, 180]], tolerance=1e-8)
        self.assertEncloses(result, 1 + 1e-13)

    def test_unsupported_harmonics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "first-harmonic"):
            build_trig_model(lambda q: math.cos(2 * math.radians(q[0])), 1)

    def test_nonfinite_objectives_and_malformed_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            build_trig_model(lambda q: float("nan"), 1)
        with self.assertRaises(ValueError):
            build_trig_model(lambda q: 0, 0)
        model = build_trig_model(lambda q: math.cos(math.radians(q[0])), 1)
        for bounds in ([], [[20, -20]], [[0, float("inf")]], [[0, 10, 20]]):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                maximize_absolute(model, bounds)
        for kwargs in ({"max_cells": 0}, {"tolerance": 0}, {"seeds_deg": [[500]]},
                       {"seeds_deg": [[float("nan")]]}, {"seeds_deg": [[0, 1]]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                maximize_absolute(model, [[-10, 10]], **kwargs)


if __name__ == "__main__":
    unittest.main()
