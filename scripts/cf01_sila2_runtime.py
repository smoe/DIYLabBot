"""One CF01 simulator/protocol core behind the SiLA transport and its journal.

Transport leases are not process ownership. Uncertain effects, disk failures and
restarts fail closed, while the controlled stop remains available.
"""
import copy
import hashlib
import json
import math
import time
import uuid

import build_cf01_sila2 as contract
import cf01_rack_batch as batch
from cf01_sila2_store import ProcessStore, StoreError, DuplicateIntent, encode
from centrifuge_control import Simulator, ControlError
from centrifuge_protocol import MockProtocol, state_si


def source_signature():
    profile, _, _ = contract.load()
    return hashlib.sha256(encode({'profile': profile,
        'qualification_profile_sha256': hashlib.sha256(batch.SOURCE.read_bytes()).hexdigest()}).encode()).hexdigest()


class StationRuntime:
    def __init__(self, path, clock=None):
        self.profile, sources, self.commands = contract.load()
        self.clock_mode = 'monotonic_realtime' if clock is None else 'injected_manual'
        epoch = time.monotonic()
        self.clock = clock or (lambda: time.monotonic() - epoch)
        self.store = ProcessStore(path, source_signature())
        self.store_fault = False
        self.needs_reconciliation = False
        self.lock_id = None
        self.lock_principal = None
        self.lock_timeout = None
        self.lock_deadline = None
        self.core_token = None
        self.jobs = {}
        self.robot_access = None
        data = sources['network_batch']
        batch.validate(data)
        capacity = len(data['samples'])
        self.sim = Simulator(clock=self.clock, qualification=data['simulation_qualification'],
                             initial_slots={i: {'present': False, 'seated': False, 'mass_g': None} for i in range(1, capacity + 1)})
        self.bridge = MockProtocol(self.sim)
        try:
            previous = self.store.read_snapshot()
            if previous is not None:
                self.robot_access = copy.deepcopy(previous.get('robot_access'))
                fresh_boot = self.sim.boot_id
                allowed = set(vars(self.sim)) - {'spec', 'p', 'clock'}
                values = previous['backend']
                if set(values) != allowed:
                    raise StoreError('Unsupported station checkpoint; explicit migration required')
                for key, value in values.items():
                    setattr(self.sim, key, copy.deepcopy(value))
                self.sim.slots = {int(k): v for k, v in self.sim.slots.items()}
                self.sim.boot_id = fresh_boot
                self.sim.events = []
                self.sim.event('CF01.network.boot', previous_boot_id=values['boot_id'])
                self.needs_reconciliation = bool(previous['needs_reconciliation'] or self.store.pending() or self.sim.owner)
                # Monotonic epochs are process-local. Never replay an old job or
                # use an old stopping deadline as a deadline in the new boot.
                if self.needs_reconciliation:
                    self.sim.stopping = None
                    self.sim.fault = None
                    self.sim._trip('RecoveryRequired')
                self.sim.feedback_time = self.clock()
                self.sim.encoder_feedback_time = self.clock()
            if self.store.pending():
                self.needs_reconciliation = True
                self.sim._trip('RecoveryRequired')
            self._checkpoint()
        except BaseException:
            self.store.close()
            raise

    def snapshot(self):
        return {'format': 'solidcraftbot.cf01-network-checkpoint/1',
                'backend': {k: copy.deepcopy(v) for k, v in vars(self.sim).items() if k not in {'spec', 'p', 'clock'}},
                'needs_reconciliation': self.needs_reconciliation, 'robot_access': copy.deepcopy(self.robot_access)}

    def _disk_failed(self):
        self.store_fault = True
        self.needs_reconciliation = True
        self.sim._trip('RecoveryRequired')
        self.sim.execute('stop')

    def _checkpoint(self):
        if self.store_fault:
            return
        try:
            self.store.checkpoint(self.snapshot())
        except Exception as error:
            self._disk_failed()
            raise ControlError('PersistenceFailure', 'Station checkpoint failed; process recovery is required') from error

    def tick(self):
        self.sim.execute('status')
        if self.lock_id is not None and self.lock_deadline is not None and self.clock() >= self.lock_deadline:
            self.lock_id = self.lock_principal = None
            self.lock_deadline = None
            self.needs_reconciliation = True
            self.sim._trip('OwnerTimeout')
            self.sim.execute('stop')
            self._checkpoint()

    def status(self):
        self.tick()
        status = self.sim.execute('status')
        return {**state_si(status), 'process_time_s': self.clock(),
                'recovery_required': self.needs_reconciliation or status['fault'] is not None,
                'clock_mode': self.clock_mode, 'run_phase': (status['run'] or {}).get('phase', 'idle'),
                'rotor_slots': [{'slot': slot, 'present': value['present'], 'seated': value['seated'],
                                 'mass_valid': value['mass_g'] is not None,
                                 'mass_g': value['mass_g'] if value['mass_g'] is not None else 0.}
                                for slot, value in sorted(self.sim.slots.items())]}

    def _begin(self, request_id, name, args, principal, execution_uuid=None):
        try:
            self.store.begin(request_id, self.sim.boot_id, name, args, principal, execution_uuid)
        except DuplicateIntent as error:
            raise ControlError('DuplicateRequest', str(error)) from error
        except StoreError:
            raise
        except Exception as error:
            self._disk_failed()
            raise ControlError('PersistenceFailure', 'Could not persist command intent; effect refused') from error

    def _finish(self, request_id, phase, result):
        try:
            self.store.finish(request_id, phase, result, self.snapshot())
        except Exception as error:
            self._disk_failed()
            raise ControlError('PersistenceFailure', 'Could not persist command outcome; effect remains uncertain') from error

    def lock(self, identifier, timeout, principal):
        self.tick()
        if self.lock_id is not None:
            raise ControlError('ServerAlreadyLocked', 'Server already locked')
        if not isinstance(identifier, str) or not identifier.strip() or type(timeout) is not int or timeout < 0:
            raise ValueError('Nonempty LockIdentifier and nonnegative integer Timeout required')
        if self.store_fault:
            raise ControlError('PersistenceFailure', 'Station journal unavailable')
        request = str(uuid.uuid4())
        self._begin(request, 'LockServer', {'lock_identifier': identifier, 'timeout': timeout}, principal)
        self.lock_id, self.lock_principal = identifier, principal
        self.lock_timeout = timeout
        self.lock_deadline = self.clock() + timeout if timeout else None
        if self.sim.owner is None and not self.needs_reconciliation:
            self.core_token = self.sim.execute('acquire', client_id=principal)['token']
        self._finish(request, 'succeeded', {'lock_acquired': True})

    def touch(self, identifier, principal):
        self.tick()
        if self.lock_id is not None:
            if identifier != self.lock_id or principal != self.lock_principal:
                raise ControlError('InvalidLockIdentifier', 'Lock belongs to another client or principal')
            if self.lock_timeout:
                self.lock_deadline = self.clock() + self.lock_timeout
            if self.core_token:
                self.sim.execute('heartbeat', self.core_token)
        elif identifier:
            raise ControlError('InvalidLockIdentifier', 'Lock no longer exists')

    def unlock(self, identifier, principal):
        self.tick()
        if self.lock_id is None:
            raise ControlError('ServerNotLocked', 'No lock exists')
        if identifier != self.lock_id or principal != self.lock_principal:
            raise ControlError('InvalidLockIdentifier', 'Invalid lock owner')
        request = str(uuid.uuid4())
        self._begin(request, 'UnlockServer', {'lock_identifier': identifier}, principal)
        # Standard UnlockServer releases its lease even if process recovery is
        # needed. It does not claim to release an unresolved physical inventory.
        self.lock_id = self.lock_principal = self.lock_deadline = None
        active = any(j['phase'] not in {'succeeded', 'failed', 'canceled'} for j in self.jobs.values())
        if active or self.needs_reconciliation:
            self.sim.execute('stop')
            self.needs_reconciliation = True
        elif self.core_token:
            try:
                self.sim.execute('release', self.core_token)
                self.core_token = None
            except ControlError:
                self.sim.execute('stop')
                self.needs_reconciliation = True
        self._finish(request, 'succeeded', {'lock_released': True, 'process_recovery_required': self.needs_reconciliation})

    def invoke(self, name, args, principal, request_id=None, execution_uuid=None):
        self.tick()
        if name in {'status', 'rotation_feedback'}:
            return {'success': True, 'state': self.status()}
        command = next((c for c in self.commands if c['id'] == name), None)
        if command is None or set(args) != set(command['arguments']):
            raise ControlError('InvalidArgument', 'Exactly the declared command arguments are required')
        for key, kind in command['arguments'].items():
            value = args[key]
            valid = ((kind == 'boolean' and type(value) is bool)
                     or (kind == 'integer' and type(value) is int)
                     or (kind == 'number' and type(value) in (int, float) and math.isfinite(value)))
            if not valid:
                raise ControlError('InvalidArgument', 'Invalid typed value for ' + key)
            rule = self.profile['parameters'].get(key, {})
            if ('exclusive_minimum' in rule and value <= rule['exclusive_minimum']) or ('minimum' in rule and value < rule['minimum']):
                raise ControlError('InvalidArgument', 'Value below declared bound: ' + key)
            if 'maximum_reference' in rule:
                maximum = self.sim.spec
                for field in rule['maximum_reference']:
                    maximum = maximum[field]
                if value > maximum:
                    raise ControlError('InvalidArgument', 'Value above declared bound: ' + key)
        if name == 'stop':
            # A journal fault must never prevent the priority controlled stop.
            try:
                self._begin(request_id, name, args, principal)
            except ControlError as error:
                if error.code == 'PersistenceFailure':
                    self.sim.execute('stop')
                raise
            self.sim.execute('stop')
            result = {'success': True, 'state': self.status()}
            self._finish(request_id, 'succeeded', result)
            return result
        if self.store_fault:
            raise ControlError('PersistenceFailure', 'Journal unavailable; process motion refused')
        if self.needs_reconciliation:
            raise ControlError('RecoveryRequired', 'Explicit local synthetic reconciliation is required')
        if self.lock_id is None or principal != self.lock_principal or self.core_token is None:
            raise ControlError('RecoveryRequired', 'Acquire the standard lock before a process command')
        self._begin(request_id, name, args, principal, execution_uuid)
        events = len(self.sim.events)
        try:
            if command['observable']:
                result = self.bridge.begin(name, self.core_token, **args)
                self.jobs[execution_uuid] = {'core_id': result['id'], 'request_id': request_id,
                                             'principal': principal, 'phase': result['phase']}
                self._checkpoint()
                return result
            self.bridge.invoke(name, self.core_token, **args)
            result = {'success': True, 'state': self.status()}
            self._finish(request_id, 'succeeded', result)
            return result
        except ControlError as error:
            if len(self.sim.events) != events:
                self.needs_reconciliation = True
            self._finish(request_id, 'failed', {'error_code': error.code, 'message': str(error)})
            raise
        except Exception as error:
            self.needs_reconciliation = True
            self.sim.execute('stop')
            self._finish(request_id, 'failed', {'error_code': 'UnexpectedBackendError'})
            raise ControlError('UnexpectedBackendError', 'Backend failure; explicit recovery required') from error

    def poll(self, execution_uuid):
        self.tick()
        job = self.jobs[execution_uuid]
        result = self.bridge.poll(job['core_id'])
        if job.get('finished'):
            return result
        job['phase'] = result['phase']
        if result['phase'] in {'succeeded', 'canceled', 'failed'}:
            self._finish(job['request_id'], result['phase'], result)
            job['finished'] = True
        else:
            self._checkpoint()
        return result

    def cancel(self, execution_uuid, principal=None):
        if execution_uuid not in self.jobs or self.jobs[execution_uuid]['phase'] in {'succeeded', 'canceled', 'failed'}:
            raise ControlError('InvalidCommandExecutionUUID', 'No running observable command for this UUID')
        job = self.jobs[execution_uuid]
        request = str(uuid.uuid5(uuid.UUID(self.store.server_uuid), self.sim.boot_id + '/cancel/' + execution_uuid))
        try:
            self._begin(request, 'CancelCommand', {'execution_uuid': execution_uuid}, principal or job['principal'])
        except ControlError as error:
            if error.code == 'DuplicateRequest':
                return self.bridge.poll(job['core_id'])
            raise
        result = self.bridge.cancel(job['core_id'])
        job['phase'] = result['phase']
        self._finish(request, 'succeeded', {'cancel_accepted': True, 'state': result['state']})
        return result

    def close(self):
        self.store.close()

    def observe_robot(self, boot_id, observation_id, actor_id, sample_id, slot, event, principal):
        """Explicit mock observations; never a general robot-clear setter."""
        self.tick()
        if self.store_fault:
            raise ControlError('PersistenceFailure', 'Station journal unavailable')
        if self.needs_reconciliation or self.sim.fault:
            raise ControlError('RecoveryRequired', 'Reconcile the station before further observations')
        if (boot_id != self.sim.boot_id or not self.lock_id or principal != self.lock_principal
                or actor_id != principal or not isinstance(sample_id, str) or not sample_id.strip()
                or type(slot) is not int or slot != self.sim.indexed_slot
                or event not in self.profile['simulation_feature']['events']):
            raise ControlError('InvalidObservation', 'Observation identity, lock, index or event mismatch')
        arguments = {'boot_id': boot_id, 'actor_id': actor_id, 'sample_id': sample_id, 'slot': slot, 'event': event}
        self._begin(observation_id, 'ObserveRobotAccess', arguments, principal)
        try:
            status = self.sim.execute('status')
            safe = (status['standstill_confirmed'] and status['brake_held'] and self.sim.index_ok
                    and self.sim.lid == 'open')
            item = self.sim.slots[slot]
            if event == 'withdraw':
                expected = {'sample_id': sample_id, 'slot': slot, 'principal': principal}
                valid = self.robot_access and all(self.robot_access[k] == v for k, v in expected.items())
                confirmed = (item['present'] and item['seated'] if valid and self.robot_access['event'] == 'begin_loading'
                             else not item['present'])
                if not safe or not valid or self.sim.robot_clear or not confirmed:
                    raise ControlError('InvalidObservation', 'Matching access and confirmed station transfer required before withdrawal')
                self.sim.robot_clear = True
                self.robot_access = None
            else:
                valid_slot = (not item['present'] and self.sim.lift_mm == 0 if event == 'begin_loading'
                              else item['present'] and self.sim.lift_mm > 0)
                if not safe or not self.sim.robot_clear or self.robot_access or not valid_slot:
                    raise ControlError('InvalidObservation', 'Safe indexed open station and appropriate loading/presentation state required')
                self.sim.robot_clear = False
                self.robot_access = {'sample_id': sample_id, 'slot': slot, 'principal': principal, 'event': event}
            self.sim.event('CF01.synthetic.robot_observation', **arguments, observation_id=observation_id)
            result = {'success': True, 'state': self.status()}
            self._finish(observation_id, 'succeeded', result)
            return result
        except ControlError as error:
            self._finish(observation_id, 'failed', {'error_code': error.code})
            raise


def reconcile_station(path, observation):
    """Local-only full synthetic observation; cannot run while a server is live."""
    from pathlib import Path
    if not Path(path).is_file():
        raise StoreError('Reconciliation requires an existing station store')
    if not isinstance(observation, dict):
        raise StoreError('Reconciliation requires an observation object')
    if observation.get('evidence') != 'synthetic_person_confirmation':
        raise StoreError('Reconciliation requires explicit synthetic person confirmation')
    with ProcessStore(path, source_signature()) as store:
        prior = store.read_snapshot()
        if (observation.get('server_uuid') != store.server_uuid or prior is None
                or observation.get('expected_boot_id') != prior['backend']['boot_id']):
            raise StoreError('Reconciliation observation targets a different server or boot')
        for field in ['standstill_confirmed', 'parking_brake_held', 'robot_clear', 'pusher_parked', 'lid_closed_locked']:
            if observation.get(field) is not True:
                raise StoreError('Positive synthetic observation required: ' + field)
        slots = observation.get('slots')
        fixture = contract.load()[1]['network_batch']
        batch.validate(fixture)
        capacity = len(fixture['samples'])
        if (not isinstance(slots, list) or len(slots) != capacity
                or any(not isinstance(s, dict) or type(s.get('slot')) is not int for s in slots)
                or {s['slot'] for s in slots} != set(range(1, capacity + 1))):
            raise StoreError('Every numbered rotor slot must be explicitly observed')
        initial = {}
        for slot in slots:
            if type(slot.get('present')) is not bool or type(slot.get('seated')) is not bool:
                raise StoreError('Explicit presence/seating observations required')
            if slot['present'] and (not slot['seated'] or slot.get('cap_closed') is not True):
                raise StoreError('Every present tube must be seated and capped')
            if 'mass_g' not in slot:
                raise StoreError('Every slot requires a mass value or explicit null')
            mass = slot['mass_g']
            if mass is not None and (type(mass) not in (int, float) or not math.isfinite(mass) or mass <= 0):
                raise StoreError('Observed mass must be positive or explicitly unknown')
            if not slot['present'] and (slot['seated'] or mass is not None):
                raise StoreError('An empty slot has neither a seated tube nor tube mass')
            initial[slot['slot']] = {'present': slot['present'], 'seated': slot['seated'], 'mass_g': mass}
        sim = Simulator(clock=lambda: 0., initial_slots=initial, qualification=fixture['simulation_qualification'])
        snapshot = {'format': 'solidcraftbot.cf01-network-checkpoint/1',
                    'backend': {k: v for k, v in vars(sim).items() if k not in {'spec', 'p', 'clock'}},
                    'needs_reconciliation': False}
        store.reconcile(observation.get('actor_id'), observation, snapshot)
