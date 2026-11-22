"""Source-derived seminar facade cuts and outward sash interfaces."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as stack
import building_seminar_windows as windows
import relative_floorplan as floor
import tube_carrier_model as portable


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def rotate(point, origin, angle):
    radians = math.radians(angle); c, s = math.cos(radians), math.sin(radians)
    x, y = point[0]-origin[0], point[1]-origin[1]
    return [origin[0]+c*x-s*y, origin[1]+s*x+c*y]+list(point[2:])


def positive_overlap(first, second):
    # Independent separating-axis oracle for two convex plan footprints.
    for polygon in (first, second):
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            normal = [a[1]-b[1], b[0]-a[0]]
            x, y = [dot(point, normal) for point in first], [dot(point, normal) for point in second]
            if min(max(x), max(y))-max(min(x), min(y)) <= 1e-6:
                return False
    return True


class SeminarWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(stack.SOURCE.read_text())
        cls.p = stack.parameters(cls.source)
        cls.plan = stack.level_plan(cls.source, 'EG')
        cls.config = json.loads((ROOT/'model/furnishings/seminar-eg10.json').read_text())['window_front']
        cls.level = {'id': 'EG', 'z_mm': 0, 'clear_top_mm': cls.p['clear_height_mm']}
        cls.result = windows.compile(cls.config, cls.plan, cls.p, cls.level)
        cls.view = cls.result['interface']
        cls.created = {op['body']: op['shape'] for op in cls.result['operations'] if op['action'] == 'create'}

    def test_registered_facade_chain_and_every_band_station_are_accounted_for(self):
        view = self.view
        self.assertEqual(view['source_wall_ids'], ['EW093', 'EW094', 'EW095', 'EW096'])
        self.assertEqual(view['effective_wall_ids'], ['EW093', 'EW094', 'EW094_Align1', 'EW095', 'EW096', 'EW096_Align1'])
        self.assertEqual(view['effective_wall_ids'], [row['wall_id'] for row in view['segments']])
        station = 0; sash_ids = []
        for segment in view['segments']:
            self.assertAlmostEqual(segment['band_interval_mm'][0], station)
            self.assertAlmostEqual(segment['band_interval_mm'][1]-station, segment['length_mm'])
            local = 0
            for interval in segment['coverage']:
                low, high = interval['interval_mm']
                self.assertAlmostEqual(low, local)
                self.assertGreater(high, low)
                local = high
                self.assertIn(interval['kind'], {'sash_aperture', 'end_jamb', 'mullion', 'transition_mullion'})
                if interval['kind'] == 'sash_aperture':
                    sash_ids.append(interval['sash_id'])
                    self.assertLessEqual(high-low, self.config['max_sash_width_mm'])
            self.assertAlmostEqual(local, segment['length_mm'])
            station += local
        self.assertAlmostEqual(station, view['band_length_mm'])
        self.assertEqual(sash_ids, [sash['id'] for sash in view['sashes']])
        self.assertEqual([row['wall_id'] for row in view['segments'] if row['coverage'][0]['kind'] == 'transition_mullion'],
                         ['EW094', 'EW096_Align1'])

    def test_every_pane_and_handle_belongs_to_exactly_one_moving_sash(self):
        self.assertGreater(len(self.view['sashes']), 1)
        covered = []; frames = []
        bodies = {body['id']: body for body in self.result['bodies']}
        for index, sash in enumerate(self.view['sashes'], 1):
            self.assertEqual(sash['label'], 'Fenster '+str(index))
            self.assertEqual(sash['moving_body_ids'], [sash['sash_frame_body_id'], sash['glass_body_id'], sash['handle_body_id']])
            covered += sash['moving_body_ids']; frames.append(sash['fixed_frame_body_id'])
            self.assertNotIn(sash['fixed_frame_body_id'], sash['moving_body_ids'])
            self.assertEqual(sash['axis'], [0, 0, 1])
            self.assertEqual(sash['reference_angle_deg'], 0)
            self.assertEqual(sash['closed_angle_deg'], 0)
            self.assertEqual(abs(sash['angle_deg']), self.config['open_angle_deg'])
            self.assertEqual(len({bodies[name]['component'] for name in sash['moving_body_ids']}), 1)
            self.assertEqual(bodies[sash['handle_body_id']]['role'], 'concept_seminar_window_handle')
        self.assertEqual(len(covered), len(set(covered)))
        self.assertEqual(set(covered+frames), set(bodies))
        self.assertEqual({name for name, body in bodies.items() if body['role'].endswith('_glass')},
                         {sash['glass_body_id'] for sash in self.view['sashes']})
        self.assertTrue(all(component['grounded'] is True for component in self.result['components']))
        self.assertEqual(self.view['native_reference'], 'closed')
        for key in ('dimensions_measured', 'hardware_qualified', 'sweep_collision_qualified', 'weather_sealing_qualified'):
            self.assertIs(self.view[key], False)

    def test_apertures_cut_actual_retained_walls_and_probe_the_complete_height(self):
        wall_ids = {wall['id'] for wall in self.plan['walls']}
        cuts = {op['body']: [] for op in self.result['operations'] if op['action'] == 'cut' and '__Wall_' in op['body']}
        for op in self.result['operations']:
            if op['body'] in cuts:
                cuts[op['body']].append(op)
        self.assertEqual(sum(map(len, cuts.values())), len(self.view['sashes']))
        self.assertEqual(len(self.result['window_probes']), len(self.view['sashes']))
        for sash, probe in zip(self.view['sashes'], self.result['window_probes']):
            self.assertIn(sash['wall_id'], wall_ids)
            self.assertEqual(probe['target_body'], 'EG__Wall_'+sash['wall_id'])
            cut = next(op['shape'] for op in cuts[probe['target_body']] if op['id'] == sash['id']+'_WallCut')
            self.assertEqual(cut['offset'], self.level['z_mm']+self.config['sill_mm'])
            self.assertEqual(cut['depth'], self.config['head_mm']-self.config['sill_mm'])
            xs = [dot(point, sash['outward'][:2]) for point in cut['points']]
            self.assertAlmostEqual(max(xs)-min(xs), 1.4*self.p['display_thickness'])
            self.assertGreater(probe['offset_mm'], cut['offset'])
            self.assertLess(probe['offset_mm']+probe['depth_mm'], cut['offset']+cut['depth'])

    def test_outward_hinges_keep_all_moving_material_clear_of_own_frame_plane(self):
        # This is an own-frame geometric invariant, not a swept-scene proof.
        for sash in self.view['sashes']:
            closed_glass = self.created[sash['glass_body_id']]
            centre = [sum(point[i] for point in closed_glass['points'])/4 for i in (0, 1)]+[closed_glass['offset']]
            moved = rotate(centre, sash['origin_mm'], sash['angle_deg'])
            self.assertGreater(dot([moved[i]-centre[i] for i in (0, 1)], sash['outward'][:2]), 0)
            reference = sash['origin_mm']
            # Origin is on the outermost corner; all material starts behind it
            # and to its free side. The declared outward sign is therefore not
            # interchangeable with an inward-opening angle.
            for body_id in sash['moving_body_ids']:
                for point in self.created[body_id]['points']:
                    initial = dot([point[i]-reference[i] for i in (0, 1)], sash['outward'][:2])
                    for fraction in (0, .1, .25, .5, .75, 1):
                        actual = rotate(point, reference, fraction*sash['angle_deg'])
                        displacement = dot([actual[i]-reference[i] for i in (0, 1)], sash['outward'][:2])
                        self.assertGreaterEqual(displacement, initial-1e-7)
            self.assertGreater(sash['hinge_clearance_mm'], 0)

    def test_sampled_sash_and_handle_sweep_does_not_cross_own_fixed_frame_material(self):
        # Resolve the fixed ring into four positive solids; checking the outer
        # bounding box alone would incorrectly reject the sash in its opening.
        for sash in self.view['sashes']:
            outer = self.created[sash['fixed_frame_body_id']]
            a, b, c, d = outer['points']; width = math.dist(a, b)
            tangent = [(b[i]-a[i])/width for i in (0, 1)]
            f = self.config['frame_mm']
            shift = lambda point, delta: [point[i]+delta*tangent[i] for i in (0, 1)]
            bars = [([a, b, c, d], outer['offset'], outer['offset']+f),
                    ([a, b, c, d], outer['offset']+outer['depth']-f, outer['offset']+outer['depth']),
                    ([a, shift(a, f), shift(d, f), d], outer['offset'], outer['offset']+outer['depth']),
                    ([shift(b, -f), b, c, shift(c, -f)], outer['offset'], outer['offset']+outer['depth'])]
            for body_id in sash['moving_body_ids']:
                shape = self.created[body_id]
                for step in range(15):
                    points = [rotate(point, sash['origin_mm'], sash['angle_deg']*step/14) for point in shape['points']]
                    for footprint, low, high in bars:
                        if min(shape['offset']+shape['depth'], high) > max(shape['offset'], low)+1e-7:
                            self.assertFalse(positive_overlap(points, footprint), (body_id, step))

    def test_each_inspection_viewpoint_is_inside_actual_inset_source_room(self):
        polygon = self.view['room_boundary_polygon_mm']
        for sash in self.view['sashes']:
            eye = sash['viewpoint']['eye_mm']
            self.assertEqual(floor.point_membership(eye[:2], polygon), 1)
            gap = min(windows.point_segment_distance(eye, a, b) for a, b in zip(polygon, polygon[1:]+polygon[:1]))-self.p['display_thickness']/2
            self.assertGreaterEqual(gap, 160)
            self.assertAlmostEqual(gap, sash['viewpoint_wall_clearance_mm'])
            self.assertGreater(eye[2], self.level['z_mm'])
            self.assertLess(eye[2], self.level['clear_top_mm'])

    def test_reversing_stored_wall_directions_preserves_glazing_and_outward_handing(self):
        plan = copy.deepcopy(self.plan)
        changed = set(self.view['effective_wall_ids'])
        for wall in plan['walls']:
            if wall['id'] in changed:
                wall['start'], wall['end'] = wall['end'], wall['start']
        for area in plan['areas']:
            for edge in area['boundary']:
                if edge['wall'] in changed:
                    edge['direction'] *= -1
        result = windows.compile(self.config, plan, self.p, self.level)
        self.assertEqual(result, self.result)

    def test_room_boundary_rotation_keeps_the_one_complete_chain(self):
        plan = copy.deepcopy(self.plan)
        area = next(area for area in plan['areas'] if area['id'] == self.config['area'])
        area['boundary'] = area['boundary'][5:]+area['boundary'][:5]
        actual = windows.compile(self.config, plan, self.p, self.level)
        self.assertEqual(actual['interface']['effective_wall_ids'], self.view['effective_wall_ids'])
        self.assertEqual(actual['operations'], self.result['operations'])

    def test_invalid_or_conflicting_geometry_fails_without_silently_omitting_windows(self):
        for key, value in (('sill_mm', False), ('head_mm', math.nan), ('glass_mm', -1),
                           ('open_angle_deg', 90), ('head_mm', self.config['sill_mm']),
                           ('sash_depth_mm', self.config['glass_mm'])):
            source = copy.deepcopy(self.config); source[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                windows.compile(source, self.plan, self.p, self.level)
        for names in (['EW093', 'EW093'], ['Missing'], ['EW093', 'EW095'], ['EW090']):
            source = copy.deepcopy(self.config); source['wall_ids'] = names
            with self.subTest(names=names), self.assertRaises(ValueError):
                windows.compile(source, self.plan, self.p, self.level)
        plan = copy.deepcopy(self.plan)
        plan['openings'].append({'id': 'Existing', 'wall': 'EW093', 'kind': 'window', 'interval': [.2, .4]})
        with self.assertRaisesRegex(ValueError, 'existing source opening'):
            windows.compile(self.config, plan, self.p, self.level)

    def test_portable_commands_create_all_panes_frames_handles_and_keep_wall_cuts(self):
        result = dict(self.result, joints=[])
        class Provider:
            SOURCE = ROOT/'model/furnishings/seminar-eg10.json'
            expanded = staticmethod(lambda *_: result)
            pose = staticmethod(lambda *_: {})
            samples = staticmethod(lambda *_: [])
        commands = portable.solidcraft_commands(stack.native_spec(self.source, self.p), self.p, Provider)
        created = [command['params']['body_name'] for command in commands if 'body_name' in command['params']]
        self.assertEqual(len(created), len(set(created)))
        self.assertEqual(set(created), set(self.view['body_ids']))
        wall_targets = [command['params']['targets'][0] for command in commands
                        if command['command'] == 'solid.extrude' and command['params'].get('operation') == 'cut'
                        and command['params']['targets'][0].startswith('EG__Wall_')]
        self.assertEqual(len(wall_targets), len(self.view['sashes']))
        self.assertTrue(all(op['shape']['kind'] == 'polygon_prism' and op['shape']['fixed'] is True
                            for op in self.result['operations']))


if __name__ == '__main__':
    unittest.main()
