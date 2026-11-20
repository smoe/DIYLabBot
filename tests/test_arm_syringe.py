"""SP02 source/attachment invariants; ideal displacement is not a delivered dose."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import arm_syringe as model
import build_arm_syringe as builder
import pneumatic_hose as hose
import robot_spec as robot
import spatial_hose_carrier as carrier
import joint_hose_routing as joint_routing

CONTACT_PAIRS = frozenset(frozenset(pair) for pair in (
    ('ClampPadL0', 'Upper_plate_L'), ('ClampPadL1', 'Upper_plate_L'),
    ('ClampPadR0', 'Upper_plate_R'), ('ClampPadR1', 'Upper_plate_R'),
    ('TipFlangePad', 'Bare_tool_flange'), ('TipFlangePad', 'J6_output_coupler'),
    ('LeadScrewEnvelopeFine', 'MotorEnvelopeFine'), ('MotorEnvelopeFine', 'ScrewCoupler'),
    ('SinglePumpPlate', 'ClampBridge0'), ('SinglePumpPlate', 'ClampBridge1'),
    ('PumpHoseBarb', 'PneumaticHose'), ('TipSidePort', 'PneumaticHose'),
    ('TipShaft', 'DisposableTip'),
))


class IntervalShape:
    """Independent unit-Y/Z box witness for clearance policy, without native CAD."""
    def __init__(self, interval):
        self.low, self.high = interval

    def distToShape(self, other):
        return (max(0, self.low-other.high, other.low-self.high), [], [])

    def common(self, other):
        return SimpleNamespace(Volume=max(0, min(self.high, other.high)-max(self.low, other.low)))


class ArmSyringeClearancePolicyTests(unittest.TestCase):
    @staticmethod
    def inspect(intervals, contacts=()):
        arm = [{'id': 'Arm', 'role': 'structure'}]
        own = [{'id': 'ToolA', 'component': 'A'}, {'id': 'ToolB', 'component': 'B'}]
        shapes = {name: IntervalShape(interval) for name, interval in intervals.items()}
        boxes = {name: {'min': [low, 0, 0], 'max': [high, 1, 1]}
                 for name, (low, high) in intervals.items()}
        return builder.audit_clearances(arm, own, shapes, list(contacts), boxes)

    def test_each_clearance_category_retains_its_own_positive_minimum(self):
        report = self.inspect({'Arm': (0, 1), 'PneumaticHose': (1.1, 1.2),
                               'ToolA': (4, 5), 'ToolB': (7, 8)})
        self.assertTrue(report['passed'])
        for category, minimum in {'hose_arm': .1, 'tooling_arm': 3, 'tooling_tooling': 2}.items():
            with self.subTest(category=category):
                self.assertAlmostEqual(report['categories'][category]['minimum_distance_mm'], minimum)
                self.assertTrue(report['categories'][category]['passed'])
        self.assertAlmostEqual(report['minimum_nonallowed_distance_mm'], .1)

    def test_zero_volume_boundary_contact_fails_unless_explicitly_declared(self):
        intervals = {'Arm': (0, 1), 'PneumaticHose': (-5, -4), 'ToolA': (1, 2), 'ToolB': (7, 8)}
        unrecognized = self.inspect(intervals)
        self.assertFalse(unrecognized['passed'])
        self.assertEqual(len(unrecognized['undeclared_contacts']), 1)
        self.assertEqual(unrecognized['undeclared_contacts'][0]['overlap_mm3'], 0)
        accepted = self.inspect(intervals, [{'a': 'ToolA', 'b': 'Arm', 'reason': 'Test mounting face'}])
        self.assertTrue(accepted['passed'])
        self.assertFalse(accepted['undeclared_contacts'])
        self.assertEqual(accepted['allowed_contacts'][0]['distance_mm'], 0)
        self.assertEqual(accepted['allowed_contacts'][0]['overlap_mm3'], 0)
        self.assertEqual(accepted['categories']['tooling_arm']['minimum_distance_mm'], 6)
        self.assertTrue(all(row['minimum_distance_mm'] > 0 for row in accepted['categories'].values()))
        contacts = [{'a': 'PneumaticHose', 'b': name, 'distance_mm': 0., 'overlap_mm3': 0.}
                    for name in ('PumpHoseBarb', 'TipSidePort')]
        interfaces = {'pump': {'body': 'PumpHoseBarb'}, 'tip': {'body': 'TipSidePort'}}
        mating = {'passed': True, 'interfaces': {'pump': {'passed': True}, 'tip': {'passed': True}}}
        self.assertFalse(builder.pneumatic_connections({'allowed_contacts': contacts}, interfaces)['passed'])
        self.assertTrue(builder.pneumatic_connections({'allowed_contacts': contacts}, interfaces, mating)['passed'])
        for failed in ({'passed': False, 'interfaces': mating['interfaces']},
                       {'passed': True, 'interfaces': {'pump': {'passed': True}}},
                       {'passed': True, 'interfaces': {'pump': {'passed': False}, 'tip': {'passed': True}}}):
            self.assertFalse(builder.pneumatic_connections({'allowed_contacts': contacts}, interfaces, failed)['passed'])
        with self.assertRaises(ValueError):
            builder.pneumatic_connections({'allowed_contacts': contacts})
        contacts[0]['distance_mm'] = .001
        self.assertFalse(builder.pneumatic_connections({'allowed_contacts': contacts}, interfaces, mating)['passed'])

    def test_declared_contact_still_fails_for_material_overlap_above_numeric_tolerance(self):
        report = self.inspect({'Arm': (0, 1), 'PneumaticHose': (-5, -4),
                               'ToolA': (.5, 1.5), 'ToolB': (7, 8)},
                              [{'a': 'ToolA', 'b': 'Arm', 'reason': 'Test mounting face'}])
        self.assertFalse(report['passed'])
        self.assertEqual(report['allowed_contacts'][0]['overlap_mm3'], .5)
        self.assertFalse(report['allowed_contacts'][0]['within_overlap_zero_tolerance'])
        self.assertEqual(report['interferences'][0]['volume_mm3'], .5)

    def test_pair_coverage_keeps_host_links_and_cameras_but_rejects_unknown_or_duplicate_declarations(self):
        groups = builder.clearance_pair_groups(
            [{'id': 'L2Body', 'role': 'structure'}, {'id': 'Camera', 'role': 'camera'},
             {'id': 'ViewCone', 'role': 'viewing_cone'}],
            [{'id': 'ToolA', 'component': 'A'}, {'id': 'ToolB', 'component': 'B'}])
        self.assertEqual(set(groups['hose_arm']), {('PneumaticHose', 'L2Body'), ('PneumaticHose', 'Camera')})
        self.assertEqual(set(groups['tooling_arm']),
                         {(tool, arm) for tool in ('ToolA', 'ToolB') for arm in ('L2Body', 'Camera')})
        self.assertEqual({frozenset(pair) for pair in groups['tooling_tooling']},
                         {frozenset(pair) for pair in [('ToolA', 'ToolB'), ('ToolA', 'PneumaticHose'),
                                                      ('ToolB', 'PneumaticHose')]})
        intervals = {'Arm': (0, 1), 'PneumaticHose': (-5, -4), 'ToolA': (1, 2), 'ToolB': (7, 8)}
        contact = {'a': 'ToolA', 'b': 'Arm', 'reason': 'Test mounting face'}
        for contacts in ([{**contact, 'b': 'Unknown'}], [contact, {**contact, 'a': 'Arm', 'b': 'ToolA'}]):
            with self.subTest(contacts=contacts), self.assertRaises(ValueError):
                self.inspect(intervals, contacts)

    def test_carrier_guard_checks_external_classes_and_cannot_be_masked_by_material_contacts(self):
        arm = [{'id': 'Arm', 'role': 'structure'}, {'id': 'Camera', 'role': 'camera'},
               {'id': 'ViewCone', 'role': 'viewing_cone'}]
        rigid = [{'id': 'ToolA', 'component': 'A'}, {'id': 'ToolB', 'component': 'B'}]
        snapshot = {'carrier': {'nominal_link_count': 2, 'links': [{'id': 'C0'}, {'id': 'C1'}],
                                'native_aliases': ['C0', 'C1']}}
        delivered = builder.carrier_bodies(snapshot)
        self.assertEqual({row['id'] for row in delivered}, {'CarrierEnvelope', 'CarrierLinks'})
        self.assertNotIn('CarrierOuterGuard', {row['id'] for row in delivered})
        guards = builder.guard_pair_groups(arm, rigid)
        self.assertEqual(set(guards['carrier_guard_arm']),
                         {('CarrierOuterGuard', 'Arm'), ('CarrierOuterGuard', 'Camera')})
        self.assertEqual(set(guards['carrier_guard_tooling']),
                         {('CarrierOuterGuard', 'ToolA'), ('CarrierOuterGuard', 'ToolB')})
        material_groups = builder.clearance_pair_groups(arm, rigid+delivered)
        material_pairs = {frozenset(pair) for pairs in material_groups.values() for pair in pairs}
        self.assertIn(frozenset(('PneumaticHose', 'CarrierEnvelope')), material_pairs)
        self.assertIn(frozenset(('PneumaticHose', 'CarrierLinks')), material_pairs)
        intervals = {'Arm': (0, 1), 'Camera': (8, 9), 'ToolA': (1, 2), 'ToolB': (10, 11),
                     'PneumaticHose': (-5, -4), 'CarrierEnvelope': (-9, -8),
                     'CarrierLinks': (-12, -11), 'CarrierOuterGuard': (.5, 1.5)}
        shapes = {name: IntervalShape(interval) for name, interval in intervals.items()}
        boxes = {name: {'min': [low, 0, 0], 'max': [high, 1, 1]}
                 for name, (low, high) in intervals.items()}
        material = builder.audit_clearances(arm, rigid+delivered, shapes,
                                            [{'a': 'ToolA', 'b': 'Arm', 'reason': 'Mount face'}], boxes)
        guard = builder.audit_clearances(arm, rigid, shapes, [], boxes, pair_groups=guards)
        self.assertTrue(material['passed'])
        self.assertFalse(guard['passed'])
        merged = builder.merge_clearance_checks(material, guard)
        self.assertFalse(merged['passed'])
        self.assertEqual(merged['allowed_contacts'], material['allowed_contacts'])
        self.assertEqual(merged['interferences'], guard['interferences'])
        self.assertTrue(all(row['volume_mm3'] == .5 for row in merged['interferences']))
        self.assertIs(merged['clearance_proxy_policy']['delivered_material_body'], False)

    def test_named_route_comparison_validates_optional_provenance_without_ignoring_geometry(self):
        joints = [0, 10, 20, 0, 30, 0]
        route = {'length_mm': 10., 'qualified': False,
                 'segments': [{'kind': 'line', 'start_mm': [0., 0., 0.], 'end_mm': [10., 0., 0.]}]}
        for expected, actual in ((route, route),
                                 (route, {**route, 'joints_deg': joints}),
                                 ({**route, 'joints_deg': joints}, route)):
            with self.subTest(expected_provenance='joints_deg' in expected,
                              actual_provenance='joints_deg' in actual):
                checked = builder.compare_named_route(expected, {'joints_deg': joints, 'hose_path': actual})
                self.assertTrue(checked['passed'])
                self.assertFalse(checked['mismatches'])
        wrong = [0, 11, 20, 0, 30, 0]
        for expected, actual in (({**route, 'joints_deg': wrong}, route),
                                 (route, {**route, 'joints_deg': wrong})):
            with self.subTest(expected=expected, actual=actual), self.assertRaises(ValueError):
                builder.compare_named_route(expected, {'joints_deg': joints, 'hose_path': actual})
        changed = copy.deepcopy(route)
        changed['segments'][0]['end_mm'][0] = 9.
        self.assertFalse(builder.compare_named_route(route, {'joints_deg': joints, 'hose_path': changed})['passed'])
        self.assertFalse(builder.compare_named_route(route, {'joints_deg': joints,
                         'hose_path': {**route, 'unrecognized_metadata': True}})['passed'])

    def test_full_build_requires_a_passed_finite_hose_self_clearance_record(self):
        accepted = {'passed': True, 'continuous_self_clearance_verified': False}
        self.assertIs(builder.require_hose_self_clearance({'hose_self_clearance': accepted}), accepted)
        rejected = [{}, {'hose_self_clearance': None},
                    {'hose_self_clearance': {'passed': False, 'continuous_self_clearance_verified': False}},
                    {'hose_self_clearance': {'passed': True}},
                    {'hose_self_clearance': {'passed': True, 'continuous_self_clearance_verified': True}},
                    {'hose_self_clearance': {'passed': True, 'continuous_self_clearance_verified': 0}}]
        for state in rejected:
            with self.subTest(state=state), self.assertRaises(ValueError):
                builder.require_hose_self_clearance(state)


class ArmSyringeCurveComparisonTests(unittest.TestCase):
    @staticmethod
    def fixture(*, split=False, midpoint_offset=0., boundary_shift=0.):
        # Independent straight/quarter-circle route with a real six-role
        # partition. No stored CAD output or live routing study is required.
        point = [0., 0., 0.]
        direction = [1., 0., 0.]
        segments, parts = [], []
        def line(length, start=None, end=None):
            a = list(point) if start is None else list(start)
            b = [v+length*axis for v, axis in zip(a, direction)] if end is None else list(end)
            return {'kind': 'line', 'start_mm': a, 'end_mm': b, 'length_mm': math.dist(a, b)}
        def part(name, kind, length, subdivide=False):
            nonlocal point
            start = len(segments)
            end = [value+length*axis for value, axis in zip(point, direction)]
            if subdivide:
                middle = [(a+b)/2 for a, b in zip(point, end)]
                middle[1] += midpoint_offset
                segments.extend((line(length/2, point, middle), line(length/2, middle, end)))
            else:
                segments.append(line(length))
            point = end
            parts.append({'id': name, 'kind': kind, 'length_mm': sum(row['length_mm'] for row in segments[start:]),
                          'segment_start_index': start, 'segment_count': len(segments)-start})
        for name, kind, length in (('pump_inserted', 'inserted', 6),
                                   ('pump_support', 'socket_strain_relief', 10),
                                   ('pump_lead', 'connector_straight_lead', 10)):
            part(name, kind, length)
        part('entry_span', 'bare_span', 20, subdivide=split)
        guide_start = len(segments)
        segments.append(line(10));point = list(segments[-1]['end_mm'])
        center = [point[0], point[1]+50, 0.]
        segments.append({'kind': 'arc', 'start_mm': list(point),
            'end_mm': [center[0]+50, center[1], 0.],
            'through_mm': [center[0]+50/math.sqrt(2), center[1]-50/math.sqrt(2), 0.],
            'center_mm': center, 'axis': [0., 0., 1.], 'radius_mm': 50.,
            'sweep_rad': math.pi/2, 'length_mm': 50*math.pi/2})
        point = list(segments[-1]['end_mm']);direction = [0., 1., 0.]
        segments.append(line(100-10-50*math.pi/2));point = list(segments[-1]['end_mm'])
        guide_segments = copy.deepcopy(segments[guide_start:])
        parts.append({'id': 'guide', 'kind': 'nominal_carrier', 'length_mm': 100.,
                      'segment_start_index': guide_start, 'segment_count': len(segments)-guide_start})
        part('exit_span', 'bare_span', 20-boundary_shift)
        part('ordinary_clip', 'clip_straight', 20+boundary_shift)
        for name, kind, length in (('tip_lead', 'connector_straight_lead', 10),
                                   ('tip_support', 'socket_strain_relief', 10),
                                   ('tip_inserted', 'inserted', 6)):
            part(name, kind, length)
        length = sum(row['length_mm'] for row in segments)
        guide = {'format': 'solidcraftbot.static-hose-centerline/1', 'segments': guide_segments,
                 'length_mm': 100., 'min_bend_radius_mm': 50.,
                 'carrier_fit': {'endpoint_straights_mm': [10., 10.]}}
        account = {'inserted_mm': 12., 'socket_strain_relief_mm': 20.,
                   'connector_straight_leads_mm': 20., 'clip_supported_mm': 20.+boundary_shift,
                   'carrier_supported_mm': 100., 'free_bare_spans_mm': 40.-boundary_shift,
                   'external_guide_straights_included_in_free_mm': 20.,
                   'total_mm': length, 'sum_error_mm': 0., 'service_loop_parameter_mm': 0.,
                   'parts': parts, 'scope': 'Synthetic material fixture, not an arm design'}
        route = {'format': guide['format'], 'controls_mm': [[0., 0., 0.], list(point)],
                 'segments': segments, 'sample_points_mm': [[0., 0., 0.], list(point)],
                 'length_mm': length, 'requested_bend_radius_mm': 12., 'min_bend_radius_mm': 50.,
                 'qualified': False, 'carrier_path': guide, 'routing_frames': {},
                 'framed_crossings': {}, 'crossing_control_indices': {}, 'length_accounting': account}
        state = {'id': 'synthetic', 'joints_deg': [0.]*6, 'stroke_mm': 0., 'motor_angle_deg': 0.,
                 'valve_angle_deg': 0., 'part_matrices': {}, 'hose_path': route,
                 'hose_self_clearance': {'passed': True}, 'source_clearance': {'passed': True},
                 'length_accounting': account, 'carrier': {'path': copy.deepcopy(guide)}, 'hose_points_mm': route['sample_points_mm'],
                 'hose_inner_radius_mm': .25, 'hose_outer_radius_mm': .9, 'hose_slack_parameter_mm': 0.,
                 'theoretical_displacement_ul': 0., 'actual_dispensed_volume_ul': None, 'metrics': {},
                 'connection_interfaces': {}, 'tip_seat': {}, 'tip_tcp_mm': list(point)}
        parameters = {'hoseLength': length, 'hoseBendRadius': 12., 'connectorStraightLead': 10.,
                      'hoseInsertionDepth': 6., 'strainReliefLength': 10.}
        return state, parameters

    @classmethod
    def clipped_fixture(cls, *, split=False, short_free_lead=False, first_flex_length=20.):
        # Literal282mm material:8 independently owned20mm spans,7 real10mm
        # support intervals and2×26mm sockets. No ignored proof file is read.
        state, parameters = cls.fixture()
        names = ('j3_parent', 'j3_child', 'j4_parent', 'j4_child',
                 'j5_parent', 'j5_child', 'j6_parent')
        segments, parts, sections, frames, stations = [], [], [], {}, {}
        point = [0., 0., 0.];direction = [1., 0., 0.];covered = 0.
        def line(length):
            nonlocal point
            end = [v+length*d for v, d in zip(point, direction)]
            segments.append({'kind': 'line', 'start_mm': list(point), 'end_mm': end, 'length_mm': length})
            point = end
        def add(name, kind, length, *, subdivide=False, bend=False):
            nonlocal direction, point, covered
            index = len(segments);start = list(point)
            if bend:
                # A real R12 quarter circle fits20mm only with1mm and.15mm
                # endpoint straights, so it must fail the separate5mm gate.
                line(1.)
                center = [point[0], point[1]+12., point[2]]
                end = [center[0]+12., center[1], center[2]]
                segments.append({'kind': 'arc', 'start_mm': list(point), 'end_mm': end,
                    'through_mm': [center[0]+12/math.sqrt(2), center[1]-12/math.sqrt(2), center[2]],
                    'center_mm': center, 'axis': [0., 0., 1.], 'radius_mm': 12.,
                    'sweep_rad': math.pi/2, 'length_mm': 6*math.pi})
                point = end;direction = [0., 1., 0.]
                line(length-1.-6*math.pi)
            else:
                for amount in ([length/2, length/2] if subdivide else [length]):line(amount)
            part = {'id': name, 'kind': kind, 'length_mm': length,
                    'segment_start_index': index, 'segment_count': len(segments)-index}
            parts.append(part);covered += length
            return part, start
        for name, kind, length in (('pump_inserted', 'inserted', 6.),
                                   ('pump_support', 'socket_strain_relief', 10.),
                                   ('pump_lead', 'connector_straight_lead', 10.)):
            add(name, kind, length)
        for index in range(8):
            length = first_flex_length if index == 1 else 20.
            part, _ = add('section'+str(index), 'bare_span', length,
                          subdivide=split and index == 0, bend=short_free_lead and index == 1)
            sections.append({key: part[key] for key in ('id', 'segment_start_index', 'segment_count')}|
                {'kind': 'fixed_link' if index % 2 == 0 else 'joint_loop',
                 'target_length_mm': length, 'actual_length_mm': length})
            if index < 7:
                name = names[index];part, start = add(name, 'clip_straight', 10.)
                center = [(a+b)/2 for a, b in zip(start, point)]
                stations[name] = covered-5.
                frames[name] = {'center_mm': center, 'start_mm': start, 'end_mm': list(point),
                                'tangent': list(direction), 'x_axis': [0., 0., 1.]}
        for name, kind, length in (('tip_lead', 'connector_straight_lead', 10.),
                                   ('tip_support', 'socket_strain_relief', 10.),
                                   ('tip_inserted', 'inserted', 6.)):
            add(name, kind, length)
        account = {'inserted_mm': 12., 'socket_strain_relief_mm': 20.,
            'connector_straight_leads_mm': 20., 'clip_supported_mm': 70.,
            'carrier_supported_mm': 0., 'free_bare_spans_mm': 140.+first_flex_length,
            'external_guide_straights_included_in_free_mm': 0., 'total_mm': covered,
            'sum_error_mm': 0., 'parts': parts, 'scope': 'Independent clipped material fixture'}
        path = {'format': 'solidcraftbot.static-hose-centerline/1',
            'routing_format': joint_routing.FORMAT, 'controls_mm': [[0., 0., 0.], list(point)],
            'segments': segments, 'sample_points_mm': [[0., 0., 0.], list(point)],
            'length_mm': covered, 'requested_bend_radius_mm': 12.,
            'min_bend_radius_mm': 12. if short_free_lead else None, 'qualified': False,
            'routing_frames': frames, 'framed_crossings': {}, 'crossing_control_indices': {},
            'clip_frames': frames, 'clip_material_stations_mm': stations,
            'section_records': sections, 'length_accounting': account}
        for section in sections:
            if section['kind'] != 'joint_loop':
                continue
            offset = sum(row['length_mm'] for row in segments[:section['segment_start_index']])
            length = section['actual_length_mm'];count = math.ceil(length/2.)
            points = [carrier.path_position(path, offset+length*i/count)['point_mm']
                      for i in range(count+1)]
            origin_x = points[0][0]+length/2.;half_cell = length/(2*count)
            section['local_reach'] = {
                'maximum_radial_reach_upper_bound_mm': max(math.hypot(q[1], q[2]) for q in points)+half_cell,
                'required_maximum_radial_reach_mm': 1000.,
                'axial_range_outer_bound_mm': [min(q[0]-origin_x for q in points)-half_cell,
                                              max(q[0]-origin_x for q in points)+half_cell],
                'required_axial_range_mm': [-1000., 1000.],
                'scope': 'Independent synthetic joint-axis interval bounds'}
        state.update(hose_path=path, length_accounting=account, carrier=None,
            hose_points_mm=path['sample_points_mm'], hose_slack_parameter_mm=None,
            hose_routing_design={'format': joint_routing.PROOF_FORMAT,
                'section_lengths_mm': {row['id']: row['target_length_mm'] for row in sections},
                'hose_length_mm': covered, 'clip_material_stations_mm': stations},
            clip_support_interfaces={}, hose_proximity={'passed': True})
        parameters.update(hoseLength=covered, hoseClipLength=10., clipFreeLead=5.)
        return state, parameters

    def test_collinear_subdivision_inside_one_physical_part_preserves_the_complete_core(self):
        plain, p = self.fixture()
        split, q = self.fixture(split=True)
        self.assertEqual(p, q)
        self.assertEqual(len(split['hose_path']['segments']), len(plain['hose_path']['segments'])+1)
        a = builder.canonical_material_core(plain, p)
        b = builder.canonical_material_core(split, q)
        self.assertTrue(builder.compare_derived_metrics(a, b, tolerance=1e-9)['passed'])
        self.assertEqual(len(a['length_accounting']['parts']), len(plain['length_accounting']['parts']))
        self.assertEqual(len(b['length_accounting']['parts'][3]['curves']), 1)
        self.assertEqual(a['carrier_segments'], b['carrier_segments'])
        self.assertNotEqual(builder.route_derivation_diagnostics(plain['hose_path']),
                            builder.route_derivation_diagnostics(split['hose_path']))
        plain, p = self.clipped_fixture();split, q = self.clipped_fixture(split=True)
        a = builder.canonical_material_core(plain, p)
        b = builder.canonical_material_core(split, q)
        self.assertTrue(builder.compare_derived_metrics(a, b, tolerance=1e-9)['passed'])
        material = builder.route_material_checks(plain['hose_path'], p)
        self.assertEqual(set(material['clip_end_straights']), set(plain['hose_path']['clip_frames']))
        self.assertTrue(all(row['passed'] for row in material['clip_end_straights'].values()))

    def test_curve_normalization_rejects_offline_points_changed_partitions_and_foreign_data(self):
        plain, p = self.fixture()
        expected = builder.canonical_material_core(plain, p)
        almost, q = self.fixture(split=True, midpoint_offset=1e-8)
        checked = builder.canonical_material_core(almost, q)
        self.assertFalse(builder.compare_derived_metrics(expected, checked, tolerance=1e-9)['passed'])
        self.assertEqual(len(checked['length_accounting']['parts'][3]['curves']), 2)
        shifted, q = self.fixture(boundary_shift=5.)
        self.assertFalse(builder.compare_derived_metrics(expected,
                         builder.canonical_material_core(shifted, q), tolerance=1e-9)['passed'])
        mutations = [
            ('foreign state', lambda state: state.update(foreign=True)),
            ('foreign route', lambda state: state['hose_path'].update(foreign=True)),
            ('foreign account', lambda state: state['length_accounting'].update(foreign=True)),
            ('foreign part', lambda state: state['length_accounting']['parts'][0].update(foreign=True)),
            ('foreign fitter data', lambda state: state['length_accounting']['parts'][3].update(bare_fit={'foreign': True})),
            ('foreign segment', lambda state: state['hose_path']['segments'][0].update(foreign=True)),
            ('overlapping partition', lambda state: state['length_accounting']['parts'][1].update(segment_start_index=0)),
            ('failed self gate', lambda state: state['hose_self_clearance'].update(passed=False)),
            ('failed source gate', lambda state: state['source_clearance'].update(passed=False)),
        ]
        for label, mutate in mutations:
            state, q = self.fixture()
            mutate(state)
            with self.subTest(case=label), self.assertRaises(ValueError):
                builder.canonical_material_core(state, q)
        state, q = self.fixture()
        arc_index = next(i for i, row in enumerate(state['hose_path']['segments']) if row['kind'] == 'arc')
        state['hose_path']['segments'][arc_index]['through_mm'][2] += 1e-5
        state['hose_path']['carrier_path']['segments'][1]['through_mm'][2] += 1e-5
        with self.assertRaises(ValueError):
            builder.canonical_material_core(state, q)
        state, q = self.clipped_fixture()
        state['hose_path']['clip_frames']['j3_parent']['start_mm'][0] += .01
        with self.assertRaises(ValueError):
            builder.canonical_material_core(state, q)
        short, q = self.clipped_fixture(short_free_lead=True)
        self.assertTrue(joint_routing.validate_material_path(short['hose_path'], q)['passed'])
        self.assertEqual(short['hose_path']['length_mm'], 282.)
        with self.assertRaises(ValueError):
            builder.route_material_checks(short['hose_path'], q)

    def test_interval_sampling_bounds_are_diagnostics_after_independent_limit_checks(self):
        plain, p = self.clipped_fixture(first_flex_length=72.)
        alternate = copy.deepcopy(plain)

        def record(state):
            return next(row for row in state['hose_path']['section_records']
                        if row['id'] == 'section1')

        def reach(intervals):
            # This literal72mm straight lies on its joint axis: radial distance0,
            # axial endpoints-28/+44. Independent Lipschitz bounds differ only
            # by the half-cell width when an ABI chooses36 instead of37 cells.
            half_cell = 72./(2*intervals)
            return {'maximum_radial_reach_upper_bound_mm': half_cell,
                    'required_maximum_radial_reach_mm': 60.,
                    'axial_range_outer_bound_mm': [-28.-half_cell, 44.+half_cell],
                    'required_axial_range_mm': [-30., 55.],
                    'scope': 'Independent straight-axis interval-bound fixture'}

        record(plain)['local_reach'] = reach(36)
        record(alternate)['local_reach'] = reach(37)
        self.assertAlmostEqual(reach(36)['maximum_radial_reach_upper_bound_mm']-
                               reach(37)['maximum_radial_reach_upper_bound_mm'], 1./37)
        expected = builder.canonical_material_core(plain, p)
        actual = builder.canonical_material_core(alternate, p)
        self.assertTrue(builder.compare_derived_metrics(expected, actual, tolerance=1e-9)['passed'])
        for state in (plain, alternate):
            retained = next(row for row in builder.route_derivation_diagnostics(state['hose_path'])
                            if row['id'] == 'section1')
            self.assertEqual(retained['local_reach'], record(state)['local_reach'])
        self.assertNotEqual(builder.route_derivation_diagnostics(plain['hose_path']),
                            builder.route_derivation_diagnostics(alternate['hose_path']))

        mutations = [
            ('radial limit exceeded', 'maximum_radial_reach_upper_bound_mm', 60.000001),
            ('axial lower limit exceeded', 'axial_range_outer_bound_mm', [-30.000001, 45.]),
            ('axial upper limit exceeded', 'axial_range_outer_bound_mm', [-29., 55.000001]),
            ('nonfinite radial bound', 'maximum_radial_reach_upper_bound_mm', math.nan),
            ('nonfinite axial bound', 'axial_range_outer_bound_mm', [-29., math.inf]),
            ('boolean radial bound', 'maximum_radial_reach_upper_bound_mm', True),
            ('reversed axial bounds', 'axial_range_outer_bound_mm', [45., -29.]),
        ]
        for label, key, value in mutations:
            changed = copy.deepcopy(alternate);record(changed)['local_reach'][key] = value
            with self.subTest(case=label), self.assertRaises(ValueError):
                builder.canonical_material_core(changed, p)
        changed = copy.deepcopy(alternate)
        record(changed)['local_reach']['required_maximum_radial_reach_mm'] = 61.
        self.assertFalse(builder.compare_derived_metrics(expected,
            builder.canonical_material_core(changed, p), tolerance=1e-9)['passed'])

        changed, q = self.clipped_fixture(first_flex_length=72., split=True)
        record(changed)['local_reach'] = reach(37)
        part = next(row for row in changed['hose_path']['length_accounting']['parts']
                    if row['id'] == 'section0')
        index = part['segment_start_index']
        changed['hose_path']['segments'][index]['end_mm'][1] += 1e-8
        changed['hose_path']['segments'][index+1]['start_mm'][1] += 1e-8
        self.assertFalse(builder.compare_derived_metrics(expected,
            builder.canonical_material_core(changed, q), tolerance=1e-9)['passed'])


class ArmSyringeSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(model.SOURCE.read_text())
        cls.spec = model.load()
        cls.p = model.parameters(cls.spec)
        cls._states = {}

    def observed_state(self, name):
        if name not in self._states:
            self._states[name] = model.state(self.spec, self.p, name)
        return self._states[name]

    def load_mutation(self, mutate):
        source = copy.deepcopy(self.raw)
        mutate(source)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'changed.json'
            path.write_text(json.dumps(source))
            return model.load(path)

    def assert_matrix_close(self, actual, expected):
        self.assertLess(max(abs(a-b) for row_a, row_b in zip(actual, expected)
                            for a, b in zip(row_a, row_b)), 1e-10)

    def test_all_leading_sources_are_pinned_and_changed_pins_fail_closed(self):
        for field in ('robot', 'syringe_library'):
            ref = self.spec[field]
            self.assertEqual(ref['source_sha256'], hashlib.sha256((ROOT/ref['source']).read_bytes()).hexdigest())
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
                self.load_mutation(lambda source: source[field].update(source_sha256='0'*64))
        self.assertIsNone(self.spec['hose_carrier'])

    def test_carrier_profile_remains_unqualified_and_rejects_claimed_acceptance(self):
        # The old R50 article remains an unchanged, unqualified library input;
        # it is not delivered by this clip-only routing mode.
        self.assertIsNone(self.spec['hose_carrier'])
        profile = carrier.load()
        self.assertTrue(profile['qualification'])
        self.assertTrue(all(type(value) is bool and not value for value in profile['qualification'].values()))
        self.assertTrue(profile['open_requirements'])
        self.assertTrue(all(value is None for value in profile['open_requirements'].values()))
        flag = next(iter(profile['qualification']))
        requirement = next(iter(profile['open_requirements']))
        for mutate in (lambda p: p['qualification'].update({flag: True}),
                       lambda p: p['open_requirements'].update({requirement: 0})):
            changed = copy.deepcopy(profile);mutate(changed)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'carrier.json';path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    carrier.load(path)

    def test_single_fine_syringe_and_one_fixed_tip_have_no_coarse_or_changer_geometry(self):
        source = model.expanded(self.spec, self.p)
        names = [row['id'] for row in source['bodies']]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({'GlassFine', 'SealFine', 'MotorEnvelopeFine', 'GuideCarriage',
                         'DriveNutEnvelope', 'FrontScrewBearing', 'CarriageSwitchFlag',
                         'HeadCollar', 'DisposableTip', 'TipSidePort'}.issubset(names))
        self.assertFalse(any('Coarse' in name for name in names))
        self.assertNotIn('HeadRemoval', {row['id'] for row in source['joints']})
        self.assertEqual(self.spec['nominal_capacity_ul'], 1000)
        self.assertEqual(self.spec['fixed_tip_head'], 'macro')
        self.assertFalse(self.spec['head_mount']['changeable_during_operation'])
        native = model.native_spec(self.spec, self.p)
        self.assertFalse(any('Coarse' in name for name in native['parameters']))

    def test_socket_and_tip_seat_assumptions_have_declared_dimensions_and_reject_bad_overrides(self):
        expected = {'socketRadialClearance': (.05, [.02, .15]),
                    'hoseInsertionDepth': (6, [4, 10]),
                    'strainReliefLength': (10, [5, 20]),
                    'connectorStraightLead': (10, [5, 20]),
                    'tipEngagementLength': (8, [5, 12]),
                    'tipTaperRelief': (.05, [.02, .15])}
        for name, (default, bounds) in expected.items():
            with self.subTest(parameter=name):
                definition = self.spec['parameters'][name]
                self.assertEqual(definition['unit'], 'mm')
                self.assertEqual(definition['value'], default)
                self.assertEqual(definition['range'], bounds)
                self.assertTrue(definition['meaning'].strip())
                for invalid in (True, math.nan, math.inf, 0,
                                math.nextafter(bounds[0], -math.inf),
                                math.nextafter(bounds[1], math.inf)):
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        model.parameters(self.spec, {name: invalid})
        for key in ('socket_ferrules_seals_and_tolerances', 'hose_clamps_and_strain_relief',
                    'tip_insertion_and_retention_forces'):
            self.assertIn(key, self.spec['open_requirements'])
            self.assertIsNone(self.spec['open_requirements'][key])
        self.assertAlmostEqual(self.p['hoseInnerRadius']*2, .5)
        self.assertAlmostEqual(self.p['hoseOuterRadius']*2, 1.8)
        self.assertEqual(self.spec['parameters']['hoseBendRadius']['range'][0], 12)
        self.assertGreaterEqual(self.p['hoseBendRadius'], 12)
        for invalid in (8, math.nextafter(12, -math.inf)):
            with self.subTest(bare_bend_radius=invalid), self.assertRaises(ValueError):
                model.parameters(self.spec, {'hoseBendRadius': invalid})

    def test_socket_frames_distinguish_material_end_support_and_straight_lead_in_local_and_world_space(self):
        local = model.connection_interfaces(self.spec, self.p)
        self.assertEqual(set(local), {'pump', 'tip'})
        expected = {'pump': ([-self.p['spacing']/2, -79, self.p['axisZ']], [0, -1, 0]),
                    'tip': ([-11, -95, self.p['axisZ']-27], [-1, 0, 0])}
        matrices = {'PumpFrame': [[0, -1, 0, 12], [1, 0, 0, 34], [0, 0, 1, 56], [0, 0, 0, 1]],
                    'WristHead': [[1, 0, 0, -9], [0, 0, -1, 8], [0, 1, 0, 7], [0, 0, 0, 1]]}
        world = model.connection_interfaces(self.spec, self.p, matrices)
        for name, (floor, outward) in expected.items():
            row = local[name]
            with self.subTest(interface=name):
                self.assertLess(math.dist(row['material_end_mm'], floor), 1e-10)
                self.assertEqual(row['pneumatic_junction_mm'], row['material_end_mm'])
                self.assertEqual(row['outward'], outward)
                self.assertAlmostEqual(math.dist(row['x_axis'], [0, 0, 0]), 1)
                self.assertAlmostEqual(sum(a*b for a, b in zip(row['x_axis'], outward)), 0)
                self.assertAlmostEqual(row['socket_radius_mm']-row['tube_outer_radius_mm'], .05)
                self.assertGreater(row['radial_clearance_mm'], 0)
                distances = {'socket_mouth_mm': self.p['hoseInsertionDepth'],
                             'unsupported_exit_mm': self.p['hoseInsertionDepth']+self.p['strainReliefLength'],
                             'bend_start_mm': self.p['hoseInsertionDepth']+self.p['strainReliefLength']+self.p['connectorStraightLead']}
                for key, distance in distances.items():
                    point = [value+distance*axis for value, axis in zip(floor, outward)]
                    self.assertLess(math.dist(row[key], point), 1e-10)
                witnesses = row['floor_witness_points_mm']
                self.assertGreaterEqual(len(witnesses), 4)
                for point in witnesses:
                    delta = [a-b for a, b in zip(point, floor)]
                    self.assertAlmostEqual(sum(a*b for a, b in zip(delta, outward)), 0)
                    radial = math.dist(point, floor)
                    self.assertGreater(radial, row['tube_inner_radius_mm'])
                    self.assertLess(radial, row['tube_outer_radius_mm'])
                self.assertIs(row['seal_qualified'], False)
                self.assertTrue(row['assumption'].strip())
                matrix = matrices[row['component']]
                for key in ('material_end_mm', 'pneumatic_junction_mm', 'socket_mouth_mm',
                            'unsupported_exit_mm', 'bend_start_mm'):
                    self.assertLess(math.dist(world[name][key], robot.transform(matrix, row[key])), 1e-9)
                for key in ('outward', 'x_axis'):
                    direction = [sum(matrix[i][j]*row[key][j] for j in range(3)) for i in range(3)]
                    self.assertLess(math.dist(world[name][key], direction), 1e-9)
                for actual, point in zip(world[name]['floor_witness_points_mm'], witnesses):
                    self.assertLess(math.dist(actual, robot.transform(matrix, point)), 1e-9)

    def test_socket_geometry_has_an_annular_floor_positive_wall_gap_and_supported_clamp(self):
        for depth in (4, 6, 10):
            p = model.parameters(self.spec, {'hoseInsertionDepth': depth})
            source = model.expanded(self.spec, p)
            operations = {row['id']: row for row in source['operations']}
            bodies = {row['id']: row for row in source['bodies']}
            value = lambda expression: model.evaluate(expression, p)
            for name, interface in model.connection_interfaces(self.spec, p).items():
                body = interface['body']
                base = operations[body]['shape']
                socket = operations[body+'_Socket']['shape']
                bore = operations[body+'_Bore']['shape']
                clamp_id = 'PumpHoseClamp' if name == 'pump' else 'TipHoseClamp'
                clamp = operations[clamp_id]['shape']
                clamp_gap = operations[clamp_id+'_Clearance']['shape']
                with self.subTest(depth=depth, interface=name):
                    inward = [-v for v in interface['outward']]
                    mouth, floor = interface['socket_mouth_mm'], interface['material_end_mm']
                    for shape in (base, socket):
                        self.assertEqual(shape['kind'], 'cylinder')
                        self.assertLess(math.dist([value(v) for v in shape['origin']], mouth), 1e-9)
                        self.assertEqual(shape['axis'], inward)
                    self.assertAlmostEqual(value(base['height']), depth+interface['through_length_mm'])
                    self.assertAlmostEqual(value(socket['height']), depth)
                    self.assertAlmostEqual(value(socket['radius'])-p['hoseOuterRadius'], p['socketRadialClearance'])
                    self.assertGreater(value(base['radius']), value(socket['radius']))
                    self.assertEqual(operations[body+'_Socket']['action'], 'cut')
                    self.assertEqual(operations[body+'_Bore']['action'], 'cut')
                    self.assertLess(math.dist([value(v) for v in bore['origin']], floor), 1e-9)
                    self.assertEqual(bore['axis'], inward)
                    self.assertAlmostEqual(value(bore['radius']), p['hoseInnerRadius'])
                    self.assertAlmostEqual(value(bore['height']), interface['through_length_mm'])
                    self.assertLess(math.dist([a+depth*b for a, b in zip(mouth, inward)], floor), 1e-9)
                    for shape in (clamp, clamp_gap):
                        self.assertLess(math.dist([value(v) for v in shape['origin']], mouth), 1e-9)
                        self.assertEqual(shape['axis'], interface['outward'])
                        self.assertAlmostEqual(value(shape['height']), p['strainReliefLength'])
                    self.assertGreater(value(clamp['radius']), value(clamp_gap['radius']))
                    self.assertAlmostEqual(value(clamp_gap['radius'])-p['hoseOuterRadius'], p['socketRadialClearance'])
                    self.assertEqual(bodies[clamp_id]['component'], interface['component'])
                    self.assertNotEqual(bodies[clamp_id]['component'], 'ConsumableTip')

    def test_derived_tip_shaft_engages_separate_consumable_at_one_lower_seal_circle(self):
        library = model.library(self.spec)
        for engagement in (5, 8, 12):
            p = model.parameters(self.spec, {'tipEngagementLength': engagement})
            source = model.expanded(self.spec, p)
            operations = {row['id']: row for row in source['operations']}
            bodies = {row['id']: row for row in source['bodies']}
            value = lambda expression: model.evaluate(expression, p)
            tip = operations['DisposableTip']['shape']
            interior = operations['DisposableTip_Interior']['shape']
            shaft = operations['TipShaft']['shape']
            upper = operations['TipShaft_Upper']['shape']
            air = operations['TipShaft_Air']['shape']
            seat = model.tip_seat(self.spec, p)
            bottom = value(tip['origin'][2])
            top = bottom+value(tip['height'])
            inner_start = value(interior['origin'][2])
            slope = (value(interior['top_radius'])-value(interior['radius']))/value(interior['height'])
            inner_at = lambda z: value(interior['radius'])+slope*(z-inner_start)
            seal_z = top-engagement
            with self.subTest(engagement=engagement):
                self.assertNotIn('TipCone', bodies)
                self.assertEqual(bodies['TipShaft']['component'], 'WristHead')
                self.assertEqual(bodies['DisposableTip']['component'], 'ConsumableTip')
                self.assertNotEqual(bodies['TipShaft']['component'], bodies['DisposableTip']['component'])
                self.assertEqual(shaft['kind'], 'cone')
                self.assertEqual(shaft['axis'], [0, 0, 1])
                self.assertAlmostEqual(value(shaft['origin'][2]), seal_z)
                self.assertAlmostEqual(value(shaft['height']), engagement)
                self.assertAlmostEqual(value(shaft['radius']), inner_at(seal_z))
                self.assertAlmostEqual(value(shaft['top_radius']), inner_at(top)-p['tipTaperRelief'])
                for fraction in (.25, .5, .75, 1):
                    z = seal_z+engagement*fraction
                    radius = value(shaft['radius'])+fraction*(value(shaft['top_radius'])-value(shaft['radius']))
                    self.assertAlmostEqual(inner_at(z)-radius, p['tipTaperRelief']*fraction)
                    self.assertGreater(inner_at(z)-radius, 0)
                self.assertEqual(operations['TipShaft_Upper']['action'], 'join')
                self.assertAlmostEqual(value(upper['origin'][2]), top)
                self.assertAlmostEqual(value(upper['radius']), value(shaft['top_radius']))
                self.assertAlmostEqual(value(upper['height']), 15)
                self.assertAlmostEqual(value(upper['top_radius']), library['tip_heads'][self.spec['fixed_tip_head']]['cone_radius_mm'])
                self.assertEqual(operations['TipShaft_Air']['action'], 'cut')
                self.assertAlmostEqual(value(air['radius']), p['pipeBore'])
                self.assertAlmostEqual(value(air['origin'][2]), seal_z)
                self.assertAlmostEqual(value(air['height']), engagement+15)
                self.assertLess(math.dist(seat['seal_center_mm'], [0, -95, seal_z]), 1e-9)
                self.assertAlmostEqual(seat['seal_radius_mm'], inner_at(seal_z))
                self.assertLess(math.dist(seat['tip_tcp_mm'], [value(v) for v in tip['origin']]), 1e-9)
                self.assertIs(seat['seal_qualified'], False)
                self.assertIs(seat['insertion_force_qualified'], False)
                mounting = model.mounts(self.spec, p)
                self.assertEqual(mounting['ConsumableTip'], mounting['WristHead'])
                self.assertEqual(mounting['ConsumableTip']['link'], 'L6_BareFlange')
                contacts = {frozenset((row['a'], row['b'])) for row in model.allowed_contacts(self.spec, p)}
                self.assertIn(frozenset(('TipShaft', 'DisposableTip')), contacts)

    def test_fixed_host_links_and_tip_family_cannot_silently_change(self):
        mutations = [lambda s: s.update(syringe_id='Coarse'),
                     lambda s: s.update(nominal_capacity_ul=10000),
                     lambda s: s.update(fixed_tip_head='micro'),
                     lambda s: s['pump_mount'].update(link='L4_ForearmRoll'),
                     lambda s: s['head_mount'].update(changeable_during_operation=True)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.load_mutation(mutate)

    def test_invalid_driving_parameters_are_rejected_before_geometry(self):
        for overrides in ({'pitch': 0}, {'pitch': -1}, {'pitch': True},
                          {'outboard': float('nan')}, {'outboard': float('inf')},
                          {'hoseLength': 1}, {'unimplemented_option': 1}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                model.parameters(self.spec, overrides)
        wrong_units = copy.deepcopy(self.spec)
        wrong_units['parameters']['pitch']['unit'] = 'deg'
        with self.assertRaises(ValueError):
            model.parameters(wrong_units)

    def test_runtime_load_rejects_incomplete_or_contradictory_source_contracts(self):
        mutations = [
            ('missing open requirements', lambda s: s.update(open_requirements={})),
            ('unknown open requirement', lambda s: s['open_requirements'].update(unknown=None)),
            ('missing carrier reference', lambda s: s.pop('hose_carrier')),
            ('obsolete carrier article reactivated', lambda s: s.update(hose_carrier={
                'source': 'model/spatial-hose-carrier.shared.json', 'source_sha256': '0'*64})),
            ('unknown assembly reference field', lambda s: s['robot'].update(unimplemented=1)),
            ('absolute assembly reference', lambda s: s['robot'].update(source=str((ROOT/s['robot']['source']).resolve()))),
            ('escaping assembly reference', lambda s: s['robot'].update(source='../'+s['robot']['source'])),
            ('missing inspection state', lambda s: s['states'].pop('extended')),
            ('missing earlier named boundary', lambda s: s['states'].pop('window_route_shortest')),
            ('invalid inspection state name', lambda s: s['states'].update({'not a state identifier': s['states']['working']})),
            ('contradictory mount axis', lambda s: s['pump_mount'].update(axis_direction_zero=[0, 0, 1])),
            ('wrong outlet direction', lambda s: s['pump_mount'].update(outlet_direction_zero=[0, 0, -1])),
            ('missing outlet direction', lambda s: s['pump_mount'].pop('outlet_direction_zero')),
            ('missing orientation declaration', lambda s: s['pump_mount'].pop('orientation_status')),
            ('wrong longitudinal reference', lambda s: s['pump_mount'].update(longitudinal_reference='arbitrary offset')),
            ('uninspected reference claimed inspected', lambda s: s['inspiration'].update(inspected=True)),
            ('missing parameter', lambda s: s['parameters'].pop('pitch')),
            ('unknown parameter', lambda s: s['parameters'].update(unknown=s['parameters']['pitch'])),
            ('missing parameter field', lambda s: s['parameters']['pitch'].pop('range')),
            ('unknown parameter field', lambda s: s['parameters']['pitch'].update(unknown=1)),
            ('nonfinite parameter range', lambda s: s['parameters']['pitch'].update(range=[float('nan'), 4])),
            ('boolean parameter range', lambda s: s['parameters']['pitch'].update(range=[True, 4])),
            ('reversed parameter range', lambda s: s['parameters']['pitch'].update(range=[4, 1])),
            ('missing state field', lambda s: s['states']['working'].pop('stroke_fraction')),
            ('unknown state field', lambda s: s['states']['working'].update(unknown=1)),
            ('missing hose design contract', lambda s: s.pop('hose_length_design')),
            ('unknown hose design field', lambda s: s['hose_length_design'].update(unknown=1)),
            ('missing itemized allowances', lambda s: s['hose_length_design'].pop('allowances')),
            ('negative cut allowance', lambda s: s['hose_length_design']['allowances'][0].update(value_mm=-1)),
            ('boolean cut allowance', lambda s: s['hose_length_design']['allowances'][0].update(value_mm=True)),
            ('unexplained cut allowance', lambda s: s['hose_length_design']['allowances'][0].update(reason='')),
            ('duplicate cut allowance id', lambda s: s['hose_length_design']['allowances'].append(copy.deepcopy(s['hose_length_design']['allowances'][0]))),
            ('obsolete unitemized margin', lambda s: s['hose_length_design'].update(margin_mm=10)),
            ('invalid cut resolution', lambda s: s['hose_length_design'].update(cut_resolution_mm=0)),
            ('invalid refinement bounds', lambda s: s['hose_length_design'].update(clearance_minimum_step_mm=s['hose_length_design']['clearance_sample_step_mm']+1)),
            ('boolean hose scan setting', lambda s: s['hose_length_design'].update(scan_max_step_deg=True)),
        ]
        for label, mutate in mutations:
            with self.subTest(source=label), self.assertRaises(ValueError):
                self.load_mutation(mutate)

    def test_clipped_source_rejects_invalid_supports_chain_joint_ownership_and_bounds(self):
        frame_id = next(iter(self.spec['hose_routing']['clips']))
        def frame(source):
            return source['hose_routing']['clips'][frame_id]
        def route(source):
            return source['hose_routing']
        def fixed(source):
            return next(row for row in route(source)['sections'] if row['kind'] == 'fixed_link')
        def flex(source):
            return next(row for row in route(source)['sections'] if row['kind'] == 'joint_loop')
        def swap_crossed_joints(source):
            first, second = [row for row in route(source)['sections'] if row['kind'] == 'joint_loop'][:2]
            for key in ('joint', 'parent_link'):
                first[key], second[key] = second[key], first[key]
        mutations = [
            ('missing framed recipe', lambda s: s.pop('hose_routing')),
            ('unknown framed field', lambda s: route(s).update(unknown=1)),
            ('unknown host link', lambda s: frame(s).update(link='UnknownLink')),
            ('unknown clip host body', lambda s: frame(s).update(host_body='UnknownHost')),
            ('incomplete vector', lambda s: frame(s).update(center_mm=[0, 0])),
            ('boolean coordinate', lambda s: frame(s).update(center_mm=[True, 0, 0])),
            ('nonfinite coordinate', lambda s: frame(s).update(center_mm=[math.nan, 0, 0])),
            ('undefined expression', lambda s: frame(s).update(center_mm=['unknown_dimension', 0, 0])),
            ('zero tangent', lambda s: frame(s).update(tangent=[0, 0, 0])),
            ('scaled tangent', lambda s: frame(s).update(tangent=[0, 0, 2])),
            ('parallel frame axes', lambda s: frame(s).update(x_axis=copy.deepcopy(frame(s)['tangent']))),
            ('missing physical clip', lambda s: route(s)['clips'].pop(frame_id)),
            ('duplicate clip body', lambda s: route(s)['clips']['j3_child'].update(body_id=frame(s)['body_id'])),
            ('unknown mount recipe', lambda s: frame(s)['mount'].update(kind='unknown')),
            ('negative support', lambda s: s['parameters']['hoseClipLength'].update(value=-1)),
            ('duplicate section', lambda s: route(s)['sections'].append(copy.deepcopy(route(s)['sections'][0]))),
            ('reversed chain', lambda s: route(s)['sections'].reverse()),
            ('unknown endpoint', lambda s: route(s)['sections'][0].update(to='unknown_clip')),
            ('rigid section crosses joint', lambda s: fixed(s).update(link='L3_Elbow')),
            ('unknown structural proximity host', lambda s: fixed(s).update(host_bodies=['UnknownHost'])),
            ('unrelated structural proximity host', lambda s: fixed(s).update(host_bodies=['Wrist_yoke_bridge'])),
            ('nonpositive fixed offset bound', lambda s: fixed(s).update(max_offset_mm=0)),
            ('wrong joint owner', lambda s: flex(s).update(parent_link='L6_BareFlange')),
            ('crossings swapped between adjacent links', swap_crossed_joints),
            ('oversized local pocket', lambda s: flex(s).update(max_reach_mm=81)),
            ('reversed axial pocket', lambda s: flex(s).update(axial_range_mm=[2, 1])),
            ('empty candidate family', lambda s: flex(s)['loop_fit'].update(families=[])),
            ('boolean candidate', lambda s: flex(s)['loop_fit'].update(heights_mm=[True])),
            ('nonfinite candidate', lambda s: flex(s)['loop_fit'].update(shifts_mm=[math.inf])),
            ('invalid sampling step', lambda s: route(s).update(sample_step_mm=0)),
            ('retention claimed verified', lambda s: route(s)['qualification'].update(axial_retention_verified=True)),
        ]
        for label, mutate in mutations:
            with self.subTest(source=label), self.assertRaises(ValueError):
                self.load_mutation(mutate)

    def test_tooling_operating_window_is_within_robot_limits_and_narrow_bounds_are_inspected(self):
        arm = model.arm(self.spec)
        windows = self.spec['operating_window_deg']
        self.assertEqual(set(windows), {joint['id'] for joint in arm['joints']})
        self.assertEqual(self.spec['operating_window_status'],
                         'Tooling usage assumption; not robot limits or hardware qualification')
        for index, joint in enumerate(arm['joints']):
            with self.subTest(joint=joint['id']):
                row = windows[joint['id']]
                self.assertEqual(set(row), {'range', 'reason'})
                low, high = row['range']
                self.assertGreaterEqual(low, joint['limits_deg'][0])
                self.assertLessEqual(high, joint['limits_deg'][1])
                self.assertLess(low, high)
                self.assertTrue(row['reason'].strip())
                for state in self.spec['states'].values():
                    self.assertLessEqual(low, state['joints_deg'][index])
                    self.assertLessEqual(state['joints_deg'][index], high)
                values = [state['joints_deg'][index] for state in self.spec['states'].values()]
                for boundary, robot_boundary in zip((low, high), joint['limits_deg']):
                    if boundary != robot_boundary:
                        self.assertTrue(any(abs(value-boundary) < 1e-9 for value in values),
                                        'No static reference at narrowed boundary '+str(boundary))

    def test_operating_window_rejects_missing_bounds_and_states_outside_its_usage_assumption(self):
        mutations = [
            lambda s: s.pop('operating_window_status'),
            lambda s: s.update(operating_window_status='Hardware qualified limits'),
            lambda s: s['operating_window_deg'].pop('J4_ForearmRoll'),
            lambda s: s['operating_window_deg'].update(unknown={'range': [0, 1], 'reason': 'unknown joint'}),
            lambda s: s['operating_window_deg']['J4_ForearmRoll'].update(range=[1, -1]),
            lambda s: s['operating_window_deg']['J4_ForearmRoll'].update(range=[-171, 171]),
            lambda s: s['operating_window_deg']['J4_ForearmRoll'].update(range=[False, 30]),
            lambda s: s['operating_window_deg']['J4_ForearmRoll'].update(reason=''),
            lambda s: s['states']['working']['joints_deg'].__setitem__(3, s['operating_window_deg']['J4_ForearmRoll']['range'][1]+1),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.load_mutation(mutate)
        added = self.load_mutation(lambda s: s['states'].update(extra_boundary=copy.deepcopy(s['states']['working'])))
        self.assertIn('extra_boundary', added['states'])

    def test_normal_pump_states_keep_stroke_reserve_and_hard_ends_require_explicit_reference_flag(self):
        reserve = self.p['strokeReserve']
        self.assertGreater(reserve, 0)
        self.assertLess(2*reserve, self.p['strokeFine'])
        self.assertTrue(self.spec['states']['upright']['hard_end_reference'])
        for name, row in self.spec['states'].items():
            stroke = model.pose(self.spec, self.p, name)['PumpStroke']
            with self.subTest(state=name):
                if row.get('hard_end_reference', False):
                    self.assertIn(stroke, (0, self.p['strokeFine']))
                else:
                    self.assertGreaterEqual(stroke, reserve)
                    self.assertLessEqual(stroke, self.p['strokeFine']-reserve)
        mutations = [lambda s: s['states']['upright'].pop('hard_end_reference'),
                     lambda s: s['states']['working'].update(stroke_fraction=0),
                     lambda s: s['states']['working'].update(stroke_fraction=1),
                     lambda s: s['states']['working'].update(hard_end_reference=True),
                     lambda s: s['parameters']['strokeReserve'].update(value=True)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.load_mutation(mutate)
        wider_reserve = model.parameters(self.spec, {'strokeReserve': 5})
        for name in ('pump_advanced', 'pump_retracted'):
            with self.subTest(overridden_reserve_state=name), self.assertRaises(ValueError):
                model.pose(self.spec, wider_reserve, name)

    def test_switch_flag_fits_both_apertures_and_trigger_planes_follow_reserved_stroke(self):
        for reserve in (.5, 2, 5):
            p = model.parameters(self.spec, {'strokeReserve': reserve})
            source = model.expanded(self.spec, p)
            operations = {row['id']: row['shape'] for row in source['operations']}
            def bounds(shape):
                low = [model.evaluate(value, p) for value in shape['origin']]
                return low, [value+model.evaluate(size, p) for value, size in zip(low, shape['size'])]
            flag_low, flag_high = bounds(operations['CarriageSwitchFlag'])
            _, carriage_high = bounds(operations['CarriageFine'])
            _, advanced_high = bounds(operations['EndstopEnvelopeAdvanced'])
            retracted_low, _ = bounds(operations['EndstopEnvelopeRetracted'])
            with self.subTest(reserve=reserve):
                self.assertAlmostEqual(advanced_high[1], flag_low[1]+reserve)
                self.assertAlmostEqual(retracted_low[1], flag_high[1]+p['strokeFine']-reserve)
                for tag in ('Advanced', 'Retracted'):
                    sensor_low, sensor_high = bounds(operations['EndstopEnvelope'+tag])
                    aperture_low, aperture_high = bounds(operations['EndstopAperture'+tag])
                    self.assertGreater(sensor_low[0], carriage_high[0])
                    self.assertLess(aperture_low[0], sensor_low[0])
                    terminal_low = max(flag_low[0], sensor_low[0])
                    terminal_high = min(flag_high[0], sensor_high[0])
                    self.assertGreater(terminal_high, terminal_low)
                    self.assertGreaterEqual(terminal_low-aperture_low[0], .5-1e-9)
                    self.assertGreaterEqual(aperture_high[0]-terminal_high, .5-1e-9)
                    self.assertGreaterEqual(flag_low[2]-aperture_low[2], .5-1e-9)
                    self.assertGreaterEqual(aperture_high[2]-flag_high[2], .5-1e-9)

    def test_drive_nut_has_a_clearance_seat_while_axial_retention_remains_open(self):
        source = model.expanded(self.spec, self.p)
        operations = {row['id']: row for row in source['operations']}
        pocket = operations['DriveNutSeat']
        self.assertEqual((pocket['action'], pocket['body'], pocket['shape']['kind']),
                         ('cut', 'CarriageFine', 'box'))
        def bounds(operation):
            shape = operation['shape']
            low = [model.evaluate(value, self.p) for value in shape['origin']]
            return low, [value+model.evaluate(size, self.p) for value, size in zip(low, shape['size'])]
        nut_low, nut_high = bounds(operations['DriveNutEnvelope'])
        seat_low, seat_high = bounds(pocket)
        carriage_low, carriage_high = bounds(operations['CarriageFine'])
        for axis in (0, 1, 2):
            with self.subTest(axis=axis):
                self.assertGreaterEqual(nut_low[axis]-seat_low[axis], .2-1e-9)
                self.assertGreaterEqual(seat_high[axis]-nut_high[axis], .2-1e-9)
        for axis in (0, 2):
            self.assertGreater(seat_low[axis], carriage_low[axis])
            self.assertLess(seat_high[axis], carriage_high[axis])
        self.assertGreater(seat_low[1], carriage_low[1])
        self.assertGreater(seat_high[1], carriage_high[1])
        self.assertAlmostEqual(nut_high[1], carriage_high[1])
        self.assertIn('drive_nut_retention_method', self.spec['open_requirements'])
        self.assertIsNone(self.spec['open_requirements']['drive_nut_retention_method'])

    def test_air_budget_counts_inserted_tube_and_floor_bores_once_and_excludes_ambient_tip_relief(self):
        for engagement in (5, 8, 12):
            p = model.parameters(self.spec, {'tipEngagementLength': engagement})
            shapes = {row['id']: row['shape'] for row in model.expanded(self.spec, p)['operations']}
            value = lambda expression: model.evaluate(expression, p)
            interior, tip, shaft = (shapes[key] for key in ('DisposableTip_Interior', 'DisposableTip', 'TipShaft'))
            floor, side, collar = (shapes[key] for key in ('TipSidePort_Bore', 'HeadCollar_SideAir', 'HeadCollar'))
            axial, shaft_air = shapes['HeadCollar_Air'], shapes['TipShaft_Air']
            small, large = value(floor['radius']), value(axial['radius'])
            bottom = value(tip['origin'][2])
            top = bottom+value(tip['height'])
            seal_z = value(shaft['origin'][2])
            slope = (value(interior['top_radius'])-value(interior['radius']))/value(interior['height'])
            inner_at = lambda z: value(interior['radius'])+slope*(z-value(interior['origin'][2]))
            frustum = lambda length, a, b: math.pi*length*(a*a+a*b+b*b)/3
            cavity = frustum(seal_z-bottom, inner_at(bottom), inner_at(seal_z))
            relief = (frustum(top-seal_z, inner_at(seal_z), inner_at(top))
                      -frustum(top-seal_z, value(shaft['radius']), value(shaft['top_radius'])))
            start = value(floor['origin'][0])
            end = min(value(side['origin'][0])+value(side['height']),
                      value(collar['origin'][0])+value(collar['radius']))
            centre = value(axial['origin'][0])
            # Independent Gauss-Chebyshev integration of the crossing bores.
            nodes = 64
            half_overlap = 2*small**2*math.pi/(nodes+1)*sum(
                math.sin(k*math.pi/(nodes+1))**2 *
                math.sqrt(large**2-small**2*math.cos(k*math.pi/(nodes+1))**2)
                for k in range(1, nodes+1))
            side_volume = (end-start)*math.pi*small**2-2*half_overlap
            blind_volume = side_volume-((centre-start)*math.pi*small**2-half_overlap)
            central = math.pi*large**2*(value(axial['height'])+value(shaft_air['height']))
            air = model.air_volumes(self.spec, p, p['strokeFine']/2)
            with self.subTest(engagement=engagement):
                self.assertAlmostEqual(blind_volume, .0412115373, places=9)
                self.assertAlmostEqual(air['head'], central+cavity+side_volume, places=8)
                self.assertAlmostEqual(air['unpressurized_tip_relief_air_ul'], relief, places=8)
                self.assertGreater(relief, 0)
                self.assertAlmostEqual(air['tube'], math.pi*small**2*p['hoseLength'], places=7)
                through = value(shapes['PumpHoseBarb_Bore']['height'])
                self.assertAlmostEqual(air['fittings'], math.pi*p['pipeBore']**2*32+math.pi*small**2*through, places=8)
                self.assertAlmostEqual(air['total'], sum(air[key] for key in ('syringe', 'fittings', 'tube', 'head')), places=7)
                recipe = {row['id']: row for row in model.air_path_recipe(self.spec, p, p['strokeFine']/2)}
                self.assertEqual(set(recipe), {'SyringeAir', 'CoreFittingAir', 'PumpFloorAir', 'HeadBoreAir', 'HeadSideAir', 'TipCavityAir'})
                self.assertEqual(recipe['TipCavityAir']['component'], 'ConsumableTip')
                self.assertAlmostEqual(recipe['TipCavityAir']['shape']['height'], seal_z-bottom)
                self.assertAlmostEqual(recipe['TipCavityAir']['shape']['top_radius'], inner_at(seal_z))
                self.assertEqual(recipe['PumpFloorAir']['shape']['origin'], [value(v) for v in shapes['PumpHoseBarb_Bore']['origin']])
                self.assertEqual(recipe['HeadSideAir']['shape']['origin'], [value(v) for v in side['origin']])
                self.assertAlmostEqual(recipe['HeadBoreAir']['shape']['height'], value(axial['height'])+value(shaft_air['height']))

    def test_hose_joint_crossings_and_enclosed_air_volume_are_geometric_diagnostics(self):
        witness = {'values': [1., 2.], 'qualified': False}
        rounded = {'values': [1.+1e-13, 2.], 'qualified': False}
        agreement = builder.compare_derived_metrics(witness, rounded)
        self.assertTrue(agreement['passed'])
        self.assertGreater(agreement['maximum_absolute_numeric_difference'], 0)
        self.assertGreater(agreement['numeric_values_compared'], 0)
        wrong_metrics = [{}, {**witness, 'unexpected': 1}, {'values': [1.], 'qualified': False},
                         {'values': [float('nan'), 2.], 'qualified': False},
                         {'values': [1.01, 2.], 'qualified': False},
                         {'values': [1., 2.], 'qualified': 0}]
        for changed in wrong_metrics:
            with self.subTest(changed_metrics=changed):
                failed = builder.compare_derived_metrics(witness, changed)
                self.assertFalse(failed['passed'])
                self.assertTrue(failed['mismatches'])
        arm = model.arm(self.spec)
        parameters = robot.parameters(arm)
        crossing_ids = {joint['id'] for joint in arm['joints'][2:]}
        for name in self.spec['states']:
            state = self.observed_state(name)
            frames = robot.forward(arm, state['joints_deg'])
            metrics = state['metrics']
            crossings = metrics['hose_crossings']
            self.assertEqual(set(crossings), crossing_ids)
            for joint in arm['joints'][2:]:
                with self.subTest(state=name, crossing=joint['id']):
                    crossing = crossings[joint['id']]
                    origin = [model.evaluate(v, parameters) for v in joint['frame']['origin']]
                    point = robot.transform(frames[joint['parent']], origin)
                    end = robot.transform(frames[joint['parent']], [a+b for a, b in zip(origin, joint['frame']['axis'])])
                    direction = [b-a for a, b in zip(point, end)]
                    self.assertLess(math.dist(crossing['axis_point_mm'], point), 1e-8)
                    self.assertLess(math.dist(crossing['axis_direction'], direction), 1e-8)
                    waypoint = crossing['waypoint_mm']
                    self.assertLess(min(math.dist(waypoint, control) for control in state['hose_path']['controls_mm']), 1e-8)
                    offset = [a-b for a, b in zip(waypoint, point)]
                    along = sum(a*b for a, b in zip(offset, direction))/sum(v*v for v in direction)
                    expected = math.sqrt(sum((a-along*b)**2 for a, b in zip(offset, direction)))
                    self.assertAlmostEqual(crossing['distance_to_axis_mm'], expected, places=7)
            air = metrics['enclosed_air_volume_ul']
            volumes = [air[part] for part in ('syringe', 'fittings', 'tube', 'head')]
            self.assertTrue(all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in volumes))
            self.assertAlmostEqual(air['total'], sum(volumes), places=7)
            self.assertAlmostEqual(air['tube'], math.pi*self.p['hoseInnerRadius']**2*self.p['hoseLength'], places=6)
            self.assertTrue(air['scope'])
            self.assertTrue(air['assumptions'])
            self.assertIsNone(state['actual_dispensed_volume_ul'])

    def test_intentional_contacts_include_socket_floors_and_the_separate_tip_seal(self):
        contacts = model.allowed_contacts(self.spec, self.p)
        pairs = [frozenset((row['a'], row['b'])) for row in contacts]
        self.assertEqual(len(pairs), len(CONTACT_PAIRS))
        self.assertEqual(set(pairs), CONTACT_PAIRS)
        self.assertTrue(all(row['reason'].strip() for row in contacts))

    def test_lead_changes_motor_rotation_without_changing_stroke_or_nominal_volume(self):
        slower_lead = model.parameters(self.spec, {'pitch': 1})
        faster_lead = model.parameters(self.spec, {'pitch': 4})
        for name in self.spec['states']:
            first = model.pose(self.spec, slower_lead, name)
            second = model.pose(self.spec, faster_lead, name)
            self.assertEqual(first['PumpStroke'], second['PumpStroke'])
            self.assertAlmostEqual(first['MotorRotation'], 4*second['MotorRotation'])
            self.assertEqual(first['IsolationValve'], second['IsolationValve'])
        self.assertAlmostEqual(math.pi*self.p['radiusFine']**2*self.p['strokeFine'], 1000)

    def test_actuator_states_obey_coupling_and_reject_outside_joint_limits(self):
        source = model.expanded(self.spec, self.p)
        for row in model.samples(self.spec, self.p):
            q = row['joint_values']
            model.validate_pose(source, q)
            self.assertAlmostEqual(q['MotorRotation']*self.p['pitch']/360, q['PumpStroke'])
        q = model.pose(self.spec, self.p)
        for key, value in [('PumpStroke', -1), ('PumpStroke', math.nextafter(self.p['strokeFine'], math.inf)),
                           ('MotorRotation', float('nan')), ('IsolationValve', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                model.validate_pose(source, {**q, key: value})
        with self.assertRaises(ValueError):
            model.validate_pose(source, {})

    def test_fixed_groups_follow_their_source_links_without_reapplying_joint_origins(self):
        arm = model.arm(self.spec)
        mounts = model.mounts(self.spec, self.p)
        for name in ('upright', 'working', 'extended'):
            state = self.observed_state(name)
            links = robot.forward(arm, state['joints_deg'])
            for group, mounting in mounts.items():
                with self.subTest(state=name, group=group):
                    expected = robot.multiply(links[mounting['link']], mounting['zero_transform'])
                    self.assert_matrix_close(state['part_matrices'][group], expected)

    def test_physical_mount_witnesses_agree_with_the_arm_flange_and_outboard_axis(self):
        source = model.expanded(self.spec, self.p)
        shapes = {row['body']: row['shape'] for row in source['operations'] if row['action'] == 'create'}
        mounts = model.mounts(self.spec, self.p)
        barrel = shapes['GlassFine']
        centre = robot.transform(mounts['PumpFrame']['zero_transform'],
                                 [model.evaluate(v, self.p) for v in barrel['origin']])
        self.assertAlmostEqual(centre[0], -self.p['outboard'])
        self.assertAlmostEqual(centre[1], 0)
        pump_axis = [mounts['PumpFrame']['zero_transform'][i][1] for i in range(3)]
        self.assertEqual(pump_axis, self.spec['pump_mount']['axis_direction_zero'])
        self.assertEqual(pump_axis, [0, 0, -1])
        self.assertEqual(self.spec['pump_mount']['outlet_direction_zero'], [0, 0, 1])
        rotation = mounts['PumpFrame']['zero_transform']
        columns = [[rotation[i][j] for i in range(3)] for j in range(3)]
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(sum(a*b for a, b in zip(columns[i], columns[j])), int(i == j))
        cross = [columns[1][1]*columns[2][2]-columns[1][2]*columns[2][1],
                 columns[1][2]*columns[2][0]-columns[1][0]*columns[2][2],
                 columns[1][0]*columns[2][1]-columns[1][1]*columns[2][0]]
        self.assertAlmostEqual(sum(a*b for a, b in zip(columns[0], cross)), 1)
        pad = shapes['TipFlangePad']
        far_face = [model.evaluate(v, self.p) for v in pad['origin']]
        far_face = [v+a*pad['height'] for v, a in zip(far_face, pad['axis'])]
        actual = robot.transform(mounts['WristHead']['zero_transform'], far_face)
        arm = model.arm(self.spec)
        ap = robot.parameters(arm)
        anchor_z = ap['shoulder_z']+self.spec['pump_mount']['shoulder_offset_mm']
        plate_start = [model.evaluate(value, self.p) for value in shapes['SinglePumpPlate']['origin']]
        plate_end = list(plate_start)
        plate_end[1] += model.evaluate(shapes['SinglePumpPlate']['size'][1], self.p)
        pump_mount = mounts['PumpFrame']['zero_transform']
        self.assertAlmostEqual(robot.transform(pump_mount, plate_start)[2], anchor_z+plate_end[1])
        self.assertAlmostEqual(robot.transform(pump_mount, plate_end)[2], anchor_z+plate_start[1])
        flange_face = [model.evaluate(v, ap) for v in arm['flange_reference']['point']]
        self.assertLess(math.dist(actual, flange_face), 1e-10)

    def test_piston_motion_changes_only_the_carriage_relative_to_the_fixed_mounts(self):
        before, after = (self.observed_state(name) for name in ('pump_advanced', 'pump_retracted'))
        self.assertEqual(before['joints_deg'], after['joints_deg'])
        for group in ('PumpFrame', 'WristHead', 'ArmBracket', 'PumpValve'):
            self.assert_matrix_close(before['part_matrices'][group], after['part_matrices'][group])
        a = robot.transform(before['part_matrices']['PumpCarriage'], [0, 0, 0])
        b = robot.transform(after['part_matrices']['PumpCarriage'], [0, 0, 0])
        distance = after['stroke_mm']-before['stroke_mm']
        frame = before['part_matrices']['PumpFrame']
        expected = [frame[i][1]*distance for i in range(3)]
        self.assertLess(math.dist([y-x for x, y in zip(a, b)], expected), 1e-9)

    def test_tip_tcp_is_derived_from_the_separate_consumable_under_wrist_motion(self):
        source = model.expanded(self.spec, self.p)
        tip = next(row['shape'] for row in source['operations']
                   if row['action'] == 'create' and row['body'] == 'DisposableTip')
        local = [model.evaluate(value, self.p) for value in tip['origin']]
        self.assertEqual(tip['axis'], [0, 0, 1])
        self.assertLess(math.dist(model.tip_seat(self.spec, self.p)['tip_tcp_mm'], local), 1e-10)
        for name in ('upright', 'working', 'extended'):
            state = self.observed_state(name)
            expected = robot.transform(state['part_matrices']['ConsumableTip'], local)
            self.assertLess(math.dist(state['tip_tcp_mm'], expected), 1e-10)
            self.assert_matrix_close(state['part_matrices']['ConsumableTip'], state['part_matrices']['WristHead'])
        self.assertGreater(math.dist(self.observed_state('upright')['tip_tcp_mm'],
                                     self.observed_state('working')['tip_tcp_mm']), 100)

    def test_hose_material_ends_bottom_on_socket_floors_and_keep_required_straight_lengths(self):
        source = model.expanded(self.spec, self.p)
        operations = {row['id']: row['shape'] for row in source['operations']}
        local = model.connection_interfaces(self.spec, self.p)
        for name in self.spec['states']:
            state = self.observed_state(name)
            world = model.connection_interfaces(self.spec, self.p, state['part_matrices'])
            path = state['hose_path']
            for key, endpoint, segments in (('pump', path['segments'][0]['start_mm'], path['segments']),
                                             ('tip', path['segments'][-1]['end_mm'], list(reversed(path['segments'])))):
                interface = local[key]
                floor = [model.evaluate(v, self.p) for v in operations[interface['body']+'_Bore']['origin']]
                matrix = state['part_matrices'][interface['component']]
                with self.subTest(state=name, interface=key):
                    self.assertLess(math.dist(endpoint, robot.transform(matrix, floor)), 1e-9)
                    self.assertLess(math.dist(endpoint, world[key]['material_end_mm']), 1e-9)
                    outward = world[key]['outward']
                    straight = 0.
                    for segment in segments:
                        if segment['kind'] != 'line':
                            break
                        a, b = segment['start_mm'], segment['end_mm']
                        if key == 'tip':
                            a, b = b, a
                        distance = math.dist(a, b)
                        if distance == 0:
                            continue
                        tangent = [(end-start)/distance for start, end in zip(a, b)]
                        if math.dist(tangent, outward) > 1e-9:
                            break
                        straight += distance
                    required = self.p['hoseInsertionDepth']+self.p['strainReliefLength']+self.p['connectorStraightLead']
                    self.assertGreaterEqual(straight, required-1e-8)
                    for point in world[key]['floor_witness_points_mm']:
                        delta = [a-b for a, b in zip(point, endpoint)]
                        self.assertAlmostEqual(sum(a*b for a, b in zip(delta, outward)), 0, places=8)
            pump_tangent = world['pump']['outward']
            link = robot.forward(model.arm(self.spec), state['joints_deg'])['L2_UpperArm']
            self.assertLess(math.dist(pump_tangent, [link[i][2] for i in range(3)]), 1e-9)

    def test_one_tube_cut_length_is_preserved_across_all_named_configurations(self):
        for name in self.spec['states']:
            state = self.observed_state(name)
            path = state['hose_path']
            metrics = hose.diagnostics(path, state['hose_inner_radius_mm'], state['hose_outer_radius_mm'])
            self.assertAlmostEqual(metrics['length_mm'], self.p['hoseLength'], places=6)
            self.assertAlmostEqual(metrics['air_volume_ul'], math.pi*self.p['hoseInnerRadius']**2*self.p['hoseLength'], places=6)
            self.assertGreaterEqual(metrics['min_bend_radius_mm'], 12-1e-8)
            self.assertIsNone(state['carrier'])
            self.assertNotIn('carrier_path', path)
            self.assertEqual(path['routing_format'], joint_routing.FORMAT)
            self.assertIsNone(state['hose_slack_parameter_mm'])
            self.assertEqual(len(path['clip_material_stations_mm']), 7)
            self.assertTrue(all(segment['radius_mm'] >= 12-1e-8 for segment in path['segments']
                                if segment['kind'] == 'arc'))
            self.assertFalse(path['qualified'])
            self.assertTrue(state['hose_self_clearance']['passed'])
            self.assertIs(state['hose_self_clearance']['continuous_self_clearance_verified'], False)
            for first, second in zip(path['segments'], path['segments'][1:]):
                self.assertLess(math.dist(first['end_mm'], second['start_mm']), 1e-9)

    def test_sectioned_design_itemizes_the_cut_and_retains_fixed_material_in_every_required_state(self):
        band = model.named_length_band(self.spec, self.p)
        self.assertEqual(band['format'], joint_routing.PROOF_FORMAT)
        self.assertTrue(band['passed'])
        self.assertEqual(band['status'], 'demonstrated')
        self.assertEqual(set(band['states']), set(self.spec['states']))
        self.assertFalse(band['failures'])
        self.assertTrue(band['scope'])
        self.assertTrue(all(value is False for value in band['qualification'].values()))
        self.assertTrue(band['source_files_sha256'])
        for name, checksum in band['source_files_sha256'].items():
            self.assertEqual(model.digest(ROOT/name), checksum)
        selection = band['cut_selection']
        allowances = self.spec['hose_length_design']['allowances']
        self.assertEqual(selection['allowances'], allowances)
        self.assertEqual(len({row['id'] for row in allowances}), len(allowances))
        self.assertTrue(all(type(row['value_mm']) in (int, float)
                            and math.isfinite(row['value_mm']) and row['value_mm'] >= 0
                            and row['reason'].strip() for row in allowances))
        section_ids = {row['id'] for row in self.spec['hose_routing']['sections']}
        self.assertEqual(set(band['section_lengths_mm']), section_ids)
        self.assertEqual(set(band['base_section_lengths_mm']), section_ids)
        supported = (2*(self.p['hoseInsertionDepth']+self.p['strainReliefLength']+self.p['connectorStraightLead'])
                     +len(self.spec['hose_routing']['clips'])*self.p['hoseClipLength'])
        base_total = math.fsum(band['base_section_lengths_mm'].values())+supported
        itemized = sum(row['value_mm'] for row in allowances)
        resolution = self.spec['hose_length_design']['cut_resolution_mm']
        expected_cut = math.ceil((base_total+itemized-1e-9)/resolution)*resolution
        self.assertAlmostEqual(selection['base_physical_length_mm'], base_total)
        self.assertAlmostEqual(selection['allowance_total_mm'], itemized)
        self.assertAlmostEqual(selection['rounding_mm'], expected_cut-base_total-itemized)
        self.assertGreaterEqual(selection['rounding_mm'], -1e-9)
        self.assertLess(selection['rounding_mm'], resolution+1e-9)
        self.assertAlmostEqual(selection['selected_cut_mm'], expected_cut)
        self.assertAlmostEqual(selection['selected_cut_mm'], self.p['hoseLength'])
        self.assertAlmostEqual(band['hose_length_mm'], expected_cut)
        allocation = selection['allocation_section']
        self.assertIn(allocation, {row['id'] for row in self.spec['hose_routing']['sections']
                                   if row['kind'] == 'joint_loop'})
        self.assertAlmostEqual(selection['allocated_extra_mm'], itemized+selection['rounding_mm'])
        for section in section_ids:
            extra = selection['allocated_extra_mm'] if section == allocation else 0
            self.assertAlmostEqual(band['section_lengths_mm'][section], band['base_section_lengths_mm'][section]+extra)
        self.assertAlmostEqual(math.fsum(band['section_lengths_mm'].values())+supported, expected_cut)
        self.assertEqual(set(band['clip_material_stations_mm']), set(self.spec['hose_routing']['clips']))
        for name, selected in band['states'].items():
            with self.subTest(state=name):
                self.assertTrue(selected['passed'])
                self.assertEqual(selected['joints_deg'], self.spec['states'][name]['joints_deg'])
                self.assertTrue(selected['checks']['passed'])
                for field in ('self_clearance', 'external_clearance', 'proximity'):
                    self.assertTrue(selected['checks'][field]['passed'])
                for section in self.spec['hose_routing']['sections']:
                    if section['kind'] != 'joint_loop':continue
                    local = selected['sections'][section['id']]['checks']
                    self.assertTrue(local['passed'])
                    self.assertTrue(local['self_clearance']['passed'])
                    self.assertTrue(local['adjacent_support_self_clearance']['passed'])
                    self.assertIs(local['adjacent_support_self_clearance']['screening_probe_only'], True)
                    reservation = local['clip_outer_wall_keepouts']
                    self.assertTrue(reservation['passed'])
                    self.assertAlmostEqual(reservation['required_radial_clearance_mm'],
                        2*self.p['hoseOuterRadius']+self.p['clipHoseGap']+self.p['clipWall'])
                    self.assertEqual(set(reservation['clips']),
                        set(self.spec['hose_routing']['clips']) & {section['from'], section['to']})
                    self.assertTrue(all(row['passed'] for row in reservation['clips'].values()))
                path = selected['path']
                self.assertAlmostEqual(path['length_mm'], expected_cut, places=6)
                self.assertAlmostEqual(path['length_accounting']['total_mm'], expected_cut, places=6)
                self.assertTrue(joint_routing.validate_material_path(path, self.p, band)['passed'])
                self.assertTrue(builder.compare_derived_metrics(path['clip_material_stations_mm'],
                    band['clip_material_stations_mm'], tolerance=1e-7)['passed'])
                observed = self.observed_state(name)
                self.assertTrue(observed['source_clearance']['passed'])
                self.assertTrue(observed['hose_proximity']['passed'])
                self.assertEqual(observed['length_accounting'], observed['hose_path']['length_accounting'])
                self.assertIsNone(observed['hose_slack_parameter_mm'])

    def test_material_regions_partition_actual_segments_and_count_both_insertions_once(self):
        categories = {'inserted': 'inserted_mm', 'socket_strain_relief': 'socket_strain_relief_mm',
                      'connector_straight_lead': 'connector_straight_leads_mm',
                      'clip_straight': 'clip_supported_mm', 'nominal_carrier': 'carrier_supported_mm',
                      'bare_span': 'free_bare_spans_mm'}
        for name in self.spec['states']:
            path = self.observed_state(name)['hose_path']
            account = path['length_accounting']
            parts = account['parts']
            sums = {key: 0. for key in categories.values()}
            cursor = 0
            with self.subTest(state=name):
                self.assertEqual(len({part['id'] for part in parts}), len(parts))
                for part in parts:
                    self.assertIn(part['kind'], categories)
                    self.assertEqual(part['segment_start_index'], cursor)
                    self.assertIs(type(part['segment_count']), int)
                    self.assertGreater(part['segment_count'], 0)
                    segments = path['segments'][cursor:cursor+part['segment_count']]
                    self.assertEqual(len(segments), part['segment_count'])
                    measured = sum(math.dist(segment['start_mm'], segment['end_mm'])
                                   if segment['kind'] == 'line'
                                   else segment['radius_mm']*segment['sweep_rad']
                                   for segment in segments)
                    self.assertAlmostEqual(part['length_mm'], measured, places=7)
                    sums[categories[part['kind']]] += measured
                    cursor += part['segment_count']
                self.assertEqual(cursor, len(path['segments']))
                for field, measured in sums.items():
                    self.assertAlmostEqual(account[field], measured, places=7)
                self.assertAlmostEqual(sums['inserted_mm'], 2*self.p['hoseInsertionDepth'], places=7)
                self.assertAlmostEqual(sums['socket_strain_relief_mm'], 2*self.p['strainReliefLength'], places=7)
                self.assertAlmostEqual(sums['connector_straight_leads_mm'], 2*self.p['connectorStraightLead'], places=7)
                for kind in ('inserted', 'socket_strain_relief', 'connector_straight_lead'):
                    self.assertEqual(sum(part['kind'] == kind for part in parts), 2)
                self.assertEqual(sums['carrier_supported_mm'], 0.)
                self.assertNotIn('carrier_path', path)
                self.assertEqual(sum(part['kind'] == 'clip_straight' for part in parts), 7)
                self.assertAlmostEqual(sums['clip_supported_mm'], 7*self.p['hoseClipLength'])
                self.assertAlmostEqual(sum(sums.values()), self.p['hoseLength'], places=6)
                self.assertAlmostEqual(account['total_mm'], self.p['hoseLength'], places=6)
                self.assertAlmostEqual(account['total_mm'], path['length_mm'], places=7)
                self.assertLess(abs(account['sum_error_mm']), 1e-7)

    def test_geometric_displacement_does_not_claim_a_measured_dose_or_real_performance(self):
        self.assertTrue(self.spec['qualification'])
        self.assertTrue(all(type(value) is bool and not value for value in self.spec['qualification'].values()))
        self.assertTrue(all(value is None for value in self.spec['open_requirements'].values()))
        for name, row in self.spec['states'].items():
            state = self.observed_state(name)
            self.assertAlmostEqual(state['theoretical_displacement_ul'], 1000*row['stroke_fraction'])
            self.assertIsNone(state['actual_dispensed_volume_ul'])
        with self.assertRaises(ValueError):
            self.load_mutation(lambda s: s['qualification'].update(dosing_accuracy_verified=True))
        with self.assertRaises(ValueError):
            self.load_mutation(lambda s: s['open_requirements'].update(permitted_dose_error_ul=0))

    def test_schema_rejects_omitted_qualifications_and_unimplemented_fields(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('Install the locked schema test dependencies')
        schema_path = ROOT/'model/arm-syringe.schema.json'
        if not schema_path.exists():
            self.skipTest('Arm-syringe schema not yet created')
        schema = json.loads(schema_path.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(self.raw)
        mutations = [lambda s: s.update(nominal_capacity_ul=10000),
                     lambda s: s.update(unimplemented_tool_changer=True),
                     lambda s: s['qualification'].pop('dosing_accuracy_verified'),
                     lambda s: s['open_requirements'].update(permitted_leak_rate_ul_s=0),
                     lambda s: s['operating_window_deg'].pop('J4_ForearmRoll'),
                     lambda s: s['operating_window_deg']['J4_ForearmRoll'].update(reason=''),
                     lambda s: s['states']['working'].update(hard_end_reference=True),
                     lambda s: s['states']['working'].update(unknown=1)]
        for mutate in mutations:
            changed = copy.deepcopy(self.raw);mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(jsonschema.ValidationError):
                validator.validate(changed)
        added = copy.deepcopy(self.raw)
        added['states']['extra_boundary'] = copy.deepcopy(added['states']['working'])
        validator.validate(added)


class ArmSyringeNativeEvidenceTests(unittest.TestCase):
    def assert_native_contact_on_plane(self, contact, center, normal, inner_radius, outer_radius):
        self.assertTrue(contact['passed'])
        self.assertLessEqual(contact['distance_mm'], 1e-7)
        self.assertLessEqual(contact['overlap_mm3'], 1e-5)
        self.assertLessEqual(contact['contact_plane_extent_mm'], 1e-7)
        self.assertTrue(contact['native_contact_points_mm'])
        for point in contact['native_contact_points_mm']:
            delta = [a-b for a, b in zip(point, center)]
            along = sum(a*b for a, b in zip(delta, normal))
            radius = math.sqrt(sum((a-along*b)**2 for a, b in zip(delta, normal)))
            self.assertLessEqual(abs(along), 1e-7)
            self.assertGreaterEqual(radius, inner_radius-1e-6)
            self.assertLessEqual(radius, outer_radius+1e-6)
        for rejected in contact['rejected_inconsistent_native_points']:
            self.assertGreater(max(rejected['distance_to_a_mm'], rejected['distance_to_b_mm']), 1e-7)

    def assert_clipped_native_geometry(self, row, native, spec, p, design):
        checked = native['clip_checks'];path = row['state']['hose_path']
        self.assertTrue(checked['passed'])
        self.assertEqual(set(checked['supports']), set(spec['hose_routing']['clips']))
        self.assertTrue(all(value is False for value in checked['qualification'].values()))
        self.assertTrue(builder.compare_derived_metrics(checked['material_stations_mm'],
            design['clip_material_stations_mm'], tolerance=1e-7)['passed'])
        self.assertTrue(builder.compare_derived_metrics(checked['section_lengths_mm'],
            design['section_lengths_mm'], tolerance=1e-7)['passed'])
        for name, support in checked['supports'].items():
            source = spec['hose_routing']['clips'][name]
            self.assertTrue(support['passed'])
            self.assertEqual(support['clip_body'], source['body_id'])
            self.assertEqual(support['host_body'], source['host_body'])
            self.assertEqual(support['attachment_link'], source['link'])
            self.assertLessEqual(support['frame_error_mm'], 1e-7)
            self.assertAlmostEqual(support['physical_support_length_mm'], p['hoseClipLength'])
            self.assertAlmostEqual(support['required_hose_gap_mm'], p['clipHoseGap'])
            self.assertAlmostEqual(support['required_host_gap_mm'], p['mountGap'])
            self.assertAlmostEqual(support['material_station_mm'], design['clip_material_stations_mm'][name], places=6)
            self.assertLess(math.dist(support['center_mm'], path['clip_frames'][name]['center_mm']), 1e-7)
            self.assertTrue(all(value is False for value in support['qualification'].values()))
            self.assertEqual(set(support['overlap_volume_mm3']), {'hose_mm3', 'host_mm3'})
            self.assertTrue(all(value <= 1e-5 for value in support['overlap_volume_mm3'].values()))
            self.assertGreaterEqual(len(support['bore_witnesses']), 12)
            for witness in support['bore_witnesses']:
                self.assertLessEqual(witness['hose_membership_error_mm'], 1e-6)
                self.assertLessEqual(witness['clip_membership_error_mm'], 1e-6)
                self.assertGreater(witness['native_radial_gap_mm'], 0)
                self.assertAlmostEqual(witness['native_radial_gap_mm'], p['clipHoseGap'], places=6)
            self.assertTrue(support['host_witnesses'])
            for witness in support['host_witnesses']:
                self.assertLessEqual(witness['host_membership_error_mm'], 1e-6)
                self.assertGreater(witness['native_clamp_gap_mm'], 0)
                self.assertAlmostEqual(witness['native_clamp_gap_mm'], p['mountGap'], places=6)

        definitions = {section['id']: section for section in spec['hose_routing']['sections']}
        records = {section['id']: section for section in path['section_records']}
        self.assertEqual(set(checked['fixed_sections']),
                         {name for name, section in definitions.items() if section['kind'] == 'fixed_link'})
        self.assertEqual(set(checked['joint_loops']),
                         {name for name, section in definitions.items() if section['kind'] == 'joint_loop'})
        for name, section in checked['fixed_sections'].items():
            self.assertTrue(section['passed'])
            self.assertEqual(section['host_bodies'], definitions[name]['host_bodies'])
            self.assertEqual(section['maximum_allowed_distance_mm'], definitions[name]['max_offset_mm'])
            self.assertEqual(section['sample_count'], len(section['witnesses']))
            self.assertGreaterEqual(section['sample_count'], 2)
            self.assertLessEqual(section['maximum_arclength_gap_mm'], 2.)
            self.assertAlmostEqual(section['maximum_arclength_gap_mm']*(section['sample_count']-1),
                                   records[name]['actual_length_mm'], places=6)
            maximum = max(witness['distance_mm'] for witness in section['witnesses'])
            self.assertAlmostEqual(section['maximum_sampled_distance_mm'], maximum, places=7)
            self.assertAlmostEqual(section['maximum_distance_upper_bound_mm'],
                                   maximum+section['maximum_arclength_gap_mm']/2, places=7)
            self.assertLessEqual(section['maximum_distance_upper_bound_mm'], definitions[name]['max_offset_mm']+1e-7)
            offset = sum(segment['length_mm'] for segment in path['segments'][:records[name]['segment_start_index']])
            for i, witness in enumerate(section['witnesses']):
                point = carrier.path_position(path, offset+i*section['maximum_arclength_gap_mm'])['point_mm']
                self.assertLess(math.dist(witness['point_mm'], point), 1e-7)
                self.assertIn(witness['host_body'], definitions[name]['host_bodies'])
                self.assertLessEqual(witness['witness_membership_error_mm'], 1e-7)
                self.assertAlmostEqual(math.dist(witness['point_mm'], witness['nearest_host_point_mm']),
                                       witness['distance_mm'], places=7)
                self.assertAlmostEqual(witness['native_distance_mm'], witness['distance_mm'], places=7)

        arm = model.arm(spec);arm_parameters = robot.parameters(arm)
        fk = robot.forward(arm, row['state']['joints_deg'])
        for name, section in checked['joint_loops'].items():
            definition = definitions[name]
            joint = next(joint for joint in arm['joints'] if joint['id'] == definition['joint'])
            self.assertTrue(section['passed'])
            self.assertEqual(section['joint'], joint['id'])
            self.assertEqual(section['maximum_radial_reach_mm'], definition['max_reach_mm'])
            self.assertEqual(section['allowed_axial_range_mm'], definition['axial_range_mm'])
            origin = robot.transform(fk[joint['parent']], [model.evaluate(v, arm_parameters) for v in joint['frame']['origin']])
            axis = [sum(fk[joint['parent']][i][j]*model.evaluate(joint['frame']['axis'][j], arm_parameters)
                        for j in range(3)) for i in range(3)]
            self.assertLess(math.dist(section['joint_origin_mm'], origin), 1e-7)
            self.assertLess(math.dist(section['joint_axis'], axis), 1e-7)
            self.assertGreaterEqual(section['sample_count'], 2)
            self.assertLessEqual(section['maximum_arclength_gap_mm'], 2.)
            self.assertAlmostEqual(section['maximum_arclength_gap_mm']*(section['sample_count']-1),
                                   records[name]['actual_length_mm'], places=6)
            offset = sum(segment['length_mm'] for segment in path['segments'][:records[name]['segment_start_index']])
            radial, axial = [], []
            for i in range(section['sample_count']):
                point = carrier.path_position(path, offset+i*section['maximum_arclength_gap_mm'])['point_mm']
                delta = [value-start for value, start in zip(point, origin)]
                projection = sum(a*b for a, b in zip(delta, axis))
                axial.append(projection)
                radial.append(math.sqrt(max(0., sum(v*v for v in delta)-projection**2)))
            half = section['maximum_arclength_gap_mm']/2
            self.assertAlmostEqual(section['maximum_sampled_radial_distance_mm'], max(radial), places=7)
            self.assertAlmostEqual(section['radial_distance_upper_bound_mm'], max(radial)+half, places=7)
            self.assertLessEqual(section['radial_distance_upper_bound_mm'], definition['max_reach_mm']+1e-7)
            expected_axial = [min(axial)-half, max(axial)+half]
            for actual, expected in zip(section['axial_range_bounds_mm'], expected_axial):
                self.assertAlmostEqual(actual, expected, places=7)
            self.assertLessEqual(definition['axial_range_mm'][0], expected_axial[0]+1e-7)
            self.assertGreaterEqual(definition['axial_range_mm'][1], expected_axial[1]-1e-7)

    def test_complete_both_cad_proof_retains_current_sources_geometry_and_qualifications(self):
        path = ROOT/'cad/arm-syringe/shared-build-report.json'
        if not path.exists():
            self.skipTest('Build all current arm-syringe inspection states in both CAD systems')
        report = json.loads(path.read_text())
        spec = model.load()
        if report.get('source_sha256') != model.digest(model.SOURCE):
            self.skipTest('Only a previous-revision native proof is available; build current interfaces in both CAD systems')
        state_names = {row['id'] for row in report.get('states', [])}
        if report.get('backends') != 'both' or state_names != set(spec['states']):
            self.skipTest('Only an interim or single-backend proof is available; full both-CAD proof required')
        self.assertEqual(report['format'], 'solidcraftbot.arm-syringe-build/1')
        self.assertTrue(report['passed'])
        self.assertEqual(report['source'], str(model.SOURCE.relative_to(ROOT)))
        self.assertEqual(report['source_sha256'], model.digest(model.SOURCE))
        self.assertEqual(report['qualification'], spec['qualification'])
        self.assertTrue(all(type(v) is bool and not v for v in report['qualification'].values()))
        self.assertTrue(report['source_files_sha256'])
        for name, expected in report['source_files_sha256'].items():
            with self.subTest(source=name):
                self.assertEqual(model.digest(ROOT/name), expected)
        self.assertEqual(set(report['arm_cache']), {'freecad', 'solidcraft'})
        for backend, cache in report['arm_cache'].items():
            with self.subTest(cache=backend):
                self.assertEqual(cache['backend'], backend)
                self.assertEqual(cache['spec_sha256'], spec['robot']['source_sha256'])
                self.assertEqual(model.digest(Path(cache['path'])), cache['sha256'])
                self.assertEqual(model.digest(Path(cache['report_path'])), cache['report_sha256'])
                for field in ('generator_sha256', 'vendor_source_sha256'):
                    for name, expected in cache[field].items():
                        self.assertEqual(model.digest(ROOT/name), expected, name)
        p = model.parameters(spec)
        self.assertIsNone(report['window_scan'])
        proof_ref = report['routing_proof']
        self.assertEqual(proof_ref['format'], joint_routing.PROOF_FORMAT)
        self.assertEqual(model.digest(ROOT/proof_ref['path']), proof_ref['sha256'])
        band = json.loads((ROOT/proof_ref['path']).read_text())
        builder.validate_routing_proof(band, model, spec, p)
        self.assertTrue(band['passed'])
        self.assertEqual(band['status'], 'demonstrated')
        self.assertEqual(set(band['states']), set(spec['states']))
        self.assertEqual(band['parameters'], p)
        self.assertEqual(band['failures'], [])
        self.assertEqual(proof_ref['state_count'], len(spec['states']))
        self.assertAlmostEqual(band['hose_length_mm'], p['hoseLength'])
        for key in ('format', 'section_lengths_mm', 'hose_length_mm',
                    'clip_material_stations_mm', 'qualification'):
            self.assertEqual(proof_ref[key], band[key])
        self.assertTrue(band['qualification'])
        self.assertTrue(all(value is False for value in band['qualification'].values()))
        for name, expected in band['source_files_sha256'].items():
            self.assertEqual(model.digest(ROOT/name), expected)
        self.assertIsNotNone(proof_ref['source_report'])
        self.assertEqual(model.digest(ROOT/proof_ref['source_report']['path']), proof_ref['source_report']['sha256'])
        self.assertEqual((ROOT/proof_ref['path']).read_bytes(), (ROOT/proof_ref['source_report']['path']).read_bytes())
        own = model.expanded(spec, p)
        own_ids = {row['id'] for row in own['bodies']}
        arm_operations = [op for link in robot.expanded(model.arm(spec))['links']
                          for op in link['recipe'] if op['action'] == 'create']
        arm_ids = {op['body'] for op in arm_operations}
        physical_arm_ids = {op['body'] for op in arm_operations if op['role'] != 'viewing_cone'}
        expected_ids = own_ids | arm_ids | {'PneumaticHose'}
        self.assertIsNone(spec['hose_carrier'])
        self.assertFalse({'CarrierEnvelope', 'CarrierLinks', 'CarrierOuterGuard'} & expected_ids)
        self.assertFalse(own_ids & arm_ids)
        self.assertNotIn('CarrierOuterGuard', expected_ids)
        self.assertEqual(len(report['states']), len(spec['states']))
        for row in report['states']:
            with self.subTest(state=row['id']):
                self.assertIsNone(row['state']['carrier'])
                expected_counts = {name: 1 for name in expected_ids}
                self.assertEqual(row['carrier_bodies'], [])
                self.assertEqual(row['carrier_aliases'], {})
                self.assertIsNone(row['carrier_checks'])
                self.assertTrue(row['passed'])
                self.assertEqual(row['semantic_body_count'], len(expected_ids))
                self.assertIsNone(row['state']['actual_dispensed_volume_ul'])
                self.assertAlmostEqual(row['state']['hose_path']['length_mm'], p['hoseLength'], places=6)
                selected = band['states'][row['id']]
                self.assertEqual(row['named_length_witness'], {key: value for key, value in selected.items() if key != 'path'})
                self.assertTrue(row['named_route_agreement']['passed'])
                self.assertFalse(row['named_route_agreement']['mismatches'])
                self.assertTrue(builder.compare_named_route(selected['path'], row['state'])['passed'])
                self.assertTrue(builder.compare_derived_metrics(row['state']['length_accounting'], selected['path']['length_accounting'], tolerance=1e-7)['passed'])
                self.assertTrue(joint_routing.validate_material_path(row['state']['hose_path'], p, band)['passed'])
                self.assertTrue(row['state']['source_clearance']['passed'])
                self.assertIsNone(row['state']['hose_slack_parameter_mm'])
                self.assertTrue(row['state']['hose_proximity']['passed'])
                recomputed = builder.compare_derived_metrics(row['state']['metrics'],
                                                             model.state(spec, p, row['id'])['metrics'])
                self.assertTrue(recomputed['passed'], recomputed['mismatches'])
                self.assertEqual(row['metrics'], row['state']['metrics'])
                material = row['route_material_checks']
                self.assertTrue(material['passed'])
                self.assertGreaterEqual(material['required_bare_radius_mm'], 12)
                if material['achieved_bare_radius_mm'] is not None:
                    self.assertGreaterEqual(material['achieved_bare_radius_mm'], material['required_bare_radius_mm']-1e-7)
                self.assertIsNone(material['required_guide_radius_mm'])
                self.assertIsNone(material['achieved_guide_radius_mm'])
                self.assertAlmostEqual(material['exact_segment_length_mm'], p['hoseLength'], places=6)
                self.assertAlmostEqual(material['accounted_material_length_mm'], p['hoseLength'], places=6)
                self.assertEqual(material['material_partition'], row['state']['length_accounting'])
                self.assertLess(abs(material['sum_error_mm']), 1e-7)
                self.assertIsNone(material['guide_end_straights'])
                self.assertEqual(set(material['clip_end_straights']), set(spec['hose_routing']['clips']))
                for lead in material['clip_end_straights'].values():
                    self.assertTrue(lead['passed'])
                    self.assertEqual(lead['required_free_leads_mm'], [p['clipFreeLead']]*2)
                    self.assertAlmostEqual(lead['physical_support_length_mm'], p['hoseClipLength'])
                    self.assertTrue(all(actual >= required-1e-7 for actual, required in
                        zip(lead['achieved_free_leads_mm'], lead['required_free_leads_mm'])))
                comparisons = row['body_comparisons']
                self.assertEqual({item['body'] for item in comparisons}, expected_ids)
                self.assertEqual(len(comparisons), len(expected_ids))
                self.assertTrue(all(item['passed'] for item in comparisons))
                self.assertTrue(row['freecad_presentation']['passed'])
                self.assertTrue(row['freecad_presentation']['geometry_bytes_unchanged'])
                self.assertFalse(row['freecad_presentation']['gui_render_checked'])
                self.assertTrue(row['clearance_checks']['passed'])
                self.assertFalse(row['clearance_checks']['interferences'])
                categories = row['clearance_checks']['categories']
                self.assertEqual(set(categories), {'hose_arm', 'tooling_arm', 'tooling_tooling'})
                for name, category in categories.items():
                    self.assertTrue(category['passed'])
                    self.assertGreater(category['minimum_distance_mm'], 0)
                    self.assertEqual(set(category['closest_pair']), {'a', 'b'})
                    closest = frozenset(category['closest_pair'].values())
                    self.assertTrue(closest.issubset(expected_ids))
                    self.assertNotIn(closest, CONTACT_PAIRS)
                    self.assertGreater(category['checked_pairs'], 0)
                    self.assertGreater(category['nonallowed_pairs'], 0)
                    self.assertGreater(category['exact_distance_checks'], 0)
                    self.assertEqual(category['exact_distance_checks']+category['broad_phase_skipped_pairs'],
                                     category['checked_pairs'])
                contacts = row['clearance_checks']['allowed_contacts']
                self.assertEqual(len(contacts), len(CONTACT_PAIRS))
                self.assertEqual({frozenset((item['a'], item['b'])) for item in contacts}, CONTACT_PAIRS)
                self.assertEqual(sum(category['declared_pairs'] for category in categories.values()), len(CONTACT_PAIRS))
                tolerance = row['clearance_checks']['tolerances']['overlap_zero_mm3']
                self.assertTrue(all(item['overlap_mm3'] <= tolerance for item in contacts))
                self.assertFalse(row['clearance_checks']['undeclared_contacts'])
                self.assertIsNone(row['clearance_checks'].get('clearance_proxy_policy'))
                self.assertEqual(set(row['files']), set(row['artifact_sha256']))
                for name, expected in row['artifact_sha256'].items():
                    self.assertEqual(model.digest(ROOT/row['files'][name]), expected, name)
                with zipfile.ZipFile(ROOT/row['files']['solidcraft']) as archive:
                    solidcraft = json.loads(archive.read('document.json'))
                metadata = solidcraft['metadata']['org.solidcraftbot.arm-syringe']
                self.assertEqual(metadata['operating_window_status'], spec['operating_window_status'])
                self.assertEqual(metadata['operating_window_deg'], spec['operating_window_deg'])
                with zipfile.ZipFile(ROOT/row['files']['freecad']) as archive:
                    freecad = ET.fromstring(archive.read('Document.xml'))
                controller = freecad.find("ObjectData/Object[@name='SyringeController']")
                status = controller.find("Properties/Property[@name='OperatingWindowStatus']/String")
                window = controller.find("Properties/Property[@name='OperatingWindowDeg']/String")
                self.assertEqual(status.get('value'), spec['operating_window_status'])
                self.assertEqual(json.loads(window.get('value')), spec['operating_window_deg'])
                max_angle = freecad.find("ObjectData/Object[@name='SyringeParameters']/Properties/Property[@name='maxMotorAngle']/Float")
                self.assertAlmostEqual(float(max_angle.get('value')), p['maxMotorAngle'])
                native = json.loads((ROOT/row['files']['freecad_validation']).read_text())
                self.assertTrue(native['passed'])
                self.assertEqual(native['source_sha256'], report['source_sha256'])
                self.assertEqual(native['qualification'], spec['qualification'])
                self.assertEqual(native['metrics'], row['state']['metrics'])
                self.assertTrue(builder.compare_derived_metrics(native['route_material_checks'], material, tolerance=1e-9)['passed'])
                self.assertTrue(native['independent_route_material_checks']['passed'])
                agreement = native['native_metrics_agreement']
                self.assertTrue(agreement['passed'])
                self.assertFalse(agreement['mismatches'])
                self.assertGreater(agreement['numeric_values_compared'], 0)
                self.assertEqual(agreement['absolute_numeric_tolerance'], 1e-9)
                self.assertLessEqual(agreement['maximum_absolute_numeric_difference'],
                                     agreement['absolute_numeric_tolerance'])
                compiled = native['compiled_state_agreement']
                self.assertTrue(compiled['passed'])
                self.assertFalse(compiled['mismatches'])
                self.assertEqual(compiled['absolute_numeric_tolerance'], 1e-9)
                self.assertLessEqual(compiled['maximum_absolute_numeric_difference'], 1e-9)
                derivation = native['route_derivation_diagnostics']
                self.assertIs(derivation['physical_curve_equivalence_established'], True)
                diagnostics_agreement = builder.compare_derived_metrics(derivation['leading'],
                    builder.route_derivation_diagnostics(row['state']['hose_path'],
                        sample_step_mm=spec['hose_routing']['sample_step_mm']), tolerance=1e-9)
                self.assertTrue(diagnostics_agreement['passed'], diagnostics_agreement['mismatches'])
                self.assertEqual([part['id'] for part in derivation['independent']],
                                 [part['id'] for part in row['state']['length_accounting']['parts']])
                self.assertTrue(derivation['scope'])
                definitions = {item['id']: item for item in spec['hose_routing']['sections']}
                section_records = {item['id']: item for item in row['state']['hose_path']['section_records']}
                reach_arm = model.arm(spec);reach_parameters = robot.parameters(reach_arm)
                reach_fk = robot.forward(reach_arm, row['state']['joints_deg'])
                for evaluated in (derivation['leading'], derivation['independent']):
                    for diagnostic in evaluated:
                        definition = definitions.get(diagnostic['id'])
                        if definition is None or definition['kind'] != 'joint_loop':
                            continue
                        raw = diagnostic['local_reach'];grid = diagnostic['sample_grid']
                        self.assertEqual(raw['required_maximum_radial_reach_mm'], definition['max_reach_mm'])
                        self.assertEqual(raw['required_axial_range_mm'], definition['axial_range_mm'])
                        values = [raw['maximum_radial_reach_upper_bound_mm']]+raw['axial_range_outer_bound_mm']
                        self.assertTrue(all(type(value) in (int, float) and math.isfinite(value) for value in values))
                        self.assertLessEqual(0., raw['maximum_radial_reach_upper_bound_mm'])
                        self.assertLessEqual(raw['maximum_radial_reach_upper_bound_mm'], definition['max_reach_mm'])
                        low, high = raw['axial_range_outer_bound_mm']
                        self.assertLessEqual(definition['axial_range_mm'][0], low)
                        self.assertLessEqual(low, high)
                        self.assertLessEqual(high, definition['axial_range_mm'][1])
                        length, count = grid['section_length_mm'], grid['interval_count']
                        self.assertEqual(grid['requested_maximum_interval_mm'], spec['hose_routing']['sample_step_mm'])
                        self.assertEqual(count, max(1, math.ceil(length/grid['requested_maximum_interval_mm'])))
                        self.assertAlmostEqual(grid['interval_width_mm']*count, length, places=9)
                        self.assertEqual(len(grid['section_arclength_midpoints_mm']), count)
                        self.assertEqual(len(grid['reconstructed_world_points_mm']), count)
                        record = section_records[diagnostic['id']]
                        self.assertAlmostEqual(length, record['actual_length_mm'], delta=1e-9)
                        offset = sum(segment['length_mm'] for segment in
                            row['state']['hose_path']['segments'][:record['segment_start_index']])
                        for index, (station, point) in enumerate(zip(grid['section_arclength_midpoints_mm'],
                                grid['reconstructed_world_points_mm'])):
                            self.assertAlmostEqual(station, (index+.5)*grid['interval_width_mm'], places=9)
                            expected = carrier.path_position(row['state']['hose_path'], offset+station)['point_mm']
                            self.assertLess(math.dist(point, expected), 1e-9)
                        joint = next(item for item in reach_arm['joints'] if item['id'] == definition['joint'])
                        origin = robot.transform(reach_fk[joint['parent']],
                            [model.evaluate(v, reach_parameters) for v in joint['frame']['origin']])
                        axis = [sum(reach_fk[joint['parent']][i][j]*model.evaluate(
                            joint['frame']['axis'][j], reach_parameters) for j in range(3)) for i in range(3)]
                        axial, radial = [], []
                        for point in grid['reconstructed_world_points_mm']:
                            delta = [value-start for value, start in zip(point, origin)]
                            along = sum(a*b for a, b in zip(delta, axis))
                            axial.append(along)
                            radial.append(math.sqrt(max(0., sum(v*v for v in delta)-along*along)))
                        half = grid['interval_width_mm']/2
                        self.assertAlmostEqual(raw['maximum_radial_reach_upper_bound_mm'],
                                               max(radial)+half, delta=1e-7)
                        for actual, expected in zip(raw['axial_range_outer_bound_mm'],
                                                    [min(axial)-half, max(axial)+half]):
                            self.assertAlmostEqual(actual, expected, delta=1e-7)
                for source_clearance in (native['source_clearance'], native['independent_source_clearance']):
                    self.assertTrue(source_clearance['passed'])
                    self.assertGreater(source_clearance['minimum_margin_lower_bound_mm'], 0)
                    self.assertTrue(source_clearance['scope'])
                case = json.loads((ROOT/row['files']['case']).read_text())
                self.assertEqual(case['compiled_state'], row['state'])
                self.assertEqual(native['hose_self_clearance'], row['state']['hose_self_clearance'])
                for diagnostic in (native['hose_self_clearance'], native['independent_hose_self_clearance']):
                    self.assertTrue(diagnostic['passed'])
                    self.assertIs(diagnostic['continuous_self_clearance_verified'], False)
                self.assertIsNone(native['carrier_checks'])
                self.assertEqual(row['clip_checks'], native['clip_checks'])
                self.assert_clipped_native_geometry(row, native, spec, p, band)
                self.assertEqual(row['pneumatic_connections'], native['pneumatic_connections'])
                connections = native['pneumatic_connections']
                self.assertTrue(connections['passed'])
                self.assertEqual(set(connections['required_interfaces']), {'pump', 'tip'})
                self.assertEqual(set(connections['required_bodies']), {'PumpHoseBarb', 'TipSidePort'})
                self.assertEqual(set(connections['observations']), {'PumpHoseBarb', 'TipSidePort'})
                self.assertTrue(all(item['distance_mm'] <= 1e-7 and item['overlap_mm3'] <= 1e-5
                                    for item in connections['observations'].values()))
                mating = connections['socket_mating']
                self.assertTrue(mating['passed'])
                self.assertEqual(set(mating['interfaces']), {'pump', 'tip'})
                interfaces = model.connection_interfaces(spec, p, row['state']['part_matrices'])
                for key, interface in interfaces.items():
                    checked = mating['interfaces'][key]
                    self.assertTrue(checked['passed'])
                    self.assertEqual(checked['body'], interface['body'])
                    self.assertIs(checked['seal_qualified'], False)
                    for error in ('coaxial_error_mm', 'axial_endpoint_error_mm', 'axis_alignment_error',
                                  'insertion_depth_error_mm', 'maximum_radial_gap_error_mm'):
                        self.assertLessEqual(checked[error], 1e-7)
                    self.assertAlmostEqual(checked['measured_insertion_depth_mm'], p['hoseInsertionDepth'], places=7)
                    required = p['hoseInsertionDepth']+p['strainReliefLength']+p['connectorStraightLead']
                    self.assertAlmostEqual(checked['required_straight_run_mm'], required, places=7)
                    self.assertGreaterEqual(checked['achieved_straight_run_mm'], required-1e-7)
                    self.assertGreater(checked['minimum_native_radial_gap_mm'], 0)
                    self.assertAlmostEqual(checked['radial_clearance_mm'], p['socketRadialClearance'])
                    self.assertGreaterEqual(len(checked['radial_gap_witnesses']), 8)
                    for witness in checked['radial_gap_witnesses']:
                        for field in ('tube_wall_socket_distance_mm', 'socket_wall_tube_distance_mm'):
                            self.assertAlmostEqual(witness[field], p['socketRadialClearance'], places=7)
                            self.assertGreater(witness[field], 0)
                        self.assertLessEqual(witness['tube_wall_distance_mm'], 1e-7)
                        self.assertLessEqual(witness['socket_wall_distance_mm'], 1e-7)
                    self.assertEqual(len(checked['floor_witnesses']), 4)
                    for witness in checked['floor_witnesses']:
                        self.assertLessEqual(witness['tube_distance_mm'], 1e-7)
                        self.assertLessEqual(witness['socket_distance_mm'], 1e-7)
                    self.assert_native_contact_on_plane(checked['floor_contact'],
                        interface['material_end_mm'], interface['outward'],
                        interface['tube_inner_radius_mm'], interface['tube_outer_radius_mm'])
                    support = checked['strain_relief']
                    self.assertTrue(support['passed'])
                    self.assertEqual(support['native_component'], interface['component'])
                    self.assertEqual(support['required_component'], interface['component'])
                    self.assertNotEqual(support['native_component'], 'ConsumableTip')
                    self.assertEqual(support['clamp_body'], 'PumpHoseClamp' if key == 'pump' else 'TipHoseClamp')
                    self.assertEqual(len(support['radial_gap_witnesses']), 4)
                    for witness in support['radial_gap_witnesses']:
                        self.assertAlmostEqual(witness['native_radial_gap_mm'], p['socketRadialClearance'], places=7)
                self.assertEqual(row['tip_seat_checks'], native['tip_seat_checks'])
                seat_check = native['tip_seat_checks']
                self.assertTrue(seat_check['passed'])
                self.assertIs(seat_check['seal_qualified'], False)
                self.assertIs(seat_check['insertion_force_qualified'], False)
                seat = model.tip_seat(spec, p)
                self.assertEqual(seat_check['shaft_body'], seat['shaft_body'])
                self.assertEqual(seat_check['tip_body'], seat['tip_body'])
                self.assertAlmostEqual(seat_check['engagement_length_mm'], p['tipEngagementLength'])
                self.assertAlmostEqual(seat_check['mouth_radial_relief_mm'], p['tipTaperRelief'])
                self.assertLessEqual(seat_check['coaxial_error_mm'], 1e-7)
                self.assertLessEqual(seat_check['tcp_error_mm'], 1e-7)
                self.assertLess(math.dist(seat_check['rederived_tcp_mm'], row['state']['tip_tcp_mm']), 1e-7)
                head = row['state']['part_matrices']['WristHead']
                center = robot.transform(head, seat['seal_center_mm'])
                normal = [head[i][2] for i in range(3)]
                self.assert_native_contact_on_plane(seat_check['seal_contact'], center, normal,
                                                    seat['seal_radius_mm'], seat['seal_radius_mm'])
                self.assertEqual(len(seat_check['seal_circle_witnesses']), 4)
                for witness in seat_check['seal_circle_witnesses']:
                    self.assertLessEqual(witness['shaft_distance_mm'], 1e-7)
                    self.assertLessEqual(witness['tip_distance_mm'], 1e-7)
                    self.assertAlmostEqual(math.dist(witness['point_mm'], center), seat['seal_radius_mm'], places=6)
                self.assertTrue(seat_check['native_relief_samples'])
                for witness in seat_check['native_relief_samples']:
                    gap = p['tipTaperRelief']*witness['fraction_above_seal']
                    self.assertGreater(witness['native_radial_gap_mm'], 0)
                    self.assertAlmostEqual(witness['expected_radial_gap_mm'], gap, places=7)
                    self.assertAlmostEqual(witness['native_radial_gap_mm'], gap, places=7)
                self.assertEqual(row['air_path_checks'], native['air_path_checks'])
                air_check = native['air_path_checks']
                self.assertTrue(air_check['passed'])
                probe = air_check['head_probe']
                self.assertTrue(probe['passed'])
                self.assertLess(math.dist(probe['points_mm'][0], interfaces['tip']['pneumatic_junction_mm']), 1e-7)
                self.assertLess(math.dist(probe['points_mm'][-1], row['state']['tip_tcp_mm']), 1e-7)
                self.assertTrue(probe['observations'])
                self.assertTrue(all(item['material_intersection_mm'] <= 1e-7 for item in probe['observations']))
                self.assertGreaterEqual(probe['minimum_axis_clearance_mm'], probe['required_axis_clearance_mm']-1e-7)
                inventory = air_check['cavity_union']
                self.assertTrue(inventory['passed'])
                self.assertTrue(inventory['valid'])
                self.assertEqual(inventory['solid_count'], 1)
                self.assertIs(inventory['ideal_open_valve_reference'], True)
                self.assertIs(inventory['delivered_material_body'], False)
                self.assertEqual(inventory['construction_frame'], 'PumpFrame')
                construction = inventory['construction_frame_matrix']
                self.assertTrue(builder.compare_derived_metrics(construction,
                    row['state']['part_matrices']['PumpFrame'], tolerance=1e-9)['passed'])
                columns = [[construction[i][j] for i in range(3)] for j in range(3)]
                for i in range(3):
                    for j in range(3):
                        self.assertAlmostEqual(sum(a*b for a, b in zip(columns[i], columns[j])), int(i == j), places=12)
                a, b, c = columns
                cross = [b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0]]
                self.assertAlmostEqual(sum(x*y for x, y in zip(a, cross)), 1, places=12)
                self.assertLessEqual(inventory['rigid_placement_volume_difference_mm3'], 1e-7)
                self.assertLessEqual(abs(inventory['native_local_volume_mm3']-inventory['native_volume_mm3']), 1e-7)
                self.assertAlmostEqual(inventory['rigid_placement_volume_difference_mm3'],
                    abs(inventory['native_local_volume_mm3']-inventory['native_volume_mm3']), places=9)
                self.assertIs(type(inventory['native_recipe_connected_components']), int)
                self.assertGreater(inventory['native_recipe_connected_components'], 0)
                self.assertTrue(inventory['native_union_strategy'])
                groups = inventory['native_recipe_groups']
                self.assertEqual(len(groups), inventory['native_recipe_connected_components'])
                recipe = model.air_path_recipe(spec, p, row['state']['stroke_mm'])
                grouped_components = [component for group in groups for component in group['source_components']]
                self.assertEqual(len(grouped_components), len(set(grouped_components)))
                self.assertEqual(set(grouped_components), {item['component'] for item in recipe})
                for group in groups:
                    self.assertEqual(group['solid_count'], 1)
                    self.assertTrue(group['source_components'])
                    self.assertGreater(group['local_volume_mm3'], 0)
                    self.assertTrue(math.isfinite(group['local_volume_mm3']))
                    self.assertGreater(group['placed_volume_mm3'], 0)
                    self.assertTrue(math.isfinite(group['placed_volume_mm3']))
                    difference = abs(group['local_volume_mm3']-group['placed_volume_mm3'])
                    self.assertLessEqual(difference, 1e-7)
                    self.assertLessEqual(group['rigid_placement_volume_difference_mm3'], 1e-7)
                    self.assertAlmostEqual(group['rigid_placement_volume_difference_mm3'], difference, places=9)
                self.assertLessEqual(inventory['relative_volume_error'], 1e-6)
                expected_air = row['state']['metrics']['enclosed_air_volume_ul']
                self.assertAlmostEqual(inventory['expected_volume_ul'], expected_air['total'], places=7)
                self.assertLessEqual(abs(inventory['native_volume_mm3']-expected_air['total'])/expected_air['total'], 1e-6)
                self.assertLessEqual(abs(inventory['native_tube_lumen_volume_mm3']-math.pi*p['hoseInnerRadius']**2*p['hoseLength']), 1e-5)
                self.assertAlmostEqual(inventory['excluded_ambient_tip_relief_ul'], expected_air['unpressurized_tip_relief_air_ul'], places=7)
                self.assertEqual(set(inventory['recipe_ids']), {item['id'] for item in model.air_path_recipe(spec, p, row['state']['stroke_mm'])})
                self.assertTrue(native['reopened']['passed'])
                self.assertEqual({item['body'] for item in native['arm_pose_checks']}, arm_ids)
                self.assertEqual({item['body'] for item in native['new_part_pose_checks']}, own_ids)
                for item in native['arm_pose_checks']+native['new_part_pose_checks']:
                    self.assertLess(item['error_mm'], 1e-6, item['body'])
                self.assertLess(native['motor_coupling_error_deg'], 1e-7)
                self.assertLess(native['hose']['relative_wall_volume_error'], 1e-6)
                self.assertLess(native['hose']['centerline_material_intersection_mm'], 1e-7)
                self.assertEqual(set(native['geometry']), expected_ids)
                self.assertTrue(all(item['valid'] and item['closed_solids']
                                    and item['solid_count'] == expected_counts[name]
                                    for name, item in native['geometry'].items()))
        required_views = {'overview', 'overview_close', 'pump', 'tip', 'syringe_junction',
                          'pipette_junction', 'guide_transition', 'tightest_bend',
                          'pump_section', 'tip_section'}
        self.assertTrue(required_views.issubset(report['renders']))
        by_state = {row['id']: row for row in report['states']}
        for name, view in report['renders'].items():
            self.assertEqual(model.digest(ROOT/view['path']), view['sha256'])
            self.assertIn(view['state'], by_state)
            state = by_state[view['state']]
            self.assertEqual(view['native_artifact'], state['files']['solidcraft'])
            self.assertEqual(view['native_artifact_sha256'], state['artifact_sha256']['solidcraft'])
            self.assertEqual(model.digest(ROOT/view['native_artifact']), view['native_artifact_sha256'])
            if name in ('pump_section', 'tip_section'):
                self.assertEqual(view['state'], 'upright')
                self.assertEqual(view['section'], {'plane': 'XZ', 'at': 0, 'flip': True, 'hatch': True})
                self.assertEqual(model.digest(ROOT/view['command_file']), view['command_sha256'])
                commands = json.loads((ROOT/view['command_file']).read_text())['commands']
                self.assertEqual(commands, [
                    {'command': 'inspect.section', 'params': {'clear': True}},
                    {'command': 'inspect.section', 'params': view['section']}])
        tightest = report['renders']['tightest_bend']
        drawn = by_state[tightest['state']]['state']['hose_path']['segments'][tightest['geometry_witness']['segment_index']]
        self.assertEqual(drawn['kind'], 'arc')
        self.assertEqual(tightest['geometry_witness']['achieved_radius_mm'], drawn['radius_mm'])
        self.assertAlmostEqual(drawn['radius_mm'], min(segment['radius_mm']
            for row in report['states'] for segment in row['state']['hose_path']['segments']
            if segment['kind'] == 'arc'))
        transition = report['renders']['guide_transition']
        witness = transition['geometry_witness']
        self.assertEqual(witness['clip_station'], 'j4_child')
        frame = by_state[transition['state']]['state']['hose_path']['clip_frames'][witness['clip_station']]
        self.assertLess(math.dist(witness['clip_center_mm'], frame['center_mm']), 1e-7)
        self.assertTrue(transition['scope'])


if __name__ == '__main__':
    unittest.main()
