"""Bounded live service checks without rebuilding CAD or running the full seed."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
live = importlib.import_module('run_building_fleet_patrol')


class PatrolServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = {'missions': {'targets': [
            {'level': 'EG', 'area': 'A'}, {'level': 'OG3', 'area': 'B'}]}}
        self.app = live.Application(self.source, {}, Path(self.directory.name), lambda progress: None)
        self.addCleanup(self.app.journal.close)
        self.job = {'request_id': 'process-1', 'pickup': {'level': 'EG', 'area': 'A'},
                    'delivery': {'level': 'OG3', 'area': 'B'}}

    def test_profile_pins_current_fleet_and_keeps_qualification_open(self):
        value = live.load_profile()
        self.assertFalse(value['qualification']['loads_implemented'])
        self.assertFalse(value['qualification']['native_full_program_verified'])
        self.assertEqual(value['patrol']['termination'], 'explicit_stop')
        self.assertEqual(value['patrol']['corner_timing'], 'variable_progress')
        legacy = copy.deepcopy(value)
        del legacy['patrol']['corner_timing']
        with patch.object(live.model, 'read_json', return_value=legacy):
            self.assertEqual(live.load_profile(), legacy)

    def test_profile_rejects_stale_pin_or_unsupported_policy(self):
        value = live.load_profile()
        for mutation in ('source', 'policy', 'corner_timing'):
            changed = copy.deepcopy(value)
            if mutation == 'source':
                changed['sources']['fleet']['sha256'] = '0' * 64
            elif mutation == 'policy':
                changed['recruitment']['diversion'] = 'teleport'
            else:
                changed['patrol']['corner_timing'] = 'unknown'
            with patch.object(live.model, 'read_json', return_value=changed):
                with self.assertRaises(ValueError):
                    live.load_profile()

    def test_duplicate_request_does_not_enqueue_twice(self):
        first = self.app.request(self.job)
        self.assertEqual(first, self.app.request(self.job))
        self.assertEqual(self.app.commands.qsize(), 1)
        changed = copy.deepcopy(self.job)
        changed['delivery'] = changed['pickup']
        with self.assertRaises(ValueError):
            self.app.request(changed)

    def test_unknown_or_excluded_destination_never_enters_engine(self):
        for bad in ({'level': 'KG', 'area': 'K0_013'}, {'level': 'OG3', 'area': 'R3_028'}):
            with self.assertRaises(ValueError):
                self.app.request({**self.job, 'pickup': bad})
        self.assertTrue(self.app.commands.empty())

    def test_pause_is_immediate_even_while_engine_is_preparing(self):
        self.app.control('pause')
        self.assertTrue(self.app.snapshot()['paused'])
        self.app.control('resume')
        self.assertFalse(self.app.snapshot()['paused'])

    def test_snapshot_is_detached_from_engine_state(self):
        self.app.state['states'] = [{'id': 'BF01'}]
        returned = self.app.snapshot()
        returned['states'][0]['id'] = 'different'
        self.assertEqual(self.app.snapshot()['states'][0]['id'], 'BF01')

    def test_route_preparation_keeps_last_executed_scene_available(self):
        self.app.state = {'format': 'solidcraftbot.building-fleet-live-snapshot/1',
                          'status': 'ready', 'states': [{'id': 'BF01'}], 'model_time_s': .15}
        self.app.progress({'phase': 'own_drive_prepare', 'model_time_s': .15})
        snapshot = self.app.snapshot()
        self.assertEqual(snapshot['status'], 'ready')
        self.assertEqual(snapshot['states'], [{'id': 'BF01'}])
        self.assertEqual(snapshot['model_time_s'], .15)

    def test_fault_stops_worker_and_remains_visible(self):
        def fail(progress):
            raise ValueError('floor support failed')
        self.app.factory = fail
        self.app.run()
        self.assertEqual(self.app.snapshot()['status'], 'error')
        self.assertIn('floor support failed', self.app.snapshot()['error'])
        with self.assertRaises(ValueError):
            self.app.request(self.job)
        rows = [json.loads(line) for line in (Path(self.directory.name) / 'commands.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['event'], 'engine_error')


if __name__ == '__main__':
    unittest.main()
