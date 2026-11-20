"""Non-sliding material and close-arm geometry; no motion or dosing claim."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import arm_syringe as model
import joint_hose_routing as routing
import pneumatic_hose as hose
import arm_hose_proximity as proximity
import robot_spec as robot


# Independent regression snapshots from the completed650b source (master0d8d52a).
# The new routing may change, but neither these inputs nor the16 poses may drift.
PRESERVED_INPUTS = {
    'model/robot.json': '978fa3557abcfe549f5c2bd572c761d387310c2983f1d4e60cfd903df621bfdd',
    'model/syringe-pipette.shared.json': '017103cfbee9809631ff29fb7a005a2e2428efb0074afe55e001fde5e9b2ff1b',
    'model/syringe-pipette.schema.json': 'ba5ff7a4da6ea30d80ea5f247f695b7cfdb43691694221e828719f7524c732d0',
    'scripts/syringe_pipette.py': '9628f085e11bd349bce0fc130ce3b24bfe3b20741e018746938d6d7bdb901afd',
    'scripts/build_syringe_pipette.py': '20657c6384a09b3607cdaf6004a322db9a387aa1e04affa424630b2e99c2fd00',
    'scripts/build_syringe_pipette_freecad.py': '71f8471a06a924a2ad8bd16b9e2162878242cb71e2853a9de52d5c3a7eb40c88',
    'tests/test_syringe_pipette.py': 'aaf4a5389f024620039148006247d03cdd5d0d50ee84d3795a67fec307f4375f',
    'docs/syringe-pipette-concept.md': '80d19eacd25026a98098fbd1d4d89275dcf2eee6a4eaecb0c157d32bfabef04e',
    'model/spatial-hose-carrier.shared.json': '6c1a24bcb15d91d620f1a413d86410138f2390bfdb3bd774851574aa4dc21396',
    'model/spatial-hose-carrier.schema.json': '453bf98f4ee7a2fae37147387d45caa4adea737410ac675d663b6e2ffb60d6a0',
    'scripts/spatial_hose_carrier.py': '4ed168ae197949f3fcd9e435a068f564bdf5b2554042a6342138255b8c0855c6',
    'cad/vendor/igus/triflex-r-reference.pdf': '8daf7f369d366c74d9eeb68bdf5fa9268f1fe30aa0d55d94ecacef9470696911',
}
ORIGINAL_STATES = {
    'extended': {'joints_deg': [-20, 65, 35, 0, 80, 0], 'stroke_fraction': .75, 'valve_deg': 0},
    'isolated': {'joints_deg': [-20, 45, 60, 0, 75, 0], 'stroke_fraction': .5, 'valve_deg': 90},
    'pump_advanced': {'joints_deg': [-20, 45, 60, 0, 75, 0], 'stroke_fraction': .05, 'valve_deg': 0},
    'pump_retracted': {'joints_deg': [-20, 45, 60, 0, 75, 0], 'stroke_fraction': .95, 'valve_deg': 0},
    'upright': {'hard_end_reference': True, 'joints_deg': [0, 0, 0, 0, 0, 0], 'stroke_fraction': 0, 'valve_deg': 0},
    'window_back': {'joints_deg': [-20, -30, -10, 0, 75, 0], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_camera_mount': {'joints_deg': [-160, 65, 65, -30, 110, 30], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_carrier_mid': {'joints_deg': [-20, 45, 48, 0, 75, 0], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_route_longest': {'joints_deg': [-20, 45, 60, -30, 110, 30], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_route_shortest': {'joints_deg': [-160.0, 65, -10.0, 30.0, -55.0, -30.0], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_route_shortest_revised': {'joints_deg': [-160, -30, -10, 30, 110, 0], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_wrist_neg': {'joints_deg': [-20, 45, 60, -30, 75, -30], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_wrist_pitch_neg': {'joints_deg': [-20, 45, 60, 0, -110, 0], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_wrist_pitch_pos': {'joints_deg': [-20, 45, 60, 0, 110, 0], 'stroke_fraction': .5, 'valve_deg': 0},
    'window_wrist_pos': {'joints_deg': [-20, 45, 60, 30, 75, 30], 'stroke_fraction': .5, 'valve_deg': 0},
    'working': {'joints_deg': [-20, 45, 60, 0, 75, 0], 'stroke_fraction': .5, 'valve_deg': 0},
}
ORIGINAL_FLAGS = {
    'dimensions_measured', 'dosing_accuracy_verified', 'leakage_verified',
    'actuator_force_verified', 'mount_strength_verified', 'hose_full_range_verified',
    'hardware_execution_implemented',
}
ORIGINAL_OPEN_REQUIREMENTS = {
    'syringe_article', 'tip_article', 'motor_and_spindle_article',
    'clamp_fasteners_and_load', 'tube_article_and_minimum_bend_radius_mm',
    'pressure_and_volume_calibration', 'usable_dose_range_ul', 'permitted_dose_error_ul',
    'permitted_leak_rate_ul_s', 'position_feedback_and_endstop_articles',
    'drive_nut_retention_method', 'socket_ferrules_seals_and_tolerances',
    'hose_clamps_and_strain_relief', 'tip_insertion_and_retention_forces',
}


def geometric_segment_length(segment):
    """Independent length from endpoints/circle geometry, not the reported sum."""
    if segment['kind'] == 'line':
        return math.dist(segment['start_mm'], segment['end_mm'])
    if segment['kind'] != 'arc':
        raise AssertionError('Unknown physical curve segment: '+repr(segment['kind']))
    center = segment['center_mm']
    vectors = [[point[i]-center[i] for i in range(3)]
               for point in (segment['start_mm'], segment['through_mm'], segment['end_mm'])]
    radius = math.sqrt(sum(value*value for value in vectors[0]))
    axis = segment['axis']
    if abs(sum(value*value for value in axis)-1) > 1e-8:
        raise AssertionError('Circular segment axis is not unit length')
    for vector in vectors:
        if abs(math.sqrt(sum(value*value for value in vector))-radius) > 1e-7:
            raise AssertionError('Arc witness is not on its circle')
        if abs(sum(a*b for a, b in zip(vector, axis))) > 1e-7:
            raise AssertionError('Arc witness is outside its plane')
    first = vectors[0]
    def angle(vector):
        cross = [first[1]*vector[2]-first[2]*vector[1],
                 first[2]*vector[0]-first[0]*vector[2],
                 first[0]*vector[1]-first[1]*vector[0]]
        return math.atan2(sum(a*b for a, b in zip(axis, cross)),
                          sum(a*b for a, b in zip(first, vector))) % (2*math.pi)
    sweep = angle(vectors[2])
    if sweep < 1e-12 and math.dist(segment['start_mm'], segment['end_mm']) < 1e-8:
        sweep = 2*math.pi
    if angle(vectors[1]) > sweep+1e-8:
        raise AssertionError('Through-point is outside the directed circular arc')
    if abs(segment['radius_mm']-radius) > 1e-7 or abs(segment['sweep_rad']-sweep) > 1e-8:
        raise AssertionError('Reported circular quantities disagree with actual witnesses')
    return radius*sweep


class CloseArmHosePreservationTests(unittest.TestCase):
    def test_original_sixteen_complete_pose_dictionaries_remain_unchanged(self):
        source = json.loads(model.SOURCE.read_text())
        self.assertTrue(set(ORIGINAL_STATES).issubset(source['states']))
        actual = {name: source['states'][name] for name in ORIGINAL_STATES}
        # Canonical JSON also detects changed numeric types and added pose fields.
        self.assertEqual(json.dumps(actual, sort_keys=True), json.dumps(ORIGINAL_STATES, sort_keys=True))

    def test_robot_sp01_and_unused_carrier_library_remain_byte_identical(self):
        source = json.loads(model.SOURCE.read_text())
        for name, expected in PRESERVED_INPUTS.items():
            with self.subTest(input=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected)
        self.assertEqual(source['robot']['source_sha256'], PRESERVED_INPUTS['model/robot.json'])
        self.assertEqual(source['syringe_library']['source_sha256'], PRESERVED_INPUTS['model/syringe-pipette.shared.json'])

    def test_existing_unqualified_flags_and_unknown_hardware_requirements_stay_open(self):
        source = json.loads(model.SOURCE.read_text())
        self.assertTrue(ORIGINAL_FLAGS.issubset(source['qualification']))
        self.assertTrue(all(value is False for value in source['qualification'].values()))
        self.assertTrue(ORIGINAL_OPEN_REQUIREMENTS.issubset(source['open_requirements']))
        self.assertTrue(all(value is None for value in source['open_requirements'].values()))


class FixedMaterialValidationTests(unittest.TestCase):
    @staticmethod
    def straight_fixture(left=30., right=30.):
        """A literal straight tube: two sockets, two sections and one true clip."""
        definitions = [('pump_inserted', 'inserted', 6.),
                       ('pump_strain', 'socket_strain_relief', 10.),
                       ('pump_lead', 'connector_straight_lead', 10.),
                       ('left', 'bare_span', left), ('clip', 'clip_straight', 10.),
                       ('right', 'bare_span', right),
                       ('tip_lead', 'connector_straight_lead', 10.),
                       ('tip_strain', 'socket_strain_relief', 10.),
                       ('tip_inserted', 'inserted', 6.)]
        segments, parts, offset = [], [], 0.
        for name, kind, length in definitions:
            segments.append({'kind': 'line', 'start_mm': [offset, 0., 0.],
                             'end_mm': [offset+length, 0., 0.], 'length_mm': length})
            parts.append({'id': name, 'kind': kind, 'length_mm': length,
                          'segment_start_index': len(segments)-1, 'segment_count': 1})
            offset += length
        station = 26+left+5
        path = {'format': 'solidcraftbot.static-hose-centerline/1', 'segments': segments,
                'length_mm': offset, 'min_bend_radius_mm': None,
                'requested_bend_radius_mm': 12., 'qualified': False,
                'controls_mm': [[0., 0., 0.], [offset, 0., 0.]],
                'sample_points_mm': [[0., 0., 0.], [offset, 0., 0.]],
                'routing_format': routing.FORMAT,
                'clip_material_stations_mm': {'clip': station},
                'section_records': [
                    {'id': 'left', 'kind': 'fixed_link', 'link': 'L2_UpperArm',
                     'from': 'pump', 'to': 'clip', 'target_length_mm': left,
                     'actual_length_mm': left, 'segment_start_index': 3, 'segment_count': 1},
                    {'id': 'right', 'kind': 'joint_loop', 'joint': 'J3_Elbow',
                     'parent_link': 'L2_UpperArm', 'from': 'clip', 'to': 'tip',
                     'target_length_mm': right, 'actual_length_mm': right,
                     'segment_start_index': 5, 'segment_count': 1}],
                'length_accounting': {'inserted_mm': 12., 'socket_strain_relief_mm': 20.,
                    'connector_straight_leads_mm': 20., 'clip_supported_mm': 10.,
                    'carrier_supported_mm': 0., 'free_bare_spans_mm': left+right,
                    'external_guide_straights_included_in_free_mm': 0.,
                    'total_mm': offset, 'sum_error_mm': 0., 'parts': parts}}
        design = {'section_lengths_mm': {'left': left, 'right': right},
                  'clip_material_stations_mm': {'clip': station}, 'hose_length_mm': offset}
        parameters = {'hoseBendRadius': 12., 'hoseClipLength': 10., 'hoseLength': offset,
                      'hoseOuterRadius': .9}
        return path, parameters, design

    def test_each_clamp_interval_and_material_station_is_independent_of_the_total_cut(self):
        path, parameters, design = self.straight_fixture()
        check = routing.validate_material_path(path, parameters, design)
        self.assertTrue(check['passed'])
        self.assertEqual(check['section_lengths_mm'], {'left': 30., 'right': 30.})
        self.assertEqual(check['clip_material_stations_mm'], {'clip': 61.})
        self.assertEqual(check['total_length_mm'], 122.)
        self.assertEqual(math.fsum(geometric_segment_length(s) for s in path['segments']), 122.)
        migrated, _, _ = self.straight_fixture(left=32., right=28.)
        self.assertEqual(migrated['length_mm'], path['length_mm'])
        self.assertTrue(routing.validate_material_path(migrated, parameters)['passed'])
        with self.assertRaises(ValueError):
            routing.validate_material_path(migrated, parameters, design)

    def test_false_segment_lengths_cannot_trade_material_between_clips(self):
        path, parameters, _ = self.straight_fixture()
        # Physical geometry stays122mm, but the first section claims32 instead
        # of30 and the second28 instead of30; all aggregate metadata balances.
        for index, value in ((3, 32.), (5, 28.)):
            path['segments'][index]['length_mm'] = value
            path['length_accounting']['parts'][index]['length_mm'] = value
        path['section_records'][0].update(target_length_mm=32., actual_length_mm=32.)
        path['section_records'][1].update(target_length_mm=28., actual_length_mm=28.)
        path['clip_material_stations_mm']['clip'] += 2
        self.assertEqual(math.fsum(s['length_mm'] for s in path['segments']), 122.)
        with self.assertRaises(ValueError):
            routing.validate_material_path(path, parameters)

    def test_material_stations_follow_geometry_not_reordered_bookkeeping(self):
        path, parameters, _ = self.straight_fixture()
        parts = path['length_accounting']['parts']
        path['length_accounting']['parts'] = [parts[4]]+parts[:4]+parts[5:]
        path['clip_material_stations_mm']['clip'] = 5.
        with self.assertRaises(ValueError):
            routing.validate_material_path(path, parameters)

    def test_every_physical_section_requires_one_matching_record_and_range(self):
        path, parameters, design = self.straight_fixture()
        for change in ('missing', 'duplicate', 'wrong_range'):
            changed = copy.deepcopy(path)
            if change == 'missing':
                changed['section_records'].pop()
            elif change == 'duplicate':
                changed['section_records'][1] = copy.deepcopy(changed['section_records'][0])
            else:
                changed['section_records'][0]['segment_start_index'] = 5
            with self.subTest(change=change), self.assertRaises(ValueError):
                routing.validate_material_path(changed, parameters, design)

    def test_achieved_arc_radius_cannot_be_lowered_or_promoted_by_metadata(self):
        def fixture(radius):
            path = hose.centerline([[0, 0, 0], [40, 0, 0], [40, 40, 0]], radius)
            length = path['length_mm'];count = len(path['segments'])
            path.update(clip_material_stations_mm={}, section_records=[
                {'id': 'corner', 'kind': 'joint_loop', 'target_length_mm': length,
                 'actual_length_mm': length, 'segment_start_index': 0, 'segment_count': count}])
            path['length_accounting'] = {'inserted_mm': 0., 'socket_strain_relief_mm': 0.,
                'connector_straight_leads_mm': 0., 'clip_supported_mm': 0.,
                'carrier_supported_mm': 0., 'free_bare_spans_mm': length,
                'external_guide_straights_included_in_free_mm': 0., 'total_mm': length,
                'sum_error_mm': 0., 'parts': [{'id': 'corner', 'kind': 'bare_span',
                    'length_mm': length, 'segment_start_index': 0, 'segment_count': count}]}
            return path
        parameters = {'hoseBendRadius': 12., 'hoseClipLength': 10.}
        valid = fixture(12.)
        self.assertAlmostEqual(math.fsum(geometric_segment_length(s) for s in valid['segments']),
                               56+6*math.pi)
        self.assertTrue(routing.validate_material_path(valid, parameters)['passed'])
        for hide in (False, True):
            invalid = fixture(11.5)
            if hide:
                invalid['min_bend_radius_mm'] = 12.
                for segment in invalid['segments']:
                    if segment['kind'] == 'arc':segment['radius_mm'] = 12.
            with self.subTest(hidden_radius=hide), self.assertRaises(ValueError):
                routing.validate_material_path(invalid, parameters)


class ActualHostProximityTests(unittest.TestCase):
    @staticmethod
    def witnesses(operations, step=1.):
        expanded = {'links': [{'id': 'Link', 'recipe': operations}]}
        own = {'components': [], 'bodies': [], 'operations': []}
        with patch.object(proximity.robot, 'expanded', return_value=expanded):
            result = proximity.material_witnesses({}, own, {}, {}, ['Host'], step_mm=step)
        return result

    @staticmethod
    def inspect(path, witnesses, limit):
        path = copy.deepcopy(path)
        path['section_records'] = [{'id': 'run', 'segment_start_index': 0,
                                   'segment_count': len(path['segments'])}]
        spec = {'hose_routing': {'sections': [{'id': 'run', 'kind': 'fixed_link',
            'host_bodies': ['Host'], 'max_offset_mm': limit}]}}
        return proximity.bounds(path, spec, {}, {'Link': robot.identity()}, {},
            {'arm': {'joints': []}, 'material_witnesses': witnesses}, sample_step_mm=2.)

    def test_host_witnesses_are_in_actual_csg_material_not_the_hollow_bbox(self):
        operations = [
            {'action': 'create', 'body': 'Host', 'primitive': {
                'kind': 'box', 'origin': [0, 0, 0], 'size': [10, 10, 10]}},
            {'action': 'cut', 'body': 'Host', 'primitive': {
                'kind': 'box', 'origin': [1, 1, 1], 'size': [8, 8, 8]}}]
        witnesses = self.witnesses(operations)
        self.assertTrue(witnesses['Host']['points_mm'])
        for point in witnesses['Host']['points_mm']:
            self.assertTrue(all(0 <= value <= 10 for value in point))
            self.assertFalse(all(1 <= value <= 9 for value in point))
        # These tube centres lie INSIDE the host's enclosing box, but in its
        # four-millimetre-distant void. An AABB distance would falsely be zero.
        distant = hose.centerline([[5, 5, 3], [5, 5, 7]], 12)
        rejected = self.inspect(distant, witnesses, 1.)
        self.assertFalse(rejected['passed'])
        self.assertGreater(rejected['sections']['run']['maximum_host_distance_upper_bound_mm'], 4.)
        near = hose.centerline([[-1, 5, 3], [-1, 5, 7]], 12)
        self.assertTrue(self.inspect(near, witnesses, 3.)['passed'])

    def test_an_off_arm_bulge_is_rejected_despite_near_endpoints(self):
        witnesses = self.witnesses([{'action': 'create', 'body': 'Host', 'primitive': {
            'kind': 'box', 'origin': [0, -2, -2], 'size': [2, 4, 64]}}], step=2.)
        path = hose.centerline([[-1, 0, 0], [-50, 0, 0], [-50, 0, 60], [-1, 0, 60]], 12)
        self.assertEqual(path['segments'][0]['start_mm'], [-1., 0., 0.])
        self.assertEqual(path['segments'][-1]['end_mm'], [-1., 0., 60.])
        result = self.inspect(path, witnesses, 3.)
        section = result['sections']['run']
        self.assertFalse(result['passed'])
        self.assertGreater(section['maximum_host_distance_upper_bound_mm'], 50.)
        self.assertEqual(section['witness']['host_body'], 'Host')
        self.assertLessEqual(section['maximum_arc_interval_mm'], 2.)
        self.assertGreater(section['interval_count'], 2)

    def test_a_nearer_unrelated_body_cannot_replace_the_designated_host(self):
        witnesses = self.witnesses([{'action': 'create', 'body': 'Host', 'primitive': {
            'kind': 'box', 'origin': [0, -2, -2], 'size': [2, 4, 64]}}], step=2.)
        witnesses['Camera'] = {'component': 'Link', 'points_mm': [[-50, 0, 10]],
                               'status': 'source_material_witnesses'}
        path = hose.centerline([[-50, 0, 9], [-50, 0, 11]], 12)
        result = self.inspect(path, witnesses, 3.)
        self.assertFalse(result['passed'])
        self.assertEqual(result['sections']['run']['witness']['host_body'], 'Host')

    def test_an_unsupported_vendor_bbox_cannot_be_invented_as_material(self):
        witnesses = self.witnesses([{'action': 'create', 'body': 'Host', 'primitive': {
            'kind': 'vendor_component', 'origin': [0, 0, 0],
            'bbox': {'min': [-1, -1, -1], 'max': [1, 1, 1]}}}])
        self.assertEqual(witnesses['Host']['status'], 'native_shape_required')
        self.assertEqual(witnesses['Host']['points_mm'], [])
        with self.assertRaises(ValueError):
            self.inspect(hose.centerline([[0, 0, 0], [0, 0, 10]], 12), witnesses, 3.)

    def test_later_body_translation_moves_both_positive_material_and_subtracted_void(self):
        delta = [20, -3, 4]
        operations = [
            {'action': 'create', 'body': 'Host', 'primitive': {
                'kind': 'box', 'origin': [0, 0, 0], 'size': [10, 10, 10]}},
            {'action': 'cut', 'body': 'Host', 'primitive': {
                'kind': 'box', 'origin': [1, 1, 1], 'size': [8, 8, 8]}},
            {'action': 'translate', 'targets': ['Host'], 'vector': delta}]
        witnesses = self.witnesses(operations)
        self.assertTrue(witnesses['Host']['points_mm'])
        for point in witnesses['Host']['points_mm']:
            original = [value-shift for value, shift in zip(point, delta)]
            self.assertTrue(all(0 <= value <= 10 for value in original))
            self.assertFalse(all(1 <= value <= 9 for value in original))
        path = hose.centerline([[25, 2, 7], [25, 2, 11]], 12)
        self.assertFalse(self.inspect(path, witnesses, 1.)['passed'])

    def test_midpoint_distance_needs_the_full_interval_lipschitz_margin(self):
        # [0,0,1] is on the face of a tiny host cube x=[0,.1],
        # y=[-.05,.05],z=[.95,1.05]. The midpoint is1mm away, while
        # each endpoint's real host distance is sqrt(1+.95^2)>1.1mm.
        witnesses = {'Host': {'component': 'Link', 'points_mm': [[0, 0, 1]],
                              'status': 'source_material_witnesses'}}
        path = hose.centerline([[-1, 0, 0], [-1, 0, 2]], 12)
        section = self.inspect(path, witnesses, 1.1)['sections']['run']
        self.assertGreater(math.hypot(1, .95), 1.1)
        self.assertEqual(section['interval_count'], 1)
        self.assertEqual(section['maximum_arc_interval_mm'], 2.)
        self.assertEqual(section['witness']['sample_distance_mm'], 1.)
        self.assertEqual(section['maximum_host_distance_upper_bound_mm'], 2.)
        self.assertFalse(section['passed'])


class LocalSupportSelectionTests(unittest.TestCase):
    @staticmethod
    def fixture(*, crossing=False, outer_wall=False):
        if crossing or outer_wall:
            x, z = (5., 2.5) if outer_wall else (12., 0.)
            controls = [[x, -60., z], [x, 60., z], [-60., 60., z],
                        [-60., 0., z], [0., 0., 0.]]
        else:
            controls = [[0., 0., 0.], [40., 0., 0.]]
        path = hose.centerline(controls, 12., sample_step_mm=2.)
        start, end = controls[0], controls[-1]
        directions = []
        for a, b in ((controls[0], controls[1]), (controls[-2], controls[-1])):
            distance = math.dist(a, b)
            directions.append([(b[i]-a[i])/distance for i in range(3)])
        first, last = directions
        parent_start = [v-10*t for v, t in zip(start, first)]
        child_end = [v+10*t for v, t in zip(end, last)]
        evaluated = {
            'parent': {'body_id': 'ParentClip', 'start_mm': parent_start, 'end_mm': start,
                       'center_mm': [(a+b)/2 for a, b in zip(parent_start, start)], 'tangent': first},
            'child': {'body_id': 'ChildClip', 'start_mm': end, 'end_mm': child_end,
                      'center_mm': [(a+b)/2 for a, b in zip(end, child_end)], 'tangent': last}}
        parameters = {'hoseBendRadius': 12., 'hoseOuterRadius': .9,
                      'hoseClipLength': 10., 'clipFreeLead': 5.,
                      'clipHoseGap': .05, 'clipWall': 1.2}
        return path, {'from': 'parent', 'to': 'child'}, evaluated, parameters

    def test_support_and_tangent_continuations_are_checked_without_adding_cut_material(self):
        straight, section, frames, parameters = self.fixture()
        self.assertTrue(routing._support_probe(straight, section, frames, parameters, 2.)['passed'])
        path, section, frames, parameters = self.fixture(crossing=True)
        original = copy.deepcopy(path)
        self.assertTrue(hose.self_clearance_diagnostics(path, .9)['passed'])
        # Earlier x12 vertical material crosses the child continuation x10..15,
        # while the existing loop itself stops at x0 and remains self-clear.
        probe = routing._support_probe(path, section, frames, parameters, 2.)
        self.assertFalse(probe['passed'])
        self.assertIs(probe['screening_probe_only'], True)
        self.assertEqual(path, original)
        self.assertEqual(path['length_mm'], original['length_mm'])
        # It is specifically a continuation crossing, outside the finite clip.
        self.assertTrue(routing._clip_keepouts(path, section, frames, parameters)['passed'])

    def test_outer_clip_wall_needs_more_space_than_tube_to_tube_self_clearance(self):
        straight, section, frames, parameters = self.fixture()
        self.assertTrue(routing._clip_keepouts(straight, section, frames, parameters)['passed'])
        path, section, frames, parameters = self.fixture(outer_wall=True)
        self.assertTrue(hose.self_clearance_diagnostics(path, .9)['passed'])
        self.assertTrue(routing._support_probe(path, section, frames, parameters, 2.)['passed'])
        keepouts = routing._clip_keepouts(path, section, frames, parameters)
        self.assertFalse(keepouts['passed'])
        self.assertAlmostEqual(keepouts['required_radial_clearance_mm'], 3.05)
        child = keepouts['clips']['child']
        self.assertFalse(child['passed'])
        witness = child['witness']
        self.assertGreater(witness['radial_mm'], 2*parameters['hoseOuterRadius'])
        self.assertLess(witness['radial_mm'], keepouts['required_radial_clearance_mm'])
        self.assertLessEqual(abs(witness['axial_mm']), parameters['hoseClipLength']/2)


class PhysicalClipGeometryTests(unittest.TestCase):
    def test_clip_support_variants_move_real_saddles_bores_splits_and_interfaces(self):
        source = model.load()
        for length in (6., 10., 12.):
            parameters = model.parameters(source, {'hoseClipLength': length})
            geometry = model.clip_geometry(source, parameters)
            self.assertEqual(len(geometry['bodies']), 7)
            self.assertEqual(set(geometry['support_interfaces']), set(source['hose_routing']['clips']))
            for station, support in geometry['support_interfaces'].items():
                with self.subTest(length=length, station=station):
                    self.assertEqual(support['physical_support_length_mm'], length)
                    self.assertEqual(support['link'], source['hose_routing']['clips'][station]['link'])
                    self.assertEqual(support['host_body'], source['hose_routing']['clips'][station]['host_body'])
                    self.assertEqual(geometry['mounts'][support['component']]['link'], support['link'])
                    self.assertTrue(all(value is False for value in support['qualification'].values()))
                    operations = [row for row in geometry['operations'] if row['body'] == support['clip_body']]
                    self.assertTrue(operations)
                    cylinders = []
                    for row in operations:
                        shape = row['shape']
                        if shape['kind'] != 'cylinder':continue
                        center = [value+axis*shape['height']/2
                                  for value, axis in zip(shape['origin'], shape['axis'])]
                        if math.dist(center, support['center_mm']) < 1e-8:
                            cylinders.append((row['action'], shape))
                    outer = parameters['hoseOuterRadius']+parameters['clipHoseGap']+parameters['clipWall']
                    bore = parameters['hoseOuterRadius']+parameters['clipHoseGap']
                    saddle = [shape for action, shape in cylinders
                              if action in ('create', 'join') and abs(shape['radius']-outer) < 1e-8]
                    hollow = [shape for action, shape in cylinders
                              if action == 'cut' and abs(shape['radius']-bore) < 1e-8]
                    self.assertEqual(len(saddle), 1)
                    self.assertEqual(len(hollow), 1)
                    self.assertEqual(saddle[0]['height'], length)
                    self.assertAlmostEqual(hollow[0]['height'], length+.2)
                    self.assertAlmostEqual(support['bore_radius_mm']-parameters['hoseOuterRadius'], parameters['clipHoseGap'])
                    self.assertTrue(any(row['action'] == 'cut' and row['shape']['kind'] == 'box'
                        and abs(row['shape']['size'][2]-(length+.2)) < 1e-8
                        and abs(row['shape']['origin'][2]-(support['center_mm'][2]-(length+.2)/2)) < 1e-8
                        for row in operations))

    def test_all_seven_route_supports_match_physical_clip_poses_in_every_original_state(self):
        source = model.load();parameters = model.parameters(source)
        arm = model.arm(source);geometry = model.clip_geometry(source, parameters)
        mounting = model.mounts(source, parameters)
        context = {'parameters': model.route_parameters(source, parameters, arm, mounting),
                   'connection_interfaces': model.connection_interfaces}
        self.assertEqual(set(geometry['support_interfaces']), set(source['hose_routing']['clips']))
        for name, state in ORIGINAL_STATES.items():
            link_frames = robot.forward(arm, state['joints_deg'])
            mounted = {key: robot.multiply(link_frames[row['link']], row['zero_transform'])
                       for key, row in mounting.items()}
            evaluated = routing.frames(source, parameters, link_frames, mounted, context)
            for station, support in geometry['support_interfaces'].items():
                with self.subTest(state=name, station=station):
                    physical_center = robot.transform(mounted[support['component']], support['center_mm'])
                    frame = evaluated[station]
                    self.assertLess(math.dist(frame['center_mm'], physical_center), 1e-8)
                    self.assertEqual(frame['body_id'], support['clip_body'])
                    self.assertEqual(frame['host_body'], support['host_body'])
                    self.assertAlmostEqual(math.dist(frame['start_mm'], frame['end_mm']), parameters['hoseClipLength'])
                    axis = [sum(mounted[support['component']][i][j]*support['axis'][j] for j in range(3))
                            for i in range(3)]
                    self.assertLess(math.dist(frame['tangent'], axis), 1e-8)

    def test_a_global_slack_number_cannot_replace_independently_fixed_sections(self):
        source = model.load();parameters = model.parameters(source)
        for value in (0., 5., 80., True):
            with self.subTest(global_slack=value), self.assertRaises(ValueError):
                model.route_at(source, parameters,
                    source['states']['working']['joints_deg'], value, state_id='working')


class LinkClippedDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = model.load()
        cls.parameters = model.parameters(cls.source)
        cls.proof = model.named_length_band(cls.source, cls.parameters)

    def require_design(self):
        self.assertTrue(self.proof['passed'], self.proof.get('failures'))
        self.assertEqual(self.proof['format'], routing.PROOF_FORMAT)
        self.assertEqual(set(self.proof['states']), set(self.source['states']))
        self.assertTrue(all(value is False for value in self.proof['qualification'].values()))

    def test_fixed_link_curves_are_one_rigid_local_template_across_all_poses(self):
        self.require_design()
        templates = {}
        arm = model.arm(self.source)
        for name, selected in self.proof['states'].items():
            fk = robot.forward(arm, self.source['states'][name]['joints_deg'])
            path = selected['path']
            for record in path['section_records']:
                if record['kind'] != 'fixed_link':continue
                transform = fk[record['link']]
                def inverse_point(point):
                    delta = [point[i]-transform[i][3] for i in range(3)]
                    return [sum(transform[i][j]*delta[i] for i in range(3)) for j in range(3)]
                def inverse_vector(vector):
                    return [sum(transform[i][j]*vector[i] for i in range(3)) for j in range(3)]
                local = []
                start, count = record['segment_start_index'], record['segment_count']
                for segment in path['segments'][start:start+count]:
                    row = {'kind': segment['kind']}
                    row.update({key: inverse_point(segment[key]) for key in
                                ('start_mm', 'end_mm', 'through_mm', 'center_mm') if key in segment})
                    if 'axis' in segment:row['axis'] = inverse_vector(segment['axis'])
                    for key in ('radius_mm', 'sweep_rad'):
                        if key in segment:row[key] = segment[key]
                    local.append(row)
                first = templates.setdefault(record['id'], local)
                with self.subTest(state=name, section=record['id']):
                    self.assertEqual(len(local), len(first))
                    for actual, expected in zip(local, first):
                        self.assertEqual(set(actual), set(expected))
                        self.assertEqual(actual['kind'], expected['kind'])
                        for key in set(actual)-{'kind'}:
                            if isinstance(actual[key], list):
                                self.assertLess(math.dist(actual[key], expected[key]), 1e-7)
                            else:self.assertAlmostEqual(actual[key], expected[key], places=7)
        self.assertEqual(set(templates), {row['id'] for row in self.source['hose_routing']['sections']
                                         if row['kind'] == 'fixed_link'})

    def test_actual_geometry_fixes_every_section_and_clip_material_station(self):
        self.require_design()
        for name, selected in self.proof['states'].items():
            path = selected['path'];segments = path['segments']
            measured = [geometric_segment_length(segment) for segment in segments]
            with self.subTest(state=name):
                self.assertAlmostEqual(math.fsum(measured), self.proof['hose_length_mm'], places=6)
                for segment, exact in zip(segments, measured):
                    self.assertAlmostEqual(segment['length_mm'], exact, places=7)
                    if segment['kind'] == 'arc':
                        actual_radius = math.dist(segment['start_mm'], segment['center_mm'])
                        self.assertGreaterEqual(actual_radius, 12-1e-7)
                self.assertEqual({row['id'] for row in path['section_records']},
                                 set(self.proof['section_lengths_mm']))
                for section in path['section_records']:
                    start, count = section['segment_start_index'], section['segment_count']
                    exact = math.fsum(measured[start:start+count])
                    self.assertAlmostEqual(exact, self.proof['section_lengths_mm'][section['id']], places=6)
                    self.assertAlmostEqual(exact, section['actual_length_mm'], places=7)
                stations = {}
                for part in path['length_accounting']['parts']:
                    start, count = part['segment_start_index'], part['segment_count']
                    if part['kind'] == 'clip_straight':
                        self.assertTrue(all(segment['kind'] == 'line' for segment in segments[start:start+count]))
                        exact = math.fsum(measured[start:start+count])
                        self.assertAlmostEqual(exact, self.parameters['hoseClipLength'], places=7)
                        stations[part['id']] = math.fsum(measured[:start])+exact/2
                self.assertEqual(set(stations), set(self.source['hose_routing']['clips']))
                for station, actual in stations.items():
                    self.assertAlmostEqual(actual, self.proof['clip_material_stations_mm'][station], places=6)
                    self.assertAlmostEqual(actual, path['clip_material_stations_mm'][station], places=7)

if __name__ == '__main__':
    unittest.main()
