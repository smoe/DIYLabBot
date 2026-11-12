"""Root integration uses explicit software fixtures, never laboratory evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from cutrun_input_sonication_demo import FixtureSession
from cutrun_input_sonication_workflow import InputSonicationWorkflow
from cutrun_manual_sop_workflow import CutRunManualSopWorkflow
from cutrun_manual_workflow import CutRunManualWorkflow
from manual_process_clock import SystemClock
from manual_tasks import Journal, TaskError, digest
import material_ledger as ledger


class InputSonicationRuntimeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='input-sonication-test-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.journal = Journal(self.directory / 'journal.sqlite3')
        self.addCleanup(self.journal.close)
        self.fixture = FixtureSession(self.journal, 'TEST.InputSonication.Runtime', self.directory)
        self.serial = 0

    @property
    def flow(self):
        return self.fixture.flow

    def snapshot(self, flow=None):
        flow = self.flow if flow is None else flow
        return {'state': flow.state,
            'events': flow.journal.connection.execute(
                'SELECT sequence, document, sha256 FROM events WHERE run_id=? ORDER BY sequence',
                (flow.run_id,)).fetchall(), 'owners': flow.journal.owners()}

    def envelope(self, identity=None, source_kind='test_fixture'):
        self.serial += 1
        return {'observation_id': identity or 'TEST.IndependentObservation.' + str(self.serial),
            'source_kind': source_kind, 'observed_at': None,
            'source_ref': 'fixture://input-sonication/runtime-test', 'artifact_sha256': None}

    def act_on(self, flow, command, **data):
        return flow.act(command, self.fixture.actor, observation=self.envelope(), **data)

    def make_other(self, source, *, clock=None):
        journal = Journal(self.directory / ('other-' + str(self.serial) + '.sqlite3'))
        self.serial += 1
        self.addCleanup(journal.close)
        flow = InputSonicationWorkflow.create(journal, source,
            materials=copy.deepcopy(self.fixture.materials), vessels=copy.deepcopy(self.fixture.vessels),
            reactions=copy.deepcopy(self.fixture.reactions), actors=[self.fixture.actor],
            run_id='TEST.OtherSonication.' + str(self.serial),
            clock=self.fixture.clock if clock is None else clock,
            evidence_files=self.fixture.evidence_files)
        return flow

    def prepare(self):
        self.fixture.prepare_input()
        return self.flow.state

    def complete_fixture(self):
        self.fixture.begin()
        self.fixture.confirm()
        self.fixture.phase_evidence()
        self.fixture.size_evidence()
        self.fixture.complete()
        return self.flow.state

    def test_intent_binds_the_current_input_material_and_vessel_without_booking_effect(self):
        self.prepare()
        before = self.flow.state
        current = before['manual']['reactions'][self.fixture.reaction_id]['current_material_id']
        self.fixture.begin()
        state = self.flow.state
        booking = state['bookings'][self.fixture.intent_id]
        self.assertEqual(booking['outcome'], 'intent')
        self.assertEqual(booking['request']['inputs'][0]['material_id'], current)
        self.assertEqual(booking['request']['outputs'][0]['vessel_id'],
                         before['inventory']['materials'][current]['vessel_id'])
        self.assertEqual(state['manual']['reactions'][self.fixture.reaction_id]['current_material_id'], current)
        self.assertNotIn(self.fixture.output_material_id, state['inventory']['materials'])
        self.assertEqual(state['pending_operation'], {'intent_id': self.fixture.intent_id})
        self.assertTrue(state['resources'])
        self.assertTrue(self.journal.owners())
        other_roles = {reaction['role'] for identity, reaction in state['manual']['reactions'].items()
                       if identity != self.fixture.reaction_id}
        self.assertEqual(other_roles, {'h3k4me3', 'igg'})
        self.assertFalse(any(action.get('sonication') for action in state['manual']['actions'].values()
                             if action['reaction_id'] != self.fixture.reaction_id))

    def test_normal_completion_preserves_lineage_and_accounts_for_qc_once(self):
        self.prepare()
        source = self.flow.state['manual']['reactions'][self.fixture.reaction_id]['current_material_id']
        state = self.complete_fixture()
        material = state['inventory']['materials'][self.fixture.output_material_id]
        self.assertEqual(material['parents'], [source])
        self.assertEqual(ledger.remaining(state, self.fixture.output_material_id)['value'], 295)
        self.assertEqual(state['bookings'][self.fixture.intent_id]['outcome'], 'performed')
        self.assertEqual(state['sop']['stages'][self.fixture.stage_run_id]['status'], 'completed')
        self.assertEqual(state['status'], 'working')
        self.assertTrue(state['resources'])
        report = self.flow.report()
        self.assertFalse(report['hardware_executed'])
        self.assertFalse(report['network_executed'])
        self.assertFalse(report['preparation_execution_ready'])
        self.assertFalse(report['execution_ready'])
        self.assertFalse(report['reference_success'])
        self.assertFalse(state['definition']['preparation_complete'])
        self.assertFalse(state['definition']['can_claim_reference_success'])
        self.assertFalse(state['definition']['original_pdf_verified'])
        self.assertTrue(any(item['id'] == 'manufacturer_original'
                            for item in state['definition']['raw_open_requirements']))
        self.assertFalse(any(state['definition']['real_stage_readiness'].values()))

    def test_both_enriched_reactions_are_rejected_before_any_material_effect(self):
        for role in ('h3k4me3', 'igg'):
            with self.subTest(role=role):
                directory = self.directory / role
                journal = Journal(directory / 'journal.sqlite3')
                self.addCleanup(journal.close)
                fixture = FixtureSession(journal, 'TEST.Excluded.' + role, directory)
                fixture.prepare_input()
                before = fixture.flow.state
                reaction = next(identity for identity, item in before['manual']['reactions'].items()
                                if item['role'] == role)
                with self.assertRaisesRegex(TaskError, 'bound Input reaction'):
                    fixture.act('begin_sonication', intent_id=fixture.intent_id,
                        reaction_id=reaction, stage_run_id=fixture.stage_run_id,
                        output_material_id=fixture.output_material_id, reason='Forbidden enriched branch')
                after = fixture.flow.state
                self.assertEqual(after['inventory'], before['inventory'])
                self.assertEqual(after['bookings'], before['bookings'])
                self.assertEqual(after['resources'], before['resources'])

    def test_repeated_observation_is_one_event_and_conflicting_reuse_is_rejected(self):
        self.prepare()
        self.fixture.begin()
        envelope = self.envelope('TEST.StableCancellation')
        self.flow.act('cancel', self.fixture.actor, observation=envelope, reason='Fixture cancellation')
        before = self.snapshot()
        self.flow.act('cancel', self.fixture.actor, observation=envelope, reason='Fixture cancellation')
        self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(TaskError, 'identity reused'):
            self.flow.act('cancel', self.fixture.actor, observation=envelope, reason='Changed fixture reason')
        self.assertEqual(self.snapshot(), before)

    def test_generic_confirm_and_resolution_cannot_bypass_the_sonication_observation(self):
        self.prepare(); self.fixture.begin()
        state = self.flow.state
        request = state['bookings'][self.fixture.intent_id]['request']
        actual_inputs = [{'material_id': item['material_id'], 'quantity': item['quantity']}
                         for item in request['inputs']]
        actual_outputs = [{'material_id': self.fixture.output_material_id,
                           'quantity': {'value': 300, 'unit': 'uL'}}]
        for command, values in [
                ('confirm_material_action', {'actual_inputs': actual_inputs, 'actual_outputs': actual_outputs}),
                ('resolve_action', {'outcome': 'performed', 'actual_inputs': actual_inputs,
                                    'actual_outputs': actual_outputs, 'mixed': None})]:
            with self.subTest(command=command):
                before = self.snapshot()
                with self.assertRaises(TaskError):
                    self.fixture.act(command, intent_id=self.fixture.intent_id,
                        reason='Attempted generic fixture bypass', **values)
                self.assertEqual(self.snapshot(), before)

    def test_stage_needs_physical_completion_then_phase_and_size_evidence(self):
        self.prepare(); self.fixture.begin()
        with self.assertRaises(TaskError):
            self.fixture.act('complete_stage', stage_run_id=self.fixture.stage_run_id,
                receipts=self.fixture.receipts('S09'), action_ids=[self.fixture.intent_id],
                reason='Attempted completion before any effect observation')
        self.fixture.confirm()
        with self.assertRaises(TaskError): self.fixture.complete()
        self.fixture.phase_evidence()
        with self.assertRaises(TaskError): self.fixture.complete()
        self.fixture.size_evidence(); self.fixture.complete()
        self.assertEqual(self.flow.state['sop']['stages'][self.fixture.stage_run_id]['status'], 'completed')

    def test_wrong_observed_vessel_does_not_book_or_introduce_output(self):
        self.prepare(); self.fixture.begin()
        resources = self.flow.state['resources']
        with self.assertRaises(TaskError):
            self.fixture.act('confirm_sonication', intent_id=self.fixture.intent_id,
                actual_output_quantity={'value': 300, 'unit': 'uL'},
                observed_vessel_id='TEST.ForeignVessel', reason='Mismatched fixture vessel')
        state = self.flow.state
        self.assertEqual(state['bookings'][self.fixture.intent_id]['outcome'], 'intent')
        self.assertNotIn(self.fixture.output_material_id, state['inventory']['materials'])
        self.assertEqual(state['resources'], resources)

    def test_physical_completion_requires_original_observation_bytes(self):
        self.prepare(); self.fixture.begin()
        state = self.flow.state
        vessel = state['bookings'][self.fixture.intent_id]['request']['outputs'][0]['vessel_id']
        with self.assertRaisesRegex(TaskError, '(?i)(original|artifact|evidence)'):
            self.fixture.act('confirm_sonication', intent_id=self.fixture.intent_id,
                actual_output_quantity={'value': 300, 'unit': 'uL'},
                observed_vessel_id=vessel, reason='No archived completion original')
        self.assertEqual(self.flow.state['bookings'][self.fixture.intent_id]['outcome'], 'intent')

    def test_a_complete_time_record_and_size_result_do_not_replace_temperature_coverage(self):
        self.prepare(); self.fixture.begin(); self.fixture.confirm(); self.fixture.size_evidence()
        state = self.flow.state
        stage = state['sop']['stages'][self.fixture.stage_run_id]
        phase_id = 'S09.input_preparation'
        requirement = state['definition']['sop_profile']['phase_requirements'][phase_id]
        qualifications = state['definition']['sop_profile']['qualifications']
        start = self.fixture.phase_started_s
        end = start + 25
        original = json.dumps({'fixture_only': True, 'start_s': start, 'end_s': end,
                               'temperature_deg_c': 4}).encode()
        self.fixture.act('attach_sop_evidence', file_name='time-and-temperature-fixture.json',
                         origin='test_fixture', artifact=original)
        common = {'stage_run_id': stage['id'], 'phase_id': phase_id,
            'reaction_id': self.fixture.reaction_id, 'material_id': stage['material_id'],
            'vessel_id': stage['vessel_id'], 'time_basis_id': self.fixture.time_basis,
            'source_kind': 'test_fixture', 'artifact_sha256': digest(original)}
        self.fixture.act('record_phase_time', stage_run_id=stage['id'], phase_id=phase_id,
            record={**common, 'evidence_id': self.fixture.prefix + '.TimeOnly',
                'qualification_ref': requirement['time_qualification_ref'],
                'start_earliest_s': start, 'start_latest_s': start,
                'end_earliest_s': end, 'end_latest_s': end})
        with self.assertRaisesRegex(TaskError, '(?i)(temperature|phase|time|conformance)'):
            self.fixture.complete()
        phase = self.flow.state['sop']['stages'][stage['id']]['phases'][phase_id]
        self.assertEqual(len(phase['times']), 1)
        self.assertEqual(phase['temperatures'], [])
        self.fixture.act('record_phase_temperature', stage_run_id=stage['id'], phase_id=phase_id,
            record={**common, 'evidence_id': self.fixture.prefix + '.TemperatureOnly',
                'source_id': qualifications[requirement['temperature_qualification_ref']]['source_id'],
                'qualification_ref': requirement['temperature_qualification_ref'],
                'time_qualification_ref': requirement['time_qualification_ref'],
                'from_earliest_s': start, 'from_latest_s': start, 'to_earliest_s': end,
                'to_latest_s': end, 'minimum_deg_c': 4, 'maximum_deg_c': 4,
                'uncertainty_deg_c': 0})
        self.fixture.complete()
        self.assertEqual(self.flow.state['sop']['stages'][stage['id']]['status'], 'completed')

    def test_size_result_requires_its_own_canonical_qc_withdrawal(self):
        self.prepare(); self.fixture.begin(); self.fixture.confirm()
        before = self.flow.state
        with self.assertRaisesRegex(TaskError, '(?i)confirmed root QC withdrawal'):
            self.fixture.act('record_sonication_size', intent_id=self.fixture.intent_id,
                size_id=self.fixture.prefix + '.ForeignSize',
                withdrawal_intent_id=self.fixture.prefix + '.InputPreparation',
                minimum_bp=150, maximum_bp=450, reason='Wrong root action reference',
                artifact=b'fixture-only unmatched fragment-size result')
        after = self.flow.state
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertEqual(ledger.remaining(after, self.fixture.output_material_id)['value'], 300)
        self.assertEqual(after['bookings'][self.fixture.intent_id]['outcome'], 'performed')

    def test_later_bad_size_original_is_retained_without_repeating_transformation_or_qc_debit(self):
        self.prepare(); self.fixture.begin(); self.fixture.confirm()
        self.fixture.phase_evidence(); self.fixture.size_evidence()
        before = self.flow.state
        original = json.dumps({'fixture_only': True, 'minimum_bp': 12000, 'maximum_bp': 15000}).encode()
        size_id = self.fixture.prefix + '.ContradictorySize'
        self.fixture.act('record_sonication_size', intent_id=self.fixture.intent_id, size_id=size_id,
            withdrawal_intent_id=self.fixture.prefix + '.SizeWithdrawal', minimum_bp=12000,
            maximum_bp=15000, reason='Explicit contradictory fixture result', artifact=original)
        after = self.flow.state
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertEqual(ledger.remaining(after, self.fixture.output_material_id)['value'], 295)
        self.assertEqual(after['bookings'][self.fixture.intent_id]['outcome'], 'performed')
        record = after['manual']['actions'][self.fixture.intent_id]['sonication']['size_records'][size_id]
        self.assertFalse(record['fixture_range_conformant'])
        self.assertEqual(self.journal.artifact(record['observation']['artifact_sha256']), original)
        self.assertTrue(after['recovery_required'])
        self.assertTrue(any(item['code'] == 'sonication_size_deviation' for item in after['manual']['holds']))
        with self.assertRaises(TaskError):self.fixture.complete()
        self.assertEqual(self.flow.state['sop']['stages'][self.fixture.stage_run_id]['status'], 'open')

    def test_test_clock_and_fixture_observation_boundary_cannot_be_upgraded(self):
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, '(?i)test clock'):
            self.make_other(copy.deepcopy(self.fixture.source), clock=SystemClock())
        self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(TaskError, '(?i)(fixture|test)'):
            self.flow.act('cancel', self.fixture.actor,
                observation=self.envelope(source_kind='human_observation'), reason='Wrong evidence kind')
        self.assertEqual(self.snapshot(), before)

    def test_disabled_or_unknown_bindings_keep_s09_closed(self):
        for change in ('disabled', 'unknown'):
            with self.subTest(change=change):
                source = copy.deepcopy(self.fixture.source)
                if change == 'disabled':source['runtime_profile']['enabled'] = False
                else:
                    fact = source['sonication_source']['parameters']['pulse_on_s']
                    fact.update(value=None, basis='unknown', source_refs=[])
                flow = self.make_other(source)
                self.act_on(flow, 'accept_inventory', observations=flow.inventory_observations())
                self.act_on(flow, 'workspace_clear', confirmed=True)
                self.act_on(flow, 'claim')
                before = self.snapshot(flow)
                with self.assertRaisesRegex(TaskError, 'Open SOP bindings block stage S09'):
                    self.act_on(flow, 'begin_stage', stage_id='S09',
                        reaction_id=self.fixture.reaction_id, stage_run_id='TEST.Blocked.S09')
                self.assertEqual(self.snapshot(flow), before)

    def test_old_capture_engines_cannot_open_the_new_versioned_run(self):
        for cls in (CutRunManualWorkflow, CutRunManualSopWorkflow):
            with self.subTest(engine=cls.ENGINE):
                before = self.snapshot()
                with self.assertRaises(TaskError):
                    cls.open(self.journal, self.flow.run_id, resume=True, clock=self.fixture.clock)
                self.assertEqual(self.snapshot(), before)

    def test_helper_drift_rejects_new_effect_before_journal_or_reservation_change(self):
        self.prepare()
        path = (ROOT / 'scripts/cutrun_input_sonication_demo.py').resolve()
        read_bytes = Path.read_bytes
        original = read_bytes(path)
        reads = []
        def drift(candidate):
            if candidate.resolve() == path:
                reads.append(candidate)
                return original + b'\n'
            return read_bytes(candidate)
        before = self.snapshot()
        with patch.object(Path, 'read_bytes', drift):
            with self.assertRaisesRegex(TaskError, '(?i)(source changed|runtime source)'):
                self.fixture.act('cancel', reason='Sources must still match before a new event')
        self.assertTrue(reads)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(read_bytes(path), original)

    def test_restart_preserves_pending_intent_and_fences_the_old_session(self):
        self.prepare(); self.fixture.begin()
        old_flow = self.flow
        resources = self.flow.state['resources']
        booking = copy.deepcopy(self.flow.state['bookings'][self.fixture.intent_id])
        self.fixture.resume()
        state = self.flow.state
        self.assertEqual(state['bookings'][self.fixture.intent_id], booking)
        self.assertEqual(state['resources'], resources)
        self.assertTrue(state['recovery_required'])
        before = self.snapshot()
        with self.assertRaisesRegex(TaskError, '(?i)stale'):
            old_flow.act('cancel', self.fixture.actor, observation=self.envelope(), reason='Old writer')
        self.assertEqual(self.snapshot(), before)
        self.fixture.act('resolve_sonication', intent_id=self.fixture.intent_id,
                         outcome='unknown', reason='Fixture result is not known after interruption')
        self.assertEqual(self.flow.state['bookings'][self.fixture.intent_id]['outcome'], 'unknown')
        self.assertEqual(self.flow.state['resources'], resources)
        self.assertNotIn(self.fixture.output_material_id, self.flow.state['inventory']['materials'])

    def test_cancel_unknown_holds_resources_until_resolution_disposition_and_inventory(self):
        self.prepare(); self.fixture.begin()
        resources = self.flow.state['resources']
        self.fixture.act('cancel', reason='Explicit fixture cancellation')
        self.fixture.act('resolve_sonication', intent_id=self.fixture.intent_id,
                         outcome='unknown', reason='Fixture outcome remains unknown')
        with self.assertRaises(TaskError):
            self.fixture.act('finish_cancel', workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertEqual(self.flow.state['resources'], resources)
        self.fixture.act('resolve_sonication', intent_id=self.fixture.intent_id,
                         outcome='not_performed', reason='Explicit fixture nonperformance observation')
        with self.assertRaises(TaskError):
            self.fixture.act('finish_cancel', workspace_clear=True)
        self.fixture.return_to_origin()
        for identity, material in self.flow.state['inventory']['materials'].items():
            if material['disposition_confirmation'] is None:
                self.fixture.act('set_disposition', material_id=identity, disposition='retained',
                                 reason='Explicit fixture retained-material observation')
        self.fixture.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                         reason='Complete fixture inventory and device-area reconciliation')
        self.fixture.act('finish_cancel', workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertEqual(self.flow.state['resources'], [])
        self.assertFalse(any(owner == self.flow.run_id for owner in self.journal.owners().values()))

    def test_completed_sonication_does_not_release_or_close_with_vessel_still_in_device(self):
        self.prepare(); self.fixture.begin(); self.fixture.confirm()
        self.fixture.phase_evidence(); self.fixture.size_evidence()
        resources = self.flow.state['resources']
        with patch.object(self.fixture, 'return_to_origin', return_value=None):
            with self.assertRaises(TaskError):self.fixture.complete()
        self.assertEqual(self.flow.state['sop']['stages'][self.fixture.stage_run_id]['status'], 'open')
        self.assertEqual(self.flow.state['resources'], resources)
        self.fixture.return_to_origin()
        self.fixture.reconcile()
        self.fixture.complete()
        self.assertEqual(self.flow.state['sop']['stages'][self.fixture.stage_run_id]['status'], 'completed')

    def test_read_only_report_uses_snapshot_clock_and_changes_no_journal_bytes(self):
        self.prepare(); self.fixture.begin()
        before = self.snapshot()
        reader = InputSonicationWorkflow(self.journal, self.flow.run_id, None)
        report = reader.report()
        self.assertEqual(report['run_id'], self.flow.run_id)
        self.assertEqual(report['sonication']['pending_intents'], [self.fixture.intent_id])
        self.assertEqual(self.snapshot(), before)

    def test_phase_before_sonication_intent_cannot_supply_its_execution_time(self):
        self.prepare()
        self.fixture.clock.advance(50)
        self.fixture.begin()
        self.fixture.confirm()  # Canonical effect at 75 s; stage began at 0 s.
        self.fixture.phase_evidence()  # Deliberately old interval 0..25 s.
        self.fixture.size_evidence()
        self.fixture.return_to_origin()
        before = self.snapshot()
        with self.assertRaises(TaskError):
            self.fixture.complete()
        self.assertEqual(self.flow.state['sop']['stages'][self.fixture.stage_run_id]['status'], 'open')
        self.assertEqual(self.flow.state['bookings'][self.fixture.intent_id]['outcome'], 'performed')
        self.assertEqual(len(self.flow.state['bookings']), len(before['state']['bookings']))
        report = self.flow.report()
        issues = report['sop']['stages'][self.fixture.stage_run_id]['current_assessment']['issues']
        self.assertTrue(any('sonication' in issue and ('time' in issue or 'intent' in issue)
                            for issue in issues), issues)


if __name__ == '__main__':
    unittest.main()
