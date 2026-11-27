import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from centrifuge_control import ControlError, Simulator
from cf01_empty_seat_handoff import EmptySeatHandoffSimulator


class EmptySeatHandoffTests(unittest.TestCase):
    def setUp(self):
        known_empty = {slot: {'present': False, 'seated': False, 'mass_g': None} for slot in range(1, 13)}
        self.station = EmptySeatHandoffSimulator(initial_slots=known_empty)
        self.token = self.station.execute('acquire', client_id='test')['token']

    def handoff(self, command, **observations):
        return self.station.execute(command, self.token, **{'slot': 7, 'sample_id': 'tube-07', **observations})

    def open_indexed(self):
        self.station.execute('index', self.token, slot=7)
        self.station.execute('open_lid', self.token)

    def test_default_simulator_keeps_ordinary_command_contract(self):
        with self.assertRaisesRegex(ControlError, 'Unknown command'):
            Simulator().execute('begin_raise_empty_support', slot=7, sample_id='tube-07', empty_confirmed=True)

    def test_raise_needs_open_lid_secured_index_and_empty_slot(self):
        with self.assertRaisesRegex(ControlError, 'Fully open lid'):
            self.handoff('begin_raise_empty_support', empty_confirmed=True)
        self.open_indexed()
        with self.assertRaisesRegex(ControlError, 'match the secured index'):
            self.handoff('begin_raise_empty_support', slot=1, empty_confirmed=True)
        self.station.brake_engage_confirmed = False
        with self.assertRaisesRegex(ControlError, 'confirmed parking brake'):
            self.handoff('begin_raise_empty_support', empty_confirmed=True)
        self.station.brake_engage_confirmed = True
        self.station.slots[7].update(present=True, seated=True, mass_g=1.2)
        with self.assertRaisesRegex(ControlError, 'known empty'):
            self.handoff('begin_raise_empty_support', empty_confirmed=True)
        self.assertIsNone(self.station.status()['pusher_handoff'])

    def test_supported_ownership_clearance_and_park_are_ordered(self):
        self.open_indexed()
        self.handoff('begin_raise_empty_support', empty_confirmed=True)
        with self.assertRaisesRegex(ControlError, 'synthetic observation'):
            self.handoff('confirm_empty_support_extended', extended_confirmed=False)
        raised = self.handoff('confirm_empty_support_extended', extended_confirmed=True)
        self.assertFalse(raised['slots'][7]['present'] or raised['grip_frame']['valid'])
        self.station.robot_clear = False
        tube = {'rested_confirmed': True, 'released_confirmed': True,
                'cap_closed_confirmed': True, 'mass_g': 1.2}
        with self.assertRaisesRegex(ControlError, 'selected handoff identity'):
            self.handoff('confirm_tube_on_support', **tube, sample_id='different-tube')
        with self.assertRaisesRegex(ControlError, 'synthetic observation'):
            self.handoff('confirm_tube_on_support', **{**tube, 'rested_confirmed': False})
        supported = self.handoff('confirm_tube_on_support', **tube)
        self.assertEqual(supported['slots'][7], {'present': True, 'seated': False, 'mass_g': 1.2})
        for other in ('lower_tube', 'retract_lift', 'close_lid', 'index', 'start', 'release'):
            with self.subTest(command=other), self.assertRaisesRegex(ControlError, 'active supported handoff'):
                self.station.execute(other, self.token)
        with self.assertRaisesRegex(ControlError, 'Robot must be clear'):
            self.handoff('begin_lower_supported_tube', workspace_clear_confirmed=True)
        self.station.robot_clear = True
        self.handoff('begin_lower_supported_tube', workspace_clear_confirmed=True)
        with self.assertRaisesRegex(ControlError, 'Expected supported handoff phase'):
            self.handoff('confirm_empty_support_parked', parked_confirmed=True)
        self.handoff('confirm_supported_tube_seated', seated_confirmed=True)
        with self.assertRaisesRegex(ControlError, 'active supported handoff'):
            self.station.execute('close_lid', self.token)
        with self.assertRaisesRegex(ControlError, 'synthetic observation'):
            self.handoff('confirm_empty_support_parked', parked_confirmed=False)
        seated = self.handoff('confirm_empty_support_parked', parked_confirmed=True)
        self.assertIsNone(seated['pusher_handoff'])
        self.assertEqual(seated['slots'][7], {'present': True, 'seated': True, 'mass_g': 1.2})
        self.assertTrue(self.station.execute('close_lid', self.token)['lid_locked'])


if __name__ == '__main__':
    unittest.main()
