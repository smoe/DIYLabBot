"""Synthetic TS01 identity/metric contract, not native-export qualification."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import TaskError, digest, encoded
import tapestation_results as ts


def expected(count=1):
    return {'workflow_run_id': 'SYN.DNeasy.Run', 'instrument_run_id': 'SYN.TS.Run',
            'analysis_id': 'SYN.TS.Analysis', 'instrument_id': 'TS01',
            'assay_id': 'GenomicDNA.ScreenTape', 'assay_revision': 'SYN.1',
            'measurements': [
                {'measurement_id': 'Measure.%d' % index, 'lane_id': 'A%d' % (index + 2),
                 'sample_id': 'Source.%d' % index, 'product_material_id': 'DNA.%d' % index,
                 'product_vessel_id': 'EluateTube.%d' % index, 'product_content_revision': 4,
                 'aliquot_material_id': 'QC.%d' % index, 'aliquot_vessel_id': 'QCTube.%d' % index,
                 'aliquot_content_revision': 1} for index in range(count)]}


def artifact(value):
    return encoded(value).encode('utf-8')


class TapeStationResultTests(unittest.TestCase):
    POLICY = {'minimum_din': 6.0, 'minimum_fragment_size_bp': 10000.0}

    def setUp(self):
        self.mapping = expected()
        self.raw = ts.synthetic_report(self.mapping)
        self.value = json.loads(self.raw)

    def test_leading_contract_retains_existing_unqualified_TS01_and_assay_references(self):
        protocol = ts.load_protocol()
        self.assertEqual(protocol['instrument']['source']['source'], 'model/tapestation.shared.json')
        self.assertIsNone(protocol['instrument']['selected_model'])
        self.assertEqual(protocol['instrument']['planning_reference'], '4200 TapeStation')
        self.assertEqual(protocol['assay']['sample_volume_ul'], 1)
        self.assertEqual(protocol['assay']['sample_buffer_volume_ul'], 10)
        self.assertEqual(protocol['assay']['ladder_volume_ul'], 1)
        self.assertEqual(protocol['assay']['ladder_buffer_volume_ul'], 10)
        self.assertEqual(protocol['assay']['ladder_position'], 'A1')
        self.assertEqual(protocol['assay']['preparation'], {'buffer_equilibration_s': 1800,
            'mix_duration_s': 60, 'mix_rpm': 2000, 'spin_duration_s': 60})
        self.assertEqual(ts.MAX_REPORT_BYTES, protocol['limits']['max_report_bytes'])
        self.assertEqual(protocol['source_sha256'], digest(ts.SOURCE.read_bytes()))

    def test_valid_report_preserves_raw_checksum_and_independent_metrics_without_accepting_it(self):
        parsed = ts.parse_report(self.raw, self.mapping)
        self.assertEqual(parsed['artifact_sha256'], digest(self.raw))
        self.assertEqual(parsed['rows'], self.value['rows'])
        self.assertEqual(parsed['issues'], [])
        self.assertFalse(parsed['synthetic_policy_passed'])
        result = ts.evaluate(parsed['rows'][0], self.POLICY)
        self.assertTrue(result['synthetic_policy_passed'])
        self.assertTrue(result['review_required'])
        self.assertFalse(result['analytical_qualified'])
        self.assertFalse(result['hardware_executed'])
        # A normal DNeasy fragment estimate is outside the narrower accuracy reference.
        self.assertFalse(result['sizing_accuracy_reference_applicable'])

    def test_reordered_rows_are_matched_by_identity_and_never_row_position(self):
        mapping = expected(2)
        value = json.loads(ts.synthetic_report(mapping))
        value['rows'].reverse()
        parsed = ts.parse_report(artifact(value), mapping)
        self.assertEqual([row['measurement_id'] for row in parsed['rows']], ['Measure.1', 'Measure.0'])

    def test_every_top_identity_must_match_explicit_workflow_mapping(self):
        for name in ts.TOP_FIELDS:
            value = copy.deepcopy(self.value); value[name] = 'Foreign.Identity'
            with self.subTest(field=name), self.assertRaises(TaskError):
                ts.parse_report(artifact(value), self.mapping)

    def test_every_sample_product_aliquot_revision_and_lane_identity_must_match(self):
        for name in ts.IDENTITY_FIELDS:
            value = copy.deepcopy(self.value)
            value['rows'][0][name] = 999 if name in ts.REVISION_FIELDS else 'Foreign.Identity'
            with self.subTest(field=name), self.assertRaises(TaskError):
                ts.parse_report(artifact(value), self.mapping)

    def test_missing_and_foreign_measurements_are_rejected(self):
        for rows in [[], self.value['rows'] * 2]:
            value = {**self.value, 'rows': rows}
            with self.assertRaises(TaskError): ts.parse_report(artifact(value), self.mapping)
        value = copy.deepcopy(self.value); value['rows'][0]['measurement_id'] = 'Unmapped.Measure'
        with self.assertRaises(TaskError): ts.parse_report(artifact(value), self.mapping)

    def test_duplicate_reported_or_expected_lanes_and_aliquots_are_rejected(self):
        mapping = expected(2)
        value = json.loads(ts.synthetic_report(mapping))
        for name in ['measurement_id', 'lane_id', 'aliquot_material_id', 'aliquot_vessel_id']:
            duplicate = copy.deepcopy(value); duplicate['rows'][1][name] = duplicate['rows'][0][name]
            with self.subTest(field=name), self.assertRaises(TaskError):
                ts.parse_report(artifact(duplicate), mapping)
            bad_mapping = copy.deepcopy(mapping)
            bad_mapping['measurements'][1][name] = bad_mapping['measurements'][0][name]
            with self.subTest(expected_field=name), self.assertRaises(TaskError):
                ts.parse_report(artifact(value), bad_mapping)

    def test_report_size_rows_and_original_byte_type_are_bounded(self):
        for content in [b'', self.raw.decode(), b' ' * (ts.MAX_REPORT_BYTES + 1)]:
            with self.assertRaises(TaskError): ts.parse_report(content, self.mapping)
        value = {**self.value, 'rows': self.value['rows'] * 97}
        with self.assertRaises(TaskError): ts.parse_report(artifact(value), self.mapping)

    def test_explicit_synthetic_marker_and_exact_shape_are_required(self):
        for extra in [{'synthetic': False}, {'format': 'agilent.native.report'}, {'sample_name': 'Source.0'}]:
            value = {**self.value, **extra}
            with self.assertRaises(TaskError): ts.parse_report(artifact(value), self.mapping)
        value = copy.deepcopy(self.value); value['rows'][0]['sample_name'] = 'Source.0'
        with self.assertRaises(TaskError): ts.parse_report(artifact(value), self.mapping)

    def test_duplicate_json_fields_nonfinite_values_and_deep_json_are_rejected(self):
        for raw in [b'{"format":"one","format":"two"}', b'{"number":NaN}', b'{"number":Infinity}',
                    b'\xff\xfeinvalid', b'[' * 1500 + b'0' + b']' * 1500]:
            with self.assertRaises(TaskError): ts.parse_report(raw, self.mapping)

    def test_booleans_nonfinite_and_negative_revisions_or_metrics_are_rejected(self):
        cases = [('din', True), ('din', 0), ('din', 11), ('sample_concentration_ng_ul', True),
                 ('sample_concentration_ng_ul', -1), ('product_content_revision', True),
                 ('aliquot_content_revision', -1)]
        for name, bad in cases:
            value = copy.deepcopy(self.value); value['rows'][0][name] = bad
            with self.subTest(field=name, bad=bad), self.assertRaises(TaskError):
                ts.parse_report(artifact(value), self.mapping)

    def test_null_metrics_are_retained_and_block_synthetic_policy_success(self):
        raw = ts.synthetic_report(self.mapping, din=None, fragment_size_bp=None,
                                  size_qualifier='unavailable', sample_concentration_ng_ul=None)
        parsed = ts.parse_report(raw, self.mapping)
        self.assertIsNone(parsed['rows'][0]['din'])
        result = ts.evaluate(parsed['rows'][0], self.POLICY)
        self.assertFalse(result['synthetic_policy_passed'])
        self.assertIn('din_unavailable', result['issues'])
        self.assertIn('fragment_size_unavailable', result['issues'])
        self.assertIn('din_functional_concentration_unknown', result['issues'])

    def test_censored_sizing_keeps_no_precise_value_and_never_automatically_passes(self):
        raw = ts.synthetic_report(self.mapping, fragment_size_bp=None, size_qualifier='above_sizing_range')
        row = ts.parse_report(raw, self.mapping)['rows'][0]
        self.assertIsNone(row['fragment_size']['value'])
        self.assertFalse(ts.evaluate(row, self.POLICY)['synthetic_policy_passed'])
        with self.assertRaises(TaskError):
            ts.synthetic_report(self.mapping, fragment_size_bp=100000, size_qualifier='above_sizing_range')

    def test_out_of_range_size_is_retained_as_reported_estimate_but_blocks_success(self):
        for size in [100, 60001]:
            raw = ts.synthetic_report(self.mapping, fragment_size_bp=size)
            parsed = ts.parse_report(raw, self.mapping)
            self.assertEqual(parsed['rows'][0]['fragment_size']['value'], size)
            result = ts.evaluate(parsed['rows'][0], self.POLICY)
            self.assertFalse(result['synthetic_policy_passed'])
            self.assertIn('fragment_size_out_of_reference_range', result['issues'])

    def test_concentration_range_is_separate_from_fragment_length_and_DIN_scale(self):
        for concentration in [0, 4.99, 300.01]:
            row = ts.parse_report(ts.synthetic_report(self.mapping, sample_concentration_ng_ul=concentration), self.mapping)['rows'][0]
            self.assertFalse(ts.evaluate(row, self.POLICY)['synthetic_policy_passed'])
        row = ts.parse_report(ts.synthetic_report(self.mapping, sample_concentration_ng_ul=5), self.mapping)['rows'][0]
        result = ts.evaluate(row, self.POLICY)
        self.assertTrue(result['synthetic_policy_passed'])
        self.assertFalse(result['concentration_quantitative_reference_applicable'])

    def test_flags_and_original_messages_are_preserved_and_prevent_silent_acceptance(self):
        flags, messages = ['vendor_new_flag'], ['Original instrument warning remains intact.']
        raw = ts.synthetic_report(self.mapping, flags=flags, messages=messages)
        row = ts.parse_report(raw, self.mapping)['rows'][0]
        self.assertEqual(row['flags'], flags); self.assertEqual(row['messages'], messages)
        evaluation = ts.evaluate(row, self.POLICY)
        self.assertFalse(evaluation['synthetic_policy_passed'])
        self.assertIn('unknown_instrument_flag', evaluation['issues'])
        self.assertIn('instrument_messages_present', evaluation['issues'])

    def test_messages_are_bounded_single_line_and_flags_are_distinct(self):
        for flags, messages in [(['same', 'same'], []), ([], ['bad\nmessage']),
                                ([], ['x'] * 33), ([], ['x' * 2049])]:
            with self.assertRaises(TaskError): ts.synthetic_report(self.mapping, flags=flags, messages=messages)

    def test_fragment_metric_requires_explicit_supported_method_and_units(self):
        for name, bad in [('method', 'din_inferred'), ('unit', 'kb'), ('qualifier', 'guaranteed')]:
            value = copy.deepcopy(self.value); value['rows'][0]['fragment_size'][name] = bad
            with self.assertRaises(TaskError): ts.parse_report(artifact(value), self.mapping)
        row = ts.parse_report(ts.synthetic_report(self.mapping, size_method='smear_mean'), self.mapping)['rows'][0]
        self.assertEqual(row['fragment_size']['method'], 'smear_mean')

    def test_policy_is_explicit_synthetic_and_low_values_fail_without_relabeling_raw_data(self):
        row = ts.parse_report(self.raw, self.mapping)['rows'][0]
        original = copy.deepcopy(row)
        self.assertIn('synthetic_review_policy_missing', ts.evaluate(row)['issues'])
        self.assertFalse(ts.evaluate(row, {'minimum_din': 9, 'minimum_fragment_size_bp': 10000})['synthetic_policy_passed'])
        self.assertFalse(ts.evaluate(row, {'minimum_din': 6, 'minimum_fragment_size_bp': 40000})['synthetic_policy_passed'])
        self.assertEqual(row, original)
        for policy in [{}, {**self.POLICY, 'native_qualified': True}, {'minimum_din': True, 'minimum_fragment_size_bp': 10}]:
            with self.assertRaises(TaskError): ts.evaluate(row, policy)

    def test_decoded_rows_are_detached_from_input_mapping_and_protocol(self):
        mapping = copy.deepcopy(self.mapping); protocol = ts.load_protocol()
        before = copy.deepcopy(protocol)
        parsed = ts.parse_report(self.raw, mapping, protocol)
        parsed['rows'][0]['flags'].append('later_mutation')
        self.assertEqual(protocol, before)
        self.assertEqual(mapping, self.mapping)
        self.assertEqual(ts.parse_report(self.raw, mapping, protocol)['rows'][0]['flags'], [])

    def test_supported_reference_accuracy_interval_does_not_become_device_qualification(self):
        row = ts.parse_report(ts.synthetic_report(self.mapping, fragment_size_bp=12000), self.mapping)['rows'][0]
        result = ts.evaluate(row, self.POLICY)
        self.assertTrue(result['sizing_accuracy_reference_applicable'])
        self.assertFalse(result['analytical_qualified'])


class TapeStationSchemaTests(unittest.TestCase):
    def test_protocol_mapping_report_and_policy_match_formal_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema development dependency required')
        schema = json.loads(ts.SCHEMA.read_bytes())
        Draft202012Validator.check_schema(schema)
        for definition, value in [('protocol', json.loads(ts.SOURCE.read_bytes())),
                                  ('expected', expected()),
                                  ('report', json.loads(ts.synthetic_report(expected()))),
                                  ('policy', TapeStationResultTests.POLICY)]:
            validator = Draft202012Validator({**schema, '$ref': '#/$defs/' + definition})
            with self.subTest(definition=definition): validator.validate(value)


if __name__ == '__main__':
    unittest.main()
