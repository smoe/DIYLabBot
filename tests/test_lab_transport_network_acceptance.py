"""Actual TLS clients, authenticated courier roles and one canonical T3 owner.

One genuine local CF01 mock execution provides the prefix. Per-test database
copies are isolated synthetic test worlds, not supported stock continuation.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lab_transport_http as http
from lab_transport_http import TransportClient, TransportHTTPServer, TransportHTTPError
from lab_transport_access import credential
from lab_transport_network import NetworkWorkflow, Service
from lab_workflow_ledger import remaining
from manual_tasks import Journal, digest

OWNER = 'SYN.Operator01'
RUN = 'SYN.T3.NetworkAcceptance'
PASSWORD = 'Synthetic.Test.Courier.Password.2026'


class CourierNetworkAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'exports').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='t3-network-acceptance-', dir=ROOT / 'exports')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        cls.prefix = cls.folder / 'prefix.sqlite3'
        with Journal(cls.prefix) as journal:
            flow = NetworkWorkflow.create(journal, run_id=RUN)
            flow.accept_rack(OWNER, flow.inventory_observations())
            for sample in flow.state['definition']['manifest']['samples']:
                flow.confirm_mass(OWNER, sample['vessel_id'], 2.0, 0)
            assert flow.run_cf01(OWNER)['passed']
            cls.server_uuid = flow.state['network']['server_uuid']
            cls.initial_inventory = copy.deepcopy(flow.state['inventory'])
            cls.initial_bookings = copy.deepcopy(flow.state['bookings'])
            flow.close()
        cls.accounts = [
            credential('owner', PASSWORD, OWNER, [{'id': 'Grant.Owner', 'kind': 'owner', 'resource_id': RUN}]),
            credential('source', PASSWORD, 'SYN.LabA.Endpoint', [{'id': 'Grant.Source', 'kind': 'endpoint', 'resource_id': 'LabA.CF01'}]),
            credential('source2', PASSWORD, 'SYN.LabA.Endpoint', [{'id': 'Grant.Source', 'kind': 'endpoint', 'resource_id': 'LabA.CF01'}]),
            credential('courier', PASSWORD, 'SYN.Human.Courier', [{'id': 'Grant.Courier', 'kind': 'agent', 'resource_id': 'AgentHuman'}]),
            credential('receiver', PASSWORD, 'SYN.LabB.Endpoint', [{'id': 'Grant.Target', 'kind': 'endpoint', 'resource_id': 'LabB.NanoDrop'}]),
            credential('observer', PASSWORD, 'SYN.Observer', [{'id': 'Grant.Observer', 'kind': 'observer', 'resource_id': RUN}]),
        ]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.folder)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'journal.sqlite3'
        shutil.copyfile(self.prefix, self.store)
        for name, value in [
            ('service.json', {'format': 'solidcraftbot.lab-transport-service/1', 'store': str(self.store),
                              'run_id': RUN, 'server_uuid': self.server_uuid}),
            ('users.json', {'format': 'solidcraftbot.lab-transport-users/1', 'users': self.accounts}),
        ]:
            path = self.directory / name
            path.write_text(json.dumps(value) + '\n'); path.chmod(0o600)
        self.service = None; self.server = None; self.thread = None
        self.start()
        self.addCleanup(self.stop)
        self.clients = {}
        self.counter = 0

    def start(self):
        self.service = Service(self.directory)
        self.server = TransportHTTPServer(self.service, self.directory / 'tls')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown(); self.server.server_close()
            self.thread.join(timeout=5)
            self.server = None
        if self.service is not None:
            self.service.close(); self.service = None

    def root(self):
        with Journal(self.store) as journal: return journal.get_current(RUN, verify=True)

    def client(self, subject):
        if subject not in self.clients:
            client = TransportClient(self.server.origin, self.server.certificate_path)
            info = client.info()
            self.assertEqual(info['server_uuid'], self.server_uuid)
            result = client.login(subject, PASSWORD, info['server_uuid'])
            self.assertEqual(result['subject'], subject)
            self.clients[subject] = client
        return self.clients[subject]

    def identity(self, prefix='Request'):
        self.counter += 1
        return prefix + '.' + str(self.counter)

    def owner_request(self, operation, args, request_id=None):
        owner = self.client('owner'); snapshot = owner.snapshot()
        full = {'boot_id': snapshot['boot_id'], 'assignment_epoch': snapshot['assignment_epoch'], **args}
        return owner.submit(request_id or self.identity(), 'Grant.Owner', operation, full, snapshot['cursor'])

    def prepared(self):
        owner = self.client('owner')
        first = owner.snapshot()
        self.assertFalse(first['write_session_available'])
        self.owner_request('resume', {})
        state = owner.snapshot()
        hint = state['workflow_reconcile']
        self.assertTrue(hint['allowed'])
        args = {**hint['args_template'], 'manifest_confirmed': True,
                'workspace_clear': True, 'arm_clear': True, 'gripper_empty': True}
        owner.submit(self.identity('Boundary'), hint['grant_id'], 'reconcile', args, state['cursor'])
        self.owner_request('prepare_route', {'route_id': 'CF01ToNanoDrop', 'job_id': 'CF01.Out'})
        self.owner_request('dispatch', {'job_id': 'CF01.Out'})
        state, _ = self.root()
        self.assertEqual(state['transport']['jobs']['CF01.Out']['receipts'], {})
        self.assertIsNone(state['transport']['outbox']['CF01.Out']['claim'])
        self.transport_inventory = copy.deepcopy(state['inventory'])
        self.transport_bookings = copy.deepcopy(state['bookings'])
        for identity, vessel in state['inventory']['vessels'].items():
            for field in ['id', 'sample_id', 'content_revision', 'location']:
                self.assertEqual(vessel[field], self.initial_inventory['vessels'][identity][field])

    def statement(self, subject, role, request_id=None):
        client = self.client(subject); snapshot = client.snapshot()
        job = next(item for item in snapshot['jobs'] if item['job_id'] == 'CF01.Out')
        actions = [item for item in job['allowed_actions'] if item['operation'] == 'attest' and item['role'] == role]
        self.assertTrue(actions, (subject, role, job['allowed_actions']))
        args = {'job_id': job['job_id'], 'role': role, 'observation_id': self.identity('Observation'),
                'assignment_epoch': job['assignment_epoch'],
                'handover_id': job['pickup_handover_id'] if role.startswith('pickup') else job['delivery_handover_id'],
                'manifest_sha256': job['manifest_sha256'], 'observed_rack_id': job['rack_id'], 'confirmed': True}
        return client, request_id or self.identity(), actions[0]['grant_id'], args, snapshot['cursor']

    def attest(self, subject, role):
        client, request_id, grant, args, cursor = self.statement(subject, role)
        return client.submit(request_id, grant, 'attest', args, cursor)

    def test_four_authenticated_roles_apply_causally_and_preserve_existing_inventory(self):
        self.prepared()
        # Delivery before pickup is retained, but cannot release NanoDrop.
        self.attest('receiver', 'delivery_accept')
        source = self.statement('source', 'pickup_release')
        courier = self.statement('courier', 'pickup_accept')
        barrier = threading.Barrier(2)
        def concurrent_statement(statement):
            client, request, grant, args, cursor = statement
            barrier.wait(timeout=10)
            try:
                return client.submit(request, grant, 'attest', args, cursor)
            except TransportHTTPError as error:
                if error.status != 409 and not (error.status is None and error.code == 'ConnectionOrResponseFailure'):
                    raise
                return error
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(concurrent_statement, [source, courier]))
        # An independent CAS writer can reject one in-flight statement without
        # losing its intent. Read its durable receipt, then explicitly repeat
        # the same request only when no effect was committed.
        for index, result in enumerate(results):
            if isinstance(result, TransportHTTPError):
                client, request, grant, args, cursor = [source, courier][index]
                print(f'\nConcurrent request {request}: {result.code}; reading its own durable receipt.', flush=True)
                receipt = client.receipt(request, cursor)
                if receipt['receipt']:
                    print(f'Concurrent request {request}: committed receipt resolved the ambiguous response; no POST repeated.', flush=True)
                    results[index] = receipt
                else:
                    print(f'Concurrent request {request}: no receipt; explicitly repeating the same ID and unchanged arguments.', flush=True)
                    results[index] = client.submit(request, grant, 'attest', args, cursor)
        self.assertEqual({result['receipt']['request_id'] for result in results}, {source[1], courier[1]})
        state, _ = self.root()
        self.assertFalse(state['stages']['nanodrop']['rack_ready'])
        self.assertEqual(state['transport']['jobs']['CF01.Out']['phase'], 'delivery_pending')
        self.attest('courier', 'delivery_release')
        state, _ = self.root()
        self.assertTrue(state['stages']['nanodrop']['rack_ready'])
        self.assertEqual(state['transport']['jobs']['CF01.Out']['phase'], 'completed')
        self.assertEqual(state['inventory'], self.transport_inventory)
        self.assertEqual(state['bookings'], self.transport_bookings)
        self.assertEqual(remaining(state, 'Sample01'), 40)
        self.assertIsNone(remaining(state, 'Sample03'))
        self.assertNotIn('inventory', state['transport'])
        with Journal(self.store) as journal:
            flow = NetworkWorkflow(journal, RUN)
            report = flow.report()
            self.assertTrue(report['network_executed'])
            self.assertFalse(report['instrument_network_executed'])
            self.assertFalse(any(item.startswith('No network,') for item in report['limitations']))
            self.assertFalse(report['passed'])  # Analytical stages remain unexecuted.
            self.assertFalse(report['hardware_executed'])
            self.assertFalse(report['robot_motion_executed'])
            for record in state['transport']['requests'].values():
                context = record.get('request_context')
                if context is None: continue
                raw = journal.artifact(record['artifact_sha256'])
                self.assertEqual(digest(raw), context['wire_sha256'])
                self.assertNotIn(PASSWORD.encode(), raw)
                self.assertNotIn(b'Bearer', raw)
                self.assertEqual(context['transport_channel'], 'https')

    def test_false_role_and_principal_payload_cannot_mutate_the_owner(self):
        self.prepared()
        source, request, grant, args, cursor = self.statement('source', 'pickup_release')
        before = self.root()
        for role in ('pickup_accept', 'delivery_release', 'delivery_accept'):
            bad = {**args, 'role': role}
            with self.assertRaises(TransportHTTPError) as error:
                source.submit(self.identity(), grant, 'attest', bad, cursor)
            self.assertEqual(error.exception.status, 403)
            self.assertEqual(self.root(), before)
        with self.assertRaises(TransportHTTPError):
            source.submit(request, grant, 'attest', {**args, 'principal': 'SYN.Human.Courier'}, cursor)
        self.assertEqual(self.root(), before)
        with self.assertRaises(TransportHTTPError):
            source.submit(self.identity(), grant, 'attest', {**args, 'job_id': 'Wrong.Job'}, cursor)
        self.assertEqual(self.root(), before)
        observer = self.client('observer')
        with self.assertRaises(TransportHTTPError) as error:
            observer.submit(self.identity(), 'Grant.Observer', 'attest', args)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.root(), before)

    def test_account_bound_deduplication_survives_lost_reply_and_new_login(self):
        self.prepared()
        source, request, grant, args, cursor = self.statement('source', 'pickup_release')
        real = http._Handler._respond
        dropped = []
        def lose_body(handler, status, value, content_type='application/json; charset=utf-8'):
            if isinstance(value, dict) and value.get('receipt', {}).get('request_id') == request and not dropped:
                dropped.append(True)
                handler.close_connection = True
                try: handler.connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                handler.connection.close()
                return
            return real(handler, status, value, content_type)
        with patch.object(http._Handler, '_respond', new=lose_body):
            with self.assertRaises(TransportHTTPError): source.submit(request, grant, 'attest', args, cursor)
        self.assertTrue(dropped)
        committed, revision = self.root()
        original = copy.deepcopy(committed['transport']['requests'][request])
        source.logout(); self.clients.pop('source')
        reconnected = self.client('source')
        lookup = reconnected.receipt(request, cursor)
        self.assertEqual(lookup['receipt'], original)
        replay = reconnected.submit(request, grant, 'attest', args, cursor)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['receipt'], original)
        self.assertEqual(self.root()[1], revision)
        other_account = self.client('source2')  # Same domain principal/grant; distinct software subject.
        with self.assertRaises(TransportHTTPError) as error:
            other_account.submit(request, grant, 'attest', args, cursor)
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(TransportHTTPError) as error: other_account.receipt(request)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.root()[1], revision)
        with self.assertRaises(TransportHTTPError):
            reconnected.submit(request, grant, 'attest', {**args, 'observed_rack_id': 'OtherRack'}, cursor)
        self.assertEqual(self.root()[1], revision)

    def test_restart_does_not_dispatch_and_old_owner_intent_cannot_authorize_new_epoch(self):
        self.prepared()
        source, request, grant, args, cursor = self.statement('source', 'pickup_release')
        accepted = source.submit(request, grant, 'attest', args, cursor)
        owner = self.client('owner'); old = owner.snapshot()
        old_intent = {'boot_id': old['boot_id'], 'assignment_epoch': old['assignment_epoch'],
                      'job_id': 'CF01.Out', 'reason': 'Intent prepared before a different server boot'}
        before, revision = self.root()
        self.stop(); self.start(); self.clients = {}
        fresh_source = self.client('source')
        current = fresh_source.snapshot(cursor)
        self.assertNotEqual(current['boot_id'], old['boot_id'])
        self.assertFalse(current['write_session_available'])
        self.assertEqual(self.root()[1], revision, 'Boot must not resume or dispatch')
        replay = fresh_source.submit(request, grant, 'attest', args, cursor)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['receipt'], accepted['receipt'])
        self.assertEqual(self.root()[1], revision)
        self.owner_request('resume', {})
        held, after_resume = self.root()
        self.assertEqual(held['transport']['jobs']['CF01.Out']['control'], 'held')
        self.assertEqual(held['transport']['outbox']['CF01.Out']['status'], 'uncertain')
        with self.assertRaises(TransportHTTPError):
            self.client('owner').submit('Old.Owner.Intent', 'Grant.Owner', 'hold', old_intent)
        self.assertEqual(self.root()[1], after_resume)
        self.assertEqual(held['inventory'], before['inventory'])
        self.assertTrue({'rack:Rack', 'vessel:Tube01', 'agent:AgentHuman'} <= set(held['resources']))

    def test_wrong_manifest_is_retained_as_conflict_without_receiving_stage_release(self):
        self.prepared()
        source, request, grant, args, cursor = self.statement('source', 'pickup_release')
        result = source.submit(request, grant, 'attest', {**args, 'manifest_sha256': '0' * 64}, cursor)
        self.assertIsNotNone(result['receipt'])
        state, _ = self.root()
        self.assertEqual(state['transport']['jobs']['CF01.Out']['control'], 'held')
        self.assertFalse(state['stages']['nanodrop']['rack_ready'])
        self.assertTrue(any(entry['status'] == 'conflict' for entry in state['transport']['inbox'].values()))
        self.assertEqual(state['inventory'], self.transport_inventory)
        self.assertEqual(state['bookings'], self.transport_bookings)

    def test_logout_reconnect_and_independent_root_change_preserve_claims(self):
        self.prepared()
        source, request, grant, args, cursor = self.statement('source', 'pickup_release')
        state, revision = self.root()
        source.logout(); self.clients.pop('source')
        self.assertEqual(self.root(), (state, revision))
        with Journal(self.store) as journal:
            flow = NetworkWorkflow(journal, RUN, state['session'])
            flow.advance_time(OWNER, 0.1)
        fresh = self.client('source')
        result = fresh.submit(request, grant, 'attest', args, cursor)
        self.assertIsNotNone(result['receipt'])
        after, _ = self.root()
        self.assertEqual(after['logical_time_s'], state['logical_time_s'] + 0.1)
        self.assertIn('agent:AgentHuman', after['resources'])
        self.assertFalse(after['stages']['nanodrop']['rack_ready'])

    def test_rejected_workflow_observations_leave_no_partial_receipt_or_artifact(self):
        self.owner_request('resume', {})
        owner = self.client('owner'); snapshot = owner.snapshot()
        hint = snapshot['workflow_reconcile']
        self.assertTrue(hint['allowed'])
        args = {**hint['args_template'], 'manifest_confirmed': True,
                'workspace_clear': True, 'arm_clear': True, 'gripper_empty': True}
        args['observations'] = copy.deepcopy(args['observations'])
        args['observations'][0]['vessel_id'] = 'Wrong.Vessel'
        before = self.root()
        with Journal(self.store) as journal:
            artifacts = journal.connection.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0]
        request = self.identity('Invalid.Boundary')
        with self.assertRaises(TransportHTTPError):
            owner.submit(request, hint['grant_id'], 'reconcile', args, snapshot['cursor'])
        self.assertEqual(self.root(), before)
        self.assertIsNone(owner.receipt(request)['receipt'])
        with Journal(self.store) as journal:
            self.assertEqual(journal.connection.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0], artifacts)


if __name__ == '__main__':
    unittest.main()
