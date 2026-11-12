"""Explicit interval fixtures, never proposed laboratory parameters or proof."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from manual_tasks import TaskError
from cutrun_sop_evidence import evaluate_phase, validate_temperature, validate_time


class SopEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.identity = {'stage_run_id': 'Test.StageRun', 'phase_id': 'S04.antibody_incubation',
            'reaction_id': 'Test.Reaction', 'material_id': 'Test.Sample', 'vessel_id': 'Test.Tube'}
        self.qualifications = {
            'Test.TimeQualification': {'kind': 'time', 'source_id': 'Test.Clock', 'relationship': None,
                'evidence_ref': 'Test.ProspectiveClockEvidence'},
            'Test.TemperatureQualification': {'kind': 'temperature', 'source_id': 'Test.Probe',
                'relationship': 'sample_measurement', 'evidence_ref': 'Test.ProspectiveTemperatureEvidence'}}
        self.requirements = {'duration_min_s': 10, 'duration_max_s': 12,
            'temperature_min_deg_c': 3, 'temperature_max_deg_c': 5,
            'time_qualification_ref': 'Test.TimeQualification',
            'temperature_qualification_ref': 'Test.TemperatureQualification',
            'evidence_ref': 'Test.ProspectivePhaseDecision'}
        self.time = {**self.identity, 'evidence_id': 'Test.TimeEvidence', 'time_basis_id': 'Test.Clock',
            'qualification_ref': 'Test.TimeQualification', 'source_kind': 'test_fixture',
            'artifact_sha256': 'a' * 64, 'start_earliest_s': 0, 'start_latest_s': 1,
            'end_earliest_s': 11, 'end_latest_s': 12}
        self.temperature = {**self.identity, 'evidence_id': 'Test.TemperatureEvidence',
            'time_basis_id': 'Test.Clock', 'qualification_ref': 'Test.TemperatureQualification',
            'time_qualification_ref': 'Test.TimeQualification', 'source_id': 'Test.Probe',
            'source_kind': 'test_fixture', 'artifact_sha256': 'b' * 64,
            'from_earliest_s': 0, 'from_latest_s': 0, 'to_earliest_s': 12, 'to_latest_s': 12,
            'minimum_deg_c': 4, 'maximum_deg_c': 4, 'uncertainty_deg_c': 0.5}

    def evaluate(self, *, time=None, temperatures=None, requirements=None, qualifications=None):
        return evaluate_phase(self.time if time is None else time,
            [self.temperature] if temperatures is None else temperatures,
            self.requirements if requirements is None else requirements,
            self.qualifications if qualifications is None else qualifications)

    def codes(self, report):
        return {code.split(':', 1)[0] for code in report['issues']}

    def test_qualified_occurrence_bounds_and_complete_specimen_interval_pass(self):
        report = self.evaluate()
        self.assertTrue(report['complete']);self.assertTrue(report['conformant'])
        self.assertEqual(report['duration_bounds'], {'min_s': 10, 'max_s': 12})
        self.assertEqual(report['coverage'], {'required_from_s': 0, 'required_to_s': 12,
                                            'covered_through_s': 12, 'complete': True})
        self.assertEqual(report['issues'], [])

    def test_adjacent_intervals_cover_but_even_a_small_unmeasured_gap_does_not(self):
        first = {**self.temperature, 'to_earliest_s': 6, 'to_latest_s': 6}
        second = {**self.temperature, 'evidence_id': 'Test.Second', 'from_earliest_s': 6, 'from_latest_s': 6}
        self.assertTrue(self.evaluate(temperatures=[first, second])['conformant'])
        second.update(from_earliest_s=6.0000000001, from_latest_s=6.0000000001)
        self.assertIn('temperature_coverage_missing', self.codes(self.evaluate(temperatures=[first, second])))

    def test_endpoint_readings_do_not_supply_continuous_coverage(self):
        first = {**self.temperature, 'to_earliest_s': 0, 'to_latest_s': 0}
        last = {**self.temperature, 'evidence_id': 'Test.Last', 'from_earliest_s': 12, 'from_latest_s': 12}
        report = self.evaluate(temperatures=[first, last])
        self.assertFalse(report['coverage']['complete'])
        self.assertIn('temperature_coverage_missing', self.codes(report))

    def test_uncertain_observation_endpoints_cover_only_the_guaranteed_interval(self):
        record = {**self.temperature, 'from_latest_s': 1, 'to_earliest_s': 11}
        self.assertIn('temperature_coverage_missing', self.codes(self.evaluate(temperatures=[record])))

    def test_temperature_uncertainty_envelope_must_fit_the_whole_declared_range(self):
        record = {**self.temperature, 'uncertainty_deg_c': 1.1}
        self.assertIn('temperature_out_of_range', self.codes(self.evaluate(temperatures=[record])))
        record['uncertainty_deg_c'] = 1
        self.assertTrue(self.evaluate(temperatures=[record])['conformant'])

    def test_later_good_interval_does_not_erase_an_overlapping_bad_observation(self):
        bad = {**self.temperature, 'evidence_id': 'Test.Bad', 'minimum_deg_c': 9, 'maximum_deg_c': 9}
        for records in ([bad, self.temperature], [self.temperature, bad]):
            report = self.evaluate(temperatures=records)
            self.assertTrue(report['coverage']['complete'])
            self.assertFalse(report['conformant'])
            self.assertIn('temperature_out_of_range', self.codes(report))

    def test_a_bound_proxy_can_qualify_but_device_setpoint_cannot(self):
        for relationship, expected in [('qualified_proxy', True), ('device_setpoint', False), (None, False)]:
            with self.subTest(relationship=relationship):
                registry = copy.deepcopy(self.qualifications)
                registry['Test.TemperatureQualification']['relationship'] = relationship
                report = self.evaluate(qualifications=registry)
                self.assertEqual(report['conformant'], expected)
                if not expected:self.assertIn('temperature_unqualified', self.codes(report))

    def test_source_or_prospective_temperature_qualification_mismatch_cannot_cover(self):
        for field, value in [('source_id', 'Test.OtherProbe'), ('qualification_ref', 'Test.NotRegistered')]:
            with self.subTest(field=field):
                report = self.evaluate(temperatures=[{**self.temperature, field: value}])
                self.assertIn('temperature_unqualified', self.codes(report))

    def test_clock_domain_mismatch_cannot_be_converted_using_capture_timestamps(self):
        for field, value in [('time_basis_id', 'Test.OtherClock'), ('time_qualification_ref', 'Test.NotRegistered')]:
            with self.subTest(field=field):
                report = self.evaluate(temperatures=[{**self.temperature, field: value}])
                self.assertIn('temperature_time_unqualified', self.codes(report))
        with self.assertRaises(TaskError):
            validate_time({**self.time, 'capture_utc': '2026-11-12T12:00:00Z'}, self.identity, self.qualifications)

    def test_time_qualification_must_match_the_prospective_binding(self):
        for record in ({**self.time, 'qualification_ref': None},
                       {**self.time, 'time_basis_id': 'Test.OtherClock'}):
            self.assertIn('time_unqualified', self.codes(self.evaluate(time=record)))
        registry = copy.deepcopy(self.qualifications)
        registry['Test.OtherQualification'] = registry['Test.TimeQualification']
        self.assertIn('time_unqualified', self.codes(self.evaluate(
            time={**self.time, 'qualification_ref': 'Test.OtherQualification'}, qualifications=registry)))

    def test_open_requirements_are_not_defaults_or_success(self):
        requirements = dict.fromkeys(self.requirements)
        report = self.evaluate(requirements=requirements, qualifications={})
        self.assertFalse(report['complete'])
        self.assertIn('requirements_open', self.codes(report))
        self.assertEqual(requirements, dict.fromkeys(self.requirements))

    def test_unknown_occurrence_endpoints_remain_unknown_duration(self):
        for field, bound in [('start_latest_s', 'min_s'), ('end_earliest_s', 'min_s'),
                             ('start_earliest_s', 'max_s'), ('end_latest_s', 'max_s')]:
            with self.subTest(field=field):
                report = self.evaluate(time={**self.time, field: None})
                self.assertIsNone(report['duration_bounds'][bound])
                self.assertIn('duration_unknown', self.codes(report))

    def test_unknown_temperature_and_uncertainty_do_not_fill_coverage(self):
        for field in ('minimum_deg_c', 'maximum_deg_c', 'uncertainty_deg_c'):
            with self.subTest(field=field):
                report = self.evaluate(temperatures=[{**self.temperature, field: None}])
                self.assertIn('temperature_unknown', self.codes(report))
                self.assertFalse(report['coverage']['complete'])

    def test_early_and_overdue_intervals_are_preserved_but_nonconformant(self):
        report = self.evaluate(time={**self.time, 'end_earliest_s': 9, 'end_latest_s': 10})
        self.assertIn('duration_below_minimum', self.codes(report))
        report = self.evaluate(time={**self.time, 'end_latest_s': 13})
        self.assertIn('duration_above_maximum', self.codes(report))

    def test_uncertain_endpoint_order_is_not_nominal_duration_evidence(self):
        record = {**self.time, 'start_latest_s': 11.5}
        self.assertIn('occurrence_order_uncertain', self.codes(self.evaluate(time=record)))

    def test_zero_duration_cannot_claim_temperature_evidence_without_observations(self):
        record = {**self.time, 'start_latest_s': 0, 'end_earliest_s': 0, 'end_latest_s': 0}
        req = {**self.requirements, 'duration_min_s': 0, 'duration_max_s': 0}
        self.assertIn('temperature_coverage_missing', self.codes(self.evaluate(time=record, temperatures=[], requirements=req)))

    def test_identity_is_bound_to_all_five_components(self):
        for field in self.identity:
            with self.subTest(field=field), self.assertRaises(TaskError):
                validate_temperature({**self.temperature, field: 'Test.Wrong'}, self.identity, self.qualifications)

    def test_original_checksum_and_explicit_source_kind_are_required(self):
        for change in ({'artifact_sha256': None}, {'artifact_sha256': 'bad'},
                       {'source_kind': 'synthetic_input'}, {'source_kind': None}):
            with self.subTest(change=change), self.assertRaises(TaskError):
                validate_time({**self.time, **change}, self.identity, self.qualifications)

    def test_fixture_and_real_observations_cannot_be_merged_into_qualification(self):
        report = self.evaluate(temperatures=[{**self.temperature, 'source_kind': 'device_export'}])
        self.assertIn('fixture_evidence_mismatch', self.codes(report))
        self.assertFalse(report['conformant'])

    def test_closed_shapes_reject_missing_extra_and_malformed_registry_fields(self):
        for record in ({key: value for key, value in self.time.items() if key != 'evidence_id'},
                       {**self.time, 'unimplemented_flag': True}):
            with self.assertRaises(TaskError):validate_time(record, self.identity, self.qualifications)
        registry = copy.deepcopy(self.qualifications)
        registry['Test.TimeQualification']['relationship'] = 'sample_measurement'
        with self.assertRaises(TaskError):validate_time(self.time, self.identity, registry)

    def test_nan_infinity_bools_and_negative_uncertainties_are_rejected(self):
        for value in (True, False, float('nan'), float('inf'), -1, 10 ** 1000):
            with self.subTest(value=str(value)[:20]), self.assertRaises(TaskError):
                validate_time({**self.time, 'start_earliest_s': value}, self.identity, self.qualifications)
            with self.subTest(uncertainty=str(value)[:20]), self.assertRaises(TaskError):
                validate_temperature({**self.temperature, 'uncertainty_deg_c': value}, self.identity, self.qualifications)

    def test_reversed_intervals_temperature_bounds_and_requirement_ranges_are_rejected(self):
        for record in ({**self.time, 'start_latest_s': -1},
                       {**self.time, 'start_earliest_s': 13, 'start_latest_s': 14}):
            with self.assertRaises(TaskError):validate_time(record, self.identity, self.qualifications)
        with self.assertRaises(TaskError):
            validate_temperature({**self.temperature, 'minimum_deg_c': 5, 'maximum_deg_c': 4}, self.identity, self.qualifications)
        with self.assertRaises(TaskError):self.evaluate(requirements={**self.requirements, 'duration_max_s': 9})

    def test_duplicate_evidence_ids_cannot_double_count_an_interval(self):
        with self.assertRaises(TaskError):self.evaluate(temperatures=[self.temperature, self.temperature])
        with self.assertRaises(TaskError):self.evaluate(temperatures=[{**self.temperature, 'evidence_id': self.time['evidence_id']}])

    def test_validators_and_assessment_do_not_mutate_or_alias_originals(self):
        before = copy.deepcopy((self.time, self.temperature, self.requirements, self.qualifications))
        record = validate_time(self.time, self.identity, self.qualifications)
        record['evidence_id'] = 'Test.Changed'
        self.evaluate()
        self.assertEqual((self.time, self.temperature, self.requirements, self.qualifications), before)


if __name__ == '__main__':
    unittest.main()
