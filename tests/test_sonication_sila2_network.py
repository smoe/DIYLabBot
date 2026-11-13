"""Opt-in separate-process loopback TLS/gRPC for S09 software fixtures only."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
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


@unittest.skipUnless(importlib.util.find_spec('sila') is not None,
                     'Requires pinned SiLA SDK for the server module; this projection test opens no sockets')
class WireReportProjectionTests(unittest.TestCase):
    def test_multimegabyte_history_keeps_chain_metadata_and_all_current_root_values(self):
        from sonication_sila2_server import encoded, wire_report
        trace = [{'sequence': index, 'kind': 'fixture_transition', 'sha256': str(index) * 64,
                  'previous_sha256': None if index == 1 else str(index - 1) * 64,
                  'time_unix_s': 100. + index,
                  'state': {'large_historical_snapshot': 'X' * 2_200_000},
                  'payload': {'historical_payload': 'explicitly in the private journal'}}
                 for index in (1, 2, 3)]
        current = {'status': 'working', 'inventory': {'materials': {'input': {'quantity_ul': 295}}},
                   'bookings': {'qc': {'quantity_ul': 5}}, 'remaining': {'input': {'value': 295, 'unit': 'uL'}},
                   'sonication': {'intents': {'effect': {'quantity_before': {'value': 300, 'unit': 'uL'}}}},
                   'hardware_executed': False, 'network_executed': False, 'execution_ready': False,
                   'reference_success': False, 'source_files_sha256': {'model/fixture.json': 'a' * 64},
                   'transport_receipts': {'sila_loopback_executed': True}, 'trace': trace}
        source = {'server_uuid': 'server', 'boot_id': 'boot', 'reports': {'run': current}}
        self.assertGreater(len(encoded(source)), 6_000_000)
        projected = wire_report(source)
        self.assertLess(len(encoded(projected)), 2 ** 21)
        self.assertEqual(projected['server_uuid'], source['server_uuid'])
        observed = projected['reports']['run']
        for key, value in current.items():
            if key != 'trace':
                self.assertEqual(observed[key], value, key)
        fields = ('sequence', 'kind', 'sha256', 'previous_sha256', 'time_unix_s')
        self.assertEqual(observed['trace'], [{key: event[key] for key in fields} for event in trace])
        self.assertEqual(observed['wire_projection'], {
            'format': 'solidcraftbot.s09-sila2-wire-report/1', 'trace': 'metadata_only',
            'full_journal': 'private root journal and evidence export'})
        self.assertEqual(len(current['trace'][0]['state']['large_historical_snapshot']), 2_200_000)
        self.assertNotIn('wire_projection', current)
        observed['inventory']['materials']['input']['quantity_ul'] = 0
        self.assertEqual(current['inventory']['materials']['input']['quantity_ul'], 295)


@unittest.skipUnless(ENABLED, 'Requires pinned SiLA dependencies and SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1; skipped is not network evidence')
class SonicationNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        from cf01_sila2_auth import credential
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='s09-tls-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.directory = self.folder / 'server'
        self.credentials = self.folder / 'users.json'
        users = await asyncio.to_thread(lambda: [
            credential('operator', 'test-only-s09-operator-password', 'operator'),
            credential('second', 'test-only-s09-second-password', 'operator'),
            credential('observer', 'test-only-s09-observer-password', 'observer')])
        self.credentials.write_text(json.dumps({'format': 'solidcraftbot.sonication-sila-users/1', 'users': users}))
        self.credentials.chmod(0o600)
        self.log_path = self.folder / 'server.log'
        self.log = self.log_path.open('a')
        self.process = self.client = None
        self.run_id = 'Fixture.S09.NET.' + uuid.uuid4().hex[:8]

    async def asyncTearDown(self):
        if self.client is not None:
            await self.client.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait, 5)
        self.log.close()
        diagnostics = ROOT / 'exports/verification/s09-sila2/network/server-logs'
        diagnostics.mkdir(parents=True, exist_ok=True)
        destination = diagnostics / (self._testMethodName + '-' + str(time.time_ns()) + '.log')
        destination.write_bytes(self.log_path.read_bytes())
        self.temp.cleanup()

    async def start(self, pause_after=None):
        ready = self.folder / ('ready-' + uuid.uuid4().hex + '.json')
        args = [sys.executable, str(ROOT / 'scripts/run_sonication_sila2.py'), 'serve',
                '--directory', str(self.directory), '--credentials', str(self.credentials),
                '--tls-directory', str(self.directory / 'tls'), '--ready-file', str(ready)]
        if pause_after:
            args += ['--pause-after', pause_after]
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        deadline = time.monotonic() + 15
        while True:
            if ready.exists():
                try:
                    self.ready = json.loads(ready.read_text())
                    break
                except json.JSONDecodeError:
                    pass  # The exclusive ready file can be observed before its first flush.
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.fail('S09 server did not start: ' + self.log_path.read_text())
            await asyncio.sleep(.03)
        from sila.client import Client, ClientConfig
        self.client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=True,
            root_certificates=Path(self.ready['certificate']).read_bytes(), default_timeout=20000))
        await self.client.open()
        self.auth, self.token = await self.login('operator', 'test-only-s09-operator-password')
        return self.ready

    async def login(self, username, password):
        result = await self.client.AuthenticationService.Login(UserIdentification=username, Password=password,
            RequestedServer=self.ready['server_uuid'], RequestedFeatures=[])
        return await self.client.AuthorizationService.AccessToken.from_native(self.client, result.AccessToken), result.AccessToken

    async def lock(self, seconds=30, auth=None):
        self.lock_identifier = str(uuid.uuid4())
        await self.client.LockController.LockServer(LockIdentifier=self.lock_identifier, Timeout=seconds,
            metadata=[auth or self.auth])
        return await self.client.LockController.LockIdentifier.from_native(self.client, self.lock_identifier)

    async def command(self, name, lease, request=None, auth=None, **arguments):
        response = await getattr(self.client.CutRunInputSonicationWorkflow, name)(
            RequestIdentifier=request or str(uuid.uuid4()), RunIdentifier=self.run_id,
            metadata=[auth or self.auth, lease], **arguments)
        if hasattr(response, 'get_responses'):
            response = await wait_for_execution(response, 15)
        return json.loads(response.StatusJson)

    async def create(self, lease, scenario='normal', request=None):
        return await self.command('CreateRun', lease, request=request, ScenarioIdentifier=scenario)

    async def run_execution(self, lease, request=None):
        return await self.client.CutRunInputSonicationWorkflow.RunUntilDecision(
            RequestIdentifier=request or str(uuid.uuid4()), RunIdentifier=self.run_id,
            metadata=[self.auth, lease])

    async def report(self, auth=None):
        reports = json.loads(await self.client.CutRunInputSonicationWorkflow.Report.read(metadata=[auth or self.auth]))
        return reports['reports'][self.run_id]

    async def status(self, auth=None):
        return json.loads(await self.client.CutRunInputSonicationWorkflow.Status.read(metadata=[auth or self.auth]))

    def event_count(self):
        connection = sqlite3.connect('file:' + self.ready['journal'] + '?mode=ro', uri=True)
        try:
            return connection.execute('SELECT COUNT(*) FROM events WHERE run_id=?', (self.run_id,)).fetchone()[0]
        finally:
            connection.close()

    async def wait_pending(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            report = await self.report()
            if report['pending_operation'] is not None and report['sonication']['pending_intents']:
                return report
            await asyncio.sleep(.03)
        self.fail('No persisted S09 sonication intent observed: ' + repr({key: report[key]
            for key in ('status', 'recovery_required', 'pending_operation', 'sonication')}))

    async def wait_material_pending(self, suffix):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            report = await self.report()
            pending = report['pending_operation']
            if (pending is not None and pending['intent_id'].endswith(suffix)
                    and report['bookings'][pending['intent_id']]['outcome'] == 'intent'):
                return report
            await asyncio.sleep(.03)
        self.fail('No persisted material intent observed: ' + repr({key: report[key]
            for key in ('status', 'recovery_required', 'pending_operation')}))

    async def kill_and_restart(self):
        old = self.ready
        self.process.kill()
        await asyncio.to_thread(self.process.wait, 5)
        self.assertEqual(self.process.returncode, -signal.SIGKILL)
        await self.client.close()
        self.client = None
        await self.start()
        self.assertEqual(self.ready['server_uuid'], old['server_uuid'])
        self.assertNotEqual(self.ready['boot_id'], old['boot_id'])
        return await self.lock()

    def assert_normal(self, report):
        self.assertEqual(len(report['sonication']['intents']), 1)
        identity, intent = next(iter(report['sonication']['intents'].items()))
        self.assertEqual(report['bookings'][identity]['outcome'], 'performed')
        self.assertEqual(intent['quantity_before'], {'value': 300, 'unit': 'uL'})
        physical = intent['physical_receipt']['observation']
        self.assertEqual(physical['actual_output_quantity'], {'value': 300, 'unit': 'uL'})
        self.assertEqual(len(physical['artifact_sha256']), 64)
        self.assertEqual(len(intent['size_records']), 1)
        size = next(iter(intent['size_records'].values()))
        self.assertEqual(len(size['observation']['artifact_sha256']), 64)
        self.assertTrue(size['fixture_range_conformant'])
        self.assertFalse(size['biological_acceptance'])
        self.assertEqual(report['remaining'][intent['material_after_id']]['value'], 295)
        self.assertEqual(report['sop']['stages'][intent['stage_run_id']]['status'], 'completed')
        self.assertNotIn(report['status'], {'completed', 'cancelled'})
        self.assertTrue(report['resources'])
        self.assertEqual(report['inventory']['vessels'][intent['vessel_id']]['location'], intent['original_rack_location'])
        self.assertFalse(report['hardware_executed'])
        self.assertFalse(report['network_executed'])  # Existing domain flag remains separate from transport.
        self.assertTrue(report['transport_receipts']['sila_loopback_executed'])
        self.assertFalse(report['execution_ready'])
        self.assertFalse(report['reference_success'])
        qc = [booking for booking in report['bookings'].values()
              if booking['request']['kind'] == 'withdrawal']
        self.assertEqual(len(qc), 1)
        self.assertEqual(qc[0]['actual_inputs'][0]['quantity'], {'value': 5, 'unit': 'uL'})
        return intent

    @staticmethod
    def observation_document(report, *, outcome=None, return_to_origin=False, finish=False):
        """Client-selected synthetic declarations; no root access or mutations."""
        inventory = report['inventory']
        intents = report['sonication']['intents']
        intent = next(iter(intents.values()))
        observations = [{'vessel_id': identity,
            'material_ids': [key for key, material in inventory['materials'].items()
                             if material['vessel_id'] == identity],
            'location': copy.deepcopy(vessel['location'])}
            for identity, vessel in inventory['vessels'].items()]
        resolution = None
        if outcome is not None:
            resolution = {'outcome': outcome}
            if outcome == 'performed':
                resolution.update(actual_output_quantity={'value': 300, 'unit': 'uL'},
                                  observed_vessel_id=intent['vessel_id'])
                for observation in observations:
                    if observation['vessel_id'] == intent['vessel_id']:
                        observation['material_ids'] = [intent['material_after_id']]
        if return_to_origin:
            for observation in observations:
                if observation['vessel_id'] == intent['vessel_id']:
                    observation['location'] = copy.deepcopy(intent['original_rack_location'])
        dispositions = []
        if finish:
            dispositions = [{'material_id': identity, 'disposition': 'retained',
                             'reason': 'Explicit client fixture retention declaration'}
                for identity, material in inventory['materials'].items()
                if material['disposition'] != 'consumed' and material['disposition_confirmation'] is None]
        return {'format': 'solidcraftbot.s09-fixture-reconciliation/1',
            'evidence_ref': 'decision_evidence', 'reason': 'Explicit client fixture declaration, no scan or hardware',
            'observations': observations, 'workspace_clear': True,
            'clock_gap': {'minimum_s': 25, 'maximum_s': 25} if report['clock']['gap_required'] else None,
            'sonication': resolution, 'dispositions': dispositions}

    async def test_identity_authentication_observer_and_simulation_boundary(self):
        from sila.client import SiLAError
        await self.start()
        self.assertNotEqual(self.process.pid, os.getpid())
        self.assertEqual(await self.client.SiLAService.ServerUUID.read(), self.ready['server_uuid'])
        self.assertTrue(await self.client.SimulationController.SimulationMode.read(metadata=[self.auth]))
        with self.assertRaises(SiLAError):
            await self.client.SimulationController.StartRealMode(metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await self.client.CutRunInputSonicationWorkflow.Status.read()
        observer, _ = await self.login('observer', 'test-only-s09-observer-password')
        observed = await self.status(observer)
        self.assertTrue(observed['simulation_only'])
        self.assertFalse(observed['hardware_available'])
        with self.assertRaises(SiLAError):
            await self.client.LockController.LockServer(LockIdentifier='observer', Timeout=30, metadata=[observer])
        self.assertFalse(await self.client.LockController.IsLocked.read(metadata=[self.auth]))
        lease = await self.lock()
        with self.assertRaises(SiLAError):
            await self.command('CreateRun', lease, auth=observer, ScenarioIdentifier='normal')
        self.assertEqual(self.event_count(), 0)

    async def test_repeated_request_dedupes_and_command_or_principal_collision_is_rejected(self):
        from sila.client import SiLAError
        await self.start()
        lease = await self.lock()
        request = str(uuid.uuid4())
        first = await self.create(lease, request=request)
        events = self.event_count()
        self.assertEqual(await self.create(lease, request=request), first)
        self.assertEqual(self.event_count(), events)
        with self.assertRaises(SiLAError):
            await self.create(lease, request=request, scenario='restart')
        with self.assertRaises(SiLAError):
            await self.command('CancelRun', lease, request=request, Reason='Request collision')
        self.assertEqual(self.event_count(), events)
        await self.client.LockController.UnlockServer(LockIdentifier=self.lock_identifier, metadata=[self.auth])
        second, _ = await self.login('second', 'test-only-s09-second-password')
        second_lease = await self.lock(auth=second)
        with self.assertRaises(SiLAError):
            await self.command('CreateRun', second_lease, request=request, auth=second, ScenarioIdentifier='normal')
        self.assertEqual(self.event_count(), events)

    async def test_normal_tls_uses_one_root_ledger_and_keeps_overall_cutrun_open(self):
        await self.start()
        lease = await self.lock()
        await self.create(lease)
        response = await wait_for_execution(await self.run_execution(lease), 15)
        self.assertEqual(json.loads(response.StatusJson)['outcome'], 'completed')
        self.assert_normal(await self.report())

    async def test_public_cli_scenario_and_invalid_output_preflight(self):
        await self.start()
        ready = self.folder / 'client-ready.json'
        ready.write_text(json.dumps(self.ready))
        login = self.folder / 'operator-login.json'
        login.write_text(json.dumps({'username': 'operator', 'password': 'test-only-s09-operator-password'}))
        login.chmod(0o600)
        output = self.folder / 'scenario.json'
        result = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT / 'scripts/run_sonication_sila2.py'),
            '--language', 'en', 'scenario', '--ready-file', str(ready), '--login-input', str(login),
            '--run-id', self.run_id, '--out', str(output), '--timeout', '20'], cwd=ROOT,
            capture_output=True, text=True, timeout=40, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(output.read_text())
        self.assertEqual(json.loads(result.stdout), evidence)
        self.assertTrue(evidence['network_executed'])
        self.assertFalse(evidence['ros_executed'])
        self.assertFalse(evidence['hardware_executed'])
        self.assertEqual([receipt['command'] for receipt in evidence['receipts']], ['CreateRun', 'RunUntilDecision'])
        self.assert_normal(evidence['report'])
        self.assertNotIn('test-only-s09-operator-password', result.stdout)
        before = self.event_count()
        # Existing evidence is rejected before any second CreateRun dispatch.
        again = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT / 'scripts/run_sonication_sila2.py'),
            'scenario', '--ready-file', str(ready), '--login-input', str(login), '--run-id', self.run_id,
            '--out', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(again.returncode, 1)
        self.assertEqual(self.event_count(), before)
        self.assertEqual(json.loads(output.read_text()), evidence)

    async def test_timeout_retry_dedupes_without_repeating_the_pending_effect(self):
        from cf01_sila2_client import UncertainExecution, connect_station
        from sila.client import SiLAError
        await self.start('sonication_intent')
        lease = await self.lock()
        await self.create(lease)
        request = str(uuid.uuid4())
        execution = await self.run_execution(lease, request=request)
        before = await self.wait_pending()
        with self.assertRaises(UncertainExecution):
            await wait_for_execution(execution, .05)
        # A dropped client never cancels or recreates the durable server worker.
        original_execution_uuid = execution.command_execution_uuid
        await self.client.close()
        self.client, self.auth = await connect_station(self.ready, 'operator', 'test-only-s09-operator-password')
        lease = await self.client.LockController.LockIdentifier.from_native(self.client, self.lock_identifier)
        retry = await self.run_execution(lease, request=request)
        events = self.event_count()
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=original_execution_uuid,
            metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await wait_for_execution(retry, 8)
        after = await self.report()
        self.assertEqual(after['pending_operation'], before['pending_operation'])
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertTrue(after['resources'])
        self.assertEqual(len(after['sonication']['intents']), 1)
        self.assertGreaterEqual(self.event_count(), events)

    async def test_cancel_controller_stops_at_boundary_without_cancelrun_or_release(self):
        from sila.client import SiLAError
        await self.start('sonication_intent')
        lease = await self.lock()
        await self.create(lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution.command_execution_uuid,
            metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 8)
        report = await self.report()
        self.assertEqual(report['bookings'], before['bookings'])
        self.assertEqual(report['pending_operation'], before['pending_operation'])
        self.assertTrue(report['resources'])
        self.assertNotEqual(report['status'], 'cancelled')

    async def test_lease_expiry_stops_next_effect_without_releasing_root(self):
        from sila.client import SiLAError
        await self.start('sonication_intent')
        # Full source/fixture validation must reach its persisted intent before
        # the finite wall-time lease expires at the private test boundary.
        lease = await self.lock(seconds=15)
        await self.create(lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 25)
        after = await self.report()
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertTrue(after['resources'])
        self.assertFalse(await self.client.LockController.IsLocked.read(metadata=[self.auth]))

    async def test_logout_revokes_execution_before_any_further_effect(self):
        from sila.client import SiLAError
        await self.start('sonication_intent')
        lease = await self.lock()
        await self.create(lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        await self.client.AuthenticationService.Logout(AccessToken=self.token)
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 8)
        observer, _ = await self.login('observer', 'test-only-s09-observer-password')
        after = await self.report(observer)
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertTrue(after['resources'])

    async def test_sigkill_requires_resume_and_explicit_wire_reconciliation_without_effect_replay(self):
        from sila.client import SiLAError
        await self.start('sonication_intent')
        lease = await self.lock()
        await self.create(lease, scenario='restart')
        request = str(uuid.uuid4())
        await self.run_execution(lease, request=request)
        before = await self.wait_pending()
        intent_id = before['pending_operation']['intent_id']
        lease = await self.kill_and_restart()
        events = self.event_count()
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease), 5)
        self.assertEqual(self.event_count(), events)
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease, request=request), 5)
        self.assertEqual(self.event_count(), events)
        await self.command('ResumeRun', lease, Resume=True)
        held = await self.report()
        self.assertEqual(held['bookings'], before['bookings'])
        self.assertTrue(held['resources'])
        await self.command('ReconcileRun', lease,
            ObservationJson=json.dumps(self.observation_document(held, outcome='unknown')))
        unknown = await self.report()
        self.assertEqual(unknown['bookings'][intent_id]['outcome'], 'unknown')
        self.assertTrue(unknown['resources'])
        await self.command('ReconcileRun', lease,
            ObservationJson=json.dumps(self.observation_document(unknown, outcome='performed')))
        await wait_for_execution(await self.run_execution(lease), 15)
        finished = await self.report()
        self.assert_normal(finished)
        self.assertEqual(finished['bookings'][intent_id]['outcome'], 'performed')
        self.assertEqual(len(finished['sonication']['intents']), 1)

    async def sigkill_material_reconciliation(self, boundary, suffix):
        from sila.client import SiLAError
        from sonication_sila2_runtime import reconciliation_document
        await self.start(boundary)
        lease = await self.lock()
        await self.create(lease, scenario='restart')
        request = str(uuid.uuid4())
        await self.run_execution(lease, request=request)
        before = await self.wait_material_pending(suffix)
        intent_id = before['pending_operation']['intent_id']
        self.assertEqual(len([identity for identity in before['bookings'] if identity.endswith(suffix)]), 1)
        lease = await self.kill_and_restart()
        events = self.event_count()
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease), 5)
        self.assertEqual(self.event_count(), events)
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease, request=request), 5)
        self.assertEqual(self.event_count(), events)
        await self.command('ResumeRun', lease, Resume=True)
        held = await self.report()
        self.assertEqual(held['bookings'], before['bookings'])
        self.assertTrue(held['resources'])
        document = reconciliation_document(held, outcome='performed')
        self.assertIsNone(document['sonication'])
        self.assertEqual(document['material']['intent_id'], intent_id)
        self.assertEqual(document['material']['outcome'], 'performed')
        expected_input = 10_000 if suffix == '.InputPreparation' else 5
        expected_unit = 'cells' if suffix == '.InputPreparation' else 'uL'
        self.assertEqual(document['material']['actual_inputs'][0]['quantity'],
                         {'value': expected_input, 'unit': expected_unit})
        self.assertEqual(document['material']['actual_outputs'], [] if suffix == '.SizeWithdrawal' else [
            {'material_id': before['bookings'][intent_id]['request']['outputs'][0]['material_id'],
             'quantity': {'value': 300, 'unit': 'uL'}}])
        await self.command('ReconcileRun', lease, ObservationJson=json.dumps(document))
        resolved = await self.report()
        self.assertEqual(resolved['bookings'][intent_id]['outcome'], 'performed')
        self.assertIsNone(resolved['pending_operation'])
        await wait_for_execution(await self.run_execution(lease), 15)
        finished = await self.report()
        self.assert_normal(finished)
        self.assertEqual(finished['status'], 'working')
        self.assertEqual(len(finished['bookings']), 3)
        self.assertEqual(len([identity for identity in finished['bookings'] if identity.endswith(suffix)]), 1)
        self.assertEqual(finished['bookings'][intent_id]['outcome'], 'performed')
        events = self.event_count()
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease, request=request), 5)
        self.assertEqual(self.event_count(), events)

    async def test_sigkill_input_preparation_intent_is_reconciled_over_wire_without_replaying_cells(self):
        await self.sigkill_material_reconciliation('input_preparation_intent', '.InputPreparation')

    async def test_sigkill_qc_withdrawal_intent_is_reconciled_over_wire_without_second_qc_consumption(self):
        await self.sigkill_material_reconciliation('qc_withdrawal_intent', '.SizeWithdrawal')

    async def test_cancel_unknown_keeps_holds_until_effect_return_and_complete_dispositions(self):
        from sila.client import SiLAError
        await self.start('sonication_intent')
        lease = await self.lock()
        await self.create(lease, scenario='cancel')
        execution = await self.run_execution(lease)
        await self.wait_pending()
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution.command_execution_uuid,
            metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await wait_for_execution(execution, 8)
        await self.command('CancelRun', lease, Reason='Explicit synthetic cancellation during an unresolved effect')
        cancelled = await self.report()
        await self.command('ReconcileRun', lease,
            ObservationJson=json.dumps(self.observation_document(cancelled, outcome='unknown')))
        unknown = await self.report()
        self.assertTrue(unknown['resources'])
        premature = self.observation_document(unknown, outcome='unknown', return_to_origin=True, finish=True)
        with self.assertRaises(SiLAError):
            await self.command('FinishCancel', lease, ObservationJson=json.dumps(premature))
        self.assertTrue((await self.report())['resources'])
        await self.command('ReconcileRun', lease,
            ObservationJson=json.dumps(self.observation_document(await self.report(), outcome='not_performed')))
        resolved = await self.report()
        missing = self.observation_document(resolved, return_to_origin=True, finish=True)
        missing['dispositions'] = []
        with self.assertRaises(SiLAError):
            await self.command('FinishCancel', lease, ObservationJson=json.dumps(missing))
        self.assertTrue((await self.report())['resources'])
        at_device = self.observation_document(await self.report(), finish=True)
        with self.assertRaises(SiLAError):
            await self.command('FinishCancel', lease, ObservationJson=json.dumps(at_device))
        self.assertTrue((await self.report())['resources'])
        final = self.observation_document(await self.report(), return_to_origin=True, finish=True)
        await self.command('FinishCancel', lease, ObservationJson=json.dumps(final))
        report = await self.report()
        self.assertEqual(report['status'], 'cancelled')
        self.assertFalse(report['resources'])
        self.assertEqual(len(report['sonication']['intents']), 1)

    async def test_wrong_certificate_uuid_and_plaintext_cannot_write(self):
        from sila import SiLATimeoutError
        from sila.client import Client, ClientConfig
        from sila.server import create_certificate
        from cf01_sila2_client import connect_station
        await self.start()
        events = self.event_count()
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            await connect_station({**self.ready, 'server_uuid': str(uuid.uuid4())},
                                  'operator', 'test-only-s09-operator-password')
        wrong = create_certificate(str(uuid.uuid4()), ip_addresses=['127.0.0.1'])
        for tls, trust in ((True, wrong.pem_certificate), (False, None)):
            client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=tls,
                root_certificates=trust, default_timeout=500))
            try:
                with self.assertRaises(SiLATimeoutError):
                    await client.open(timeout=500)
            finally:
                await client.close()
        self.assertEqual(self.event_count(), events)


if __name__ == '__main__':
    unittest.main()
