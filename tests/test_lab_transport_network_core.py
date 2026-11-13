"""T3 authority, wire-receipt and restart rules without claiming network I/O."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import async_transport_domain as domain
from lab_transport_access import AuthError, credential
from lab_transport_network import CoreError, NetworkWorkflow, Service
from manual_tasks import Journal, TaskError, encoded


class NetworkCoreTests(unittest.TestCase):
    RUN = 'SYN.T3.Core'
    PASSWORD = 'SYN.Only.Core.Fixture.Password'

    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='lab-transport-network-core-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'workflows.sqlite3'
        with Journal(self.store) as journal:
            flow = NetworkWorkflow.create(journal, run_id=self.RUN)
            self.server_uuid = flow.state['network']['server_uuid']
            flow.close()
        self.users = [credential('owner', self.PASSWORD, 'SYN.Operator01',
                                 [{'id': 'Owner', 'kind': 'owner', 'resource_id': self.RUN}]),
                      credential('another-owner', self.PASSWORD, 'SYN.Operator01',
                                 [{'id': 'Owner', 'kind': 'owner', 'resource_id': self.RUN}]),
                      credential('observer', self.PASSWORD, 'SYN.Reader01',
                                 [{'id': 'Observe', 'kind': 'observer', 'resource_id': self.RUN}]),
                      credential('courier', self.PASSWORD, 'SYN.Human.Courier',
                                 [{'id': 'Courier', 'kind': 'agent', 'resource_id': 'AgentHuman'}])]
        (self.directory / 'service.json').write_text(json.dumps({
            'format': 'solidcraftbot.lab-transport-service/1', 'store': str(self.store),
            'run_id': self.RUN, 'server_uuid': self.server_uuid}))
        (self.directory / 'users.json').write_text(json.dumps({
            'format': 'solidcraftbot.lab-transport-users/1', 'users': self.users}))
        for name in ['service.json', 'users.json']:
            (self.directory / name).chmod(0o600)
        self.service = Service(self.directory)
        self.addCleanup(lambda: self.service.close())
        self.counter = 0

    def account(self, name='owner'):
        token = self.service.access.login(name, self.PASSWORD, self.server_uuid)['access_token']
        return self.service.access.authorize(token)

    def snapshot(self, context):
        return self.service.snapshot(context, self.RUN)

    def post(self, context, operation, args=None, request_id=None, grant_id='Owner', raw=None):
        self.counter += 1
        request_id = request_id or 'SYN.Request.%03d' % self.counter
        if args is None:
            state = self.snapshot(context)
            args = {'boot_id': state['boot_id'], 'assignment_epoch': state['assignment_epoch']}
        body = {'request_id': request_id, 'grant_id': grant_id, 'operation': operation, 'args': args}
        wire = encoded(body).encode() if raw is None else raw
        return self.service.request(context, self.RUN, request_id, operation, args, wire, grant_id=grant_id)

    def test_readonly_boot_login_and_snapshot_never_resume_or_mutate_root(self):
        with Journal(self.store) as journal: before = journal.history(self.RUN)
        context = self.account()
        snapshot = self.snapshot(context)
        self.assertFalse(snapshot['write_session_available'])
        self.assertEqual(snapshot['assignment_epoch'], 1)
        self.assertIsInstance(snapshot['cursor'], dict)
        with Journal(self.store) as journal: self.assertEqual(journal.history(self.RUN), before)

    def test_resume_request_receipt_is_atomic_subject_bound_and_idempotent(self):
        owner = self.account(); first = self.post(owner, 'resume', request_id='Resume.One')
        with Journal(self.store) as journal:
            before = journal.history(self.RUN)
            record = journal.get_current(self.RUN)[0]['transport']['requests']['Resume.One']
            self.assertEqual(record['request_context']['subject'], 'owner')
            self.assertEqual(journal.artifact(record['artifact_sha256']), encoded({
                'request_id': 'Resume.One', 'grant_id': 'Owner', 'operation': 'resume',
                'args': {'boot_id': first['snapshot']['boot_id'], 'assignment_epoch': 1}}).encode())
        args = {'boot_id': first['snapshot']['boot_id'], 'assignment_epoch': 1}
        second = self.post(self.account(), 'resume', args, request_id='Resume.One')
        self.assertTrue(second['replayed'])
        self.assertEqual(first['receipt'], second['receipt'])
        with Journal(self.store) as journal: self.assertEqual(journal.history(self.RUN), before)
        with self.assertRaises(CoreError) as rejected:
            self.post(self.account('another-owner'), 'resume', args, request_id='Resume.One')
        self.assertEqual(rejected.exception.code, 'request_conflict')

    def test_restart_returns_saved_reply_readonly_and_never_takes_owner_session(self):
        owner = self.account(); old = self.snapshot(owner)
        args = {'boot_id': old['boot_id'], 'assignment_epoch': old['assignment_epoch']}
        first = self.post(owner, 'resume', args, request_id='Resume.BeforeRestart')
        self.service.close()
        self.service = Service(self.directory)
        new_owner = self.account()
        self.assertFalse(self.snapshot(new_owner)['write_session_available'])
        replay = self.post(new_owner, 'resume', args, request_id='Resume.BeforeRestart')
        self.assertTrue(replay['replayed']); self.assertEqual(first['receipt'], replay['receipt'])
        self.assertFalse(replay['snapshot']['write_session_available'])
        with self.assertRaises(CoreError) as rejected:
            self.post(new_owner, 'resume', args, request_id='New.OldBoot')
        self.assertEqual(rejected.exception.code, 'stale_owner_context')

    def test_changed_wire_bytes_are_not_a_duplicate_even_with_same_arguments(self):
        owner = self.account(); state = self.snapshot(owner)
        args = {'boot_id': state['boot_id'], 'assignment_epoch': state['assignment_epoch']}
        self.post(owner, 'resume', args, request_id='Same.Wire')
        raw = json.dumps({'request_id': 'Same.Wire', 'grant_id': 'Owner',
                          'operation': 'resume', 'args': args}, indent=2).encode()
        with self.assertRaises(CoreError) as rejected:
            self.post(owner, 'resume', args, request_id='Same.Wire', raw=raw)
        self.assertEqual(rejected.exception.code, 'request_conflict')

    def test_owner_epoch_is_rechecked_after_an_interleaved_resume(self):
        owner = self.account(); original = NetworkWorkflow.resume_network
        raced = False
        def interleave(flow, *args, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                self.post(owner, 'resume', request_id='Concurrent.Resume')
            return original(flow, *args, **kwargs)
        with patch.object(NetworkWorkflow, 'resume_network', interleave):
            with self.assertRaises(CoreError) as rejected:
                self.post(owner, 'resume', request_id='Stale.Resume')
        self.assertEqual(rejected.exception.code, 'stale_owner_context')
        with Journal(self.store) as journal:
            state = journal.get_current(self.RUN)[0]
        self.assertEqual(state['transport']['assignment_epoch'], 2)
        self.assertIn('Concurrent.Resume', state['transport']['requests'])
        self.assertNotIn('Stale.Resume', state['transport']['requests'])

    def test_raced_resume_receipt_never_adopts_a_later_external_owner_session(self):
        owner = self.account(); original = NetworkWorkflow.resume_network
        raced = False
        outsider_session = None
        def interleave(flow, *args, **kwargs):
            nonlocal raced, outsider_session
            if not raced:
                raced = True
                # Another request commits the identical intent. Before this
                # caller notices its receipt, a new local owner fences it.
                original(flow, *args, **kwargs)
                with Journal(self.store) as other:
                    outsider = NetworkWorkflow.open(other, self.RUN, resume=True)
                    outsider_session = outsider.session
            return original(flow, *args, **kwargs)
        with patch.object(NetworkWorkflow, 'resume_network', interleave):
            result = self.post(owner, 'resume', request_id='Raced.Resume')
        self.assertTrue(result['replayed'])
        self.assertFalse(result['snapshot']['write_session_available'])
        self.assertIsNone(self.service._write_session)
        with Journal(self.store) as journal:
            state = journal.get_current(self.RUN)[0]
        self.assertEqual(state['session'], outsider_session)
        self.assertEqual(state['transport']['assignment_epoch'], 3)
        self.assertEqual(list(state['transport']['requests']), ['Raced.Resume'])

    def test_observer_cannot_perform_owner_effect_or_read_another_accounts_receipt(self):
        owner = self.account(); self.post(owner, 'resume', request_id='Owner.Resume')
        observer = self.account('observer')
        with self.assertRaises(CoreError) as rejected:
            self.post(observer, 'resume', grant_id='Observe')
        self.assertEqual(rejected.exception.status, 403)
        with self.assertRaises(CoreError) as rejected:
            self.service.receipt(observer, self.RUN, 'Owner.Resume')
        self.assertEqual(rejected.exception.status, 403)

    def test_payload_context_and_grant_forgery_cannot_replace_authentication(self):
        owner = self.account(); forged = dict(owner)
        with self.assertRaises(AuthError): self.snapshot(forged)
        owner['grants'][0]['resource_id'] = 'Other.Run'
        with self.assertRaises(AuthError): self.snapshot(owner)

    def test_cursor_rejects_rollback_foreign_run_and_forged_history_hash(self):
        owner = self.account(); cursor = self.snapshot(owner)['cursor']
        for key, value in [('sha256', '0' * 64), ('run_id', 'Other.Run'), ('sequence', 999999)]:
            bad = copy.deepcopy(cursor); bad[key] = value
            with self.assertRaises(CoreError) as rejected:
                self.service.snapshot(owner, self.RUN, cursor=bad)
            self.assertEqual(rejected.exception.code, 'cursor_mismatch')

    def test_failed_resume_append_preserves_epoch_session_artifact_and_receipt(self):
        owner = self.account()
        with Journal(self.store) as journal: before = journal.history(self.RUN)
        with patch.object(Journal, 'append', side_effect=TaskError('SYN injected storage failure')):
            with self.assertRaises(CoreError): self.post(owner, 'resume', request_id='Failed.Resume')
        with Journal(self.store) as journal: self.assertEqual(journal.history(self.RUN), before)
        self.assertIsNone(self.service.receipt(owner, self.RUN, 'Failed.Resume')['receipt'])
        self.assertFalse(self.snapshot(owner)['write_session_available'])

    def test_in_process_authenticated_commands_do_not_claim_actual_network_execution(self):
        owner = self.account(); self.post(owner, 'resume')
        with Journal(self.store) as journal:
            report = NetworkWorkflow(journal, self.RUN).report()
        self.assertFalse(report['network_executed'])
        self.assertFalse(report['transport_network_executed'])
        self.assertFalse(report['hardware_executed'])
        self.assertIn('No instrument-network execution, hardware, new CAD geometry or executed robot paths',
                      report['limitations'])
        self.assertNotIn('No network, hardware, new CAD geometry or executed robot paths', report['limitations'])

    def test_manual_boundary_availability_does_not_reopen_cancelled_or_started_work(self):
        with Journal(self.store) as journal:
            state = journal.get_current(self.RUN)[0]
        # Detached capability projection only: this is not a fabricated device
        # execution or a persisted continuation fixture.
        state.update(active_stage='nanodrop', status='held', recovery_required='session_restarted')
        stage = state['stages']['nanodrop']
        stage.update(status='waiting_transport', recovery_required='session_restarted')
        self.assertTrue(NetworkWorkflow.workflow_reconcile_available(state))
        for status in ['cancelling', 'completed', 'running']:
            state['status'] = status
            self.assertFalse(NetworkWorkflow.workflow_reconcile_available(state))
        state['status'] = 'held'
        for status in ['working', 'completed', 'cancelling']:
            stage['status'] = status
            self.assertFalse(NetworkWorkflow.workflow_reconcile_available(state))

    def test_dispatch_hint_requires_the_existing_owner_and_domain_gates(self):
        with Journal(self.store) as journal:
            flow = NetworkWorkflow.open(journal, self.RUN, resume=True)
            flow.accept_rack('SYN.Operator01', flow.inventory_observations())
            state = flow.state
            flow.close()
        # A detached, valid queue proposal exercises dispatch capability only.
        # It does not invent a successful CF01 stage or persist a route bypass.
        topology = NetworkWorkflow._topology(state)
        manifests = NetworkWorkflow._manifests(state)
        owner = topology['owner_principal']; job_id = 'Capability.Job'
        for operation, args in [
            ('request', {'job_id': job_id, 'rack_id': state['definition']['rack_instance'],
                         'target_endpoint': 'LabB.NanoDrop', 'agent_id': 'AgentHuman'}),
            ('reserve', {'job_id': job_id}), ('prepare', {'job_id': job_id}),
        ]:
            state['transport'] = domain.embedded_apply(state['transport'], operation, args,
                                                       owner, topology, manifests)
        self.assertTrue(NetworkWorkflow.dispatch_available(state, job_id))
        for operation in ['hold', 'cancel']:
            blocked = copy.deepcopy(state)
            blocked['transport'] = domain.embedded_apply(state['transport'], operation,
                {'job_id': job_id, 'reason': 'Explicit synthetic dispatch gate'}, owner, topology, manifests)
            self.assertFalse(NetworkWorkflow.dispatch_available(blocked, job_id))
        for changes in [{'status': 'held'}, {'status': 'cancelling'},
                        {'recovery_required': 'session_restarted'},
                        {'logical_time_s': state['deadline_s']}]:
            blocked = {**state, **changes}
            self.assertFalse(NetworkWorkflow.dispatch_available(blocked, job_id))

    def test_service_binding_rejects_another_root_identity(self):
        self.service.close()
        config = json.loads((self.directory / 'service.json').read_text())
        config['server_uuid'] = '00000000-0000-4000-8000-000000000099'
        (self.directory / 'service.json').write_text(json.dumps(config))
        with self.assertRaises(TaskError): Service(self.directory)


if __name__ == '__main__':
    unittest.main()
