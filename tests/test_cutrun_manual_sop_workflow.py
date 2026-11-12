"""SOP sequence tests use qualified test fixtures, never laboratory evidence."""
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import cutrun_manual_sources as base_sources
import cutrun_manual_workflow as base_runtime
import cutrun_manual_sop_sources as sources
import cutrun_manual_sop_workflow as runtime
from cutrun_manual_sop_workflow import CutRunManualSopWorkflow
from manual_tasks import Journal, TaskError, digest, encoded
import material_ledger as ledger
import test_cutrun_manual_workflow as capture_fixture
import test_cutrun_manual_cli as capture_cli
from test_manual_process_clock import FakeClock


class ManualSopWorkflowTests(unittest.TestCase):
    ACTOR = capture_fixture.CutrunManualWorkflowTests.ACTOR
    OBSERVER = capture_fixture.CutrunManualWorkflowTests.OBSERVER
    REFERENCE = capture_fixture.CutrunManualWorkflowTests.REFERENCE
    IGG = capture_fixture.CutrunManualWorkflowTests.IGG
    INPUT = capture_fixture.CutrunManualWorkflowTests.INPUT
    declarations = capture_fixture.CutrunManualWorkflowTests.declarations
    confirmed_base = capture_fixture.CutrunManualWorkflowTests.confirmed
    envelope = capture_fixture.CutrunManualWorkflowTests.envelope
    act = capture_fixture.CutrunManualWorkflowTests.act
    claim = capture_fixture.CutrunManualWorkflowTests.claim
    mapping = capture_fixture.CutrunManualWorkflowTests.mapping
    attach = capture_fixture.CutrunManualWorkflowTests.attach

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='manual-sop-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture_root = (self.directory / 'repository').resolve()
        self.profile = json.loads(base_sources.SOURCE.read_text())
        self.sop_profile = json.loads((ROOT / 'model/cutrun-manual-sop.profile.json').read_text())
        self.original = self.directory / 'manufacturer.pdf'
        self.original.write_bytes(b'%PDF-1.7\nExplicit SOP unit-test original, not laboratory evidence.\n')
        old_hash = self.profile['sources']['manufacturer']['source_sha256']
        self.profile['sources']['manufacturer']['source_sha256'] = digest(self.original.read_bytes())
        sop_name = self.profile['sources']['sop']['source']
        names = {*base_sources.RUNTIME, *sources.RUNTIME, sop_name,
                 'model/cutrun-manual-sop.profile.json', 'model/cutrun-manual-sop.protocol.json'}
        for name in names:
            target = self.fixture_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        content = (self.fixture_root / sop_name).read_bytes().replace(
            old_hash.encode(), self.profile['sources']['manufacturer']['source_sha256'].encode())
        (self.fixture_root / sop_name).write_bytes(content)
        self.profile['sources']['sop']['source_sha256'] = digest(content)
        for module in (base_sources, base_runtime, sources, runtime):
            if hasattr(module, 'ROOT'):
                item = patch.object(module, 'ROOT', self.fixture_root)
                item.start();self.addCleanup(item.stop)
        self.evidence = self.directory / 'prospective-test-decisions.txt'
        self.evidence.write_bytes(b'Explicit test-only prospective decisions and instrument qualifications.\n')
        self.evidence_files = {'decision_evidence': self.evidence}
        self.journal = Journal(self.directory / 'sop.sqlite3')
        self.addCleanup(self.journal.close)
        # Exercise the production checked-prefix reader between commands;
        # closure and reports independently replay and audit full history.
        self.journal.state = self.journal.get_current
        self.clock = FakeClock()
        self.time_basis = self.clock.record['clock_id']
        self.serial = 0
        self.materials, self.vessels, self.reactions = self.declarations()
        self.stage_ids = {}
        self.stage_inputs = {}
        self.stage_actions = {}
        self.phase_records = {}
        self.flow = self.create()
        self.claim()

    def confirmed_sop(self):
        profile = copy.deepcopy(self.sop_profile)
        profile['qualifications'] = {
            'Test.Time.Qualification': {'kind': 'time', 'source_id': self.time_basis,
                'relationship': None, 'evidence_ref': 'decision_evidence'},
            'Test.Temperature.Qualification': {'kind': 'temperature', 'source_id': 'Test.SpecimenProbe',
                'relationship': 'sample_measurement', 'evidence_ref': 'decision_evidence'}}
        for name, requirement in profile['phase_requirements'].items():
            duration = 1800 if name.endswith('.digestion') else 10
            requirement.update(duration_min_s=duration, duration_max_s=duration,
                temperature_min_deg_c=36 if name.endswith('.release') else 3,
                temperature_max_deg_c=38 if name.endswith('.release') else 5,
                time_qualification_ref='Test.Time.Qualification',
                temperature_qualification_ref='Test.Temperature.Qualification',
                evidence_ref='decision_evidence')
        return profile

    def create(self, *, base=None, sop=None, journal=None, run_id='Test.Manual.SOP'):
        return CutRunManualSopWorkflow.create(journal or self.journal,
            {'base_profile': self.confirmed_base() if base is None else base,
             'sop_profile': self.confirmed_sop() if sop is None else sop},
            materials=self.materials, vessels=self.vessels, reactions=self.reactions,
            actors=[self.ACTOR, self.OBSERVER], run_id=run_id, clock=self.clock,
            original_pdf=self.original, evidence_files=self.evidence_files)

    def begin(self, stage_id, reaction_id=None):
        identity = 'Test.Stage.' + stage_id + '.' + (reaction_id or 'Global')
        state = self.flow.state
        if reaction_id is not None:
            material = state['manual']['reactions'][reaction_id]['current_material_id']
            vessel = state['inventory']['materials'][material]['vessel_id']
        else:
            material = vessel = None
        self.act('begin_stage', stage_id=stage_id, reaction_id=reaction_id, stage_run_id=identity)
        self.stage_ids[stage_id, reaction_id] = identity
        self.stage_inputs[identity] = (reaction_id, material, vessel)
        self.stage_actions[identity] = []
        return identity

    def category_receipts(self, stage_id):
        stage = self.flow.state['definition']['sop_protocol']['stages'][stage_id]
        return {category: 'decision_evidence' for category in stage['completion_evidence']}

    def finish(self, stage_id, reaction_id=None, *, receipts=None, action_ids=None):
        identity = self.stage_ids[stage_id, reaction_id]
        return self.act('complete_stage', stage_run_id=identity,
            receipts=self.category_receipts(stage_id) if receipts is None else receipts,
            action_ids=self.stage_actions[identity] if action_ids is None else action_ids,
            reason='Explicit test-only observed stage completion')

    def evidence_identity(self, identity, phase_id, evidence_id):
        reaction, material, vessel = self.stage_inputs[identity]
        return {'evidence_id': evidence_id, 'stage_run_id': identity, 'phase_id': phase_id,
            'reaction_id': reaction, 'material_id': material, 'vessel_id': vessel,
            'time_basis_id': self.time_basis, 'source_kind': 'test_fixture',
            'artifact_sha256': digest(self.evidence.read_bytes())}

    def phase(self, stage_id, reaction_id, phase_id, *, temperature=None, changes=None, time_changes=None):
        identity = self.stage_ids[stage_id, reaction_id]
        start = self.clock.record['monotonic_ns'] / 1_000_000_000
        requirement = self.flow.state['definition']['sop_profile']['phase_requirements'][phase_id]
        duration = requirement['duration_min_s']
        self.clock.advance(duration)
        end = self.clock.record['monotonic_ns'] / 1_000_000_000
        time = {**self.evidence_identity(identity, phase_id, 'Test.Time.' + identity + '.' + phase_id),
            'qualification_ref': 'Test.Time.Qualification', 'start_earliest_s': start,
            'start_latest_s': start, 'end_earliest_s': end, 'end_latest_s': end}
        if time_changes:time.update(time_changes)
        self.act('record_phase_time', stage_run_id=identity, phase_id=phase_id, record=time)
        value = (37 if phase_id.endswith('.release') else 4) if temperature is None else temperature
        record = {**self.evidence_identity(identity, phase_id, 'Test.Temperature.' + identity + '.' + phase_id),
            'source_id': 'Test.SpecimenProbe', 'time_qualification_ref': 'Test.Time.Qualification',
            'qualification_ref': 'Test.Temperature.Qualification',
            'from_earliest_s': start, 'from_latest_s': start, 'to_earliest_s': end,
            'to_latest_s': end, 'minimum_deg_c': value, 'maximum_deg_c': value, 'uncertainty_deg_c': 0}
        if changes:record.update(changes)
        self.act('record_phase_temperature', stage_run_id=identity, phase_id=phase_id, record=record)
        self.phase_records[identity, phase_id] = (time, record)
        return time, record

    def material_withdrawal(self, stage_id, reaction_id):
        identity = self.stage_ids[stage_id, reaction_id]
        material = self.flow.state['manual']['reactions'][reaction_id]['current_material_id']
        intent = 'Test.Material.' + identity
        self.act('begin_material_action', intent_id=intent, reaction_id=reaction_id, stage_id=stage_id,
            kind='withdrawal', inputs=[{'material_id': material,
                'quantity': {'value': 1, 'unit': 'cells'}, 'consume_all': False}], outputs=[],
            purpose='Explicit fixture-only material withdrawal; no biochemical operation')
        self.act('confirm_material_action', intent_id=intent,
            actual_inputs=[{'material_id': material, 'quantity': {'value': 1, 'unit': 'cells'}}],
            actual_outputs=[], reason='Explicit fixture-only quantity observation')
        self.stage_actions[identity].append(intent)
        return intent

    def ordinary(self, stage_id, reaction_id):
        self.begin(stage_id, reaction_id)
        self.material_withdrawal(stage_id, reaction_id)
        for phase_id in self.flow.state['definition']['sop_protocol']['stages'][stage_id]['phases']:
            self.phase(stage_id, reaction_id, phase_id)
        self.finish(stage_id, reaction_id)

    def opening(self):
        self.begin('S01');self.finish('S01')

    def to_activation(self, reaction_id=None):
        reaction_id = reaction_id or self.REFERENCE
        if ('S01', None) not in self.stage_ids:self.opening()
        for stage in ('S02', 'S03', 'S04', 'S05'):
            self.ordinary(stage, reaction_id)
        self.begin('S06', reaction_id);self.finish('S06', reaction_id)
        self.begin('S07', reaction_id)
        intent = 'Test.Activation.' + reaction_id
        self.act('begin_activation', intent_id=intent, reaction_id=reaction_id,
                 stop_access=True, mixing_available=True)
        self.act('confirm_dose', intent_id=intent, actual_volume_ul=150, mixed=True,
                 reason='Explicit fixture-only activation observation')
        self.stage_actions[self.stage_ids['S07', reaction_id]].append(intent)
        return intent

    def stop(self, reaction_id=None):
        reaction_id = reaction_id or self.REFERENCE
        intent = 'Test.Stop.' + reaction_id
        self.act('begin_stop', intent_id=intent, reaction_id=reaction_id,
                 stop_access=True, mixing_available=True)
        self.act('confirm_dose', intent_id=intent, actual_volume_ul=150, mixed=True,
                 reason='Explicit fixture-only stop dose and mixing observation')
        return intent

    def transform(self, stage_id, reaction_id, kind, value, vessel_id):
        identity = self.stage_ids[stage_id, reaction_id]
        state = self.flow.state
        material = state['manual']['reactions'][reaction_id]['current_material_id']
        quantity = ledger.remaining(state, material)
        actual = {'value': quantity['value'], 'unit': quantity['unit']}
        output_id = 'Test.Output.' + stage_id + '.' + reaction_id
        intent = 'Test.Transform.' + identity
        self.act('begin_material_action', intent_id=intent, reaction_id=reaction_id,
            stage_id=stage_id, kind='transformation',
            inputs=[{'material_id': material, 'quantity': actual, 'consume_all': True}],
            outputs=[{'material_id': output_id, 'kind': kind, 'vessel_id': vessel_id,
                      'role': 'released_fraction' if kind == 'intermediate' else 'purified_dna'}],
            retained_material_id=output_id,
            purpose='Explicit fixture transformation; quantity is observed test input, not a predicted yield')
        self.act('confirm_material_action', intent_id=intent,
            actual_inputs=[{'material_id': material, 'quantity': actual}],
            actual_outputs=[{'material_id': output_id, 'quantity': {'value': value, 'unit': 'uL'}}],
            reason='Explicit test-only observed output quantity')
        self.stage_actions[identity].append(intent)
        return output_id

    def branch(self, reaction_id):
        self.to_activation(reaction_id)
        self.phase('S07', reaction_id, 'S07.digestion')
        stop_intent = self.stop(reaction_id)
        self.finish('S07', reaction_id)
        identity = self.begin('S08', reaction_id)
        self.stage_actions[identity].append(stop_intent)
        self.phase('S08', reaction_id, 'S08.release')
        self.phase('S08', reaction_id, 'S08.separation')
        self.transform('S08', reaction_id, 'intermediate', 100,
                       self.reactions[reaction_id]['vessel_id'])
        self.finish('S08', reaction_id)
        return self.purify(reaction_id)

    def purify(self, reaction_id):
        self.begin('S10', reaction_id)
        self.phase('S10', reaction_id, 'S10.purification')
        role = self.reactions[reaction_id]['role']
        product = self.transform('S10', reaction_id, 'product', 50, 'Test.' + role + '.ProductTube')
        self.finish('S10', reaction_id)
        return product

    def qc(self):
        identity = self.begin('S11')
        checksum = self.attach()
        mappings = []
        for role, reaction_id in (('h3k4me3', self.REFERENCE), ('igg', self.IGG), ('input', self.INPUT)):
            material = self.flow.state['manual']['reactions'][reaction_id]['current_material_id']
            for method in ('fluorometry', 'qpcr'):
                intent = 'Test.QC.Withdrawal.' + role + '.' + method
                self.act('begin_qc_withdrawal', intent_id=intent, reaction_id=reaction_id,
                         method=method, quantity={'value': 2, 'unit': 'uL'})
                self.act('confirm_material_action', intent_id=intent,
                    actual_inputs=[{'material_id': material, 'quantity': {'value': 2, 'unit': 'uL'}}],
                    actual_outputs=[], reason='Explicit fixture-only product QC withdrawal')
                self.stage_actions[identity].append(intent)
                mapping_id = 'Test.QC.Mapping.' + role + '.' + method
                status = 'below_loq' if role == 'igg' and method == 'fluorometry' else 'quantified'
                self.act('map_qc', **self.mapping(checksum, role=role, reaction_id=reaction_id,
                    material_id=material, mapping_id=mapping_id, method=method,
                    locator='Test.Well.' + role + '.' + method, result_status=status,
                    value=None if status == 'below_loq' else 20 if method == 'qpcr' else 2,
                    unit='Cq' if method == 'qpcr' else 'ng/uL'))
                self.act('review_qc', mapping_id=mapping_id, decision='technically_accepted',
                         reason='Explicit test-only technical review')
                mappings.append(mapping_id)
        ntc = self.mapping(checksum, role='ntc', mapping_id='Test.QC.Mapping.ntc', method='qpcr',
            locator='Test.Well.ntc', result_status='not_detected', value=None, unit='Cq')
        ntc.update(reaction_id=None, material_id=None)
        self.act('map_qc', **ntc)
        self.act('review_qc', mapping_id=ntc['mapping_id'], decision='technically_accepted',
                 reason='Explicit test-only NTC technical review')
        mappings.append(ntc['mapping_id'])
        self.act('review_biology', mapping_ids=mappings, decision='accepted',
                 criteria_ref='decision_evidence', reason='Explicit test-only assessment, not a real biological claim')
        self.finish('S11')
        return mappings

    def test_complete_serial_sop_and_early_input_keep_ledger_qc_and_capture_distinct(self):
        self.opening()
        self.ordinary('S02', self.INPUT);self.ordinary('S09', self.INPUT)
        input_product = self.purify(self.INPUT)
        reference_product = self.branch(self.REFERENCE)
        igg_product = self.branch(self.IGG)
        mappings = self.qc()
        self.assertEqual(len(mappings), 7)
        self.begin('S12')
        for identity, material in self.flow.state['inventory']['materials'].items():
            if material['disposition'] != 'consumed':
                self.act('set_disposition', material_id=identity, disposition='retained',
                         reason='Explicit fixture-only final material handover')
        self.act('confirm_inventory', observations=self.flow.inventory_observations())
        self.finish('S12')
        # A separate forensic copy branches the software fixture after S12,
        # allowing us to challenge freshness without editing the valid run.
        altered = self.directory / 'completed-handover-copy.sqlite3'
        with sqlite3.connect(altered) as connection:
            self.journal.connection.backup(connection)
        with Journal(altered) as journal:
            journal.state = journal.get_current
            changed = CutRunManualSopWorkflow(journal, self.flow.run_id, self.flow.session, clock=self.clock)
            changed.act('review_qc', self.ACTOR, observation=self.envelope(), mapping_id=mappings[0],
                decision='technically_accepted', reason='A later review changes the evidence snapshot')
            stale = changed.report()
            self.assertFalse(stale['sop']['stages'][self.stage_ids['S11', None]]['current_assessment']['conformant'])
            self.assertFalse(stale['sop']['sequence_complete'])
            with self.assertRaises(TaskError):
                changed.act('close_capture', self.ACTOR, observation=self.envelope(), workspace_clear=True,
                            reason='A stale QC snapshot cannot close the SOP capture')
        altered = self.directory / 'changed-material-handover-copy.sqlite3'
        with sqlite3.connect(altered) as connection:
            self.journal.connection.backup(connection)
        with Journal(altered) as journal:
            journal.state = journal.get_current
            changed = CutRunManualSopWorkflow(journal, self.flow.run_id, self.flow.session, clock=self.clock)
            changed.act('set_disposition', self.ACTOR, observation=self.envelope(),
                material_id=reference_product, disposition='quarantined',
                reason='A later material decision changes the recorded handover')
            changed.act('reconcile', self.ACTOR, observation=self.envelope(),
                observations=changed.inventory_observations(), workspace_clear=True,
                reason='Fresh inventory confirms the later quarantine; it does not restore the old handover')
            stale = changed.report()
            self.assertFalse(stale['sop']['stages'][self.stage_ids['S12', None]]['current_assessment']['conformant'])
            self.assertFalse(stale['sop']['sequence_complete'])
            with self.assertRaises(TaskError):
                changed.act('close_capture', self.ACTOR, observation=self.envelope(), workspace_clear=True,
                            reason='A changed material handover cannot close using its old receipt')
        self.act('close_capture', workspace_clear=True, reason='Explicit test-only full SOP capture handover')
        report = self.flow.report()
        self.assertTrue(report['capture_completed'])
        self.assertFalse(report['reference_success']);self.assertFalse(report['passed'])
        self.assertFalse(report['execution_ready'])
        for product in (input_product, reference_product, igg_product):
            self.assertEqual(ledger.remaining(self.flow.state, product)['value'], 46)
            self.assertEqual(self.flow.state['inventory']['materials'][product]['disposition'], 'retained')
        self.assertTrue(ledger.audit(self.flow.state))

    def test_unknown_phase_parameters_stay_null_and_do_not_become_stage_success(self):
        with Journal(self.directory / 'open-sop.sqlite3') as journal:
            self.flow = self.create(sop=self.sop_profile, journal=journal, run_id='Test.Open.SOP')
            self.claim();self.opening();self.ordinary('S02', self.REFERENCE)
            profile = self.flow.state['definition']['sop_profile']
            self.assertTrue(all(value is None for requirement in profile['phase_requirements'].values()
                                for value in requirement.values()))
            before = self.flow.state
            with self.assertRaises(TaskError):self.begin('S03', self.REFERENCE)
            self.assertEqual(self.flow.state, before)
            self.act('record_observation', stage_id='S03', reaction_id=self.REFERENCE,
                status='unknown', details={'reason': 'Open phase bounds remain unknown'})
            self.assertFalse(self.flow.report()['reference_success'])

    def test_creation_archives_new_profile_and_protocol_as_a_distinct_engine(self):
        definition = self.flow.state['definition']
        self.assertEqual(definition['profile']['type'], 'cutrun_manual_sop/1')
        manifest = definition['initial_artifact_sha256']
        protocol = (self.fixture_root / sources.PROTOCOL).read_bytes()
        self.assertIn(digest(protocol), manifest)
        self.assertEqual(self.journal.artifact(digest(protocol)), protocol)
        profile = encoded(self.confirmed_sop()).encode()
        self.assertIn(digest(profile), manifest)
        self.assertEqual(self.journal.artifact(digest(profile)), profile)
        self.assertFalse(self.flow.report()['reference_success'])

    def test_a_stage_original_created_during_the_run_is_preserved_and_can_support_completion(self):
        self.begin('S01')
        raw = b'Observed stage original created after the prospective profile\r\n\x00\xff'
        checksum = digest(raw)
        self.act('attach_sop_evidence', artifact=raw, file_name='stage-original.bin', origin='test_fixture')
        self.assertEqual(self.journal.artifact(checksum), raw)
        self.finish('S01', receipts={category: checksum for category in self.category_receipts('S01')})
        self.assertTrue(self.flow.report()['sop']['stages'][self.stage_ids['S01', None]]['current_assessment']['conformant'])
        self.journal.connection.execute('DELETE FROM artifacts WHERE sha256=?', (checksum,))
        with self.assertRaisesRegex(TaskError, 'Missing or corrupt artifact'):
            self.flow.report()

    def test_free_notes_and_generic_material_calls_cannot_skip_the_stage_sequence(self):
        self.act('record_observation', stage_id='S10', reaction_id=self.REFERENCE,
                 status='observed', details={'claim': 'A note is not stage completion'})
        before = self.flow.state
        with self.assertRaises(TaskError):self.begin('S10', self.REFERENCE)
        with self.assertRaises(TaskError):
            self.act('begin_material_action', intent_id='Test.Bypass', reaction_id=self.REFERENCE,
                stage_id='S10', kind='withdrawal', inputs=[{'material_id': 'Test.h3k4me3',
                'quantity': {'value': 1, 'unit': 'cells'}, 'consume_all': False}], outputs=[],
                purpose='Attempt to bypass the SOP stage gate')
        self.assertEqual(self.flow.state, before)

    def test_input_has_an_early_separate_route_and_cannot_enter_activation_branch(self):
        self.opening();self.ordinary('S02', self.INPUT)
        self.ordinary('S09', self.INPUT)
        before = self.flow.state
        with self.assertRaises(TaskError):self.begin('S04', self.INPUT)
        with self.assertRaises(TaskError):
            self.act('begin_activation', intent_id='Test.InputActivation', reaction_id=self.INPUT,
                     stop_access=True, mixing_available=True)
        self.assertEqual(self.flow.state, before)
        self.begin('S10', self.INPUT)

    def test_missing_typed_completion_receipt_cannot_advance_the_stage(self):
        self.begin('S01')
        receipts = self.category_receipts('S01')
        receipts.pop(next(iter(receipts)))
        with self.assertRaises(TaskError):self.finish('S01', receipts=receipts)
        with self.assertRaises(TaskError):self.begin('S02', self.REFERENCE)
        self.finish('S01')
        self.begin('S02', self.REFERENCE)

    def test_material_receipts_from_a_different_stage_cannot_prove_this_stage(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        old_action = self.stage_actions[self.stage_ids['S02', self.REFERENCE]][0]
        self.begin('S03', self.REFERENCE)
        self.phase('S03', self.REFERENCE, 'S03.preparation')
        with self.assertRaises(TaskError):self.finish('S03', self.REFERENCE, action_ids=[old_action])

    def test_capture_only_engine_cannot_open_a_sop_run_as_its_own_contract(self):
        before, history = self.flow.state, self.journal.history(self.flow.run_id)
        with self.assertRaises(TaskError):
            base_runtime.CutRunManualWorkflow.open(self.journal, self.flow.run_id, resume=True, clock=self.clock)
        self.assertEqual(self.flow.state, before)
        self.assertEqual(self.journal.history(self.flow.run_id), history)

    def test_unknown_temperature_uncertainty_is_preserved_but_not_phase_qualification(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        self.begin('S03', self.REFERENCE);self.material_withdrawal('S03', self.REFERENCE)
        self.phase('S03', self.REFERENCE, 'S03.preparation', changes={'uncertainty_deg_c': None})
        with self.assertRaises(TaskError):self.finish('S03', self.REFERENCE)
        self.assertFalse(self.flow.report()['reference_success'])

    def test_unknown_occurrence_maximum_is_not_replaced_by_the_capture_time(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        self.begin('S03', self.REFERENCE);self.material_withdrawal('S03', self.REFERENCE)
        self.phase('S03', self.REFERENCE, 'S03.preparation', time_changes={'end_latest_s': None})
        with self.assertRaises(TaskError):self.finish('S03', self.REFERENCE)
        self.assertFalse(self.flow.report()['reference_success'])

    def test_a_registered_setpoint_source_is_archiveable_but_cannot_qualify_specimen_temperature(self):
        profile = self.confirmed_sop()
        profile['qualifications']['Test.Setpoint.Qualification'] = {
            'kind': 'temperature', 'source_id': 'Test.Device.Setpoint',
            'relationship': 'device_setpoint', 'evidence_ref': 'decision_evidence'}
        with Journal(self.directory / 'setpoint.sqlite3') as journal:
            self.flow = self.create(sop=profile, journal=journal, run_id='Test.Setpoint.SOP')
            self.claim();self.opening();self.ordinary('S02', self.REFERENCE)
            self.begin('S03', self.REFERENCE);self.material_withdrawal('S03', self.REFERENCE)
            self.phase('S03', self.REFERENCE, 'S03.preparation', changes={
                'qualification_ref': 'Test.Setpoint.Qualification', 'source_id': 'Test.Device.Setpoint'})
            with self.assertRaises(TaskError):self.finish('S03', self.REFERENCE)
            self.assertFalse(self.flow.report()['reference_success'])

    def test_sparse_point_temperatures_do_not_fill_the_process_interval(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        self.begin('S03', self.REFERENCE);self.material_withdrawal('S03', self.REFERENCE)
        time, record = self.phase('S03', self.REFERENCE, 'S03.preparation',
            changes={'to_earliest_s': 0, 'to_latest_s': 0})
        # Both points are real declared fixture observations. Neither claims
        # continuous specimen temperature between them.
        second = {**record, 'evidence_id': 'Test.Last.Point',
            'from_earliest_s': time['end_latest_s'], 'from_latest_s': time['end_latest_s'],
            'to_earliest_s': time['end_latest_s'], 'to_latest_s': time['end_latest_s']}
        self.act('record_phase_temperature', stage_run_id=record['stage_run_id'],
                 phase_id='S03.preparation', record=second)
        with self.assertRaises(TaskError):self.finish('S03', self.REFERENCE)

    def test_wrong_specimen_or_phase_is_rejected_without_installing_evidence(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        self.begin('S03', self.REFERENCE);self.material_withdrawal('S03', self.REFERENCE)
        time, record = self.phase('S03', self.REFERENCE, 'S03.preparation')
        before = self.flow.state
        bad = {**record, 'evidence_id': 'Test.Wrong.Specimen', 'vessel_id': 'Test.igg.Tube'}
        with self.assertRaises(TaskError):
            self.act('record_phase_temperature', stage_run_id=record['stage_run_id'],
                     phase_id='S03.preparation', record=bad)
        self.assertEqual(self.flow.state, before)

    def test_declared_observer_can_supply_evidence_without_taking_the_claimed_work(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        self.begin('S03', self.REFERENCE);self.material_withdrawal('S03', self.REFERENCE)
        _, record = self.phase('S03', self.REFERENCE, 'S03.preparation')
        observed = {**record, 'evidence_id': 'Test.Second.Observer.Specimen.Record'}
        self.act('record_phase_temperature', actor=self.OBSERVER,
                 stage_run_id=record['stage_run_id'], phase_id='S03.preparation', record=observed)
        event = self.journal.history(self.flow.run_id)[-1]
        self.assertEqual(event['payload']['actor_id'], self.OBSERVER)
        self.assertEqual(self.flow.state['actor_id'], self.ACTOR)
        self.finish('S03', self.REFERENCE)

    def test_an_early_protective_stop_remains_recordable_without_nominal_stage_completion(self):
        self.to_activation();self.clock.advance(1)
        self.stop()
        state = self.flow.state
        self.assertEqual(state['manual']['reactions'][self.REFERENCE]['status'], 'stopped')
        stop = state['manual']['reactions'][self.REFERENCE]['stop']['intent_id']
        self.assertEqual(state['bookings'][stop]['outcome'], 'performed')
        self.assertEqual(ledger.remaining(state, 'Test.h3k4me3.stop')['value'], 350)
        with self.assertRaises(TaskError):self.finish('S07', self.REFERENCE)

    def test_release_and_separation_cannot_be_declared_overlapping_while_each_looks_valid_alone(self):
        self.to_activation();self.phase('S07', self.REFERENCE, 'S07.digestion')
        stop = self.stop();self.finish('S07', self.REFERENCE)
        identity = self.begin('S08', self.REFERENCE);self.stage_actions[identity].append(stop)
        released, _ = self.phase('S08', self.REFERENCE, 'S08.release')
        start, end = released['start_earliest_s'], released['end_latest_s']
        self.phase('S08', self.REFERENCE, 'S08.separation',
            time_changes={'start_earliest_s': start, 'start_latest_s': start,
                          'end_earliest_s': end, 'end_latest_s': end},
            changes={'from_earliest_s': start, 'from_latest_s': start,
                     'to_earliest_s': end, 'to_latest_s': end})
        self.transform('S08', self.REFERENCE, 'intermediate', 100,
                       self.reactions[self.REFERENCE]['vessel_id'])
        with self.assertRaises(TaskError):self.finish('S08', self.REFERENCE)

    def test_qualified_external_clock_does_not_allow_overlapping_successive_stages(self):
        self.time_basis = 'Test.External.Qualified.Clock'
        with Journal(self.directory / 'external-clock.sqlite3') as journal:
            journal.state = journal.get_current
            self.flow = self.create(journal=journal, run_id='Test.External.Clock.SOP')
            self.claim();self.opening();self.ordinary('S02', self.REFERENCE)
            self.ordinary('S03', self.REFERENCE)
            self.begin('S04', self.REFERENCE);self.material_withdrawal('S04', self.REFERENCE)
            self.phase('S04', self.REFERENCE, 'S04.antibody_incubation',
                time_changes={'start_earliest_s': 0, 'start_latest_s': 0,
                              'end_earliest_s': 10, 'end_latest_s': 10},
                changes={'from_earliest_s': 0, 'from_latest_s': 0,
                         'to_earliest_s': 10, 'to_latest_s': 10})
            with self.assertRaises(TaskError):self.finish('S04', self.REFERENCE)
            self.assertFalse(self.flow.report()['reference_success'])

    def test_external_duration_cannot_override_a_known_one_second_normal_activation_stop_interval(self):
        self.time_basis = 'Test.External.Qualified.Clock'
        for stop_kind in ('normal', 'retrospective'):
            with self.subTest(stop_kind=stop_kind), Journal(self.directory / (stop_kind + '-external-duration.sqlite3')) as journal:
                journal.state = journal.get_current
                self.stage_ids, self.stage_inputs, self.stage_actions, self.phase_records = {}, {}, {}, {}
                self.flow = self.create(journal=journal, run_id='Test.External.Duration.' + stop_kind)
                self.claim();self.to_activation()
                start = self.clock.record['monotonic_ns'] / 1_000_000_000
                self.clock.advance(1)
                if stop_kind == 'normal':self.stop()
                else:
                    self.act('record_external_stop', reaction_id=self.REFERENCE, actual_volume_ul=150,
                        mixed=True, reason='Observed actual stop was captured one second after normal activation')
                identity = self.stage_ids['S07', self.REFERENCE]
                time = {**self.evidence_identity(identity, 'S07.digestion', 'Test.False.External.Duration'),
                    'qualification_ref': 'Test.Time.Qualification', 'start_earliest_s': start,
                    'start_latest_s': start, 'end_earliest_s': start + 1800, 'end_latest_s': start + 1800}
                temperature = {
                    **self.evidence_identity(identity, 'S07.digestion', 'Test.False.External.Duration.Temperature'),
                    'source_id': 'Test.SpecimenProbe', 'time_qualification_ref': 'Test.Time.Qualification',
                    'qualification_ref': 'Test.Temperature.Qualification',
                    'from_earliest_s': start, 'from_latest_s': start, 'to_earliest_s': start + 1800,
                    'to_latest_s': start + 1800, 'minimum_deg_c': 4, 'maximum_deg_c': 4,
                    'uncertainty_deg_c': 0}
                self.act('record_phase_time', stage_run_id=identity, phase_id='S07.digestion', record=time)
                self.act('record_phase_temperature', stage_run_id=identity, phase_id='S07.digestion', record=temperature)
                with self.assertRaises(TaskError):self.finish('S07', self.REFERENCE)
                self.assertFalse(self.flow.report()['sop']['stages'][identity]['current_assessment']['conformant'])

    def test_nominal_activation_temperature_must_fit_the_prospective_phase_limits(self):
        profile = self.confirmed_sop()
        profile['phase_requirements']['S07.digestion'].update(temperature_min_deg_c=36, temperature_max_deg_c=38)
        with Journal(self.directory / 'contradictory-temperature-target.sqlite3') as journal:
            journal.state = journal.get_current
            self.flow = self.create(journal=journal, sop=profile, run_id='Test.Contradictory.Temperature.Target')
            self.claim()
            with self.assertRaises(TaskError):self.to_activation()
            reaction = self.flow.state['manual']['reactions'][self.REFERENCE]
            self.assertIsNone(reaction['activation'])
            self.assertEqual(ledger.remaining(self.flow.state, 'Test.h3k4me3.activation')['value'], 500)

    def test_restart_keeps_open_stage_and_pending_activation_without_replay_or_deadline_reset(self):
        self.opening()
        for stage in ('S02', 'S03', 'S04', 'S05'):
            self.ordinary(stage, self.REFERENCE)
        self.begin('S06', self.REFERENCE);self.finish('S06', self.REFERENCE)
        self.begin('S07', self.REFERENCE)
        self.act('begin_activation', intent_id='Test.Pending.Activation', reaction_id=self.REFERENCE,
                 stop_access=True, mixing_available=True)
        before = self.flow.state
        resumed = CutRunManualSopWorkflow.open(self.journal, self.flow.run_id,
                                              resume=True, clock=self.clock)
        after = resumed.state
        self.assertEqual(after['bookings'], before['bookings'])
        self.assertEqual(after['manual']['reactions'], before['manual']['reactions'])
        self.assertEqual(after['deadline_s'], before['deadline_s'])
        self.assertEqual(after['pending_operation'], {'intent_id': 'Test.Pending.Activation'})
        self.assertNotEqual(resumed.session, self.flow.session)
        with self.assertRaises(TaskError):
            self.act('confirm_dose', intent_id='Test.Pending.Activation', actual_volume_ul=150,
                     mixed=True, reason='A fenced old writer must fail')

    def test_late_conflicting_temperature_cannot_be_erased_by_later_good_coverage(self):
        self.opening();self.ordinary('S02', self.REFERENCE)
        self.ordinary('S03', self.REFERENCE)
        identity = self.stage_ids['S03', self.REFERENCE]
        _, previous = self.phase_records[identity, 'S03.preparation']
        bad = {**previous, 'evidence_id': 'Test.Late.Contradiction',
               'minimum_deg_c': 99, 'maximum_deg_c': 99}
        self.act('record_phase_temperature', stage_run_id=identity,
                 phase_id='S03.preparation', record=bad)
        good = {**previous, 'evidence_id': 'Test.Later.Good.Coverage'}
        self.act('record_phase_temperature', stage_run_id=identity,
                 phase_id='S03.preparation', record=good)
        self.assertIsNotNone(self.flow.state['recovery_required'])
        with self.assertRaises(TaskError):self.begin('S04', self.REFERENCE)
        self.assertFalse(self.flow.report()['reference_success'])

    def test_close_capture_cannot_bypass_unfinished_sop_stages(self):
        self.opening()
        with self.assertRaises(TaskError):
            self.act('close_capture', workspace_clear=True, reason='Attempt to skip the remaining SOP')


class ManualSopCliTests(unittest.TestCase):
    ACTOR = capture_cli.CutrunManualCliTests.ACTOR
    RUN = capture_cli.CutrunManualCliTests.RUN
    setUp = capture_cli.CutrunManualCliTests.setUp
    run_cli = capture_cli.CutrunManualCliTests.run_cli
    create = capture_cli.CutrunManualCliTests.create
    snapshot = capture_cli.CutrunManualCliTests.snapshot
    observation = capture_cli.CutrunManualCliTests.observation

    def test_default_prepare_includes_all_sop_stages_and_keeps_all_phase_bounds_open(self):
        result, plan = self.run_cli('prepare')
        self.assertEqual(result.returncode, 0, plan.get('error', result.stderr))
        self.assertEqual(set(plan['sop_protocol']['stages']), {'S%02d' % number for number in range(1, 13)})
        self.assertEqual(plan['sop_profile']['qualifications'], {})
        self.assertTrue(all(value is None for phase in plan['sop_profile']['phase_requirements'].values()
                            for value in phase.values()))
        self.assertFalse(plan['preparation_complete']);self.assertFalse(plan['can_claim_reference_success'])
        self.assertFalse(self.store.exists())

    def test_default_create_uses_the_recipe_engine_and_read_only_report_keeps_unstarted_stages(self):
        created = self.create()
        self.assertEqual(created['state']['definition']['profile']['type'], 'cutrun_manual_recipe/1')
        before = self.snapshot()
        result, report = self.run_cli('report', self.RUN)
        self.assertEqual(result.returncode, 0, report.get('error', result.stderr))
        self.assertFalse(report['sop']['sequence_complete'])
        self.assertTrue(report['sop']['stage_order_enforced'])
        self.assertEqual(report['sop']['stages'], {})
        self.assertEqual(self.snapshot(), before)

    def test_capture_only_run_remains_capture_only_through_cli_dispatch(self):
        inventory = json.loads(self.inventory.read_text())
        with Journal(self.store) as journal:
            flow = base_runtime.CutRunManualWorkflow.create(journal, **inventory, run_id=self.RUN)
            session = flow.session
        before = self.snapshot()
        result, report = self.run_cli('report', self.RUN)
        self.assertEqual(result.returncode, 0, report.get('error', result.stderr))
        self.assertEqual(report['format'], base_runtime.CutRunManualWorkflow.REPORT_FORMAT)
        self.assertNotIn('sop', report)
        self.assertEqual(self.snapshot(), before)
        result, error = self.run_cli('act', self.RUN, '--session', session, '--actor', self.ACTOR,
            '--action', 'begin_stage', '--observation', self.observation(),
            '--data', json.dumps({'stage_id': 'S01', 'reaction_id': None, 'stage_run_id': 'Test.No.Migration'}))
        self.assertEqual(result.returncode, 1)
        self.assertIn('error', error)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
