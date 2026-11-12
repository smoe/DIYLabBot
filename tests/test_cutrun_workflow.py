"""Synthetic CUT&RUN effects retain identity, time uncertainty and stop evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError
from material_workflow import MaterialWorkflow
import material_ledger as ledger
from cutrun_workflow import CutRunWorkflow


class CutrunWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'cutrun.sqlite3'
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.flow = CutRunWorkflow.create(self.journal, run_id='SYN.CUTRUN.TEST')
        self.definition = copy.deepcopy(self.flow.state['definition'])
        self.actor = self.definition['execution']['stop_actors'][0]
        self.flow.act('accept_inventory', self.actor, observations=self.flow.inventory_observations())
        self.flow.act('workspace_clear', self.actor, confirmed=True)
        self.flow.act('claim', self.actor)
        self.serial = 0

    def snapshot(self):
        # Fixture construction uses the journal's checked prefix view. Assertions,
        # reports and final acceptance still exercise full history reads.
        return self.flow.journal.get_current(self.flow.run_id)[0]

    def plan(self, branch_id=None):
        plans = self.definition['preparation_plan']['branches']
        return plans[0] if branch_id is None else next(item for item in plans if item['id'] == branch_id)

    def branch(self, branch_id=None):
        return self.snapshot()['process']['branches'][self.plan(branch_id)['id']]

    def next_step(self, branch_id=None):
        plan = self.plan(branch_id)
        return plan['steps'][self.branch(plan['id'])['cursor']]

    def identity(self, label):
        self.serial += 1
        return f'SYN.Process.{label}.{self.serial}'

    def begin(self, branch_id=None, operation=None):
        plan = self.plan(branch_id)
        step = self.next_step(plan['id'])
        intent = self.identity(operation or step['operation'])
        self.flow.act('begin_phase', self.actor, branch_id=plan['id'],
                      operation=operation or step['operation'], intent_id=intent,
                      reaction_id=self.branch(plan['id'])['reaction_id'])
        return intent

    def temperature(self, branch_id, start_s, end_s, value):
        self.flow.act('observe_temperature', self.actor, branch_id=branch_id,
                      reaction_id=self.branch(branch_id)['reaction_id'], start_s=start_s,
                      end_s=end_s, temperature_deg_c=value)

    def advance(self, seconds):
        if seconds > 0:
            self.flow.act('advance_time', self.actor, seconds=seconds)

    def outputs(self, intent_id):
        state = self.snapshot()
        request = state['bookings'][intent_id]['request']
        volumes = state['definition']['execution']['bookkeeping_volumes_ul']
        roles = {'identified_reaction_material': 'reaction', 'product_containing_supernatant': 'supernatant',
                 'retained_bead_remainder': 'bead_remainder', 'retained_input_pellet': 'bead_remainder',
                 'column_bound_analyte': 'column', 'purified_dna': 'eluate', 'retained_column_residue': 'residue'}
        return [{'material_id': item['material_id'],
                 'quantity': {'value': volumes[roles[item['role']]] if item['role'] in roles else None, 'unit': 'uL'}}
                for item in request['outputs']]

    def phase(self, branch_id=None, *, temperature=True, observations=None):
        plan = self.plan(branch_id)
        step = self.next_step(plan['id'])
        self.assertNotIn(step['operation'], {'activate_digest', 'stop_reaction'})
        start = self.snapshot()['logical_time_s']
        intent = self.begin(plan['id'])
        duration = step['parameters'].get('duration_s', {}).get('value', 0)
        self.advance(duration)
        target = step['parameters'].get('temperature_deg_c', {}).get('value')
        if temperature and target is not None and duration:
            self.temperature(plan['id'], start, self.snapshot()['logical_time_s'], target)
        receipt = {'completed': True}
        if step['operation'] == 'isolate_product':
            receipt['cleared'] = True
        if step['operation'] == 'check_input_size':
            receipt['fragment_size_bp'] = 300
        if self.snapshot()['process']['operations'][intent]['material_effect']:
            receipt['outputs'] = self.outputs(intent)
        if observations:
            receipt.update(observations)
        self.flow.act('confirm_phase', self.actor, intent_id=intent,
                      reaction_id=self.branch(plan['id'])['reaction_id'], observations=receipt,
                      reason='Explicit synthetic phase observations')
        return intent

    def before_activation(self, branch_id=None, *, ready=True):
        plan = self.plan(branch_id)
        while self.next_step(plan['id'])['operation'] != 'activate_digest':
            self.phase(plan['id'])
        if ready:
            self.flow.act('confirm_stop_readiness', self.actor, branch_id=plan['id'],
                          reaction_id=self.branch(plan['id'])['reaction_id'], access=True, mixing_available=True)
        return plan['id']

    def activate(self, branch_id=None, *, mixed=True):
        branch_id = self.before_activation(branch_id)
        step = self.next_step(branch_id)
        intent = self.begin(branch_id)
        self.advance(self.definition['execution']['activation_service_s'])
        self.flow.act('confirm_phase', self.actor, intent_id=intent,
                      reaction_id=self.branch(branch_id)['reaction_id'],
                      observations={'dose_ul': step['parameters']['volume_ul']['value'], 'mixed': mixed},
                      reason='Explicit synthetic activation receipt')
        return branch_id, intent

    def stop(self, branch_id, *, mixed=True, actor=None, nominal=True):
        actor = actor or self.actor
        branch = self.branch(branch_id)
        if nominal and branch['activation']['contact']['max_s'] is not None:
            duration = next(item for item in self.plan(branch_id)['steps'] if item['operation'] == 'activate_digest')['parameters']['duration_s']['value']
            self.advance(max(0, branch['activation']['contact']['max_s'] + duration - self.snapshot()['logical_time_s']))
        intent = self.identity('stop')
        self.flow.act('begin_stop', actor, branch_id=branch_id, reaction_id=branch['reaction_id'],
                      intent_id=intent, access=True, mixing_available=True)
        self.advance(self.definition['execution']['stop_service_s'])
        target = next(item for item in self.plan(branch_id)['steps'] if item['operation'] == 'activate_digest')['parameters']['temperature_deg_c']['value']
        self.temperature(branch_id, branch['activation']['contact']['min_s'], self.snapshot()['logical_time_s'], target)
        dose = self.definition['preparation_plan']['stop_plan']['dose_per_branch_ul']['value']
        self.flow.act('confirm_stop', actor, intent_id=intent, reaction_id=branch['reaction_id'],
                      actual_volume_ul=dose, mixed=mixed, reason='Explicit synthetic stop receipt')
        return intent, dose

    def complete_branch(self, branch_id=None):
        plan = self.plan(branch_id)
        while self.branch(plan['id'])['cursor'] < len(plan['steps']):
            operation = self.next_step(plan['id'])['operation']
            if operation == 'activate_digest':
                self.activate(plan['id'])
            elif operation == 'stop_reaction':
                self.stop(plan['id'])
            else:
                self.phase(plan['id'])
        return plan['id']

    def qc_record(self, branch_id, method='fluorometry', *, value=2, below=False):
        state = self.snapshot()
        return {'run_id': self.flow.run_id, 'attempt_id': state['attempt_id'],
                'reaction_id': self.branch(branch_id)['reaction_id'], 'branch_id': branch_id,
                'material_id': self.plan(branch_id)['product_material_id'], 'method': method,
                'stage': 'purified_dna', 'value': value, 'unit': 'ng/uL' if method == 'fluorometry' else 'Cq',
                'below_detection_limit': below}

    def qc_withdrawal(self, branch_id, method='fluorometry'):
        intent = self.identity('qc_' + method)
        reaction = self.branch(branch_id)['reaction_id']
        self.flow.act('begin_qc', self.actor, branch_id=branch_id, reaction_id=reaction,
                      intent_id=intent, method=method)
        volume = self.definition['preparation_plan']['qc']['aliquot_volumes_ul'][method]['value']
        self.flow.act('confirm_qc_withdrawal', self.actor, intent_id=intent, reaction_id=reaction,
                      actual_volume_ul=volume, reason='Explicit synthetic product QC withdrawal')
        return intent

    def import_record(self, record):
        raw = json.dumps(record, sort_keys=True).encode()
        self.flow.act('import_qc', self.actor, artifact=raw, file_name='synthetic-qc.json')
        return raw, digest(raw)

    def test_closed_format_and_generic_material_commands_cannot_bypass_process_gates(self):
        with self.assertRaises(TaskError):
            MaterialWorkflow.open(self.journal, self.flow.run_id, resume=True)
        from run_material_lifecycle import fixture_declarations
        with Journal(Path(self.temp.name) / 'legacy.sqlite3') as legacy_journal:
            materials, vessels, _, _ = fixture_declarations('cutrun', 'SYN.Legacy.Cutrun')
            legacy = MaterialWorkflow.create(legacy_journal, 'cutrun', materials=materials,
                                             vessels=vessels, run_id='SYN.Legacy.Cutrun')
            old_state = legacy.state
            old_history = legacy_journal.history(legacy.run_id)
            with self.assertRaises(TaskError):
                CutRunWorkflow.open(legacy_journal, legacy.run_id, resume=True)
            self.assertEqual(legacy.state, old_state)
            self.assertEqual(legacy_journal.history(legacy.run_id), old_history)
        revision = len(self.journal.history(self.flow.run_id))
        for command in ['begin_effect', 'confirm_effect', 'resolve_quantity', 'take', 'place']:
            with self.subTest(command=command), self.assertRaises(TaskError):
                self.flow.act(command, self.actor)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)
        with self.assertRaises(TaskError):
            self.begin(operation='elute')

    def test_writer_constructor_rejects_changed_runtime_pins_without_mutating_the_run(self):
        before = self.flow.state
        revision = len(self.journal.history(self.flow.run_id))
        with patch('cutrun_workflow.digest', return_value='0' * 64):
            with self.assertRaisesRegex(TaskError, 'Runtime source changed'):
                CutRunWorkflow(self.journal, self.flow.run_id, self.flow.session)
            reader = CutRunWorkflow(self.journal, self.flow.run_id, None)
            self.assertEqual(reader.state, before)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)

    def test_timed_phase_requires_elapsed_interval_and_explicit_completion(self):
        self.phase()
        step = self.next_step()
        self.assertGreater(step['parameters']['duration_s']['value'], 0)
        intent = self.begin()
        with self.assertRaises(ObservationError):
            self.flow.act('confirm_phase', self.actor, intent_id=intent,
                          reaction_id=self.branch()['reaction_id'], observations={'completed': True},
                          reason='A timer or assumed completion is insufficient')
        self.assertEqual(self.flow.state['process']['operations'][intent]['status'], 'intent')
        self.assertTrue(self.flow.state['recovery_required'])

    def test_identical_phase_receipt_is_idempotent_and_conflicting_receipt_cannot_reapply_effect(self):
        intent = self.phase()
        operation = self.flow.state['process']['operations'][intent]
        receipt = copy.deepcopy(operation['confirmation'])
        before = self.flow.state
        revision = len(self.journal.history(self.flow.run_id))
        self.flow.act('confirm_phase', self.actor, intent_id=intent, reaction_id=operation['reaction_id'],
                      observations=receipt['observations'], reason=receipt['reason'])
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)
        self.assertEqual(self.flow.state, before)
        changed = copy.deepcopy(receipt['observations'])
        changed['completed'] = False
        with self.assertRaises(TaskError):
            self.flow.act('confirm_phase', self.actor, intent_id=intent, reaction_id=operation['reaction_id'],
                          observations=changed, reason=receipt['reason'])
        self.assertEqual(self.flow.state, before)

    def test_missing_temperature_coverage_is_preserved_as_a_quality_hold(self):
        self.phase()
        self.phase(temperature=False)
        codes = {item['code'] for item in self.branch()['deviations']}
        self.assertIn('temperature_coverage_missing', codes)
        self.assertTrue(self.flow.state['recovery_required'])
        self.flow.act('reconcile', self.actor, observations=self.flow.inventory_observations(),
                      workspace_clear=True, reason='Inventory agreement cannot erase temperature history')
        self.assertTrue(self.flow.state['recovery_required'])

    def test_activation_mixing_is_distinct_from_possible_contact_and_stopping_remains_available(self):
        branch_id, activation = self.activate(mixed=False)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'possibly_active')
        self.assertTrue(self.flow.state['recovery_required'])
        stop, dose = self.stop(branch_id)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertEqual(self.flow.state['process']['operations'][activation]['status'], 'performed')
        self.assertEqual(self.flow.state['process']['operations'][stop]['status'], 'performed')

    def test_activation_requires_explicit_stop_readiness_before_contact_intent(self):
        branch_id = self.before_activation(ready=False)
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.begin(branch_id)
        self.assertEqual(self.flow.state, before)
        self.flow.act('confirm_stop_readiness', self.actor, branch_id=branch_id,
                      reaction_id=self.branch(branch_id)['reaction_id'], access=False, mixing_available=True)
        with self.assertRaises(TaskError):
            self.begin(branch_id)
        self.assertIsNone(self.branch(branch_id)['activation'])

    def test_stop_dose_and_mixing_are_separate_and_a_mixing_receipt_does_not_redose(self):
        branch_id, activation = self.activate()
        stop, dose = self.stop(branch_id, mixed=False)
        state = self.flow.state
        stock = state['definition']['execution']['branches'][branch_id]['stop_material_id']
        balance = ledger.remaining(state, stock)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stop_dosed_unmixed')
        self.assertTrue(state['recovery_required'])
        self.flow.act('confirm_stop_mixing', self.actor, intent_id=stop,
                      reaction_id=self.branch(branch_id)['reaction_id'], mixed=True,
                      reason='Explicit synthetic mixing observation after dosing')
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertEqual(ledger.remaining(self.flow.state, stock), balance)
        with self.assertRaises(TaskError):
            self.flow.act('confirm_stop', self.actor, intent_id=stop,
                          reaction_id=self.branch(branch_id)['reaction_id'], actual_volume_ul=dose,
                          mixed=True, reason='Must not repeat the dose to fix mixing')

    def test_mixing_only_command_cannot_shift_an_already_observed_combined_stop(self):
        branch_id, activation = self.activate()
        stop, dose = self.stop(branch_id, mixed=True)
        instant = copy.deepcopy(self.branch(branch_id)['stop']['completed_at'])
        self.advance(10)
        with self.assertRaises(TaskError):
            self.flow.act('confirm_stop_mixing', self.actor, intent_id=stop,
                          reaction_id=self.branch(branch_id)['reaction_id'], mixed=True,
                          reason='A later observation cannot move the already confirmed stop instant')
        self.assertEqual(self.branch(branch_id)['stop']['completed_at'], instant)

    def test_time_progresses_under_hold_and_a_late_stop_is_recorded_without_nominal_success(self):
        branch_id, activation = self.activate()
        deadline = self.branch(branch_id)['activation']['stop_deadline_s']
        self.advance(deadline - self.flow.state['logical_time_s'] + 1)
        self.assertTrue(self.flow.state['recovery_required'])
        before = self.flow.state['logical_time_s']
        self.advance(5)
        self.assertEqual(self.flow.state['logical_time_s'], before + 5)
        stop, dose = self.stop(branch_id, nominal=False)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertIn('late_stop', {item['code'] for item in self.branch(branch_id)['deviations']})
        self.assertTrue(self.flow.state['recovery_required'])
        self.assertFalse(self.flow.report()['passed'])

    def test_restart_after_activation_intent_keeps_possible_activity_and_requires_time_gap_evidence(self):
        branch_id = self.before_activation()
        activation = self.begin(branch_id)
        initial_deadline = self.branch(branch_id)['activation']['stop_deadline_s']
        self.flow.close()
        resumed = CutRunWorkflow.open(self.journal, self.flow.run_id, resume=True)
        self.flow = resumed
        self.assertTrue(self.flow.state['clock']['gap_required'])
        self.assertIsNone(self.flow.state['clock']['uncertainty_s'])
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'possibly_active')
        self.assertEqual(self.branch(branch_id)['activation']['stop_deadline_s'], initial_deadline)
        self.flow.act('resolve_time_gap', self.actor, min_s=10, max_s=None,
                      reason='Synthetic interruption with unbounded elapsed time')
        self.assertIsNone(self.flow.state['clock']['uncertainty_s'])
        self.assertEqual(self.flow.state['process']['operations'][activation]['status'], 'intent')
        stop, dose = self.stop(branch_id, nominal=False)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertEqual(self.flow.state['process']['operations'][activation]['status'], 'intent')
        self.assertEqual(self.flow.state['pending_operation'], {'intent_id': activation})

    def test_abrupt_process_exit_after_activation_intent_preserves_pending_contact_and_requires_gap_resolution(self):
        branch_id = self.before_activation()
        self.flow.close()
        activation = 'SYN.HardCrash.Activation'
        script = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from manual_tasks import Journal
from cutrun_workflow import CutRunWorkflow
journal = Journal(sys.argv[2])
flow = CutRunWorkflow.open(journal, sys.argv[3], resume=True)
actor, branch_id, intent_id = sys.argv[4:7]
reaction_id = flow.state['process']['branches'][branch_id]['reaction_id']
flow.act('resolve_time_gap', actor, min_s=0, max_s=0, reason='Explicit synthetic gap evidence before crash fixture')
flow.act('reconcile', actor, observations=flow.inventory_observations(), workspace_clear=True,
         reason='Explicit synthetic inventory before crash fixture')
flow.act('confirm_stop_readiness', actor, branch_id=branch_id, reaction_id=reaction_id,
         access=True, mixing_available=True)
flow.act('begin_phase', actor, branch_id=branch_id, operation='activate_digest',
         intent_id=intent_id, reaction_id=reaction_id)
os._exit(23)
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT / 'scripts'), str(self.path),
                                 self.flow.run_id, self.actor, branch_id, activation], capture_output=True, text=True)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        old_state = self.journal.state(self.flow.run_id)[0]
        stale = CutRunWorkflow(self.journal, self.flow.run_id, old_state['session'])
        with Journal(self.path) as reopened:
            resumed = CutRunWorkflow.open(reopened, self.flow.run_id, resume=True)
            state = resumed.state
            self.assertTrue(state['clock']['gap_required'])
            self.assertIsNone(state['clock']['uncertainty_s'])
            self.assertEqual(state['process']['branches'][branch_id]['reaction_state'], 'possibly_active')
            self.assertEqual(state['process']['operations'][activation]['status'], 'intent')
            self.assertEqual(state['pending_operation'], {'intent_id': activation})
            self.assertIsNone(state['process']['operations'][activation]['confirmation'])
            with self.assertRaises(TaskError):
                stale.act('advance_time', self.actor, seconds=1)
            before = copy.deepcopy(state['bookings'])
            with self.assertRaises(TaskError):
                resumed.act('begin_phase', self.actor, branch_id=branch_id, operation='activate_digest',
                            intent_id='SYN.BlindReplay', reaction_id=state['process']['branches'][branch_id]['reaction_id'])
            self.assertEqual(resumed.state['bookings'], before)
            self.assertNotIn('SYN.BlindReplay', resumed.state['process']['operations'])

    def test_blocked_stop_path_is_durable_and_does_not_pretend_dosing_or_stopping(self):
        branch_id, activation = self.activate()
        stock = self.flow.state['definition']['execution']['branches'][branch_id]['stop_material_id']
        before = ledger.remaining(self.flow.state, stock)
        self.flow.act('begin_stop', self.actor, branch_id=branch_id,
                      reaction_id=self.branch(branch_id)['reaction_id'], intent_id='SYN.Blocked.Stop',
                      access=False, mixing_available=True)
        self.assertIsNone(self.branch(branch_id)['stop'])
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'active')
        self.assertEqual(ledger.remaining(self.flow.state, stock), before)
        self.assertTrue(self.flow.state['recovery_required'])
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertEqual(event['kind'], 'begin_stop')
        self.assertIs(event['payload']['access'], False)
        self.assertIn('stop_path_blocked', {item['code'] for item in self.branch(branch_id)['deviations']})

    def test_independent_stop_observer_can_stop_but_cannot_confirm_another_actors_activation(self):
        branch_id = self.before_activation()
        activation = self.begin(branch_id)
        other = self.flow.state['definition']['execution']['stop_actors'][1]
        self.advance(self.flow.state['definition']['execution']['activation_service_s'])
        with self.assertRaises(TaskError):
            self.flow.act('resolve_effect', other, intent_id=activation,
                          reaction_id=self.branch(branch_id)['reaction_id'], outcome='not_performed',
                          observations={}, reason='A stop observer does not own ordinary effects')
        stop, dose = self.stop(branch_id, actor=other, nominal=False)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertEqual(self.flow.state['process']['operations'][activation]['status'], 'intent')

    def test_two_protective_stops_are_independent_when_the_first_stop_outcome_is_unknown(self):
        plans = [plan for plan in self.flow.state['definition']['preparation_plan']['branches'] if plan['workflow'] == 'cutrun']
        first, second = plans[0]['id'], plans[1]['id']
        self.before_activation(first)
        self.before_activation(second)
        self.activate(first)
        self.activate(second)
        for plan in plans:
            branch = self.branch(plan['id'])
            duration = next(step for step in plan['steps'] if step['operation'] == 'activate_digest')['parameters']['duration_s']['value']
            self.advance(max(0, branch['activation']['contact']['max_s'] + duration - self.flow.state['logical_time_s']))
        first_stop = self.identity('uncertain_stop')
        self.flow.act('begin_stop', self.actor, branch_id=first, reaction_id=self.branch(first)['reaction_id'],
                      intent_id=first_stop, access=True, mixing_available=True)
        self.flow.act('mark_effect_unknown', self.actor, intent_id=first_stop,
                      reason='Synthetic lost first stop acknowledgement')
        second_stop, dose = self.stop(second, nominal=False)
        self.assertEqual(self.branch(second)['reaction_state'], 'stopped')
        self.assertEqual(self.flow.state['process']['operations'][second_stop]['status'], 'performed')
        self.assertEqual(self.flow.state['process']['operations'][first_stop]['status'], 'unknown')
        first_stock = self.flow.state['definition']['execution']['branches'][first]['stop_material_id']
        self.assertIsNone(ledger.remaining(self.flow.state, first_stock)['value'])
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.flow.act('begin_stop', self.actor, branch_id=first, reaction_id=self.branch(first)['reaction_id'],
                          intent_id='SYN.Redose.UnknownStop', access=True, mixing_available=True)
        self.assertEqual(self.flow.state, before)

    def test_resolved_performed_activation_preserves_the_observed_protective_stop_and_original_deadline(self):
        branch_id = self.before_activation()
        step = self.next_step(branch_id)
        activation = self.begin(branch_id)
        deadline = self.branch(branch_id)['activation']['stop_deadline_s']
        self.flow.act('mark_effect_unknown', self.actor, intent_id=activation,
                      reason='Synthetic unknown activation acknowledgement')
        self.stop(branch_id, nominal=False)
        receipt = {'intent_id': activation, 'reaction_id': self.branch(branch_id)['reaction_id'],
                   'outcome': 'performed', 'observations': {'dose_ul': step['parameters']['volume_ul']['value'], 'mixed': True},
                   'reason': 'Explicit synthetic reconciliation of activation after protective stopping'}
        self.flow.act('resolve_effect', self.actor, **receipt)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertEqual(self.branch(branch_id)['activation']['stop_deadline_s'], deadline)
        self.assertEqual(self.flow.state['process']['operations'][activation]['status'], 'performed')
        self.assertIsNone(self.flow.state['pending_operation'])
        before = self.flow.state['bookings']
        revision = len(self.journal.history(self.flow.run_id))
        self.flow.act('resolve_effect', self.actor, **receipt)
        self.assertEqual(self.flow.state['bookings'], before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)

    def test_activation_absent_after_protective_stop_needs_abnormal_quarantine_not_nominal_product(self):
        branch_id = self.before_activation()
        activation = self.begin(branch_id)
        self.flow.act('mark_effect_unknown', self.actor, intent_id=activation, reason='Synthetic possible activation')
        self.flow.act('cancel', self.actor, reason='Explicit synthetic cancellation during possible chemistry')
        owners = self.journal.owners()
        with self.assertRaisesRegex(TaskError, 'termination|mixing'):
            self.flow.act('finish_cancel', self.actor, workspace_clear=True)
        self.assertEqual(self.journal.owners(), owners)
        self.stop(branch_id, nominal=False)
        self.flow.act('resolve_effect', self.actor, intent_id=activation,
                      reaction_id=self.branch(branch_id)['reaction_id'], outcome='not_performed', observations={},
                      reason='Explicit synthetic observation that activation was not performed')
        self.assertNotIn(self.plan(branch_id)['product_material_id'], self.flow.state['inventory']['materials'])
        current = self.branch(branch_id)['current_material_id']
        with self.assertRaises(TaskError):
            self.flow.act('set_disposition', self.actor, material_id=current, disposition='retained',
                          reason='A changed branch is not a nominal product')
        self.flow.act('abnormal_termination', self.actor, branch_id=branch_id,
                      reaction_id=self.branch(branch_id)['reaction_id'], reason='Explicit synthetic abnormal branch termination')
        for material_id, material in self.flow.state['inventory']['materials'].items():
            if material['disposition'] == 'consumed':
                continue
            self.flow.act('set_disposition', self.actor, material_id=material_id,
                          disposition='quarantined' if material_id == current else 'retained',
                          reason='Explicit synthetic material disposition after abnormal termination')
        self.flow.act('confirm_inventory', self.actor, observations=self.flow.inventory_observations())
        self.flow.act('finish_cancel', self.actor, workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertEqual(self.flow.state['inventory']['materials'][current]['disposition'], 'quarantined')
        self.assertFalse(self.flow.report()['passed'])

    def test_contradictory_temperature_reported_after_stopping_cannot_be_overlaid_away(self):
        branch_id, activation = self.activate()
        self.stop(branch_id)
        branch = self.branch(branch_id)
        start = branch['activation']['contact']['min_s']
        end = branch['stop']['completed_at']['min_s']
        target = next(step for step in self.plan(branch_id)['steps'] if step['operation'] == 'activate_digest')['parameters']['temperature_deg_c']['value']
        self.temperature(branch_id, start, end, target + 20)
        self.assertEqual(self.branch(branch_id)['reaction_state'], 'stopped')
        self.assertIn('temperature_out_of_range', {item['code'] for item in self.branch(branch_id)['deviations']})
        self.temperature(branch_id, start, end, target)
        self.flow.act('reconcile', self.actor, observations=self.flow.inventory_observations(),
                      workspace_clear=True, reason='A good overlay cannot erase contradictory historical temperature evidence')
        self.assertTrue(self.flow.state['recovery_required'])

    def test_dynamic_stop_capacity_rejects_a_new_activation_after_bounded_restart_uncertainty(self):
        plans = [plan for plan in self.flow.state['definition']['preparation_plan']['branches'] if plan['workflow'] == 'cutrun']
        first, second = plans[0]['id'], plans[1]['id']
        self.before_activation(first)
        self.before_activation(second)
        self.activate(first)
        self.flow.close()
        self.flow = CutRunWorkflow.open(self.journal, self.flow.run_id, resume=True)
        self.flow.act('resolve_time_gap', self.actor, min_s=0, max_s=120,
                      reason='Explicit synthetic bounded restart uncertainty')
        self.flow.act('reconcile', self.actor, observations=self.flow.inventory_observations(),
                      workspace_clear=True, reason='Explicit synthetic inventory reconciliation')
        for branch_id in (first, second):
            self.flow.act('confirm_stop_readiness', self.actor, branch_id=branch_id,
                          reaction_id=self.branch(branch_id)['reaction_id'], access=True, mixing_available=True)
        before = self.flow.state
        with self.assertRaisesRegex(TaskError, 'stop|deadline'):
            self.begin(second)
        self.assertEqual(self.flow.state, before)
        self.assertIsNone(self.branch(second)['activation'])

    def test_loss_of_stop_readiness_for_an_active_branch_holds_and_blocks_a_second_activation(self):
        plans = [plan for plan in self.definition['preparation_plan']['branches'] if plan['workflow'] == 'cutrun']
        first, second = plans[0]['id'], plans[1]['id']
        self.before_activation(first)
        self.before_activation(second)
        self.activate(first)
        self.flow.act('confirm_stop_readiness', self.actor, branch_id=first,
                      reaction_id=self.branch(first)['reaction_id'], access=False, mixing_available=True)
        self.assertIn('stop_readiness_lost', {item['code'] for item in self.branch(first)['deviations']})
        self.assertTrue(self.flow.state['recovery_required'])
        revision = len(self.journal.history(self.flow.run_id))
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.begin(second)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)
        self.assertEqual(self.flow.state, before)
        self.assertIsNone(self.branch(second)['activation'])

    def test_failed_phase_persistence_rolls_back_materials_process_cursor_and_artifact(self):
        intent = self.begin()
        observations = {'completed': True, 'outputs': self.outputs(intent)}
        before = self.flow.state
        revision = len(self.journal.history(self.flow.run_id))
        resources = copy.deepcopy(self.journal.owners())
        original = self.journal._event
        def fail_after_event(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Synthetic persistence failure after event insert')
        with patch.object(self.journal, '_event', side_effect=fail_after_event), self.assertRaises(RuntimeError):
            self.flow.act('confirm_phase', self.actor, intent_id=intent, reaction_id=self.branch()['reaction_id'],
                          observations=observations, reason='Synthetic phase observation', artifact=b'SYNTHETIC PHASE EVIDENCE')
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)
        self.assertEqual(self.journal.owners(), resources)

    def test_wrong_phase_reaction_identity_is_a_hold_and_does_not_consume_material(self):
        intent = self.begin()
        before = self.flow.state
        with self.assertRaises(ObservationError):
            self.flow.act('confirm_phase', self.actor, intent_id=intent,
                          reaction_id='SYN.ForeignReaction', observations={'completed': True, 'outputs': self.outputs(intent)},
                          reason='Synthetic wrong identity')
        self.assertEqual(self.flow.state['inventory'], before['inventory'])
        self.assertEqual(self.flow.state['process']['branches'], before['process']['branches'])
        self.assertTrue(self.flow.state['recovery_required'])

    def test_qc_import_preserves_invalid_original_bytes_and_cannot_debit_a_product(self):
        raw = b'{"run_id":"foreign","stage":"library"}'
        before = self.flow.state['bookings']
        self.flow.act('import_qc', self.actor, artifact=raw, file_name='invalid-qc.json')
        checksum = digest(raw)
        entry = self.flow.state['process']['qc_imports'][checksum]
        self.assertFalse(entry['accepted'])
        self.assertEqual(self.journal.artifact(checksum), raw)
        self.assertEqual(self.flow.state['bookings'], before)
        self.assertTrue(self.flow.state['recovery_required'])
        self.flow.act('reconcile', self.actor, observations=self.flow.inventory_observations(),
                      workspace_clear=True, reason='Inventory agreement does not resolve quarantined original QC evidence')
        self.assertEqual(self.flow.state['recovery_required'], 'quarantined_qc_artifact')
        with self.assertRaises(TaskError):
            self.begin()
        revision = len(self.journal.history(self.flow.run_id))
        self.flow.act('import_qc', self.actor, artifact=raw, file_name='invalid-qc.json')
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)

    def test_nonfinite_qc_bytes_are_quarantined_verbatim_without_poisoning_the_journal(self):
        before = self.flow.state['bookings']
        for value in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(value=value):
                raw = b'{"value":' + value + b'}'
                checksum = digest(raw)
                self.flow.act('import_qc', self.actor, artifact=raw, file_name='nonfinite-qc.json')
                entry = self.flow.state['process']['qc_imports'][checksum]
                self.assertFalse(entry['accepted'])
                self.assertIsNone(entry['record'])
                json.dumps(entry, allow_nan=False)
                self.assertEqual(self.journal.artifact(checksum), raw)
                self.assertEqual(self.flow.state['bookings'], before)

    def test_qc_rejects_wrong_identity_method_stage_and_unit_without_another_withdrawal(self):
        branch_id = self.complete_branch()
        self.qc_withdrawal(branch_id)
        before = copy.deepcopy(self.flow.state['bookings'])
        base = self.qc_record(branch_id)
        changes = {'run_id': 'foreign', 'attempt_id': 'foreign', 'reaction_id': 'foreign',
                   'branch_id': 'foreign', 'material_id': 'foreign', 'method': 'library_fragment_analysis',
                   'stage': 'library', 'unit': 'mg', 'below_detection_limit': 'false'}
        for key, value in changes.items():
            with self.subTest(key=key):
                raw, checksum = self.import_record({**base, key: value})
                self.assertFalse(self.flow.state['process']['qc_imports'][checksum]['accepted'])
                self.assertEqual(self.journal.artifact(checksum), raw)
                self.assertEqual(self.flow.state['bookings'], before)

    def test_below_detection_is_preserved_as_unknown_value_and_not_nominal_qc_success(self):
        branch_id = self.complete_branch()
        self.qc_withdrawal(branch_id)
        product = self.plan(branch_id)['product_material_id']
        balance = ledger.remaining(self.flow.state, product)
        raw, checksum = self.import_record(self.qc_record(branch_id, value=None, below=True))
        record = self.flow.state['process']['qc_imports'][checksum]
        self.assertTrue(record['accepted'])
        self.assertFalse(record['quantifiable'])
        self.assertIsNone(record['record']['value'])
        self.assertEqual(ledger.remaining(self.flow.state, product), balance)
        with self.assertRaises(TaskError):
            self.flow.act('review_qc', self.actor, reason='A detection limit is not quantitative biological success')
        self.assertEqual(self.journal.artifact(checksum), raw)

    def test_complete_synthetic_reference_retains_products_and_has_no_biological_success_claim(self):
        for plan in self.flow.state['definition']['preparation_plan']['branches']:
            branch_id = self.complete_branch(plan['id'])
            for method in ['fluorometry', 'qpcr']:
                self.qc_withdrawal(branch_id, method)
                raw, checksum = self.import_record(self.qc_record(branch_id, method))
                self.assertTrue(self.flow.state['process']['qc_imports'][checksum]['accepted'])
        state = self.flow.state
        ntc = state['definition']['preparation_plan']['qc']['ntc']
        self.import_record({'run_id': state['run_id'], 'attempt_id': state['attempt_id'],
            'reaction_id': state['attempt_id'] + '.NTC', 'branch_id': ntc['id'], 'material_id': None,
            'method': 'qpcr', 'stage': 'pcr_no_template_control', 'value': None, 'unit': 'Cq',
            'below_detection_limit': True})
        self.flow.act('review_qc', self.actor, reason='Explicit synthetic technical review only')
        for material_id, material in self.flow.state['inventory']['materials'].items():
            if material['disposition'] == 'consumed':
                continue
            self.flow.act('set_disposition', self.actor, material_id=material_id, disposition='retained',
                          reason='Explicit synthetic retention of products, remainders and unused aliquots')
        self.flow.act('confirm_inventory', self.actor, observations=self.flow.inventory_observations())
        self.flow.act('release', self.actor, workspace_clear=True)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertTrue(report['synthetic_process_executed'])
        self.assertFalse(report['biochemical_protocol_executed'])
        self.assertFalse(report['hardware_executed'])
        self.assertIsNone(report['biological_success'])
        self.assertEqual(report['resources'], [])
        self.assertEqual(len(report['process']['qc_imports']), 7)


if __name__ == '__main__':
    unittest.main()
