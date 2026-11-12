"""Clock-bound tests use declared fake observations, never real-time waits."""

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from manual_tasks import TaskError
import manual_process_clock as clock


class FakeClock:
    """Explicit test clock; its bounds are fixtures, not laboratory evidence."""

    def __init__(self, *, clock_id='TEST.Epoch.1', process_id='TEST.Writer.1', uncertainty_s=0.0):
        self.record = {'format': clock.FORMAT, 'source_kind': 'test_clock',
            'clock_id': clock_id, 'process_id': process_id, 'utc': '2026-11-12T12:00:00Z',
            'monotonic_ns': 0, 'uncertainty_s': uncertainty_s, 'suspend_policy': 'inclusive'}

    def sample(self):
        return copy.deepcopy(self.record)

    def advance(self, seconds, *, utc_seconds=None):
        self.record['monotonic_ns'] += int(seconds * 1_000_000_000)
        stamp = datetime.fromisoformat(self.record['utc'].replace('Z', '+00:00'))
        stamp += timedelta(seconds=seconds if utc_seconds is None else utc_seconds)
        self.record['utc'] = stamp.isoformat().replace('+00:00', 'Z')
        return self.sample()


class ManualProcessClockTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeClock()
        self.first = self.provider.sample()
        self.initial = clock.initial(self.first)

    def domain_gap(self, state=None):
        state = self.initial if state is None else state
        sample = copy.deepcopy(state['last_sample'])
        sample.update(clock_id='TEST.OtherEpoch', process_id='TEST.OtherWriter', monotonic_ns=0)
        return clock.refresh(state, sample), sample

    def test_system_provider_reports_only_unqualified_process_scoped_observations(self):
        provider = clock.SystemClock()
        with patch('manual_process_clock.time.monotonic_ns', return_value=123456):
            sample = provider.sample()
            again = provider.sample()
        self.assertEqual(set(sample), clock.SAMPLE_FIELDS)
        self.assertEqual(sample['source_kind'], 'system_clock')
        self.assertEqual(sample['monotonic_ns'], 123456)
        self.assertIsNone(sample['uncertainty_s'])
        self.assertEqual(sample['suspend_policy'], 'unqualified')
        self.assertEqual(sample['clock_id'], again['clock_id'])
        self.assertEqual(sample['process_id'], again['process_id'])
        self.assertTrue(sample['utc'].endswith('Z'))

    def test_new_system_provider_has_no_assumed_continuity_with_another_provider(self):
        one, two = clock.SystemClock(), clock.SystemClock()
        self.assertNotEqual(one.clock_id, two.clock_id)
        self.assertNotEqual(one.process_id, two.process_id)
        state = clock.initial(one.sample())
        state = clock.refresh(state, two.sample())
        self.assertTrue(state['gap_required'])
        self.assertIsNone(state['upper_s'])

    def test_sample_validation_returns_detached_data(self):
        result = clock.validate_sample(self.first)
        result['clock_id'] = 'TEST.Changed'
        self.assertEqual(self.first, self.provider.sample())

    def test_unknown_or_missing_sample_fields_are_rejected(self):
        for field in ('missing', 'extra', 'format'):
            sample = copy.deepcopy(self.first)
            if field == 'missing':
                del sample['monotonic_ns']
            elif field == 'extra':
                sample['calibrated'] = True
            else:
                sample['format'] = 'solidcraftbot.clock-observation/2'
            with self.subTest(field=field), self.assertRaises(TaskError):
                clock.validate_sample(sample)

    def test_utc_requires_an_aware_utc_z_timestamp(self):
        for utc in ('2026-11-12T12:00:00', '2026-11-12T12:00:00+01:00', 'yesterdayZ', None):
            with self.subTest(utc=utc), self.assertRaises(TaskError):
                clock.validate_sample({**self.first, 'utc': utc})

    def test_uncertainty_is_null_or_finite_nonnegative_number(self):
        for uncertainty in (-1, True, float('nan'), float('inf'), 10 ** 1000, '0'):
            with self.subTest(uncertainty=uncertainty), self.assertRaises(TaskError):
                clock.validate_sample({**self.first, 'uncertainty_s': uncertainty})
        self.assertIsNone(clock.validate_sample({**self.first, 'uncertainty_s': None})['uncertainty_s'])

    def test_monotonic_counter_rejects_boolean_negative_fractional_and_unbounded_values(self):
        for counter in (True, -1, 0.1, float('inf'), 10 ** 1000):
            with self.subTest(counter=type(counter).__name__), self.assertRaises(TaskError):
                clock.validate_sample({**self.first, 'monotonic_ns': counter})

    def test_provider_identity_and_declared_policies_cannot_be_omitted_or_invented(self):
        for field, value in (('clock_id', ''), ('process_id', ' '), ('source_kind', 'calibrated_device'),
                             ('suspend_policy', 'probably_inclusive')):
            with self.subTest(field=field), self.assertRaises(TaskError):
                clock.validate_sample({**self.first, field: value})

    def test_qualified_test_clock_begins_at_zero_with_visible_test_provenance(self):
        self.assertEqual((self.initial['lower_s'], self.initial['upper_s']), (0, 0))
        self.assertFalse(self.initial['gap_required'])
        self.assertEqual(self.initial['last_sample']['source_kind'], 'test_clock')
        json.dumps(self.initial, allow_nan=False)

    def test_unqualified_provider_does_not_create_a_finite_elapsed_upper_bound(self):
        first = {**self.first, 'uncertainty_s': None, 'suspend_policy': 'unqualified'}
        state = clock.initial(first)
        self.assertIsNone(state['upper_s'])
        sample = {**self.provider.advance(10), 'uncertainty_s': None, 'suspend_policy': 'unqualified'}
        state = clock.refresh(state, sample)
        self.assertEqual(state['lower_s'], 10)
        self.assertIsNone(state['upper_s'])
        self.assertFalse(state['gap_required'])

    def test_elapsed_bounds_include_both_endpoint_uncertainties(self):
        first = {**self.first, 'uncertainty_s': 0.25}
        state = clock.initial(first)
        sample = {**self.provider.advance(10), 'uncertainty_s': 0.5}
        state = clock.refresh(state, sample)
        self.assertEqual(state['lower_s'], 9.25)
        self.assertEqual(state['upper_s'], 10.75)
        state = clock.refresh(state, {**self.provider.advance(0.1), 'uncertainty_s': 0.5})
        self.assertEqual(state['lower_s'], 9.25)
        self.assertAlmostEqual(state['upper_s'], 11.85)

    def test_repeated_identical_sample_does_not_advance_or_expand_bounds(self):
        sample = {**self.first, 'uncertainty_s': 0.5}
        state = clock.initial(sample)
        self.assertEqual(clock.refresh(state, sample), state)

    def test_writer_process_change_with_explicit_same_clock_domain_keeps_continuity(self):
        sample = {**self.provider.advance(10), 'process_id': 'TEST.Writer.2'}
        state = clock.refresh(self.initial, sample)
        self.assertEqual((state['lower_s'], state['upper_s']), (10, 10))
        self.assertFalse(state['gap_required'])
        self.assertEqual(state['last_sample']['process_id'], 'TEST.Writer.2')

    def test_forward_utc_step_opens_gap_without_inventing_utc_elapsed_time(self):
        state = clock.refresh(self.initial, self.provider.advance(10, utc_seconds=3600))
        self.assertEqual(state['lower_s'], 10)
        self.assertTrue(state['gap_required'])
        self.assertEqual(state['gap_base']['lower_s'], 0)
        self.assertIn('utc_monotonic_disagreement', {item['code'] for item in state['anomalies']})

    def test_backward_utc_step_does_not_shorten_monotonic_lower_evidence(self):
        state = clock.refresh(self.initial, self.provider.advance(10, utc_seconds=-1))
        self.assertEqual(state['lower_s'], 10)
        self.assertTrue(state['gap_required'])
        self.assertIsNone(state['upper_s'])
        self.assertIn('utc_regressed', {item['code'] for item in state['anomalies']})

    def test_new_domain_preserves_the_pre_gap_anchor_and_infers_no_zero_gap(self):
        before = clock.refresh(self.initial, self.provider.advance(10))
        state, _ = self.domain_gap(before)
        self.assertEqual(state['lower_s'], 10)
        self.assertTrue(state['gap_required'])
        self.assertIsNone(state['upper_s'])
        self.assertEqual(state['gap_base'], {key: before[key] for key in ('lower_s', 'upper_s', 'last_sample')})

    def test_regressed_counter_cannot_move_elapsed_time_backwards(self):
        before = clock.refresh(self.initial, self.provider.advance(10))
        sample = {**self.provider.advance(1), 'monotonic_ns': 5_000_000_000}
        state = clock.refresh(before, sample)
        self.assertEqual(state['lower_s'], 10)
        self.assertTrue(state['gap_required'])
        self.assertIn('monotonic_regressed', {item['code'] for item in state['anomalies']})

    def test_changed_suspend_policy_breaks_the_old_continuity_claim(self):
        state = clock.refresh(self.initial, {**self.provider.advance(10), 'suspend_policy': 'unqualified'})
        self.assertEqual(state['lower_s'], 0)
        self.assertTrue(state['gap_required'])
        self.assertIn('suspend_policy_changed', {item['code'] for item in state['anomalies']})

    def test_changed_source_kind_cannot_silently_turn_test_time_into_real_evidence(self):
        state = clock.refresh(self.initial, {**self.provider.advance(10), 'source_kind': 'system_clock'})
        self.assertTrue(state['gap_required'])
        self.assertIn('clock_source_changed', {item['code'] for item in state['anomalies']})

    def test_refresh_during_gap_advances_only_new_known_delta_and_keeps_fixed_base(self):
        state, sample = self.domain_gap()
        base = copy.deepcopy(state['gap_base'])
        sample.update(monotonic_ns=5_000_000_000, utc='2026-11-12T12:00:05Z')
        state = clock.refresh(state, sample)
        self.assertEqual(state['lower_s'], 5)
        self.assertEqual(state['gap_base'], base)
        self.assertEqual(clock.refresh(state, sample), state)
        sample.update(monotonic_ns=8_000_000_000, utc='2026-11-12T12:00:08Z')
        state = clock.refresh(state, sample)
        self.assertEqual(state['lower_s'], 8)
        self.assertEqual(state['gap_base'], base)
        self.assertIsNone(state['upper_s'])

    def test_explicit_gap_interval_is_from_original_anchor_through_current_sample(self):
        before = clock.refresh(self.initial, self.provider.advance(10))
        state, sample = self.domain_gap(before)
        sample.update(monotonic_ns=5_000_000_000, utc='2026-11-12T12:00:15Z')
        state = clock.refresh(state, sample)
        result = clock.reconcile_gap(state, sample, 20, 30, 'TEST.Explicit evidence', 'TEST.Log.Entry.1')
        self.assertEqual((result['lower_s'], result['upper_s']), (30, 40))
        self.assertFalse(result['gap_required'])
        self.assertIsNone(result['gap_base'])
        self.assertEqual(result['gap_resolution']['from_sample'], before['last_sample'])
        self.assertEqual(result['gap_resolution']['through_sample'], sample)
        self.assertEqual(result['gap_resolution']['evidence_ref'], 'TEST.Log.Entry.1')
        self.assertEqual(result['anomalies'], state['anomalies'])

    def test_unknown_gap_maximum_remains_unknown_after_later_good_samples_and_restart(self):
        state, sample = self.domain_gap()
        state = clock.reconcile_gap(state, sample, 2, None, 'TEST.Unbounded interruption', 'TEST.Log.Entry.2')
        self.assertEqual(state['lower_s'], 2)
        self.assertIsNone(state['upper_s'])
        sample.update(monotonic_ns=3_000_000_000, utc='2026-11-12T12:00:03Z')
        state = clock.refresh(state, sample)
        self.assertEqual(state['lower_s'], 5)
        sample.update(clock_id='TEST.ThirdEpoch', monotonic_ns=0)
        state = clock.refresh(state, sample)
        state = clock.reconcile_gap(state, sample, 1, 1, 'TEST.Later known interruption', 'TEST.Log.Entry.3')
        self.assertEqual(state['lower_s'], 6)
        self.assertIsNone(state['upper_s'])

    def test_historically_unqualified_upper_cannot_be_repaired_by_a_finite_gap(self):
        state = clock.initial({**self.first, 'uncertainty_s': None, 'suspend_policy': 'unqualified'})
        state, sample = self.domain_gap(state)
        result = clock.reconcile_gap(state, sample, 0, 0, 'TEST.Explicit zero gap only', 'TEST.Log.Entry.4')
        self.assertIsNone(result['upper_s'])
        self.assertEqual(result['lower_s'], 0)

    def test_gap_maximum_cannot_erase_monotonic_time_already_observed_during_gap(self):
        state, sample = self.domain_gap()
        sample.update(monotonic_ns=10_000_000_000, utc='2026-11-12T12:00:10Z')
        before = copy.deepcopy(state)
        with self.assertRaises(TaskError):
            clock.reconcile_gap(state, sample, 0, 9, 'TEST.Contradictory maximum', 'TEST.Log.Entry.5')
        self.assertEqual(state, before)

    def test_invalid_gap_intervals_or_missing_provenance_leave_input_unchanged(self):
        state, sample = self.domain_gap()
        before = copy.deepcopy(state)
        cases = [(-1, 1, 'reason', 'ref'), (2, 1, 'reason', 'ref'),
                 (0, float('nan'), 'reason', 'ref'), (0, 1, '', 'ref'), (0, 1, 'reason', '')]
        for minimum, maximum, reason, evidence in cases:
            with self.subTest(bounds=(minimum, maximum)), self.assertRaises(TaskError):
                clock.reconcile_gap(state, sample, minimum, maximum, reason, evidence)
            self.assertEqual(state, before)

    def test_gap_reconciliation_requires_an_actual_unresolved_gap(self):
        with self.assertRaises(TaskError):
            clock.reconcile_gap(self.initial, self.first, 0, 0, 'TEST.No gap', 'TEST.Log.Entry.6')

    def test_uncommitted_clock_proposals_are_detached_and_do_not_advance_live_state(self):
        before = copy.deepcopy(self.initial)
        proposal = clock.refresh(self.initial, self.provider.advance(10))
        self.assertEqual(self.initial, before)
        self.assertEqual(proposal['lower_s'], 10)
        proposal['last_sample']['clock_id'] = 'TEST.Modified proposal'
        self.assertEqual(self.initial, before)
        state, sample = self.domain_gap()
        saved = copy.deepcopy(state)
        result = clock.reconcile_gap(state, sample, 1, 2, 'TEST.Uncommitted closure', 'TEST.Log.Entry.7')
        result['gap_resolution']['through_sample']['clock_id'] = 'TEST.Modified closure'
        self.assertEqual(state, saved)


if __name__ == '__main__':
    unittest.main()
