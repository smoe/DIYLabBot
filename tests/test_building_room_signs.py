"""Independent corridor-side geometry and narrow annotation validation cases."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_room_signs as signs
import build_building_stack as evidence
import building_stack as building
import relative_floorplan as floor


def sign_source():
    return {'format': 'solidcraftbot.corridor-room-signs/1',
            'selection': 'known_room_corridor_doors', 'side': 'right_from_corridor',
            'letter_case': 'uppercase',
            'width_mm': 400., 'minimum_width_mm': 180., 'height_mm': 160.,
            'center_height_mm': 1550., 'jamb_gap_mm': 60., 'wall_gap_mm': 2.,
            'thickness_mm': 4., 'text_height_mm': 24., 'line_width_mm': 2.,
            'text_margin_mm': 10., 'background_color': '#FFFFFF',
            'ink_color': '#18242B', 'basis': 'unmeasured_presentation_assumption'}


def two_area_plan(room_side='north'):
    # Both polygons share exactly one horizontal wall; no global room centre
    # or handed-frame helper is used to define the expected observer's right.
    vertices = {'A': [0., 0.], 'B': [5000., 0.], 'N2': [5000., 3000.],
                'N3': [0., 3000.], 'S2': [5000., -2000.], 'S3': [0., -2000.]}
    edges = [('Shared', 'A', 'B'), ('NorthRight', 'B', 'N2'),
             ('NorthTop', 'N2', 'N3'), ('NorthLeft', 'N3', 'A'),
             ('SouthLeft', 'A', 'S3'), ('SouthBottom', 'S3', 'S2'),
             ('SouthRight', 'S2', 'B')]
    north = [{'wall': wall, 'direction': 1}
             for wall in ('Shared', 'NorthRight', 'NorthTop', 'NorthLeft')]
    south = [{'wall': wall, 'direction': 1}
             for wall in ('SouthLeft', 'SouthBottom', 'SouthRight')]+[
                 {'wall': 'Shared', 'direction': -1}]
    areas = [{'id': 'Room' if side == room_side else 'Corridor',
              'kind': 'room' if side == room_side else 'corridor',
              'label': 'Known room' if side == room_side else 'Corridor',
              'boundary': boundary} for side, boundary in [('north', north), ('south', south)]]
    return {'vertices': vertices,
            'walls': [{'id': name, 'start': a, 'end': b, 'kind': 'wall'} for name, a, b in edges],
            'areas': areas,
            'openings': [{'id': 'Door', 'kind': 'door', 'wall': 'Shared', 'interval': [.3, .5]}]}


class CorridorRoomSignTests(unittest.TestCase):
    def setUp(self):
        self.source = sign_source()
        self.p = {'display_scale': 1., 'display_thickness': 200.,
                  'door_height_mm': 2150., 'display_height': 4000.}
        self.levels = [{'id': 'OG3', 'z_mm': 12750.}]
        self.names = {('OG3', 'Room'): {'text': '3.003 Labor', 'basis': 'owner_confirmed'}}

    def compile(self, plan=None, *, source=None, names=None, omitted=(), door_geometry=None):
        plan = two_area_plan() if plan is None else plan
        with patch.object(signs.labels, 'labels', return_value=self.names if names is None else names):
            return signs.compile(self.source if source is None else source, {},
                {'OG3': plan}, self.p, self.levels, omitted_wall_ids=omitted,
                door_geometry=door_geometry)

    def test_right_is_from_the_corridor_on_both_sides_of_the_wall(self):
        for side, direction, jamb_x in [('north', 1., 2500.), ('south', -1., 1500.)]:
            with self.subTest(room_side=side):
                result = self.compile(two_area_plan(side));record, = result['interface']['signs']
                self.assertEqual(record['right_vector'], [direction, 0., 0.])
                self.assertEqual(record['front_normal'], [0., -direction, 0.])
                self.assertEqual(record['right_jamb_mm'], [jamb_x, 0., 14300.])
                self.assertAlmostEqual(record['center_mm'][0], jamb_x+direction*260.)
                self.assertAlmostEqual(record['center_mm'][1], -direction*102.)
                self.assertEqual(record['center_mm'][2], 14300.)
                self.assertEqual(record['corridor_id'], 'Corridor')
                # Every plate point stays wholly beyond the right jamb.
                plate = next(op['shape'] for op in result['operations'] if op['body'].endswith('_Plate'))
                offsets = [(point[0]-jamb_x)*direction for point in plate['points']]
                self.assertAlmostEqual(min(offsets), self.source['jamb_gap_mm'])
                self.assertGreater(min(offsets), 0)

    def test_wall_reversal_boundary_winding_and_rotation_preserve_physical_placement(self):
        angle = .63;co, si = math.cos(angle), math.sin(angle)
        def rotate(point):
            return [123.+co*point[0]-si*point[1], -456.+si*point[0]+co*point[1]]
        for side in ('north', 'south'):
            expected, = self.compile(two_area_plan(side))['interface']['signs']
            for reverse_wall, reverse_boundaries in ((True, False), (False, True), (True, True)):
                plan = two_area_plan(side)
                if reverse_wall:
                    wall = next(w for w in plan['walls'] if w['id'] == 'Shared')
                    wall['start'], wall['end'] = wall['end'], wall['start']
                    for area in plan['areas']:
                        next(e for e in area['boundary'] if e['wall'] == 'Shared')['direction'] *= -1
                    for opening in plan['openings']:
                        lo, hi = opening['interval'];opening['interval'] = [1-hi, 1-lo]
                if reverse_boundaries:
                    for area in plan['areas']:
                        area['boundary'] = [{**edge, 'direction': -edge['direction']}
                                            for edge in reversed(area['boundary'])]
                plan['vertices'] = {name: rotate(point) for name, point in plan['vertices'].items()}
                result = self.compile(plan);actual, = result['interface']['signs']
                with self.subTest(side=side, reversed_wall=reverse_wall, reversed_boundary=reverse_boundaries):
                    for key in ('center_mm', 'right_jamb_mm'):
                        self.assertLess(math.dist(actual[key][:2], rotate(expected[key][:2])), 1e-8)
                    for key in ('right_vector', 'front_normal'):
                        x, y, z = expected[key]
                        self.assertLess(math.dist(actual[key], [co*x-si*y, si*x+co*y, z]), 1e-9)
                    for operation in result['operations']:
                        if operation['shape']['kind'] == 'polygon_prism':
                            self.assertGreater(floor.signed_area(operation['shape']['points']), 0)

    def test_plate_and_lettering_are_portable_native_geometry_with_no_source_mutation(self):
        plan = two_area_plan();source = copy.deepcopy(self.source);before = copy.deepcopy(plan)
        result = self.compile(plan);record, = result['interface']['signs']
        self.assertEqual(self.source, source);self.assertEqual(plan, before)
        self.assertEqual(result['components'], [{'id': 'RoomSigns', 'grounded': True}])
        self.assertEqual([b['role'] for b in result['bodies']], ['room_sign_plate', 'room_sign_ink'])
        self.assertNotIn('geometry_semantics', result['bodies'][0])
        self.assertEqual(result['bodies'][1]['geometry_semantics'], 'disconnected_surface_annotation')
        self.assertFalse(result['interface']['signage_qualified'])
        self.assertEqual(record['wall_material_clearance']['height_envelope_local_mm'], [1468., 1632.])
        ink, = [op for op in result['operations'] if op['body'] == record['body_ids'][1]]
        self.assertEqual(ink['action'], 'create')
        self.assertEqual(ink['shape']['kind'], 'cylinder_bundle')
        self.assertEqual(ink['shape']['combine'], 'union')
        bundle = ink['shape'];cylinders = bundle['cylinders'];frame = bundle['frame']
        self.assertEqual(bundle['coordinate_frame'], 'glyph_local_mm')
        self.assertEqual(frame['x'], record['right_vector'])
        self.assertEqual(frame['y'], [0., 0., 1.])
        self.assertEqual(frame['z'], record['front_normal'])
        self.assertEqual(record['letter_case'], 'uppercase')
        self.assertEqual(''.join(record['lines']).replace(' ', ''), record['text'].upper().replace(' ', ''))
        expected_origin = [a+b*(self.source['thickness_mm']+self.source['line_width_mm']/2)
                           for a, b in zip(record['center_mm'], record['front_normal'])]
        self.assertLess(math.dist(frame['origin'], expected_origin), 1e-9)
        self.assertEqual(len(cylinders), record['stroke_count'])
        self.assertGreater(len(cylinders), len(record['text']))
        cursor = 0
        for span in bundle['glyph_spans']:
            self.assertEqual(span['start'], cursor)
            self.assertGreater(span['count'], 0)
            for shape in cylinders[span['start']:span['start']+span['count']]:
                self.assertEqual(set(shape), {'origin', 'radius', 'height', 'axis'})
                self.assertGreater(shape['height'], 0);self.assertGreater(shape['radius'], 0)
                self.assertAlmostEqual(sum(v*v for v in shape['axis']), 1.)
                for fraction in (0., 1.):
                    local = [offset+v+fraction*shape['height']*axis for offset, v, axis in
                             zip(span['offset_mm'], shape['origin'], shape['axis'])]
                    point = [frame['origin'][i]+sum(frame[key][i]*local[j]
                             for j, key in enumerate(('x', 'y', 'z'))) for i in range(3)]
                    delta = [a-b for a, b in zip(point, record['center_mm'])]
                    horizontal = sum(a*b for a, b in zip(delta, record['right_vector']))
                    self.assertLess(abs(horizontal)+shape['radius'], record['width_mm']/2)
                    self.assertLess(abs(delta[2])+shape['radius'], record['height_mm']/2)
                    depth = sum(a*b for a, b in zip(delta, record['front_normal']))
                    self.assertAlmostEqual(depth, self.source['thickness_mm']+shape['radius'])
            cursor += span['count']
        self.assertEqual(cursor, len(cylinders))

    def test_wrapped_trailing_spaces_cannot_shift_native_lettering_between_python_versions(self):
        source = {**sign_source(), 'text_height_mm': 14., 'text_margin_mm': 8., 'height_mm': 110.}
        with patch.object(signs.textwrap, 'wrap', return_value=['0.008 ', 'RLT-ZE', 'NTRALE']):
            lines, height = signs.text_lines('0.008 RLT-Zentrale', 82.826499, source)
        self.assertEqual(lines, ['0.008', 'RLT-ZE', 'NTRALE'])
        self.assertEqual(height, 14.)
        expected = self.compile()
        wrap = signs.textwrap.wrap
        def trailing_space_wrap(*args, **kwargs):
            return [line+' ' for line in wrap(*args, **kwargs)]
        with patch.object(signs.textwrap, 'wrap', side_effect=trailing_space_wrap):
            actual = self.compile()
        self.assertEqual(actual, expected)

    def footprint(self, record, *, depth=None):
        # Reconstruct the actual plate/paint envelope independently of the fit
        # helper. Cylinder centres sit at plate thickness+radius, so the outer
        # paint face reaches thickness+the full line width.
        depth = self.source['thickness_mm']+self.source['line_width_mm'] if depth is None else depth
        return [[record['center_mm'][i]+record['right_vector'][i]*along+
                 record['front_normal'][i]*across for i in (0, 1)]
                for along, across in [(-record['width_mm']/2, 0), (record['width_mm']/2, 0),
                                      (record['width_mm']/2, depth), (-record['width_mm']/2, depth)]]

    def test_perpendicular_material_shrinks_the_plate_despite_a_clear_door_wall_run(self):
        plan = two_area_plan()
        plan['vertices'].update(ObstacleA=[2850., -1000.], ObstacleB=[2850., 500.])
        plan['walls'].append({'id': 'Obstacle', 'kind': 'wall',
                             'start': 'ObstacleA', 'end': 'ObstacleB'})
        record, = self.compile(plan)['interface']['signs']
        # The real wall's near face is x2750, not its x2850 centreline. The
        # original x2560..2960 plate crosses it; a 2mm gap permits at most188mm.
        polygon = self.footprint(record)
        self.assertAlmostEqual(min(p[0] for p in polygon), 2560.)
        self.assertLessEqual(max(p[0] for p in polygon), 2748.+1e-7)
        self.assertGreater(record['width_mm'], 187.999)
        self.assertLessEqual(record['width_mm'], 188.+1e-7)
        self.assertGreaterEqual(2750.-max(p[0] for p in polygon), self.source['wall_gap_mm']-1e-7)
        self.assertEqual(record['placement'], 'right_jamb_wall')
        self.assertGreater(record['width_reduction_mm'], 211.999)

    def test_oblique_material_fit_includes_the_outer_ink_face_not_only_the_plate(self):
        plan = two_area_plan();root2 = math.sqrt(2.)
        near_face = 3066.+2*root2
        centerline = near_face+100*root2
        center_y = 3000.-centerline
        plan['vertices'].update(ObliqueA=[2500., center_y-500.],
                                ObliqueB=[3500., center_y+500.])
        plan['walls'].append({'id': 'Oblique', 'kind': 'wall',
                             'start': 'ObliqueA', 'end': 'ObliqueB'})
        # At the old400mm width the plate alone has exactly2mm separation,
        # while its 2mm paint extension reduces that gap to0.5858mm.
        self.assertAlmostEqual((near_face-(2960.+106.))/root2, 2.)
        self.assertLess((near_face-(2960.+108.))/root2, self.source['wall_gap_mm'])
        record, = self.compile(plan)['interface']['signs']
        polygon = self.footprint(record)
        independent_gap = (near_face-max(point[0]-point[1] for point in polygon))/root2
        self.assertGreaterEqual(independent_gap, self.source['wall_gap_mm']-1e-7)
        self.assertGreater(record['width_mm'], 397.999)
        self.assertLessEqual(record['width_mm'], 398.+1e-7)
        self.assertEqual(record['wall_material_clearance']['footprint_depth_mm'], 6.)

    def test_aperture_void_is_used_only_when_it_covers_the_full_local_height(self):
        plan = two_area_plan()
        def contains_material(bottom, top):
            pieces = signs.wall_material(plan, self.p, 'OG3', bottom, top)
            return any(floor.point_membership([2000., 0.], item['polygon_mm']) >= 0
                       for item in pieces if item['source_wall_id'] == 'Shared')
        self.assertFalse(contains_material(1000., 1100.))
        self.assertTrue(contains_material(2100., 2200.))
        plan['openings'][0]['kind'] = 'window'
        self.assertFalse(contains_material(1500., 1600.))
        self.assertTrue(contains_material(1390., 1500.))
        plan['openings'][0]['kind'] = 'unknown'
        self.assertTrue(contains_material(1500., 1600.))

    def test_edge_crossing_is_material_overlap_even_without_an_inside_vertex(self):
        first = [[0., 0.], [10., 0.], [10., 2.], [0., 2.]]
        wall = [[4., -5.], [6., -5.], [6., 5.], [4., 5.]]
        self.assertTrue(all(floor.point_membership(p, wall) == -1 for p in first))
        self.assertTrue(all(floor.point_membership(p, first) == -1 for p in wall))
        result = signs.polygon_gap(first, wall)
        self.assertEqual(result['gap_mm'], 0.)
        self.assertAlmostEqual(result['overlap_area_mm2'], 4.)
        self.assertGreaterEqual(floor.point_membership(result['first_point_mm'], first), 0)
        self.assertGreaterEqual(floor.point_membership(result['second_point_mm'], wall), 0)

    def test_actual_open_door_leaf_moves_the_right_gap_and_keeps_a_clear_hall_view(self):
        plan = two_area_plan();source = copy.deepcopy(self.source);source['jamb_gap_mm'] = 10.
        body = 'OG3__DoorLeaf_Door'
        geometry = {'bodies': [{'id': body, 'role': 'concept_open_wood_room_door'}],
                    'operations': [{'id': 'Leaf_Prism', 'body': body, 'action': 'create',
                        'shape': {'kind': 'polygon_prism', 'plane': 'XY',
                                  'points': [[2480., 0.], [2520., 0.], [2520., -1000.], [2480., -1000.]],
                                  'offset': self.levels[0]['z_mm'], 'depth': 2150.}}]}
        unchecked, = self.compile(plan, source=source)['interface']['signs']
        self.assertLess(min(p[0] for p in self.footprint(unchecked)), 2520.)
        checked, = self.compile(plan, source=source, door_geometry=geometry)['interface']['signs']
        self.assertTrue(checked['open_leaf_material_checked'])
        self.assertGreater(checked['effective_jamb_gap_mm'], source['jamb_gap_mm'])
        # The actual40mm leaf straddles its x2500 hinge. At label height it
        # overlaps the old10mm-gap plate; the new first edge needs x2522+.
        self.assertGreaterEqual(min(p[0] for p in self.footprint(checked))-2520.,
                                source['wall_gap_mm']-1e-7)
        view = checked['source_viewpoint']
        self.assertEqual(floor.point_membership(view['eye_mm'][:2],
            floor.outline(plan, 'Corridor')), 1)
        self.assertGreater(view['front_cosine'], .1)
        eye, target = view['eye_mm'], view['target_mm']
        low, high = 0., 1.
        for axis, limits in enumerate(((2480., 2520.), (-1000., 0.))):
            delta = target[axis]-eye[axis]
            if delta == 0:
                if not limits[0] <= eye[axis] <= limits[1]:
                    low, high = 1., 0.;break
            else:
                first, last = sorted((bound-eye[axis])/delta for bound in limits)
                low, high = max(low, first), min(high, last)
        self.assertGreater(low, high, 'The reported hall centre ray intersects the actual leaf')
        missing = copy.deepcopy(geometry);missing['operations'] = []
        with self.assertRaises(ValueError):
            self.compile(plan, source=source, door_geometry=missing)

    def test_unknown_names_internal_doors_and_exterior_doors_do_not_invent_signs(self):
        self.assertEqual(self.compile(names={})['interface']['signs'], [])
        for mode in ('internal', 'exterior', 'window', 'ambiguous'):
            plan = two_area_plan();names = copy.deepcopy(self.names)
            if mode == 'internal':
                corridor = next(a for a in plan['areas'] if a['id'] == 'Corridor');corridor['kind'] = 'room'
                names['OG3', 'Corridor'] = {'text': '3.004 Büro', 'basis': 'owner_confirmed'}
            elif mode == 'exterior':
                plan['areas'] = [a for a in plan['areas'] if a['id'] == 'Room']
            elif mode == 'window':
                plan['openings'][0]['kind'] = 'window'
            else:
                plan['areas'].append({'id': 'Third', 'kind': 'room', 'label': 'Unknown',
                                      'boundary': copy.deepcopy(plan['areas'][0]['boundary'])})
            with self.subTest(mode=mode):
                result = self.compile(plan, names=names)
                self.assertEqual(result['interface']['signs'], [])
                self.assertEqual({r['area_id'] for r in result['interface']['unplaced_rooms']},
                                 {identity[1] for identity in names})

    def test_omitted_wall_reports_the_known_room_without_a_floating_plaque(self):
        result = self.compile(omitted=['OG3__Wall_Shared'])
        self.assertEqual(result['operations'], []);self.assertEqual(result['bodies'], [])
        entry, = result['interface']['unplaced_rooms']
        self.assertEqual((entry['level_id'], entry['area_id']), ('OG3', 'Room'))
        self.assertEqual(entry['reason'], 'no_retained_direct_corridor_door')

    def test_insufficient_right_wall_never_falls_back_to_the_left(self):
        for side, interval in [('north', [.86, .96]), ('south', [.04, .14])]:
            plan = two_area_plan(side);plan['openings'][0]['interval'] = interval
            # There is no retained right recess face; left-side space remains.
            return_id = 'SouthRight' if side == 'north' else 'NorthLeft'
            next(w for w in plan['walls'] if w['id'] == return_id)['kind'] = 'open'
            with self.subTest(side=side), self.assertRaisesRegex(ValueError, 'right-jamb'):
                self.compile(plan)

    def test_only_the_immediate_hall_facing_right_recess_can_receive_the_plate(self):
        for side, interval, host, center, right, normal in [
                ('north', [.86, .96], 'SouthRight', [4898., -360., 14300.], [0., -1., 0.], [-1., 0., 0.]),
                ('south', [.04, .14], 'NorthLeft', [102., 360., 14300.], [0., 1., 0.], [1., 0., 0.])]:
            for reversed_host, reversed_boundary in ((False, False), (True, False), (False, True)):
                plan = two_area_plan(side);plan['openings'][0]['interval'] = interval
                if reversed_host:
                    wall = next(w for w in plan['walls'] if w['id'] == host)
                    wall['start'], wall['end'] = wall['end'], wall['start']
                    for area in plan['areas']:
                        for edge in area['boundary']:
                            if edge['wall'] == host:edge['direction'] *= -1
                if reversed_boundary:
                    for area in plan['areas']:
                        area['boundary'] = [{**edge, 'direction': -edge['direction']}
                                            for edge in reversed(area['boundary'])]
                record, = self.compile(plan)['interface']['signs']
                with self.subTest(side=side, reversed_host=reversed_host, reversed_boundary=reversed_boundary):
                    self.assertEqual(record['placement'], 'immediate_right_recess_wall')
                    self.assertLess(math.dist(record['center_mm'], center), 1e-8)
                    self.assertEqual(record['right_vector'], right)
                    self.assertEqual(record['front_normal'], normal)
                    self.assertEqual(record['support_wall_body_ids'], ['OG3__Wall_'+host])
                plan['openings'].append({'id': 'ReturnWindow', 'wall': host,
                                         'kind': 'window', 'interval': [.6, .8]})
                with self.assertRaisesRegex(ValueError, 'right-jamb'):
                    self.compile(plan)

    def test_next_aperture_limits_the_plate_even_if_the_wall_continues(self):
        plan = two_area_plan()
        plan['openings'].append({'id': 'Window', 'kind': 'window', 'wall': 'Shared', 'interval': [.58, .68]})
        record, = self.compile(plan)['interface']['signs']
        self.assertAlmostEqual(record['width_mm'], 330.)
        self.assertAlmostEqual(record['center_mm'][0]+record['width_mm']/2, 2890.)
        for interval in ([.52, .68], [.48, .6]):
            plan['openings'][-1]['interval'] = interval
            with self.subTest(next_aperture=interval), self.assertRaisesRegex(ValueError, 'right-jamb'):
                self.compile(plan)

    def test_collinear_retained_edges_continue_but_do_not_bridge_an_aperture_or_missing_wall(self):
        plan = two_area_plan();plan['vertices']['Split'] = [2600., 0.]
        next(w for w in plan['walls'] if w['id'] == 'Shared')['end'] = 'Split'
        plan['walls'].append({'id': 'SharedTail', 'start': 'Split', 'end': 'B', 'kind': 'wall'})
        plan['openings'][0]['interval'] = [1500./2600, 2500./2600]
        for area in plan['areas']:
            boundary = []
            for edge in area['boundary']:
                if edge['wall'] != 'Shared':
                    boundary.append(edge)
                elif edge['direction'] == 1:
                    boundary.extend([edge, {'wall': 'SharedTail', 'direction': 1}])
                else:
                    boundary.extend([{'wall': 'SharedTail', 'direction': -1}, edge])
            area['boundary'] = boundary
        record, = self.compile(plan)['interface']['signs']
        self.assertAlmostEqual(record['width_mm'], 400.)
        self.assertAlmostEqual(record['center_mm'][0], 2760.)
        self.assertEqual(record['support_wall_body_ids'], ['OG3__Wall_Shared', 'OG3__Wall_SharedTail'])
        with self.assertRaisesRegex(ValueError, 'right-jamb'):
            self.compile(plan, omitted=['OG3__Wall_SharedTail'])
        plan['openings'].append({'id': 'Window', 'kind': 'window', 'wall': 'SharedTail',
                                 'interval': [.125, .25]})
        record, = self.compile(plan)['interface']['signs']
        self.assertAlmostEqual(record['width_mm'], 330.)
        self.assertAlmostEqual(record['center_mm'][0]+record['width_mm']/2, 2890.)

    def test_missing_wall_reference_fails_as_a_declared_input_error(self):
        plan = two_area_plan();plan['walls'] = [wall for wall in plan['walls'] if wall['id'] != 'Shared']
        with self.assertRaises(ValueError):
            self.compile(plan)

    def test_invalid_appearance_left_side_and_unrenderable_text_are_rejected(self):
        for key, value in [('side', 'left_from_corridor'), ('jamb_gap_mm', True),
                           ('letter_case', 'lowercase'),
                           ('wall_gap_mm', math.nan), ('width_mm', -1),
                           ('minimum_width_mm', 500.), ('background_color', 'white'),
                           ('ink_color', '#12345Z'), ('extra', 'unsupported')]:
            source = copy.deepcopy(self.source);source[key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                self.compile(source=source)
        for text in ('3.003 🧪', 'W'*2000):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                self.compile(names={('OG3', 'Room'): {'text': text, 'basis': 'owner_confirmed'}})


class GlyphBundleContractTests(unittest.TestCase):
    def bundle(self):
        return {'kind': 'cylinder_bundle', 'combine': 'union', 'coordinate_frame': 'glyph_local_mm',
                'cylinders': [{'origin': [0., 0., 0.], 'axis': [1., 0., 0.], 'radius': .5, 'height': 10.},
                              {'origin': [10., 0., 0.], 'axis': [0., 1., 0.], 'radius': .5, 'height': 3.},
                              {'origin': [0., 0., 0.], 'axis': [0., 1., 0.], 'radius': .5, 'height': 8.}],
                'glyph_spans': [{'start': 0, 'count': 2, 'offset_mm': [5., 7., 0.]},
                                {'start': 2, 'count': 1, 'offset_mm': [25., 7., 0.]}],
                'frame': {'origin': [100., 200., 300.], 'x': [0., 1., 0.],
                          'y': [0., 0., 1.], 'z': [1., 0., 0.]}}

    def test_glyph_partition_is_complete_ordered_and_cannot_hide_a_bad_stroke(self):
        signs.validate_bundle(self.bundle())
        mutations = [
            ('uncovered stroke', lambda s: s['glyph_spans'].pop()),
            ('overlapping glyph', lambda s: s['glyph_spans'][1].update(start=1)),
            ('gap in coverage', lambda s: s['glyph_spans'][1].update(start=3)),
            ('out of order', lambda s: s['glyph_spans'].reverse()),
            ('boolean start', lambda s: s['glyph_spans'][0].update(start=False)),
            ('boolean count', lambda s: s['glyph_spans'][0].update(count=True)),
            ('zero count', lambda s: s['glyph_spans'][0].update(count=0)),
            ('offset dimension', lambda s: s['glyph_spans'][0].update(offset_mm=[1., 2.])),
            ('offset nonfinite', lambda s: s['glyph_spans'][0].update(offset_mm=[math.nan, 0., 0.])),
            ('offset out of plane', lambda s: s['glyph_spans'][0].update(offset_mm=[0., 0., 1.])),
            ('foreign partition field', lambda s: s['glyph_spans'][0].update(foreign=True)),
            ('nonfinite stroke', lambda s: s['cylinders'][0].update(height=math.inf)),
            ('nonunit axis', lambda s: s['cylinders'][0].update(axis=[2., 0., 0.])),
            ('stroke out of plane', lambda s: s['cylinders'][0].update(origin=[0., 0., 1.])),
            ('foreign coordinate contract', lambda s: s.update(coordinate_frame='world_mm')),
        ]
        for name, mutate in mutations:
            value = self.bundle();mutate(value)
            with self.subTest(case=name), self.assertRaises(ValueError):
                signs.validate_bundle(value)

    def test_world_frame_is_finite_upright_orthonormal_and_right_handed(self):
        signs.validate_bundle(self.bundle())
        for key, value in [('origin', [math.nan, 0., 0.]), ('x', [True, 0., 0.]),
                           ('x', [0., 2., 0.]), ('y', [0., 1., 0.]),
                           ('z', [-1., 0., 0.]), ('z', [1., 1e-7, 0.])]:
            shape = self.bundle();shape['frame'][key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                signs.validate_bundle(shape)

    def test_solidcraft_uses_per_glyph_unions_then_the_declared_rigid_world_frame(self):
        shape = self.bundle()
        source = {'bodies': [{'id': 'Ink', 'component': 'RoomSigns',
                             'appearance': {'color': '#18242B', 'opacity': 1}}],
                  'operations': [{'id': 'Ink_Strokes', 'body': 'Ink', 'action': 'create', 'shape': shape}]}
        commands = signs.solidcraft_ink_commands(source)
        cylinders = [c for c in commands if c['command'] == 'solid.cylinder']
        unions = [c for c in commands if c['command'] == 'solid.combine']
        self.assertEqual(len(cylinders), 3)
        self.assertEqual(len(unions), 2)  # One two-stroke glyph, then the label.
        self.assertTrue(all(c['params']['operation'] == 'join' for c in unions))
        bodies = {}
        for command in commands:
            name, p = command['command'], command['params']
            if name == 'solid.cylinder':
                bodies[p['body_name']] = [p['base'],
                    [a+p['height']*b for a, b in zip(p['base'], p['axis'])]]
            elif name == 'solid.combine':
                for tool in p['tools']:
                    bodies[p['target']].extend(bodies.pop(tool))
                self.assertFalse(p['keep_tools'])
            elif name == 'solid.move':
                for body in p['bodies']:
                    if 'translate' in p:
                        bodies[body] = [[a+b for a, b in zip(point, p['translate'])] for point in bodies[body]]
                    else:
                        self.assertTrue(p['angle'].endswith(' deg'))
                        angle = math.radians(float(p['angle'].split()[0]));axis = p['axis']
                        rotated = []
                        for point in bodies[body]:
                            cross = [axis[1]*point[2]-axis[2]*point[1],
                                     axis[2]*point[0]-axis[0]*point[2],
                                     axis[0]*point[1]-axis[1]*point[0]]
                            dot = sum(a*b for a, b in zip(axis, point))
                            rotated.append([v*math.cos(angle)+c*math.sin(angle)+n*dot*(1-math.cos(angle))
                                            for v, c, n in zip(point, cross, axis)])
                        bodies[body] = rotated
            else:
                self.assertIn(name, {'component.move_bodies', 'appearance.assign'})
        self.assertEqual(set(bodies), {'Ink'})
        expected = [[100., 205., 307.], [100., 215., 307.],
                    [100., 215., 307.], [100., 215., 310.],
                    [100., 225., 307.], [100., 225., 315.]]
        for actual, target in zip(bodies['Ink'], expected):
            self.assertLess(math.dist(actual, target), 1e-9)


class DefaultRoomSignAcceptanceTests(unittest.TestCase):
    def test_all_eighty_known_corridor_doors_keep_fitted_signs_without_silent_loss(self):
        spec = building.load();p = building.parameters(spec)
        data = building.interfaces(spec, p);view = data['room_signs']
        plans = {level['id']: building.level_plan(spec, level['id']) for level in spec['levels']}
        names = signs.labels.labels(spec, plans)
        omitted = set(data.get('furnishings', {}).get('omitted_walls', []))
        omitted.update(data.get('exterior', {}).get('omitted_body_ids', []))
        expected = {}
        for level_id, plan in plans.items():
            for opening in plan['openings']:
                if opening['kind'] != 'door' or level_id+'__Wall_'+opening['wall'] in omitted:
                    continue
                adjacent = [area for area in plan['areas']
                            if any(edge['wall'] == opening['wall'] for edge in area['boundary'])]
                halls = [area for area in adjacent if area['kind'] == 'corridor']
                rooms = [area for area in adjacent if area['kind'] != 'corridor'
                         and (level_id, area['id']) in names]
                if len(adjacent) == 2 and len(halls) == len(rooms) == 1:
                    expected[level_id, opening['id']] = (level_id, rooms[0]['id'])
        self.assertEqual(len(expected), 80)
        actual = {(row['level_id'], row['opening_id']): row for row in view['signs']}
        self.assertEqual(len(view['signs']), 80)
        self.assertEqual(set(actual), set(expected))
        self.assertEqual({key[0] for key in actual}, {level['id'] for level in spec['levels']})
        for key, row in actual.items():
            self.assertEqual(row['text'], names[expected[key]]['text'])
            self.assertGreaterEqual(row['width_mm'], spec['room_signs']['minimum_width_mm'])
            self.assertTrue(row['open_leaf_material_checked'])
            observer = row['source_viewpoint']
            corridor = next(area for area in plans[key[0]]['areas'] if area['id'] == row['corridor_id'])
            polygon = [[v*p['display_scale'] for v in point]
                       for point in floor.outline(plans[key[0]], corridor)]
            self.assertEqual(floor.point_membership(observer['eye_mm'][:2], polygon), 1)
            self.assertGreater(observer['front_cosine'], .1)
            self.assertTrue(row['wall_material_clearance']['passed'])
            self.assertGreaterEqual(row['wall_material_clearance']['minimum_gap_mm'],
                                    spec['room_signs']['wall_gap_mm']-1e-7)
            self.assertEqual(row['wall_material_clearance']['footprint_depth_mm'],
                             spec['room_signs']['thickness_mm']+spec['room_signs']['line_width_mm'])
        # These identities are labelled source areas, including aliases and
        # generated reference footprints; their count is not missing rooms.
        unplaced = {(row['level_id'], row['area_id']) for row in view['unplaced_rooms']}
        self.assertEqual(unplaced, set(names)-set(expected.values()))
        self.assertIs(view['signage_qualified'], False)


class SurfaceAnnotationMeasurementTests(unittest.TestCase):
    def measurement(self, **overrides):
        return {'body': 'Ink', 'valid': True, 'solid_count': 5, 'closed_solids': True,
                'volume_mm3': 12., 'world_center_of_mass_mm': [1., 2., 3.],
                'bbox': {'min': [0., 0., 0.], 'max': [2., 4., 6.]}, **overrides}

    def source(self, **metadata):
        return {'bodies': [{'id': 'Ink', 'role': 'room_sign_ink',
                            'geometry_semantics': 'disconnected_surface_annotation', **metadata}]}

    def test_only_explicit_room_sign_ink_allows_disconnected_closed_solids(self):
        row = self.measurement()
        result = evidence.checked_measurements({'geometry': [row]}, self.source(), backend='freecad')
        self.assertEqual(result, [{'body': 'Ink', 'volume_mm3': 12.,
            'world_center_of_mass_mm': [1., 2., 3.], 'bbox': row['bbox']}])
        for metadata in ({'role': 'ordinary_part'}, {'role': 'room_sign_plate'},
                         {'geometry_semantics': 'ordinary_solid'}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                evidence.checked_measurements({'geometry': [row]}, self.source(**metadata), backend='freecad')
        source = self.source();source['bodies'][0].pop('geometry_semantics')
        with self.assertRaises(ValueError):
            evidence.checked_measurements({'geometry': [row]}, source, backend='freecad')

    def test_annotation_permission_cannot_hide_invalid_or_nonfinite_measurements(self):
        for overrides in ({'valid': False}, {'closed_solids': False}, {'solid_count': 0}, {'solid_count': True},
                          {'solid_count': 2.5}, {'volume_mm3': math.nan},
                          {'volume_mm3': 0}, {'world_center_of_mass_mm': [1., math.inf, 3.]},
                          {'bbox': {'min': [0., 0., 0.], 'max': [2., 0., 6.]}}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                evidence.checked_measurements({'geometry': [self.measurement(**overrides)]},
                                    self.source(), backend='freecad')

    def test_annotation_role_is_matched_by_identity_without_relaxing_other_bodies(self):
        ink = self.measurement();ordinary = self.measurement(body='Wall', solid_count=2)
        source = self.source();source['bodies'].append({'id': 'Wall', 'role': 'wall'})
        for order in ([ink, ordinary], [ordinary, ink]):
            with self.subTest(order=[row['body'] for row in order]), self.assertRaises(ValueError):
                evidence.checked_measurements({'geometry': order}, source, backend='freecad')
        ordinary['solid_count'] = 1
        self.assertEqual(len(evidence.checked_measurements({'geometry': [ordinary, ink]}, source,
                                                 backend='freecad')), 2)
        source['bodies'].append(copy.deepcopy(source['bodies'][0]))
        with self.assertRaises(ValueError):
            evidence.checked_measurements({'geometry': [ordinary, ink]}, source, backend='freecad')


if __name__ == '__main__':
    unittest.main()
