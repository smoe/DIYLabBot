"""Static hose geometry invariants; these are not flow or pressure tests."""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import pneumatic_hose as hose


def direction(vector):
    length = math.sqrt(sum(v*v for v in vector))
    return [v/length for v in vector]


def tangent(segment, end=False):
    if segment['kind'] == 'line':
        return direction([b-a for a, b in zip(segment['start_mm'], segment['end_mm'])])
    point = segment['end_mm'] if end else segment['start_mm']
    r = [p-c for p, c in zip(point, segment['center_mm'])]
    a = segment['axis']
    return direction([a[1]*r[2]-a[2]*r[1], a[2]*r[0]-a[0]*r[2], a[0]*r[1]-a[1]*r[0]])


class PneumaticHoseTests(unittest.TestCase):
    ROUTE = [[0, 0, 0], [0, 0, 30], [30, 0, 30], [30, 30, 30], [30, 30, 80]]

    def assertPointAlmostEqual(self, actual, expected, places=9):
        self.assertEqual(len(actual), 3)
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=places)

    def test_native_sweep_contract_rejects_gaps_and_c0_only_splices(self):
        path = hose.centerline(self.ROUTE, 12)
        hose._joined_path(path)
        disconnected = {'segments': [
            {'kind': 'line', 'start_mm': [0, 0, 0], 'end_mm': [0, 0, 10]},
            {'kind': 'line', 'start_mm': [0, 0, 11], 'end_mm': [0, 0, 20]}]}
        corner = {'segments': [
            {'kind': 'line', 'start_mm': [0, 0, 0], 'end_mm': [0, 0, 10]},
            {'kind': 'line', 'start_mm': [0, 0, 10], 'end_mm': [10, 0, 10]}]}
        for invalid in (disconnected, corner):
            with self.assertRaises(ValueError):
                hose._joined_path(invalid)

    def test_nonlocal_self_check_catches_the_upright_pump_tail_crossing(self):
        # Reduced geometric regression for the observed source failure: a
        # returning tail crosses the initial axial pump lead in the same plane.
        controls = [[-90, 0, 428], [-90, 0, 468], [-90, 90, 468],
                    [-90, 90, 360], [-90, 60, 360], [-90, 60, 420],
                    [-90, -60, 445], [-35, 45, 505]]
        bad = hose.self_clearance_diagnostics(hose.centerline(controls, 12), .9)
        self.assertFalse(bad['passed'])
        self.assertLess(bad['minimum_sampled_centerline_distance_mm'], .5)
        self.assertEqual(bad['near_segment_witness']['first']['segment_index'], 0)
        self.assertFalse(bad['continuous_self_clearance_verified'])
        moved = [list(point) for point in controls];moved[-2][0] = -125
        good = hose.self_clearance_diagnostics(hose.centerline(moved, 12), .9)
        self.assertTrue(good['passed'])
        self.assertGreater(good['sample_spacing_distance_lower_bound_mm'], 1.8)

    def test_nonlocal_self_check_keeps_short_local_neighbors_separate(self):
        short = hose.centerline([[0, 0, 0], [0, 0, 2]])
        report = hose.self_clearance_diagnostics(short, .9)
        self.assertTrue(report['passed'])
        self.assertEqual(report['checked_pairs'], 0)
        self.assertIsNone(report['near_segment_witness'])
        self.assertIn('excluded local neighborhood', report['scope'])
        for radius, step in ((0, .5), (.9, 0), (True, .5), (.9, math.inf)):
            with self.assertRaises(ValueError): hose.self_clearance_diagnostics(short, radius, step)

    def test_straight_hose_preserves_exact_endpoints_and_length(self):
        points = [[12.5, -3, 7], [12.5, -3, 107]]
        path = hose.centerline(points)
        self.assertEqual(path['sample_points_mm'][0], points[0])
        self.assertEqual(path['sample_points_mm'][-1], points[-1])
        self.assertEqual(path['length_mm'], 100)
        self.assertIsNone(path['min_bend_radius_mm'])
        self.assertTrue(all(s['kind'] == 'line' for s in path['segments']))
        self.assertFalse(path['qualified'])

    def test_right_angle_rounding_has_the_analytic_quarter_circle(self):
        radius = 12
        path = hose.centerline([[0, 0, 0], [0, 0, 30], [30, 0, 30]], radius)
        self.assertAlmostEqual(path['length_mm'], 60-2*radius+math.pi*radius/2)
        arc, = [s for s in path['segments'] if s['kind'] == 'arc']
        self.assertPointAlmostEqual(arc['start_mm'], [0, 0, 18])
        self.assertPointAlmostEqual(arc['end_mm'], [12, 0, 30])
        self.assertPointAlmostEqual(arc['center_mm'], [12, 0, 18])
        self.assertPointAlmostEqual(arc['through_mm'],
                                    [12-12/math.sqrt(2), 0, 18+12/math.sqrt(2)])
        self.assertAlmostEqual(arc['radius_mm'], radius)
        self.assertAlmostEqual(arc['sweep_rad'], math.pi/2)

    def test_spatial_fillets_form_a_connected_tangent_wire(self):
        path = hose.centerline(self.ROUTE, 12)
        self.assertEqual(len([s for s in path['segments'] if s['kind'] == 'arc']), 3)
        self.assertAlmostEqual(path['length_mm'], 140-72+18*math.pi)
        for before, after in zip(path['segments'], path['segments'][1:]):
            self.assertPointAlmostEqual(before['end_mm'], after['start_mm'])
            self.assertPointAlmostEqual(tangent(before, end=True), tangent(after))
        # Every arc sample lies on its reported circle, independently of its plane.
        for segment in path['segments']:
            if segment['kind'] == 'arc':
                for key in ('start_mm', 'through_mm', 'end_mm'):
                    self.assertAlmostEqual(math.dist(segment[key], segment['center_mm']),
                                           segment['radius_mm'])

    def test_rigidly_moving_the_arm_route_preserves_hose_geometry(self):
        def transform(p):
            # Proper rigid rotation (cyclic axis permutation) followed by translation.
            return [p[1]+50, p[2]-20, p[0]+3.5]
        original = hose.centerline(self.ROUTE, 12)
        moved = hose.centerline([transform(p) for p in self.ROUTE], 12)
        self.assertAlmostEqual(original['length_mm'], moved['length_mm'])
        self.assertAlmostEqual(original['min_bend_radius_mm'], moved['min_bend_radius_mm'])
        self.assertEqual(len(original['segments']), len(moved['segments']))
        for a, b in zip(original['segments'], moved['segments']):
            self.assertEqual(a['kind'], b['kind'])
            self.assertAlmostEqual(a['length_mm'], b['length_mm'])
            for key in ('start_mm', 'end_mm', 'through_mm', 'center_mm'):
                if key in a:
                    self.assertPointAlmostEqual(transform(a[key]), b[key])

    def test_air_and_wall_volumes_are_geometric_and_not_dosing_evidence(self):
        path = hose.centerline([[0, 0, 0], [0, 0, 100]])
        report = hose.diagnostics(path, .3, .9)
        self.assertAlmostEqual(report['air_volume_ul'], 9*math.pi)
        self.assertAlmostEqual(report['wall_volume_mm3'], 72*math.pi)
        self.assertAlmostEqual(report['air_volume_ul']+report['wall_volume_mm3'], 81*math.pi)
        self.assertFalse(path['qualified'])
        self.assertNotIn('dispensed_volume_ul', report)
        self.assertIn('no selected-hose', report['scope'])

    def test_short_spans_reject_the_hard_radius_with_a_geometric_witness(self):
        controls = [[0, 0, 0], [0, 0, 10], [10, 0, 10]]
        with self.assertRaises(hose.HoseBendError) as caught:
            hose.centerline(controls, 12)
        witness = caught.exception.witness
        self.assertEqual(witness['control_indices'], [0, 1])
        self.assertEqual(witness['available_mm'], 10)
        self.assertAlmostEqual(witness['required_mm'], 12)
        self.assertEqual(witness['required_radius_mm'], 12)
        # A different explicit design requirement is allowed; an automatic
        # reduction from R12 to R4 is not.
        path = hose.centerline(controls, 4)
        self.assertEqual(path['requested_bend_radius_mm'], 4)
        self.assertEqual(path['min_bend_radius_mm'], 4)
        for outer in (path['min_bend_radius_mm'], math.nextafter(path['min_bend_radius_mm'], math.inf)):
            with self.subTest(outer=outer), self.assertRaises(ValueError):
                hose.solidcraft_commands(path, .3, outer)

    def test_two_adjacent_corners_must_fit_the_sum_of_both_tangent_setbacks(self):
        controls = [[0, 0, 0], [0, 0, 20], [20, 0, 20], [20, 0, 40]]
        with self.assertRaises(hose.HoseBendError) as caught:
            hose.centerline(controls, 12)
        witness = caught.exception.witness
        self.assertEqual(witness['control_indices'], [1, 2])
        self.assertEqual(witness['available_mm'], 20)
        self.assertAlmostEqual(witness['required_mm'], 24)
        for value in witness['tangent_setbacks_mm']:
            self.assertAlmostEqual(value, 12)
        controls[2][0] = controls[3][0] = 24
        path = hose.centerline(controls, 12)
        hose._joined_path(path)
        self.assertEqual(path['min_bend_radius_mm'], 12)
        self.assertAlmostEqual(path['bend_constraints']['spans'][1]['remaining_straight_mm'], 0)

    def test_connector_and_guide_endpoint_straights_are_reserved_before_rounding(self):
        controls = [[0, 0, 0], [0, 0, 30], [30, 0, 30]]
        path = hose.centerline(controls, 12, endpoint_straights_mm=(18, 18))
        self.assertAlmostEqual(path['segments'][0]['length_mm'], 18)
        self.assertAlmostEqual(path['segments'][-1]['length_mm'], 18)
        for leads in ((18.01, 18), (18, 18.01)):
            with self.subTest(leads=leads), self.assertRaises(hose.HoseBendError) as caught:
                hose.centerline(controls, 12, endpoint_straights_mm=leads)
            self.assertGreater(caught.exception.witness['required_mm'], caught.exception.witness['available_mm'])
        # Collinear source markers do not introduce an artificial short span.
        straight = hose.centerline([[0, 0, 0], [0, 0, 10], [0, 0, 30]],
                                  endpoint_straights_mm=(15, 15))
        self.assertEqual(len(straight['segments']), 1)
        self.assertEqual(straight['length_mm'], 30)
        with self.assertRaises(hose.HoseBendError):
            hose.centerline([[0, 0, 0], [0, 0, 30]], endpoint_straights_mm=(15, 16))

    def test_invalid_endpoint_straight_requirements_are_rejected(self):
        for leads in (None, [], [0], [0, 0, 0], [-1, 0], [0, True], [math.inf, 0], [0, math.nan]):
            with self.subTest(leads=leads), self.assertRaises(ValueError):
                hose.centerline(self.ROUTE, endpoint_straights_mm=leads)

    def test_degenerate_and_nonfinite_route_points_are_rejected(self):
        invalid = [None, [], [[0, 0, 0]], [[0, 0, 0], [0, 0, 0]],
                   [[0, 0, 0], [1, 0, 0], [0, 0, 0]],
                   [[True, 0, 0], [1, 0, 0]], [[0, 0], [1, 0, 0]],
                   [[0, 0, 0], [math.inf, 0, 0]], [[0, 0, 0], [0, math.nan, 0]]]
        for route in invalid:
            with self.subTest(route=route), self.assertRaises(ValueError):
                hose.centerline(route)

    def test_invalid_bend_and_sampling_settings_are_rejected(self):
        for value in (0, -1, True, math.nan, math.inf):
            for name in ('bend_radius', 'sample_step_mm'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    hose.centerline(self.ROUTE, **{name: value})

    def test_invalid_tube_radii_are_rejected_before_native_execution(self):
        path = hose.centerline(self.ROUTE)
        for inner, outer in ((0, .9), (-.3, .9), (.9, .3), (.9, .9),
                             (True, .9), (.3, math.nan), (.3, math.inf)):
            with self.subTest(inner=inner, outer=outer):
                with self.assertRaises(ValueError):
                    hose.diagnostics(path, inner, outer)
                with self.assertRaises(ValueError):
                    hose.solidcraft_commands(path, inner, outer)

    def test_native_sweep_selects_the_annulus_and_does_not_depend_on_sampling_density(self):
        coarse = hose.centerline(self.ROUTE, 12, sample_step_mm=10)
        fine = hose.centerline(self.ROUTE, 12, sample_step_mm=.5)
        self.assertNotEqual(len(coarse['sample_points_mm']), len(fine['sample_points_mm']))
        self.assertEqual(coarse['segments'], fine['segments'])
        commands = hose.solidcraft_commands(coarse, .3, .9)
        self.assertEqual(commands, hose.solidcraft_commands(fine, .3, .9))
        sweeps = [c['params'] for c in commands if c['command'] == 'solid.sweep']
        annular, = sweeps
        self.assertEqual(annular['operation'], 'new')
        self.assertEqual(annular['profiles'], [{'curves': ['c1']}])
        self.assertEqual(len(annular['path']), len(coarse['segments']))
        # Selecting all nested-circle regions previously produced a filled
        # native hose.  Select the outer region explicitly, with its inner hole.
        circles = [c['params']['radius'] for c in commands if c['command'] == 'sketch.circle.center']
        self.assertEqual(circles, [.9, .3])

    def test_solidcraft_circle_parameter_seam_preserves_the_spatial_annulus(self):
        # Native regression: SMLib rejected an otherwise exact thin toroidal
        # arc with a large radius at the former circle parameter origin.
        # Rotating a circular profile's basis changes no material or lumen.
        path = hose.centerline([[17, -4, 12], [47, 26, 42], [60, 50, 80]])
        start, normal, old_x, old_y = hose._start_frame(path)
        commands = hose.solidcraft_commands(path, .25, .9)
        plane, = [c['params']['plane'] for c in commands
                  if c['command'] == 'sketch.create' and isinstance(c['params']['plane'], dict)]
        self.assertEqual(hose.SOLIDCRAFT_PROFILE_SEAM_DEG, 90)
        self.assertPointAlmostEqual(plane['origin'], start)
        self.assertPointAlmostEqual(plane['x_dir'], old_y)
        self.assertPointAlmostEqual(plane['y_dir'], [-v for v in old_x])
        x, y = plane['x_dir'], plane['y_dir']
        cross = [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
        self.assertPointAlmostEqual(cross, normal)
        for radius in (.25, .9):
            for angle in (0, .7, 2.4, 5.1):
                radial = [radius*(math.cos(angle)*a+math.sin(angle)*b) for a, b in zip(x, y)]
                self.assertAlmostEqual(math.sqrt(sum(v*v for v in radial)), radius)
                self.assertAlmostEqual(sum(a*b for a, b in zip(radial, normal)), 0)


if __name__ == '__main__':
    unittest.main()
