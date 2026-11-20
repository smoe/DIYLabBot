"""Independent witnesses for conservative source-only hose clearance bounds."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import arm_syringe_clearance as clearance
import pneumatic_hose as hose
import robot_spec as robot


class SourceEnvelopeTests(unittest.TestCase):
    def assert_contains(self, bounds, point):
        for axis in range(3):
            self.assertLessEqual(bounds['min'][axis], point[axis]+1e-11)
            self.assertGreaterEqual(bounds['max'][axis], point[axis]-1e-11)

    def test_arbitrary_axis_cylinder_and_tapered_cone_enclose_sampled_surfaces(self):
        axis = [1/math.sqrt(14), 2/math.sqrt(14), 3/math.sqrt(14)]
        u = [2/math.sqrt(5), -1/math.sqrt(5), 0]
        v = [axis[1]*u[2]-axis[2]*u[1], axis[2]*u[0]-axis[0]*u[2],
             axis[0]*u[1]-axis[1]*u[0]]
        origin, height = [2, -3, 4], 7
        for kind, end_radius in (('cylinder', 2), ('cone', 5), ('cone', .5)):
            shape = {'kind': kind, 'origin': origin, 'axis': [1, 2, 3],
                     'height': 'height', 'radius': 2, 'top_radius': end_radius}
            bounds = clearance.primitive_bounds(shape, {'height': height})
            with self.subTest(kind=kind, end_radius=end_radius):
                for fraction in (0, .25, .5, .75, 1):
                    radius = 2+fraction*(end_radius-2)
                    for angle in [i*math.pi/24 for i in range(48)]:
                        point = [origin[i]+fraction*height*axis[i]
                                 +radius*(math.cos(angle)*u[i]+math.sin(angle)*v[i])
                                 for i in range(3)]
                        self.assert_contains(bounds, point)
                # A non-axis-aligned cap projects into every coordinate.
                self.assertTrue(all(bounds['min'][i] < origin[i] for i in range(3)))

    def test_vendor_bounds_use_registered_local_frame_and_polygon_depth_uses_its_normal(self):
        vendor = {'kind': 'vendor_step', 'origin': [10, 20, 30], 'axis': [0, 1, 0],
                  'x': [0, 0, 1], 'bbox_mm': {'min': [-2, -1, -.5], 'max': [4, 3, 2]}}
        self.assertEqual(clearance.primitive_bounds(vendor, {}),
                         {'min': [9, 19.5, 28], 'max': [13, 22, 34]})
        prism = {'kind': 'polygon_prism', 'origin': [5, 6, 7], 'u_axis': [1, 0, 0],
                 'v_axis': [0, 0, 2], 'depth': 3,
                 'loops': [[[0, 0], [2, 0], [2, 1], [0, 1]],
                           [[.5, .2], [1, .2], [1, .6], [.5, .6]]]}
        self.assertEqual(clearance.primitive_bounds(prism, {}),
                         {'min': [5, 3, 7], 'max': [7, 6, 9]})

    @staticmethod
    def source_rows(operations):
        arm = {'links': [{'id': 'L0', 'recipe': operations}]}
        with patch.object(robot, 'expanded', return_value=arm):
            return clearance.source_envelopes({}, {'components': [], 'bodies': [], 'operations': []}, {}, {})

    def test_unions_and_translation_expand_move_bounds_while_cuts_never_reduce_them(self):
        operations = [
            {'action': 'create', 'body': 'Body', 'primitive':
             {'kind': 'box', 'origin': [0, 0, 0], 'size': [1, 2, 3]}},
            {'action': 'join', 'body': 'Body', 'primitive':
             {'kind': 'cylinder', 'origin': [2, 0, 0], 'axis': [0, 0, 1], 'radius': 1, 'height': 1}},
            {'action': 'union', 'targets': ['Body'], 'primitive':
             {'kind': 'box', 'origin': [-4, 5, 0], 'size': [1, 1, 1]}},
            {'action': 'translate', 'targets': ['Body'], 'vector': [10, -2, 1]},
            {'action': 'create', 'body': 'View', 'role': 'viewing_cone', 'primitive':
             {'kind': 'cone', 'origin': [0, 0, 0], 'radius': 50, 'top_radius': 0, 'height': 100}},
        ]
        before = self.source_rows(operations)
        after = self.source_rows(operations+[
            {'action': 'cut', 'body': 'Body', 'primitive':
             {'kind': 'box', 'origin': [-100, -100, -100], 'size': [200, 200, 200]}},
            {'action': 'subtract', 'targets': ['Body'], 'primitive':
             {'kind': 'box', 'origin': [-100, -100, -100], 'size': [200, 200, 200]}},
        ])
        self.assertEqual(after, before)
        self.assertEqual(len(after), 1)
        row, = after
        self.assertEqual(row['body'], 'Body')
        self.assertEqual(row['component'], 'L0')
        self.assertIs(row['arm_body'], True)
        self.assertEqual(row['numeric_envelope_padding_mm'], 1e-6)
        self.assertEqual(row['bbox'], {'min': [6-1e-6, -3-1e-6, 1-1e-6],
                                      'max': [13+1e-6, 4+1e-6, 4+1e-6]})

    def test_unsupported_primitive_or_action_fails_instead_of_omitting_a_body(self):
        with self.assertRaises(ValueError):
            clearance.primitive_bounds({'kind': 'sphere', 'origin': [0, 0, 0], 'radius': 1}, {})
        for action in ('scale', 'rotate', 'unimplemented'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.source_rows([{'action': action, 'body': 'Body'}])


class SourceRouteClearanceTests(unittest.TestCase):
    @staticmethod
    def path(start, end, kind='bare_span', part_id='span'):
        path = hose.centerline([start, end])
        path['length_accounting'] = {'parts': [{'id': part_id, 'kind': kind,
                                               'length_mm': path['length_mm']}]}
        return path

    @staticmethod
    def envelope(bounds, *, arm=True):
        return {'body': 'WitnessBody', 'component': 'Host', 'bbox': bounds, 'arm_body': arm}

    def test_uncut_cylinder_proves_real_corner_clearance_inside_its_enclosing_box(self):
        for raw_axis in ([0, 0, 1], [0, 1, 0], [1, 2, 3]):
            norm = math.sqrt(sum(value*value for value in raw_axis))
            axis = [value/norm for value in raw_axis]
            planar = math.hypot(axis[0], axis[1])
            x = [-axis[1]/planar, axis[0]/planar, 0.] if planar > 1e-9 else [1., 0., 0.]
            y = [axis[1]*x[2]-axis[2]*x[1], axis[2]*x[0]-axis[0]*x[2],
                 axis[0]*x[1]-axis[1]*x[0]]
            origin = [3., -4., 2.]
            point = lambda along, u, v: [origin[i]+along*axis[i]+u*x[i]+v*y[i] for i in range(3)]
            body = SourceEnvelopeTests.source_rows([{'action': 'create', 'body': 'Cylinder',
                'primitive': {'kind': 'cylinder', 'origin': origin, 'axis': raw_axis,
                              'radius': 10., 'height': 20.}}])
            route = self.path(point(5, 8, 8), point(15, 8, 8))
            analytic_gap = math.hypot(8, 8)-10-.5
            with self.subTest(axis=raw_axis):
                self.assertGreater(analytic_gap, .8)
                result = clearance.check_route(route, body, {'L0': robot.identity()}, .5, .5,
                                               sample_step_mm=1.)
                self.assertTrue(result['passed'])
                self.assertGreater(result['minimum_margin_lower_bound_mm'], .3)

    def test_cylinder_interior_and_radius_overlap_fail_even_when_cuts_remove_material(self):
        create = {'action': 'create', 'body': 'Cylinder', 'primitive': {
            'kind': 'cylinder', 'origin': [0, 0, 0], 'axis': [0, 0, 1], 'radius': 10., 'height': 20.}}
        cut = {'action': 'cut', 'body': 'Cylinder', 'primitive': {
            'kind': 'box', 'origin': [-20, -20, -1], 'size': [40, 40, 22]}}
        before = SourceEnvelopeTests.source_rows([create])
        after = SourceEnvelopeTests.source_rows([create, cut])
        self.assertEqual(after, before)
        for radial in (0., 9.9, 10.3):
            with self.subTest(radial=radial):
                path = self.path([radial, 0, 5], [radial, 0, 15])
                result = clearance.check_route(path, after, {'L0': robot.identity()}, .5, .5,
                                               sample_step_mm=1.)
                self.assertFalse(result['passed'])
                self.assertEqual(result['classification'], 'envelope_proximity')

    def test_positive_primitive_union_keeps_its_real_gap_and_moves_all_members(self):
        operations = [
            {'action': 'create', 'body': 'Body', 'primitive': {
                'kind': 'cylinder', 'origin': [0, 0, 0], 'radius': 2., 'height': 4.}},
            {'action': 'join', 'body': 'Body', 'primitive': {
                'kind': 'box', 'origin': [10, 0, 0], 'size': [2., 2., 4.]}},
            {'action': 'translate', 'targets': ['Body'], 'vector': [20, -3, 7]},
            {'action': 'cut', 'body': 'Body', 'primitive': {
                'kind': 'box', 'origin': [-100, -100, -100], 'size': [200, 200, 200]}}]
        bodies = SourceEnvelopeTests.source_rows(operations)
        # Both original positive solids still obstruct after the translation.
        for x, y in ((20, -3), (31, -2)):
            with self.subTest(inside=(x, y)):
                result = clearance.check_route(self.path([x, y, 8], [x, y, 10]), bodies,
                    {'L0': robot.identity()}, .1, .1, sample_step_mm=.5)
                self.assertFalse(result['passed'])
        # The gap between those solids is inside their combined AABB but clear.
        gap = clearance.check_route(self.path([25, -3, 8], [25, -3, 10]), bodies,
            {'L0': robot.identity()}, .1, .1, sample_step_mm=.5)
        self.assertTrue(gap['passed'])
        # No obsolete unshifted primitive may remain in the enclosure.
        old = clearance.check_route(self.path([0, 0, 1], [0, 0, 3]), bodies,
            {'L0': robot.identity()}, .1, .1, sample_step_mm=.5)
        self.assertTrue(old['passed'])

    def test_local_oriented_box_proves_a_gap_that_a_world_aabb_would_lose(self):
        c = math.sqrt(.5)
        matrix = [[c, -c, 0, 10], [c, c, 0, 20], [0, 0, 1, 30], [0, 0, 0, 1]]
        bounds = {'min': [-1, -.1, -.1], 'max': [1, .1, .1]}
        start, end = (robot.transform(matrix, point) for point in ([-.5, .8, 0], [.5, .8, 0]))
        midpoint = robot.transform(matrix, [0, .8, 0])
        # The midpoint lies inside the rotated body's enclosing world AABB.
        self.assertLess(abs(midpoint[0]-10), 1.1*c)
        self.assertLess(abs(midpoint[1]-20), 1.1*c)
        result = clearance.check_route(self.path(start, end), [self.envelope(bounds)],
                                       {'Host': matrix}, .1, 2, sample_step_mm=.2)
        self.assertTrue(result['passed'])
        self.assertGreaterEqual(result['minimum_margin_lower_bound_mm'], .49)

    def test_half_step_bound_catches_a_crossing_between_distant_samples(self):
        path = self.path([0, 0, 0], [10, 0, 0])
        body = self.envelope({'min': [4.9, -.1, -.1], 'max': [5.1, .1, .1]})
        result = clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
                                       sample_step_mm=10)
        self.assertFalse(result['passed'])
        self.assertEqual(result['classification'], 'envelope_proximity')
        self.assertLess(result['witness']['margin_lower_bound_mm'], 0)
        self.assertGreater(result['witness']['arc_length_mm'], 0)
        self.assertLess(result['witness']['arc_length_mm'], 10)
        # Both endpoint samples alone are far clear; the interval bound matters.
        self.assertGreater(min(math.dist(point, [5, 0, 0]) for point in ([0, 0, 0], [10, 0, 0])), 4)

    def test_adaptive_refinement_proves_a_small_positive_gap_without_changing_geometry_or_radius(self):
        path = self.path([0, 0, 0], [10, 0, 0])
        body = self.envelope({'min': [4.9, .21, -.1], 'max': [5.1, .31, .1]})
        coarse = clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
                                       sample_step_mm=10, minimum_sample_step_mm=10)
        self.assertFalse(coarse['passed'])
        refined = clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
                                        sample_step_mm=10, minimum_sample_step_mm=.05)
        self.assertTrue(refined['passed'])
        self.assertGreater(refined['minimum_margin_lower_bound_mm'], 0)
        self.assertGreater(refined['refined_interval_count'], 0)
        self.assertLess(refined['finest_interval_mm'], .22)
        self.assertGreater(refined['interval_evaluations'], 1)
        self.assertEqual(refined['maximum_sample_step_mm'], 10)
        self.assertEqual(refined['minimum_sample_step_mm'], .05)
        self.assertIn('adaptive interval', refined['scope'])

    def test_supported_socket_regions_still_check_the_arm_and_bare_regions_check_tooling(self):
        bounds = {'min': [4, -1, -1], 'max': [6, 1, 1]}
        for kind in ('inserted', 'socket_strain_relief', 'connector_straight_lead', 'clip_straight'):
            path = self.path([0, 0, 0], [10, 0, 0], kind)
            with self.subTest(kind=kind):
                arm = clearance.check_route(path, [self.envelope(bounds)],
                                            {'Host': robot.identity()}, .1, 2, sample_step_mm=1)
                self.assertFalse(arm['passed'])
                owned = clearance.check_route(path, [self.envelope(bounds, arm=False)],
                                              {'Host': robot.identity()}, .1, 2, sample_step_mm=1)
                self.assertFalse(owned['passed'])
                intended = self.path([0, 0, 0], [10, 0, 0], kind, 'pump_'+kind)
                mating = clearance.check_route(intended, [self.envelope(bounds, arm=False)],
                    {'Host': robot.identity()}, .1, 2, sample_step_mm=1,
                    socket_mating_bodies={'pump': ['WitnessBody']})
                self.assertEqual(mating['passed'], kind != 'clip_straight')
                other = {**self.envelope(bounds, arm=False), 'body': 'UnrelatedTool'}
                both = clearance.check_route(intended, [self.envelope(bounds, arm=False), other],
                    {'Host': robot.identity()}, .1, 2, sample_step_mm=1,
                    socket_mating_bodies={'pump': ['WitnessBody']})
                self.assertFalse(both['passed'])
                if kind != 'clip_straight':
                    self.assertEqual(both['witness']['body'], 'UnrelatedTool')
        bare = clearance.check_route(self.path([0, 0, 0], [10, 0, 0]),
                                     [self.envelope(bounds, arm=False)], {'Host': robot.identity()},
                                     .1, 2, sample_step_mm=1)
        self.assertFalse(bare['passed'])

    def test_socket_exemption_cannot_cover_a_half_step_interval_extending_into_bare_hose(self):
        path = self.path([0, 0, 0], [10, 0, 0])
        path['length_accounting']['parts'] = [
            {'id': 'pump_inserted', 'kind': 'inserted', 'length_mm': 1},
            {'id': 'free', 'kind': 'bare_span', 'length_mm': 9}]
        body = self.envelope({'min': [2, -.1, -.1], 'max': [2.1, .1, .1]}, arm=False)
        result = clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
            sample_step_mm=10, socket_mating_bodies={'pump': ['WitnessBody']})
        self.assertFalse(result['passed'])
        self.assertEqual(result['classification'], 'envelope_proximity')

    def test_carrier_guard_uses_its_outer_radius_instead_of_the_tube_radius(self):
        body = self.envelope({'min': [-1, 1.4, -.1], 'max': [11, 1.5, .1]}, arm=False)
        outcomes = {}
        for kind in ('bare_span', 'nominal_carrier'):
            outcomes[kind] = clearance.check_route(self.path([0, 0, 0], [10, 0, 0], kind),
                [body], {'Host': robot.identity()}, .2, 2, sample_step_mm=.25)
        self.assertTrue(outcomes['bare_span']['passed'])
        self.assertFalse(outcomes['nominal_carrier']['passed'])

    def test_malformed_material_partition_cannot_hide_spans_from_tooling_checks(self):
        body = self.envelope({'min': [4, -.1, -.1], 'max': [6, .1, .1]}, arm=False)
        invalid = [[], [{'id': 'span', 'kind': 'unknown', 'length_mm': 10}],
                   [{'id': 'span', 'kind': 'inserted', 'length_mm': 5}]]
        invalid += [[{'id': 'span', 'kind': 'bare_span', 'length_mm': value}]
                    for value in (0, -1, math.nan, math.inf, True)]
        for parts in invalid:
            path = self.path([0, 0, 0], [10, 0, 0])
            path['length_accounting']['parts'] = parts
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
                                      sample_step_mm=1)

    def test_malformed_socket_mapping_cannot_create_broad_or_substring_exemptions(self):
        path = self.path([0, 0, 0], [10, 0, 0], 'inserted', 'pump_inserted')
        body = self.envelope({'min': [4, -.1, -.1], 'max': [6, .1, .1]}, arm=False)
        invalid = [[], True, 'WitnessBody', {'pump': 'WitnessBody'}, {'pump': []},
                   {'pump': ['WitnessBody', 'WitnessBody']}, {'pump': ['']},
                   {'pump': [1]}, {'unknown': ['WitnessBody']}]
        for mapping in invalid:
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
                    sample_step_mm=1, socket_mating_bodies=mapping)
        # Similar names are not the declared body, even with a valid mapping.
        exact = clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
            sample_step_mm=1, socket_mating_bodies={'pump': ['WitnessBodyExtra']})
        self.assertFalse(exact['passed'])

    def test_invalid_radii_or_sample_steps_cannot_produce_clearance_acceptance(self):
        path = self.path([0, 0, 0], [10, 0, 0])
        body = self.envelope({'min': [4, -.1, -.1], 'max': [6, .1, .1]})
        for tube, guard, step in ((-1, 2, 1), (.1, -2, 1), (math.nan, 2, 1),
                                  (.1, math.inf, 1), (.1, 2, 0), (.1, 2, -1),
                                  (.1, 2, math.inf), (True, 2, 1), (2, .1, 1)):
            with self.subTest(tube=tube, guard=guard, step=step), self.assertRaises(ValueError):
                clearance.check_route(path, [body], {'Host': robot.identity()}, tube, guard,
                                      sample_step_mm=step)
        for minimum_step in (0, -.1, math.inf, math.nan, True, 2):
            with self.subTest(minimum_step=minimum_step), self.assertRaises(ValueError):
                clearance.check_route(path, [body], {'Host': robot.identity()}, .1, 2,
                                      sample_step_mm=1, minimum_sample_step_mm=minimum_step)


if __name__ == '__main__':
    unittest.main()
