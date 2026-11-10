"""Actual CLI processes and forced restart, separate from in-process mocks."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cf01_sila2_client import wait_for_execution
ENABLED = importlib.util.find_spec('sila') is not None and os.getenv('SOLIDCRAFTBOT_SILA_NETWORK_TESTS') == '1'


@unittest.skipUnless(ENABLED, 'Install SiLA dependencies and set SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1')
class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = ROOT / 'exports/generated/cf01-sila2/process-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.directory.name)
        self.process = self.client = None
        self.logs = []
        self.private('input.json', [{'username': 'operator', 'password': 'process-test-password', 'role': 'operator'}])
        result = await self.cli('init', '--credentials-input', self.root / 'input.json',
                                '--credentials', self.root / 'users.json', '--store', self.root / 'station.sqlite3')
        self.assertTrue(json.loads(result)['initialized'])
        await self.start()

    def private(self, name, value):
        path = self.root / name
        path.touch(mode=0o600)
        path.write_text(json.dumps(value))
        return path

    async def cli(self, *arguments, success=True, timeout_s=30):
        process = await asyncio.create_subprocess_exec(sys.executable, 'scripts/run_cf01_sila2.py',
            *map(str, arguments), cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if success:
            self.assertEqual(process.returncode, 0, stderr.decode())
        else:
            self.assertNotEqual(process.returncode, 0)
        return stdout.decode()

    async def start(self):
        from sila.client import Client, ClientConfig
        ready_path = self.root / ('ready-' + str(uuid.uuid4()) + '.json')
        log = (self.root / ('server-' + str(uuid.uuid4()) + '.log')).open('w')
        self.logs.append(log)
        self.process = await asyncio.create_subprocess_exec(sys.executable, 'scripts/run_cf01_sila2.py', 'serve',
            '--credentials', str(self.root / 'users.json'), '--store', str(self.root / 'station.sqlite3'),
            '--tls-directory', str(self.root / 'tls'), '--ready-file', str(ready_path),
            cwd=ROOT, stdout=log, stderr=log)
        deadline = time.monotonic() + 15
        while not ready_path.is_file():
            if self.process.returncode is not None or time.monotonic() >= deadline:
                self.fail('Server did not become ready; see ' + str(log.name))
            await asyncio.sleep(.05)
        self.ready = json.loads(ready_path.read_text())
        self.ready_path = ready_path
        self.client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=True,
                             root_certificates=Path(self.ready['certificate']).read_bytes(), default_timeout=5000))
        await self.client.open()
        login = await self.client.AuthenticationService.Login(UserIdentification='operator', Password='process-test-password',
                         RequestedServer=self.ready['server_uuid'], RequestedFeatures=[])
        self.auth = await self.client.AuthorizationService.AccessToken.from_native(self.client, login.AccessToken)
        self.empty_lock = await self.client.LockController.LockIdentifier.from_native(self.client, '')

    async def stop(self, hard=False):
        if self.client is not None:
            await self.client.close()
            self.client = None
        if self.process is not None and self.process.returncode is None:
            self.process.kill() if hard else self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 15)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
                raise

    async def asyncTearDown(self):
        await self.stop()
        for log in self.logs:
            log.close()
        self.directory.cleanup()

    async def command(self, name, lock, **arguments):
        intent = await self.client.CentrifugeControl.RequestIdentifier.from_native(self.client, str(uuid.uuid4()))
        result = await getattr(self.client.CentrifugeControl, name)(metadata=[self.auth, lock, intent], **arguments)
        return await wait_for_execution(result, 5) if hasattr(result, 'get_responses') else result

    async def test_hard_restart_preserves_identity_and_pending_job_without_replay(self):
        from sila.client import SiLAError
        from sila.client.command_execution import CommandExecution
        import centrifuge_model
        lock_id = str(uuid.uuid4())
        await self.client.LockController.LockServer(LockIdentifier=lock_id, Timeout=60, metadata=[self.auth])
        lock = await self.client.LockController.LockIdentifier.from_native(self.client, lock_id)
        capacity = centrifuge_model.load()['rotor']['slots']
        for slot in range(1, capacity + 1):
            await self.command('CloseLid', lock)
            await self.command('IndexRotor', lock, Slot=slot)
            await self.command('OpenLid', lock)
            await self.command('ConfirmSeated', lock, MassG=2., SeatedConfirmed=True, CapClosedConfirmed=True)
        await self.command('CloseLid', lock)
        request = str(uuid.uuid4())
        intent = await self.client.CentrifugeControl.RequestIdentifier.from_native(self.client, request)
        execution = await self.client.CentrifugeControl.RunCentrifuge(RcfXG=100., DurationS=30.,
                          metadata=[self.auth, lock, intent])
        state = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, lock])).State
        self.assertFalse(state.StandstillConfirmed)
        old_ready, old_execution = self.ready, execution.command_execution_uuid
        old_certificate = Path(self.ready['certificate']).read_bytes()
        await self.stop(hard=True)
        await self.start()
        self.assertEqual(self.ready['server_uuid'], old_ready['server_uuid'])
        self.assertNotEqual(self.ready['boot_id'], old_ready['boot_id'])
        self.assertEqual(Path(self.ready['certificate']).read_bytes(), old_certificate)
        state = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, self.empty_lock])).State
        self.assertTrue(state.RecoveryRequired)
        self.assertNotEqual(state.RunPhase, 'running')
        stale = CommandExecution(self.client.CentrifugeControl.RunCentrifuge, old_execution)
        with self.assertRaises(SiLAError):
            await stale.get_responses(timeout=1000)
        await self.client.LockController.LockServer(LockIdentifier='new-lease', Timeout=60, metadata=[self.auth])
        fresh_lock = await self.client.LockController.LockIdentifier.from_native(self.client, 'new-lease')
        with self.assertRaises(SiLAError):
            await self.command('ConfirmSeated', fresh_lock, MassG=2., SeatedConfirmed=True, CapClosedConfirmed=True)
        await self.stop()
        inspected = json.loads(await self.cli('inspect', '--store', self.root / 'station.sqlite3'))
        self.assertTrue(inspected['needs_reconciliation'])
        self.assertEqual([entry['request_id'] for entry in inspected['pending']], [request])
        observation = {'evidence': 'synthetic_person_confirmation', 'actor_id': 'reviewer',
            'server_uuid': inspected['server_uuid'], 'expected_boot_id': inspected['boot_id'],
            'acknowledged_uncertain_request_ids': [request],
            **{key: True for key in ('standstill_confirmed', 'parking_brake_held', 'robot_clear', 'pusher_parked', 'lid_closed_locked')},
            'slots': [{'slot': slot, 'present': True, 'seated': True, 'cap_closed': True, 'mass_g': 2.} for slot in range(1, capacity + 1)]}
        observation_path = self.private('observation.json', observation)
        await self.cli('reconcile', '--store', self.root / 'station.sqlite3', '--observation', observation_path)
        await self.start()
        recovered = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, self.empty_lock])).State
        self.assertFalse(recovered.RecoveryRequired)
        self.assertEqual(recovered.RunPhase, 'idle')
        self.assertTrue(all(value.Present for value in recovered.RotorSlots))

    async def test_cli_batch_and_live_store_fencing(self):
        await self.cli('inspect', '--store', self.root / 'station.sqlite3', success=False)
        await self.cli('reconcile', '--store', self.root / 'station.sqlite3',
                       '--observation', self.private('invalid-observation.json', {}), success=False)
        login = self.private('login.json', {'username': 'operator', 'password': 'process-test-password'})
        result = json.loads(await self.cli('batch', '--ready-file', self.ready_path, '--login-input', login,
            '--journal', self.root / 'batch.jsonl', '--out', self.root / 'report.json', timeout_s=90))
        self.assertTrue(result['passed'])
        self.assertTrue(result['network_executed'])
        self.assertTrue(result['order_restored'])
