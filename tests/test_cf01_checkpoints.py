"""Durable CF01 event boundaries and a shared synthetic process clock."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from cf01_rack_batch import BatchError, Runner


class CheckpointTests(unittest.TestCase):
    def test_command_intent_is_committed_before_dispatch_and_reply_before_completion(self):
        events = []
        runner = Runner(checkpoint=lambda kind, payload, view: events.append((kind, payload, view)))
        dispatch = runner.bridge.dispatch

        def checked_dispatch(transport, name, fields):
            self.assertEqual(events[-1][0], 'command_intent')
            self.assertEqual(events[-1][1]['command'], 'acquire')
            self.assertIsNone(runner.sim.owner)
            return dispatch(transport, name, fields)

        runner.bridge.dispatch = checked_dispatch
        runner.command('acquire', client_id='checkpoint-test')
        self.assertEqual([event[0] for event in events],
                         ['command_intent', 'command_reply', 'state_observed', 'command_completed'])
        self.assertIsNotNone(runner.sim.owner)
        self.assertEqual(events[1][1]['response']['control_token'], runner.token)
        self.assertTrue(events[-1][1]['response']['success'])
        self.assertEqual([event[1]['checkpoint_sequence'] for event in events], [1, 2, 3, 4])

    def test_handoff_intent_precedes_feedback_and_completion_follows_observation(self):
        events = []
        runner = Runner(checkpoint=lambda kind, payload, view: events.append((kind, payload, view)))
        sample = runner.samples[0]

        def feedback(event, observed_sample):
            self.assertEqual(events[-1][0], 'handoff_intent')
            self.assertEqual(runner.world['rack'][0], sample['id'])
            self.assertIsNone(runner.world['gripper'])
            return {'sample_id': observed_sample['id'], 'grasp_confirmed': True, 'source_empty': True}

        runner.feedback = feedback
        runner.observe('pick_rack', sample, ('grasp_confirmed', 'source_empty'))
        self.assertEqual([event[0] for event in events], ['handoff_intent', 'robot_observed'])
        observed = events[-1][2]
        self.assertEqual(observed['inventory']['rack'][0], sample['id'])
        self.assertEqual(observed['world_inventory']['gripper'], sample['id'])
        self.assertEqual(observed['ownership'], 'pending')
        runner.complete_handoff()
        kind, payload, view = events[-1]
        self.assertEqual(kind, 'handoff_completed')
        self.assertTrue(payload['robot_confirmation'])
        self.assertEqual(payload['source']['place_id'], 'Slot01')
        self.assertEqual(view['inventory']['gripper'], sample['id'])
        self.assertIsNone(view['pending_handoff'])
        self.assertEqual(view['ownership'], 'confirmed')

    def test_checkpoint_failure_before_dispatch_has_no_station_effect(self):
        def checkpoint(kind, payload, view):
            if kind == 'command_intent':
                raise OSError('Journal write failed')

        runner = Runner(checkpoint=checkpoint)
        dispatched = []
        runner.bridge.dispatch = lambda *args: dispatched.append(args)
        with self.assertRaisesRegex(OSError, 'Journal write failed'):
            runner.run()
        self.assertEqual(dispatched, [])
        self.assertIsNone(runner.sim.owner)
        self.assertFalse(runner.stop_attempted)
        with self.assertRaisesRegex(RuntimeError, 'invalidated'):
            runner.run()

    def test_checkpoint_failure_after_station_effect_preserves_uncompleted_intent(self):
        committed = []

        def checkpoint(kind, payload, view):
            if kind == 'command_reply':
                raise OSError('Reply commit failed')
            committed.append((kind, payload, view))

        runner = Runner(checkpoint=checkpoint)
        with self.assertRaisesRegex(OSError, 'Reply commit failed'):
            runner.run()
        self.assertIsNotNone(runner.sim.owner)
        self.assertEqual(committed[-1][0], 'command_intent')
        self.assertEqual(committed[-1][1]['command'], 'acquire')
        self.assertFalse(runner.stop_attempted)
        self.assertNotIn('command_completed', [event[0] for event in committed])

    def test_handoff_checkpoint_failures_do_not_create_a_durable_completion(self):
        for failing_kind in ['handoff_intent', 'handoff_completed']:
            with self.subTest(failing_kind=failing_kind):
                committed = []

                def checkpoint(kind, payload, view):
                    if kind == failing_kind:
                        raise OSError('Handoff write failed')
                    committed.append((kind, payload, view))

                runner = Runner(checkpoint=checkpoint)
                sample = runner.samples[0]
                with self.assertRaisesRegex(OSError, 'Handoff write failed'):
                    runner.observe('pick_rack', sample, ('grasp_confirmed', 'source_empty'))
                    runner.complete_handoff()
                if failing_kind == 'handoff_intent':
                    self.assertEqual(runner.world['rack'][0], sample['id'])
                    self.assertEqual(committed, [])
                else:
                    self.assertEqual(committed[-1][0], 'robot_observed')
                    self.assertEqual(committed[-1][2]['inventory']['rack'][0], sample['id'])
                    self.assertEqual(committed[-1][2]['world_inventory']['gripper'], sample['id'])
                with self.assertRaisesRegex(RuntimeError, 'invalidated'):
                    runner.command('acquire', client_id='must-not-continue')

    def test_failure_checkpoint_error_propagates_instead_of_becoming_a_stop_error(self):
        def checkpoint(kind, payload, view):
            if kind == 'failed':
                raise OSError('Failure record commit failed')

        runner = Runner(feedback=lambda event, sample: None, checkpoint=checkpoint)
        with self.assertRaisesRegex(OSError, 'Failure record commit failed'):
            runner.run()
        self.assertEqual(runner.failure['operation'], 'rack_ready')
        self.assertFalse(runner.stop_attempted)

    def test_negative_station_reply_is_durable_before_failed_handoff_and_stop(self):
        for transport in ['ros2', 'sila2']:
            with self.subTest(transport=transport):
                events = []
                runner = Runner(transport=transport,
                                checkpoint=lambda kind, payload, view: events.append((kind, payload, view)))
                dispatch = runner.bridge.dispatch
                wire_name = 'confirm_seated' if transport == 'ros2' else runner.bridge.commands['confirm_seated']['name']

                def reject_confirmation(encoding, name, fields):
                    response = dispatch(encoding, name, fields)
                    return {'success': False} if name == wire_name else response

                runner.bridge.dispatch = reject_confirmation
                with self.assertRaisesRegex(BatchError, 'Station acknowledgement missing or rejected') as failure:
                    runner.run()
                rejected = next(i for i, (kind, payload, view) in enumerate(events)
                                if kind == 'command_reply' and payload['command'] == 'confirm_seated')
                self.assertEqual(events[rejected][1]['response'], {'success': False})
                self.assertFalse(events[rejected][2]['pending_handoff']['station_confirmation'])
                failed = next(i for i, event in enumerate(events) if event[0] == 'failed')
                stop_requested = next(i for i, event in enumerate(events) if event[0] == 'stop_requested')
                stop_accepted = next(i for i, event in enumerate(events) if event[0] == 'stop_accepted')
                self.assertLess(rejected, failed)
                self.assertLess(failed, stop_requested)
                self.assertLess(stop_requested, stop_accepted)
                self.assertNotIn('stop', [payload.get('command') for kind, payload, view in events
                                         if kind == 'command_completed'])
                self.assertEqual(events[failed][1]['operation'], 'confirm_seated')
                self.assertEqual(events[failed][2]['ownership'], 'unresolved')
                self.assertFalse(failure.exception.report['passed'])

    def test_checkpoint_views_are_compact_json_and_do_not_mutate_runner_state(self):
        events = []

        def checkpoint(kind, payload, view):
            json.dumps({'payload': payload, 'view': view}, allow_nan=False)
            self.assertNotIn('trace', view)
            events.append((kind, copy.deepcopy(payload), copy.deepcopy(view)))
            view['inventory']['rack'][0] = 'Injected vessel'
            if 'arguments' in payload:
                payload['arguments']['client_id'] = 'Changed caller argument'

        runner = Runner(checkpoint=checkpoint)
        report = runner.run()
        self.assertTrue(report['passed'])
        self.assertEqual(report['initial_order'], report['final_order'])
        self.assertNotIn('Injected vessel', report['final_order'])
        self.assertTrue(all('trace' not in view for kind, payload, view in events))
        self.assertEqual(events[-1][2]['inventory'], report['inventory'])
        self.assertTrue(events[-1][2]['spin_completed'])
        self.assertGreater(events[-1][2]['heartbeat_count'], 0)
        self.assertNotIn('heartbeat', [payload.get('command') for kind, payload, view in events
                                       if kind == 'command_intent'])

    def test_external_clock_is_shared_by_observable_wait_and_heartbeats(self):
        time = [50.0]
        advances = []
        events = []

        def advance(seconds):
            advances.append(seconds)
            time[0] += seconds

        runner = Runner(clock=lambda: time[0], advance_clock=advance,
                        checkpoint=lambda kind, payload, view: events.append((kind, payload, view)))
        runner.command('acquire', client_id='shared-clock-test')
        runner.command('index', slot=1)
        dispatch, poll = runner.bridge.dispatch, runner.bridge.poll
        delayed = [None]
        polls = [0]

        def delayed_dispatch(transport, name, fields):
            response = dispatch(transport, name, fields)
            if name == 'open_lid':
                delayed[0] = response['id']
                return {**response, 'phase': 'running'}
            return response

        def delayed_poll(job_id):
            if job_id == delayed[0]:
                polls[0] += 1
                if polls[0] == 1:
                    return {'id': job_id, 'phase': 'running'}
            return poll(job_id)

        runner.bridge.dispatch, runner.bridge.poll = delayed_dispatch, delayed_poll
        result = runner.command('open_lid')
        self.assertEqual(result['phase'], 'succeeded')
        self.assertEqual(time[0], 50.5)
        self.assertEqual(runner.now, time[0])
        self.assertEqual(sum(advances), 0.5)
        self.assertEqual(runner._heartbeat_count, 2)
        observed = [payload['response']['phase'] for kind, payload, view in events if kind == 'job_observed']
        self.assertEqual(observed, ['succeeded'])
        self.assertEqual(events[-1][2]['job']['id'], delayed[0])
        self.assertEqual(events[-1][2]['time_s'], time[0])
        self.assertGreater(runner.sim.deadline, time[0])
        with self.assertRaisesRegex(ValueError, 'only through advance_clock'):
            runner.now += 1

    def test_invalid_polled_job_is_recorded_before_failure(self):
        events = []
        runner = Runner(checkpoint=lambda kind, payload, view: events.append((kind, payload, view)))
        dispatch = runner.bridge.dispatch
        poll = runner.bridge.poll
        delayed = [None]

        def delayed_dispatch(transport, name, fields):
            response = dispatch(transport, name, fields)
            if name == 'open_lid':
                delayed[0] = response['id']
                return {**response, 'phase': 'running'}
            return response

        def invalid_poll(job_id):
            return {'id': 'foreign-job', 'phase': 'succeeded'} if job_id == delayed[0] else poll(job_id)

        runner.bridge.dispatch = delayed_dispatch
        runner.bridge.poll = invalid_poll
        with self.assertRaisesRegex(BatchError, 'Invalid observable response'):
            runner.run()
        observed = next(i for i, event in enumerate(events) if event[0] == 'job_observed')
        failed = next(i for i, event in enumerate(events) if event[0] == 'failed')
        self.assertEqual(events[observed][1]['response'], {'id': 'foreign-job', 'phase': 'succeeded'})
        self.assertLess(observed, failed)

    def test_external_clock_callback_failure_is_not_wrapped_as_station_failure(self):
        def fail_clock(seconds):
            raise OSError('Clock event commit failed')

        runner = Runner(clock=lambda: 0.0, advance_clock=fail_clock)
        with self.assertRaisesRegex(OSError, 'Clock event commit failed'):
            runner.run()
        self.assertFalse(runner.stop_attempted)
        self.assertIsNone(runner.failure)

    def test_external_clock_must_be_paired_and_advance_the_requested_duration(self):
        for kwargs in [{'clock': lambda: 0}, {'advance_clock': lambda seconds: None}]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'provided together'):
                Runner(**kwargs)
        for start in [1.0, 1e15]:
            with self.subTest(start=start):
                runner = Runner(clock=lambda: start, advance_clock=lambda seconds: None)
                with self.assertRaisesRegex(ValueError, 'did not advance'):
                    runner.advance(0.25)

    def test_standalone_clock_remains_mutable(self):
        runner = Runner()
        runner.now += 2.5
        self.assertEqual(runner.now, 2.5)


if __name__ == '__main__':
    unittest.main()
