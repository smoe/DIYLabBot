"""Finite sampling and failure accounting, without CAD or hose physics claims."""
import copy
import itertools
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import arm_syringe
import arm_syringe_window as window_scan


class ArmSyringeWindowTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(arm_syringe.SOURCE.read_text())
        self.joints = arm_syringe.arm(self.spec)['joints']
        self.ids = [joint['id'] for joint in self.joints]
        self.spec['operating_window_deg'] = {
            name: {'range': [0, 60], 'reason': 'Synthetic sampling fixture'} for name in self.ids}
        self.spec['operating_window_status'] = 'Synthetic unqualified test window'
        self.spec['hose_length_design'] = {
            'margin_mm': 10, 'scan_max_step_deg': 30, 'max_service_loop_mm': 200}
        self.spec['states'] = {
            'upright': {'joints_deg': [0]*6},
            'working': {'joints_deg': [30]*6},
            'same_working_coordinates': {'joints_deg': [30]*6}}
        self.p = {'hoseLength': 540}

    @staticmethod
    def route(spec, p, q, slack):
        return {'length_mm': 500+sum((i+1)*value/60 for i, value in enumerate(q))+slack}

    def run_scan(self, **kwargs):
        return window_scan.scan(self.spec, self.p, route_at=self.route, **kwargs)

    def physical_fixture(self):
        self.spec['hose_length_design'] = {
            'allowances': [{'id': 'cut', 'value_mm': 2, 'reason': 'Synthetic cutting fixture'},
                           {'id': 'assembly', 'value_mm': .5, 'reason': 'Synthetic assembly fixture'}],
            'scan_max_step_deg': 30, 'max_service_loop_mm': 200,
            'loop_sample_step_mm': 10, 'cut_resolution_mm': 1,
            'clearance_sample_step_mm': 2, 'clearance_minimum_step_mm': .05,
            'scope': 'Synthetic integration fixture; no physical clearance claim'}
        self.p['hoseOuterRadius'] = .9
        return {'status': 'demonstrated', 'states': {name: {} for name in self.spec['states']},
                'selected_states': {name: {} for name in self.spec['states']},
                'cut_selection': {'selected_cut_mm': 540}, 'failures': [],
                'scope': 'Synthetic independently supplied named-band fixture',
                'qualification': {'hardware_execution_implemented': False}}

    def physical_scan(self, route=None, band=None):
        if route is None:
            route = self.route
        if band is None:
            band = self.physical_fixture()
        def self_check(path, radius):
            return {'passed': not path.get('fixture_self_crossing', False),
                    'continuous_self_clearance_verified': False}
        def external(spec, p, path, frames, mounted, context):
            return {'passed': not path.get('fixture_envelope', False),
                    'scope': 'Synthetic injected source-envelope result'}
        with patch.object(arm_syringe, 'prepare_route_context', return_value=object()), \
             patch.object(arm_syringe, '_placements', return_value=({}, {})), \
             patch.object(arm_syringe, '_route_clearance', side_effect=external), \
             patch.object(arm_syringe.pneumatic_hose, 'self_clearance_diagnostics', side_effect=self_check):
            return window_scan.scan(self.spec, self.p, route_at=route, named_band=band)

    def test_itemized_design_uses_independent_named_cut_instead_of_diagnostic_extrema(self):
        band = self.physical_fixture()
        seen = []
        def named(source, parameters):
            seen.append((source, parameters))
            return band
        report = self.physical_scan(band=named)
        self.assertEqual(seen, [(self.spec, self.p)])
        self.assertIs(report['named_state_band'], band)
        self.assertTrue(report['sample_coverage']['complete'])
        self.assertTrue(report['sample_coverage']['named_state_support_complete'])
        self.assertEqual(report['suggested_hose_length_mm'], 540)
        self.assertEqual(report['hose_length_design']['margin_mm'], 2.5)
        self.assertIn('Derived sum', report['hose_length_design']['margin_origin'])
        self.assertEqual(report['hose_length_design']['allowances'], self.spec['hose_length_design']['allowances'])
        self.assertEqual(report['common_endpoint_bracket']['suggested_length_mm'], 524)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['diagnostic_unsupported'], [])
        self.assertTrue(all(value is False for value in report['qualification'].values()))

    def test_geometric_diagnostic_failures_and_length_mismatches_remain_classified(self):
        band = self.physical_fixture()
        def route(spec, p, q, slack):
            if q == [0]*6 and slack == 0:
                raise arm_syringe.pneumatic_hose.HoseBendError('Fixture bend does not fit', {'required_radius_mm': 12})
            if q == [60]*6 and slack == 0:
                raise arm_syringe.routing.RouteClearanceError('Fixture envelope hit', {'body': 'Witness'})
            if q == [30]*6:
                return {'length_mm': 600+slack-.05*slack*(200-slack)}
            if q == [0, 0, 0, 0, 0, 60]:
                return {'length_mm': 400+slack/10+.02*slack*(200-slack)}
            if q == [60, 0, 0, 0, 0, 0]:
                return {'length_mm': 1000-slack}
            path = self.route(spec, p, q, slack)
            path['fixture_self_crossing'] = q == [0, 60, 0, 0, 0, 0]
            path['fixture_envelope'] = q == [0, 0, 60, 0, 0, 0]
            return path
        report = self.physical_scan(route, band)
        self.assertTrue(report['sample_coverage']['complete'])
        self.assertTrue(report['sample_coverage']['named_state_support_complete'])
        self.assertEqual(report['errors'], [])
        self.assertIsNone(report['common_endpoint_bracket'])
        self.assertEqual(report['suggested_hose_length_mm'], 540)
        classes = {row['classification'] for row in report['diagnostic_unsupported']}
        self.assertTrue({'bend', 'envelope_proximity', 'self_crossing', 'nonmonotonic_endpoint_lengths'} <= classes)
        samples = {tuple(row['joints_deg']): row for row in report['samples']}
        self.assertEqual(samples[(30,)*6]['classification'], 'too_short_for_endpoint_bracket')
        self.assertEqual(samples[(0, 0, 0, 0, 0, 60)]['classification'], 'too_long_for_endpoint_bracket')
        self.assertEqual(samples[(60, 0, 0, 0, 0, 0)]['classification'], 'nonmonotonic_endpoint_lengths')
        self.assertEqual(samples[(0,)*6]['classification'], 'route_unavailable_at_diagnostic_endpoint')
        self.assertEqual(samples[(0,)*6]['endpoints']['zero_slack']['error']['witness']['required_radius_mm'], 12)
        self.assertEqual(report['sample_coverage']['unsupported_endpoint_observations'], len(report['diagnostic_unsupported']))
        self.assertEqual(report['sample_coverage']['route_endpoint_calls'], 2*len(report['samples']))

    def test_blocked_named_band_suppresses_cut_even_with_complete_diagnostic_lengths(self):
        band = self.physical_fixture()
        band.update(status='blocked', selected_states={}, failures=[{'state': 'working', 'classification': 'no_feasible_route'}])
        band['cut_selection']['selected_cut_mm'] = None
        report = self.physical_scan(band=band)
        self.assertFalse(report['sample_coverage']['complete'])
        self.assertFalse(report['sample_coverage']['named_state_support_complete'])
        self.assertIsNone(report['suggested_hose_length_mm'])
        self.assertEqual(report['errors'][0]['error_type'], 'NamedBandBlocked')
        self.assertEqual(report['errors'][0]['failures'], band['failures'])

    def test_malformed_or_unexpected_evaluator_errors_override_an_injected_demonstrated_band(self):
        for failure in ('nonfinite', 'runtime', 'evidence'):
            with self.subTest(failure=failure):
                band = self.physical_fixture()
                def route(spec, p, q, slack):
                    if q == [0]*6 and slack == 0:
                        if failure == 'nonfinite':
                            return {'length_mm': math.nan}
                        if failure == 'runtime':
                            raise RuntimeError('Unexpected fixture producer failure')
                        raise arm_syringe.routing.RoutingEvidenceError('Malformed fixture evidence')
                    return self.route(spec, p, q, slack)
                report = self.physical_scan(route, band)
                self.assertFalse(report['sample_coverage']['complete'])
                self.assertEqual(len(report['errors']), 1)
                self.assertIsNone(report['suggested_hose_length_mm'])
                self.assertIsNone(report['common_endpoint_bracket'])
                self.assertEqual(report['diagnostic_unsupported'], [])

    def test_six_dimensional_corner_extrema_and_length_proposal(self):
        report = self.run_scan()
        self.assertEqual(report['sample_coverage']['corner_count'], 64)
        self.assertEqual(report['sample_coverage']['edge_count'], 6*32)
        self.assertEqual(report['sample_coverage']['unique_joint_coordinates'], 64+6*32+1)
        self.assertEqual(report['extrema']['zero_slack']['shortest']['joints_deg'], [0]*6)
        self.assertEqual(report['extrema']['zero_slack']['longest']['joints_deg'], [60]*6)
        self.assertEqual(report['extrema']['zero_slack']['shortest']['length_mm'], 500)
        self.assertEqual(report['extrema']['zero_slack']['longest']['length_mm'], 521)
        self.assertEqual(report['suggested_hose_length_mm'], 531)
        bracket = report['common_endpoint_bracket']
        self.assertEqual((bracket['min_length_mm'], bracket['max_length_mm']), (521, 700))
        self.assertTrue(bracket['selected_within'])
        self.assertTrue(bracket['suggested_within'])

    def test_every_hypercube_edge_retains_both_endpoints_and_bounded_spacing(self):
        # A nondivisible span exercises ceil subdivision and exact endpoints.
        self.spec['operating_window_deg'][self.ids[0]]['range'] = [-.1, 59.95]
        report = self.run_scan(max_step_deg=22)
        corners = {tuple(row['joints_deg']) for row in report['samples'] if row['corner']}
        self.assertEqual(corners, set(itertools.product(*[
            self.spec['operating_window_deg'][name]['range'] for name in self.ids])))
        for edge in report['edges']:
            axis = self.ids.index(edge['joint_id'])
            samples = [row for row in report['samples'] if edge['id'] in row['edges']]
            coordinates = sorted(row['joints_deg'][axis] for row in samples)
            self.assertEqual(coordinates[0], edge['range_deg'][0])
            self.assertEqual(coordinates[-1], edge['range_deg'][1])
            self.assertEqual(len(coordinates), edge['sample_count'])
            self.assertTrue(all(b-a <= 22+1e-12 for a, b in zip(coordinates, coordinates[1:])))
            for row in samples:
                self.assertTrue(all(row['joints_by_id_deg'][name] == value
                                    for name, value in edge['fixed_joints_deg'].items()))

    def test_fixed_axes_do_not_multiply_edges_or_duplicate_geometry_calls(self):
        for name in self.ids:
            self.spec['operating_window_deg'][name]['range'] = [0, 0]
        self.spec['states'] = {'upright': {'joints_deg': [0]*6},
                               'alias': {'joints_deg': [0]*6}}
        calls = []
        prepared_context = object()

        def route(spec, p, q, slack, *, context):
            self.assertIs(context, prepared_context)
            calls.append((tuple(q), slack))
            return self.route(spec, p, q, slack)

        with patch.object(arm_syringe, 'prepare_route_context', return_value=prepared_context,
                          create=True) as prepare, patch.object(arm_syringe, 'route_at', side_effect=route):
            report = window_scan.scan(self.spec, self.p)
        prepare.assert_called_once_with(self.spec, self.p)
        self.assertEqual(report['edges'], [])
        self.assertEqual(report['sample_coverage']['unique_joint_coordinates'], 1)
        self.assertEqual(calls, [((0.0,)*6, 0.0), ((0.0,)*6, 200.0)])
        self.assertEqual(report['samples'][0]['named_states'], ['upright', 'alias'])

    def test_shared_edges_and_named_state_aliases_are_evaluated_only_twice(self):
        calls = []

        def route(spec, p, q, slack):
            calls.append((tuple(q), slack))
            return self.route(spec, p, q, slack)

        report = window_scan.scan(self.spec, self.p, route_at=route)
        self.assertEqual(len(calls), 2*len(report['samples']))
        self.assertEqual(len(calls), len(set(calls)))
        working, = [row for row in report['samples'] if 'working' in row['named_states']]
        self.assertEqual(working['named_states'], ['working', 'same_working_coordinates'])
        self.assertFalse(working['corner'])
        self.assertEqual(working['edges'], [])

    def test_named_states_outside_window_remain_explicit_length_constraints(self):
        self.spec['states']['outside'] = {'joints_deg': [90]*6}
        report = self.run_scan()
        self.assertEqual(report['sample_coverage']['named_states_outside_window'], ['outside'])
        longest = report['extrema']['zero_slack']['longest']
        self.assertEqual(longest['named_states'], ['outside'])
        self.assertFalse(longest['inside_window'])
        self.assertEqual(longest['length_mm'], 531.5)
        self.assertEqual(report['suggested_hose_length_mm'], 542)
        self.assertEqual(report['common_endpoint_bracket']['min_length_mm'], 531.5)

    def test_failed_or_nonfinite_endpoint_preserves_coverage_and_suppresses_proposal(self):
        for invalid in ('exception', math.nan, math.inf, -1, 0, True):
            with self.subTest(invalid=invalid):
                calls = []

                def route(spec, p, q, slack):
                    calls.append((tuple(q), slack))
                    if q == [0]*6 and slack == 0:
                        if invalid == 'exception':
                            raise RuntimeError('Synthetic route failure')
                        return {'length_mm': invalid}
                    return self.route(spec, p, q, slack)

                report = window_scan.scan(self.spec, self.p, route_at=route)
                self.assertEqual(len(report['errors']), 1)
                self.assertFalse(report['sample_coverage']['complete'])
                self.assertIsNone(report['suggested_hose_length_mm'])
                self.assertIsNone(report['common_endpoint_bracket'])
                first = report['samples'][0]['endpoints']
                self.assertIn('error', first['zero_slack'])
                self.assertEqual(first['max_service_loop']['length_mm'], 700)
                self.assertEqual(len(calls), 2*len(report['samples']))

    def test_empty_or_reversed_length_brackets_are_not_reported_as_fitting(self):
        report = self.run_scan(max_slack_mm=5)
        self.assertTrue(report['sample_coverage']['complete'])
        self.assertFalse(report['common_endpoint_bracket']['nonempty'])
        self.assertFalse(report['common_endpoint_bracket']['suggested_within'])
        reverse = window_scan.scan(self.spec, self.p,
            route_at=lambda spec, p, q, slack: {'length_mm': 1000-slack})
        self.assertFalse(reverse['sample_coverage']['complete'])
        self.assertEqual(len(reverse['errors']), len(reverse['samples']))
        self.assertTrue(all(row['error_type'] == 'ReversedLengthBracket' for row in reverse['errors']))
        self.assertIsNone(reverse['suggested_hose_length_mm'])

    def test_invalid_windows_limits_states_and_numeric_settings_are_rejected(self):
        original = copy.deepcopy(self.spec)
        invalid_windows = [None, {}, {name: {} for name in self.ids}]
        for field, value in [('range', [0, math.inf]), ('range', [True, 1]),
                             ('range', [2, 1]), ('range', [-161, 1]),
                             ('range', [0, 1, 2]), ('reason', ''), ('extra', 1)]:
            candidate = copy.deepcopy(original['operating_window_deg'])
            candidate[self.ids[0]][field] = value
            invalid_windows.append(candidate)
        for window in invalid_windows:
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.run_scan(window=window if window is not None else {})
        for key, value in [('max_step_deg', 0), ('max_step_deg', True),
                           ('margin_mm', -1), ('max_slack_mm', math.nan), ('max_slack_mm', 0)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.run_scan(**{key: value})
        for q in ([0]*5, [0]*5+[math.nan], [0]*5+[171]):
            self.spec['states']['bad'] = {'joints_deg': q}
            with self.subTest(q=q), self.assertRaises(ValueError):
                self.run_scan()

    def test_report_pins_sources_and_distinguishes_sampling_from_qualification(self):
        report = self.run_scan()
        self.assertEqual(report['joint_order'], self.ids)
        for joint in self.joints:
            row = report['operating_window_deg'][joint['id']]
            self.assertEqual(row['source_frame'], joint['frame'])
            self.assertEqual(row['source_limits_deg'], joint['limits_deg'])
        self.assertTrue(report['sample_coverage']['complete'])
        self.assertTrue(all(value is False for value in report['qualification'].values()))
        self.assertIn('two service-loop endpoints only', report['scope'])
        pins = report['source_pins']['files_sha256']
        self.assertIn('scripts/arm_syringe_window.py', pins)
        self.assertIn(self.spec['robot']['source'], pins)
        self.assertTrue(all(len(value) == 64 for value in pins.values()))
        changed = self.run_scan(margin_mm=11)
        self.assertNotEqual(report['scan_input_canonical_sha256'], changed['scan_input_canonical_sha256'])
        json.dumps(report, allow_nan=False)

    def test_concurrent_source_changes_invalidate_a_numerically_complete_scan(self):
        before = {'files_sha256': {'route.py': 'old'}}
        after = {'files_sha256': {'route.py': 'new'}}
        with patch.object(window_scan, '_pins', side_effect=[before, after]):
            report = self.run_scan()
        self.assertEqual(report['source_pins'], before)
        self.assertFalse(report['source_files_unchanged_during_scan'])
        self.assertFalse(report['sample_coverage']['complete'])
        self.assertEqual(report['errors'][0]['error_type'], 'SourceChangedDuringScan')
        self.assertIsNone(report['suggested_hose_length_mm'])
        self.assertIsNone(report['common_endpoint_bracket'])


if __name__ == '__main__':
    unittest.main()
