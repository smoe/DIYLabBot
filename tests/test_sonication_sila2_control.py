"""Offline Root invariants; these tests do not claim a SiLA network run."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from cutrun_input_sonication_control import MODE, NetworkInputSonicationWorkflow
from cutrun_input_sonication_demo import FixtureClock, FixtureSession
from cutrun_input_sonication_workflow import InputSonicationWorkflow
from manual_tasks import Journal, TaskError, digest, encoded


class SonicationControlTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='s09-control-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.journal = Journal(self.directory / 'journal.sqlite3')
        self.addCleanup(self.journal.close)
        self.control = {'mode': MODE, 'server_uuid': 'test.s09.server',
            'source_files_sha256': {'scripts/cutrun_input_sonication_control.py':
                digest((ROOT / 'scripts/cutrun_input_sonication_control.py').read_bytes())}}
        self.context = self.context_for('CreateRun', 'create')
        self.fixture = FixtureSession(self.journal, 'TEST.S09.NetworkControl', self.directory,
            workflow_class=NetworkInputSonicationWorkflow,
            workflow_options={'control': self.control, 'command_context': self.context})

    def context_for(self, command, request, *, boot='test.boot.1', principal='network.principal', **arguments):
        args = {'request_identifier': request, 'run_identifier': 'TEST.S09.NetworkControl', **arguments}
        return {'request_id': request, 'command': command, 'arguments': args,
            'fingerprint': digest(encoded({'command': command, 'arguments': args}).encode()),
            'principal': principal, 'server_uuid': 'test.s09.server', 'boot_id': boot,
            'execution_uuid': 'execution.' + request, 'clock': lambda: 1000.0,
            'transport': 'in_process'}

    @property
    def flow(self):
        return self.fixture.flow

    def snapshot(self):
        return {'state': self.flow.state,
            'events': self.journal.connection.execute(
                'SELECT sequence, document, sha256 FROM events ORDER BY run_id, sequence').fetchall(),
            'owners': self.journal.owners()}

    def finish_create(self):
        self.flow.finish_command({'created': self.flow.run_id})

    def command(self, command='RecordObservation', request='record', **arguments):
        self.flow.command_context = self.context_for(command, request, **arguments)

    def reopen(self, *, guard=None, clock=None, context=None):
        return NetworkInputSonicationWorkflow.open(self.journal, self.flow.run_id, resume=True,
            clock=clock or self.fixture.clock,
            command_context=context or self.context_for('ResumeRun', 'resume', boot='test.boot.2'),
            transition_guard=guard)

    def test_creation_effect_receipt_and_material_introduction_share_first_event(self):
        first = self.journal.history(self.flow.run_id)[0]
        state = first['state']
        self.assertEqual(first['kind'], 'created')
        self.assertEqual(state['control'], self.control)
        self.assertTrue(state['inventory']['materials'])
        self.assertTrue(state['resources'])
        command = state['network']['commands']['create']
        self.assertEqual(command['confirmation_event_sequence'], 1)
        self.assertEqual(command['status'], 'accepted')
        receipt = state['creation_receipt']['network_receipt']
        self.assertEqual(receipt['principal'], 'network.principal')
        self.assertEqual(receipt['evidence'], 'network_receipt')
        self.assertIsNone(state['actor_id'])

    def test_create_guard_denial_introduces_no_root_inventory_or_reservations(self):
        journal = Journal(self.directory / 'denied.sqlite3')
        self.addCleanup(journal.close)
        before = list(journal.connection.iterdump())
        def denied():
            raise PermissionError('Lease expired before creation')
        with self.assertRaises(PermissionError):
            FixtureSession(journal, 'TEST.S09.Denied', self.directory / 'denied',
                workflow_class=NetworkInputSonicationWorkflow,
                workflow_options={'control': self.control, 'command_context': self.context_for(
                                      'CreateRun', 'create', run_identifier='TEST.S09.Denied'),
                                  'transition_guard': denied})
        self.assertEqual(list(journal.connection.iterdump()), before)

    def test_create_storage_failure_rolls_back_receipt_inventory_and_holds(self):
        journal = Journal(self.directory / 'failed-create.sqlite3')
        self.addCleanup(journal.close)
        before = list(journal.connection.iterdump())
        with patch.object(journal, '_event', side_effect=TaskError('Injected event storage failure')):
            with self.assertRaisesRegex(TaskError, 'storage failure'):
                FixtureSession(journal, 'TEST.S09.FailedCreate', self.directory / 'failed-create',
                    workflow_class=NetworkInputSonicationWorkflow,
                    workflow_options={'control': self.control, 'command_context': self.context_for(
                        'CreateRun', 'create', run_identifier='TEST.S09.FailedCreate')})
        self.assertEqual(list(journal.connection.iterdump()), before)

    def test_domain_receipt_keeps_principal_separate_from_fixture_actor_and_provenance(self):
        self.finish_create()
        self.command()
        self.fixture.act('record_observation', stage_id='S09', reaction_id=self.fixture.reaction_id,
                         status='observed', details={'fixture_only': True})
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertEqual(event['payload']['actor_id'], self.fixture.actor)
        self.assertEqual(event['payload']['evidence'], 'test_fixture')
        self.assertEqual(event['payload']['observation']['source_kind'], 'test_fixture')
        self.assertNotEqual(event['payload']['actor_id'], 'network.principal')
        self.assertEqual(event['payload']['network_receipt']['principal'], 'network.principal')
        record = self.flow.state['manual']['stage_observations'][-1]
        self.assertEqual(record['actor_id'], self.fixture.actor)
        self.assertEqual(record['evidence'], 'test_fixture')
        self.assertNotIn('principal', record)

    def test_payload_cannot_impersonate_system_identity_or_evidence(self):
        self.finish_create()
        self.command('ControllerObservation', 'controller')
        self.flow.control_event('controller_observation', lambda state: None,
            {'actor_id': 'forged.actor', 'evidence': 'device_export',
             'network_receipt': {'principal': 'forged.principal'}, 'detail': 'preserved'})
        payload = self.journal.history(self.flow.run_id)[-1]['payload']
        self.assertEqual(payload['actor_id'], self.fixture.actor)
        self.assertEqual(payload['evidence'], 'network_receipt')
        self.assertEqual(payload['network_receipt']['principal'], 'network.principal')
        self.assertEqual(payload['detail'], 'preserved')

    def test_domain_guard_runs_before_any_effect_and_receipt_is_not_committed(self):
        self.finish_create()
        self.command('CancelRun', 'denied')
        def denied():
            raise PermissionError('Lease expired')
        self.flow.transition_guard = denied
        before = self.snapshot()
        with self.assertRaises(PermissionError):
            self.fixture.act('cancel', reason='Denied request')
        self.assertEqual(self.snapshot(), before)

    def test_failed_append_does_not_leave_an_acceptance_without_its_effect(self):
        self.finish_create()
        self.command('CancelRun', 'storage-failed')
        before = self.snapshot()
        original = self.journal._event
        def fail(*args, **kwargs):
            if args[3] == 'cancel':
                raise TaskError('Injected storage failure')
            return original(*args, **kwargs)
        with patch.object(self.journal, '_event', side_effect=fail):
            with self.assertRaisesRegex(TaskError, 'storage failure'):
                self.fixture.act('cancel', reason='Fixture cancellation')
        self.assertEqual(self.snapshot(), before)

    def test_first_domain_effect_and_receipt_are_in_the_same_confirmation_event(self):
        self.fixture.prepare_input(); self.fixture.begin()
        self.finish_create()
        self.command('ConfirmSonication', 'confirm')
        before = self.snapshot()
        self.fixture.confirm()
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertEqual(len(self.snapshot()['events']), len(before['events']) + 1)
        self.assertEqual(event['kind'], 'confirm_sonication')
        self.assertEqual(event['state']['bookings'][self.fixture.intent_id]['outcome'], 'performed')
        self.assertIn(self.fixture.output_material_id, event['state']['inventory']['materials'])
        self.assertEqual(event['state']['network']['commands']['confirm']['confirmation_event_sequence'],
                         event['sequence'])
        self.assertEqual(event['payload']['evidence'], 'test_fixture')
        self.assertEqual(event['payload']['network_receipt']['request_id'], 'confirm')

    def test_rejected_observation_keeps_first_receipt_with_its_root_hold(self):
        self.finish_create()
        self.command('ConfirmInventory', 'bad-inventory')
        before = self.snapshot()
        observations = self.flow.inventory_observations()
        observations[0]['material_ids'] = ['foreign.material']
        with self.assertRaises(TaskError):
            self.fixture.act('confirm_inventory', observations=observations)
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertEqual(event['kind'], 'observation_rejected')
        self.assertEqual(event['state']['inventory'], before['state']['inventory'])
        self.assertEqual(event['state']['recovery_required'], 'observation_mismatch')
        self.assertEqual(event['state']['network']['commands']['bad-inventory']['status'], 'accepted')
        self.assertEqual(event['payload']['network_receipt']['request_id'], 'bad-inventory')

    def test_controller_update_cannot_rebind_the_existing_root(self):
        self.finish_create()
        self.command('ControllerObservation', 'rebind')
        before = self.snapshot()
        def rebind(state):
            state['control']['server_uuid'] = 'forged.server'
        with self.assertRaisesRegex(TaskError, 'immutable'):
            self.flow.control_event('rebound', rebind)
        self.assertEqual(self.snapshot(), before)

    def test_command_completion_is_correlated_even_when_observation_is_a_noop(self):
        self.finish_create()
        self.command('CancelRun', 'first-cancel')
        envelope = self.fixture.envelope('TEST.S09.Stable.Cancel')
        self.fixture.act('cancel', observation=envelope, reason='Fixture cancellation')
        self.flow.finish_command({'cancel_requested': True})
        self.command('CancelRun', 'noop-cancel')
        before = self.snapshot()
        self.fixture.act('cancel', observation=envelope, reason='Fixture cancellation')
        self.assertEqual(self.snapshot(), before)
        self.flow.finish_command({'cancel_requested': True})
        after = self.snapshot()
        self.assertEqual(after['state']['inventory'], before['state']['inventory'])
        self.assertEqual(len(after['events']), len(before['events']) + 1)
        self.assertEqual(after['state']['network']['commands']['noop-cancel']['status'], 'completed')
        payload = self.journal.history(self.flow.run_id)[-1]['payload']
        self.assertEqual(payload['network_receipt']['request_id'], 'noop-cancel')

    def test_trusted_interruption_can_finish_receipt_without_repeating_effect(self):
        self.finish_create()
        self.command('CancelRun', 'interrupt')
        self.fixture.act('cancel', reason='Fixture cancellation')
        before = self.flow.state
        def denied():
            raise PermissionError('Lease expired after effect')
        self.flow.transition_guard = denied
        with self.assertRaises(PermissionError):
            self.flow.control_event('untrusted_event', lambda state: state.update(workspace_clear=True))
        self.flow.control_event('execution_interrupted', lambda state: state.update(recovery_required='network_interrupted'),
                                {'reason': 'Lease expired'}, trusted=True)
        self.flow.finish_command({'outcome': 'uncertain'}, outcome='uncertain', error='ReconciliationRequired')
        after = self.flow.state
        for name in ('inventory', 'bookings', 'resources', 'cancel_reason'):
            self.assertEqual(after[name], before[name])
        self.assertEqual(after['network']['commands']['interrupt']['status'], 'uncertain')

    def test_terminal_lifecycle_allows_only_its_correlated_command_completion(self):
        self.finish_create()
        self.command('CancelRun', 'cancel')
        self.fixture.act('cancel', reason='Fixture cancellation')
        self.flow.finish_command({'cancel_requested': True})
        self.command('FinishCancel', 'finish-cancel')
        for identity in self.flow.state['inventory']['materials']:
            self.fixture.act('set_disposition', material_id=identity, disposition='retained',
                             reason='Explicit fixture material retention')
        self.fixture.reconcile()
        self.fixture.act('finish_cancel', workspace_clear=True)
        before = self.snapshot()
        self.assertEqual(before['state']['status'], 'cancelled')
        self.assertIsNone(before['state']['session'])
        self.assertEqual(before['owners'], {})
        with self.assertRaisesRegex(TaskError, '(?i)stale'):
            self.flow.control_event('command_finished', lambda state: None, trusted=True)
        stale = NetworkInputSonicationWorkflow(self.journal, self.flow.run_id, 'foreign-session',
            clock=self.fixture.clock, command_context=self.flow.command_context)
        with self.assertRaisesRegex(TaskError, '(?i)stale terminal'):
            stale.finish_command({'forged': True})
        reader = NetworkInputSonicationWorkflow(self.journal, self.flow.run_id, None,
            command_context=self.flow.command_context)
        with self.assertRaisesRegex(TaskError, '(?i)stale terminal'):
            reader.finish_command({'forged': True})
        self.assertEqual(self.snapshot(), before)
        self.flow.finish_command({'cancelled': True})
        after = self.snapshot()
        self.assertEqual(len(after['events']), len(before['events']) + 1)
        self.assertEqual(after['state']['network']['commands']['finish-cancel']['status'], 'completed')
        for name in ('inventory', 'bookings', 'resources', 'status', 'session'):
            self.assertEqual(after['state'][name], before['state'][name])
        with self.assertRaisesRegex(TaskError, 'already finished'):
            self.flow.finish_command({'cancelled': True})
        self.assertEqual(self.snapshot(), after)

    def test_root_legacy_class_cannot_write_resume_or_close_bound_run_but_can_read(self):
        before = self.snapshot()
        legacy = InputSonicationWorkflow(self.journal, self.flow.run_id, self.flow.session,
                                        clock=self.fixture.clock)
        self.assertEqual(legacy.report()['run_id'], self.flow.run_id)
        with self.assertRaisesRegex(TaskError, 'SiLA server'):
            legacy.act('cancel', self.fixture.actor, observation=self.fixture.envelope(), reason='Legacy bypass')
        with self.assertRaisesRegex(TaskError, 'SiLA server'):
            InputSonicationWorkflow.open(self.journal, self.flow.run_id, resume=True, clock=self.fixture.clock)
        with self.assertRaisesRegex(TaskError, 'SiLA server'):
            legacy.close()
        self.assertEqual(self.snapshot(), before)

    def test_local_cli_report_reads_and_resume_cannot_bypass_root_binding(self):
        prefix = [sys.executable, '-B', str(ROOT / 'scripts/run_cutrun_input_sonication.py'),
                  '--store', str(self.journal.path)]
        reader = subprocess.run([*prefix, 'report', self.flow.run_id], text=True, capture_output=True)
        self.assertEqual(reader.returncode, 0, reader.stderr)
        clock = self.directory / 'clock.json'
        clock.write_text(encoded(self.fixture.clock.record))
        before = self.snapshot()
        writer = subprocess.run([*prefix, 'resume', self.flow.run_id, '--clock', str(clock)],
                                text=True, capture_output=True)
        self.assertNotEqual(writer.returncode, 0)
        self.assertIn('SiLA server', writer.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_reused_request_changed_context_and_bad_fingerprint_have_no_event(self):
        before = self.snapshot()
        for field, value in [('principal', 'other.principal'), ('command', 'CancelRun'),
                             ('execution_uuid', 'other.execution'), ('fingerprint', '0' * 64)]:
            with self.subTest(field=field):
                self.flow.command_context = {**self.context, field: value}
                if field == 'command':
                    self.flow.command_context['fingerprint'] = digest(encoded({
                        'command': value, 'arguments': self.context['arguments']}).encode())
                with self.assertRaises(TaskError):
                    self.fixture.act('cancel', reason='Conflicting request')
                self.assertEqual(self.snapshot(), before)

    def test_finished_request_cannot_be_redispatched_through_engine(self):
        self.finish_create()
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'already finished'):
            self.fixture.act('cancel', reason='Forbidden redispatch')
        self.assertEqual(self.snapshot(), before)

    def test_new_boot_requires_resume_before_any_domain_or_controller_effect(self):
        self.finish_create()
        self.flow.command_context = self.context_for('CancelRun', 'newboot', boot='test.boot.2')
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.fixture.act('cancel', reason='Stale boot')
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.flow.finish_command({'fake': True})
        self.assertEqual(self.snapshot(), before)

    def test_resume_receipt_session_clock_and_uncertain_old_commands_are_one_commit(self):
        self.fixture.prepare_input(); self.fixture.begin()
        before = self.snapshot()
        old = self.flow
        clock = FixtureClock(record=self.fixture.clock.record)
        clock.record['process_id'] = 'Fixture.NewProcess'
        resumed = self.reopen(clock=clock)
        after = self.snapshot()
        self.assertEqual(len(after['events']), len(before['events']) + 1)
        self.assertNotEqual(after['state']['session'], old.session)
        self.assertEqual(after['state']['clock']['last_sample']['process_id'], 'Fixture.NewProcess')
        self.assertEqual(after['state']['network']['commands']['create']['status'], 'uncertain')
        self.assertEqual(after['state']['network']['commands']['resume']['status'], 'accepted')
        for field in ('inventory', 'bookings', 'resources'):
            self.assertEqual(after['state'][field], before['state'][field])
        self.assertTrue(after['state']['recovery_required'])
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertTrue(event['payload']['no_effect_replayed'])
        self.assertEqual(event['payload']['network_receipt']['request_id'], 'resume')
        old.command_context = self.context_for('CancelRun', 'old-session', boot='test.boot.2')
        with self.assertRaisesRegex(TaskError, '(?i)stale'):
            old.act('cancel', self.fixture.actor, observation=self.fixture.envelope(), reason='Old session')
        resumed.finish_command({'resumed': True})

    def test_resume_guard_and_storage_failure_leave_all_old_state_unchanged(self):
        before = self.snapshot()
        def denied():
            raise PermissionError('Lease expired before resume')
        with self.assertRaises(PermissionError):
            self.reopen(guard=denied)
        self.assertEqual(self.snapshot(), before)
        with patch.object(self.journal, '_event', side_effect=TaskError('Injected resume storage failure')):
            with self.assertRaisesRegex(TaskError, 'storage failure'):
                self.reopen()
        self.assertEqual(self.snapshot(), before)

    def test_control_source_drift_blocks_effect_and_resume_without_mutation(self):
        path = ROOT / 'scripts/cutrun_input_sonication_control.py'
        read_bytes = Path.read_bytes
        before = self.snapshot()
        def changed(candidate):
            data = read_bytes(candidate)
            return data + b'\n' if candidate.resolve() == path else data
        with patch.object(Path, 'read_bytes', changed):
            with self.assertRaisesRegex(TaskError, '(?i)source changed'):
                self.fixture.act('cancel', reason='Changed control helper')
            with self.assertRaisesRegex(TaskError, '(?i)source changed'):
                self.reopen()
        self.assertEqual(self.snapshot(), before)

    def test_network_open_does_not_migrate_standalone_runs_or_change_their_bytes(self):
        journal = Journal(self.directory / 'standalone.sqlite3')
        self.addCleanup(journal.close)
        standalone = FixtureSession(journal, 'TEST.S09.Standalone', self.directory / 'standalone')
        before = list(journal.connection.iterdump())
        with self.assertRaisesRegex(TaskError, '(?i)(binding|migrated)'):
            NetworkInputSonicationWorkflow.open(journal, standalone.run_id, resume=True,
                clock=standalone.clock, control=self.control,
                command_context=self.context_for('ResumeRun', 'forbidden-migration'))
        self.assertEqual(list(journal.connection.iterdump()), before)
        self.assertNotIn('control', standalone.flow.state)
        self.assertNotIn('network', standalone.flow.state)


if __name__ == '__main__':
    unittest.main()
