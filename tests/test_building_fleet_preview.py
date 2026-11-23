"""Pure experimental-prefix contracts; these fixtures are not qualified runs."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_building_fleet_demo as complete
import build_building_fleet_preview as preview


def fixture():
    return {'format': 'solidcraftbot.building-fleet-program/1', 'complete': False,
        'duration_s': 2, 'received_messages': [{'original': 'receipt'}],
        'camera_captures': {'own': {'original': 'capture'}},
        'trajectories': [{'vehicle_id': 'BF%02d' % i, 'episodes': [
            {'start_s': 0, 'end_s': 2, 'points': [
                {'time_s': t, 'pose_mm_rad': [i, t, 0],
                 'velocity_mm_rad_s': [0, 1, 0], 'acceleration_mm_rad_s2': [0, 0, 0]}
                for t in (0, 1, 2)]}]} for i in range(1, 21)]}


class PreviewTests(unittest.TestCase):
    def test_complete_builder_still_rejects_partial(self):
        with self.assertRaisesRegex(ValueError, 'Complete compiled'):
            complete.completed_program(fixture())

    def test_consistent_recording_preserves_every_node_and_receipt(self):
        source = fixture()
        original = copy.deepcopy(source)
        value, clipping = preview.partial_prefix(source)
        self.assertEqual(source, original)
        self.assertEqual(value, source)
        self.assertIs(value['complete'], False)
        self.assertFalse(clipping['clipped_to_common_recorded_prefix'])
        self.assertEqual(clipping['recorded_end_s'], 2)
        self.assertEqual(value['received_messages'], source['received_messages'])
        self.assertEqual(value['camera_captures'], source['camera_captures'])

    def test_interrupted_append_uses_only_common_existing_knots(self):
        source = fixture()
        source['trajectories'][-1]['episodes'][0]['end_s'] = 1
        source['trajectories'][-1]['episodes'][0]['points'].pop()
        original = copy.deepcopy(source)
        value, clipping = preview.partial_prefix(source)
        self.assertEqual(source, original)
        self.assertEqual(value['duration_s'], 1)
        self.assertTrue(clipping['clipped_to_common_recorded_prefix'])
        for before, after in zip(source['trajectories'], value['trajectories']):
            self.assertEqual(after['episodes'][0]['points'], before['episodes'][0]['points'][:2])
            self.assertEqual(after['episodes'][0]['end_s'], 1)

    def test_complete_or_missing_fleet_is_not_an_experimental_recording(self):
        for mutate in (lambda p: p.update(complete=True),
                       lambda p: p['trajectories'].pop(),
                       lambda p: p.update(duration_s=float('nan'))):
            source = fixture()
            mutate(source)
            with self.assertRaises(ValueError):
                preview.partial_prefix(source)

    def test_no_new_interpolated_common_endpoint_is_invented(self):
        source = fixture()
        source['trajectories'][-1]['episodes'][0]['points'] = [
            source['trajectories'][-1]['episodes'][0]['points'][0],
            {**source['trajectories'][-1]['episodes'][0]['points'][1], 'time_s': .5}]
        source['trajectories'][-1]['episodes'][0]['end_s'] = .5
        with self.assertRaisesRegex(ValueError, 'No positive common'):
            preview.partial_prefix(source)


if __name__ == '__main__':
    unittest.main()
