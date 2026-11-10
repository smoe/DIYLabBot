"""The independent-client pipe cannot turn a delayed reply into a stop receipt."""
import io
import json
from pathlib import Path
import queue
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests/sila2-dotnet'))
from runner_bridge import TecanStation
from cf01_sila2_client import UncertainExecution


class PipeReceiptTests(unittest.TestCase):
    def station(self):
        station = object.__new__(TecanStation)
        station.failed = False
        station.responses = queue.Queue()
        station.process = types.SimpleNamespace(stdin=io.StringIO())
        return station

    def assert_no_further_effect(self, station):
        before = station.process.stdin.getvalue()
        with self.assertRaises(UncertainExecution):
            station.exchange('submit', name='Stop', parameters={})
        self.assertEqual(station.process.stdin.getvalue(), before)

    def test_mismatched_late_receipt_poisoned_before_another_effect(self):
        station = self.station()
        station.responses.put(json.dumps({'ok': True, 'call_id': 'old-call', 'response': {'state': {}}}))
        with self.assertRaises(UncertainExecution):
            station.exchange('submit', name='Stop', parameters={})
        self.assertTrue(station.failed)
        self.assert_no_further_effect(station)

    def test_response_deadline_and_invalid_framing_do_not_allow_more_effects(self):
        station = self.station()
        with patch.object(station.responses, 'get', side_effect=queue.Empty):
            with self.assertRaises(UncertainExecution):
                station.exchange('submit', name='RunCentrifuge', parameters={})
        self.assert_no_further_effect(station)
        station = self.station()
        station.responses.put('not a response')
        with self.assertRaises(UncertainExecution):
            station.exchange('submit', name='RunCentrifuge', parameters={})
        self.assert_no_further_effect(station)
