"""Finite static band selection must prove its chosen length, not just a hull."""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import arm_syringe_routing as routing
import pneumatic_hose as hose
import spatial_hose_carrier as carrier


class FramedRoutingBandTests(unittest.TestCase):
    PARAMETERS = {'hoseBendRadius': 12, 'hoseOuterRadius': .9}

    def test_declared_fillet_candidates_avoid_a_long_biarc_without_shrinking_bends(self):
        args = ([0, 65, 525], [-37, 0, 650.7], [0, 1, 0], [1, 0, 0], 12)
        biarc = carrier.biarc_path(*args)
        fitted = routing.bare_span(*args, tangent_distance_multipliers=[1, 1.5, 2, 3, 4, 6, 8])
        self.assertLess(fitted['length_mm'], biarc['length_mm']-100)
        self.assertEqual(fitted['min_bend_radius_mm'], 12)
        self.assertEqual(fitted['segments'][0]['start_mm'], args[0])
        self.assertEqual(fitted['segments'][-1]['end_mm'], args[1])
        self.assertLess(math.dist(hose._start_frame(fitted)[1], args[2]), 1e-8)
        self.assertLess(math.dist(carrier.path_position(fitted, fitted['length_mm'])['tangent'], args[3]), 1e-8)
        hose._joined_path(fitted)
        self.assertEqual(fitted['bare_fit']['candidate_count'], 50)
        for values in ([], [0], [-1], [True], [math.nan]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                routing.bare_span(*args, tangent_distance_multipliers=values)

    def test_bare_candidates_retain_rejected_clearance_witnesses_and_choose_a_checked_branch(self):
        args = ([0, 65, 525], [-37, 0, 650.7], [0, 1, 0], [1, 0, 0], 12)
        def check(path):
            return {'passed': path['length_mm'] >= 200, 'scope': 'Synthetic branch-selection fixture',
                    'witness': {'length_mm': path['length_mm']}}
        path = routing.bare_span(*args, tangent_distance_multipliers=[1, 1.5, 2, 3, 4, 6, 8], candidate_check=check)
        evidence = path['bare_fit']
        self.assertGreaterEqual(path['length_mm'], 200)
        self.assertTrue(evidence['selected_clearance']['passed'])
        self.assertTrue(evidence['clearance_rejections'])
        self.assertTrue(all(row['length_mm'] < 200 and not row['clearance']['passed']
                            for row in evidence['clearance_rejections']))
        with self.assertRaises(routing.RoutingEvidenceError):
            routing.bare_span(*args, tangent_distance_multipliers=[1, 2],
                              candidate_check=lambda path: {'passed': True, 'scope': 'Bad evidence', 'gap': math.nan})
        with self.assertRaises(routing.RouteClearanceError):
            routing.bare_span(*args, candidate_check=lambda path: {'passed': False, 'scope': 'Rejected test branch'})

    def path(self, length, slack):
        path = hose.centerline([[0, 0, 0], [length, 0, 0]])
        path['carrier_path'] = hose.centerline([[0, 0, 0], [100, 0, 0]], 50)
        path['length_accounting'] = {
            'inserted_mm': 12, 'socket_strain_relief_mm': 20,
            'connector_straight_leads_mm': 20, 'clip_supported_mm': 10,
            'carrier_supported_mm': 100, 'free_bare_spans_mm': length-162,
            'total_mm': length, 'sum_error_mm': 0, 'service_loop_parameter_mm': slack}
        return path

    def compile(self, evaluate, clear=None, samples=(0, 10, 20), allowances=None, states=('a', 'b')):
        if clear is None:
            clear = lambda path, state, slack: {'passed': True, 'scope': 'Synthetic clearance fixture only'}
        if allowances is None:
            allowances = [{'id': 'cut_tolerance', 'value_mm': 2, 'reason': 'Synthetic cutting tolerance'}]
        return routing.compile_named_band(states, evaluate, samples, p=self.PARAMETERS,
            clearance_check=clear, allowances=allowances, self_sample_step_mm=5)

    def test_common_cut_has_independently_solved_routes_and_exact_material_partition(self):
        def evaluate(name, slack):
            return self.path((200+slack) if name == 'a' else (210+2*slack), slack)
        report = self.compile(evaluate)
        self.assertEqual(report['status'], 'demonstrated')
        self.assertEqual(report['common_band']['lower_mm'], 210)
        self.assertEqual(report['common_band']['upper_mm'], 220)
        self.assertEqual(report['cut_selection']['selected_cut_mm'], 212)
        for name, loop in [('a', 12), ('b', 1)]:
            row = report['selected_states'][name]
            self.assertAlmostEqual(row['loop_parameter_mm'], loop)
            self.assertAlmostEqual(row['route']['length_mm'], 212)
            partition = row['material_partition']
            self.assertAlmostEqual(sum(partition[k] for k in ('inserted_mm', 'socket_strain_relief_mm',
                'connector_straight_leads_mm', 'clip_supported_mm', 'carrier_supported_mm', 'free_bare_spans_mm')), 212)
        self.assertTrue(all(v is False for v in report['qualification'].values()))
        self.assertIn('hulls only', report['common_band']['scope'])

    def test_clearance_gap_inside_the_length_hull_cannot_be_reported_as_feasible(self):
        def evaluate(name, slack):
            return self.path(200+slack, slack)
        def clearance(path, name, slack):
            return {'passed': not 5 < slack < 15, 'scope': 'Synthetic forbidden middle interval'}
        report = self.compile(evaluate, clearance, allowances=[
            {'id': 'cut_tolerance', 'value_mm': 12, 'reason': 'Selected cut falls inside the test gap'}], states=('a',))
        self.assertTrue(report['common_band']['nonempty'])
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['selected_states'], {})
        self.assertEqual(report['states']['a']['samples'][1]['classification'], 'clearance')
        self.assertEqual([run['sample_indices'] for run in report['states']['a']['consecutive_passed_sample_runs']], [[0], [2]])
        self.assertEqual(report['failures'][0]['classification'], 'selected_cut_not_demonstrated')

    def test_nonmonotonic_length_curve_is_solved_locally_and_rounding_is_itemized(self):
        report = self.compile(lambda name, slack: self.path(200+abs(slack-10), slack), states=('a',),
            allowances=[{'id': 'cut_tolerance', 'value_mm': 2.25, 'reason': 'Synthetic allowance'}])
        self.assertEqual(report['status'], 'demonstrated')
        self.assertEqual(report['cut_selection']['selected_cut_mm'], 203)
        self.assertAlmostEqual(report['cut_selection']['rounding_allowance_mm'], .75)
        self.assertAlmostEqual(report['selected_states']['a']['loop_parameter_mm'], 7)

    def test_bend_failures_keep_their_witness_and_missing_clearance_blocks_selection(self):
        def evaluate(name, slack):
            if slack == 0:
                raise hose.HoseBendError('Test corner does not fit', {'segment_index': 2, 'required_radius_mm': 12})
            return self.path(200+slack, slack)
        report = self.compile(evaluate, states=('a',))
        self.assertEqual(report['states']['a']['samples'][0]['classification'], 'bend')
        self.assertEqual(report['states']['a']['samples'][0]['witness']['segment_index'], 2)
        report = routing.compile_named_band(['a'], lambda name, slack: self.path(200+slack, slack),
            [0, 10], p=self.PARAMETERS, clearance_check=None, allowances=[], self_sample_step_mm=5)
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(all(row['classification'] == 'clearance_not_evaluated' for row in report['states']['a']['samples']))

    def test_allowances_and_loop_samples_are_finite_and_have_explicit_reasons(self):
        evaluate = lambda name, slack: self.path(200+slack, slack)
        for samples in ([0], [0, math.inf], [-1, 0], [0, True]):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                self.compile(evaluate, samples=samples)
        for allowances in ([{'id': 'x', 'value_mm': 1, 'reason': ''}],
                           [{'id': 'x', 'value_mm': -1, 'reason': 'Invalid'}],
                           [{'id': 'x', 'value_mm': 1, 'reason': 'a'}, {'id': 'x', 'value_mm': 1, 'reason': 'b'}]):
            with self.subTest(allowances=allowances), self.assertRaises(ValueError):
                self.compile(evaluate, allowances=allowances)

    def test_malformed_lengths_or_clearance_evidence_are_fatal_not_geometric_failures(self):
        def bad_length(name, slack):
            path = self.path(200+slack, slack)
            if slack == 10:
                path['length_mm'] = math.nan
            return path
        with self.assertRaises(routing.RoutingEvidenceError):
            self.compile(bad_length)
        def bad_solver_length(name, slack):
            path = self.path(200+slack, slack)
            if 0 < slack < 10:
                path['length_mm'] = math.inf
            return path
        with self.assertRaises(routing.RoutingEvidenceError):
            self.compile(bad_solver_length, samples=(0, 10), states=('a',))
        def bad_clearance(path, name, slack):
            return {'passed': True, 'scope': 'Malformed test evidence', 'margin_mm': math.nan}
        with self.assertRaises(ValueError):
            self.compile(lambda name, slack: self.path(200+slack, slack), bad_clearance)


if __name__ == '__main__':
    unittest.main()
