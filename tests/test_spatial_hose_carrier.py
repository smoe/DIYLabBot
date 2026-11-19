"""Exact static paths and honest nominal collar geometry, without CAD imports."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import spatial_hose_carrier as carrier
import pneumatic_hose as hose


class SpatialHoseCarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = carrier.load()
        # A stable synthetic source-independent fixture remains nominal32 even
        # when the arm's selected collar count changes after native inspection.
        cls.profile = copy.deepcopy(cls.profile)
        cls.profile['geometry']['nominal_link_count'] = 32
        cls.profile['guide_fit']['seed_mode'] = 'chord_midpoint'
        cls.profile['guide_fit']['offsets_xz_mm'] = [[0, 0], [-50, 0], [50, 0],
            [-100, 0], [100, 0], [0, 50], [0, -50], [-50, -50]]
        cls.path = carrier.fit(cls.profile, [-90, 90, 468], [-90, 60, 400], [0, 1, 0], [0, 0, 1])

    def assertPoint(self, actual, expected):
        self.assertLess(math.dist(actual, expected), 1e-8)

    def test_manufacturer_proxy_is_pinned_and_physical_requirements_stay_open(self):
        profile = carrier.validate(copy.deepcopy(self.profile))
        self.assertEqual(profile['reference']['published_outer_diameter_mm'], 34.5)
        self.assertEqual(profile['reference']['published_bend_radius_mm'], 50)
        self.assertEqual(profile['reference']['published_pitch_mm'], 11.3)
        self.assertTrue(all(value is False for value in profile['qualification'].values()))
        self.assertTrue(all(value is None for value in profile['open_requirements'].values()))
        changed = copy.deepcopy(profile);changed['reference']['brochure']['sha256'] = '0'*64
        with self.assertRaises(ValueError): carrier.validate(changed)
        changed = copy.deepcopy(profile);changed['qualification']['dynamic_articulation_verified'] = True
        with self.assertRaises(ValueError): carrier.validate(changed)

    def test_four_native_circles_have_exact_length_endpoints_and_tangent_joins(self):
        self.assertAlmostEqual(self.path['length_mm'], 32*11.3, places=7)
        self.assertGreaterEqual(self.path['min_bend_radius_mm'], 50)
        self.assertEqual(len(self.path['segments']), 4)
        self.assertPoint(self.path['segments'][0]['start_mm'], [-90, 90, 468])
        self.assertPoint(self.path['segments'][-1]['end_mm'], [-90, 60, 400])
        for before, after in zip(self.path['segments'], self.path['segments'][1:]):
            self.assertPoint(before['end_mm'], after['start_mm'])
            self.assertPoint(carrier._at(before, 1)[1], carrier._at(after, 0)[1])
        self.assertPoint(carrier.path_position(self.path, 0)['tangent'], [0, 1, 0])
        self.assertPoint(carrier.path_position(self.path, self.path['length_mm'])['tangent'], [0, 0, 1])
        for segment in self.path['segments']:
            self.assertAlmostEqual(segment['length_mm'], segment['radius_mm']*segment['sweep_rad'])
            for key in ('start_mm', 'through_mm', 'end_mm'):
                self.assertAlmostEqual(math.dist(segment[key], segment['center_mm']), segment['radius_mm'])

    def test_endpoint_tangent_biarc_preserves_hard_radius_and_explicit_leads(self):
        path = carrier.biarc_path([0, 0, 0], [40, 40, 0], [1, 0, 0], [0, 1, 0], 12,
                                  endpoint_straights_mm=(10, 10))
        self.assertPoint(path['segments'][0]['start_mm'], [0, 0, 0])
        self.assertPoint(path['segments'][-1]['end_mm'], [40, 40, 0])
        self.assertEqual(path['segments'][0]['length_mm'], 10)
        self.assertEqual(path['segments'][-1]['length_mm'], 10)
        self.assertAlmostEqual(path['min_bend_radius_mm'], 30)
        self.assertAlmostEqual(path['length_mm'], 20+15*math.pi)
        hose._joined_path(path)
        self.assertPoint(carrier.path_position(path, 0)['tangent'], [1, 0, 0])
        self.assertPoint(carrier.path_position(path, path['length_mm'])['tangent'], [0, 1, 0])
        self.assertFalse(path['qualified'])
        with self.assertRaises(hose.HoseBendError) as caught:
            carrier.biarc_path([0, 0, 0], [40, 40, 0], [1, 0, 0], [0, 1, 0], 31,
                               endpoint_straights_mm=(10, 10))
        self.assertEqual(caught.exception.witness['required_radius_mm'], 31)
        self.assertAlmostEqual(caught.exception.witness['achieved_radius_mm'], 30)
        straight = carrier.biarc_path([0, 0, 0], [100, 0, 0], [1, 0, 0], [1, 0, 0], 50)
        self.assertEqual(straight['length_mm'], 100)
        self.assertIsNone(straight['min_bend_radius_mm'])

    def test_declared_endpoint_biarc_seed_follows_endpoint_frames(self):
        profile = copy.deepcopy(self.profile)
        profile['guide_fit']['seed_mode'] = 'endpoint_biarc'
        profile['guide_fit']['offsets_xz_mm'] = [[0, 0], [-10, 0], [10, 0], [0, 10], [0, -10],
            [-20, 0], [20, 0], [0, 20], [0, -20], [-40, 0], [40, 0]]
        path = carrier.fit(profile, [-110, 120, 330], [-10, 120, 370], [0, 0, -1], [0, 0, 1],
                           search_axes=[[-1, 0, 0], [0, 1, 0], [0, 0, -1]], endpoint_straights_mm=(10, 10))
        self.assertEqual(path['carrier_fit']['seed_mode'], 'endpoint_biarc')
        self.assertAlmostEqual(path['length_mm'], 32*11.3)
        self.assertGreaterEqual(path['min_bend_radius_mm'], 50)
        hose._joined_path(path)
        self.assertEqual(path['segments'][0]['length_mm'], 10)
        self.assertEqual(path['segments'][-1]['length_mm'], 10)
        profile['guide_fit']['seed_mode'] = 'unknown'
        with self.assertRaises(ValueError): carrier.validate(profile)
        with self.assertRaises(ValueError):
            carrier.fit(self.profile, [-90, 90, 468], [-90, 60, 400], [0, 1, 0], [0, 0, 1], seed_mode='unknown')

    def test_carrier_endpoint_leads_are_included_once_in_the_nominal_length(self):
        path = carrier.fit(self.profile, [-90, 90, 468], [-90, 60, 400], [0, 1, 0], [0, 0, 1],
                           endpoint_straights_mm=(10, 15))
        self.assertAlmostEqual(path['length_mm'], 32*11.3, places=7)
        self.assertEqual(path['segments'][0]['kind'], 'line')
        self.assertEqual(path['segments'][0]['length_mm'], 10)
        self.assertEqual(path['segments'][-1]['kind'], 'line')
        self.assertEqual(path['segments'][-1]['length_mm'], 15)
        self.assertAlmostEqual(sum(s['length_mm'] for s in path['segments'][1:-1]), 32*11.3-25, places=7)
        self.assertGreaterEqual(path['min_bend_radius_mm'], 50)
        hose._joined_path(path)
        self.assertEqual(path['carrier_fit']['endpoint_straights_mm'], [10, 15])
        with self.assertRaises(ValueError):
            carrier.fit(self.profile, [-90, 90, 468], [-90, 60, 400], [0, 1, 0], [0, 0, 1],
                        endpoint_straights_mm=(200, 200))

    def test_search_frame_rotates_with_endpoint_frames_instead_of_world_axes(self):
        def point(p): return [p[1]+50, p[2]-20, p[0]+3.5]
        def vector(p): return [p[1], p[2], p[0]]
        moved = carrier.fit(self.profile, point([-90, 90, 468]), point([-90, 60, 400]),
                            vector([0, 1, 0]), vector([0, 0, 1]),
                            search_axes=[vector([1, 0, 0]), vector([0, 1, 0]), vector([0, 0, 1])])
        self.assertAlmostEqual(moved['length_mm'], self.path['length_mm'])
        self.assertEqual(moved['carrier_fit']['guide_offset_xz_mm'], self.path['carrier_fit']['guide_offset_xz_mm'])
        for old, new in zip(self.path['segments'], moved['segments']):
            self.assertEqual(old['kind'], new['kind'])
            for key in ('start_mm', 'through_mm', 'end_mm', 'center_mm'):
                self.assertPoint(new[key], point(old[key]))
            self.assertPoint(new['axis'], vector(old['axis']))
            self.assertAlmostEqual(new['radius_mm'], old['radius_mm'])

    def test_nonorthonormal_search_frames_and_invalid_leads_fail_closed(self):
        for axes in ([[1, 0, 0]], [[1, 0, 0], [1, 0, 0], [0, 0, 1]],
                     [[-1, 0, 0], [0, 1, 0], [0, 0, 1]],
                     [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
                     [[1, 0, 0], [0, math.nan, 0], [0, 0, 1]]):
            with self.subTest(axes=axes), self.assertRaises(ValueError):
                carrier.fit(self.profile, [-90, 90, 468], [-90, 60, 400], [0, 1, 0], [0, 0, 1],
                            search_axes=axes)
        for leads in ((-1, 0), (0, True), (0, math.inf), (1,)):
            with self.subTest(leads=leads), self.assertRaises(ValueError):
                carrier.biarc_path([0, 0, 0], [40, 40, 0], [1, 0, 0], [0, 1, 0], 12,
                                   endpoint_straights_mm=leads)
        with self.assertRaises(hose.HoseBendError) as caught:
            carrier.biarc_path([0, 0, 0], [40, 40, 0], [1, 0, 0], [0, 1, 0], 12,
                               endpoint_straights_mm=(40, 40))
        self.assertEqual(caught.exception.witness['kind'], 'endpoint_tangent_biarc')

    def test_arc_length_stations_are_distinguished_from_rigid_link_chords(self):
        record = carrier.carrier_records(self.profile, self.path)
        self.assertEqual(len(record['links']), 32)
        self.assertEqual(len(set(record['native_aliases'])), 32)
        self.assertIn('not', self.profile['reference']['radius_datum_scope'])
        self.assertIn('adjacent chords are shorter', record['scope'])
        for a, b in zip(record['links'], record['links'][1:]):
            self.assertAlmostEqual(b['arc_length_mm']-a['arc_length_mm'], 11.3)
            self.assertLessEqual(math.dist(a['center_mm'], b['center_mm']), 11.3+1e-8)
        self.assertTrue(any(math.dist(a['center_mm'], b['center_mm']) < 11.29
                            for a, b in zip(record['links'], record['links'][1:])))
        self.assertGreater(record['collar_containment']['outer_margin_lower_bound_mm'], .2)
        self.assertGreater(record['collar_containment']['inner_margin_lower_bound_mm'], .15)
        self.assertTrue(all(link['component'] == 'CarrierSnapshot' for link in record['links']))

    def test_rigid_placement_preserves_native_arcs_and_all_nominal_stations(self):
        matrix = [[0, -1, 0, 100], [1, 0, 0, -50], [0, 0, 1, 7], [0, 0, 0, 1]]
        moved = carrier.transform_path(self.path, matrix)
        self.assertEqual(moved['length_mm'], self.path['length_mm'])
        for s in (0, 17.5, 110, 200, self.path['length_mm']):
            old = carrier.path_position(self.path, s);new = carrier.path_position(moved, s)
            self.assertPoint(new['point_mm'], [100-old['point_mm'][1], old['point_mm'][0]-50, old['point_mm'][2]+7])
            self.assertPoint(new['tangent'], [-old['tangent'][1], old['tangent'][0], old['tangent'][2]])
        self.assertEqual(len(moved['segments']), 4)
        self.assertNotEqual(moved['segments'][0]['start_mm'], self.path['segments'][0]['start_mm'])

    def test_only_a_bounded_static_nonlocal_self_check_is_reported(self):
        check = self.path['carrier_fit']['nonlocal_self_check']
        self.assertTrue(check['passed'])
        self.assertEqual(check['maximum_sample_step_mm'], 5)
        self.assertGreater(check['sample_spacing_distance_lower_bound_mm'], 34.5)
        self.assertIn('Finite', check['scope'])
        self.assertFalse(self.path['qualified'])
        json.dumps(self.path, allow_nan=False)

    def test_invalid_endpoints_tangents_and_impossible_spans_are_rejected(self):
        for bad in ([0, 0], [0, True, 0], [math.nan, 0, 0], [0, math.inf, 0]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                carrier.fit(self.profile, bad, [1, 2, 3], [0, 1, 0], [0, 0, 1])
        with self.assertRaises(ValueError): carrier.fit(self.profile, [0, 0, 0], [1, 2, 3], [0, 0, 0], [0, 0, 1])
        with self.assertRaises(ValueError): carrier.fit(self.profile, [0, 0, 0], [0, 0, 0], [0, 1, 0], [0, 0, 1])
        with self.assertRaises(ValueError): carrier.fit(self.profile, [0, 0, 0], [1000, 0, 0], [0, 1, 0], [0, 0, 1])
        for distance in (-1, self.path['length_mm']+1, math.inf, True):
            with self.subTest(distance=distance), self.assertRaises(ValueError): carrier.path_position(self.path, distance)

    def test_invalid_radius_or_collar_geometry_does_not_become_a_qualified_model(self):
        for section, key, value in [('geometry', 'minimum_centerline_bend_radius_mm', 49.9),
                                    ('geometry', 'nominal_link_count', True),
                                    ('geometry', 'inner_radius_mm', 20),
                                    ('guide_fit', 'fit_iterations', 0)]:
            changed = copy.deepcopy(self.profile);changed[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): carrier.validate(changed)
        changed = copy.deepcopy(self.profile);changed['geometry']['ring_geometry']['outer_radius_mm'] = 17.25
        with self.assertRaises(ValueError): carrier.validate(changed)
        wrong = copy.deepcopy(self.path);wrong['length_mm'] += 1
        with self.assertRaises(ValueError): carrier.carrier_records(self.profile, wrong)

    def test_nonrigid_or_left_handed_placements_are_rejected(self):
        for matrix in ([[[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                        [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 1, 1]]]):
            with self.subTest(matrix=matrix), self.assertRaises(ValueError): carrier.transform_path(self.path, matrix)

    def test_solidcraft_profiles_preserve_holes_and_aliases_for_two_semantic_bodies(self):
        record = carrier.carrier_records(self.profile, self.path)
        envelope = carrier.solidcraft_envelope_commands(record)
        sweeps = [command for command in envelope if command['command'] == 'solid.sweep']
        self.assertEqual(len(sweeps), 1)
        self.assertEqual(sweeps[0]['params']['profiles'], [{'curves': ['c1']}])
        commands = carrier.solidcraft_links_commands(record)
        extrusions = [command for command in commands if command['command'] == 'solid.extrude']
        self.assertEqual([command['params']['body_name'] for command in extrusions], record['native_aliases'])
        self.assertTrue(all(command['params']['profiles'] == [{'curves': ['c1']}] for command in extrusions))
        self.assertEqual(len(extrusions), 32)


if __name__ == '__main__':
    unittest.main()
