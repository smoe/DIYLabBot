"""Unexpected post-commit failures never authorize another DNA execution."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_quantification import Workflow
from dna_sila2_runtime import DNARuntime
from manual_tasks import Journal, TaskError


class DNAFailureFencingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dna-failure-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.runtime = DNARuntime(self.temp.name)
        self.addCleanup(self.runtime.close)
        self.run = 'SYN.DNA.Failure'
        self.command('CreateRun', 'create')

    def command(self, name, request, **data):
        return self.runtime.command(name, {'request_identifier': request,
            'run_identifier': self.run, **data}, 'account.operator')

    def run_pair(self, request='run'):
        return self.command('RunUntilDecision', request, initial_dilution='none', after_range='',
            nanodrop_concentration=50., qubit_concentration=48., qubit_report_original=False)

    def snapshot(self):
        with Journal(self.runtime.journal_path) as journal:
            return journal.get_current(self.run)[0], journal.history(self.run), journal.owners()

    def fail_after_withdrawal(self, error, *, persistent=False, unreadable=False):
        append, read = Journal.append, Journal.get_current
        fired = False

        def append_fault(journal, run, revision, kind, payload, state, **options):
            nonlocal fired
            if fired and persistent:
                raise sqlite3.OperationalError('Injected persistent journal write loss')
            result = append(journal, run, revision, kind, payload, state, **options)
            if not fired and kind == 'device.confirm_measurement':
                fired = True
                raise error
            return result

        def read_fault(journal, run, **options):
            if fired and unreadable:
                raise sqlite3.OperationalError('Injected post-effect state read loss')
            return read(journal, run, **options)

        with patch.object(Journal, 'append', append_fault), patch.object(Journal, 'get_current', read_fault):
            if persistent or unreadable:
                with self.assertRaises((sqlite3.Error, type(error))):
                    self.run_pair()
                result = None
            else:
                result = self.run_pair()
        self.assertTrue(fired)
        return result

    def resume_and_finish(self):
        self.command('ResumeRun', 'resume', resume=True)
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'reconcil'):
            self.run_pair('before-reconcile')
        self.assertEqual(self.snapshot(), before)
        with Journal(self.runtime.journal_path) as journal:
            observations = Workflow(journal, self.run).inventory_observations()
        self.command('ReconcileInventory', 'reconcile', observation_json=json.dumps({
            'observations': observations, 'workspace_clear': True, 'blank_still_valid': True,
            'calibration_still_valid': True}))
        self.run_pair('continued')
        report = self.runtime.report(self.run)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['bookings']), 2)
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)

    def assert_read_only_replay(self, outcome):
        before = self.snapshot()
        self.assertEqual(self.run_pair()['outcome'], outcome)
        self.assertEqual(self.snapshot(), before)

    def test_sqlite_error_after_confirmed_withdrawal_holds_root_and_is_not_replayed(self):
        result = self.fail_after_withdrawal(sqlite3.OperationalError('Injected post-effect SQLite failure'))
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['error'], 'PersistenceFailure')
        self.assertNotIn(self.run, self.runtime._sessions)
        state, events, owners = self.snapshot()
        self.assertEqual(state['status'], 'held')
        self.assertTrue(state['recovery_required'])
        self.assertEqual(len(state['bookings']), 1)
        self.assertTrue(owners)
        self.assertEqual([event['kind'] for event in events[-2:]], ['execution_interrupted', 'command_finished'])
        self.assert_read_only_replay('failed')
        self.resume_and_finish()

    def test_key_error_after_confirmed_withdrawal_holds_root_and_is_not_replayed(self):
        result = self.fail_after_withdrawal(KeyError('Injected missing result field'))
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(self.snapshot()[0]['status'], 'held')
        self.assert_read_only_replay('failed')
        self.resume_and_finish()

    def test_persistently_unwritable_journal_fences_session_and_same_boot_resume_marks_accepted_uncertain(self):
        self.fail_after_withdrawal(sqlite3.OperationalError('Injected first write uncertainty'), persistent=True)
        before = self.snapshot()
        self.assertNotIn(self.run, self.runtime._sessions)
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.run_pair('new-request')
        self.assertEqual(self.snapshot(), before)
        self.assert_read_only_replay('accepted')
        finish = Workflow.finish_command
        seen = []

        def inspect_resume(flow, *args, **kwargs):
            if flow.command_context['command'] == 'ResumeRun':
                commands = flow.state['network']['commands']
                seen.append((commands['run']['status'], commands['resume']['status']))
            return finish(flow, *args, **kwargs)

        with patch.object(Workflow, 'finish_command', inspect_resume):
            self.resume_and_finish()
        self.assertEqual(seen, [('uncertain', 'accepted')])
        self.assertEqual(self.snapshot()[0]['network']['commands']['run']['status'], 'uncertain')

    def test_unreadable_state_after_effect_also_fences_the_process_session(self):
        self.fail_after_withdrawal(KeyError('Injected result decoding failure'), unreadable=True)
        self.assertNotIn(self.run, self.runtime._sessions)
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.run_pair('new-request')
        self.assertEqual(self.snapshot(), before)
        self.assert_read_only_replay('accepted')

    def test_exception_before_first_own_receipt_has_no_journal_effect(self):
        before = self.snapshot()
        with patch.object(self.runtime, '_run', side_effect=KeyError('Before first effect')):
            with self.assertRaises(KeyError):
                self.run_pair()
        self.assertEqual(self.snapshot(), before)

    def test_terminal_completion_failure_preserves_release_and_fences_new_commands(self):
        with patch.object(Workflow, 'finish_command', side_effect=sqlite3.OperationalError('Lost completion receipt')):
            with self.assertRaises(sqlite3.Error):
                self.run_pair()
        before = self.snapshot()
        self.assertEqual(before[0]['status'], 'completed')
        self.assertEqual(before[0]['resources'], [])
        self.assertEqual(before[2], {})
        self.assertNotIn(self.run, self.runtime._sessions)
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.command('AcceptResult', 'new-terminal-effect', sample_identifier='DNA01',
                allow_unquantified=False, reason='New terminal request')
        self.assertEqual(self.snapshot(), before)
        self.assert_read_only_replay('accepted')
        self.command('ResumeRun', 'terminal-resume', resume=True)
        after = self.snapshot()[0]
        for key in ('status', 'resources', 'inventory', 'bookings'):
            self.assertEqual(after[key], before[0][key])
        self.assertEqual(after['network']['commands']['run']['status'], 'uncertain')

    def test_server_maps_sqlite_errors_to_persistence_failure(self):
        from dna_sila2_server import DNAServer

        class PersistenceFailure(Exception):
            pass

        server = object.__new__(DNAServer)
        server.feature = SimpleNamespace(errors={'PersistenceFailure': PersistenceFailure})
        with self.assertRaises(PersistenceFailure):
            server._error(sqlite3.OperationalError('Injected SQLite failure'))


if __name__ == '__main__':
    unittest.main()
