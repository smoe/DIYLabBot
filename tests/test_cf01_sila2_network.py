"""Actual TLS/gRPC tests; opt in explicitly, never substitute local dispatch."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cf01_sila2_client import wait_for_execution
ENABLED = importlib.util.find_spec('sila') is not None and os.getenv('SOLIDCRAFTBOT_SILA_NETWORK_TESTS') == '1'


@unittest.skipUnless(ENABLED, 'Install SiLA dependencies and set SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1')
class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        from cf01_sila2_auth import credential
        from cf01_sila2_server import CF01Server
        from sila.client import Client, ClientConfig
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.application = CF01Server(root / 'station.sqlite3',
            [credential('operator', 'test-only-operator-password', 'operator'),
             credential('observer', 'test-only-observer-password', 'observer')], root / 'tls')
        await self.application.start()
        self.client = Client(ClientConfig(hostname='127.0.0.1', port=self.application.port,
                             tls=True, root_certificates=self.application.certificate, default_timeout=5000))
        await self.client.open()
        self.auth = await self.login('operator', 'test-only-operator-password')

    async def asyncTearDown(self):
        await self.client.close()
        await self.application.stop()
        self.directory.cleanup()

    async def login(self, username, password):
        response = await self.client.AuthenticationService.Login(UserIdentification=username, Password=password,
                        RequestedServer=self.application.runtime.store.server_uuid, RequestedFeatures=[])
        return await self.client.AuthorizationService.AccessToken.from_native(self.client, response.AccessToken)

    async def lock(self):
        identifier = str(uuid.uuid4())
        await self.client.LockController.LockServer(LockIdentifier=identifier, Timeout=30, metadata=[self.auth])
        return await self.client.LockController.LockIdentifier.from_native(self.client, identifier)

    async def intent(self):
        return await self.client.CentrifugeControl.RequestIdentifier.from_native(self.client, str(uuid.uuid4()))

    async def command(self, name, lock, **arguments):
        command = getattr(self.client.CentrifugeControl, name)
        response = await command(metadata=[self.auth, lock, await self.intent()], **arguments)
        if hasattr(response, 'get_responses'):
            response = await wait_for_execution(response, 5)
        return response

    async def load_rotor(self, lock):
        for slot in range(1, 13):
            await self.command('CloseLid', lock)
            await self.command('IndexRotor', lock, Slot=slot)
            await self.command('OpenLid', lock)
            await self.command('ConfirmSeated', lock, MassG=2., SeatedConfirmed=True, CapClosedConfirmed=True)
        await self.command('CloseLid', lock)

    async def test_identity_feature_discovery_and_confirmed_command(self):
        self.assertEqual(await self.client.SiLAService.ServerUUID.read(), self.application.runtime.store.server_uuid)
        self.assertTrue(await self.client.SimulationController.SimulationMode.read(metadata=[self.auth]))
        lock = await self.lock()
        response = await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, lock])
        self.assertTrue(response.State.SimulationOnly)
        self.assertEqual(response.State.ClockMode, 'monotonic_realtime')
        self.assertEqual([slot.Slot for slot in response.State.RotorSlots], list(range(1, 13)))
        self.assertTrue(all(not slot.Present and not slot.MassValid for slot in response.State.RotorSlots))
        execution = await self.client.CentrifugeControl.IndexRotor(Slot=1, metadata=[self.auth, lock, await self.intent()])
        result = await wait_for_execution(execution, 5)
        self.assertEqual(result.State.IndexedSlot, 1)
        self.assertTrue(result.State.IndexConfirmed)

    async def test_unauthenticated_and_observer_changes_are_rejected(self):
        from sila.client import SiLAError
        with self.assertRaises(SiLAError):
            await self.client.CentrifugeControl.GetStatus()
        observer = await self.login('observer', 'test-only-observer-password')
        with self.assertRaises(SiLAError):
            await self.client.LockController.LockServer(LockIdentifier='observer', Timeout=30, metadata=[observer])
        self.assertIsNone(self.application.runtime.lock_id)
        observed = await self.client.CentrifugeControl.Status.read(metadata=[observer], timeout=5000)
        self.assertTrue(observed.SimulationOnly)

    def status_endpoint(self):
        return {'tls': True, 'simulation_only': True, 'hardware_available': False,
                'bind': '127.0.0.1', 'port': self.application.port,
                'server_uuid': self.application.runtime.store.server_uuid,
                'boot_id': self.application.runtime.sim.boot_id,
                'certificate': str(Path(self.directory.name) / 'tls/server.crt')}

    async def test_read_only_reconnect_observes_held_work_and_changed_boot_without_touching_lease(self):
        from cf01_sila2_client import read_station_status
        lock = await self.lock()
        await self.command('IndexRotor', lock, Slot=2)
        runtime = self.application.runtime
        runtime.needs_reconciliation = True
        deadline, owner = runtime.lock_deadline, runtime.sim.owner
        ready = {**self.status_endpoint(), 'boot_id': str(uuid.uuid4())}
        observed = await read_station_status(ready, 'observer', 'test-only-observer-password')
        self.assertTrue(observed['boot_changed'])
        self.assertTrue(observed['state']['recovery_required'])
        self.assertEqual(observed['observed_boot_id'], runtime.sim.boot_id)
        self.assertEqual(observed['state']['indexed_slot'], 2)
        self.assertFalse(observed['process_effects_dispatched'])
        self.assertFalse(observed['workflow_clock_advanced'])
        self.assertEqual(runtime.lock_deadline, deadline)
        self.assertEqual(runtime.sim.owner, owner)
        self.assertLessEqual(observed['client_request_started_monotonic_s'], observed['client_response_received_monotonic_s'])

    async def test_read_only_reconnect_checks_server_identity_and_does_not_echo_credentials(self):
        from cf01_sila2_client import read_station_status
        for ready, password in [(self.status_endpoint(), 'SYN.WrongSecret'),
                                ({**self.status_endpoint(), 'server_uuid': str(uuid.uuid4())}, 'SYN.Secret')]:
            with self.subTest(server=ready['server_uuid']):
                with self.assertRaisesRegex(RuntimeError, 'Could not read authenticated CF01') as caught:
                    await read_station_status(ready, 'observer', password)
                self.assertNotIn(password, str(caught.exception))
        self.assertIsNone(self.application.runtime.lock_id)

    async def test_status_cli_reconnects_without_creating_a_batch_journal(self):
        from run_cf01_sila2 import private_json
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cf01-status-', dir=ROOT / 'exports') as folder:
            root = Path(folder)
            ready, login, output = root / 'ready.json', root / 'login.json', root / 'status.json'
            private_json(ready, self.status_endpoint())
            private_json(login, {'username': 'observer', 'password': 'test-only-observer-password'})
            args = [sys.executable, str(ROOT / 'scripts/run_cf01_sila2.py'), '--language', 'en',
                    'status', '--ready-file', str(ready), '--login-input', str(login), '--out', str(output)]
            result = await asyncio.to_thread(subprocess.run, args, cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['process_effects_dispatched'])
            observed = json.loads(output.read_text())
            self.assertEqual(observed['observation'], 'authenticated_live_status')
            self.assertFalse(observed['boot_changed'])
            self.assertEqual(set(path.name for path in root.iterdir()), {'ready.json', 'login.json', 'status.json'})

    async def test_no_real_mode_or_unvalidated_slot(self):
        from sila.client import SiLAError
        with self.assertRaises(SiLAError):
            await self.client.SimulationController.StartRealMode(metadata=[self.auth])
        lock = await self.lock()
        with self.assertRaises(SiLAError):
            await self.client.CentrifugeControl.IndexRotor(Slot=13, metadata=[self.auth, lock, await self.intent()])
        self.assertIsNone(self.application.runtime.sim.indexed_slot)

    async def test_duplicate_network_intent_does_not_repeat_effect(self):
        from sila.client import SiLAError
        lock, intent = await self.lock(), await self.intent()
        execution = await self.client.CentrifugeControl.IndexRotor(Slot=1, metadata=[self.auth, lock, intent])
        await wait_for_execution(execution, 5)
        other = await self.client.CentrifugeControl.IndexRotor(Slot=2, metadata=[self.auth, lock, intent])
        with self.assertRaises(SiLAError):
            await wait_for_execution(other, 5)
        self.assertEqual(self.application.runtime.sim.indexed_slot, 1)

    async def test_server_clock_progresses_while_client_is_idle(self):
        before = self.application.runtime.status()['process_time_s']
        await asyncio.sleep(.15)
        after = self.application.runtime.status()['process_time_s']
        self.assertGreaterEqual(after - before, .14)
        self.assertIsNotNone(self.application._ticker)
        self.assertFalse(self.application._ticker.done())

    async def test_cancellation_ack_precedes_confirmed_stop_and_execution_error(self):
        from sila.client import DefinedExecutionError
        lock = await self.lock()
        await self.load_rotor(lock)
        execution = await self.client.CentrifugeControl.RunCentrifuge(RcfXG=100., DurationS=5.,
                          metadata=[self.auth, lock, await self.intent()])
        await asyncio.sleep(.15)
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution.command_execution_uuid,
                                                        metadata=[self.auth])
        state = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, lock])).State
        self.assertFalse(state.StandstillConfirmed)
        self.assertEqual(state.RunPhase, 'braking')
        with self.assertRaises(DefinedExecutionError) as caught:
            await wait_for_execution(execution, self.application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 3)
        self.assertEqual(caught.exception.identifier, 'CommandCanceled')
        state = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, lock])).State
        self.assertTrue(state.StandstillConfirmed)
        self.assertTrue(state.ParkingBrakeHeld)

    async def test_normal_spin_and_braking_finish_without_client_advancing_time(self):
        lock = await self.lock()
        await self.load_rotor(lock)
        execution = await self.client.CentrifugeControl.RunCentrifuge(RcfXG=100., DurationS=.3,
                          metadata=[self.auth, lock, await self.intent()])
        response = await wait_for_execution(execution, self.application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 3)
        self.assertTrue(response.State.StandstillConfirmed)
        self.assertTrue(response.State.ParkingBrakeHeld)
        self.assertEqual(response.State.RunPhase, 'completed')

    async def test_wrong_certificate_and_plaintext_cannot_connect(self):
        from sila import SiLATimeoutError
        from sila.client import Client, ClientConfig
        from sila.server import create_certificate
        wrong = create_certificate(str(uuid.uuid4()), ip_addresses=['127.0.0.1'])
        for tls, trust, options in [(True, wrong.pem_certificate, None), (False, None, None),
                                   (True, self.application.certificate, [('grpc.ssl_target_name_override', 'wrong-host.invalid')])]:
            with self.subTest(tls=tls, options=options):
                rejected = Client(ClientConfig(hostname='127.0.0.1', port=self.application.port,
                                               tls=tls, root_certificates=trust, options=options, default_timeout=500))
                try:
                    with self.assertRaises(SiLATimeoutError):
                        await rejected.open(timeout=500)
                finally:
                    await rejected.close()
        # Rejection did not replace the persisted identity or downgrade TLS.
        self.assertEqual(await self.client.SiLAService.ServerUUID.read(), self.application.runtime.store.server_uuid)

    async def test_execution_deadline_does_not_retry_or_claim_completion(self):
        from cf01_sila2_client import UncertainExecution
        from sila.client import DefinedExecutionError
        lock = await self.lock()
        await self.load_rotor(lock)
        request = str(uuid.uuid4())
        jobs_before = len(self.application.runtime.jobs)
        intent = await self.client.CentrifugeControl.RequestIdentifier.from_native(self.client, request)
        execution = await self.client.CentrifugeControl.RunCentrifuge(RcfXG=100., DurationS=5.,
                          metadata=[self.auth, lock, intent])
        with self.assertRaises(UncertainExecution) as caught:
            await wait_for_execution(execution, .05)
        self.assertEqual(caught.exception.execution_uuid, execution.command_execution_uuid)
        state = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, lock])).State
        self.assertFalse(state.StandstillConfirmed)
        pending = self.application.runtime.store.pending()
        self.assertEqual([item['request_id'] for item in pending], [request])
        self.assertEqual(len(self.application.runtime.jobs), jobs_before + 1)
        await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution.command_execution_uuid,
                                                        metadata=[self.auth])
        with self.assertRaises(DefinedExecutionError) as canceled:
            await wait_for_execution(execution, self.application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 3)
        self.assertEqual(canceled.exception.identifier, 'CommandCanceled')
        self.assertFalse(self.application.runtime.store.pending())

    async def test_existing_batch_runner_roundtrip_uses_only_network_station(self):
        import json
        from cf01_sila2_batch import ClientJournal, NetworkStation
        from cf01_rack_batch import Runner
        root = Path(self.directory.name)
        ready = {'bind': '127.0.0.1', 'port': self.application.port,
                 'server_uuid': self.application.runtime.store.server_uuid,
                 'boot_id': self.application.runtime.sim.boot_id,
                 'certificate': str(root / 'tls/server.crt'), 'tls': True,
                 'simulation_only': True, 'hardware_available': False}

        def run():
            journal = ClientJournal(root / 'batch-client.jsonl')
            station = None
            try:
                station = NetworkStation(ready, 'operator', 'test-only-operator-password', journal)
                runner = Runner(transport='sila2', station_backend=station, checkpoint=journal.checkpoint)
                self.assertIsNone(runner.sim, 'Network batch must not construct a second simulator')
                return runner.run()
            finally:
                if station is not None:
                    station.close()
                journal.close()

        report = await asyncio.wait_for(asyncio.to_thread(run), 90)
        self.assertTrue(report['passed'])
        self.assertTrue(report['network_executed'])
        self.assertTrue(report['spin_completed'])
        self.assertTrue(report['order_restored'])
        self.assertEqual(report['initial_order'], report['final_order'])
        self.assertFalse(any(report['inventory']['rotor']))
        self.assertIsNone(report['inventory']['gripper'])
        self.assertIsNone(report['pending_handoff'])
        self.assertIsNone(self.application.runtime.lock_id)
        self.assertIsNone(self.application.runtime.sim.owner)
        self.assertTrue(self.application.runtime.sim.robot_clear)
        self.assertTrue(all(not value['present'] for value in self.application.runtime.sim.slots.values()))
        observations = [event for event in self.application.runtime.sim.events if event['kind'] == 'CF01.synthetic.robot_observation']
        self.assertEqual(len(observations), 4 * len(report['initial_order']))
        rows = [json.loads(line) for line in (root / 'batch-client.jsonl').read_text().splitlines()]
        self.assertFalse(any(row['event'] == 'uncertain' for row in rows))
        self.assertTrue(any(row['event'] == 'runner_checkpoint' and row['kind'] == 'handoff_intent' for row in rows))

    async def test_partial_network_handoff_keeps_inventory_and_station_owned(self):
        from cf01_sila2_batch import ClientJournal, NetworkStation
        from cf01_rack_batch import Runner, BatchError, synthetic_feedback
        root = Path(self.directory.name)
        ready = {'bind': '127.0.0.1', 'port': self.application.port,
                 'server_uuid': self.application.runtime.store.server_uuid,
                 'boot_id': self.application.runtime.sim.boot_id,
                 'certificate': str(root / 'tls/server.crt'), 'tls': True,
                 'simulation_only': True, 'hardware_available': False}

        def feedback(event, sample):
            value = synthetic_feedback(event, sample)
            if event == 'seat_rotor':
                value['cap_closed_confirmed'] = False
            return value

        def run():
            journal = ClientJournal(root / 'partial-client.jsonl')
            station = None
            try:
                station = NetworkStation(ready, 'operator', 'test-only-operator-password', journal)
                runner = Runner(transport='sila2', station_backend=station, checkpoint=journal.checkpoint, feedback=feedback)
                try:
                    runner.run()
                except BatchError as error:
                    return error.report
                raise AssertionError('Unconfirmed seating must fail')
            finally:
                if station is not None:
                    station.close()
                journal.close()

        report = await asyncio.wait_for(asyncio.to_thread(run), 20)
        self.assertFalse(report['passed'])
        self.assertFalse(report['order_restored'])
        self.assertFalse(report['spin_completed'])
        self.assertTrue(report['stop_via_contract'])
        self.assertEqual(report['ownership'], 'unresolved')
        self.assertEqual(report['pending_handoff']['event'], 'seat_rotor')
        self.assertEqual(report['inventory']['gripper'], report['initial_order'][0])
        self.assertIsNone(report['inventory']['rotor'][0])
        self.assertIsNotNone(self.application.runtime.lock_id)
        self.assertIsNotNone(self.application.runtime.sim.owner)
        self.assertFalse(self.application.runtime.sim.robot_clear)
        self.assertFalse(self.application.runtime.sim.slots[1]['present'])

    async def test_lost_network_response_preserves_one_durable_effect(self):
        from sila import SiLATimeoutError
        from sila.client import Client, ClientConfig, DefinedExecutionError
        from sila.client.command_execution import CommandExecution
        lock = await self.lock()
        await self.load_rotor(lock)
        drop_responses = False
        dropped_bytes = 0
        connections, workers = [], set()

        async def proxy(reader, writer):
            nonlocal dropped_bytes
            task = asyncio.current_task()
            workers.add(task)
            upstream_reader, upstream_writer = await asyncio.open_connection('127.0.0.1', self.application.port)
            connections.extend([writer, upstream_writer])
            async def relay(source, destination, response):
                nonlocal dropped_bytes
                while data := await source.read(65536):
                    if response and drop_responses:
                        dropped_bytes += len(data)
                    else:
                        destination.write(data)
                        await destination.drain()
            try:
                await asyncio.gather(relay(reader, upstream_writer, False), relay(upstream_reader, writer, True))
            finally:
                writer.close()
                upstream_writer.close()
                workers.discard(task)

        listener = await asyncio.start_server(proxy, '127.0.0.1', 0)
        port = listener.sockets[0].getsockname()[1]
        client = Client(ClientConfig(hostname='127.0.0.1', port=port, tls=True,
                        root_certificates=self.application.certificate, default_timeout=5000))
        try:
            await client.open()
            authenticated = await client.AuthenticationService.Login(UserIdentification='operator',
                Password='test-only-operator-password', RequestedServer=self.application.runtime.store.server_uuid, RequestedFeatures=[])
            auth = await client.AuthorizationService.AccessToken.from_native(client, authenticated.AccessToken)
            remote_lock = await client.LockController.LockIdentifier.from_native(client, self.application.runtime.lock_id)
            request = str(uuid.uuid4())
            intent = await client.CentrifugeControl.RequestIdentifier.from_native(client, request)
            drop_responses = True
            with self.assertRaises(SiLATimeoutError):
                await client.CentrifugeControl.RunCentrifuge(RcfXG=100., DurationS=20., timeout=300,
                                                           metadata=[auth, remote_lock, intent])
            self.assertGreater(dropped_bytes, 0)
            pending = self.application.runtime.store.pending()
            self.assertEqual([item['request_id'] for item in pending], [request])
            state = (await self.client.CentrifugeControl.GetStatus(metadata=[self.auth, lock])).State
            self.assertFalse(state.StandstillConfirmed)
            self.assertEqual(state.RunPhase, 'running')
            self.assertEqual(sum(event['kind'] == 'CF01.spin' for event in self.application.runtime.sim.events), 1)
            execution_id = pending[0]['execution_uuid']
            await self.client.CancelController.CancelCommand(CommandExecutionUUID=execution_id, metadata=[self.auth])
            recovered = CommandExecution(self.client.CentrifugeControl.RunCentrifuge, execution_id)
            with self.assertRaises(DefinedExecutionError) as canceled:
                await wait_for_execution(recovered, self.application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 3)
            self.assertEqual(canceled.exception.identifier, 'CommandCanceled')
        finally:
            await client.close()
            listener.close()
            await listener.wait_closed()
            for writer in connections:
                writer.close()
            for task in list(workers):
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def test_actual_multicast_discovery_and_explicit_tls_trust(self):
        from sila.server.discovery import Discovery as Publisher, DiscoveryConfig
        from sila.client.discovery import Discovery as Browser
        from sila.client import Client, ClientConfig
        async with Browser(interface_address='127.0.0.1') as browser:
            publisher = Publisher(self.application.server, DiscoveryConfig(network_interfaces=['127.0.0.1']))
            self.application.discovery = publisher
            await publisher.start()
            service = await browser.wait_for(uuid=self.application.runtime.store.server_uuid, timeout=5000)
            self.assertIn('127.0.0.1', service.addresses)
            self.assertEqual(service.port, self.application.port)
            from cryptography import x509
            from cryptography.hazmat.primitives import serialization
            self.assertEqual(x509.load_pem_x509_certificate(service.certificate).public_bytes(serialization.Encoding.DER),
                             x509.load_pem_x509_certificate(self.application.certificate).public_bytes(serialization.Encoding.DER))
            # Discovery locates the service. Trust still comes from the explicit
            # expected certificate, not from trusting arbitrary mDNS content.
            discovered = Client(ClientConfig(hostname='127.0.0.1', port=service.port, tls=True,
                root_certificates=self.application.certificate, default_timeout=3000))
            try:
                await discovered.open()
                self.assertEqual(await discovered.SiLAService.ServerUUID.read(), service.uuid)
            finally:
                await discovered.close()

    async def test_disconnect_and_lease_expiry_brake_without_releasing_process(self):
        from sila.client import Client, ClientConfig, DefinedExecutionError
        from sila.client.command_execution import CommandExecution
        lock = await self.lock()
        await self.load_rotor(lock)
        identifier = self.application.runtime.lock_id
        await self.client.LockController.UnlockServer(LockIdentifier=identifier, metadata=[self.auth])
        identifier = str(uuid.uuid4())
        await self.client.LockController.LockServer(LockIdentifier=identifier, Timeout=1, metadata=[self.auth])
        lock = await self.client.LockController.LockIdentifier.from_native(self.client, identifier)
        execution = await self.client.CentrifugeControl.RunCentrifuge(RcfXG=100., DurationS=20.,
                          metadata=[self.auth, lock, await self.intent()])
        execution_id = execution.command_execution_uuid
        await self.client.close()  # Actual channel loss; no client-driven time or heartbeat.
        self.client = Client(ClientConfig(hostname='127.0.0.1', port=self.application.port, tls=True,
                             root_certificates=self.application.certificate, default_timeout=5000))
        await self.client.open()
        self.auth = await self.login('operator', 'test-only-operator-password')
        await asyncio.sleep(1.1)
        state = await self.client.CentrifugeControl.Status.read(metadata=[self.auth], timeout=3000)
        self.assertTrue(state.RecoveryRequired)
        self.assertFalse(state.StandstillConfirmed)
        self.assertFalse(await self.client.LockController.IsLocked.read(metadata=[self.auth]))
        self.assertIsNotNone(self.application.runtime.sim.owner)
        recovered = CommandExecution(self.client.CentrifugeControl.RunCentrifuge, execution_id)
        with self.assertRaises(DefinedExecutionError) as failed:
            await wait_for_execution(recovered, self.application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 3)
        self.assertEqual(failed.exception.identifier, 'OwnerTimeout')
        state = await self.client.CentrifugeControl.Status.read(metadata=[self.auth], timeout=3000)
        self.assertTrue(state.StandstillConfirmed)
        self.assertTrue(state.ParkingBrakeHeld)
        self.assertTrue(state.RecoveryRequired)
        self.assertIsNotNone(self.application.runtime.sim.owner)
        await self.client.LockController.LockServer(LockIdentifier='recovery-lease', Timeout=30, metadata=[self.auth])
        recovery_lock = await self.client.LockController.LockIdentifier.from_native(self.client, 'recovery-lease')
        with self.assertRaises(DefinedExecutionError) as blocked:
            await self.command('ResetFault', recovery_lock)
        self.assertEqual(blocked.exception.identifier, 'RecoveryRequired')
        self.assertTrue((await self.client.CentrifugeControl.Status.read(metadata=[self.auth], timeout=3000)).RecoveryRequired)

    async def test_lower_tube_reset_and_rotation_feedback_typed_commands(self):
        lock = await self.lock()
        await self.command('IndexRotor', lock, Slot=1)
        await self.command('OpenLid', lock)
        await self.command('ConfirmSeated', lock, MassG=2., SeatedConfirmed=True, CapClosedConfirmed=True)
        raised = await self.command('PresentTube', lock)
        self.assertGreater(raised.State.LiftM, 0)
        lowered = await self.command('LowerTube', lock, SeatedConfirmed=True)
        self.assertEqual(lowered.State.LiftM, 0)
        self.assertTrue(lowered.State.RotorSlots[0].Seated)
        feedback = await self.client.CentrifugeControl.GetRotationFeedback(metadata=[self.auth, lock])
        self.assertTrue(feedback.State.EncoderHealthy)
        self.assertTrue(feedback.State.SpeedValid)
        self.assertEqual(feedback.State.SpeedRadS, 0)
        reset = await self.command('ResetFault', lock)
        self.assertFalse(reset.State.RecoveryRequired)
        await self.command('CloseLid', lock)


if __name__ == '__main__':
    unittest.main()
