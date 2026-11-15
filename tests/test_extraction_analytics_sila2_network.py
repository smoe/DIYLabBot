"""Opt-in, separate-process TLS/gRPC proof for synthetic extraction analytics."""
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
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
class ExtractionAnalyticsNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        from cf01_sila2_auth import credential
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='extraction-analytics-tls-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.directory = self.folder / 'server'
        self.credentials = self.folder / 'users.json'
        users = await asyncio.to_thread(lambda: [
            credential('operator', 'test-only-extraction-operator-password', 'operator'),
            credential('second', 'test-only-extraction-second-password', 'operator'),
            credential('observer', 'test-only-extraction-observer-password', 'observer')])
        self.credentials.write_text(json.dumps({'format': 'solidcraftbot.dna-sila-users/1', 'users': users}))
        self.credentials.chmod(0o600)
        self.log_path = self.folder / 'server.log'
        self.log = self.log_path.open('a')
        self.process = self.client = None
        self.run_id = 'SYN.Extraction.NET.' + uuid.uuid4().hex[:8]

    async def asyncTearDown(self):
        if self.client is not None:
            await self.client.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait, 5)
        self.log.close()
        destination = ROOT / 'exports/extraction-sila2/network/server-logs'
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.log_path, destination / (self._testMethodName + '-' + str(time.time_ns()) + '.log'))
        self.temp.cleanup()

    async def start(self, pause_after=None):
        ready = self.folder / ('ready-' + uuid.uuid4().hex + '.json')
        args = [sys.executable, str(ROOT / 'scripts/run_dna_sila2.py'), 'serve',
            '--directory', str(self.directory), '--credentials', str(self.credentials),
            '--tls-directory', str(self.directory / 'tls'), '--ready-file', str(ready)]
        if pause_after:
            args += ['--extraction-pause-after', pause_after]
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        deadline = time.monotonic() + 25
        while True:
            if ready.exists():
                try:
                    self.ready = json.loads(ready.read_text())
                    break
                except json.JSONDecodeError:
                    pass
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.fail('DNA server did not start: ' + self.log_path.read_text())
            await asyncio.sleep(.03)
        from sila.client import Client, ClientConfig
        self.client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=True,
            root_certificates=Path(self.ready['certificate']).read_bytes(), default_timeout=600000))
        await self.client.open()
        self.auth, self.token = await self.login('operator', 'test-only-extraction-operator-password')
        return self.ready

    async def login(self, username, password):
        response = await self.client.AuthenticationService.Login(UserIdentification=username, Password=password,
            RequestedServer=self.ready['server_uuid'], RequestedFeatures=[])
        return await self.client.AuthorizationService.AccessToken.from_native(self.client, response.AccessToken), response.AccessToken

    async def lock(self, seconds=600, auth=None):
        self.lock_id = str(uuid.uuid4())
        await self.client.LockController.LockServer(LockIdentifier=self.lock_id, Timeout=seconds, metadata=[auth or self.auth])
        return await self.client.LockController.LockIdentifier.from_native(self.client, self.lock_id)

    async def command(self, name, lease, request=None, auth=None, **arguments):
        response = await getattr(self.client.ExtractionAnalyticsWorkflow, name)(
            RequestIdentifier=request or str(uuid.uuid4()), RunIdentifier=self.run_id,
            metadata=[auth or self.auth, lease], **arguments)
        if hasattr(response, 'get_responses'):
            response = await wait_for_execution(response, 600)
        return json.loads(response.StatusJson)

    async def create(self, lease, family='dneasy', request=None, auth=None):
        return await self.command('CreateRun', lease, request=request, auth=auth, FamilyIdentifier=family)

    async def run_execution(self, lease, request=None):
        return await self.client.ExtractionAnalyticsWorkflow.RunUntilDecision(
            RequestIdentifier=request or str(uuid.uuid4()), RunIdentifier=self.run_id, metadata=[self.auth, lease])

    async def report(self, auth=None):
        value = json.loads(await self.client.ExtractionAnalyticsWorkflow.Report.read(metadata=[auth or self.auth]))
        return value['reports'][self.run_id]

    def event_count(self):
        connection = sqlite3.connect('file:' + self.ready['journal'] + '?mode=ro', uri=True)
        try:
            return connection.execute('SELECT COUNT(*) FROM events WHERE run_id=?', (self.run_id,)).fetchone()[0]
        finally:
            connection.close()

    async def wait_pending(self, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = json.loads(await self.client.ExtractionAnalyticsWorkflow.Status.read(metadata=[self.auth]))
            current = next(row for row in status['runs'] if row['run_id'] == self.run_id)
            if current['active_device'] == 'nanodrop' and current['pending_operation']:
                report = await self.report()
                context = report['analytics']['stages'].get('nanodrop')
                if context and context['local']['pending_measurement']:
                    return report
            failed = [record for record in current['network_commands'].values()
                if record['command'] == 'RunUntilDecision' and record['status'] in {'failed', 'interrupted'}]
            if failed:
                self.fail('Execution stopped before the NanoDrop checkpoint: ' + str(failed[-1].get('response')))
            await asyncio.sleep(.2)
        self.fail('No durable NanoDrop withdrawal intent observed')

    @staticmethod
    def reconciliation(report, resolution=None, return_home=False):
        observations = []
        context = report['analytics']['stages'].get('nanodrop')
        product_vessel = None
        home = None
        if context:
            profile = context['definition']['profile']
            product_vessel = profile['samples'][0]['vessel_id']
            home = {'kind': 'rack', 'rack_id': profile['rack']['id'],
                    'place_id': context['definition']['places'][0]['id']}
        for identity, vessel in report['inventory']['vessels'].items():
            location = home if return_home and identity == product_vessel else vessel['location']
            materials = [key for key, material in report['inventory']['materials'].items() if material['vessel_id'] == identity]
            observations.append({'vessel_id': identity, 'material_ids': materials, 'location': copy.deepcopy(location)})
        value = {'format': 'solidcraftbot.extraction-analytics-reconciliation/1',
            'reason': 'Explicit synthetic test observations; no scan, sensor or person authentication',
            'observations': observations, 'workspace_clear': True}
        if context:
            value['device'] = {'device': 'nanodrop', 'pending_resolution': resolution,
                'device_valid': True, 'reason': 'Explicit synthetic blank and pending-effect observation'}
        return value

    async def assert_completed_family(self, family, expected_volume):
        await self.start()
        lease = await self.lock()
        await self.create(lease, family)
        receipt = json.loads((await wait_for_execution(await self.run_execution(lease), 600)).StatusJson)
        self.assertEqual(receipt['root_status'], 'completed')
        report = await self.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['resources'], [])
        self.assertTrue(report['transport_receipts']['sila_loopback_executed'])
        for field in ('network_executed', 'hardware_executed', 'safety_function_qualified',
                      'biochemical_protocol_executed', 'fragment_size_qualified', 'sop_qualified',
                      'tapestation_network_executed', 'tapestation_hardware_executed',
                      'nanodrop_hardware_executed', 'qubit_hardware_executed'):
            self.assertIs(report[field], False, field)
        products = [key for key, material in report['inventory']['materials'].items() if material['kind'] == 'product']
        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertEqual(report['remaining'][product]['value'], expected_volume)
        self.assertEqual(report['inventory']['materials'][product]['disposition'], 'retained')
        self.assertEqual(sorted(item['quantity']['value'] for row in report['bookings'].values()
            for item in row.get('actual_inputs', []) if item['material_id'] == product), [1, 1.5, 2])
        checksums = set(report['imports'])
        for name in ('nanodrop', 'qubit'):
            context = report['analytics']['stages'][name]
            self.assertEqual(context['local']['status'], 'completed')
            self.assertTrue(context['id'].startswith(self.run_id + '.'))
            checksums.update(context['local']['imports'])
        self.assertEqual(len(checksums), 3)
        from manual_tasks import Journal
        with Journal(self.ready['journal']) as journal:
            state = journal.state(self.run_id)[0]
            spec = state['definition']['execution']['analytics']
            self.assertEqual(state['inventory']['materials'][product]['vessel_id'], spec['product_vessel_id'])
            self.assertEqual(state['inventory']['vessels'][spec['product_vessel_id']]['location'], spec['product_home'])
            self.assertEqual(report['remaining'][spec['reagent_bindings']['working_solution']]['value'], 422)
            for checksum in checksums:
                self.assertEqual(hashlib.sha256(journal.artifact(checksum)).hexdigest(), checksum)

    async def test_dneasy_tls_run_retains_identity_consumption_artifacts_and_limits(self):
        await self.assert_completed_family('dneasy', 195.5)

    async def test_puregene_tls_run_retains_identity_consumption_artifacts_and_limits(self):
        await self.assert_completed_family('puregene', 95.5)

    async def test_same_server_keeps_legacy_feature_and_enforces_authentication_trust_and_roles(self):
        from sila.client import SiLAError
        from sila import SiLATimeoutError
        from sila.client import Client, ClientConfig
        from sila.server import create_certificate
        from cf01_sila2_client import connect_station
        await self.start()
        self.assertIn('ExtractionAnalyticsWorkflow', self.ready['extraction_feature'])
        self.assertTrue(await self.client.SimulationController.SimulationMode.read(metadata=[self.auth]))
        with self.assertRaises(SiLAError):
            await self.client.SimulationController.StartRealMode(metadata=[self.auth])
        with self.assertRaises(SiLAError):
            await self.client.ExtractionAnalyticsWorkflow.Status.read()
        observer, _ = await self.login('observer', 'test-only-extraction-observer-password')
        self.assertTrue(json.loads(await self.client.ExtractionAnalyticsWorkflow.Status.read(metadata=[observer]))['simulation_only'])
        with self.assertRaises(SiLAError):
            await self.client.LockController.LockServer(LockIdentifier='observer', Timeout=30, metadata=[observer])
        with self.assertRaises(SiLAError):
            await self.client.ExtractionAnalyticsWorkflow.CreateRun(RequestIdentifier=str(uuid.uuid4()),
                RunIdentifier=self.run_id, FamilyIdentifier='dneasy', metadata=[self.auth])
        lease = await self.lock()
        with self.assertRaises(SiLAError):
            await self.create(lease, auth=observer)
        legacy = self.run_id + '.Legacy'
        await self.client.DnaQuantificationWorkflow.CreateRun(RequestIdentifier=str(uuid.uuid4()),
            RunIdentifier=legacy, metadata=[self.auth, lease])
        await self.create(lease)
        old = json.loads(await self.client.DnaQuantificationWorkflow.Report.read(metadata=[self.auth]))
        new = json.loads(await self.client.ExtractionAnalyticsWorkflow.Report.read(metadata=[self.auth]))
        self.assertIn(legacy, old['reports'])
        self.assertNotIn(self.run_id, old['reports'])
        self.assertIn(self.run_id, new['reports'])
        self.assertNotIn(legacy, new['reports'])
        events = self.event_count()
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            await connect_station({**self.ready, 'server_uuid': str(uuid.uuid4())},
                'operator', 'test-only-extraction-operator-password')
        wrong = create_certificate(str(uuid.uuid4()), ip_addresses=['127.0.0.1'])
        for tls, trust in [(True, wrong.pem_certificate), (False, None)]:
            client = Client(ClientConfig(hostname='127.0.0.1', port=self.ready['port'], tls=tls,
                root_certificates=trust, default_timeout=500))
            try:
                with self.assertRaises(SiLATimeoutError): await client.open(timeout=500)
            finally:
                await client.close()
        self.assertEqual(self.event_count(), events)

    async def test_exact_receipt_replay_and_argument_or_principal_conflicts_have_no_effect(self):
        from sila.client import SiLAError
        await self.start()
        lease = await self.lock()
        request = str(uuid.uuid4())
        first = await self.create(lease, request=request)
        events = self.event_count()
        self.assertEqual(await self.create(lease, request=request), first)
        self.assertEqual(self.event_count(), events)
        with self.assertRaises(SiLAError): await self.create(lease, 'puregene', request=request)
        self.assertEqual(self.event_count(), events)
        await self.client.LockController.UnlockServer(LockIdentifier=self.lock_id, metadata=[self.auth])
        second, _ = await self.login('second', 'test-only-extraction-second-password')
        lease = await self.lock(auth=second)
        with self.assertRaises(SiLAError): await self.create(lease, request=request, auth=second)
        self.assertEqual(self.event_count(), events)

    async def test_sigkill_pending_draw_requires_resume_explicit_unknown_and_performed_resolution(self):
        from sila.client import SiLAError
        await self.start('nanodrop_intent')
        lease = await self.lock()
        await self.create(lease)
        request = str(uuid.uuid4())
        await self.run_execution(lease, request=request)
        before = await self.wait_pending()
        pending = before['analytics']['stages']['nanodrop']['local']['pending_measurement']
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
        with self.assertRaises(SiLAError): await wait_for_execution(await self.run_execution(lease), 15)
        self.assertEqual(self.event_count(), events)
        await self.command('ResumeRun', lease, Resume=True)
        held = await self.report()
        self.assertEqual(held['bookings'], before['bookings'])
        events = self.event_count()
        with self.assertRaises(SiLAError): await wait_for_execution(await self.run_execution(lease, request=request), 15)
        self.assertEqual(self.event_count(), events)
        unknown = self.reconciliation(held, {'intent_id': pending['intent_id'], 'outcome': 'unknown'})
        try:
            await self.command('ReconcileRun', lease, ObservationJson=json.dumps(unknown))
        except SiLAError:
            pass  # A durable unknown effect remains held even if the RPC reports RecoveryRequired.
        held = await self.report()
        self.assertEqual(held['bookings'][pending['intent_id']]['outcome'], 'unknown')
        self.assertTrue(held['resources'])
        self.assertIsNone(next(value['value'] for key, value in held['remaining'].items()
            if held['inventory']['materials'][key]['kind'] == 'product'))
        performed = self.reconciliation(held, {'intent_id': pending['intent_id'], 'outcome': 'performed',
            'observed_sample_id': pending['sample_id'], 'volume_ul': 1.5, 'cleaned': True}, return_home=True)
        await self.command('ReconcileRun', lease, ObservationJson=json.dumps(performed))
        await wait_for_execution(await self.run_execution(lease), 600)
        report = await self.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['bookings'][pending['intent_id']]['actual_inputs'][0]['quantity']['value'], 1.5)
        products = [key for key, material in report['inventory']['materials'].items() if material['kind'] == 'product']
        self.assertEqual(report['remaining'][products[0]]['value'], 195.5)
        self.assertEqual(len(report['analytics']['stages']['nanodrop']['local']['measurements']), 1)

    async def test_cancel_controller_and_lease_expiry_keep_pending_material_and_root_holds(self):
        from sila.client import SiLAError
        await self.start('nanodrop_intent')
        lease = await self.lock()
        await self.create(lease)
        execution = await self.run_execution(lease)
        before = await self.wait_pending()
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution.command_execution_uuid,
            metadata=[self.auth])
        with self.assertRaises(SiLAError): await wait_for_execution(execution, 15)
        held = await self.report()
        self.assertEqual(held['bookings'], before['bookings'])
        self.assertTrue(held['resources'])
        self.assertNotEqual(held['status'], 'cancelled')
        await self.client.LockController.UnlockServer(LockIdentifier=self.lock_id, metadata=[self.auth])
        lease = await self.lock(seconds=1)
        await asyncio.sleep(1.05)
        events = self.event_count()
        with self.assertRaises(SiLAError):
            await self.command('CancelRun', lease, Reason='Expired lease must not acquire a root effect')
        self.assertEqual(self.event_count(), events)
        self.assertEqual((await self.report())['bookings'], before['bookings'])
        self.assertTrue((await self.report())['resources'])

    async def test_public_cli_selects_extraction_contract_and_reads_without_dispatch(self):
        await self.start()
        ready = self.folder / 'client-ready.json'; ready.write_text(json.dumps(self.ready))
        login = self.folder / 'operator-login.json'
        login.write_text(json.dumps({'username': 'operator', 'password': 'test-only-extraction-operator-password'}))
        login.chmod(0o600)
        arguments = self.folder / 'create.json'; arguments.write_text(json.dumps({'family_identifier': 'puregene'}))
        output = self.folder / 'create-receipt.json'
        common = [sys.executable, str(ROOT / 'scripts/run_dna_sila2.py')]
        connection = ['--feature', 'extraction', '--ready-file', str(ready), '--login-input', str(login), '--timeout', '30']
        result = await asyncio.to_thread(subprocess.run, [*common, 'command', *connection,
            '--run-id', self.run_id, '--name', 'CreateRun', '--request-id', str(uuid.uuid4()),
            '--arguments-input', str(arguments), '--out', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), json.loads(output.read_text()))
        events = self.event_count()
        read = await asyncio.to_thread(subprocess.run, [*common, 'report', *connection], cwd=ROOT,
            capture_output=True, text=True, timeout=45)
        self.assertEqual(read.returncode, 0, read.stderr)
        observed = json.loads(read.stdout)
        self.assertFalse(observed['process_effects_dispatched'])
        self.assertEqual(observed['value']['reports'][self.run_id]['status'], 'created')
        self.assertEqual(self.event_count(), events)
        self.assertNotIn('test-only-extraction-operator-password', result.stdout + read.stdout)

    async def test_tapestation_restart_cannot_invent_completion_or_release_without_stop_receipt(self):
        from sila.client import SiLAError
        await self.start('tapestation_loaded')
        lease = await self.lock()
        await self.create(lease)
        await self.run_execution(lease)
        deadline = time.monotonic() + 300
        while True:
            before = await self.report()
            if before['process']['qc']['loaded'] is not None:
                break
            failed = [record for record in before['transport_receipts']['network']['commands'].values()
                if record['command'] == 'RunUntilDecision' and record['status'] in {'failed', 'interrupted'}]
            if failed:
                self.fail('Execution stopped before the TapeStation checkpoint: ' + str(failed[-1].get('response')))
            if time.monotonic() >= deadline:
                self.fail('TapeStation loading was not durably observed')
            await asyncio.sleep(1)
        self.assertIsNone(before['process']['qc']['run_complete'])
        self.process.kill()
        await asyncio.to_thread(self.process.wait, 5)
        await self.client.close()
        self.client = None
        await self.start()
        lease = await self.lock()
        await self.command('ResumeRun', lease, Resume=True)
        with self.assertRaises(SiLAError):
            await wait_for_execution(await self.run_execution(lease), 20)
        held = await self.report()
        self.assertEqual(held['bookings'], before['bookings'])
        self.assertIsNone(held['process']['qc']['run_complete'])
        self.assertTrue(held['resources'])
        await self.command('CancelRun', lease, Reason='Explicit synthetic cancellation of interrupted TapeStation work')
        held = await self.report()
        dispositions = []
        discarded = set()
        for identity, material in held['inventory']['materials'].items():
            if material['disposition'] in {'consumed', 'discarded'}:
                continue
            disposition = ('quarantined' if material['kind'] == 'product' else
                           'retained' if material['kind'] == 'reagent' else 'discarded')
            dispositions.append({'material_id': identity, 'disposition': disposition,
                'reason': 'Explicit synthetic final material disposition'})
            if disposition == 'discarded':
                discarded.add(identity)
        observations = [{'vessel_id': identity,
            'material_ids': [key for key, material in held['inventory']['materials'].items()
                if material['vessel_id'] == identity and key not in discarded],
            'location': copy.deepcopy(vessel['location'])}
            for identity, vessel in held['inventory']['vessels'].items()]
        document = {'format': 'solidcraftbot.extraction-analytics-reconciliation/1',
            'reason': 'Explicit synthetic stopped-run inventory and dispositions',
            'observations': observations, 'workspace_clear': True, 'dispositions': dispositions}
        with self.assertRaises(SiLAError):
            await self.command('FinishCancel', lease, ObservationJson=json.dumps(document))
        self.assertTrue((await self.report())['resources'])
        request = held['process']['qc']['request']
        row = request['expected']['measurements'][0]
        document['tapestation_abort'] = {'reason': 'Explicit synthetic stopped and retrieved TapeStation observation',
            'observations': {'sample_material_id': row['aliquot_material_id'],
                'sample_vessel_id': row['aliquot_vessel_id'], 'ladder_material_id': request['ladder_material_id'],
                'ladder_vessel_id': request['ladder_vessel_id'], 'sample_lane_id': row['lane_id'],
                'ladder_lane_id': request['ladder_lane_id'], 'screen_tape_id': request['screen_tape_id'],
                'instrument_run_id': request['expected']['instrument_run_id'],
                'analysis_id': request['expected']['analysis_id'], 'instrument_stopped': True,
                'sample_retrieved': True, 'ladder_retrieved': True,
                'materials_accounted': True, 'identities_confirmed': True}}
        await self.command('FinishCancel', lease, ObservationJson=json.dumps(document))
        report = await self.report()
        self.assertEqual(report['status'], 'cancelled')
        self.assertEqual(report['resources'], [])
        self.assertFalse(report['passed'])
        self.assertIsNone(report['process']['qc']['run_complete'])
        products = [material for material in report['inventory']['materials'].values() if material['kind'] == 'product']
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['disposition'], 'quarantined')
        self.assertIsNotNone(products[0]['vessel_id'])


if __name__ == '__main__':
    unittest.main()
