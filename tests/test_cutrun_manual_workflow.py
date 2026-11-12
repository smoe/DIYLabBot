"""Manual capture tests use explicit fake clocks and test-only source evidence."""

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import cutrun_manual_sources as sources
import cutrun_manual_workflow as runtime
from cutrun_manual_workflow import CutRunManualWorkflow
from cutrun_workflow import CutRunWorkflow
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError
from material_workflow import MaterialWorkflow
import material_ledger as ledger
from test_manual_process_clock import FakeClock


class CutrunManualWorkflowTests(unittest.TestCase):
    ACTOR = 'Test.Operator'
    OBSERVER = 'Test.StopObserver'
    REFERENCE = 'Test.Reaction.H3K4me3'
    IGG = 'Test.Reaction.IgG'
    INPUT = 'Test.Reaction.Input'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cutrun-manual-runtime-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture_root = (self.directory / 'repository').resolve()
        self.profile = json.loads(sources.SOURCE.read_text())
        self.original = self.directory / 'manufacturer.pdf'
        self.original.write_bytes(b'%PDF-1.7\nExplicit test fixture, not a laboratory original.\n')
        old_hash = self.profile['sources']['manufacturer']['source_sha256']
        self.profile['sources']['manufacturer']['source_sha256'] = digest(self.original.read_bytes())
        sop_name = self.profile['sources']['sop']['source']
        for name in (*sources.RUNTIME, sop_name):
            target = self.fixture_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        sop_bytes = (self.fixture_root / sop_name).read_bytes().replace(
            old_hash.encode(), self.profile['sources']['manufacturer']['source_sha256'].encode())
        (self.fixture_root / sop_name).write_bytes(sop_bytes)
        self.profile['sources']['sop']['source_sha256'] = digest(sop_bytes)
        for module in (sources, runtime):
            root_patch = patch.object(module, 'ROOT', self.fixture_root)
            root_patch.start()
            self.addCleanup(root_patch.stop)
        self.evidence = self.directory / 'decision.txt'
        self.evidence.write_bytes(b'Explicit prospective test-only decisions; no authenticated laboratory approval.\n')
        self.evidence_files = {'decision_evidence': self.evidence}
        self.journal = Journal(self.directory / 'manual.sqlite3')
        self.addCleanup(self.journal.close)
        self.clock = FakeClock()
        self.serial = 0
        self.materials, self.vessels, self.reactions = self.declarations()
        self.flow = self.create(self.confirmed())
        self.claim()

    def declarations(self):
        materials, vessels, reactions = [], [], {}
        for role, reaction_id in (('h3k4me3', self.REFERENCE), ('igg', self.IGG), ('input', self.INPUT)):
            material_id, vessel_id = 'Test.' + role, 'Test.' + role + '.Tube'
            materials.append({'id': material_id, 'kind': 'sample' if role == 'h3k4me3' else 'control',
                'vessel_id': vessel_id, 'quantity': {'value': 10000, 'unit': 'cells'},
                'origin_id': 'Test.Culture'})
            reagents = {}
            for operation in (() if role == 'input' else ('activation', 'stop')):
                identity = 'Test.' + role + '.' + operation
                materials.append({'id': identity, 'kind': 'reagent', 'vessel_id': identity + '.Tube',
                    'quantity': {'value': 500, 'unit': 'uL'}, 'origin_id': 'Test.Issued.' + operation})
                reagents[operation] = identity
            reactions[reaction_id] = {'role': role, 'material_id': material_id, 'vessel_id': vessel_id,
                'activation_material_id': reagents.get('activation'), 'stop_material_id': reagents.get('stop')}
        vessel_ids = [item['vessel_id'] for item in materials]
        vessel_ids += ['Test.' + role + '.ProductTube' for role in ('h3k4me3', 'igg', 'input')]
        vessel_ids.append('Test.ntc.Tube')
        for index, identity in enumerate(vessel_ids, 1):
            vessels.append({'id': identity, 'location': {'kind': 'rack', 'rack_id': 'Test.Rack',
                                                      'place_id': 'P%02d' % index}})
        return materials, vessels, reactions

    def confirmed(self):
        profile = copy.deepcopy(self.profile)
        for decision in profile['local_decisions'].values():
            decision.update(status='confirmed', value={'decision': 'Explicit test-only choice'},
                actor_id=self.ACTOR, confirmed_at='2026-01-01T12:00:00Z', evidence_ref='decision_evidence')
        values = {'task_deadline_s': 100000, 'activation_volume_ul': 150, 'stop_volume_ul': 150,
            'activation_duration_s': 1800, 'stop_window_s': 120, 'temperature_tolerance_deg_c': 1,
            'activation_temperature_deg_c': 4, 'phase_tolerance_s': 60, 'input_cells': 10000}
        for name, fact in profile['parameters'].items():
            fact.update(value=values[name], basis='locally_confirmed', source_ref='sop', evidence_ref='decision_evidence')
        profile['context'].update(culture_id='Test.Culture', material_state='fresh_unfixed', condition_id='Test.Baseline')
        for role, binding in profile['roles'].items():
            binding.update(material_id=None if role == 'ntc' else 'Test.' + role, vessel_id='Test.' + role + '.Tube')
        for role, plan in profile['qc_plan']['roles'].items():
            plan.update(assay_id='Test.RawDNA.' + role, criteria={'review_rule': 'Prospective test-only role criterion'},
                limits={'censoring': 'Preserve censored results without invented zero'}, evidence_ref='decision_evidence')
        profile['handover_plan'].update(recipient_id='Test.Recipient',
            storage_location={'rack_id': 'Test.ProductRack', 'place_id': 'P01'},
            conditions='Explicit test storage', evidence_ref='decision_evidence')
        return profile

    def create(self, profile, *, journal=None, clock=None, run_id='Test.Manual.Cutrun'):
        return CutRunManualWorkflow.create(journal or self.journal, profile, materials=self.materials,
            vessels=self.vessels, reactions=self.reactions, actors=[self.ACTOR, self.OBSERVER],
            run_id=run_id, clock=clock or self.clock, original_pdf=self.original,
            evidence_files=self.evidence_files)

    def envelope(self, *, observed_at=None):
        self.serial += 1
        return {'observation_id': 'Test.Observation.%03d' % self.serial, 'source_kind': 'test_fixture',
                'observed_at': observed_at, 'source_ref': 'Test.Explicit fixture record', 'artifact_sha256': None}

    def act(self, command, *, actor=None, envelope=None, **data):
        return self.flow.act(command, actor or self.ACTOR, observation=envelope or self.envelope(), **data)

    def claim(self):
        self.act('accept_inventory', observations=self.flow.inventory_observations())
        self.act('workspace_clear', confirmed=True)
        self.act('claim')

    def begin_activation(self, reaction_id=None, intent_id='Test.Activation'):
        self.act('begin_activation', intent_id=intent_id, reaction_id=reaction_id or self.REFERENCE,
                 stop_access=True, mixing_available=True)
        return intent_id

    def activate(self, reaction_id=None, intent_id='Test.Activation', mixed=True):
        intent = self.begin_activation(reaction_id, intent_id)
        self.act('confirm_dose', intent_id=intent, actual_volume_ul=150, mixed=mixed,
                 reason='Explicit test-only activation receipt')
        return intent

    def stop(self, reaction_id=None, *, intent_id='Test.Stop', actor=None, mixed=True):
        self.act('begin_stop', actor=actor, intent_id=intent_id, reaction_id=reaction_id or self.REFERENCE,
                 stop_access=True, mixing_available=True)
        self.act('confirm_dose', actor=actor, intent_id=intent_id, actual_volume_ul=150, mixed=mixed,
                 reason='Explicit test-only stop receipt')
        return intent_id

    def product(self, reaction_id=None):
        reaction_id = reaction_id or self.REFERENCE
        role = self.reactions[reaction_id]['role']
        source_id, output_id = self.reactions[reaction_id]['material_id'], 'Test.' + role + '.Product'
        intent = 'Test.Purify.' + role
        self.act('begin_material_action', intent_id=intent, reaction_id=reaction_id, stage_id='S10',
            kind='transformation', inputs=[{'material_id': source_id,
                'quantity': {'value': 10000, 'unit': 'cells'}, 'consume_all': True}],
            outputs=[{'material_id': output_id, 'kind': 'product',
                'vessel_id': 'Test.' + role + '.ProductTube', 'role': 'purified_dna'}],
            purpose='Explicit test-only material transformation, not a yield prediction')
        self.act('confirm_material_action', intent_id=intent,
            actual_inputs=[{'material_id': source_id, 'quantity': {'value': 10000, 'unit': 'cells'}}],
            actual_outputs=[{'material_id': output_id, 'quantity': {'value': 50, 'unit': 'uL'}}],
            reason='Explicit test-only observed product quantity')
        return output_id

    def attach(self, raw=b'Native opaque instrument bytes\r\n\x00\xff', name='original.bin'):
        self.act('attach_qc', artifact=raw, file_name=name, origin='test_fixture')
        return digest(raw)

    def mapping(self, checksum, *, role='h3k4me3', reaction_id=None, material_id=None, mapping_id='Test.Mapping', **changes):
        record = {'mapping_id': mapping_id, 'artifact_sha256': checksum,
            'reaction_id': reaction_id or self.REFERENCE, 'material_id': material_id or 'Test.' + role + '.Product',
            'role': role, 'method': 'fluorometry', 'assay_id': 'Test.RawDNA.' + role,
            'calibration_ref': 'Test.Calibration', 'locator': 'Test.Row.7', 'result_status': 'quantified',
            'value': 2, 'unit': 'ng/uL', 'dilution': 1, 'criteria_ref': 'decision_evidence',
            'reason': 'Explicit test-only original-row mapping'}
        record.update(changes)
        return record

    def test_creation_archives_original_sources_and_declared_test_provenance_atomically(self):
        state = self.flow.state
        self.assertEqual(state['format'], 'solidcraftbot.material-workflow-state/3')
        self.assertEqual(state['definition']['format'], 'solidcraftbot.material-workflow-definition/3')
        self.assertEqual(state['definition']['clock_source_kind'], 'test_clock')
        for file in (self.original, self.evidence):
            self.assertEqual(self.journal.artifact(digest(file.read_bytes())), file.read_bytes())
        self.assertEqual(state['definition']['open_requirements'], [])
        self.assertNotIn('_initial_artifacts', state['definition'])

    def test_open_laboratory_parameters_remain_null_and_block_intents_but_allow_evidence(self):
        with Journal(self.directory / 'open.sqlite3') as journal:
            self.flow = self.create(self.profile, journal=journal, run_id='Test.Open.Manual')
            self.claim()
            before = self.flow.state
            self.assertTrue(before['definition']['open_requirements'])
            self.assertTrue(all(fact['value'] is None for fact in before['definition']['manual_profile']['parameters'].values()))
            with self.assertRaises(TaskError):
                self.begin_activation()
            self.assertEqual(self.flow.state['bookings'], {})
            self.act('record_observation', stage_id='S07', reaction_id=self.REFERENCE,
                     status='unknown', details={'note': 'Open bindings were observed, no activation instruction issued'})
            self.assertEqual(len(self.flow.state['manual']['stage_observations']), 1)

    def test_closed_contract_rejects_old_runners_and_generic_synthetic_actions(self):
        before = self.flow.state
        revision = len(self.journal.history(self.flow.run_id))
        for old in (MaterialWorkflow, CutRunWorkflow):
            with self.subTest(old=old.__name__), self.assertRaises(TaskError):
                old.open(self.journal, self.flow.run_id, resume=True)
        for command in ('advance_time', 'begin_effect', 'confirm_effect', 'take', 'release'):
            with self.subTest(command=command), self.assertRaises(TaskError):
                self.act(command)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)
        from run_material_lifecycle import fixture_declarations
        for version in (1, 2):
            with self.subTest(version=version), Journal(self.directory / ('v%d.sqlite3' % version)) as other:
                if version == 1:
                    materials, vessels, _, _ = fixture_declarations('cutrun', 'Test.LegacyV1')
                    old = MaterialWorkflow.create(other, 'cutrun', materials=materials,
                                                  vessels=vessels, run_id='Test.LegacyV1')
                else:
                    old = CutRunWorkflow.create(other, run_id='SYN.Test.LegacyV2')
                old_state, history = old.state, other.history(old.run_id)
                with self.assertRaises(TaskError):
                    CutRunManualWorkflow.open(other, old.run_id, resume=True, clock=self.clock)
                self.assertEqual(old.state, old_state)
                self.assertEqual(other.history(old.run_id), history)

    def test_all_nested_receipts_and_events_keep_test_observation_provenance(self):
        self.activate()
        self.stop()
        state = self.flow.state
        self.act('record_observation', stage_id='S08', reaction_id=self.REFERENCE, status='observed', details={'mixed': True})
        def evidence(value):
            if isinstance(value, dict):
                if 'evidence' in value:
                    yield value['evidence']
                for item in value.values():
                    yield from evidence(item)
            elif isinstance(value, list):
                for item in value:
                    yield from evidence(item)
        kinds = list(evidence(self.journal.history(self.flow.run_id)))
        self.assertIn('test_fixture', kinds)
        self.assertNotIn('synthetic_input', kinds)
        self.assertEqual(state['bookings']['Test.Stop']['confirmation']['evidence'], 'test_fixture')

    def test_identical_observation_retry_has_no_new_event_or_second_debit(self):
        intent = self.begin_activation()
        envelope = self.envelope()
        data = {'intent_id': intent, 'actual_volume_ul': 150, 'mixed': True, 'reason': 'Test stable receipt'}
        self.act('confirm_dose', envelope=envelope, **data)
        before, revision = self.flow.state, len(self.journal.history(self.flow.run_id))
        self.clock.advance(5)
        self.act('confirm_dose', envelope=envelope, **data)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)

    def test_reused_observation_identity_with_changed_content_is_rejected(self):
        envelope = self.envelope()
        self.act('record_observation', envelope=envelope, stage_id='S01', reaction_id=None,
                 status='observed', details={'note': 'Original observation'})
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.act('record_observation', envelope=envelope, stage_id='S01', reaction_id=None,
                     status='observed', details={'note': 'Changed observation'})
        self.assertEqual(self.flow.state, before)

    def test_envelope_rejects_synthetic_naive_reversed_or_conflicting_artifact_evidence(self):
        for change in ({'source_kind': 'synthetic_input'},
                       {'observed_at': {'earliest_utc': '2026-01-01T00:00:00', 'latest_utc': None}},
                       {'observed_at': {'earliest_utc': '2026-01-02T00:00:00Z', 'latest_utc': '2026-01-01T00:00:00Z'}},
                       {'artifact_sha256': '0' * 64}):
            envelope = {**self.envelope(), **change}
            with self.subTest(change=change), self.assertRaises(TaskError):
                self.act('attach_qc', envelope=envelope, artifact=b'Test original', file_name='qc.bin', origin='test_fixture')

    def test_clock_progresses_during_hold_without_a_synthetic_time_command(self):
        self.begin_activation()
        self.act('mark_unknown', intent_id='Test.Activation', reason='Test lost activation receipt')
        self.clock.advance(2000)
        self.act('check_clock')
        state = self.flow.state
        self.assertEqual(state['logical_time_s'], 2000)
        self.assertTrue(state['recovery_required'])
        self.assertIn('reaction_time_uncertain', {item['code'] for item in state['manual']['holds']})

    def test_utc_rollback_opens_durable_gap_and_does_not_shorten_exposure(self):
        self.begin_activation()
        self.clock.advance(10, utc_seconds=-1)
        self.act('check_clock')
        state = self.flow.state
        self.assertEqual(state['clock']['lower_s'], 10)
        self.assertTrue(state['clock']['gap_required'])
        self.assertIsNone(state['clock']['upper_s'])
        self.assertIn('utc_regressed', {item['code'] for item in state['clock']['anomalies']})
        self.stop()
        self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['status'], 'stopped')

    def test_restart_new_clock_domain_retains_pending_activation_and_explicit_gap(self):
        self.begin_activation()
        stale = self.flow
        new_clock = FakeClock(clock_id='Test.RestartEpoch', process_id='Test.RestartWriter')
        self.flow = CutRunManualWorkflow.open(self.journal, stale.run_id, resume=True, clock=new_clock)
        self.clock = new_clock
        state = self.flow.state
        self.assertTrue(state['clock']['gap_required'])
        self.assertEqual(state['bookings']['Test.Activation']['outcome'], 'intent')
        self.assertEqual(state['manual']['reactions'][self.REFERENCE]['status'], 'possibly_active')
        with self.assertRaises(TaskError):
            stale.act('check_clock', self.ACTOR, observation=self.envelope())
        self.act('resolve_clock_gap', minimum_s=3, maximum_s=None,
                 reason='Test explicitly unbounded restart gap', evidence_ref='decision_evidence')
        self.assertEqual(self.flow.state['logical_time_s'], 3)
        self.assertIsNone(self.flow.state['clock']['upper_s'])
        self.stop()
        self.assertEqual(self.flow.state['bookings']['Test.Activation']['outcome'], 'intent')

    def test_unknown_activation_can_be_stopped_by_declared_observer_without_replay(self):
        self.begin_activation()
        self.act('mark_unknown', intent_id='Test.Activation', reason='Test missing activation receipt')
        self.stop(actor=self.OBSERVER)
        state = self.flow.state
        self.assertEqual(state['bookings']['Test.Activation']['outcome'], 'unknown')
        self.assertEqual(state['bookings']['Test.Stop']['outcome'], 'performed')
        self.assertEqual(state['manual']['reactions'][self.REFERENCE]['status'], 'stopped')
        before = copy.deepcopy(state['bookings'])
        with self.assertRaises(TaskError):
            self.begin_activation(intent_id='Test.BlindReplay')
        self.assertEqual(self.flow.state['bookings'], before)

    def test_performed_activation_reconciliation_preserves_existing_observed_stop(self):
        self.begin_activation()
        self.act('mark_unknown', intent_id='Test.Activation', reason='Test missing activation acknowledgement')
        self.stop()
        stopped = copy.deepcopy(self.flow.state['manual']['reactions'][self.REFERENCE]['stop'])
        self.act('resolve_action', intent_id='Test.Activation', outcome='performed',
            actual_inputs=[{'material_id': 'Test.h3k4me3.activation', 'quantity': {'value': 150, 'unit': 'uL'}}],
            actual_outputs=[], mixed=True, reason='Test external evidence resolves old activation')
        reaction = self.flow.state['manual']['reactions'][self.REFERENCE]
        self.assertEqual(reaction['status'], 'stopped')
        self.assertEqual(reaction['stop'], stopped)

    def test_retrospective_stop_preserves_past_occurrence_without_fabricated_old_event(self):
        self.begin_activation()
        self.act('mark_unknown', intent_id='Test.Activation', reason='Test offline activation uncertainty')
        self.clock.advance(100)
        observed = {'earliest_utc': '2026-11-12T12:00:10Z', 'latest_utc': '2026-11-12T12:00:12Z'}
        envelope = self.envelope(observed_at=observed)
        previous = self.journal.history(self.flow.run_id)
        self.act('record_external_stop', envelope=envelope, reaction_id=self.REFERENCE,
                 actual_volume_ul=150, mixed=True, reason='Test independently documented offline stop')
        trace = self.journal.history(self.flow.run_id)
        self.assertEqual(len(trace), len(previous) + 1)
        self.assertEqual(trace[:-1], previous)
        self.assertEqual(trace[-1]['kind'], 'record_external_stop')
        self.assertEqual(trace[-1]['payload']['recorded_at']['monotonic_ns'], 100_000_000_000)
        action_id = self.flow.state['protective_operations']['Test.h3k4me3.Tube']
        self.assertTrue(self.flow.state['manual']['actions'][action_id]['retrospective'])
        self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['stop']['observed_at'], observed)

    def test_external_stop_resolves_existing_unknown_intent_without_an_additional_debit(self):
        self.begin_activation()
        self.act('begin_stop', intent_id='Test.Stop.Unknown', reaction_id=self.REFERENCE,
                 stop_access=True, mixing_available=True)
        self.act('mark_unknown', intent_id='Test.Stop.Unknown', reason='Test lost stop acknowledgement')
        self.act('record_external_stop', reaction_id=self.REFERENCE, actual_volume_ul=150, mixed=True,
                 reason='Test existing stop independently observed')
        state = self.flow.state
        self.assertEqual(state['protective_operations']['Test.h3k4me3.Tube'], 'Test.Stop.Unknown')
        self.assertEqual(ledger.remaining(state, 'Test.h3k4me3.stop')['value'], 350)
        self.assertEqual(sum(action['operation'] == 'stop' for action in state['manual']['actions'].values()), 1)

    def test_missing_stop_mixing_cannot_claim_stopped_or_release_material(self):
        self.activate()
        self.stop(mixed=False)
        self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['status'], 'stop_unconfirmed')
        with self.assertRaises(TaskError):
            self.act('set_disposition', material_id='Test.h3k4me3', disposition='retained', reason='Test no mixing proof')

    def test_later_stop_mixing_adds_evidence_without_a_second_dose_or_changed_combined_stop(self):
        self.activate()
        self.stop(mixed=False)
        before = ledger.remaining(self.flow.state, 'Test.h3k4me3.stop')
        self.clock.advance(5)
        self.act('confirm_stop_mixing', intent_id='Test.Stop', mixed=True, reason='Test observed subsequent mixing')
        stopped = copy.deepcopy(self.flow.state['manual']['reactions'][self.REFERENCE]['stop'])
        self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['status'], 'stopped')
        self.assertEqual(ledger.remaining(self.flow.state, 'Test.h3k4me3.stop'), before)
        with self.assertRaises(TaskError):
            self.act('confirm_stop_mixing', intent_id='Test.Stop', mixed=True, reason='Test cannot shift confirmed stop')
        self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['stop'], stopped)

    def test_external_activation_is_retrospective_and_does_not_invent_an_earlier_deadline(self):
        self.clock.advance(100)
        observed = {'earliest_utc': '2026-11-12T12:00:10Z', 'latest_utc': '2026-11-12T12:00:12Z'}
        previous = self.journal.history(self.flow.run_id)
        self.act('record_external_activation', envelope=self.envelope(observed_at=observed),
                 reaction_id=self.REFERENCE, actual_volume_ul=150, mixed=True,
                 reason='Test paper record of activation during computer outage')
        state = self.flow.state
        reaction = state['manual']['reactions'][self.REFERENCE]
        self.assertTrue(state['recovery_required'])
        self.assertIsNone(reaction['activation']['stop_deadline_lower_s'])
        self.assertEqual(ledger.remaining(state, 'Test.h3k4me3.activation')['value'], 350)
        trace = self.journal.history(self.flow.run_id)
        self.assertEqual(trace[:-1], previous)
        self.assertEqual(trace[-1]['kind'], 'record_external_activation')
        self.assertEqual(trace[-1]['payload']['recorded_at']['monotonic_ns'], 100_000_000_000)
        self.stop()
        self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['status'], 'stopped')

    def test_generic_actions_cannot_spend_reserved_activation_or_stop_aliquots(self):
        before = self.flow.state['bookings']
        for operation in ('activation', 'stop'):
            with self.subTest(operation=operation), self.assertRaises(TaskError):
                self.act('begin_material_action', intent_id='Test.Bypass.' + operation, reaction_id=self.REFERENCE,
                    stage_id='S03', kind='withdrawal', inputs=[{'material_id': 'Test.h3k4me3.' + operation,
                        'quantity': {'value': 1, 'unit': 'uL'}, 'consume_all': False}], outputs=[], purpose='Test bypass')
        self.assertEqual(self.flow.state['bookings'], before)

    def test_material_transformation_and_qc_withdrawal_debit_only_the_product_once(self):
        product = self.product()
        self.act('begin_qc_withdrawal', intent_id='Test.QC.Withdrawal', reaction_id=self.REFERENCE,
                 method='fluorometry', quantity={'value': 2, 'unit': 'uL'})
        self.act('confirm_material_action', intent_id='Test.QC.Withdrawal',
            actual_inputs=[{'material_id': product, 'quantity': {'value': 2, 'unit': 'uL'}}],
            actual_outputs=[], reason='Test actual QC aliquot')
        state = self.flow.state
        self.assertEqual(ledger.remaining(state, product)['value'], 48)
        self.assertEqual(ledger.remaining(state, 'Test.h3k4me3')['value'], 0)
        self.assertEqual(state['inventory']['materials'][product]['parents'], ['Test.h3k4me3'])

    def test_opaque_qc_attachment_preserves_bytes_without_decoder_or_material_effect(self):
        raw = b'Not JSON; native file\r\n\x00\xff'
        before = self.flow.state['bookings']
        checksum = self.attach(raw)
        record = self.flow.state['manual']['qc_artifacts'][checksum]
        self.assertEqual(self.journal.artifact(checksum), raw)
        self.assertEqual(record['status'], 'unmapped')
        self.assertIsNone(record['decoder'])
        self.assertEqual(self.flow.state['bookings'], before)
        self.assertEqual(self.flow.state['manual']['qc_bindings'], {})

    def test_explicit_product_mapping_does_not_imply_technical_or_biological_review(self):
        product = self.product()
        checksum = self.attach()
        before = self.flow.state['bookings']
        self.act('map_qc', **self.mapping(checksum))
        state = self.flow.state
        self.assertEqual(state['manual']['qc_bindings']['Test.Mapping']['material_id'], product)
        self.assertEqual(state['manual']['qc_artifacts'][checksum]['status'], 'mapped')
        self.assertEqual(state['manual']['qc_reviews'], {})
        self.assertEqual(state['manual']['biology_reviews'], {})
        self.assertEqual(state['bookings'], before)

    def test_wrong_qc_identity_method_or_censored_zero_is_durably_quarantined(self):
        self.product()
        before = self.flow.state['bookings']
        for index, changes in enumerate(({'reaction_id': 'Test.Foreign'}, {'material_id': 'Test.Foreign'},
                {'method': 'library_fragment_size'}, {'unit': 'mg'},
                {'result_status': 'not_detected', 'value': 0}), 1):
            with self.subTest(changes=changes):
                raw = ('Test unique original %d' % index).encode()
                checksum = self.attach(raw)
                identity = 'Test.InvalidMapping.%d' % index
                self.act('map_qc', **self.mapping(checksum, mapping_id=identity, **changes))
                state = self.flow.state
                self.assertEqual(state['manual']['qc_artifacts'][checksum]['status'], 'quarantined')
                self.assertNotIn(identity, state['manual']['qc_bindings'])
                self.assertEqual(self.journal.artifact(checksum), raw)
                self.assertEqual(state['bookings'], before)

    def test_igg_and_ntc_not_detected_results_preserve_unknown_values_and_allow_role_review(self):
        product = self.product(self.IGG)
        igg = self.attach(b'Test IgG native export')
        self.act('map_qc', **self.mapping(igg, role='igg', reaction_id=self.IGG, material_id=product,
            mapping_id='Test.IgG.Mapping', result_status='not_detected', value=None))
        ntc = self.attach(b'Test NTC native export')
        record = self.mapping(ntc, mapping_id='Test.NTC.Mapping', role='ntc', method='qpcr',
            unit='Cq', result_status='not_detected', value=None)
        record.update(reaction_id=None, material_id=None)
        self.act('map_qc', **record)
        for mapping_id in ('Test.IgG.Mapping', 'Test.NTC.Mapping'):
            self.act('review_qc', mapping_id=mapping_id, decision='technically_accepted',
                     reason='Prospective role-specific test criteria permit censored control signal')
        state = self.flow.state
        self.assertIsNone(state['manual']['qc_bindings']['Test.IgG.Mapping']['value'])
        self.assertIsNone(state['manual']['qc_bindings']['Test.NTC.Mapping']['value'])
        self.assertEqual(state['manual']['biology_reviews'], {})

    def test_biological_assessment_requires_prior_technical_review_and_prospective_criteria(self):
        self.product()
        checksum = self.attach()
        self.act('map_qc', **self.mapping(checksum))
        with self.assertRaises(TaskError):
            self.act('review_biology', mapping_ids=['Test.Mapping'], decision='accepted',
                     criteria_ref='decision_evidence', reason='Test premature biological review')
        self.act('review_qc', mapping_id='Test.Mapping', decision='technically_accepted', reason='Test technical review')
        self.act('review_biology', mapping_ids=['Test.Mapping'], decision='accepted',
                 criteria_ref='decision_evidence', reason='Test explicit independent biological opinion')
        report = self.flow.report()
        self.assertTrue(report['manual']['biology_reviews'])
        self.assertFalse(report['reference_success'])
        self.assertFalse(report['passed'])
        profile = self.confirmed()
        profile['qc_plan']['roles']['ntc']['criteria'] = None
        with Journal(self.directory / 'open-criteria.sqlite3') as journal:
            self.flow = self.create(profile, journal=journal, run_id='Test.OpenCriteria')
            self.claim()
            checksum = self.attach(b'Test NTC original with open local criteria')
            mapping = self.mapping(checksum, role='ntc', method='qpcr', unit='Cq',
                                   result_status='not_detected', value=None)
            mapping.update(reaction_id=None, material_id=None)
            self.act('map_qc', **mapping)
            self.act('review_qc', mapping_id='Test.Mapping', decision='technically_accepted',
                     reason='Test transcription is technically complete, criteria still open')
            with self.assertRaises(TaskError):
                self.act('review_biology', mapping_ids=['Test.Mapping'], decision='accepted',
                         criteria_ref='decision_evidence', reason='Test open criteria cannot prove biological acceptance')
            self.assertEqual(self.flow.state['manual']['biology_reviews'], {})

    def test_persistence_failure_rolls_back_observation_clock_booking_and_original_artifact(self):
        intent = self.begin_activation()
        before, revision = self.flow.state, len(self.journal.history(self.flow.run_id))
        owners = self.journal.owners()
        self.clock.advance(10)
        raw = b'Test receipt original that must roll back'
        original_event = self.journal._event
        def fail_after_event(*args, **kwargs):
            original_event(*args, **kwargs)
            raise RuntimeError('Test injected persistence failure after event insert')
        with patch.object(self.journal, '_event', side_effect=fail_after_event), self.assertRaises(RuntimeError):
            self.act('confirm_dose', intent_id=intent, actual_volume_ul=150, mixed=True,
                     reason='Test uncommitted receipt', artifact=raw)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)
        self.assertEqual(self.journal.owners(), owners)
        with self.assertRaises(TaskError):
            self.journal.artifact(digest(raw))

    def test_capture_completion_releases_only_confirmed_materials_and_never_claims_reference_success(self):
        for material_id in self.flow.state['inventory']['materials']:
            self.act('set_disposition', material_id=material_id, disposition='retained', reason='Test explicit unchanged retention')
        self.act('confirm_inventory', observations=self.flow.inventory_observations())
        self.act('close_capture', workspace_clear=True, reason='Test capture handover, no biochemical work performed')
        report = self.flow.report()
        self.assertTrue(report['capture_completed'])
        self.assertFalse(report['passed'])
        self.assertFalse(report['reference_success'])
        self.assertFalse(report['vendor_qc_decoder_executed'])
        self.assertFalse(report['biochemical_protocol_executed'])
        self.assertEqual(report['resources'], [])

    def test_undeclared_actor_cannot_write_or_stop_and_declared_observer_cannot_take_ordinary_work(self):
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.act('record_observation', actor='Test.Undeclared', stage_id='S01', reaction_id=None,
                     status='observed', details={})
        with self.assertRaises(TaskError):
            self.act('begin_activation', actor=self.OBSERVER, intent_id='Test.WrongActor',
                     reaction_id=self.REFERENCE, stop_access=True, mixing_available=True)
        self.assertEqual(self.flow.state, before)

    def test_quarantined_qc_cannot_be_cleared_by_inventory_agreement(self):
        self.product()
        checksum = self.attach()
        self.act('map_qc', **self.mapping(checksum, material_id='Test.Foreign'))
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='Test inventory cannot repair original result identity')
        self.assertTrue(self.flow.state['recovery_required'])
        self.assertEqual(self.flow.state['manual']['qc_artifacts'][checksum]['status'], 'quarantined')

    def test_report_exposure_uses_fresh_uncommitted_time_without_rewriting_history(self):
        self.activate()
        state, history = self.flow.state, self.journal.history(self.flow.run_id)
        self.clock.advance(30)
        report = self.flow.report()
        self.assertEqual(report['clock']['lower_s'], 0)
        self.assertEqual(report['current_clock_estimate']['lower_s'], 30)
        self.assertTrue(report['current_clock_estimate_is_uncommitted'])
        self.assertEqual(report['manual']['reactions'][self.REFERENCE]['possible_exposure_s'],
                         {'min_s': 30, 'max_s': 30})
        self.assertEqual(self.flow.state, state)
        self.assertEqual(self.journal.history(self.flow.run_id), history)

    def test_abnormal_cancel_requires_quarantine_and_never_invents_a_confirmed_stop(self):
        self.activate()
        self.act('cancel', reason='Test documented cancellation without stop evidence')
        with self.assertRaises(TaskError):
            self.act('finish_cancel', workspace_clear=True)
        self.act('abnormal_termination', reaction_id=self.REFERENCE,
                 reason='Test explicit abnormal handover with missing chemical stop evidence')
        with self.assertRaises(TaskError):
            self.act('set_disposition', material_id='Test.h3k4me3', disposition='retained',
                     reason='Test unconfirmed active material cannot become nominal retained product')
        for material_id in self.flow.state['inventory']['materials']:
            self.act('set_disposition', material_id=material_id,
                     disposition='quarantined' if material_id == 'Test.h3k4me3' else 'retained',
                     reason='Test explicit abnormal material handover')
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='Test final inventory and location confirmation')
        self.act('finish_cancel', workspace_clear=True)
        state = self.flow.state
        reaction = state['manual']['reactions'][self.REFERENCE]
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(reaction['status'], 'abnormal_unconfirmed_stop')
        self.assertFalse(reaction['abnormal_termination']['chemical_stop_confirmed'])
        self.assertIsNone(reaction['stop'])
        self.assertEqual(state['inventory']['materials']['Test.h3k4me3']['disposition'], 'quarantined')
        self.assertEqual(self.journal.owners(), {})
        self.assertFalse(self.flow.report()['reference_success'])

    def test_duplicate_reaction_roles_are_rejected_before_creating_a_run(self):
        reactions = copy.deepcopy(self.reactions)
        reactions[self.IGG]['role'] = 'h3k4me3'
        with Journal(self.directory / 'duplicate-role.sqlite3') as journal:
            with self.assertRaises(TaskError):
                CutRunManualWorkflow.create(journal, self.profile, materials=self.materials,
                    vessels=self.vessels, reactions=reactions, actors=[self.ACTOR],
                    run_id='Test.DuplicateRoles', clock=self.clock, original_pdf=self.original,
                    evidence_files=self.evidence_files)
            for table in ('runs', 'events', 'artifacts', 'resources'):
                self.assertEqual(journal.connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_reaction_binding_cannot_substitute_a_nonnull_profile_material_or_target_vessel(self):
        materials = self.materials + [{'id': 'Test.OtherInput', 'kind': 'sample',
            'vessel_id': 'Test.OtherInput.Tube', 'quantity': {'value': 10000, 'unit': 'cells'},
            'origin_id': 'Test.OtherCulture'}]
        vessels = self.vessels + [{'id': 'Test.OtherInput.Tube',
            'location': {'kind': 'rack', 'rack_id': 'Test.OtherRack', 'place_id': 'P01'}}]
        for substitution in ('material', 'target_vessel'):
            reactions = copy.deepcopy(self.reactions)
            reactions[self.REFERENCE]['vessel_id'] = 'Test.OtherInput.Tube'
            if substitution == 'material':
                reactions[self.REFERENCE]['material_id'] = 'Test.OtherInput'
            with self.subTest(substitution=substitution), Journal(self.directory / (substitution + '.sqlite3')) as journal:
                with self.assertRaises(TaskError):
                    CutRunManualWorkflow.create(journal, self.confirmed(), materials=materials,
                        vessels=vessels, reactions=reactions, actors=[self.ACTOR],
                        run_id='Test.Substitution.' + substitution, clock=self.clock,
                        original_pdf=self.original, evidence_files=self.evidence_files)
                self.assertEqual(journal.connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)

    def test_reagent_only_transformation_cannot_replace_the_reaction_sample(self):
        self.materials.append({'id': 'Test.Wash', 'kind': 'reagent', 'vessel_id': 'Test.Wash.Tube',
                              'quantity': {'value': 500, 'unit': 'uL'}, 'origin_id': 'Test.Issued.Wash'})
        self.vessels.append({'id': 'Test.Wash.Tube',
            'location': {'kind': 'rack', 'rack_id': 'Test.OtherRack', 'place_id': 'P02'}})
        with Journal(self.directory / 'reagent-preparation.sqlite3') as journal:
            self.flow = self.create(self.confirmed(), journal=journal, run_id='Test.ReagentPreparation')
            self.claim()
            before = self.flow.state
            with self.assertRaises(TaskError):
                self.act('begin_material_action', intent_id='Test.ReagentOnly', reaction_id=self.REFERENCE,
                    stage_id='S03', kind='transformation', inputs=[{'material_id': 'Test.Wash',
                        'quantity': {'value': 5, 'unit': 'uL'}, 'consume_all': False}],
                    outputs=[{'material_id': 'Test.Wash.WorkingMix', 'kind': 'intermediate',
                              'vessel_id': 'Test.h3k4me3.ProductTube', 'role': 'prepared_reagent'}],
                    purpose='Test cannot promote reagent preparation to sample material')
            self.assertEqual(self.flow.state, before)

    def test_multiple_retained_outputs_require_an_explicit_current_material_selection(self):
        data = {'intent_id': 'Test.SplitProducts', 'reaction_id': self.REFERENCE, 'stage_id': 'S10',
            'kind': 'transformation', 'inputs': [{'material_id': 'Test.h3k4me3',
                'quantity': {'value': 10000, 'unit': 'cells'}, 'consume_all': True}],
            'outputs': [{'material_id': 'Test.Split.A', 'kind': 'product',
                         'vessel_id': 'Test.h3k4me3.ProductTube', 'role': 'purified_dna'},
                        {'material_id': 'Test.Split.B', 'kind': 'intermediate',
                         'vessel_id': 'Test.igg.ProductTube', 'role': 'retained_intermediate'}],
            'purpose': 'Test explicit one-to-many fraction identity'}
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.act('begin_material_action', **data)
        self.assertEqual(self.flow.state, before)
        self.act('begin_material_action', **data, retained_material_id='Test.Split.B')
        self.act('confirm_material_action', intent_id=data['intent_id'],
            actual_inputs=[{'material_id': 'Test.h3k4me3', 'quantity': {'value': 10000, 'unit': 'cells'}}],
            actual_outputs=[{'material_id': 'Test.Split.A', 'quantity': {'value': 50, 'unit': 'uL'}},
                            {'material_id': 'Test.Split.B', 'quantity': {'value': 20, 'unit': 'uL'}}],
            reason='Test explicitly observed retained fractions')
        state = self.flow.state
        self.assertEqual(state['manual']['reactions'][self.REFERENCE]['current_material_id'], 'Test.Split.B')
        self.assertEqual(state['inventory']['materials']['Test.Split.A']['parents'], ['Test.h3k4me3'])
        self.assertEqual(state['inventory']['materials']['Test.Split.B']['parents'], ['Test.h3k4me3'])

    def test_mapping_a_different_assay_than_the_bound_role_plan_quarantines_the_original(self):
        self.product()
        raw = b'Test original from a differently named assay'
        checksum = self.attach(raw)
        self.act('map_qc', **self.mapping(checksum, assay_id='Test.Unbound.Assay'))
        state = self.flow.state
        self.assertEqual(state['manual']['qc_artifacts'][checksum]['status'], 'quarantined')
        self.assertNotIn('Test.Mapping', state['manual']['qc_bindings'])
        self.assertEqual(self.journal.artifact(checksum), raw)

    def test_quarantine_needs_explicit_clarification_before_remapping_and_preserves_rejections(self):
        self.product()
        raw = b'Test original requiring explicit clarification'
        checksum = self.attach(raw)
        self.act('map_qc', **self.mapping(checksum, material_id='Test.Foreign'))
        rejections = copy.deepcopy(self.flow.state['manual']['qc_artifacts'][checksum]['rejections'])
        with self.assertRaises(TaskError):
            self.act('map_qc', **self.mapping(checksum, mapping_id='Test.OrdinaryRetry'))
        state = self.flow.state
        self.assertEqual(state['manual']['qc_artifacts'][checksum]['status'], 'quarantined')
        self.assertNotIn('Test.OrdinaryRetry', state['manual']['qc_bindings'])
        self.act('clarify_qc', artifact_sha256=checksum, decision='allow_remap',
                 reason='Test explicit identification evidence permits a new mapping attempt')
        self.assertEqual(self.flow.state['manual']['qc_artifacts'][checksum]['status'], 'unmapped')
        self.act('map_qc', **self.mapping(checksum, mapping_id='Test.ClarifiedMapping'))
        state = self.flow.state
        self.assertEqual(state['manual']['qc_artifacts'][checksum]['status'], 'mapped')
        self.assertEqual(state['manual']['qc_artifacts'][checksum]['rejections'][:len(rejections)], rejections)
        self.assertIn('Test.ClarifiedMapping', state['manual']['qc_bindings'])
        self.assertEqual(self.journal.artifact(checksum), raw)
        self.act('review_qc', mapping_id='Test.ClarifiedMapping', decision='technically_accepted',
                 reason='Test technical review before a later contradictory mapping')
        self.act('map_qc', **self.mapping(checksum, mapping_id='Test.LaterContradiction', material_id='Test.Foreign'))
        self.act('clarify_qc', artifact_sha256=checksum, decision='exclude',
                 reason='Test explicit final exclusion preserves this original evidence')
        self.assertEqual(self.flow.state['manual']['qc_artifacts'][checksum]['status'], 'excluded')
        self.assertIn('Test.ClarifiedMapping', self.flow.state['manual']['qc_bindings'])
        self.assertTrue(self.flow.state['manual']['qc_bindings']['Test.ClarifiedMapping']['invalidated'])
        self.assertNotIn('Test.ClarifiedMapping', self.flow.state['manual']['qc_reviews'])
        self.assertEqual(self.journal.artifact(checksum), raw)
        with self.assertRaises(TaskError):
            self.act('map_qc', **self.mapping(checksum, mapping_id='Test.ExcludedRetry'))

    def test_deviation_assessment_requires_resolved_effects_stop_evidence_and_separate_reconciliation(self):
        self.begin_activation()
        self.act('mark_unknown', intent_id='Test.Activation', reason='Test unavailable activation receipt')
        self.act('begin_stop', intent_id='Test.BlockedStop', reaction_id=self.REFERENCE,
                 stop_access=False, mixing_available=True)
        with self.assertRaises(TaskError):
            self.act('resolve_deviation', hold_code='stop_path_blocked',
                     reason='Test unresolved effects cannot be waived', evidence_ref='decision_evidence')
        self.stop()
        self.act('resolve_action', intent_id='Test.Activation', outcome='performed',
            actual_inputs=[{'material_id': 'Test.h3k4me3.activation', 'quantity': {'value': 150, 'unit': 'uL'}}],
            actual_outputs=[], mixed=True, reason='Test independent evidence resolves activation')
        self.act('resolve_deviation', hold_code='stop_path_blocked',
                 reason='Test documented assessment after observed stopping', evidence_ref='decision_evidence')
        state = self.flow.state
        hold = next(item for item in state['manual']['holds'] if item['code'] == 'stop_path_blocked')
        self.assertEqual(hold['resolution']['evidence_ref'], 'decision_evidence')
        self.assertTrue(state['recovery_required'])
        with self.assertRaises(TaskError):
            self.begin_activation(self.IGG, 'Test.BeforeReconciliation')
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='Test separate full inventory and work-area reconciliation')
        self.assertIsNone(self.flow.state['recovery_required'])
        self.begin_activation(self.IGG, 'Test.AfterReconciliation')

    def test_open_profile_cannot_rebind_an_initial_material_to_an_empty_reaction_vessel(self):
        vessels = self.vessels + [{'id': 'Test.EmptyReactionTarget',
            'location': {'kind': 'rack', 'rack_id': 'Test.OtherRack', 'place_id': 'P03'}}]
        reactions = copy.deepcopy(self.reactions)
        reactions[self.REFERENCE]['vessel_id'] = 'Test.EmptyReactionTarget'
        with Journal(self.directory / 'open-physical-mismatch.sqlite3') as journal:
            with self.assertRaises(TaskError):
                CutRunManualWorkflow.create(journal, self.profile, materials=self.materials,
                    vessels=vessels, reactions=reactions, actors=[self.ACTOR],
                    run_id='Test.OpenPhysicalMismatch', clock=self.clock, original_pdf=self.original,
                    evidence_files=self.evidence_files)
            self.assertEqual(journal.connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
            self.assertEqual(journal.connection.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0], 0)

    def test_automatic_deadline_event_does_not_claim_a_blocked_requests_observation_or_original(self):
        self.clock.advance(100001)
        raw = b'Test original supplied with a request blocked by deadline'
        checksum = digest(raw)
        envelope = self.envelope()
        before = self.journal.history(self.flow.run_id)
        with self.assertRaises(TaskError):
            self.act('begin_activation', envelope=envelope, artifact=raw, intent_id='Test.TooLate',
                     reaction_id=self.REFERENCE, stop_access=True, mixing_available=True)
        trace = self.journal.history(self.flow.run_id)
        self.assertEqual(len(trace), len(before) + 1)
        event = trace[-1]
        self.assertEqual(event['kind'], 'deadline_exceeded')
        self.assertEqual(event['payload']['evidence'], 'clock_observation')
        self.assertNotIn('artifact_sha256', event['payload'])
        self.assertIsNone(event['state']['observation_context'])
        self.assertNotIn(envelope['observation_id'], event['state']['manual']['observations'])
        self.assertNotIn('Test.TooLate', event['state']['bookings'])
        with self.assertRaises(TaskError):
            self.journal.artifact(checksum)
        self.act('attach_qc', envelope=envelope, artifact=raw, file_name='deadline-record.bin', origin='test_fixture')
        self.assertEqual(self.journal.artifact(checksum), raw)
        self.assertIn(envelope['observation_id'], self.flow.state['manual']['observations'])

    def test_retrospective_stop_capture_latency_is_not_a_fabricated_minimum_exposure(self):
        self.activate()
        self.clock.advance(100)
        observed = {'earliest_utc': '2026-11-12T12:00:10Z', 'latest_utc': '2026-11-12T12:00:12Z'}
        self.act('record_external_stop', envelope=self.envelope(observed_at=observed),
                 reaction_id=self.REFERENCE, actual_volume_ul=150, mixed=True,
                 reason='Test offline stopping happened before capture resumed')
        report = self.flow.report()
        reaction = report['manual']['reactions'][self.REFERENCE]
        self.assertEqual(reaction['stop']['observed_at'], observed)
        self.assertEqual(reaction['possible_exposure_s'], {'min_s': 0, 'max_s': 100})
        self.clock.advance(100)
        self.assertEqual(self.flow.report()['manual']['reactions'][self.REFERENCE]['possible_exposure_s'],
                         {'min_s': 0, 'max_s': 100})

    def test_missing_or_corrupt_initial_originals_block_report_open_and_capture_close(self):
        for material_id in self.flow.state['inventory']['materials']:
            self.act('set_disposition', material_id=material_id, disposition='retained',
                     reason='Test explicit retention before original-integrity check')
        self.act('confirm_inventory', observations=self.flow.inventory_observations())
        state = self.flow.state
        manifest = state['definition']['initial_artifact_sha256']
        self.assertGreaterEqual(len(manifest), 4)  # SOP, profile, PDF and decision evidence.
        originals = {checksum: self.journal.artifact(checksum) for checksum in manifest}
        history = self.journal.history(self.flow.run_id)
        for checksum, raw in originals.items():
            for mutation in ('delete', 'corrupt'):
                with self.subTest(checksum=checksum, mutation=mutation):
                    if mutation == 'delete':
                        self.journal.connection.execute('DELETE FROM artifacts WHERE sha256=?', (checksum,))
                    else:
                        self.journal.connection.execute('UPDATE artifacts SET content=? WHERE sha256=?',
                                                        (b'Test corrupted original bytes', checksum))
                    self.journal.connection.commit()
                    try:
                        with self.assertRaises(TaskError):
                            self.flow.report()
                        with self.assertRaises(TaskError):
                            CutRunManualWorkflow.open(self.journal, self.flow.run_id, resume=True, clock=self.clock)
                        with self.assertRaises(TaskError):
                            self.act('close_capture', workspace_clear=True,
                                     reason='Test missing original must prevent final acceptance')
                    finally:
                        self.journal.connection.execute('INSERT OR REPLACE INTO artifacts VALUES (?, ?)', (checksum, raw))
                        self.journal.connection.commit()
                    self.assertEqual(self.journal.history(self.flow.run_id), history)
        self.assertFalse(self.flow.report()['capture_completed'])

    def test_rejected_overdraw_preserves_original_and_reserves_observation_without_a_debit(self):
        self.begin_activation()
        envelope = self.envelope()
        raw = b'Test instrument/person original describing excessive actual consumption\r\n\x00'
        checksum = digest(raw)
        with self.assertRaises(ObservationError):
            self.act('confirm_dose', envelope=envelope, artifact=raw, intent_id='Test.Activation',
                     actual_volume_ul=600, mixed=True, reason='Test receipt exceeds issued quantity')
        state = self.flow.state
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertEqual(event['kind'], 'observation_rejected')
        self.assertEqual(event['payload']['artifact_sha256'], checksum)
        self.assertEqual(event['payload']['observation']['artifact_sha256'], checksum)
        self.assertEqual(self.journal.artifact(checksum), raw)
        self.assertIn(envelope['observation_id'], state['manual']['observations'])
        self.assertEqual(state['bookings']['Test.Activation']['outcome'], 'intent')
        self.assertEqual(ledger.remaining(state, 'Test.h3k4me3.activation', exclude_intent='Test.Activation')['value'], 500)
        revision = len(self.journal.history(self.flow.run_id))
        with self.assertRaises(TaskError):
            self.act('confirm_dose', envelope=envelope, artifact=raw, intent_id='Test.Activation',
                     actual_volume_ul=150, mixed=True, reason='Test changed retry cannot overwrite rejected observation')
        self.assertEqual(self.flow.state, state)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), revision)


if __name__ == '__main__':
    unittest.main()
