"""Continuous native-centreline separation for concurrent depot starts."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from building_fleet_departure import (_clear, _fit_margin, _limits, independent_starter_end,
                                      inside_departure_room, rectangular_starter_end)
from building_fleet_motion import Path as Route


class DepartureGeometryTests(unittest.TestCase):
    limits = dict(max_step_s=.05, velocity_mm_s=100., acceleration_mm_s2=50.)

    def starter(self, leader, follower, **overrides):
        return independent_starter_end(leader, follower, 100., 10., **(self.limits | overrides))

    def test_disjoint_return_loop_grants_complete_first_straight(self):
        leader = Route([[600., -300.], [600., 900.], [1200., 900.], [1200., -300.]])
        follower = Route([[0., 0.], [0., 500.], [400., 500.]])
        self.assertEqual(self.starter(leader, follower), follower.ends[0])

    def test_oblique_late_leader_return_truncates_a_straight(self):
        # The first half of the leader's route is distant, the return crosses the starter.
        leader = Route([[200., 900.], [1100., 900.], [400., -400.]], trim_mm=30.)
        follower = Route([[0., 0.], [1400., 0.]])
        prefix = self.starter(leader, follower)
        self.assertGreater(prefix, 200.)
        self.assertLess(prefix, 500.)
        reversed_leader = Route([[400., -400.], [1100., 900.], [200., 900.]], trim_mm=30.)
        self.assertAlmostEqual(prefix, self.starter(reversed_leader, follower), delta=.02)

    def test_coincident_home_or_fitted_envelope_thickness_blocks_entry(self):
        follower = Route([[0., 0.], [0., 800.]])
        self.assertEqual(self.starter(follower, follower), 0.)
        leader = Route([[240., 0.], [240., 800.]])
        self.assertEqual(self.starter(leader, follower), 800.)
        # The geometric axes remain separated, but the faster inter-tick envelope grows.
        self.assertEqual(self.starter(leader, follower, velocity_mm_s=1450.), 0.)
        tangent = Route([[210., 0.], [210., 800.]])
        self.assertEqual(self.starter(tangent, follower), 0.)

    def test_interior_bezier_conflict_and_separated_diagonal(self):
        # At u=1/2 the quadratic passes through (50,0); both ends are at y=100.
        self.assertFalse(_clear([(0., 100.), (50., -100.), (100., 100.)], 100., 1.))
        # The AABB overlaps the start but de Casteljau subdivision proves separation.
        self.assertTrue(_clear([(-100., 0.), (0., 100.)], 240., 70.))
        self.assertFalse(_clear([(-100., 0.), (0., 100.)], 240., 71.))

    def test_concave_room_checks_both_ends_and_crossed_edges(self):
        room = [[0., 0.], [1000., 0.], [1000., 1000.], [600., 1000.],
                [600., 300.], [400., 300.], [400., 1000.], [0., 1000.]]
        path = Route([[200., 500.], [800., 500.]])
        self.assertTrue(inside_departure_room(path, 120., room, 70., **self.limits))
        self.assertFalse(inside_departure_room(path, 600., room, 70., **self.limits))
        self.assertFalse(inside_departure_room(path, 128., room, 70., **self.limits))
        self.assertFalse(inside_departure_room(path, 601., room, 0., **self.limits))
        outside = Route([[-100., 500.], [300., 500.]])
        self.assertFalse(inside_departure_room(outside, 50., room, 0., **self.limits))

    def test_source_limits_and_curvature_enlarge_fitted_sweep(self):
        limits = _limits(.05, 1450., 500.)
        straight = Route([[0., 0.], [300., 0.]])
        margin = _fit_margin(straight.pieces, limits)
        self.assertGreater(margin, .9 * 1450. * .05 + 500. * .05**2 / 20.)
        corner = Route([[0., 0.], [100., 0.], [100., 100.]], trim_mm=1.)
        self.assertGreater(_fit_margin(corner.pieces, limits), margin)
        self.assertGreater(_fit_margin(straight.pieces, _limits(.4,1450.,500.)), margin)
        for step, speed, acceleration in ((.401, 100., 50.), (.05, math.nan, 50.), (.05, 10., 0.)):
            with self.assertRaises(ValueError):
                _limits(step, speed, acceleration)

    def test_rectangular_parallel_straights_preserve_the_exact_lateral_reserve(self):
        follower = Route([[500.,0.],[500.,800.]])
        forward = Route([[0.,0.],[0.,1200.]])
        reverse = Route([[0.,1200.],[0.,0.]])
        envelope = {'length_mm':512., 'width_mm':412.}
        for path in (forward,reverse):
            with self.subTest(path=path.pieces):
                # The source body gap is 500 - 412 = 88 mm, above the 85 mm reserve.
                self.assertEqual(rectangular_starter_end(path,follower,envelope,85.),800.)
                self.assertEqual(rectangular_starter_end(path,follower,envelope,88.),0.)
                self.assertEqual(independent_starter_end(path,follower,math.hypot(256,206),85.),0.)

    def test_rectangular_crossing_reserves_body_lengths_and_limits_the_prefix(self):
        follower = Route([[0.,0.],[1400.,0.]])
        protected = Route([[1000.,-500.],[1000.,500.]])
        envelope = {'length_mm':512., 'width_mm':412.}
        prefix = rectangular_starter_end(protected,follower,envelope,85.,**self.limits)
        physical_bound = 1000. - (512. + 412.)/2 - 85.
        fit = self.limits['velocity_mm_s']*self.limits['max_step_s']/2
        self.assertLess(prefix,physical_bound-fit)
        self.assertAlmostEqual(prefix,physical_bound-fit,delta=.02)

    def test_rectangular_joint_bands_block_a_cross_piece_interval(self):
        follower = Route([[500.,0.],[500.,450.]])
        parallel = Route([[0.,0.],[0.,900.]])
        away_at_end = Route([[0.,0.],[0.,900.],[-600.,900.]],trim_mm=15.)
        envelope = {'length_mm':512., 'width_mm':412.}
        self.assertEqual(rectangular_starter_end(parallel,follower,envelope,85.),450.)
        # The turn is aimed away. The test still accounts for the fit and full
        # vehicle yaw of any interval with one endpoint on that turn.
        prefix = rectangular_starter_end(away_at_end,follower,envelope,85.)
        self.assertGreater(prefix,40.)
        self.assertLess(prefix,450.)

    def test_rectangular_prefix_keeps_horizon_tolerance_on_first_straight(self):
        follower = Route([[500.,0.],[500.,900.],[1500.,900.]])
        protected = Route([[0.,0.],[0.,1500.]])
        envelope = {'length_mm':512., 'width_mm':412.}
        prefix = rectangular_starter_end(protected,follower,envelope,85.)
        self.assertAlmostEqual(prefix,follower.ends[0],delta=3e-5)
        self.assertLess(prefix+1e-5,follower.ends[0])
