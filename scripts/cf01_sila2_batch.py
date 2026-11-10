"""Real TLS station boundary for the existing order-preserving batch runner.

No simulator is constructed here. The runner remains the sole sample ledger.
Each effect has a durable client intent and an independent server journal.
"""
import asyncio
import concurrent.futures
import copy
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

import build_cf01_sila2 as contract
import cf01_rack_batch as batch
from cf01_sila2_client import UncertainExecution, wait_for_execution
from centrifuge_control import ControlError
import centrifuge_protocol as protocol


def from_wire(value):
    if isinstance(value, dict):
        return {re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower(): from_wire(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_wire(item) for item in value]
    return value


class ClientJournal:
    """New run only: never silently replay an old client's uncertain effects."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = os.fdopen(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w')
        self.sequence = 0
        self.failed = False
        self.mutex = threading.RLock()

    def append(self, event, **data):
        with self.mutex:
            if self.failed:
                raise RuntimeError('Client journal failure forbids further effects')
            try:
                self.sequence += 1
                row = json.dumps({'sequence': self.sequence, 'event': event, **data}, allow_nan=False, separators=(',', ':'))
                self.file.write(row + '\n')
                self.file.flush()
                os.fsync(self.file.fileno())
            except BaseException:
                self.failed = True
                raise

    def checkpoint(self, kind, payload, view):
        self.append('runner_checkpoint', kind=kind, payload=payload, view=view)

    def close(self):
        self.file.close()


class NetworkStation:
    """Synchronous runner facade around one async SDK client on its own loop."""
    def __init__(self, ready, username, password, journal, rpc_timeout_s=5.):
        if (not ready.get('tls') or not ready.get('simulation_only')
                or ready.get('hardware_available') is not False):
            raise ValueError('Explicit TLS simulation-only endpoint required')
        if not math.isfinite(rpc_timeout_s) or rpc_timeout_s <= 0:
            raise ValueError('Finite positive RPC timeout required')
        self.contract = protocol.load()
        self.profile, sources, _ = contract.load()
        self.spec = sources['station']
        self.rpc_timeout_s = rpc_timeout_s
        self.ready = copy.deepcopy(ready)
        self.username = username
        self.journal = journal
        self.jobs = {}
        self.lock_id = None
        self.lock_metadata = None
        self._epoch = time.monotonic()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name='cf01-sila-client', daemon=True)
        self.thread.start()
        self.client = None
        try:
            self._sync(self._open(password))
        except BaseException:
            self.close()
            raise

    def now(self):
        return time.monotonic() - self._epoch

    def evidence(self):
        import hashlib
        dependencies = [Path(__file__), Path(contract.__file__), contract.SOURCE,
                        Path(__file__).with_name('cf01_sila2_client.py')]
        return {'server_uuid': self.ready['server_uuid'], 'boot_id': self.ready['boot_id'],
                'tls': True, 'journal': str(self.journal.path), 'rpc_timeout_s': self.rpc_timeout_s,
                'client_source_files_sha256': {str(path.relative_to(contract.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                             for path in dependencies}}

    def advance(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Finite nonnegative wait required')
        time.sleep(seconds)

    def _sync(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=self.rpc_timeout_s + 2)
        except concurrent.futures.TimeoutError as error:
            future.cancel()
            raise UncertainExecution(None, 'Transport deadline expired; retain the client journal and do not repeat effects') from error

    async def _open(self, password):
        from sila.client import Client, ClientConfig
        self.client = Client(ClientConfig(hostname=self.ready['bind'], port=self.ready['port'], tls=True,
                             root_certificates=Path(self.ready['certificate']).read_bytes(),
                             default_timeout=self.rpc_timeout_s * 1000))
        await self.client.open()
        if await self.client.SiLAService.ServerUUID.read() != self.ready['server_uuid']:
            raise ValueError('SiLA server identity mismatch')
        response = await self.client.AuthenticationService.Login(UserIdentification=self.username, Password=password,
                        RequestedServer=self.ready['server_uuid'], RequestedFeatures=[])
        self.auth = await self.client.AuthorizationService.AccessToken.from_native(self.client, response.AccessToken)
        self.unlocked_metadata = await self.client.LockController.LockIdentifier.from_native(self.client, '')
        state = await self._state()
        if state['boot_id'] != self.ready['boot_id'] or state['clock_mode'] != 'monotonic_realtime':
            raise ValueError('Expected boot and monotonic real-time station clock required')
        self.journal.append('connected', server_uuid=self.ready['server_uuid'], boot_id=state['boot_id'],
                            tls=True, simulation_only=True)

    async def _state(self):
        metadata = [self.auth, self.lock_metadata if self.lock_metadata is not None else self.unlocked_metadata]
        result = await self.client.CentrifugeControl.GetStatus(metadata=metadata)
        state = from_wire(result.State)
        if state['boot_id'] != self.ready['boot_id']:
            raise UncertainExecution(None, 'Station restarted; old receipts must not be replayed')
        return state

    def state(self):
        return self._sync(self._state())

    def dispatch(self, transport, name, parameters):
        if transport != 'sila2':
            raise ValueError('Network station requires SiLA transport')
        command = next(c for c in self.contract['commands'] if c['name'] == name)
        arguments = {key: parameters[protocol.wire(transport, key)] for key in command['arguments']}
        if command['id'] not in protocol.PUBLIC and parameters.get('ControlToken') != self.lock_id:
            raise ValueError('Runner lock handle mismatch')
        return self._sync(self._dispatch(command, arguments))

    async def _effect(self, name, arguments, operation, request_id=None):
        request_id = request_id or str(uuid.uuid4())
        self.journal.append('intent', request_id=request_id, command=name, arguments=arguments,
                            server_uuid=self.ready['server_uuid'], boot_id=self.ready['boot_id'])
        try:
            result = await operation(request_id)
        except BaseException:
            # Do not invent rejection when the response was lost. No automatic
            # retry is performed, even with the same request UUID.
            self.journal.append('uncertain', request_id=request_id, command=name)
            raise
        return request_id, result

    async def _dispatch(self, command, arguments):
        identifier = command['id']
        if identifier in {'status', 'heartbeat', 'rotation_feedback'}:
            return {'success': True, 'state': await self._state()}
        if identifier == 'acquire':
            lock_id = str(uuid.uuid4())
            async def acquire(_):
                await self.client.LockController.LockServer(LockIdentifier=lock_id,
                    Timeout=max(1, math.ceil(self.spec['handling']['owner_timeout_s'] * 2)), metadata=[self.auth])
            request_id, _ = await self._effect('LockServer', {'lock_identifier': lock_id}, acquire)
            self.lock_id = lock_id
            self.lock_metadata = await self.client.LockController.LockIdentifier.from_native(self.client, lock_id)
            self.journal.append('completed', request_id=request_id)
            return {'success': True, 'control_token': lock_id, 'state': await self._state()}
        if identifier == 'release':
            async def release(_):
                await self.client.LockController.UnlockServer(LockIdentifier=self.lock_id, metadata=[self.auth])
            request_id, _ = await self._effect('UnlockServer', {'lock_identifier': self.lock_id}, release)
            self.lock_id = self.lock_metadata = None
            self.journal.append('completed', request_id=request_id)
            return {'success': True, 'state': await self._state()}

        async def invoke(request):
            intent = await self.client.CentrifugeControl.RequestIdentifier.from_native(self.client, request)
            metadata = [self.auth, intent] + ([self.lock_metadata] if self.lock_metadata is not None else [])
            return await getattr(self.client.CentrifugeControl, command['name'])(
                metadata=metadata, **{contract.base.camel(key): value for key, value in arguments.items()})

        request_id, result = await self._effect(command['name'], arguments, invoke)
        if not command['observable']:
            self.journal.append('completed', request_id=request_id)
            return {'success': True, 'state': from_wire(result.State)}
        execution_id = result.command_execution_uuid
        self.journal.append('accepted', request_id=request_id, execution_uuid=execution_id)
        timeout = batch.load()['command_execution']['completion_timeout_s']
        if identifier == 'start':
            timeout += arguments['duration_s'] + self.spec['mechanisms']['braking']['simulation_stop_s']
        task = asyncio.create_task(wait_for_execution(result, timeout))
        self.jobs[execution_id] = {'task': task, 'request_id': request_id, 'command': identifier, 'terminal': None}
        return await self._poll(execution_id)

    async def _poll(self, execution_id):
        from sila.client import DefinedExecutionError
        job = self.jobs[execution_id]
        state = await self._state()
        task = job['task']
        if task.done():
            if job['terminal'] is None:
                try:
                    result = task.result()
                    job['terminal'] = {'phase': 'succeeded', 'error_code': '', 'state': from_wire(result.State)}
                except DefinedExecutionError as error:
                    job['terminal'] = {'phase': 'canceled' if error.identifier == 'CommandCanceled' else 'failed',
                                       'error_code': error.identifier, 'state': state}
                except BaseException:
                    self.journal.append('uncertain', request_id=job['request_id'], execution_uuid=execution_id)
                    raise
                self.journal.append('terminal', request_id=job['request_id'], execution_uuid=execution_id,
                                    **job['terminal'])
            return {'id': execution_id, 'command': job['command'], **job['terminal']}
        return {'id': execution_id, 'command': job['command'], 'phase': 'braking' if state['run_phase'] == 'braking' else 'running',
                'error_code': '', 'state': state}

    def poll(self, execution_id):
        return self._sync(self._poll(execution_id))

    def observe_robot(self, event, sample):
        arguments = {'boot_id': self.ready['boot_id'], 'actor_id': self.username,
                     'sample_id': sample['id'], 'slot': sample['rotor_slot'], 'event': event}
        async def observe():
            async def invoke(request):
                await self.client.SyntheticRobotObservation.ObserveRobotAccess(
                    **{contract.base.camel(k): v for k, v in arguments.items()}, ObservationId=request,
                    metadata=[self.auth, self.lock_metadata])
            request_id, _ = await self._effect('ObserveRobotAccess', arguments, invoke)
            self.journal.append('completed', request_id=request_id)
        return self._sync(observe())

    async def _close(self):
        tasks = [job['task'] for job in self.jobs.values()]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.client is not None:
            await self.client.close()

    def close(self):
        try:
            if self.thread.is_alive():
                self._sync(self._close())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=self.rpc_timeout_s + 2)
            if self.thread.is_alive():
                raise RuntimeError('SiLA client loop did not stop')
            self.loop.close()
