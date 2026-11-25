"""Exercise consolidated S09 using explicit synthetic originals and clocks."""

import copy
import json
import shutil
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from test_cutrun_manual_recipe_workflow import ROOT, RecipeFixture
from cutrun_input_sonication_demo import FixtureSession
from cutrun_input_sonication_workflow import InputSonicationWorkflow
from cutrun_manual_recipe_workflow import CutRunManualRecipeWorkflow
from cutrun_manual_sop_workflow import CutRunManualSopWorkflow
from cutrun_manual_workflow import CutRunManualWorkflow
import cutrun_manual_recipe_v2_sources as sources
from cutrun_manual_recipe_v2_workflow import CutRunManualRecipeV2, CLARIFICATION, LYSIS_MIXTURE
from manual_process_clock import SystemClock
from manual_tasks import Journal, TaskError, digest
import material_ledger as ledger


class IntegratedInputTests(RecipeFixture, TestCase):
    def setUp(self):
        self.fixture_setup()
        for name in {*sources.RUNTIME, sources.PREFLIGHT}:
            target = self.fixture_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        protocol_path = self.fixture_root / sources.PROTOCOL
        protocol = json.loads(protocol_path.read_bytes())
        reference = protocol['recipe_protocol']
        reference['source_sha256'] = digest((self.fixture_root / reference['source']).read_bytes())
        protocol_path.write_text(json.dumps(protocol))
        self.input_profile = json.loads((self.fixture_root / sources.SOURCE).read_bytes())
        self.input_profile['protocol']['source_sha256'] = digest(protocol_path.read_bytes())
        for phase, binding in self.input_profile['phase_requirements'].items():
            binding.update(copy.deepcopy(self.confirmed_sop()['phase_requirements'][sources.SONICATION]))
            if phase == sources.LYSIS:
                binding.update(temperature_min_deg_c=20, temperature_max_deg_c=22)
        self.input_profile['input_sonication'].update(
            input_reaction_id=self.INPUT, device_instance_id='Test.Sonicator',
            sonicator_place_id='Test.Port', cycles=2, pulse_on_s=2, between_pulses_s=1,
            amplitude_percent=12, fill_volume_ul=22, plan_evidence_ref='decision_evidence',
            size_minimum_bp=150, size_maximum_bp=450, size_criteria_evidence_ref='decision_evidence')
        root = patch.object(sources, 'ROOT', self.fixture_root)
        root.start()
        self.addCleanup(root.stop)
        self.mode = 'manual_observation'

    def create(self, *, recipe=None, journal=None, run_id='Test.Manual.RecipeV2', clock=None):
        profile = {**self.input_profile, 'mode': self.mode}
        provider = clock or self.clock
        if clock is None:
            self.clock.record['source_kind'] = sources.MODES[self.mode]
        return CutRunManualRecipeV2.create(journal or self.journal,
            {'base_profile': self.confirmed_base(), 'sop_profile': self.confirmed_sop(),
             'recipe_profile': self.confirmed_recipe() if recipe is None else recipe, 'input_profile': profile},
            materials=self.materials, vessels=self.vessels, reactions=self.reactions,
            actors=[self.ACTOR, self.OBSERVER], run_id=run_id, clock=provider,
            original_pdf=self.original if self.mode == 'manual_observation' else None,
            evidence_files=self.evidence_files)

    def envelope(self, **kwargs):
        observation = super().envelope(**kwargs)
        if self.mode == 'manual_observation':
            observation['source_kind'] = 'human_observation'
        return observation

    def seconds(self):
        return self.clock.record['monotonic_ns'] / 1e9

    def input_phase(self, phase, material, start, end, value, *, temperature=True):
        stage_id = self.stage_ids['S09', self.INPUT]
        vessel = self.reactions[self.INPUT]['vessel_id']
        identity = {'stage_run_id': stage_id, 'phase_id': phase, 'reaction_id': self.INPUT,
                    'material_id': material, 'vessel_id': vessel, 'time_basis_id': self.time_basis,
                    'source_kind': self.envelope()['source_kind'], 'artifact_sha256': digest(self.evidence.read_bytes())}
        self.act('record_phase_time', stage_run_id=stage_id, phase_id=phase, record={
            **identity, 'evidence_id': phase + '.Time', 'qualification_ref': 'Test.Time.Qualification',
            'start_earliest_s': start, 'start_latest_s': start, 'end_earliest_s': end, 'end_latest_s': end})
        thermal = {**identity, 'evidence_id': phase + '.Temperature', 'source_id': 'Test.SpecimenProbe',
            'qualification_ref': 'Test.Temperature.Qualification', 'time_qualification_ref': 'Test.Time.Qualification',
            'from_earliest_s': start, 'from_latest_s': start, 'to_earliest_s': end, 'to_latest_s': end,
            'minimum_deg_c': value, 'maximum_deg_c': value, 'uncertainty_deg_c': 0}
        if temperature:
            self.act('record_phase_temperature', stage_run_id=stage_id, phase_id=phase, record=thermal)
        return thermal

    def move_input(self, location):
        observations = self.flow.inventory_observations()
        vessel = self.reactions[self.INPUT]['vessel_id']
        next(row for row in observations if row['vessel_id'] == vessel)['location'] = location
        self.act('confirm_inventory', observations=observations)

    def through_lysis(self):
        self.start()
        self.to_stage('S09', self.INPUT)
        self.original_location = copy.deepcopy(next(row['location'] for row in self.flow.inventory_observations()
            if row['vessel_id'] == self.reactions[self.INPUT]['vessel_id']))
        retained = 'Test.Recipe.Operation.%03d.Retained' % (self.operation_serial + 1)
        self.perform('S09', self.INPUT, outputs=[{'material_id': retained, 'role': LYSIS_MIXTURE,
            'kind': 'intermediate', 'vessel_id': self.reactions[self.INPUT]['vessel_id']}],
            actual_outputs=[{'material_id': retained, 'quantity': {'value': 22, 'unit': 'uL'}}])
        self.perform('S09', self.INPUT)
        start = self.seconds()
        self.clock.advance(10)
        self.lysis_temperature = self.input_phase(sources.LYSIS, retained, start, self.seconds(), 21)
        self.move_input({'kind': 'logical', 'holder_id': 'Test.Sonicator', 'place_id': 'Test.Port'})
        self.lysate = retained
        return retained

    def begin_sonication(self, intent='Test.Sonic', reaction=None):
        return self.act('begin_sonication', intent_id=intent, reaction_id=reaction or self.INPUT,
            stage_run_id=self.stage_ids['S09', self.INPUT], output_material_id='Test.Sonicated',
            reason='Record the explicit test intent')

    def through_sonication(self):
        self.through_lysis()
        start = self.seconds()
        self.begin_sonication()
        self.clock.advance(10)
        self.act('confirm_sonication', intent_id='Test.Sonic', actual_output_quantity={'value': 22, 'unit': 'uL'},
            observed_vessel_id=self.reactions[self.INPUT]['vessel_id'], reason='Observed test effect',
            artifact=b'Independent physical receipt for the test sonication.')
        self.stage_actions[self.stage_ids['S09', self.INPUT]].append('Test.Sonic')
        self.input_phase(sources.SONICATION, self.lysate, start, self.seconds(), 4)
        self.move_input(self.original_location)

    def withdraw(self, identity='Test.SizeWithdrawal', material='Test.Sonicated'):
        self.act('begin_material_action', intent_id=identity, reaction_id=self.INPUT, stage_id='S09',
            kind='withdrawal', inputs=[{'material_id': material, 'quantity': {'value': 2, 'unit': 'uL'},
                                       'consume_all': False}], outputs=[], purpose='Test fragment-size QC sample')
        self.act('confirm_material_action', intent_id=identity,
            actual_inputs=[{'material_id': material, 'quantity': {'value': 2, 'unit': 'uL'}}],
            actual_outputs=[], reason='Separately observed fragment-size QC consumption')
        self.stage_actions[self.stage_ids['S09', self.INPUT]].append(identity)

    def size(self, withdrawal='Test.SizeWithdrawal'):
        return self.act('record_sonication_size', intent_id='Test.Sonic', size_id='Test.FragmentSize',
            withdrawal_intent_id=withdrawal, minimum_bp=200, maximum_bp=300, reason='Explicit observed test result',
            artifact=b'Opaque test fragment size original with sample mapping.')

    def test_real_s09_blocks_without_size_and_requires_its_own_withdrawal(self):
        self.through_sonication()
        with self.assertRaisesRegex(TaskError, 'fragment-size evidence'):
            self.finish('S09', self.INPUT)
        with self.assertRaisesRegex(TaskError, 'own confirmed root QC withdrawal'):
            self.size('Test.Sonic')
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='The rejected test record produced no material effect')
        self.withdraw()
        with self.assertRaisesRegex(TaskError, 'fragment-size evidence'):
            self.finish('S09', self.INPUT)
        self.size()
        self.assertEqual(ledger.remaining(self.flow.state, 'Test.Sonicated')['value'], 20)
        original = self.flow.state['bookings']['Test.SizeWithdrawal']['actual_inputs'][0]
        self.assertEqual(original['material_id'], 'Test.Sonicated')
        report = self.flow.report()
        self.assertEqual(report['mode'], 'manual_observation')
        self.assertFalse(report['execution_ready'])
        size = report['sonication']['intents']['Test.Sonic']['size_records']['Test.FragmentSize']
        checksum = size['observation']['artifact_sha256']
        self.assertEqual(self.journal.artifact(checksum), b'Opaque test fragment size original with sample mapping.')
        for role in (self.INPUT, self.REFERENCE, self.IGG):
            other = self.reactions[role]['material_id']
            balance = ledger.remaining(self.flow.state, other)
            with self.assertRaisesRegex(TaskError, 'from the sonicated Input'):
                self.withdraw('Test.WrongWithdrawal.' + role, other)
            self.assertEqual(ledger.remaining(self.flow.state, other), balance)
            self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                     reason='The rejected wrong-material request produced no effect')

    def test_separate_phase_temperature_and_complete_input_into_column_stage(self):
        self.through_sonication()
        self.withdraw()
        self.size()
        start = self.seconds()
        # The physical clarification receipt and the specimen-temperature
        # record are separate observations, each linked to its own phase.
        following = self.flow.recipe_next(self.stage_ids['S09', self.INPUT])
        self.assertEqual((following['step_id'], following['operation']), (CLARIFICATION, 'separate'))
        identity = self.stage_ids['S09', self.INPUT]
        self.act('begin_recipe_operation', stage_run_id=identity, step_id=CLARIFICATION,
                 iteration=following['iteration'], operation='separate', intent_id='Test.Clarify')
        self.clock.advance(10)
        self.act('confirm_recipe_operation', intent_id='Test.Clarify', actual_inputs=[], actual_outputs=[],
                 observations={'performed': True, 'separated': True}, reason='Observed test clarification')
        thermal = self.input_phase(sources.CLARIFICATION, 'Test.Sonicated', start, self.seconds(), 4, temperature=False)
        with self.assertRaisesRegex(TaskError, 'clarification time and temperature'):
            self.perform('S09', self.INPUT)
        with self.assertRaisesRegex(TaskError, 'identity mismatch'):
            self.act('record_phase_temperature', stage_run_id=identity, phase_id=sources.CLARIFICATION,
                     record=self.lysis_temperature)
        self.act('record_phase_temperature', stage_run_id=identity, phase_id=sources.CLARIFICATION, record=thermal)
        self.perform('S09', self.INPUT)
        self.finish('S09', self.INPUT)
        self.begin('S10', self.INPUT)
        stage = self.flow.state['sop']['stages'][identity]
        self.assertEqual(stage['status'], 'completed')
        self.assertEqual(list(stage['phases']), list(sources.PHASES))

    def test_s02_cannot_capture_lysis_and_enriched_reactions_cannot_sonicate(self):
        self.start()
        self.opening()
        stage = self.begin('S02', self.INPUT)
        with self.assertRaisesRegex(TaskError, 'belong to S09'):
            self.act('record_phase_time', stage_run_id=stage, phase_id=sources.LYSIS, record={})
        with self.assertRaisesRegex(TaskError, 'belong to S09'):
            self.act('begin_recipe_operation', stage_run_id=stage, step_id='S02.cell_resuspension',
                     iteration=1, operation='add', intent_id='Test.WrongStage',
                     outputs=[{'material_id': 'Test.FalseLysate', 'role': LYSIS_MIXTURE}])
        self.finish('S02', self.INPUT)
        self.begin('S09', self.INPUT)
        for branch in (self.REFERENCE, self.IGG):
            with self.assertRaisesRegex(TaskError, 'Begin|open|S09'):
                self.begin_sonication(reaction=branch)
        with self.assertRaisesRegex(TaskError, 'qualified lysis'):
            self.begin_sonication()

    def test_restart_cannot_replay_effect_and_unknown_holds_the_root_resources(self):
        self.mode = 'test_fixture'
        self.through_lysis()
        self.begin_sonication()
        old_session = self.flow.session
        self.flow = CutRunManualRecipeV2.open(self.journal, self.flow.run_id, resume=True, clock=self.clock)
        self.assertNotEqual(old_session, self.flow.session)
        self.assertTrue(self.flow.report()['sonication']['intents']['Test.Sonic']['continuation_uncertain'])
        with self.assertRaisesRegex(TaskError, 'explicit resolve_sonication'):
            self.act('confirm_sonication', intent_id='Test.Sonic', actual_output_quantity={'value': 22, 'unit': 'uL'},
                observed_vessel_id=self.reactions[self.INPUT]['vessel_id'], reason='Invalid automatic replay',
                artifact=b'Replayed observation')
        self.act('resolve_sonication', intent_id='Test.Sonic', outcome='unknown', reason='No attributable effect receipt')
        state = self.flow.state
        self.assertEqual(state['bookings']['Test.Sonic']['outcome'], 'unknown')
        self.assertIn('sonicator:Test.Sonicator', state['resources'])
        self.assertIn('material:' + self.lysate, state['resources'])
        self.assertIn('vessel:' + self.reactions[self.INPUT]['vessel_id'], state['resources'])
        self.assertNotIn('Test.Sonicated', state['inventory']['materials'])
        with self.assertRaises(TaskError):
            self.begin_sonication(intent='Test.Replay')

    def test_clock_and_observation_modes_cannot_mix(self):
        self.flow = self.create(run_id='Test.Manual.Observation')
        real_state = self.flow.state
        with self.assertRaisesRegex(TaskError, 'cannot be mixed'):
            self.act('check_clock', envelope={**self.envelope(), 'source_kind': 'test_fixture'})
        self.assertEqual(self.flow.state, real_state)
        self.mode = 'test_fixture'
        with self.assertRaisesRegex(TaskError, 'clock source must agree'):
            self.create(clock=SystemClock())
        with Journal(self.directory / 'mode-fixture.sqlite3') as journal:
            self.flow = self.create(journal=journal)
            with self.assertRaisesRegex(TaskError, 'cannot be mixed'):
                self.act('check_clock', envelope={**self.envelope(), 'source_kind': 'human_observation'})
            with self.assertRaisesRegex(TaskError, 'Clock source kind cannot switch'):
                CutRunManualRecipeV2.open(journal, self.flow.run_id, resume=True, clock=SystemClock())

    def test_existing_manual_engines_open_on_unchanged_roots_and_pins(self):
        base = self.confirmed_base()
        sop = self.confirmed_sop()
        recipe = self.confirmed_recipe()
        for engine, source in (
            (CutRunManualWorkflow, base),
            (CutRunManualSopWorkflow, {'base_profile': base, 'sop_profile': sop}),
            (CutRunManualRecipeWorkflow, {'base_profile': base, 'sop_profile': sop, 'recipe_profile': recipe}),
        ):
            with self.subTest(engine=engine.ENGINE), Journal(self.directory / (engine.ENGINE.split('/')[0] + '.sqlite3')) as journal:
                old = engine.create(journal, source, materials=self.materials, vessels=self.vessels,
                    reactions=self.reactions, actors=[self.ACTOR], clock=self.clock, original_pdf=self.original,
                    evidence_files=self.evidence_files, run_id='Test.Existing.Manual')
                before = journal.state(old.run_id)
                self.assertEqual(engine(journal, old.run_id, None, clock=self.clock).report()['format'], engine.REPORT_FORMAT)
                with self.assertRaisesRegex(TaskError, 'Matching consolidated recipe'):
                    CutRunManualRecipeV2.open(journal, old.run_id, resume=True, clock=self.clock)
                self.assertEqual(journal.state(old.run_id), before)


class LegacySonicationReadsTests(TestCase):
    def test_existing_sonication_engine_remains_readable_without_migration(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'exports') as directory, Journal(Path(directory) / 'journal.sqlite3') as journal:
            fixture = FixtureSession(journal, 'TEST.RecipeV2.LegacySonication', directory)
            identity = fixture.flow.run_id
            before = journal.state(identity)
            report = InputSonicationWorkflow(journal, identity, None).report()
            self.assertEqual(report['format'], InputSonicationWorkflow.REPORT_FORMAT)
            with self.assertRaisesRegex(TaskError, 'Matching consolidated recipe'):
                CutRunManualRecipeV2.open(journal, identity, resume=True, clock=fixture.clock)
            self.assertEqual(journal.state(identity), before)
