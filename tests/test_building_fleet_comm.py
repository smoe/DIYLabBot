"""Independent received-state, radio blackout and sender-sequence checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_comm as comm


def heartbeat(x=0):
    return {'pose_mm':[x, 20, 0], 'level':'EG', 'area':'R0_004', 'mode':'travel', 'speed_mm_s':400}


class ChannelTests(unittest.TestCase):
    def test_seeded_jitter_is_deterministic_bounded_and_sender_ordered(self):
        def run(seed):
            channel = comm.Channel([.01, .3], seed, .3)
            for seq in range(10): channel.emit('BF01', 'heartbeat', heartbeat(seq), seq*.01)
            messages = channel.deliver(2)
            self.assertEqual([m['seq'] for m in messages], list(range(1, 11)))
            self.assertTrue(all(.01 <= m['received_s']-m['sent_s'] <= .3 for m in messages))
            return messages
        self.assertEqual(run(7), run(7)); self.assertNotEqual(run(7), run(8))

    def test_lift_blackout_buffers_original_times_including_in_flight(self):
        channel = comm.Channel([.1, .1], 1, .25)
        channel.emit('BF01', 'heartbeat', heartbeat(), 0)
        channel.set_connected('BF01', False, .05)
        channel.emit('BF01', 'heartbeat', heartbeat(200), .1)
        self.assertEqual(channel.deliver(10), [])
        channel.set_connected('BF01', True, 10)
        self.assertEqual(channel.deliver(10.05), [])
        messages = channel.deliver(11)
        self.assertEqual([m['seq'] for m in messages], [1, 2, 3, 4])
        self.assertEqual([m['sent_s'] for m in messages], [0, .05, .1, 10])
        self.assertEqual(messages[1]['payload']['event'], 'comm_lost')
        self.assertEqual(messages[-1]['payload']['event'], 'comm_restored')
        self.assertEqual([m['delivered_late'] for m in messages], [True, True, True, False])
        self.assertEqual(channel.statistics()['outages'][0]['duration_s'], 9.95)

    def test_mutation_cannot_change_sent_payload(self):
        channel = comm.Channel([0, 0], 0, .1); own = heartbeat()
        channel.emit('BF01', 'heartbeat', own, 0); own['pose_mm'][0] = 900
        self.assertEqual(channel.deliver(1)[0]['payload']['pose_mm'][0], 0)

    def test_unknown_or_nonfinite_envelopes_are_rejected(self):
        channel = comm.Channel([0, 0], 0, .1)
        with self.assertRaises(ValueError): channel.emit('BF21', 'heartbeat', heartbeat(), 0)
        with self.assertRaises(ValueError): channel.emit('BF01', 'truth', {'vehicles':{}}, 0)
        bad = heartbeat(); bad['other_vehicle_positions'] = []
        with self.assertRaises(ValueError): channel.emit('BF01', 'heartbeat', bad, 0)
        bad = heartbeat(); bad['pose_mm'][0] = float('nan')
        with self.assertRaises(ValueError): channel.emit('BF01', 'heartbeat', bad, 0)
        channel.emit('BF01', 'heartbeat', heartbeat(), 1)
        with self.assertRaises(ValueError): channel.emit('BF01', 'heartbeat', heartbeat(), .5)


class ControlRoomTests(unittest.TestCase):
    def test_only_received_messages_affect_state_and_coverage(self):
        channel = comm.Channel([.2, .2], 1, .1); panel = comm.ReceivedControlRoom()
        channel.emit('BF01', 'heartbeat', heartbeat(123), 0)
        channel.emit('BF01', 'event', {'event':'inspection_completed', 'details':{'level':'EG','area':'R0_001'}}, .1)
        self.assertEqual(panel.snapshot(0)['vehicles'], {})
        self.assertEqual(panel.snapshot(0)['coverage'], [])
        for message in channel.deliver(.25): panel.receive(message)
        self.assertEqual(panel.snapshot(.25)['vehicles']['BF01']['heartbeat']['pose_mm'][0], 123)
        self.assertEqual(panel.snapshot(.25)['coverage'], [])
        for message in channel.deliver(1): panel.receive(message)
        self.assertEqual(panel.snapshot(1)['coverage'], [{'level':'EG', 'area':'R0_001'}])
        self.assertEqual(set(panel.__dict__), {'sequence','vehicles','events','messages','coverage','duplicates'})

    def test_duplicates_and_old_sequence_do_not_overwrite_new_state(self):
        channel = comm.Channel([0, 0], 1, 1); panel = comm.ReceivedControlRoom()
        for i in range(2): channel.emit('BF01', 'heartbeat', heartbeat(i), i)
        messages = channel.deliver(2)
        panel.receive(messages[1]); self.assertFalse(panel.receive(messages[0]))
        self.assertFalse(panel.receive(messages[1]))
        self.assertEqual(panel.snapshot(2)['duplicates'], 2)
        self.assertEqual(panel.snapshot(2)['vehicles']['BF01']['heartbeat']['pose_mm'][0], 1)
        messages[1]['payload']['pose_mm'][0] = 999
        self.assertEqual(panel.snapshot(2)['vehicles']['BF01']['heartbeat']['pose_mm'][0], 1)

    def test_journal_exclusive_and_exact_received_envelopes(self):
        channel = comm.Channel([0, 0], 1, 1); panel = comm.ReceivedControlRoom()
        channel.emit('BF01', 'heartbeat', heartbeat(), 0)
        message = channel.deliver(1)[0]; panel.receive(message)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'events.jsonl'; panel.write_jsonl(path)
            self.assertEqual(json.loads(path.read_text()), message)
            with self.assertRaises(FileExistsError): panel.write_jsonl(path)

    def test_invalid_coverage_does_not_mutate_control_room(self):
        panel = comm.ReceivedControlRoom()
        message = {'seq':1,'vehicle_id':'BF01','sent_s':0,'received_s':1,'kind':'event',
                   'payload':{'event':'inspection_completed','details':{}},'delivered_late':False}
        with self.assertRaises(ValueError): panel.receive(message)
        self.assertEqual(panel.snapshot(1)['vehicles'], {})


if __name__ == '__main__': unittest.main()
