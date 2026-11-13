"""Offline coordinator checks; no SiLA network, device or ROS is executed."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import build_cutrun_input_sonication_sila2 as contract
from cutrun_input_sonication_control import NetworkInputSonicationWorkflow
from cutrun_input_sonication_demo import FixtureClock, fixture_values
from manual_tasks import Journal, TaskError, digest, encoded
from sonication_sila2_runtime import SonicationRuntime, reconciliation_document


class InjectedProcessCrash(BaseException):
    """Offline fault injection, distinct from the separate-process SIGKILL test."""


class SonicationRuntimeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='s09-runtime-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.run_id = 'Fixture.S09.Offline.' + uuid.uuid4().hex[:8]
        self.principal = 'offline.network.principal'

    def runtime(self, *, folder='server', **options):
        runtime = SonicationRuntime(self.directory / folder, **options)
        self.addCleanup(runtime.close)
        return runtime

    def arguments(self, *, request=None, **arguments):
        return {'request_identifier': request or str(uuid.uuid4()),
                'run_identifier': self.run_id, **arguments}

    def command(self, runtime, name, *, request=None, principal=None, **arguments):
        return runtime.command(name, self.arguments(request=request, **arguments),
                               principal or self.principal)

    def create(self, runtime, scenario='normal', **options):
        return self.command(runtime, 'CreateRun', scenario_identifier=scenario, **options)

    def snapshot(self, runtime):
        with Journal(runtime.journal_path) as journal:
            exists = journal.connection.execute('SELECT 1 FROM runs WHERE id=?', (self.run_id,)).fetchone()
            return {'state': journal.state(self.run_id)[0] if exists else None,
                    'events': journal.connection.execute(
                        'SELECT run_id, sequence, document, sha256 FROM events ORDER BY run_id, sequence').fetchall(),
                    'owners': journal.owners()}

    def paused_execution(self, runtime, *, crash=False):
        """Stop at a persisted boundary; a guard can emulate abrupt process loss."""
        request, execution = str(uuid.uuid4()), str(uuid.uuid4())
        crash_requested = threading.Event()
        result = {}

        def guard():
            if crash_requested.is_set():
                raise InjectedProcessCrash('Injected offline process loss at ' + runtime.pause_after)

        def worker():
            try:
                result['response'] = runtime.command('RunUntilDecision', self.arguments(request=request),
                    self.principal, execution_uuid=execution, guard=guard if crash else None)
            except BaseException as error:
                result['error'] = error

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        def stop():
            if thread.is_alive():
                runtime.close()
                thread.join(5)

        self.addCleanup(stop)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = self.snapshot(runtime)['state']
            if self.boundary_reached(state, runtime.pause_after):
                return {'request': request, 'execution': execution, 'thread': thread,
                        'result': result, 'crash_requested': crash_requested,
                        'report': runtime.report(self.run_id)}
            if not thread.is_alive():
                self.fail('Execution ended before persisted ' + runtime.pause_after + ': ' + repr(result))
            time.sleep(.01)
        self.fail('No persisted ' + runtime.pause_after + ' observed')

    @staticmethod
    def boundary_reached(state, point):
        pending = state['pending_operation']
        stages = {stage['stage_id']: stage for stage in state['sop']['stages'].values()}
        if point == 'opening_complete':
            return 'S01' in stages and stages['S01']['status'] == 'completed'
        if point in {'sonication_intent', 'input_preparation_intent', 'qc_withdrawal_intent'}:
            suffix = {'sonication_intent': '.Sonication', 'input_preparation_intent': '.InputPreparation',
                      'qc_withdrawal_intent': '.SizeWithdrawal'}[point]
            return pending is not None and pending['intent_id'].endswith(suffix)
        if point == 'phase_time':
            if 'S09' not in stages:
                return False
            phase = stages['S09']['phases']['S09.input_preparation']
            return bool(phase['times']) and not phase['temperatures']
        if point == 'qc_confirmed':
            return any(identity.endswith('.SizeWithdrawal') and booking['outcome'] == 'performed'
                       for identity, booking in state['bookings'].items())
        raise AssertionError('Unsupported offline checkpoint: ' + str(point))

    def interrupt(self, runtime, paused):
        receipt = runtime.cancel_execution(paused['execution'], self.principal)
        self.assertFalse(receipt['root_cancelled'])
        self.assertFalse(receipt['resources_released'])
        paused['thread'].join(5)
        self.assertFalse(paused['thread'].is_alive())
        self.assertNotIn('error', paused['result'])
        self.assertEqual(paused['result']['response']['outcome'], 'interrupted')
        return runtime.report(self.run_id)

    def reconcile(self, runtime, document, *, finish=False, request=None):
        return self.command(runtime, 'FinishCancel' if finish else 'ReconcileRun',
                            request=request, observation_json=json.dumps(document))

    def test_exact_request_retry_and_conflicts_leave_durable_events_unchanged(self):
        runtime = self.runtime()
        request = str(uuid.uuid4())
        first = self.create(runtime, request=request)
        before = self.snapshot(runtime)
        self.assertEqual(first['outcome'], 'completed')
        self.assertEqual(self.create(runtime, request=request), first)
        self.assertEqual(self.snapshot(runtime), before)
        conflicts = [
            ('CreateRun', {'scenario_identifier': 'restart'}, self.principal),
            ('CreateRun', {'scenario_identifier': 'normal'}, 'different.network.principal'),
            ('CancelRun', {'reason': 'Different command under the same request'}, self.principal)]
        for name, arguments, principal in conflicts:
            with self.subTest(command=name, principal=principal, arguments=arguments):
                with self.assertRaisesRegex(TaskError, 'Request identifier reused'):
                    self.command(runtime, name, request=request, principal=principal, **arguments)
                self.assertEqual(self.snapshot(runtime), before)
        self.assertEqual(runtime.status()['run_ids'], [self.run_id])
        self.assertEqual(runtime.report()['reports'][self.run_id]['run_id'], self.run_id)
        self.assertEqual(self.snapshot(runtime), before)

    def test_current_source_drift_blocks_creation_and_existing_requests_before_events(self):
        new_directory = self.directory / 'rejected'
        with patch.object(contract, 'verify_source_files', side_effect=ValueError('Injected source changed')):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                SonicationRuntime(new_directory)
        self.assertFalse(new_directory.exists())
        runtime = self.runtime()
        self.create(runtime, request='create')
        before = self.snapshot(runtime)
        with patch.object(contract, 'verify_source_files', side_effect=ValueError('Injected source changed')):
            for command, arguments in [('CreateRun', {'scenario_identifier': 'normal'}),
                                       ('CancelRun', {'reason': 'Blocked source drift'}),
                                       ('ResumeRun', {'resume': True})]:
                with self.subTest(command=command):
                    with self.assertRaisesRegex(ValueError, 'source changed'):
                        self.command(runtime, command, request='create' if command == 'CreateRun' else None,
                                     **arguments)
                    self.assertEqual(self.snapshot(runtime), before)

    def test_recovery_after_atomic_create_commit_accepts_initial_inventory_once(self):
        runtime = self.runtime()
        request, execution = str(uuid.uuid4()), str(uuid.uuid4())

        def crash_before_first_domain_transition():
            state = self.snapshot(runtime)['state']
            if state is not None and state['status'] == 'created':
                raise InjectedProcessCrash('Injected process loss after atomic CreateRoot commit')

        with self.assertRaises(InjectedProcessCrash):
            runtime.command('CreateRun', self.arguments(request=request, scenario_identifier='restart'),
                self.principal, execution_uuid=execution, guard=crash_before_first_domain_transition)
        before = self.snapshot(runtime)
        state = before['state']
        self.assertEqual(state['status'], 'created')
        self.assertIsNone(state['actor_id'])
        self.assertIsNone(state['pending_operation'])
        self.assertEqual(state['bookings'], {})
        self.assertTrue(state['inventory']['materials'])
        self.assertTrue(state['resources'])
        self.assertEqual(len(before['events']), 1)
        self.assertEqual(set(before['owners']), set(state['resources']))
        self.assertEqual(set(before['owners'].values()), {self.run_id})
        accepted = state['network']['commands'][request]
        self.assertEqual(accepted['status'], 'accepted')
        self.assertEqual(accepted['confirmation_event_sequence'], 1)
        self.assertEqual(accepted['execution_uuid'], execution)
        self.assertEqual(accepted['principal'], self.principal)
        self.assertEqual(state['creation_receipt']['network_receipt']['principal'], self.principal)
        runtime.close()
        restarted = self.runtime()
        self.assertEqual(restarted.server_uuid, runtime.server_uuid)
        self.assertNotEqual(restarted.boot_id, runtime.boot_id)
        self.command(restarted, 'ResumeRun', resume=True)
        resumed = self.snapshot(restarted)
        for key in ('inventory', 'bookings', 'resources', 'pending_operation'):
            self.assertEqual(resumed['state'][key], state[key], key)
        self.assertNotEqual(resumed['state']['session'], state['session'])
        self.assertEqual(resumed['state']['network']['commands'][request]['status'], 'uncertain')
        self.assertEqual(self.create(restarted, scenario='restart', request=request)['outcome'], 'uncertain')
        self.assertEqual(self.snapshot(restarted), resumed)
        report = restarted.report(self.run_id)
        self.assertEqual(report['sonication']['intents'], {})
        proposal = self.explicit_client_proposal(restarted, report)
        self.assertIsNone(proposal['sonication'])
        self.assertNotIn('material', proposal)
        self.assertEqual(self.reconcile(restarted, proposal)['outcome'], 'completed')
        final = self.assert_recovered_s09(restarted)
        self.assertEqual(sum(event['kind'] == 'created' for event in final['trace']), 1)
        self.assertEqual(sum(event['kind'] == 'accept_inventory' for event in final['trace']), 1)
        self.assertEqual(self.snapshot(restarted)['events'][0], before['events'][0])

    def test_normal_input_only_stage_uses_root_ledger_and_fixture_provenance(self):
        runtime = self.runtime()
        self.create(runtime)
        initial = self.snapshot(runtime)['state']
        request = str(uuid.uuid4())
        response = self.command(runtime, 'RunUntilDecision', request=request)
        self.assertEqual(response['outcome'], 'completed')
        report = runtime.report(self.run_id)
        state = self.snapshot(runtime)['state']
        values = fixture_values()
        self.assertEqual(state['actor_id'], values['actor_id'])
        self.assertNotEqual(state['actor_id'], self.principal)
        self.assertEqual(len(report['sonication']['intents']), 1)
        identity, intent = next(iter(report['sonication']['intents'].items()))
        self.assertEqual(intent['quantity_before'], {'value': 300, 'unit': 'uL'})
        self.assertEqual(report['bookings'][identity]['outcome'], 'performed')
        self.assertEqual(report['remaining'][intent['material_after_id']],
                         {'value': 295, 'unit': 'uL', 'knowledge': 'known'})
        withdrawals = [item for item in report['bookings'].values() if item['request']['kind'] == 'withdrawal']
        self.assertEqual(len(withdrawals), 1)
        self.assertEqual(withdrawals[0]['actual_inputs'], [
            {'material_id': intent['material_after_id'], 'quantity': {'value': 5, 'unit': 'uL'}}])
        self.assertEqual(report['sop']['stages'][intent['stage_run_id']]['status'], 'completed')
        self.assertEqual(state['status'], 'working')
        self.assertTrue(report['resources'])
        self.assertEqual(report['inventory']['vessels'][intent['vessel_id']]['location'], intent['original_rack_location'])
        for reaction_id, reaction in initial['manual']['reactions'].items():
            if reaction['role'] != 'input':
                self.assertEqual(state['manual']['reactions'][reaction_id], reaction)
                self.assertEqual(state['inventory']['materials'][reaction['current_material_id']],
                                 initial['inventory']['materials'][reaction['current_material_id']])
        physical = intent['physical_receipt']
        self.assertEqual(physical['observation']['actual_output_quantity'], {'value': 300, 'unit': 'uL'})
        self.assertEqual(physical['receipt']['actor_id'], values['actor_id'])
        self.assertEqual(physical['receipt']['evidence'], 'test_fixture')
        self.assertEqual(len(physical['observation']['artifact_sha256']), 64)
        size = next(iter(intent['size_records'].values()))
        self.assertEqual(size['receipt']['actor_id'], values['actor_id'])
        self.assertEqual(size['receipt']['evidence'], 'test_fixture')
        self.assertTrue(size['fixture_range_conformant'])
        self.assertFalse(size['biological_acceptance'])
        with Journal(runtime.journal_path) as journal:
            physical_event = next(event for event in journal.history(self.run_id)
                                  if event['kind'] == 'confirm_sonication')
        self.assertEqual(physical_event['payload']['actor_id'], values['actor_id'])
        self.assertEqual(physical_event['payload']['observation']['source_kind'], 'test_fixture')
        self.assertEqual(physical_event['payload']['network_receipt']['principal'], self.principal)
        self.assertFalse(report['transport_receipts']['sila_loopback_executed'])
        for flag in ('hardware_executed', 'network_executed', 'execution_ready',
                     'reference_success', 'preparation_complete'):
            self.assertFalse(report[flag], flag)
        self.assertFalse(report['sonication']['flags']['ros_executed'])
        before_retry = self.snapshot(runtime)
        self.assertEqual(self.command(runtime, 'RunUntilDecision', request=request), response)
        self.assertEqual(self.snapshot(runtime), before_retry)

    def test_interrupted_execution_and_explicit_unknown_observation_keep_all_holds(self):
        runtime = self.runtime(pause_after='sonication_intent')
        self.create(runtime, scenario='restart')
        paused = self.paused_execution(runtime)
        before = paused['report']
        held = self.interrupt(runtime, paused)
        self.assertEqual(held['pending_operation'], before['pending_operation'])
        self.assertEqual(held['bookings'], before['bookings'])
        self.assertEqual(held['resources'], before['resources'])
        self.assertIsNone(self.snapshot(runtime)['state']['cancel_reason'])
        valid = reconciliation_document(held, outcome='performed')
        wire = copy.deepcopy(held)
        wire.pop('trace')
        with self.assertRaisesRegex(TaskError, 'versioned wire report'):
            reconciliation_document(wire, outcome='performed')
        wire['wire_projection'] = {'format': 'solidcraftbot.s09-sila2-wire-report/1',
            'trace': 'metadata_only', 'full_journal': 'private root journal and evidence export'}
        wire_before = copy.deepcopy(wire)
        before_proposals = self.snapshot(runtime)
        with patch('sonication_sila2_runtime.Journal', side_effect=AssertionError('Client proposal opened a Root journal')):
            selected = reconciliation_document(wire, outcome='performed')
            selected_finish = reconciliation_document(wire, outcome='performed', finish=True)
        self.assertEqual(wire, wire_before)
        self.assertEqual(self.snapshot(runtime), before_proposals)
        self.assertEqual({key: value for key, value in selected.items() if key != 'observations'},
                         {key: value for key, value in valid.items() if key != 'observations'})
        observations = lambda document: {item['vessel_id']: (set(item['material_ids']), item['location'])
                                         for item in document['observations']}
        self.assertEqual(observations(selected), observations(valid))
        full_finish = reconciliation_document(held, outcome='performed', finish=True)
        dispositions = lambda document: {(item['material_id'], item['disposition'], item['reason'])
                                         for item in document['dispositions']}
        self.assertEqual(dispositions(selected_finish), dispositions(full_finish))
        malformed = copy.deepcopy(valid)
        malformed['sonication']['observed_vessel_id'] = 'foreign.vessel'
        missing = copy.deepcopy(valid)
        missing['observations'] = []
        for document in [None, '{', json.dumps(malformed), json.dumps(missing)]:
            with self.subTest(document=document):
                before_invalid = self.snapshot(runtime)
                with self.assertRaises((TaskError, ValueError)):
                    self.command(runtime, 'ReconcileRun', observation_json=document if document is not None else '{}')
                self.assertEqual(self.snapshot(runtime), before_invalid)
        proposal_before = self.snapshot(runtime)
        proposal = reconciliation_document(held, outcome='unknown')
        self.assertEqual(self.snapshot(runtime), proposal_before)
        result = self.reconcile(runtime, proposal)
        self.assertEqual(result['outcome'], 'completed')
        unknown = runtime.report(self.run_id)
        identity = before['pending_operation']['intent_id']
        self.assertEqual(unknown['bookings'][identity]['outcome'], 'unknown')
        self.assertEqual(unknown['resources'], before['resources'])
        self.assertIsNotNone(unknown['pending_operation'])
        self.assertNotIn(next(iter(unknown['sonication']['intents'].values()))['material_after_id'],
                         unknown['inventory']['materials'])
        before_refused = self.snapshot(runtime)
        with self.assertRaisesRegex(TaskError, 'reconciliation is required'):
            self.command(runtime, 'RunUntilDecision')
        self.assertEqual(self.snapshot(runtime), before_refused)

    def test_injected_process_loss_requires_new_session_and_explicit_outcome_without_replay(self):
        old = self.runtime(pause_after='sonication_intent')
        self.create(old, scenario='restart')
        paused = self.paused_execution(old, crash=True)
        before = self.snapshot(old)
        paused['crash_requested'].set()
        paused['thread'].join(5)
        self.assertFalse(paused['thread'].is_alive())
        self.assertIsInstance(paused['result']['error'], InjectedProcessCrash)
        self.assertEqual(self.snapshot(old), before)
        old.close()
        restarted = self.runtime()
        self.assertEqual(restarted.server_uuid, old.server_uuid)
        self.assertNotEqual(restarted.boot_id, old.boot_id)
        for command, arguments in [('RunUntilDecision', {}),
                                   ('CancelRun', {'reason': 'No implicit resume'})]:
            with self.subTest(command=command):
                with self.assertRaisesRegex(TaskError, 'ResumeRun'):
                    self.command(restarted, command, **arguments)
                self.assertEqual(self.snapshot(restarted), before)
        resumed = self.command(restarted, 'ResumeRun', resume=True)
        self.assertEqual(resumed['outcome'], 'completed')
        after_resume = self.snapshot(restarted)
        self.assertNotEqual(after_resume['state']['session'], before['state']['session'])
        self.assertEqual(after_resume['state']['network']['commands'][paused['request']]['status'], 'uncertain')
        for name in ('inventory', 'bookings', 'resources', 'pending_operation'):
            self.assertEqual(after_resume['state'][name], before['state'][name])
        self.assertTrue(after_resume['state']['clock']['gap_required'])
        retry = self.command(restarted, 'RunUntilDecision', request=paused['request'])
        self.assertEqual(retry['outcome'], 'uncertain')
        self.assertEqual(self.snapshot(restarted), after_resume)
        # An old root session stays fenced even if supplied a current boot.
        with Journal(restarted.journal_path) as journal:
            state = after_resume['state']
            args = self.arguments(reason='Stale session must not write')
            context = {'request_id': args['request_identifier'], 'fingerprint': digest(encoded({
                'command': 'CancelRun', 'arguments': args}).encode()), 'command': 'CancelRun',
                'arguments': args, 'principal': self.principal, 'server_uuid': restarted.server_uuid,
                'boot_id': restarted.boot_id, 'execution_uuid': str(uuid.uuid4()),
                'clock': time.time, 'transport': 'in_process'}
            clock = FixtureClock(record=state['clock']['last_sample'])
            stale = NetworkInputSonicationWorkflow(journal, self.run_id, before['state']['session'],
                clock=clock, command_context=context)
            prefix = fixture_values()['scenarios']['restart']['prefix']
            observation = {'observation_id': prefix + '.StaleSessionObservation', 'source_kind': 'test_fixture',
                'observed_at': {'earliest_utc': clock.record['utc'], 'latest_utc': clock.record['utc']},
                'source_ref': 'fixture://' + self.run_id, 'artifact_sha256': None}
            with self.assertRaisesRegex(TaskError, '(?i)stale'):
                stale.act('cancel', fixture_values()['actor_id'], observation=observation,
                          reason='Stale session must not write')
        self.assertEqual(self.snapshot(restarted), after_resume)
        report = restarted.report(self.run_id)
        no_gap = reconciliation_document(report, outcome='performed')
        no_gap['clock_gap'] = None
        with self.assertRaisesRegex(TaskError, 'clock gap'):
            self.reconcile(restarted, no_gap)
        self.assertEqual(self.snapshot(restarted), after_resume)
        selected = reconciliation_document(report, outcome='performed')
        self.reconcile(restarted, selected)
        resolved = restarted.report(self.run_id)
        intent_id = before['state']['pending_operation']['intent_id']
        self.assertEqual(resolved['bookings'][intent_id]['outcome'], 'performed')
        self.assertIsNone(resolved['pending_operation'])
        self.assertEqual(len(resolved['sonication']['intents']), 1)
        finished = self.command(restarted, 'RunUntilDecision')
        self.assertEqual(finished['outcome'], 'completed')
        final = restarted.report(self.run_id)
        intent = final['sonication']['intents'][intent_id]
        self.assertEqual(final['remaining'][intent['material_after_id']]['value'], 295)
        self.assertEqual(final['sop']['stages'][intent['stage_run_id']]['status'], 'completed')

    def test_cancel_releases_only_after_known_outcome_original_rack_and_complete_dispositions(self):
        runtime = self.runtime(pause_after='sonication_intent')
        self.create(runtime, scenario='cancel')
        paused = self.paused_execution(runtime)
        held = self.interrupt(runtime, paused)
        original_holds = copy.deepcopy(held['resources'])
        self.command(runtime, 'CancelRun', reason='Explicit fixture cancellation after uncertain effect')
        self.reconcile(runtime, reconciliation_document(runtime.report(self.run_id), outcome='unknown'))
        unknown = runtime.report(self.run_id)
        self.assertEqual(unknown['status'], 'cancelling')
        self.assertEqual(unknown['resources'], original_holds)
        before_unknown_finish = self.snapshot(runtime)
        with self.assertRaisesRegex(TaskError, 'Unknown .*cannot finish cancellation'):
            self.reconcile(runtime, reconciliation_document(unknown, outcome='unknown',
                           return_to_origin=True, finish=True), finish=True)
        self.assertEqual(self.snapshot(runtime), before_unknown_finish)
        self.reconcile(runtime, reconciliation_document(unknown, outcome='not_performed'))
        resolved = runtime.report(self.run_id)
        identity = held['pending_operation']['intent_id']
        self.assertEqual(resolved['bookings'][identity]['outcome'], 'not_performed')
        unintroduced_output = 'material:' + resolved['sonication']['intents'][identity]['material_after_id']
        self.assertEqual(set(resolved['resources']), set(original_holds) - {unintroduced_output})
        self.assertIsNone(resolved['pending_operation'])
        incomplete = reconciliation_document(resolved, return_to_origin=True, finish=True)
        incomplete['dispositions'] = []
        at_device = reconciliation_document(resolved, finish=True)
        for document, message in [(incomplete, 'Complete explicit material dispositions'),
                                  (at_device, 'original rack place')]:
            with self.subTest(rejection=message):
                before_invalid = self.snapshot(runtime)
                with self.assertRaisesRegex(TaskError, message):
                    self.reconcile(runtime, document, finish=True)
                self.assertEqual(self.snapshot(runtime), before_invalid)
        final_document = reconciliation_document(resolved, return_to_origin=True, finish=True)
        request = str(uuid.uuid4())
        response = self.reconcile(runtime, final_document, finish=True, request=request)
        self.assertEqual(response['outcome'], 'completed')
        final = runtime.report(self.run_id)
        self.assertEqual(final['status'], 'cancelled')
        self.assertEqual(final['resources'], [])
        intent = final['sonication']['intents'][identity]
        self.assertEqual(final['inventory']['vessels'][intent['vessel_id']]['location'], intent['original_rack_location'])
        self.assertNotIn(intent['material_after_id'], final['inventory']['materials'])
        self.assertEqual(final['remaining'][intent['material_before_id']]['value'], 300)
        for material in final['inventory']['materials'].values():
            if material['disposition'] != 'consumed':
                self.assertIsNotNone(material['disposition_confirmation'])
        with Journal(runtime.journal_path) as journal:
            self.assertEqual(journal.owners(), {})
        before_retry = self.snapshot(runtime)
        self.assertEqual(self.reconcile(runtime, final_document, finish=True, request=request), response)
        self.assertEqual(self.snapshot(runtime), before_retry)

    @staticmethod
    def wire_report(report):
        result = copy.deepcopy(report)
        result.pop('trace')
        result['wire_projection'] = {'format': 'solidcraftbot.s09-sila2-wire-report/1',
            'trace': 'metadata_only', 'full_journal': 'private root journal and evidence export'}
        return result

    def explicit_client_proposal(self, runtime, report, *, outcome=None):
        before = self.snapshot(runtime)
        original = copy.deepcopy(report)
        wire = self.wire_report(report)
        with patch('sonication_sila2_runtime.Journal', side_effect=AssertionError('Client proposal opened a Root journal')):
            full = reconciliation_document(report, outcome=outcome)
            proposal = reconciliation_document(wire, outcome=outcome)
        self.assertEqual(report, original)
        self.assertEqual(self.snapshot(runtime), before)
        self.assertEqual({key: value for key, value in proposal.items() if key != 'observations'},
                         {key: value for key, value in full.items() if key != 'observations'})
        normalized = lambda document: {item['vessel_id']: (set(item['material_ids']), item['location'])
                                       for item in document['observations']}
        self.assertEqual(normalized(proposal), normalized(full))
        return proposal

    def crash_and_resume_boundary(self, point):
        folder = 'recovery-' + point
        old = self.runtime(folder=folder, pause_after=point)
        self.create(old, scenario='restart')
        paused = self.paused_execution(old, crash=True)
        before = self.snapshot(old)
        paused['crash_requested'].set()
        paused['thread'].join(5)
        self.assertFalse(paused['thread'].is_alive(), point)
        self.assertIsInstance(paused['result'].get('error'), InjectedProcessCrash, point)
        self.assertEqual(self.snapshot(old), before)
        self.assertTrue(before['state']['resources'])
        old.close()
        restarted = self.runtime(folder=folder)
        self.assertEqual(restarted.server_uuid, old.server_uuid)
        self.assertNotEqual(restarted.boot_id, old.boot_id)
        with self.assertRaisesRegex(TaskError, 'ResumeRun'):
            self.command(restarted, 'RunUntilDecision')
        self.assertEqual(self.snapshot(restarted), before)
        self.command(restarted, 'ResumeRun', resume=True)
        resumed = self.snapshot(restarted)
        for key in ('inventory', 'bookings', 'resources', 'pending_operation'):
            self.assertEqual(resumed['state'][key], before['state'][key], (point, key))
        self.assertNotEqual(resumed['state']['session'], before['state']['session'])
        self.assertEqual(resumed['state']['network']['commands'][paused['request']]['status'], 'uncertain')
        replay = self.command(restarted, 'RunUntilDecision', request=paused['request'])
        self.assertEqual(replay['outcome'], 'uncertain')
        self.assertEqual(self.snapshot(restarted), resumed)
        return restarted, before

    def assert_recovered_s09(self, runtime):
        response = self.command(runtime, 'RunUntilDecision')
        self.assertEqual(response['outcome'], 'completed')
        report = runtime.report(self.run_id)
        prefix = fixture_values()['scenarios']['restart']['prefix']
        self.assertEqual(set(report['bookings']), {prefix + suffix for suffix in (
            '.InputPreparation', '.Sonication', '.SizeWithdrawal')})
        self.assertTrue(all(item['outcome'] == 'performed' for item in report['bookings'].values()))
        intent = report['sonication']['intents'][prefix + '.Sonication']
        self.assertEqual(len(report['sonication']['intents']), 1)
        self.assertEqual(len(intent['size_records']), 1)
        self.assertEqual(report['remaining'][intent['material_after_id']],
                         {'value': 295, 'unit': 'uL', 'knowledge': 'known'})
        qc = report['bookings'][prefix + '.SizeWithdrawal']
        self.assertEqual(qc['actual_inputs'], [
            {'material_id': intent['material_after_id'], 'quantity': {'value': 5, 'unit': 'uL'}}])
        stage = report['sop']['stages'][intent['stage_run_id']]
        self.assertEqual(stage['status'], 'completed')
        phase = stage['phases']['S09.input_preparation']
        self.assertEqual(len(phase['times']), 1)
        self.assertEqual(len(phase['temperatures']), 1)
        completed = [event['payload']['stage_run_id'] for event in report['trace']
                     if event['kind'] == 'complete_stage']
        self.assertEqual(sorted(completed), [prefix + '.Stage.' + name for name in ('S01', 'S02', 'S09')])
        self.assertEqual(report['status'], 'working')
        self.assertTrue(report['resources'])
        return report

    def recover_boundary(self, point):
        runtime, before = self.crash_and_resume_boundary(point)
        pending = before['state']['pending_operation']
        report = runtime.report(self.run_id)
        proposal = self.explicit_client_proposal(runtime, report, outcome='performed' if pending else None)
        if pending:
            self.assertIsNone(proposal['sonication'])
            self.assertEqual(proposal['material']['intent_id'], pending['intent_id'])
        response = self.reconcile(runtime, proposal)
        self.assertEqual(response['outcome'], 'completed')
        final = self.assert_recovered_s09(runtime)
        for identity, booking in before['state']['bookings'].items():
            if booking['outcome'] == 'performed':
                self.assertEqual(final['bookings'][identity], booking, (point, identity))
        for stage_id, stage in before['state']['sop']['stages'].items():
            if stage['stage_id'] == 'S09':
                for kind in ('times', 'temperatures'):
                    previous = stage['phases']['S09.input_preparation'][kind]
                    if previous:
                        self.assertEqual(final['sop']['stages'][stage_id]['phases']['S09.input_preparation'][kind],
                                         previous, (point, kind))

    def test_recovery_after_opening_complete_does_not_repeat_stage_completion(self):
        self.recover_boundary('opening_complete')

    def test_recovery_after_input_preparation_intent_requires_explicit_material_effect(self):
        self.recover_boundary('input_preparation_intent')

    def test_recovery_after_phase_time_preserves_time_and_completes_missing_temperature(self):
        self.recover_boundary('phase_time')

    def test_recovery_after_qc_withdrawal_intent_books_exactly_one_aliquot(self):
        self.recover_boundary('qc_withdrawal_intent')

    def test_recovery_after_qc_confirmation_preserves_consumption_and_adds_size_original(self):
        self.recover_boundary('qc_confirmed')

    def test_material_resolution_rejects_foreign_identity_actuals_and_mixed_effects_without_events(self):
        for point in ('input_preparation_intent', 'qc_withdrawal_intent'):
            with self.subTest(checkpoint=point):
                runtime = self.runtime(folder='invalid-' + point, pause_after=point)
                self.create(runtime, scenario='restart')
                held = self.interrupt(runtime, self.paused_execution(runtime))
                valid = self.explicit_client_proposal(runtime, held, outcome='performed')
                self.assertIsNone(valid['sonication'])
                self.assertIsNotNone(valid['material'])
                foreign_id = copy.deepcopy(valid)
                foreign_id['material']['intent_id'] = 'Foreign.Unowned.MaterialIntent'
                wrong_inputs = copy.deepcopy(valid)
                wrong_inputs['material']['actual_inputs'][0]['quantity']['value'] += 1
                wrong_outputs = copy.deepcopy(valid)
                wrong_outputs['material']['actual_outputs'] = [
                    {'material_id': 'Foreign.Output', 'quantity': {'value': 300, 'unit': 'uL'}}]
                mixed = copy.deepcopy(valid)
                mixed['sonication'] = {'outcome': 'not_performed'}
                for label, document in [('foreign_id', foreign_id), ('wrong_inputs', wrong_inputs),
                                        ('wrong_outputs', wrong_outputs), ('mixed_effects', mixed)]:
                    with self.subTest(rejection=label):
                        before = self.snapshot(runtime)
                        with self.assertRaises((TaskError, ValueError)):
                            self.reconcile(runtime, document)
                        self.assertEqual(self.snapshot(runtime), before)
                self.assertEqual(self.reconcile(runtime, valid)['outcome'], 'completed')
                state = self.snapshot(runtime)['state']
                self.assertIsNone(state['pending_operation'])
                self.assertEqual(state['bookings'][valid['material']['intent_id']]['outcome'], 'performed')
                self.assertTrue(state['resources'])
                runtime.close()

    def test_cancel_with_open_side_effect_holds_unknown_and_finishes_after_not_performed(self):
        for point in ('input_preparation_intent', 'qc_withdrawal_intent'):
            with self.subTest(checkpoint=point):
                runtime = self.runtime(folder='cancel-' + point, pause_after=point)
                self.create(runtime, scenario='cancel')
                held = self.interrupt(runtime, self.paused_execution(runtime))
                intent_id = held['pending_operation']['intent_id']
                self.command(runtime, 'CancelRun', reason='Explicit cancellation with open fixture side effect')
                self.reconcile(runtime, reconciliation_document(runtime.report(self.run_id), outcome='unknown'))
                unknown = runtime.report(self.run_id)
                self.assertEqual(unknown['bookings'][intent_id]['outcome'], 'unknown')
                self.assertEqual(unknown['resources'], held['resources'])
                before_finish = self.snapshot(runtime)
                with self.assertRaises(TaskError):
                    self.reconcile(runtime, reconciliation_document(unknown, outcome='unknown',
                                   return_to_origin=True, finish=True), finish=True)
                self.assertEqual(self.snapshot(runtime), before_finish)
                self.reconcile(runtime, reconciliation_document(unknown, outcome='not_performed'))
                resolved = runtime.report(self.run_id)
                self.assertIsNone(resolved['pending_operation'])
                self.assertEqual(resolved['bookings'][intent_id]['outcome'], 'not_performed')
                self.assertTrue(resolved['resources'])
                self.assertEqual(self.reconcile(runtime, reconciliation_document(resolved,
                    return_to_origin=True, finish=True), finish=True)['outcome'], 'completed')
                final = runtime.report(self.run_id)
                self.assertEqual(final['status'], 'cancelled')
                self.assertEqual(final['resources'], [])
                self.assertEqual(final['bookings'][intent_id]['outcome'], 'not_performed')
                for output in final['bookings'][intent_id]['request']['outputs']:
                    self.assertNotIn(output['material_id'], final['inventory']['materials'])
                with Journal(runtime.journal_path) as journal:
                    self.assertEqual(journal.owners(), {})
                runtime.close()


if __name__ == '__main__':
    unittest.main()
