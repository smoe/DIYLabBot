"""Canonical consumption and explicit assay/external-dilution boundaries."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import dna_quantification_ledger as ledger
from manual_tasks import TaskError
from manual_workflow import ObservationError


def state(initial=40):
    return {'run_id': 'SYN.DNA.01', 'logical_time_s': 0.0, 'bookings': {},
            'inventory': {'vessels': {'Original': {
                'id': 'Original', 'kind': 'original', 'origin': 'original',
                'sample_id': 'DNA01', 'initial_volume_ul': initial,
                'home': {'kind': 'rack', 'rack_id': 'InputRack', 'place_id': 'Slot01'},
                'location': {'kind': 'rack', 'rack_id': 'InputRack', 'place_id': 'Slot01'},
                'content_revision': 0, 'volume_uncertain': False,
                'mass_confirmation_valid': True}}}}


def reserve(root, identity='I01', source='Original', amount=2):
    return ledger.reserve_withdrawal(root, intent_id=identity, source_vessel_id=source,
        planned_volume_ul=amount, stage_id='nanodrop', attempt_id='A01',
        target={'kind': 'discarded_after_cleanup'}, actor_id='SYN.Operator01')


ND = {'range': {'basis': 'selected_input_concentration', 'unit': 'ng/uL',
                'lower': 2.0, 'lower_kind': 'limit_of_detection_not_lloq', 'upper': 27500.0}}
QB = {'assay_total_volume_ul': 200, 'sample_volume_ul_min': 1, 'sample_volume_ul_max': 20,
      'range': {'basis': 'assay_dna_mass', 'unit': 'ng', 'lower': 0.1, 'upper': 120}}


def nd(value=10, unit='ng/uL', flags=None):
    return {'measurement_id': 'ND.M01', 'metrics': {
        'concentration': {'value': value, 'unit': unit},
        'factor': {'value': 50, 'unit': None}},
        'raw_cells': {'Sample Name': 'ND.M01', 'Factor': '50'},
        'instrument_messages': {} if flags is None else flags}


def qb(tube=0.2, original=20, unit='ng/uL', flags=None):
    return {'measurement_id': 'QB.M01', 'metrics': {
        'tube_concentration': {'value': tube, 'unit': unit, 'basis': 'reported'},
        'original_concentration': {'value': original, 'unit': 'ng/uL', 'basis': 'reported'}},
        'raw_cells': {'Original Concentration': str(original)},
        'instrument_messages': {} if flags is None else flags}


class CanonicalDNALedgerTests(unittest.TestCase):
    def test_intent_precedes_single_confirmed_debit(self):
        root = state()
        self.assertEqual(ledger.remaining(root, 'Original'), 40)
        record = reserve(root)
        self.assertEqual(record['outcome'], 'intent')
        self.assertIsNone(record['actual_volume_ul'])
        self.assertIsNone(ledger.remaining(root, 'Original'))
        self.assertEqual(ledger.remaining(root, 'Original', exclude_intent='I01'), 40)
        self.assertFalse(root['inventory']['vessels']['Original']['mass_confirmation_valid'])
        root['logical_time_s'] = 3.0
        ledger.confirm_withdrawal(root, 'I01', 2)
        self.assertEqual(ledger.remaining(root, 'Original'), 38)
        self.assertEqual(root['bookings']['I01']['confirmed_at_s'], 3.0)
        self.assertEqual(root['inventory']['vessels']['Original']['content_revision'], 1)
        self.assertFalse(root['inventory']['vessels']['Original']['volume_uncertain'])
        before = copy.deepcopy(root)
        with self.assertRaisesRegex(TaskError, 'already resolved'):
            ledger.confirm_withdrawal(root, 'I01', 2)
        self.assertEqual(root, before)

    def test_compatibility_flag_does_not_replace_the_consumption_intent(self):
        root = state()
        root['inventory']['vessels']['Original']['volume_uncertain'] = True
        reserve(root)
        with self.assertRaisesRegex(TaskError, 'previous source withdrawal'):
            reserve(root, 'I02')
        self.assertNotIn('I02', root['bookings'])

    def test_unknown_initial_and_unknown_outcome_are_not_zero_or_planned_debits(self):
        root = state(None)
        reserve(root)
        root['bookings']['I01']['outcome'] = 'unknown'
        ledger.confirm_withdrawal(root, 'I01', 100, reason='Explicit observed amount')
        self.assertIsNone(ledger.remaining(root, 'Original'))
        self.assertEqual(root['bookings']['I01']['actual_volume_ul'], 100)
        root = state()
        reserve(root)
        root['bookings']['I01']['outcome'] = 'unknown'
        self.assertIsNone(ledger.remaining(root, 'Original'))
        ledger.resolve_not_performed(root, 'I01')
        self.assertEqual(ledger.remaining(root, 'Original'), 40)

    def test_not_performed_closes_intent_without_restoring_mass_or_incrementing_revision(self):
        root = state()
        reserve(root)
        ledger.resolve_not_performed(root, 'I01')
        vessel = root['inventory']['vessels']['Original']
        self.assertEqual(vessel['content_revision'], 0)
        self.assertFalse(vessel['mass_confirmation_valid'])
        self.assertFalse(vessel['volume_uncertain'])
        self.assertEqual(root['bookings']['I01']['actual_volume_ul'], 0)
        with self.assertRaises(TaskError):
            ledger.resolve_not_performed(root, 'I01')
        with self.assertRaisesRegex(TaskError, 'identity was already used'):
            reserve(root)

    def test_new_intent_never_overbooks_known_remaining_volume(self):
        root = state(3)
        reserve(root)
        ledger.confirm_withdrawal(root, 'I01', 2)
        before = copy.deepcopy(root)
        with self.assertRaisesRegex(TaskError, 'Insufficient recorded volume'):
            reserve(root, 'I02', amount=2)
        self.assertEqual(root, before)
        reserve(root, 'I02', amount=1)
        ledger.confirm_withdrawal(root, 'I02', 1)
        self.assertEqual(ledger.remaining(root, 'Original'), 0)

    def test_actual_excess_leaves_the_intent_uncertain_and_unchanged(self):
        root = state(3)
        reserve(root)
        before = copy.deepcopy(root)
        with self.assertRaisesRegex(ObservationError, 'exceeds remaining'):
            ledger.confirm_withdrawal(root, 'I01', 4, reason='Observed excess')
        self.assertEqual(root, before)
        self.assertIsNone(ledger.remaining(root, 'Original'))

    def test_actual_deviation_requires_a_reason_and_uses_the_actual_debit(self):
        root = state()
        reserve(root)
        before = copy.deepcopy(root)
        with self.assertRaisesRegex(TaskError, 'volume deviation'):
            ledger.confirm_withdrawal(root, 'I01', 3)
        self.assertEqual(root, before)
        ledger.confirm_withdrawal(root, 'I01', 3, reason='Explicit synthetic transfer deviation')
        self.assertEqual(ledger.remaining(root, 'Original'), 37)

    def test_dilution_and_assay_withdrawals_debit_their_own_vessels(self):
        root = state()
        reserve(root, 'DilutionTransfer')
        ledger.confirm_withdrawal(root, 'DilutionTransfer', 2)
        root['inventory']['vessels']['Dilution'] = {
            **copy.deepcopy(root['inventory']['vessels']['Original']),
            'id': 'Dilution', 'kind': 'dilution', 'origin': 'derived',
            'parent_vessel_id': 'Original', 'initial_volume_ul': 20,
            'content_revision': 0, 'external_factor': ledger.dilution_factor(2, 18)}
        reserve(root, 'ND', source='Dilution', amount=1.5)
        ledger.confirm_withdrawal(root, 'ND', 1.5)
        reserve(root, 'QB', source='Dilution', amount=2)
        ledger.confirm_withdrawal(root, 'QB', 2)
        self.assertEqual(ledger.remaining(root, 'Original'), 38)
        self.assertEqual(ledger.remaining(root, 'Dilution'), 16.5)

    def test_invalid_numeric_inputs_never_create_or_confirm_bookings(self):
        for value in [True, False, None, 0, -1, float('nan'), float('inf'), 10**1000]:
            with self.subTest(value=repr(value)):
                root = state()
                before = copy.deepcopy(root)
                with self.assertRaises(TaskError):
                    reserve(root, amount=value)
                self.assertEqual(root, before)
                reserve(root)
                before = copy.deepcopy(root)
                with self.assertRaises(TaskError):
                    ledger.confirm_withdrawal(root, 'I01', value)
                self.assertEqual(root, before)

    def test_unknown_and_discarded_sources_are_rejected(self):
        root = state()
        with self.assertRaisesRegex(TaskError, 'Unknown source vessel'):
            reserve(root, source='Foreign')
        root['inventory']['vessels']['Original']['location'] = {'kind': 'discarded'}
        with self.assertRaisesRegex(TaskError, 'Discarded material'):
            reserve(root)

    def test_intent_target_is_copied_and_returned_record_is_not_authoritative(self):
        root = state()
        record = reserve(root)
        record['outcome'] = 'performed'
        record['target']['kind'] = 'elsewhere'
        self.assertEqual(root['bookings']['I01']['outcome'], 'intent')
        self.assertEqual(root['bookings']['I01']['target']['kind'], 'discarded_after_cleanup')

    def test_confirmed_dilution_parts_produce_factors_ten_and_twenty(self):
        self.assertEqual(ledger.dilution_factor(2, 18), 10)
        self.assertEqual(ledger.dilution_factor(2, 38), 20)
        self.assertEqual(ledger.dilution_factor(2, 19), 10.5)
        for a, b in [(0, 9), (1, 0), (True, 9), (1, float('nan')), (1e308, 1e308)]:
            with self.subTest(sample=a, diluent=b):
                with self.assertRaises(TaskError):
                    ledger.dilution_factor(a, b)


class InputRangeProjectionTests(unittest.TestCase):
    def classify_qubit(self, result=None, **kwargs):
        return ledger.classify_input(qb() if result is None else result, 'qubit', QB,
                                     sample_volume_ul=2, total_volume_ul=200, **kwargs)

    def test_nanodrop_factor_cell_is_not_external_predilution(self):
        result = nd(10)
        original = copy.deepcopy(result)
        evaluation = ledger.classify_input(result, 'nanodrop', ND, external_factor=20)
        self.assertEqual(evaluation['status'], 'in_range')
        self.assertEqual(evaluation['selected_input_concentration']['value'], 10)
        self.assertEqual(evaluation['root_original_concentration']['value'], 200)
        self.assertEqual(evaluation['root_original_concentration']['external_factor'], 20)
        self.assertEqual(result, original)

    def test_qubit_assay_mass_and_original_input_have_separate_bases(self):
        result = qb(tube=0.2, original=20)
        original = copy.deepcopy(result)
        evaluation = self.classify_qubit(result, external_factor=10)
        self.assertEqual(evaluation['status'], 'in_range')
        self.assertEqual(evaluation['measured_basis'], 'assay_dna_mass')
        self.assertEqual(evaluation['measured_value'], 40)
        self.assertEqual(evaluation['measured_unit'], 'ng')
        self.assertEqual(evaluation['selected_input_concentration']['value'], 20)
        self.assertEqual(evaluation['root_original_concentration']['value'], 200)
        self.assertEqual(evaluation['root_original_concentration']['source_basis'], 'reported')
        self.assertEqual(result, original)

    def test_qubit_bounds_follow_tube_mass_before_external_correction(self):
        low = self.classify_qubit(qb(tube=0.0004, original=0.04), external_factor=20)
        high = self.classify_qubit(qb(tube=0.7, original=70), external_factor=1)
        self.assertEqual(low['status'], 'below_range')
        self.assertEqual(high['status'], 'above_range')
        self.assertFalse(low['quantifiable'])
        self.assertEqual(low['root_original_concentration']['value'], 0.8)
        for value in [0.0005, 0.6]:
            with self.subTest(tube=value):
                self.assertEqual(self.classify_qubit(qb(tube=value))['status'], 'in_range')

    def test_supported_units_are_normalized_once(self):
        evaluation = self.classify_qubit(qb(tube=200, original=20, unit='ng/mL'))
        self.assertAlmostEqual(evaluation['measured_value'], 40)
        result = qb()
        result['metrics']['original_concentration'] = {'value': 20000, 'unit': 'ng/mL', 'basis': 'reported'}
        self.assertEqual(self.classify_qubit(result)['selected_input_concentration']['value'], 20)

    def test_negative_nanodrop_reading_remains_below_detection_and_unquantifiable(self):
        result = nd(-0.3)
        evaluation = ledger.classify_input(result, 'nanodrop', ND)
        self.assertEqual(evaluation['status'], 'below_range')
        self.assertFalse(evaluation['quantifiable'])
        self.assertEqual(result['metrics']['concentration']['value'], -0.3)

    def test_nanodrop_endpoints_and_low_signal_are_distinguished(self):
        for value, status in [(1.9, 'below_range'), (2, 'in_range'),
                              (27500, 'in_range'), (27501, 'above_range')]:
            with self.subTest(value=value):
                self.assertEqual(ledger.classify_input(nd(value), 'nanodrop', ND)['status'], status)

    def test_invalid_or_missing_metrics_do_not_become_accepted_values(self):
        for value in [None, True, float('nan'), float('inf')]:
            with self.subTest(value=value):
                self.assertEqual(ledger.classify_input(nd(value), 'nanodrop', ND)['status'], 'unknown')
        for metric in [{'value': 10, 'unit': 'mg/mL'}, {'value': 10, 'unit': []}, None]:
            with self.subTest(metric=metric):
                result = nd()
                result['metrics']['concentration'] = metric
                self.assertEqual(ledger.classify_input(result, 'nanodrop', ND)['status'], 'unknown')
        self.assertEqual(ledger.classify_input({}, 'nanodrop', ND)['status'], 'unknown')

    def test_exact_synthetic_flags_are_conservative_and_unknown_flags_require_review(self):
        for flag, status in [('AboveRange', 'above_range'), ('BelowRange', 'below_range'),
                             ('SomeVendorWarning', 'unknown'), (None, 'unknown'), ([], 'unknown')]:
            with self.subTest(flag=flag):
                result = nd(flags={'Warnings': flag})
                before = copy.deepcopy(result)
                evaluation = ledger.classify_input(result, 'nanodrop', ND)
                self.assertEqual(evaluation['status'], status)
                self.assertFalse(evaluation['quantifiable'])
                self.assertEqual(evaluation['instrument_messages'], result['instrument_messages'])
                self.assertEqual(result, before)
        evaluation = ledger.classify_input(nd(30000, flags={'Warnings': 'BelowRange'}), 'nanodrop', ND)
        self.assertEqual(evaluation['status'], 'unknown')
        self.assertIn('contradicts', evaluation['issues'][0])

    def test_old_100_ul_recipe_and_undeclared_total_cannot_use_hs_bounds(self):
        evaluation = ledger.classify_input(qb(), 'qubit', QB,
                                           sample_volume_ul=2, total_volume_ul=100)
        self.assertEqual(evaluation['status'], 'unknown')
        missing = copy.deepcopy(QB)
        del missing['assay_total_volume_ul']
        self.assertEqual(ledger.classify_input(qb(), 'qubit', missing,
                         sample_volume_ul=2, total_volume_ul=200)['status'], 'unknown')

    def test_unknown_message_container_is_not_a_clean_report(self):
        for messages in [None, [], '', True]:
            with self.subTest(messages=messages):
                result = nd()
                result['instrument_messages'] = messages
                self.assertEqual(ledger.classify_input(result, 'nanodrop', ND)['status'], 'unknown')

    def test_sample_volume_and_range_configuration_are_bound(self):
        for sample in [True, 0, 0.5, 21, float('inf')]:
            with self.subTest(sample=sample):
                self.assertEqual(ledger.classify_input(qb(), 'qubit', QB,
                    sample_volume_ul=sample, total_volume_ul=200)['status'], 'unknown')
        for key, value in [('lower', None), ('upper', float('nan')), ('basis', 'unqualified'), ('unit', 'mg')]:
            config = copy.deepcopy(QB)
            config['range'][key] = value
            with self.subTest(key=key):
                self.assertEqual(ledger.classify_input(qb(), 'qubit', config,
                    sample_volume_ul=2, total_volume_ul=200)['status'], 'unknown')

    def test_invalid_external_factor_never_publishes_corrected_concentration(self):
        for factor in [0, 0.5, True, float('nan'), float('inf')]:
            with self.subTest(factor=factor):
                evaluation = ledger.classify_input(nd(), 'nanodrop', ND, external_factor=factor)
                self.assertEqual(evaluation['status'], 'unknown')
                self.assertIsNone(evaluation['root_original_concentration'])


if __name__ == '__main__':
    unittest.main()
