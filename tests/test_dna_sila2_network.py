"""Opt-in real TLS/gRPC against a separate DNA server process; no ROS runtime."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cf01_sila2_client import wait_for_execution

ENABLED = importlib.util.find_spec('sila') is not None and os.getenv('SOLIDCRAFTBOT_SILA_NETWORK_TESTS') == '1'


@unittest.skipUnless(ENABLED, 'Requires pinned SiLA dependencies and SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1; skipped is not network evidence')
class DNANetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        from cf01_sila2_auth import credential
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-tls-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.directory = self.folder / 'server'
        self.credentials = self.folder / 'users.json'
        self.credentials.write_text(json.dumps({'format': 'solidcraftbot.dna-sila-users/1', 'users': [
            credential('operator', 'test-only-dna-operator-password', 'operator'),
            credential('observer', 'test-only-dna-observer-password', 'observer')]}))
        self.log = (self.folder / 'server.log').open('a')
        self.process = self.client = None
        self.run_id = 'SYN.DNA.NET.' + uuid.uuid4().hex[:8]

    async def asyncTearDown(self):
        if self.client is not None:
            await self.client.close()
            self.client = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait, 5)
        self.log.close()
        self.temp.cleanup()

    async def start(self, pause_after=None):
        ready = self.folder / ('ready-' + uuid.uuid4().hex + '.json')
        args = [sys.executable, str(ROOT / 'scripts/run_dna_sila2.py'), 'serve',
                '--directory', str(self.directory), '--credentials', str(self.credentials),
                '--tls-directory', str(self.directory / 'tls'), '--ready-file', str(ready)]
        if pause_after:
            args += ['--pause-after', pause_after]
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        deadline = time.monotonic() + 15
        while not ready.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.fail('DNA server did not start: ' + (self.folder / 'server.log').read_text())
            await asyncio.sleep(.03)
        self.ready = json.loads(ready.read_text())
        from sila.client import Client, ClientConfig
        self.client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=True,
            root_certificates=Path(self.ready['certificate']).read_bytes(), default_timeout=5000))
        await self.client.open()
        self.auth, self.token = await self.login('operator', 'test-only-dna-operator-password')
        return self.ready

    async def login(self, username, password):
        result = await self.client.AuthenticationService.Login(UserIdentification=username, Password=password,
            RequestedServer=self.ready['server_uuid'], RequestedFeatures=[])
        return await self.client.AuthorizationService.AccessToken.from_native(self.client, result.AccessToken), result.AccessToken

    async def lock(self, seconds=30):
        identifier = str(uuid.uuid4())
        await self.client.LockController.LockServer(LockIdentifier=identifier, Timeout=seconds, metadata=[self.auth])
        return await self.client.LockController.LockIdentifier.from_native(self.client, identifier)

    async def command(self, name, lease, request=None, **arguments):
        response = await getattr(self.client.DnaQuantificationWorkflow, name)(RequestIdentifier=request or str(uuid.uuid4()),
            RunIdentifier=self.run_id, metadata=[self.auth, lease], **arguments)
        if hasattr(response, 'get_responses'):
            response = await wait_for_execution(response, 10)
        return json.loads(response.StatusJson)

    async def report(self, auth=None):
        reports = json.loads(await self.client.DnaQuantificationWorkflow.Report.read(metadata=[auth or self.auth]))
        return reports['reports'][self.run_id]

    def event_count(self):
        connection = sqlite3.connect('file:' + self.ready['journal'] + '?mode=ro', uri=True)
        try:
            return connection.execute('SELECT COUNT(*) FROM events WHERE run_id=?', (self.run_id,)).fetchone()[0]
        finally:
            connection.close()

    async def run_execution(self, lease, initial='none', qubit=48, request=None):
        return await self.client.DnaQuantificationWorkflow.RunUntilDecision(RequestIdentifier=request or str(uuid.uuid4()),
            RunIdentifier=self.run_id, InitialDilution=initial, AfterRange='', NanodropConcentration=50.,
            QubitConcentration=float(qubit), QubitReportOriginal=False, metadata=[self.auth, lease])

    async def wait_pending(self, dilution=False):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            report = await self.report()
            if dilution and report['pending_dilution']:
                return report
            context = report['contexts'].get(next((key for key, value in report['contexts'].items()
                if value['local'].get('pending_measurement') or value['local'].get('pending_operation')), ''))
            if not dilution and context:
                return report
            await asyncio.sleep(.03)
        self.fail('No persisted pending intent observed')

    async def test_separate_process_identity_authentication_observer_and_simulation_boundary(self):
        from sila.client import SiLAError
        await self.start()
        self.assertNotEqual(self.process.pid, os.getpid())
        self.assertEqual(await self.client.SiLAService.ServerUUID.read(), self.ready['server_uuid'])
        self.assertTrue(await self.client.SimulationController.SimulationMode.read(metadata=[self.auth]))
        with self.assertRaises(SiLAError):
            await self.client.SimulationController.StartRealMode(metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await self.client.DnaQuantificationWorkflow.Status.read()
        observer, _ = await self.login('observer', 'test-only-dna-observer-password')
        observed = json.loads(await self.client.DnaQuantificationWorkflow.Status.read(metadata=[observer]))
        self.assertTrue(observed['simulation_only'])
        self.assertFalse(observed['hardware_available'])
        with self.assertRaises(SiLAError):
            await self.client.LockController.LockServer(LockIdentifier='observer', Timeout=30, metadata=[observer])
        self.assertFalse(await self.client.LockController.IsLocked.read(metadata=[self.auth]))

    async def test_exact_repeated_request_is_same_receipt_and_changed_arguments_never_add_events(self):
        from sila.client import SiLAError
        await self.start()
        lease = await self.lock()
        request = str(uuid.uuid4())
        first = await self.command('CreateRun', lease, request=request)
        events = self.event_count()
        again = await self.command('CreateRun', lease, request=request)
        self.assertEqual(again, first)
        self.assertEqual(self.event_count(), events)
        with self.assertRaises(SiLAError):
            await self.command('CancelRun', lease, request=request, Reason='Different command with reused identity')
        self.assertEqual(self.event_count(), events)
        self.assertEqual((await self.report())['bookings'], {})

    async def test_normal_tls_pair_uses_root_ledger_and_raw_artifacts(self):
        await self.start()
        lease = await self.lock()
        await self.command('CreateRun', lease)
        result = await wait_for_execution(await self.run_execution(lease), 15)
        self.assertEqual(json.loads(result.StatusJson)['root_status'], 'completed')
        report = await self.report()
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual({entry['actual_volume_ul'] for entry in report['bookings'].values()}, {1.5, 2})
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)
        self.assertEqual(len([checksum for context in report['contexts'].values() for checksum in context['local']['imports']]), 2)
        self.assertFalse(report['hardware_executed'])

    async def test_public_cli_scenario_repeats_high_qubit_with_f10_over_tls(self):
        await self.start()
        ready = self.folder / 'client-ready.json'
        ready.write_text(json.dumps(self.ready))
        login = self.folder / 'operator-login.json'
        login.write_text(json.dumps({'username': 'operator', 'password': 'test-only-dna-operator-password'}))
        login.chmod(0o600)
        output = self.folder / 'scenario.json'
        result = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT / 'scripts/run_dna_sila2.py'),
            'scenario', '--ready-file', str(ready), '--login-input', str(login), '--run-id', self.run_id,
            '--out', str(output), '--timeout', '20'], cwd=ROOT, capture_output=True, text=True, timeout=40,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(output.read_text())
        self.assertEqual(json.loads(result.stdout), evidence)
        self.assertTrue(evidence['network_executed'])
        self.assertFalse(evidence['ros_executed'])
        self.assertFalse(evidence['hardware_executed'])
        self.assertEqual([receipt['command'] for receipt in evidence['receipts']],
                         ['CreateRun', 'RunUntilDecision', 'ChooseDilution', 'RunUntilDecision'])
        self.assertEqual(evidence['first_report']['status'], 'awaiting_choice')
        self.assertTrue(evidence['report']['passed'])
        self.assertEqual(len(evidence['report']['attempts']), 2)
        self.assertEqual(len(evidence['report']['bookings']), 5)
        self.assertEqual(evidence['report']['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 34.5)
        self.assertNotIn('test-only-dna-operator-password', result.stdout)

    async def test_cancel_controller_interrupts_at_persisted_intent_without_cancelrun_or_release(self):
        from sila.client import SiLAError
        await self.start('measurement_intent')
        lease = await self.lock()
        await self.command('CreateRun', lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution.command_execution_uuid,
            metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 8)
        report = await self.report()
        self.assertEqual(report['status'], 'held')
        self.assertFalse(report['cancel_requested'] if 'cancel_requested' in report else
                         json.loads(await self.client.DnaQuantificationWorkflow.Status.read(metadata=[self.auth]))['runs'][0]['cancel_requested'])
        self.assertEqual(report['bookings'], before['bookings'])
        self.assertTrue(report['resources'])
        self.assertIsNone(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'])

    async def test_wall_time_lease_expiry_stops_next_effect_and_keeps_root_resources(self):
        from sila.client import SiLAError
        await self.start('measurement_intent')
        lease = await self.lock(seconds=1)
        await self.command('CreateRun', lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 8)
        report = await self.report()
        self.assertEqual(report['status'], 'held')
        self.assertEqual(report['bookings'], before['bookings'])
        self.assertTrue(report['resources'])
        self.assertFalse(await self.client.LockController.IsLocked.read(metadata=[self.auth]))

    async def test_logout_revokes_running_execution_before_another_effect(self):
        from sila.client import SiLAError
        await self.start('measurement_intent')
        lease = await self.lock()
        await self.command('CreateRun', lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        await self.client.AuthenticationService.Logout(AccessToken=self.token)
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 8)
        observer, _ = await self.login('observer', 'test-only-dna-observer-password')
        report = await self.report(observer)
        self.assertEqual(report['status'], 'held')
        self.assertEqual(report['bookings'], before['bookings'])
        self.assertTrue(report['resources'])

    async def test_restart_changes_boot_and_requires_resume_without_replaying_pending_dilution(self):
        from sila.client import SiLAError
        await self.start('dilution_intent')
        lease = await self.lock()
        await self.command('CreateRun', lease)
        await self.run_execution(lease, initial='1+9')
        before = await self.wait_pending(dilution=True)
        request = next(key for key, record in before['network']['commands'].items()
                       if record['command'] == 'RunUntilDecision')
        old = self.ready
        self.process.kill()
        await asyncio.to_thread(self.process.wait, 5)
        await self.client.close()
        self.client = None
        await self.start()
        self.assertEqual(self.ready['server_uuid'], old['server_uuid'])
        self.assertNotEqual(self.ready['boot_id'], old['boot_id'])
        lease = await self.lock()
        events = self.event_count()
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease, initial='1+9', request=request), 5)
        self.assertEqual(self.event_count(), events)
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease), 5)
        await self.command('ResumeRun', lease, Resume=True)
        report = await self.report()
        self.assertEqual(report['status'], 'held')
        self.assertEqual(report['pending_dilution'], before['pending_dilution'])
        self.assertEqual(report['bookings'], before['bookings'])
        self.assertTrue(report['resources'])
        events = self.event_count()
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease, initial='1+9', request=request), 5)
        self.assertEqual(self.event_count(), events)

    async def test_sigkill_measurement_then_explicit_performed_reconciliation_resumes_once(self):
        await self.start('measurement_intent')
        lease = await self.lock()
        await self.command('CreateRun', lease)
        await self.run_execution(lease)
        before = await self.wait_pending()
        context_id = next(key for key, value in before['contexts'].items() if value['local'].get('pending_measurement'))
        pending = before['contexts'][context_id]['local']['pending_measurement']
        self.process.kill()
        await asyncio.to_thread(self.process.wait, 5)
        await self.client.close()
        self.client = None
        await self.start()
        lease = await self.lock()
        await self.command('ResumeRun', lease, Resume=True)
        held = await self.report()
        self.assertEqual(held['bookings'], before['bookings'])
        observations = [{'vessel_id': identity, 'sample_id': vessel.get('sample_id'),
                         'location': vessel.get('home', vessel['location'])}
                        for identity, vessel in held['inventory']['vessels'].items()]
        document = {'observations': observations, 'workspace_clear': True, 'blank_still_valid': True,
                    'pending_resolution': {'intent_id': pending['intent_id'], 'outcome': 'performed',
                        'observed_sample_id': 'DNA01', 'volume_ul': 1.5, 'cleaned': True}}
        await self.command('ReconcileInventory', lease, ObservationJson=json.dumps(document))
        result = await wait_for_execution(await self.run_execution(lease), 15)
        self.assertEqual(json.loads(result.StatusJson)['root_status'], 'completed')
        report = await self.report()
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual(report['bookings'][pending['intent_id']]['actual_volume_ul'], 1.5)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)
        self.assertIn(pending['measurement_id'], report['contexts'][context_id]['local']['measurements'])

    async def test_wrong_trust_and_plaintext_never_connect(self):
        from sila import SiLATimeoutError
        from sila.client import Client, ClientConfig
        from sila.server import create_certificate
        from cf01_sila2_client import connect_station
        await self.start()
        events = self.event_count()
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            await connect_station({**self.ready, 'server_uuid': str(uuid.uuid4())},
                                  'operator', 'test-only-dna-operator-password')
        self.assertEqual(self.event_count(), events)
        wrong = create_certificate(str(uuid.uuid4()), ip_addresses=['127.0.0.1'])
        for tls, trust in [(True, wrong.pem_certificate), (False, None)]:
            client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=tls,
                root_certificates=trust, default_timeout=500))
            try:
                with self.assertRaises(SiLATimeoutError):
                    await client.open(timeout=500)
            finally:
                await client.close()


if __name__ == '__main__':
    unittest.main()
