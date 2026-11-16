"""Shared-journal extraction failures retain effects and require explicit recovery."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_sila2_runtime import DNARuntime
from extraction_analytics_sila2_control import NetworkExtractionAnalyticsWorkflow
from extraction_analytics_sila2_execution import ExecutionDriver
from extraction_analytics_sila2_runtime import ExtractionAnalyticsRuntime, RECONCILIATION
from manual_tasks import Journal, TaskError, encoded


class ExtractionFailureFencingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='extraction-failure-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.host = DNARuntime(Path(self.temp.name) / 'fault')
        self.addCleanup(self.host.close)
        self.runtime = ExtractionAnalyticsRuntime(self.host)
        self.run = 'SYN.Analytics.Failure'

    def command(self, name, request, **data):
        return self.runtime.command(name, {'request_identifier': request,
            'run_identifier': self.run, **data}, 'account.operator')

    def create(self, family='dneasy'):
        self.command('CreateRun', 'create', family_identifier=family)

    def snapshot(self):
        with Journal(self.runtime.journal_path) as journal:
            return journal.get_current(self.run)[0], journal.history(self.run), journal.owners()

    def fail_after_phase(self, error, *, persistent=False, unreadable=False):
        append, read = Journal.append, Journal.get_current
        fired = False

        def append_fault(journal, run, revision, kind, payload, state, **options):
            nonlocal fired
            if fired and persistent:
                raise sqlite3.OperationalError('Injected persistent extraction journal write loss')
            result = append(journal, run, revision, kind, payload, state, **options)
            if not fired and kind == 'confirm_phase':
                fired = True
                raise error
            return result

        def read_fault(journal, run, **options):
            if fired and unreadable:
                raise sqlite3.OperationalError('Injected post-effect extraction state read loss')
            return read(journal, run, **options)

        with patch.object(Journal, 'append', append_fault), patch.object(Journal, 'get_current', read_fault):
            if persistent or unreadable:
                with self.assertRaises((sqlite3.Error, type(error))):
                    self.command('RunUntilDecision', 'run')
                result = None
            else:
                result = self.command('RunUntilDecision', 'run')
        self.assertTrue(fired)
        return result

    def assert_read_only_replay(self, outcome):
        before = self.snapshot()
        self.assertEqual(self.command('RunUntilDecision', 'run')['outcome'], outcome)
        self.assertEqual(self.snapshot(), before)

    def resume_and_finish(self):
        self.command('ResumeRun', 'resume', resume=True)
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'reconcil'):
            self.command('RunUntilDecision', 'before-reconcile')
        self.assertEqual(self.snapshot(), before)
        state = before[0]
        observed = [{'vessel_id': identity, 'material_ids': [key for key, material in
            state['inventory']['materials'].items() if material['vessel_id'] == identity],
            'location': copy.deepcopy(vessel['location'])}
            for identity, vessel in state['inventory']['vessels'].items()]
        self.command('ReconcileRun', 'reconcile', observation_json=json.dumps({
            'format': RECONCILIATION, 'reason': 'Explicit complete synthetic recovery observation',
            'observations': observed, 'workspace_clear': True}))
        self.command('RunUntilDecision', 'continued')
        self.assertTrue(self.runtime.report(self.run)['passed'])

    @staticmethod
    def ledger_projection(report):
        return {'remaining': report['remaining'], 'resources': report['resources'],
            'materials': {identity: {key: material[key] for key in
                ('kind', 'vessel_id', 'initial_quantity', 'parents', 'role', 'disposition')}
                for identity, material in report['inventory']['materials'].items()},
            'bookings': sorted(encoded({key: row[key] for key in
                ('outcome', 'actual_inputs', 'actual_outputs')}) for row in report['bookings'].values())}

    def assert_normal_root_equivalence(self, family):
        host = DNARuntime(Path(self.temp.name) / 'normal')
        try:
            normal = ExtractionAnalyticsRuntime(host)
            normal.command('CreateRun', {'request_identifier': 'create', 'run_identifier': self.run,
                'family_identifier': family}, 'account.operator')
            normal.command('RunUntilDecision', {'request_identifier': 'run',
                'run_identifier': self.run}, 'account.operator')
            report = self.runtime.report(self.run)
            expected = normal.report(self.run)
            self.assertEqual(self.ledger_projection(report), self.ledger_projection(expected))
            product = next(identity for identity, material in report['inventory']['materials'].items()
                if material['kind'] == 'product')
            self.assertEqual(report['remaining'][product]['value'], 195.5 if family == 'dneasy' else 95.5)
        finally:
            host.close()

    def test_sqlite_failure_after_first_phase_holds_puregene_and_preserves_its_ledger(self):
        self.create('puregene')
        result = self.fail_after_phase(sqlite3.OperationalError('Injected post-effect SQLite failure'))
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['error'], 'PersistenceFailure')
        self.assertNotIn(self.run, self.runtime._sessions)
        state, events, owners = self.snapshot()
        self.assertTrue(state['recovery_required'])
        self.assertFalse(state['workspace_clear'])
        self.assertTrue(owners)
        self.assertEqual([event['kind'] for event in events[-2:]], ['execution_interrupted', 'command_finished'])
        self.assert_read_only_replay('failed')
        self.resume_and_finish()
        self.assert_normal_root_equivalence('puregene')

    def test_key_error_after_first_phase_holds_dneasy_and_preserves_its_ledger(self):
        self.create()
        result = self.fail_after_phase(KeyError('Injected missing extraction field'))
        self.assertEqual(result['outcome'], 'failed')
        self.assertTrue(self.snapshot()[0]['recovery_required'])
        self.assert_read_only_replay('failed')
        self.resume_and_finish()
        self.assert_normal_root_equivalence('dneasy')

    def test_persistently_unwritable_journal_fences_session_and_same_boot_resume_marks_accepted_uncertain(self):
        self.create()
        self.fail_after_phase(sqlite3.OperationalError('Injected first extraction write uncertainty'), persistent=True)
        before = self.snapshot()
        self.assertNotIn(self.run, self.runtime._sessions)
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.command('RunUntilDecision', 'new-request')
        self.assertEqual(self.snapshot(), before)
        self.assert_read_only_replay('accepted')
        finish = NetworkExtractionAnalyticsWorkflow.finish_command
        seen = []

        def inspect_resume(flow, *args, **kwargs):
            if flow.command_context['command'] == 'ResumeRun':
                commands = flow.state['network']['commands']
                seen.append((commands['run']['status'], commands['resume']['status']))
            return finish(flow, *args, **kwargs)

        with patch.object(NetworkExtractionAnalyticsWorkflow, 'finish_command', inspect_resume):
            self.resume_and_finish()
        self.assertEqual(seen, [('uncertain', 'accepted')])
        self.assertEqual(self.snapshot()[0]['network']['commands']['run']['status'], 'uncertain')

    def test_unreadable_state_after_effect_also_fences_the_process_session(self):
        self.create()
        self.fail_after_phase(KeyError('Injected extraction decoding failure'), unreadable=True)
        self.assertNotIn(self.run, self.runtime._sessions)
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.command('RunUntilDecision', 'new-request')
        self.assertEqual(self.snapshot(), before)
        self.assert_read_only_replay('accepted')

    def test_exception_before_first_own_receipt_has_no_journal_effect(self):
        self.create()
        before = self.snapshot()
        with patch.object(ExecutionDriver, 'run', side_effect=KeyError('Before first extraction effect')):
            with self.assertRaises(KeyError):
                self.command('RunUntilDecision', 'run')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
