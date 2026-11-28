import copy
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import lab3003_cf01_cycle as cycle
from centrifuge_control import ControlError


class Lab3003CentrifugeCycleTests(unittest.TestCase):
    def timed_paths(self):
        samples = cycle._load_source()[0]['samples']
        return [dict(sample, points=[{'time_s': 0}, {'time_s': 4}],
                     jaw_points=[{'time_s': 0}, {'time_s': 4}], grip_s=1, seat_s=2) for sample in samples]

    def return_paths(self):
        return [dict(path, direction='unload') for path in reversed(self.timed_paths())]

    def test_open_lid_index_keeps_only_one_lid_cycle_per_transfer_pair(self):
        result = cycle.compile_cycle(arm_paths=self.timed_paths(), return_paths=self.return_paths(),
                                     keep_lid_open=True)
        steps = result['steps']
        self.assertTrue(result['open_lid_indexing'])
        self.assertIn(str(cycle.open_index.SOURCE.relative_to(cycle.ROOT)), result['source_files_sha256'])
        evidence = {step['phase']: step for step in steps}
        starts = ['open_indexing', 'return_open_indexing']
        ends = ['open_indexed', 'return_open_indexed']
        self.assertEqual(sum(step['phase'] in ('open', 'return_open') for step in steps), 2)
        self.assertEqual(sum(step['phase'] in ('closing', 'return_closing') for step in steps), 2)
        for start, end, prior, sample in zip(starts, ends, ('seated', 'pickup_pusher_parked'),
                                             ('B2_Tube07', 'B2_Tube01')):
            with self.subTest(index=start):
                begin, done = evidence[start], evidence[end]
                before = steps[steps.index(begin) - 1]
                self.assertEqual(before['phase'], prior)
                self.assertEqual(steps[steps.index(begin) + 1], done)
                self.assertEqual([begin['tube_id'], done['tube_id']], [sample, sample])
                self.assertFalse(begin['brake_held'])
                self.assertTrue(done['brake_held'])
                self.assertEqual(begin['seated'], ['B2_Tube01'])
                self.assertEqual(begin['lid_deg'], evidence['open']['lid_deg'])
                self.assertEqual(begin['latch_mm'], evidence['open']['latch_mm'])
                self.assertEqual(done['rotor_deg'] - begin['rotor_deg'], 180 if start.startswith('return_') else -180)
                for step in (begin, done):
                    self.assertEqual(step['lid_deg'], begin['lid_deg'])
                    self.assertEqual(step['latch_mm'], begin['latch_mm'])
                    self.assertFalse(step['lid_locked'])
                    self.assertTrue(step['arm_clear'])
                    self.assertEqual(step['rpm'], 0)
                    self.assertEqual(step['pusher_mm'], 0)
                    self.assertEqual(step['lift_mm'], 0)
                    self.assertIsNone(step['pusher_sample_id'])
        self.assertTrue(evidence['spinning']['lid_locked'])
        self.assertEqual(evidence['spinning']['lid_deg'], 0)
        self.assertEqual(evidence['spinning']['latch_mm'], [0, 0])
        self.assertTrue(evidence['transport_ready']['lid_locked'])

    def test_open_index_requires_explicit_clearance_park_and_occupancy_observations(self):
        for missing in ('workspace_clear', 'parked_confirmed', 'occupancy_confirmed'):
            with self.subTest(observation=missing):
                def observe(event, sample):
                    if sample is None:
                        return {'cover_removed': True}
                    flags = {**cycle.batch.synthetic_feedback(event, sample), 'rotor_slot': sample['slot'],
                             'empty_confirmed': True, 'extended_confirmed': True, 'rested_confirmed': True,
                             'parked_confirmed': True, 'occupancy_confirmed': True}
                    if event == 'open_index_ready':
                        flags[missing] = False
                    return flags

                with self.assertRaisesRegex(ValueError, 'confirmation: open_index_ready'):
                    cycle.compile_cycle(arm_paths=self.timed_paths(), keep_lid_open=True, feedback=observe)
        with self.assertRaisesRegex(ValueError, 'requires the supported loading paths'):
            cycle.compile_cycle(keep_lid_open=True)

    def test_combined_station_rejects_open_index_during_pending_zero_stroke_handoff(self):
        sim = cycle._OpenLidHandoffSimulator(
            initial_slots={slot: {'present': False, 'seated': False, 'mass_g': None} for slot in range(1, 13)})
        token = sim.execute('acquire', client_id='test')['token']
        sim.execute('index', token, slot=1)
        sim.execute('open_lid', token)
        sim.execute('begin_raise_empty_support', token, slot=1, sample_id='B2_Tube01', empty_confirmed=True)
        self.assertEqual(sim.execute('status')['lift_mm'], 0)
        with self.assertRaisesRegex(ControlError, 'Finish the active pusher handoff'):
            sim.execute('index_open_lid', token, slot=7)

    def test_extended_support_trace_holds_station_until_arm_clears(self):
        result = cycle.compile_cycle(arm_paths=self.timed_paths())
        self.assertFalse(result['arm_motion_checked'])
        self.assertIn(str(cycle.support.SOURCE.relative_to(cycle.ROOT)), result['source_files_sha256'])
        parameters = cycle.cf.parameters(cycle.cf.load())
        extension = parameters['park_gap'] + parameters['lift_travel']
        for sample in result['samples']:
            phases = {step['phase']: step for step in result['steps'] if step['tube_id'] == sample['id']}
            movement = [phases[key] for key in ('pusher_raised', 'arm_transfer', 'pusher_transfer', 'arm_clear')]
            self.assertEqual([sample[k] for k in ('arm_start_s', 'grip_s', 'support_release_s', 'arm_clear_s')],
                             [step['time_s'] for step in movement])
            for step in movement:
                self.assertEqual(step['pusher_mm'], extension)
                self.assertEqual(step['rotor_deg'], movement[0]['rotor_deg'])
                self.assertEqual(step['lid_deg'], movement[0]['lid_deg'])
                self.assertTrue(step['brake_held'])
            self.assertEqual([step['arm_clear'] for step in movement], [False, False, False, True])
            self.assertIsNone(phases['pusher_raised']['pusher_sample_id'])
            self.assertEqual(phases['pusher_transfer']['pusher_sample_id'], sample['id'])
            self.assertEqual(phases['pusher_transfer']['lift_mm'], parameters['lift_travel'])
            self.assertLess(phases['arm_clear']['time_s'], phases['lowering']['time_s'])
            self.assertEqual(phases['pocket_reached']['pusher_mm'], parameters['park_gap'])
            self.assertEqual(phases['pocket_reached']['lift_mm'], 0)
            self.assertEqual(phases['pocket_reached']['pusher_sample_id'], sample['id'])
            self.assertNotIn(sample['id'], phases['pocket_reached']['seated'])
            self.assertEqual(phases['seated']['time_s'], sample['pusher_lowered_s'])
            self.assertEqual(phases['seated']['pusher_mm'], 0)
            self.assertIsNone(phases['seated']['pusher_sample_id'])
            self.assertIn(sample['id'], phases['seated']['seated'])
            self.assertLess(sample['pusher_lowered_s'], phases['closing']['time_s'])
        self.assertEqual(result['steps'][-1]['phase'], 'stopped')

    def test_supported_trace_rejects_wrong_timing_and_missing_support_observation(self):
        paths = self.timed_paths()
        paths[0]['seat_s'] = 4
        with self.assertRaisesRegex(ValueError, 'return to park must be ordered'):
            cycle.compile_cycle(arm_paths=paths)

        def observe(event, sample):
            if sample is None:
                return {'cover_removed': True}
            return {**cycle.batch.synthetic_feedback(event, sample), 'rotor_slot': sample['slot'],
                    'empty_confirmed': True, 'extended_confirmed': True,
                    'rested_confirmed': False, 'parked_confirmed': True}

        with self.assertRaisesRegex(ValueError, 'confirmation: support_release'):
            cycle.compile_cycle(arm_paths=self.timed_paths(), feedback=observe)

    def test_return_requires_standstill_and_retains_each_cassette_identity(self):
        result = cycle.compile_cycle(arm_paths=self.timed_paths(), return_paths=self.return_paths())
        joined = result['steps']
        stop = next(step for step in joined if step['phase'] == 'stopped')
        self.assertTrue(stop['lid_locked'] and stop['brake_held'])
        self.assertEqual(stop['seated'], ['B2_Tube01', 'B2_Tube07'])
        self.assertFalse(stop['returned'])
        self.assertLess(result['stopped_s'], result['transport_ready_s'])
        for previous, step in zip(joined, joined[1:]):
            self.assertLess(previous['time_s'], step['time_s'])
            if step['time_s'] > stop['time_s']:
                self.assertEqual(step['rpm'], 0)
                self.assertLessEqual(abs(step['rotor_deg'] - previous['rotor_deg']), 180)
        expected = ['B2_Tube07', 'B2_Tube01']
        for index, sample in enumerate(result['return_samples']):
            identity = expected[index]
            self.assertEqual(sample['id'], identity)
            phases = {step['phase']: step for step in joined if step['tube_id'] == identity}
            contact, raised, grip, seat, clear, parked = (
                phases[key] for key in ('pickup_contact', 'pickup_raised', 'pickup_grasp',
                                        'cassette_seated', 'return_arm_clear', 'pickup_pusher_parked'))
            self.assertEqual([p['time_s'] for p in (raised, grip, seat, clear, parked)],
                             [sample[key] for key in ('arm_start_s', 'grip_s', 'cassette_release_s',
                                                      'arm_clear_s', 'pusher_parked_s')])
            self.assertEqual(contact['pusher_sample_id'], identity)
            self.assertEqual(contact['lift_mm'], 0)
            self.assertEqual(raised['pusher_sample_id'], identity)
            self.assertGreater(raised['lift_mm'], 0)
            self.assertIsNone(grip['pusher_sample_id'])
            self.assertNotIn(identity, grip['seated'] + grip['returned'])
            self.assertEqual(seat['returned'], expected[:index + 1])
            self.assertFalse(seat['arm_clear'])
            self.assertTrue(clear['arm_clear'])
            self.assertEqual(clear['pusher_mm'], raised['pusher_mm'])
            self.assertEqual(parked['pusher_mm'], 0)
            self.assertTrue(parked['arm_clear'])
            self.assertNotIn(identity, parked['seated'])
            self.assertAlmostEqual(math.remainder(raised['rotor_deg'] + (sample['slot'] - 1) * 30, 360), 0)
        ready = joined[-1]
        self.assertEqual(ready['phase'], 'transport_ready')
        self.assertEqual(ready['returned'], expected)
        self.assertFalse(ready['seated'] or ready['cover_removed'])
        self.assertTrue(ready['transport_ready'] and ready['arm_clear'] and ready['lid_locked'])
        self.assertTrue(all(not step['transport_ready'] for step in joined[:-1]))
        self.assertEqual(result['duration_s'], ready['time_s'])

    def test_return_requires_original_slot_and_confirmed_cover_before_departure(self):
        for missing, message in [('cassette_seat', 'cassette_seat'), ('cover_replaced', 'cover_replaced')]:
            with self.subTest(missing=missing):
                def observe(event, sample):
                    if sample is None:
                        return {'cover_removed': True, 'cover_replaced': event != missing}
                    return {**cycle.batch.synthetic_feedback(event, sample), 'rotor_slot': sample['slot'],
                            'empty_confirmed': True, 'extended_confirmed': True, 'rested_confirmed': True,
                            'parked_confirmed': True, 'presented_confirmed': True, 'destination_empty': True,
                            'cassette_seated': True, 'cassette_slot': 'wrong slot' if event == missing else sample['id']}

                with self.assertRaisesRegex(ValueError, 'confirmation: ' + message):
                    cycle.compile_cycle(arm_paths=self.timed_paths(), return_paths=self.return_paths(),
                                        feedback=observe)
        with self.assertRaisesRegex(ValueError, 'ordered tube'):
            cycle.compile_cycle(arm_paths=self.timed_paths(), return_paths=list(reversed(self.return_paths())))

    def test_chronology_and_observed_ownership(self):
        result = cycle.compile_cycle()
        steps = result['steps']
        self.assertTrue(result['synthetic'])
        self.assertFalse(result['hardware_qualified'])
        self.assertFalse(result['arm_motion_checked'])
        self.assertEqual(result['samples'], [{'id': 'B2_Tube01', 'slot': 1},
                                             {'id': 'B2_Tube07', 'slot': 7}])
        self.assertEqual((steps[0]['time_s'], steps[0]['phase']), (0, 'docked'))
        self.assertFalse(steps[0]['cover_removed'])
        self.assertTrue(steps[0]['brake_held'])
        self.assertTrue(all(a['time_s'] < b['time_s'] for a, b in zip(steps, steps[1:])))
        self.assertEqual([step['rotor_deg'] for step in steps if step['phase'] == 'indexed'], [0, -180])
        transitions = [(a, b) for a, b in zip(steps, steps[1:]) if a['seated'] != b['seated']]
        self.assertEqual([b['tube_id'] for _, b in transitions], ['B2_Tube01', 'B2_Tube07'])
        for before, seated in transitions:
            self.assertEqual((before['phase'], seated['phase']), ('arm_transfer', 'seated'))
            self.assertEqual(seated['seated'], before['seated'] + [seated['tube_id']])
            self.assertTrue(seated['cover_removed'] and seated['brake_held'])
            self.assertFalse(seated['arm_clear'] or seated['lid_locked'])
            self.assertGreater(seated['lid_deg'], 0)

    def test_spin_and_brake_boundaries(self):
        result = cycle.compile_cycle()
        locked, spinning, braking, stopped = result['steps'][-4:]
        self.assertEqual([step['phase'] for step in result['steps'][-4:]],
                         ['locked', 'spinning', 'braking', 'stopped'])
        self.assertTrue(locked['brake_held'])
        for step in (locked, spinning, braking, stopped):
            self.assertTrue(step['lid_locked'] and step['arm_clear'])
            self.assertEqual(step['lid_deg'], 0)
            self.assertEqual(step['latch_mm'], [0, 0])
            self.assertEqual(step['seated'], ['B2_Tube01', 'B2_Tube07'])
        self.assertFalse(spinning['brake_held'] or braking['brake_held'])
        self.assertTrue(stopped['brake_held'])
        self.assertEqual(stopped['rpm'], 0)
        self.assertGreater(spinning['rpm'], 0)

        t_spin, t_brake, t_stop = (result[key] for key in ('spin_started_s', 'brake_started_s', 'stopped_s'))
        self.assertEqual((t_spin, t_brake, t_stop),
                         (spinning['time_s'], braking['time_s'], stopped['time_s']))
        self.assertEqual(t_stop, result['duration_s'])
        self.assertEqual(braking['rpm'], spinning['rpm'])
        self.assertAlmostEqual(t_brake - t_spin, cycle.batch.load()['spin']['duration_s'])
        self.assertAlmostEqual(t_stop - t_brake, cycle.cf.load()['mechanisms']['braking']['simulation_stop_s'])
        self.assertAlmostEqual(braking['rotor_deg'] - spinning['rotor_deg'],
                               6 * spinning['rpm'] * (t_brake - t_spin))
        self.assertAlmostEqual(stopped['rotor_deg'] - braking['rotor_deg'],
                               3 * braking['rpm'] * (t_stop - t_brake))
        self.assertIn(str(cycle.SOURCE.relative_to(cycle.ROOT)), result['source_files_sha256'])
        self.assertTrue(all(digest == cycle.robot.digest(cycle.ROOT / path) for path, digest in
                            result['source_files_sha256'].items()))

    def test_cycle_source_rejects_unpinned_geometry_and_invalid_sample_mapping(self):
        definition = json.loads(cycle.SOURCE.read_text())
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'cycle.shared.json'
            with patch.object(cycle, 'SOURCE', source):
                cases = [({'id': 'B2_Tube01'}, 'distinct cassette tube identities'),
                         ({'id': 'Bumper'}, 'both cassette tubes'),
                         ({'slot': 8}, 'opposite CF01 slots')]
                for change, message in cases:
                    with self.subTest(change=change):
                        invalid = copy.deepcopy(definition)
                        invalid['samples'][1].update(change)
                        source.write_text(json.dumps(invalid))
                        with self.assertRaisesRegex(ValueError, message):
                            cycle.compile_cycle()
                del definition['sources']['laboratories']['source_sha256']
                source.write_text(json.dumps(definition))
                with self.assertRaisesRegex(ValueError, 'Pinned laboratory'):
                    cycle.compile_cycle()

    def test_rejects_missing_or_mismatched_observations(self):
        with self.assertRaisesRegex(ValueError, 'cover removal'):
            cycle.compile_cycle(cover_removed=False)

        faults = [('cover_removed', None, {'cover_removed': False}),
                  ('grasp', 'B2_Tube07', {'sample_id': 'B2_Tube01'}),
                  ('seat', 'B2_Tube01', {'rotor_slot': 7}),
                  ('seat', 'B2_Tube01', {'released_confirmed': False}),
                  ('arm_clear', 'B2_Tube01', {'workspace_clear': False})]
        for failed_event, identity, overrides in faults:
            with self.subTest(event=failed_event, overrides=overrides):
                def observe(event, sample):
                    if sample is None:
                        reply = {'cover_removed': True}
                    else:
                        reply = {**cycle.batch.synthetic_feedback(event, sample), 'rotor_slot': sample['slot']}
                    if event == failed_event and (sample['id'] if sample else None) == identity:
                        reply.update(overrides)
                    return reply

                with self.assertRaisesRegex(ValueError, 'confirmation: ' + failed_event):
                    cycle.compile_cycle(feedback=observe)

    def test_brake_failure_during_spin_prevents_confirmed_completion(self):
        class MissingBrakeFeedback(cycle.Simulator):
            def execute(self, command, token=None, **arguments):
                result = super().execute(command, token, **arguments)
                if command == 'start':
                    self.brake_engage_confirmed = False
                return result

        with patch.object(cycle, 'Simulator', MissingBrakeFeedback):
            with self.assertRaisesRegex(ValueError, 'confirmed standstill'):
                cycle.compile_cycle()

    def test_transition_timing_uses_quintic_peak_bounds(self):
        result = cycle.compile_cycle()
        limits = cycle.cf.load()['mechanisms']['lid']['nominal_lid_speed_deg_s']
        for a, b in zip(result['steps'], result['steps'][1:]):
            delta = abs(a['lid_deg'] - b['lid_deg'])
            dt = b['time_s'] - a['time_s']
            self.assertTrue(math.isfinite(dt) and dt > 0)
            if delta:
                self.assertLessEqual(15 * delta / (8 * dt), limits)


if __name__ == '__main__':
    unittest.main()
