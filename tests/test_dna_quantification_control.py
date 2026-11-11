"""Transport decisions, effects and receipts share exactly one root journal."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError
from dna_quantification import Workflow
from dna_sila2_runtime import DNARuntime


class DNAControlTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='dna-control-')
        self.directory = Path(self.temp.name)
        self.runtime = DNARuntime(self.directory)
        self.run_id = 'SYN.DNA.Control'

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def command(self, name, request, **kwargs):
        return self.runtime.command(name, dict(request_identifier=request,
            run_identifier=self.run_id, **kwargs), principal='network.operator')

    def state(self):
        with Journal(self.runtime.journal_path) as journal:
            return journal.get_current(self.run_id)[0]

    def history(self):
        with Journal(self.runtime.journal_path) as journal:
            return journal.history(self.run_id)

    def create(self):
        return self.command('CreateRun', 'create')

    def run_pair(self, request='run', **override):
        args = dict(initial_dilution='none', after_range='', nanodrop_concentration=50.,
                    qubit_concentration=48., qubit_report_original=False)
        args.update(override)
        return self.command('RunUntilDecision', request, **args)

    def test_creation_receipt_and_domain_share_first_journal_commit(self):
        self.create(); first = self.history()[0]['state']
        self.assertEqual(first['control']['mode'], 'sila2_network/1')
        receipt = first['network']['commands']['create']
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(receipt['principal'], 'network.operator')
        self.assertNotEqual(first['responsible_person_id'], receipt['principal'])
        self.assertEqual(first['creation_receipt']['evidence'], 'network_receipt')

    def test_identical_request_returns_stored_reply_without_any_event(self):
        response = self.create(); before = self.history()
        self.assertEqual(self.create(), response)
        self.assertEqual(self.history(), before)

    def test_reused_identifier_with_different_command_or_principal_has_no_event(self):
        self.create(); before = self.history()
        with self.assertRaises(TaskError):
            self.command('CancelRun', 'create', reason='different')
        with self.assertRaises(TaskError):
            self.runtime.command('CreateRun', dict(request_identifier='create', run_identifier=self.run_id), 'other')
        self.assertEqual(self.history(), before)

    def test_local_cli_mutation_and_open_cannot_bypass_network_binding(self):
        self.create(); before = self.history()
        with Journal(self.runtime.journal_path) as journal:
            flow = Workflow(journal, self.run_id, self.state()['session'])
            with self.assertRaisesRegex(TaskError, 'SiLA server'):
                flow.cancel('SYN.DNA.Operator01', 'Local bypass')
            with self.assertRaisesRegex(TaskError, 'SiLA server'):
                Workflow.open(journal, self.run_id, resume=True)
            self.assertEqual(flow.report()['run_id'], self.run_id)
        self.assertEqual(self.history(), before)

    def test_subprocess_cli_can_read_but_not_write_bound_run(self):
        self.create()
        prefix = [sys.executable, str(ROOT / 'scripts/run_dna_quantification.py'),
                  '--store', str(self.runtime.journal_path)]
        read = subprocess.run([*prefix, 'report', self.run_id], capture_output=True, text=True)
        self.assertEqual(read.returncode, 0, read.stderr)
        before = self.history()
        write = subprocess.run([*prefix, 'cancel', self.run_id, '--resume', '--reason', 'bypass'], capture_output=True, text=True)
        self.assertNotEqual(write.returncode, 0)
        self.assertEqual(self.history(), before)

    def test_network_guard_failure_before_first_effect_creates_nothing(self):
        def denied(): raise PermissionError('Lease expired')
        with self.assertRaises(PermissionError):
            self.runtime.command('CreateRun', dict(request_identifier='create',run_identifier=self.run_id),
                                 'network.operator', guard=denied)
        self.assertEqual(self.runtime.status()['run_ids'], [])

    def test_interruption_after_worker_claim_requires_custody_reconciliation(self):
        self.create()
        def expire_after_claim():
            state = self.state()
            goal_id = state.get('task_port', {}).get('pending_goal_id')
            if goal_id and state['task_port']['goals'][goal_id]['status'] == 'claimed':
                raise PermissionError('Lease expired after worker claim, before root observation')
        result = self.runtime.command('RunUntilDecision', dict(request_identifier='worker-interrupt',
            run_identifier=self.run_id, initial_dilution='none', after_range='',
            nanodrop_concentration=50., qubit_concentration=48., qubit_report_original=False),
            'network.operator', guard=expire_after_claim)
        self.assertEqual(result['error'], 'ReconciliationRequired')
        state = self.state()
        self.assertEqual(state['status'], 'held')
        self.assertTrue(state['task_port']['pending_goal_id'])
        self.assertEqual(state['bookings'], {})
        self.assertEqual(state['inventory']['vessels']['SYN.DNA.Tube01']['location']['kind'], 'rack')
        self.assertTrue(state['resources'])

    def test_scenario_is_persisted_and_cannot_silently_reset_on_resume(self):
        self.create(); self.run_pair(qubit_concentration=500)
        state = self.state(); before = self.history()
        self.assertEqual(state['scenario']['qubit_concentration'], 500)
        with self.assertRaisesRegex(TaskError, 'scenario'):
            self.run_pair('changed')
        self.assertEqual(self.history(), before)

    def test_in_process_binding_does_not_claim_network_execution(self):
        self.create(); self.run_pair()
        report = self.runtime.report(self.run_id)
        self.assertTrue(report['passed'])
        self.assertFalse(report['network_executed'])
        self.assertFalse(report['hardware_executed'])
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)

    def test_high_result_new_pair_preserves_raw_attempt_and_original_balance(self):
        self.create(); self.run_pair(qubit_concentration=500)
        first = copy.deepcopy(next(iter(self.state()['attempts'].values())))
        self.command('ChooseDilution', 'dilute', sample_identifier='DNA01', dilution_preset='1+9')
        self.run_pair('retry', qubit_concentration=500)
        report = self.runtime.report(self.run_id)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['attempts']), 2)
        self.assertEqual(report['attempts'][first['id']]['results'], first['results'])
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 34.5)

    def test_new_boot_requires_resume_and_person_reconciliation(self):
        self.create(); old_boot = self.runtime.boot_id
        self.runtime.close(); self.runtime = DNARuntime(self.directory)
        self.assertNotEqual(old_boot, self.runtime.boot_id)
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.run_pair()
        self.command('ResumeRun', 'resume', resume=True)
        self.assertEqual(self.state()['status'], 'held')
        with Journal(self.runtime.journal_path) as journal:
            observations = Workflow(journal, self.run_id).inventory_observations()
        self.command('ReconcileInventory', 'reconcile', observation_json=json.dumps({
            'observations': observations, 'workspace_clear': True}))
        self.assertEqual(self.state()['status'], 'created')
        self.run_pair()
        self.assertTrue(self.runtime.report(self.run_id)['passed'])

    def test_cancellation_intent_never_releases_reserved_lab_resources(self):
        self.create(); self.run_pair(qubit_concentration=500)
        before = self.state()['resources']
        self.command('CancelRun', 'cancel', reason='Explicit person cancellation')
        self.assertEqual(self.state()['status'], 'cancelling')
        self.assertEqual(self.state()['resources'], before)
        self.assertTrue(before)
        result = self.command('FinishCancel', 'incomplete', observation_json=json.dumps({
            'observations': [], 'workspace_clear': True}))
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(self.state()['resources'], before)

    def test_every_run_transition_is_correlated_without_token_fields(self):
        self.create(); self.run_pair()
        events = [e for e in self.history() if e['sequence'] > 1]
        for event in events:
            payload = event['payload']
            self.assertIn('request_id', payload)
            self.assertIn('execution_uuid', payload)
            self.assertEqual(payload['principal'], 'network.operator')
            self.assertNotEqual(payload['actor_id'], payload['principal'])
            self.assertNotIn('access_token', payload)

    def test_server_process_lock_is_exclusive(self):
        with self.assertRaisesRegex(TaskError, 'Another DNA server'):
            DNARuntime(self.directory)

    def test_payload_cannot_replace_principal_or_evidence_system_fields(self):
        self.create()
        with Journal(self.runtime.journal_path) as journal:
            state = journal.get_current(self.run_id)[0]
            context = dict(request_id='protected', fingerprint='0' * 64, command='test', arguments={},
                principal='network.operator', server_uuid=self.runtime.server_uuid,
                boot_id=self.runtime.boot_id, execution_uuid='execution', transport='in_process',
                clock=self.runtime.clock)
            flow = Workflow(journal, self.run_id, state['session'], context)
            flow.control_event('protected_fields', self.runtime.actor_id, payload={
                'principal': 'forged', 'evidence': 'worker_claim', 'server_uuid': 'forged'})
            payload = journal.history(self.run_id)[-1]['payload']
            self.assertEqual(payload['principal'], 'network.operator')
            self.assertEqual(payload['evidence'], 'network_receipt')
            self.assertEqual(payload['server_uuid'], self.runtime.server_uuid)

    def test_task_cannot_borrow_a_foreign_request_identifier(self):
        from dna_quantification_demo import SyntheticBackend
        with Journal(self.directory / 'local.sqlite3') as journal:
            flow = Workflow.create(journal, run_id='SYN.DNA.Local')
            backend = SyntheticBackend(); backend.accept_rack(flow)
            flow.choose_dilution(backend.actor_id, 'DNA01', 'none')
            goal = flow.task_goal(flow.state['active_context_id'],
                {'kind': 'agent', 'agent_id': 'SYN.DNA.Agent'}, 'SYN.DNA.Agent')
            goal['request_id'] = 'foreign'
            before = journal.history(flow.run_id)
            with self.assertRaisesRegex(TaskError, 'request identity'):
                flow.intend_task(backend.actor_id, goal)
            self.assertEqual(journal.history(flow.run_id), before)


if __name__ == '__main__': unittest.main()
