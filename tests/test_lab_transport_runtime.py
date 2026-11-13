"""T2 owner atomicity, replay, source fencing and interruption checks.

Each case starts from a copy of one fully journaled CF01 mock prefix. Copies
are isolated synthetic test worlds, never production stock continuation.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from async_transport_adapters import HumanTeleportMock
from cf01_rack_batch import BatchError
import lab_transport_workflow as runtime
from lab_transport_workflow import TransportWorkflow
from lab_workflow_ledger import remaining
from manual_tasks import Journal, TaskError

OWNER = 'SYN.Operator01'
RUN = 'SYN.T2.Runtime'


class LabTransportRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'exports').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='t2-runtime-', dir=ROOT / 'exports')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        cls.prefix = cls.folder / 'prefix.sqlite3'
        with Journal(cls.prefix) as journal:
            flow = TransportWorkflow.create(journal, run_id=RUN)
            flow.accept_rack(OWNER, flow.inventory_observations())
            for sample in flow.state['definition']['manifest']['samples']:
                flow.confirm_mass(OWNER, sample['vessel_id'], 2.0, 0)
            assert flow.run_cf01(OWNER)['passed']
            cls.session = flow.session

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.folder)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'workflow.sqlite3'
        shutil.copyfile(self.prefix, self.path)
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.flow = TransportWorkflow(self.journal, RUN, self.session)

    def prepare(self):
        return self.flow.prepare_transport(OWNER, 'CF01ToNanoDrop', 'CF01.Out', 'Prepare.1')

    def dispatch(self, adapter=None, request='Dispatch.1'):
        return self.flow.dispatch_transport('CF01.Out', adapter or HumanTeleportMock('AgentHuman'), OWNER, request)

    def test_create_is_unadmitted_and_read_only_open_does_not_take_session(self):
        path = Path(self.temp.name) / 'new.sqlite3'
        with Journal(path) as journal:
            flow = TransportWorkflow.create(journal, run_id='SYN.T2.New')
            state = flow.state
            self.assertFalse(state['transport_admitted'])
            self.assertEqual(state['resources'], [])
            self.assertEqual(journal.owners(), {})
            self.assertEqual(set(state['inventory']), {'vessels'})
            self.assertNotIn('inventory', state['transport'])
            count = len(journal.history(flow.run_id))
            reader = TransportWorkflow.open(journal, flow.run_id)
            self.assertIsNone(reader.session)
            self.assertEqual(len(journal.history(flow.run_id)), count)
            with self.assertRaises(TaskError): reader.advance_time(OWNER, 1)
            with self.assertRaises(TaskError): flow.prepare_transport(OWNER, 'CF01ToNanoDrop', 'Early', 'Early.1')

    def test_route_preparation_is_atomic_and_request_bound(self):
        before = self.flow.state
        record = self.prepare()
        after = self.flow.state
        self.assertEqual(record['operation'], 'prepare_route')
        self.assertEqual(after['inventory'], before['inventory'])
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertEqual(after['transport_bindings'], {'CF01ToNanoDrop': 'CF01.Out'})
        self.assertEqual(after['transport']['jobs']['CF01.Out']['phase'], 'pickup_pending')
        self.assertEqual(after['transport']['outbox']['CF01.Out']['status'], 'pending')
        revision = self.journal.get_current(RUN)[1]
        self.assertEqual(self.prepare(), record)
        self.assertEqual(self.journal.get_current(RUN)[1], revision)
        for principal, job in [('SYN.Other', 'CF01.Out'), (OWNER, 'Changed')]:
            with self.assertRaises(TaskError):
                self.flow.prepare_transport(principal, 'CF01ToNanoDrop', job, 'Prepare.1')
        self.assertEqual(self.flow.state, after)
        self.assertEqual(remaining(after, 'Sample01'), 40)
        self.assertIsNone(remaining(after, 'Sample03'))

    def test_prepare_route_rejects_unknown_fields_without_storing_a_request(self):
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.flow.transport_act('prepare_route', OWNER, 'Unexpected.Field',
                route_id='CF01ToNanoDrop', job_id='CF01.Out', extra='ignored')
        self.assertEqual(self.flow.state, before)

    def test_dispatch_commit_failure_does_not_call_worker_or_change_owner(self):
        self.prepare(); before = self.flow.state
        revision = self.journal.get_current(RUN)[1]
        adapter = Mock()
        with patch.object(self.journal, 'append', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): self.dispatch(adapter)
        adapter.submit.assert_not_called()
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.get_current(RUN)[1], revision)
        self.assertEqual({r for r, owner in self.journal.owners().items() if owner == RUN}, set(before['resources']))

    def test_failure_after_sql_receipt_insert_rolls_back_artifact_queue_and_custody(self):
        self.prepare(); batch = self.dispatch()['batch']
        before = self.flow.state
        revision = self.journal.get_current(RUN)[1]
        artifact_count = self.journal.connection.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0]
        real = self.journal._event
        def reject_after_insert(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError('synthetic SQL checkpoint failure')
        with patch.object(self.journal, '_event', side_effect=reject_after_insert):
            with self.assertRaises(RuntimeError): self.flow.ingest_transport([batch[1]])
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.get_current(RUN)[1], revision)
        self.assertEqual(self.journal.connection.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0], artifact_count)

    def test_dispatch_replay_never_resubmits_or_promotes_worker_output(self):
        self.prepare()
        worker = HumanTeleportMock('AgentHuman')
        adapter = Mock(wraps=worker)
        result = self.dispatch(adapter)
        self.assertEqual(self.flow.state['transport']['jobs']['CF01.Out']['phase'], 'pickup_pending')
        replay = self.dispatch(adapter)
        self.assertTrue(replay['replayed']); self.assertIsNone(replay['batch'])
        self.assertEqual(adapter.submit.call_count, 1)
        with self.assertRaises(TaskError): self.dispatch(adapter, 'Dispatch.Other')
        self.assertEqual(adapter.submit.call_count, 1)
        self.flow.ingest_transport(result['batch'])
        self.assertTrue(self.flow.state['stages']['nanodrop']['rack_ready'])

    def test_competing_root_commit_rejects_stale_receipt_without_losing_valid_message(self):
        self.prepare(); message = self.dispatch()['batch'][1]
        real_append = self.journal.append
        with Journal(self.path) as rival_journal:
            rival = TransportWorkflow(rival_journal, RUN, self.session)
            def competing_commit(*args, **kwargs):
                rival.advance_time(OWNER, 1)
                return real_append(*args, **kwargs)
            before = self.flow.state
            with patch.object(self.journal, 'append', side_effect=competing_commit):
                with self.assertRaisesRegex(TaskError, 'changed'):
                    self.flow.ingest_transport([message])
        state = self.flow.state
        self.assertEqual(state['logical_time_s'], before['logical_time_s'] + 1)
        self.assertEqual(state['transport'], before['transport'])
        self.assertNotIn(message['request_id'], state['transport']['requests'])
        self.flow.ingest_transport([message])
        self.assertIn(message['request_id'], self.flow.state['transport']['requests'])

    def test_visible_cancel_after_dispatch_commit_blocks_worker_invocation(self):
        self.prepare()
        adapter = Mock()
        original = self.flow._transport_transition
        def cancel_after_commit(operation, principal, request_id, args, artifact=None):
            result = original(operation, principal, request_id, args, artifact)
            if operation == 'mark_dispatched':
                other = TransportWorkflow(self.journal, RUN, self.session)
                other.transport_act('cancel', OWNER, 'Cancel.Race', job_id='CF01.Out', reason='synthetic cancellation')
            return result
        with patch.object(self.flow, '_transport_transition', side_effect=cancel_after_commit):
            with self.assertRaises(TaskError): self.dispatch(adapter)
        adapter.submit.assert_not_called()
        state = self.flow.state
        self.assertEqual(state['transport']['jobs']['CF01.Out']['control'], 'held')
        self.assertIn('agent:AgentHuman', state['resources'])

    def test_expired_root_deadline_blocks_dispatch_before_intent_and_adapter(self):
        self.prepare()
        self.flow.advance_time(OWNER, self.flow.state['deadline_s'])
        before = self.flow.state
        adapter = Mock()
        with self.assertRaisesRegex(TaskError, 'deadline'):
            self.dispatch(adapter)
        adapter.submit.assert_not_called()
        self.assertEqual(self.flow.state, before)
        self.assertEqual(before['transport']['outbox']['CF01.Out']['status'], 'pending')

    def test_deadline_crossing_after_committed_dispatch_blocks_worker(self):
        self.prepare()
        adapter = Mock()
        original = self.flow._transport_transition
        def expire_after_commit(operation, principal, request_id, args, artifact=None):
            result = original(operation, principal, request_id, args, artifact)
            if operation == 'mark_dispatched':
                self.flow.advance_time(OWNER, self.flow.state['deadline_s'])
            return result
        with patch.object(self.flow, '_transport_transition', side_effect=expire_after_commit):
            with self.assertRaisesRegex(TaskError, 'deadline'):
                self.dispatch(adapter)
        adapter.submit.assert_not_called()
        self.assertEqual(self.flow.state['transport']['outbox']['CF01.Out']['status'], 'dispatched')
        self.assertIn('agent:AgentHuman', self.flow.state['resources'])

    def test_source_change_after_dispatch_commit_blocks_worker(self):
        self.prepare()
        adapter = Mock()
        original_transition = self.flow._transport_transition
        original_verify = runtime.verify_sources
        changed = False
        def verify(definition):
            if changed:
                raise TaskError('synthetic source changed after intent')
            return original_verify(definition)
        def change_after_commit(operation, principal, request_id, args, artifact=None):
            nonlocal changed
            result = original_transition(operation, principal, request_id, args, artifact)
            if operation == 'mark_dispatched':
                changed = True
            return result
        with patch.object(runtime, 'verify_sources', side_effect=verify), \
                patch.object(self.flow, '_transport_transition', side_effect=change_after_commit):
            with self.assertRaisesRegex(TaskError, 'source changed'):
                self.dispatch(adapter)
        adapter.submit.assert_not_called()
        self.assertEqual(self.flow.state['transport']['outbox']['CF01.Out']['status'], 'dispatched')

    def test_explicit_cf01_restart_fences_owner_and_embedded_queue_together(self):
        path = Path(self.temp.name) / 'restart.sqlite3'
        with Journal(path) as journal:
            flow = TransportWorkflow.create(journal, run_id='SYN.T2.CF01.Restart')
            flow.accept_rack(OWNER, flow.inventory_observations())
            for sample in flow.state['definition']['manifest']['samples']:
                flow.confirm_mass(OWNER, sample['vessel_id'], 2.0, 0)
            def fail_first_command(runner):
                runner.bridge.dispatch = lambda *args, **kwargs: {'success': False}
            with self.assertRaises(BatchError):
                flow.run_cf01(OWNER, configure=fail_first_command)
            before = flow.state
            observations = [{'sample_id': s['sample_id'], 'vessel_id': s['vessel_id'],
                'location': {'kind': 'rack', 'rack_id': 'Rack', 'place_id': s['rack_place_id']}}
                for s in before['definition']['manifest']['samples']]
            flow.restart_cf01(OWNER, observations=observations, rotor_empty=list(range(1, 13)),
                gripper_empty=True, standstill_confirmed=True, parking_brake_held=True,
                lift_parked=True, arm_clear=True, workspace_clear=True, retire_attempt=True,
                reason='explicit synthetic retirement', expected_attempt_id=before['stages']['cf01']['attempt_id'])
            state = flow.state
            self.assertEqual(state['stages']['cf01']['status'], 'ready')
            self.assertNotEqual(state['session'], before['session'])
            self.assertEqual(state['transport']['session'], state['session'])
            self.assertEqual(state['transport']['assignment_epoch'], before['transport']['assignment_epoch'] + 1)
            self.assertEqual(state['transport']['jobs'], {})
            self.assertEqual(state['bookings'], {})

    def test_explicit_resume_fences_owner_and_queue_without_dispatch_replay(self):
        self.prepare(); self.dispatch()
        before = self.flow.state
        reopened = TransportWorkflow.open(self.journal, RUN, resume=True)
        state = reopened.state
        self.assertNotEqual(state['session'], before['session'])
        self.assertEqual(state['transport']['session'], state['session'])
        self.assertEqual(state['transport']['assignment_epoch'], before['transport']['assignment_epoch'] + 1)
        self.assertEqual(state['transport']['jobs']['CF01.Out']['control'], 'held')
        self.assertEqual(state['transport']['outbox']['CF01.Out']['status'], 'uncertain')
        self.assertEqual(state['inventory'], before['inventory'])
        self.assertEqual(state['resources'], before['resources'])
        with self.assertRaises(TaskError): self.flow.advance_time(OWNER, 1)
        adapter = Mock()
        with self.assertRaises(TaskError): reopened.dispatch_transport('CF01.Out', adapter, OWNER, 'AfterRestart.Dispatch')
        adapter.submit.assert_not_called()

    def test_hard_exit_after_committed_dispatch_is_held_on_restart(self):
        self.prepare()
        code = '''
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'scripts'))
from manual_tasks import Journal
from lab_transport_workflow import TransportWorkflow
class ExitWorker:
 def submit(self,envelope): os._exit(73)
with Journal(Path(sys.argv[1])) as journal:
 flow=TransportWorkflow(journal,'SYN.T2.Runtime',sys.argv[2])
 flow.dispatch_transport('CF01.Out',ExitWorker(),'SYN.Operator01','Crash.Dispatch')
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.path), self.session], cwd=ROOT)
        self.assertEqual(result.returncode, 73)
        state = self.flow.state
        self.assertEqual(state['transport']['outbox']['CF01.Out']['status'], 'dispatched')
        self.assertIn('Crash.Dispatch', state['transport']['requests'])
        reopened = TransportWorkflow.open(self.journal, RUN, resume=True)
        self.assertEqual(reopened.state['transport']['jobs']['CF01.Out']['control'], 'held')
        self.assertIn('agent:AgentHuman', reopened.state['resources'])
        self.assertEqual(reopened.state['bookings'], {})

    def test_second_owner_cannot_admit_the_same_existing_rack(self):
        other = TransportWorkflow.create(self.journal, run_id='SYN.T2.DuplicateOwner')
        before = other.state
        with self.assertRaises(TaskError): other.accept_rack(OWNER, other.inventory_observations())
        self.assertEqual(other.state, before)
        self.assertFalse(other.state['transport_admitted'])
        self.assertEqual(other.state['resources'], [])
        self.assertTrue(all(owner == RUN for owner in self.journal.owners().values()))

    def test_source_drift_blocks_mutations_and_report(self):
        before = self.flow.state
        original = Path.read_bytes
        def altered(path):
            data = original(path)
            return data + b'\n# synthetic drift\n' if path.resolve() == (ROOT / 'scripts/lab_transport_workflow.py').resolve() else data
        with patch.object(Path, 'read_bytes', altered):
            with self.assertRaisesRegex(TaskError, 'source changed'): self.flow.advance_time(OWNER, 1)
            with self.assertRaisesRegex(TaskError, 'source changed'): self.flow.report()
        self.assertEqual(self.flow.state, before)

    def test_corrupt_transport_batch_artifact_prevents_report(self):
        self.prepare(); batch = self.dispatch()['batch']
        self.flow.ingest_transport(batch)
        record = self.flow.state['transport']['requests'][batch[1]['request_id']]
        self.journal.connection.execute('UPDATE artifacts SET content=? WHERE sha256=?',
                                        (b'synthetic corrupt artifact', record['artifact_sha256']))
        with self.assertRaises(TaskError): self.flow.report()

    def test_cancelled_reconciled_route_cannot_be_replaced_or_count_as_success(self):
        self.prepare(); self.dispatch()
        self.flow.transport_act('cancel', OWNER, 'Cancel.1', job_id='CF01.Out', reason='synthetic abort')
        self.flow.transport_act('reconcile', OWNER, 'Reconcile.1', job_id='CF01.Out', outcome='not_performed',
                                location={'kind': 'endpoint', 'endpoint_id': 'LabA.CF01'},
                                manifest=self.flow.transport_manifests()['Rack'], reason='explicit synthetic source observation')
        self.assertEqual(self.flow.state['transport']['jobs']['CF01.Out']['phase'], 'cancelled_reconciled')
        with self.assertRaises(TaskError):
            self.flow.prepare_transport(OWNER, 'CF01ToNanoDrop', 'Retry', 'Prepare.Retry')
        self.assertFalse(self.flow.report()['transport_passed'])
        self.assertFalse(self.flow.state['stages']['nanodrop']['rack_ready'])


if __name__ == '__main__':
    unittest.main()
