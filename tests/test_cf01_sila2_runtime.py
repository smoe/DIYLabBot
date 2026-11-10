"""Network leases, independent mock time and uncertain station effects."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cf01_sila2_runtime import StationRuntime, reconcile_station
from cf01_sila2_store import StoreError
from centrifuge_control import ControlError


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'station.sqlite3'
        self.now = 0.
        self.runtime = StationRuntime(self.path, clock=lambda: self.now)
        self.runtime.lock('owner-lock', 60, 'operator')

    def tearDown(self):
        self.runtime.close()
        self.directory.cleanup()

    def execute(self, name, **args):
        request, execution = str(uuid.uuid4()), str(uuid.uuid4())
        result = self.runtime.invoke(name, args, 'operator', request, execution)
        if name in {c['id'] for c in self.runtime.commands if c['observable']}:
            result = self.runtime.poll(execution)
        return result

    def load_rotor(self):
        for slot in range(1, 13):
            self.execute('close_lid')
            self.execute('index', slot=slot)
            self.execute('open_lid')
            self.execute('confirm_seated', mass_g=2., seated_confirmed=True, cap_closed_confirmed=True)
        self.execute('close_lid')

    def test_duplicate_request_has_no_second_effect(self):
        request, execution = str(uuid.uuid4()), str(uuid.uuid4())
        self.runtime.invoke('index', {'slot': 1}, 'operator', request, execution)
        self.runtime.poll(execution)
        count = len(self.runtime.sim.events)
        with self.assertRaises(ControlError) as caught:
            self.runtime.invoke('index', {'slot': 2}, 'operator', request, str(uuid.uuid4()))
        self.assertEqual(caught.exception.code, 'DuplicateRequest')
        self.assertEqual(self.runtime.sim.indexed_slot, 1)
        self.assertEqual(len(self.runtime.sim.events), count)

    def test_slot_projection_distinguishes_unknown_mass_and_does_not_alias_core(self):
        empty = self.runtime.status()['rotor_slots']
        self.assertEqual([value['slot'] for value in empty], list(range(1, 13)))
        self.assertTrue(all(not value['present'] and not value['mass_valid'] for value in empty))
        self.execute('index', slot=1)
        self.execute('open_lid')
        self.execute('confirm_seated', mass_g=2., seated_confirmed=True, cap_closed_confirmed=True)
        observed = self.runtime.status()['rotor_slots']
        self.assertEqual(observed[0], {'slot': 1, 'present': True, 'seated': True, 'mass_valid': True, 'mass_g': 2.})
        observed[0]['mass_g'] = 99.
        self.assertEqual(self.runtime.status()['rotor_slots'][0]['mass_g'], 2.)
        self.assertFalse(empty[0]['present'])

    def test_synthetic_robot_access_requires_matching_transfer_before_withdrawal(self):
        self.execute('index', slot=1)
        self.execute('open_lid')
        def observe(event, sample='Sample01', request=None, boot=None):
            return self.runtime.observe_robot(boot or self.runtime.sim.boot_id, request or str(uuid.uuid4()),
                                               'operator', sample, 1, event, 'operator')
        with self.assertRaises(ControlError) as caught:
            observe('withdraw')
        self.assertEqual(caught.exception.code, 'InvalidObservation')
        with self.assertRaises(ControlError):
            observe('begin_loading', boot=str(uuid.uuid4()))
        request = str(uuid.uuid4())
        observe('begin_loading', request=request)
        self.assertFalse(self.runtime.status()['robot_clear'])
        with self.assertRaises(ControlError) as duplicate:
            observe('begin_loading', request=request)
        self.assertEqual(duplicate.exception.code, 'DuplicateRequest')
        with self.assertRaises(ControlError):
            observe('withdraw')
        self.execute('confirm_seated', mass_g=2., seated_confirmed=True, cap_closed_confirmed=True)
        with self.assertRaises(ControlError):
            observe('withdraw', sample='DifferentSample')
        observe('withdraw')
        self.assertTrue(self.runtime.status()['robot_clear'])
        self.assertIsNone(self.runtime.robot_access)
        self.execute('present_tube')
        observe('begin_removal')
        with self.assertRaises(ControlError):
            observe('withdraw')
        self.execute('confirm_removed', grasp_confirmed=True, tube_absent=True)
        observe('withdraw')
        self.execute('retract_lift')
        self.assertTrue(self.runtime.status()['robot_clear'])
        self.assertFalse(self.runtime.status()['rotor_slots'][0]['present'])

    def test_nonfinite_numbers_are_validation_errors_not_storage_faults(self):
        for value in [float('inf'), float('nan'), -1., True]:
            with self.subTest(value=value), self.assertRaises(ControlError) as caught:
                self.runtime.invoke('start', {'rcf_x_g': 100., 'duration_s': value}, 'operator', str(uuid.uuid4()), str(uuid.uuid4()))
            self.assertEqual(caught.exception.code, 'InvalidArgument')
            self.assertFalse(self.runtime.store_fault)
            self.assertFalse(self.runtime.needs_reconciliation)

    def test_lock_expiry_does_not_release_process_responsibility(self):
        self.now = 61.
        status = self.runtime.status()
        self.assertIsNone(self.runtime.lock_id)
        self.assertTrue(status['recovery_required'])
        self.assertIsNotNone(self.runtime.sim.owner)
        self.runtime.lock('new-lock', 60, 'different-operator')
        with self.assertRaises(ControlError) as caught:
            self.runtime.invoke('open_lid', {}, 'different-operator', str(uuid.uuid4()), str(uuid.uuid4()))
        self.assertEqual(caught.exception.code, 'RecoveryRequired')

    def test_touch_requires_same_identity_and_refreshes_core_watchdog(self):
        with self.assertRaises(ControlError):
            self.runtime.touch('owner-lock', 'other-operator')
        self.now = self.runtime.sim.spec['handling']['owner_timeout_s'] / 2
        self.runtime.touch('owner-lock', 'operator')
        self.assertGreater(self.runtime.sim.deadline, self.now)
        self.assertFalse(self.runtime.status()['recovery_required'])

    def test_time_progress_and_cancellation_require_braking_completion(self):
        self.load_rotor()
        request, execution = str(uuid.uuid4()), str(uuid.uuid4())
        result = self.runtime.invoke('start', {'rcf_x_g': 100., 'duration_s': 5.}, 'operator', request, execution)
        self.assertEqual(result['phase'], 'running')
        self.now = 1.
        self.runtime.cancel(execution)
        stopping = self.runtime.poll(execution)
        self.assertEqual(stopping['phase'], 'stopping')
        self.assertFalse(stopping['state']['standstill_confirmed'])
        self.now += self.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + .01
        stopped = self.runtime.poll(execution)
        self.assertEqual(stopped['phase'], 'canceled')
        self.assertTrue(stopped['state']['standstill_confirmed'])
        self.assertTrue(stopped['state']['parking_brake_held'])

    def test_normal_spin_completes_from_server_clock_without_client_advance(self):
        self.load_rotor()
        execution = str(uuid.uuid4())
        self.runtime.invoke('start', {'rcf_x_g': 100., 'duration_s': 1.}, 'operator', str(uuid.uuid4()), execution)
        self.now = 1.1
        self.runtime.tick()
        self.assertEqual(self.runtime.sim.run['phase'], 'braking')
        self.now += self.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + .01
        self.runtime.tick()
        self.assertEqual(self.runtime.poll(execution)['phase'], 'succeeded')

    def test_disk_failure_prevents_motion_but_not_controlled_stop(self):
        before = self.runtime.sim.indexed_slot
        with patch.object(self.runtime.store, 'begin', side_effect=OSError('disk unavailable')):
            with self.assertRaises(ControlError) as caught:
                self.runtime.invoke('index', {'slot': 1}, 'operator', str(uuid.uuid4()), str(uuid.uuid4()))
            self.assertEqual(caught.exception.code, 'PersistenceFailure')
            self.assertEqual(self.runtime.sim.indexed_slot, before)
            with self.assertRaises(ControlError):
                self.runtime.invoke('stop', {}, 'operator', str(uuid.uuid4()))
        self.assertTrue(self.runtime.status()['recovery_required'])
        self.assertTrue(any(e['kind'] == 'CF01.stop' for e in self.runtime.sim.events))

    def test_restart_requires_complete_explicit_reconciliation_and_never_replays(self):
        self.load_rotor()
        request, execution = str(uuid.uuid4()), str(uuid.uuid4())
        self.runtime.invoke('start', {'rcf_x_g': 100., 'duration_s': 5.}, 'operator', request, execution)
        old_boot = self.runtime.sim.boot_id
        self.runtime.close()
        self.runtime = StationRuntime(self.path, clock=lambda: self.now)
        self.assertNotEqual(self.runtime.sim.boot_id, old_boot)
        self.assertEqual(self.runtime.jobs, {})
        self.assertTrue(self.runtime.status()['recovery_required'])
        self.assertEqual(self.runtime.store.pending()[0]['request_id'], request)
        observation = {'evidence': 'synthetic_person_confirmation', 'actor_id': 'reviewer',
                       'server_uuid': self.runtime.store.server_uuid,
                       'expected_boot_id': self.runtime.sim.boot_id,
                       'acknowledged_uncertain_request_ids': [request],
                       **{k: True for k in ['standstill_confirmed', 'parking_brake_held', 'robot_clear', 'pusher_parked', 'lid_closed_locked']},
                       'slots': [{'slot': n, 'present': True, 'seated': True, 'cap_closed': True, 'mass_g': 2.} for n in range(1, 13)]}
        self.runtime.close()
        bad = copy.deepcopy(observation)
        bad['slots'].pop()
        with self.assertRaisesRegex(StoreError, 'Every numbered'):
            reconcile_station(self.path, bad)
        bad = copy.deepcopy(observation)
        bad['slots'][0]['slot'] = True
        with self.assertRaisesRegex(StoreError, 'Every numbered'):
            reconcile_station(self.path, bad)
        bad = copy.deepcopy(observation)
        del bad['slots'][0]['mass_g']
        with self.assertRaisesRegex(StoreError, 'explicit null'):
            reconcile_station(self.path, bad)
        reconcile_station(self.path, observation)
        self.runtime = StationRuntime(self.path, clock=lambda: self.now)
        self.assertFalse(self.runtime.status()['recovery_required'])
        self.assertIsNone(self.runtime.sim.run)
        self.runtime.lock('fresh-lock', 60, 'operator')
        self.assertFalse(self.runtime.store.pending())

    def test_reconciliation_does_not_create_a_missing_station_store(self):
        missing = self.path.with_name('missing.sqlite3')
        with self.assertRaisesRegex(StoreError, 'existing station store'):
            reconcile_station(missing, {'evidence': 'synthetic_person_confirmation'})
        self.assertFalse(missing.exists())
        self.assertFalse(Path(str(missing) + '.server-lock').exists())


if __name__ == '__main__':
    unittest.main()
