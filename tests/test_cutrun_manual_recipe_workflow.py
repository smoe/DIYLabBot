"""Recipe tests use explicit fixture quantities, never laboratory defaults."""
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

import cutrun_manual_sources as base_sources
import cutrun_manual_workflow as base_runtime
import cutrun_manual_sop_sources as sop_sources
import cutrun_manual_sop_workflow as sop_runtime
import material_ledger as ledger
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError
import test_cutrun_manual_sop_workflow as sop_fixture
from test_manual_process_clock import FakeClock


class RecipeFixture:
    """Composition avoids rerunning inherited SOP tests under a different API."""
    ACTOR = sop_fixture.ManualSopWorkflowTests.ACTOR
    OBSERVER = sop_fixture.ManualSopWorkflowTests.OBSERVER
    REFERENCE = sop_fixture.ManualSopWorkflowTests.REFERENCE
    IGG = sop_fixture.ManualSopWorkflowTests.IGG
    INPUT = sop_fixture.ManualSopWorkflowTests.INPUT
    confirmed_base = sop_fixture.ManualSopWorkflowTests.confirmed_base
    confirmed_sop = sop_fixture.ManualSopWorkflowTests.confirmed_sop
    envelope = sop_fixture.ManualSopWorkflowTests.envelope
    act = sop_fixture.ManualSopWorkflowTests.act
    claim = sop_fixture.ManualSopWorkflowTests.claim
    begin = sop_fixture.ManualSopWorkflowTests.begin
    category_receipts = sop_fixture.ManualSopWorkflowTests.category_receipts
    finish = sop_fixture.ManualSopWorkflowTests.finish
    evidence_identity = sop_fixture.ManualSopWorkflowTests.evidence_identity
    phase = sop_fixture.ManualSopWorkflowTests.phase
    opening = sop_fixture.ManualSopWorkflowTests.opening
    mapping = sop_fixture.ManualSopWorkflowTests.mapping
    attach = sop_fixture.ManualSopWorkflowTests.attach
    qc = sop_fixture.ManualSopWorkflowTests.qc

    def fixture_setup(self):
        import cutrun_manual_recipe_sources as sources
        import cutrun_manual_recipe_workflow as runtime
        import cutrun_recipe_bindings as bindings
        self.sources, self.runtime, self.bindings = sources, runtime, bindings
        self.temp = tempfile.TemporaryDirectory(prefix='manual-recipe-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture_root = (self.directory / 'repository').resolve()
        self.profile = json.loads(base_sources.SOURCE.read_text())
        self.sop_profile = json.loads((ROOT / 'model/cutrun-manual-sop.profile.json').read_text())
        self.recipe_profile = json.loads((ROOT / 'model/cutrun-manual-recipe.profile.json').read_text())
        self.protocol = json.loads((ROOT / 'model/cutrun-manual-recipe.protocol.json').read_text())
        self.original = self.directory / 'manufacturer.pdf'
        self.original.write_bytes(b'%PDF-1.7\nExplicit recipe fixture original; no laboratory evidence.\n')
        old_hash = self.profile['sources']['manufacturer']['source_sha256']
        self.profile['sources']['manufacturer']['source_sha256'] = digest(self.original.read_bytes())
        sop_name = self.profile['sources']['sop']['source']
        for name in {*base_sources.RUNTIME, *sop_sources.RUNTIME, *sources.RUNTIME, sop_name}:
            destination = self.fixture_root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        content = (self.fixture_root / sop_name).read_bytes().replace(
            old_hash.encode(), self.profile['sources']['manufacturer']['source_sha256'].encode())
        (self.fixture_root / sop_name).write_bytes(content)
        self.profile['sources']['sop']['source_sha256'] = digest(content)
        # The recipe explicitly pins the same manufacturer original as the SOP;
        # a fixture original therefore needs a correspondingly pinned fixture
        # recipe, rather than weakening either production source verifier.
        protocol_name = self.fixture_root / 'model/cutrun-manual-recipe.protocol.json'
        protocol_bytes = protocol_name.read_bytes().replace(
            old_hash.encode(), self.profile['sources']['manufacturer']['source_sha256'].encode())
        protocol_name.write_bytes(protocol_bytes)
        self.protocol = json.loads(protocol_bytes)
        for module in (base_sources, base_runtime, sop_sources, sop_runtime, sources, runtime, bindings):
            if hasattr(module, 'ROOT'):
                item = patch.object(module, 'ROOT', self.fixture_root)
                item.start(); self.addCleanup(item.stop)
        self.evidence = self.directory / 'prospective-fixture-evidence.txt'
        self.evidence.write_bytes(b'Test-only prospective recipe decisions, stock lots and qualifications.\n')
        self.evidence_files = {'decision_evidence': self.evidence}
        self.journal = Journal(self.directory / 'recipe.sqlite3')
        self.addCleanup(self.journal.close)
        self.journal.state = self.journal.get_current
        self.clock = FakeClock()
        self.time_basis = self.clock.record['clock_id']
        self.serial = 0
        self.stage_ids, self.stage_inputs, self.stage_actions, self.phase_records = {}, {}, {}, {}
        self.materials, self.vessels, self.reactions = sop_fixture.ManualSopWorkflowTests.declarations(self)
        self.next_vessel = len(self.vessels)
        self.output_vessels = [self.vessel('Test.Recipe.OutputTube.%02d' % index) for index in range(1, 41)]
        self.output_vessel_index = 0
        self.operation_serial = 0

    def vessel(self, identity):
        if identity not in {item['id'] for item in self.vessels}:
            self.next_vessel += 1
            self.vessels.append({'id': identity, 'location': {'kind': 'rack',
                'rack_id': 'Test.RecipeRack', 'place_id': 'P%03d' % self.next_vessel}})
        return identity

    def reagent(self, identity, amount=100000):
        if identity not in {item['id'] for item in self.materials}:
            self.materials.append({'id': identity, 'kind': 'reagent',
                'vessel_id': self.vessel(identity + '.Tube'),
                'quantity': {'value': amount, 'unit': 'uL'}, 'origin_id': 'Test.Issued.' + identity})
        return identity

    def create(self, *, recipe=None, journal=None, run_id='Test.Manual.Recipe'):
        return self.runtime.CutRunManualRecipeWorkflow.create(journal or self.journal,
            {'base_profile': self.confirmed_base(), 'sop_profile': self.confirmed_sop(),
             'recipe_profile': self.confirmed_recipe() if recipe is None else recipe},
            materials=self.materials, vessels=self.vessels, reactions=self.reactions,
            actors=[self.ACTOR, self.OBSERVER], run_id=run_id, clock=self.clock,
            original_pdf=self.original, evidence_files=self.evidence_files)

    def confirmed_recipe(self):
        profile = copy.deepcopy(self.recipe_profile)
        needed = set()
        for stage, steps in self.protocol['stage_steps'].items():
            for step in steps:
                if (stage == 'S02' or step['id'] in {'S03.bead_activation_wash', 'S03.bead_resuspension'}
                        or step['id'].startswith('S03.permeabilization_')):
                    continue
                refs = step['reagent_role'].values() if isinstance(step['reagent_role'], dict) else [step['reagent_role']]
                needed.update(ref for ref in refs if ref is not None)
                if step['target_role'] in profile['roles']:needed.add(step['target_role'])
        for role in needed:
            binding = profile['roles'][role]
            if role in {'h3k4me3.digestion_mix', 'igg.digestion_mix',
                        'h3k4me3.stop_mix', 'igg.stop_mix'}:
                branch, suffix = role.split('.')
                key = 'activation_material_id' if suffix == 'digestion_mix' else 'stop_material_id'
                reaction = self.REFERENCE if branch == 'h3k4me3' else self.IGG
                identity = self.reactions[reaction][key]
            else:
                identity = self.reagent('Test.Reagent.' + role)
            material = next(item for item in self.materials if item['id'] == identity)
            binding.update(mode='issued', material_id=identity, vessel_id=material['vessel_id'],
                lot_ref='Test.Lot.' + role, preparation_ref='decision_evidence', evidence_ref='decision_evidence')
        profile['incoming_preparation'].update(mode='external', evidence_ref='decision_evidence')
        profile['cell_wash_branch'].update(value='standard', evidence_ref='decision_evidence')
        if 'permeabilization' in profile:
            profile['permeabilization'].update(mode='external', evidence_ref='decision_evidence')
        for stage, steps in self.protocol['stage_steps'].items():
            for step in steps:
                binding = profile['steps'][step['id']]
                repeats = step['source_facts'].get('cycles', step['source_facts'].get('standard_cycles', 1))
                dose = 150 if step['kind'] in {'activation', 'stop'} else 10 if step['kind'] in {'load', 'elute'} else 5
                binding.update(enabled=True, repeat_count=None if step['kind'] == 'load' else repeats,
                    quantity={'value': None if step['kind'] in {'remove', 'dry'} else dose, 'unit': 'uL'},
                    evidence_ref='decision_evidence')
                if (stage == 'S02' or step['id'] in {'S03.bead_activation_wash', 'S03.bead_resuspension'}
                        or step['id'].startswith('S03.permeabilization_')):
                    binding['enabled'] = False
                    binding['repeat_count'] = None
                    binding['quantity']['value'] = None
        for role, binding in profile['consumables'].items():
            binding.update(column_id=self.vessel('Test.Column.' + role),
                collection_vessel_id=self.vessel('Test.Column.Collection.' + role),
                elution_vessel_id='Test.' + role + '.ProductTube',
                preparation_ref='decision_evidence', evidence_ref='decision_evidence')
        return profile

    def prepared(self, profile, role, *, output=1000):
        binding = profile['roles'][role]
        old = binding['material_id']
        identity = 'Test.Prepared.' + role
        binding.update(mode='prepared', material_id=identity,
            vessel_id=self.vessel(identity + '.Tube'), lot_ref=None,
            preparation_ref='decision_evidence', evidence_ref='decision_evidence',
            components={name: {'value': 10, 'unit': 'uL'} for name in binding['components']},
            output_quantity={'value': output, 'unit': 'uL'})
        # A future mixture is not already present as an issued initial material.
        self.materials[:] = [item for item in self.materials if item['id'] != old]
        if role == 'working.activated_beads':
            for step_id, count in [('S03.bead_activation_wash', 2), ('S03.bead_resuspension', 1)]:
                profile['steps'][step_id].update(enabled=True, repeat_count=count,
                    quantity={'value': 5, 'unit': 'uL'}, evidence_ref='decision_evidence')
            profile['steps']['S03.bead_resuspension']['quantity']['value'] = 10
        for component in binding['components']:
            child = profile['roles'][component]
            if child['mode'] is None:
                material_id = self.reagent('Test.Reagent.' + component)
                material = next(item for item in self.materials if item['id'] == material_id)
                child.update(mode='issued', material_id=material_id, vessel_id=material['vessel_id'],
                    lot_ref='Test.Lot.' + component, preparation_ref='decision_evidence', evidence_ref='decision_evidence')
        if role in {'h3k4me3.digestion_mix', 'igg.digestion_mix', 'h3k4me3.stop_mix', 'igg.stop_mix'}:
            branch, suffix = role.split('.')
            reaction = self.REFERENCE if branch == 'h3k4me3' else self.IGG
            key = 'activation_material_id' if suffix == 'digestion_mix' else 'stop_material_id'
            self.reactions[reaction][key] = identity
        return profile

    def setup_flow(self, *, profile=None):
        self.fixture_setup()
        self.bound_recipe = self.confirmed_recipe() if profile is None else profile
        self.flow = self.create(recipe=self.bound_recipe)
        self.claim()

    def prepare_mix(self, role, stage_run_id, *, actual=None, intent=None):
        intent = intent or 'Test.Preparation.' + role
        self.act('begin_prepare_mix', stage_run_id=stage_run_id, recipe_role=role, intent_id=intent)
        request = self.flow.state['bookings'][intent]['request']
        inputs = [{'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
                  for item in request['inputs']]
        output = self.bound_recipe['roles'][role]['output_quantity']
        outputs = [{'material_id': item['material_id'], 'quantity': copy.deepcopy(output)}
                   for item in request['outputs']]
        self.act('confirm_prepare_mix', intent_id=intent,
            actual_inputs=inputs if actual is None else actual, actual_outputs=outputs,
            reason='Explicit test-only working mixture observations')
        self.stage_actions[stage_run_id].append(intent)
        return intent

    def spare_vessel(self):
        result = self.output_vessels[self.output_vessel_index]
        self.output_vessel_index += 1
        return result

    def stage_node(self, stage_id, step_id):
        return next(item for item in self.protocol['stage_steps'][stage_id] if item['id'] == step_id)

    def perform(self, stage_id, reaction_id, *, next_operation=None, observations=None,
                retained_ul=22, outputs=None, actual_inputs=None, actual_outputs=None):
        stage_run_id = self.stage_ids[stage_id, reaction_id]
        following = self.flow.recipe_next(stage_run_id) if next_operation is None else next_operation
        self.operation_serial += 1
        intent = 'Test.Recipe.Operation.%03d' % self.operation_serial
        operation, step_id = following['operation'], following['step_id']
        node = self.stage_node(stage_id, step_id)
        state = self.flow.state
        retained_id = None
        output_quantities = {}
        declarations = []
        if operation in {'add', 'load', 'remove', 'split'}:
            material_id = following['target_material_id']
            target = state['inventory']['materials'][material_id]
            target_vessel = following['target_vessel_id']
            retained_id = intent + '.Retained'
            retained_kind, retained_role, retained_vessel = 'intermediate', 'retained_fraction', target_vessel
            current = ledger.remaining(state, material_id)
            if operation == 'split':
                observed = {'value': None, 'unit': current['unit']}
            elif operation == 'load':
                role = self.reactions[reaction_id]['role']
                retained_vessel = self.bound_recipe['consumables'][role]['column_id']
                observed = {'value': None, 'unit': 'uL'}
            elif operation == 'add':
                dose = self.bound_recipe['steps'][step_id]['quantity']['value']
                observed = ({'value': None, 'unit': 'cells'} if current['unit'] == 'cells' else
                    {'value': dose if current['unit'] == 'ng' else
                              None if current['value'] is None else current['value'] + dose,
                     'unit': 'uL'})
            elif step_id == 'S10.column_elution':
                role = self.reactions[reaction_id]['role']
                retained_kind, retained_role = 'product', 'purified_eluate'
                retained_vessel = self.bound_recipe['consumables'][role]['elution_vessel_id']
                observed = {'value': self.bound_recipe['steps'][step_id]['quantity']['value'], 'unit': 'uL'}
            elif step_id in {'S08.released_fraction', 'S09.clarified_fraction'}:
                retained_vessel = self.spare_vessel()
                observed = {'value': retained_ul, 'unit': 'uL'}
            elif step_id in {'S10.column_load', 'S10.column_wash'}:
                observed = {'value': None, 'unit': 'ng'}
            else:
                observed = {'value': 20 if node['target_role'] == 'stock.beads' else None,
                            'unit': current['unit']}
            if operation == 'remove':
                retained_role = node['source_facts'].get('retained', retained_role)
            declarations.append({'material_id': retained_id, 'kind': retained_kind,
                'vessel_id': retained_vessel, 'role': retained_role})
            output_quantities[retained_id] = observed
            if operation == 'split':
                role = self.reactions[reaction_id]['role']
                assay_id = intent + '.Assay'
                declarations.append({'material_id': assay_id, 'kind': 'intermediate',
                    'vessel_id': self.bound_recipe['consumables'][role]['permeabilization_vessel_id'],
                    'role': 'permeabilization_aliquot'})
                output_quantities[assay_id] = copy.deepcopy(self.bound_recipe['steps'][step_id]['quantity'])
            if operation == 'remove':
                removed_id = intent + '.Removed'
                removed_vessel = (target_vessel if step_id in {'S08.released_fraction',
                    'S09.clarified_fraction', 'S10.column_elution'} else self.spare_vessel())
                declarations.append({'material_id': removed_id, 'kind': 'byproduct',
                    'vessel_id': removed_vessel, 'role': node['source_facts'].get('removed', 'removed_fraction')})
                output_quantities[removed_id] = {'value': None,
                    'unit': 'ng' if step_id == 'S10.column_elution' else
                            current['unit'] if step_id in {'S08.released_fraction', 'S09.clarified_fraction'} else 'uL'}
        if outputs is not None:
            declarations = outputs
        envelope = None
        if operation == 'observe':
            raw = ('Explicit fixture-only permeability read for ' + stage_run_id).encode()
            self.act('attach_sop_evidence', artifact=raw, file_name='permeability-test-record.txt', origin='test_fixture')
            envelope = self.envelope();envelope['artifact_sha256'] = digest(raw)
        self.act('begin_recipe_operation', envelope=envelope, stage_run_id=stage_run_id, step_id=step_id,
            iteration=following['iteration'], operation=operation, intent_id=intent,
            outputs=declarations, retained_material_id=retained_id)
        state = self.flow.state
        if intent in state['bookings']:
            request = state['bookings'][intent]['request']
            observed_inputs = [{'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
                               for item in request['inputs']]
            preparation = state['recipe']['operations'][intent].get('kind') == 'preparation'
            if preparation:
                recipe_role = state['recipe']['operations'][intent]['recipe_role']
                observed_outputs = [{'material_id': item['material_id'], 'quantity':
                    copy.deepcopy(self.bound_recipe['roles'][recipe_role]['output_quantity'])}
                    for item in request['outputs']]
            else:
                observed_outputs = [{'material_id': item['material_id'], 'quantity': output_quantities[item['material_id']]}
                                    for item in request['outputs']]
        else:
            observed_inputs, observed_outputs = [], []
            preparation = False
        details = {'performed': True}
        if operation in {'mix', 'separate', 'dry', 'observe'}:
            details[{'mix': 'mixed', 'separate': 'separated', 'dry': 'dried', 'observe': 'observed'}[operation]] = True
        if observations is not None:
            details = observations
        kwargs = {'intent_id': intent,
            'actual_inputs': observed_inputs if actual_inputs is None else actual_inputs,
            'actual_outputs': observed_outputs if actual_outputs is None else actual_outputs,
            'reason': 'Explicit test-only recipe operation observation'}
        if not preparation:kwargs['observations'] = details
        self.act('confirm_prepare_mix' if preparation else 'confirm_recipe_operation', **kwargs)
        if intent in self.flow.state['bookings']:
            self.stage_actions[stage_run_id].append(intent)
        return intent

    def steps(self, stage_id, reaction_id, *, retained_ul=22):
        identity = self.stage_ids[stage_id, reaction_id]
        while (following := self.flow.recipe_next(identity)) is not None:
            if following['operation'] in {'activation', 'stop'}:
                raise AssertionError('Dedicated activation/stop must be recorded independently')
            self.perform(stage_id, reaction_id, next_operation=following, retained_ul=retained_ul)

    def ordinary(self, stage_id, reaction_id):
        self.begin(stage_id, reaction_id)
        self.steps(stage_id, reaction_id)
        for phase_id in self.flow.state['definition']['sop_protocol']['stages'][stage_id]['phases']:
            self.phase(stage_id, reaction_id, phase_id)
        self.finish(stage_id, reaction_id)

    def start(self, *, prepared_roles=(), recipe=None):
        self.bound_recipe = self.confirmed_recipe() if recipe is None else recipe
        for role in prepared_roles:
            self.prepared(self.bound_recipe, role)
        self.flow = self.create(recipe=self.bound_recipe)
        self.claim()
        return self.flow

    def to_stage(self, stage_id, reaction_id=None):
        reaction_id = self.REFERENCE if reaction_id is None else reaction_id
        if ('S01', None) not in self.stage_ids:
            self.opening()
        sequence = ('S02', 'S09', 'S10') if reaction_id == self.INPUT else (
            'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08', 'S10')
        for previous in sequence[:sequence.index(stage_id)]:
            if (previous, reaction_id) not in self.stage_ids:
                self.ordinary(previous, reaction_id)
        return self.begin(stage_id, reaction_id)

    def activate(self, reaction_id=None):
        reaction_id = self.REFERENCE if reaction_id is None else reaction_id
        identity = self.to_stage('S07', reaction_id)
        intent = 'Test.Activation.' + reaction_id
        self.act('begin_activation', intent_id=intent, reaction_id=reaction_id,
            stop_access=True, mixing_available=True)
        self.act('confirm_dose', intent_id=intent, actual_volume_ul=150, mixed=True,
            reason='Explicit fixture-only activation observation')
        self.stage_actions[identity].append(intent)
        return intent

    def stop(self, reaction_id=None):
        reaction_id = self.REFERENCE if reaction_id is None else reaction_id
        intent = 'Test.Stop.' + reaction_id
        self.act('begin_stop', intent_id=intent, reaction_id=reaction_id,
            stop_access=True, mixing_available=True)
        self.act('confirm_dose', intent_id=intent, actual_volume_ul=150, mixed=True,
            reason='Explicit fixture-only stop dose and mixing observation')
        return intent

    def purify(self, reaction_id):
        identity = self.begin('S10', reaction_id)
        self.steps('S10', reaction_id)
        self.phase('S10', reaction_id, 'S10.purification')
        self.finish('S10', reaction_id)
        return self.flow.state['manual']['reactions'][reaction_id]['current_material_id']

    def branch(self, reaction_id):
        self.activate(reaction_id)
        self.phase('S07', reaction_id, 'S07.digestion')
        stopping = self.stop(reaction_id)
        self.finish('S07', reaction_id)
        identity = self.begin('S08', reaction_id)
        self.stage_actions[identity].append(stopping)
        self.phase('S08', reaction_id, 'S08.release')
        self.phase('S08', reaction_id, 'S08.separation')
        self.steps('S08', reaction_id)
        self.finish('S08', reaction_id)
        return self.purify(reaction_id)


class ManualRecipeWorkflowTests(RecipeFixture, unittest.TestCase):
    def setUp(self):
        self.fixture_setup()

    def test_archive_keeps_unknown_recipe_parameters_open_and_cannot_start_nominal_washing(self):
        self.start(recipe=self.recipe_profile)
        state = self.flow.state
        self.assertEqual(state['definition']['profile']['type'], 'cutrun_manual_recipe/1')
        self.assertTrue(all(item['quantity']['value'] is None and item['repeat_count'] is None
                            for item in state['definition']['recipe_profile']['steps'].values()))
        self.act('record_observation', stage_id='S03', reaction_id=self.REFERENCE,
            status='unknown', details={'reason': 'Unbound wash quantities remain unknown'})
        with self.assertRaises(TaskError):
            self.begin('S03', self.REFERENCE)
        self.assertFalse(self.flow.report()['reference_success'])

    def test_generic_material_actions_and_free_notes_cannot_replace_required_washes(self):
        self.start()
        identity = self.to_stage('S03')
        self.act('record_observation', stage_id='S03', reaction_id=self.REFERENCE,
            status='observed', details={'claim': 'A note is not a confirmed wash'})
        with self.assertRaises(TaskError):
            self.finish('S03', self.REFERENCE)
        material = self.flow.state['manual']['reactions'][self.REFERENCE]['current_material_id']
        with self.assertRaises(TaskError):
            self.act('begin_material_action', intent_id='Test.Generic.Bypass', reaction_id=self.REFERENCE,
                stage_id='S03', kind='withdrawal', inputs=[{'material_id': material,
                    'quantity': {'value': 1, 'unit': 'cells'}, 'consume_all': False}], outputs=[],
                purpose='A generic receipt cannot stand in for the bound recipe')
        self.assertEqual(self.flow.recipe_next(identity)['step_id'], 'S03.bead_addition')

    def test_cell_washing_performed_here_requires_both_cycles_and_does_not_invent_recovered_cell_counts(self):
        self.bound_recipe = self.confirmed_recipe()
        self.bound_recipe['incoming_preparation'].update(mode='perform', evidence_ref='decision_evidence')
        role = self.bound_recipe['roles']['working.cell_wash']
        identity = self.reagent('Test.Reagent.working.cell_wash')
        material = next(item for item in self.materials if item['id'] == identity)
        role.update(mode='issued', material_id=identity, vessel_id=material['vessel_id'],
            lot_ref='Test.Lot.CellWash', preparation_ref='decision_evidence', evidence_ref='decision_evidence')
        for step_id, count, quantity in [('S02.initial_separation', 1, None), ('S02.cell_wash', 2, 5),
                                         ('S02.cell_resuspension', 1, 5)]:
            self.bound_recipe['steps'][step_id].update(enabled=True, repeat_count=count,
                quantity={'value': quantity, 'unit': 'uL'}, evidence_ref='decision_evidence')
        self.flow = self.create(recipe=self.bound_recipe);self.claim();self.opening()
        stage = self.begin('S02', self.REFERENCE)
        self.perform('S02', self.REFERENCE);self.perform('S02', self.REFERENCE)
        for unused in range(4):self.perform('S02', self.REFERENCE)
        next_action = self.flow.recipe_next(stage)
        self.assertEqual((next_action['step_id'], next_action['iteration']), ('S02.cell_wash', 2))
        with self.assertRaises(TaskError):self.finish('S02', self.REFERENCE)
        self.steps('S02', self.REFERENCE);self.finish('S02', self.REFERENCE)
        self.assertEqual(ledger.remaining(self.flow.state, identity)['value'], 100000 - 15)
        retained = self.flow.state['manual']['reactions'][self.REFERENCE]['current_material_id']
        self.assertEqual(ledger.remaining(self.flow.state, retained)['unit'], 'cells')
        self.assertIsNone(ledger.remaining(self.flow.state, retained)['value'])

    def test_permeability_assay_uses_its_own_sample_aliquot_and_charges_each_reagent_once(self):
        self.bound_recipe = self.confirmed_recipe()
        self.bound_recipe['permeabilization'].update(mode='perform', evidence_ref='decision_evidence')
        reagent_roles = ('working.permeabilization_wash', 'stock.digitonin', 'stock.trypan_blue')
        for role_id in reagent_roles:
            identity = self.reagent('Test.Reagent.' + role_id)
            material = next(item for item in self.materials if item['id'] == identity)
            self.bound_recipe['roles'][role_id].update(mode='issued', material_id=identity,
                vessel_id=material['vessel_id'], lot_ref='Test.Lot.' + role_id,
                preparation_ref='decision_evidence', evidence_ref='decision_evidence')
        for steps in self.protocol['stage_steps'].values():
            for step in steps:
                if step['id'].startswith('S03.permeabilization_'):
                    self.bound_recipe['steps'][step['id']].update(enabled=True, repeat_count=1,
                        quantity={'value': None if step['kind'] == 'observe' else 5, 'unit': 'uL'},
                        evidence_ref='decision_evidence')
        for role in ('h3k4me3', 'igg'):
            self.bound_recipe['consumables'][role]['permeabilization_vessel_id'] = self.vessel('Test.Assay.' + role)
        self.flow = self.create(recipe=self.bound_recipe);self.claim()
        stage = self.to_stage('S03')
        original = self.flow.state['manual']['reactions'][self.REFERENCE]['current_material_id']
        before = {role: ledger.remaining(self.flow.state, self.bound_recipe['roles'][role]['material_id'])['value']
                  for role in reagent_roles}
        splitting = self.perform('S03', self.REFERENCE)
        main = self.flow.state['manual']['reactions'][self.REFERENCE]['current_material_id']
        assay = self.flow.state['recipe']['assay_materials'][self.REFERENCE]
        self.assertNotEqual(main, assay)
        self.assertIn(original, self.flow.state['inventory']['materials'][main]['parents'])
        self.assertEqual(ledger.remaining(self.flow.state, assay)['value'], 5)
        while self.flow.recipe_next(stage)['step_id'].startswith('S03.permeabilization_'):
            self.perform('S03', self.REFERENCE)
            self.assertEqual(self.flow.state['manual']['reactions'][self.REFERENCE]['current_material_id'], main)
        for role in reagent_roles:
            self.assertEqual(ledger.remaining(self.flow.state,
                self.bound_recipe['roles'][role]['material_id'])['value'], before[role] - 5)
        self.assertEqual(self.flow.state['bookings'][splitting]['outcome'], 'performed')
        self.assertIsNone(ledger.remaining(self.flow.state, main)['value'])
        final_assay = self.flow.state['recipe']['assay_materials'][self.REFERENCE]
        self.assertEqual(ledger.remaining(self.flow.state, final_assay)['value'], 20)
        self.assertIsNone(self.flow.state['inventory']['materials'][final_assay]['disposition'])
        self.assertFalse(self.flow.report()['reference_success'])

    def test_in_run_bead_preparation_cannot_bypass_activation_washes_or_charge_resuspension_twice(self):
        self.bound_recipe = self.confirmed_recipe()
        self.prepared(self.bound_recipe, 'working.activated_beads', output=20)
        self.flow = self.create(recipe=self.bound_recipe);self.claim()
        stage = self.to_stage('S03')
        with self.assertRaises(TaskError):
            self.act('begin_prepare_mix', stage_run_id=stage,
                recipe_role='working.activated_beads', intent_id='Test.Bypass.Bead.Washes')
        buffer = self.bound_recipe['roles']['stock.bead_activation_buffer']['material_id']
        before = ledger.remaining(self.flow.state, buffer)['value']
        for cycle in (1, 2):
            for operation in ('add', 'mix', 'separate', 'remove'):
                next_action = self.flow.recipe_next(stage)
                self.assertEqual((next_action['step_id'], next_action['iteration'], next_action['operation']),
                    ('S03.bead_activation_wash', cycle, operation))
                self.perform('S03', self.REFERENCE)
        self.assertEqual(ledger.remaining(self.flow.state, buffer)['value'], before - 10)
        preparation = self.perform('S03', self.REFERENCE)
        self.perform('S03', self.REFERENCE)  # Final mixing adds no second quantity debit.
        self.assertEqual(ledger.remaining(self.flow.state, buffer)['value'], before - 20)
        role = self.bound_recipe['roles']['working.activated_beads']
        self.assertEqual(self.flow.state['bookings'][preparation]['request']['outputs'][0]['material_id'], role['material_id'])
        self.assertTrue(self.bindings.reagent_ready(self.flow.state, 'working.activated_beads'))
        self.assertEqual(self.flow.recipe_next(stage)['step_id'], 'S03.bead_addition')

    def test_acknowledged_wrong_bead_wash_dose_cannot_qualify_a_later_working_mixture(self):
        self.bound_recipe = self.confirmed_recipe()
        self.prepared(self.bound_recipe, 'working.activated_beads', output=20)
        self.flow = self.create(recipe=self.bound_recipe);self.claim()
        stage = self.to_stage('S03')
        bead_id = self.bound_recipe['roles']['stock.beads']['material_id']
        buffer_id = self.bound_recipe['roles']['stock.bead_activation_buffer']['material_id']
        bead_amount = ledger.remaining(self.flow.state, bead_id)
        dose = self.perform('S03', self.REFERENCE, actual_inputs=[
            {'material_id': bead_id, 'quantity': {'value': bead_amount['value'], 'unit': bead_amount['unit']}},
            {'material_id': buffer_id, 'quantity': {'value': 6, 'unit': 'uL'}}])
        self.assertTrue(self.flow.state['recovery_required'])
        self.act('resolve_deviation', hold_code='recipe_dose_deviation', evidence_ref='decision_evidence',
            reason='Explicit fixture-only assessment preserves the observed wrong dose')
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
            reason='Explicit fixture inventory does not turn the wrong dose into a planned wash')
        self.assertFalse(self.bindings.reagent_ready(self.flow.state, 'stock.beads'))
        while self.flow.recipe_next(stage)['step_id'] == 'S03.bead_activation_wash':
            self.perform('S03', self.REFERENCE)
        self.assertEqual(self.flow.recipe_next(stage)['step_id'], 'S03.bead_resuspension')
        with self.assertRaises(TaskError):
            self.perform('S03', self.REFERENCE)
        self.assertEqual(self.flow.state['bookings'][dose]['actual_inputs'][1]['quantity']['value'], 6)
        self.assertNotIn(self.bound_recipe['roles']['working.activated_beads']['material_id'],
                         self.flow.state['inventory']['materials'])

    def test_wash_requires_addition_mixing_separation_and_each_bound_cycle(self):
        self.start()
        identity = self.to_stage('S05')
        # Remove antibody medium before the wash, retaining the actual sample.
        self.perform('S05', self.REFERENCE)
        self.perform('S05', self.REFERENCE)
        following = self.flow.recipe_next(identity)
        self.assertEqual((following['step_id'], following['operation']), ('S05.digitonin_wash', 'add'))
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.act('begin_recipe_operation', stage_run_id=identity, step_id='S05.digitonin_wash',
                iteration=1, operation='remove', intent_id='Test.Wash.Skip.Addition', outputs=[])
        self.assertEqual(self.flow.state, before)
        for operation in ('add', 'mix', 'separate', 'remove'):
            self.assertEqual(self.flow.recipe_next(identity)['operation'], operation)
            self.perform('S05', self.REFERENCE)
        self.assertEqual(self.flow.recipe_next(identity)['step_id'], 'S05.enzyme_addition')
        with self.assertRaises(TaskError):self.finish('S05', self.REFERENCE)

    def test_reagent_is_charged_at_addition_once_and_removed_liquid_has_its_own_lineage(self):
        self.start()
        identity = self.to_stage('S03')
        role = self.bound_recipe['roles']['working.activated_beads']['material_id']
        before = ledger.remaining(self.flow.state, role)['value']
        addition = self.perform('S03', self.REFERENCE)
        after = ledger.remaining(self.flow.state, role)['value']
        self.assertEqual(before - after, 5)
        self.perform('S03', self.REFERENCE)  # Explicit mixing, no quantity effect.
        self.assertEqual(ledger.remaining(self.flow.state, role)['value'], after)
        self.perform('S03', self.REFERENCE)  # Separate binding liquid.
        removed = self.perform('S03', self.REFERENCE)
        self.assertEqual(ledger.remaining(self.flow.state, role)['value'], after)
        outputs = self.flow.state['bookings'][removed]['request']['outputs']
        self.assertEqual({item['kind'] for item in outputs}, {'intermediate', 'byproduct'})
        self.assertEqual(len({item['vessel_id'] for item in outputs}), 2)
        source = self.flow.state['bookings'][addition]['request']['outputs'][0]['material_id']
        for output in outputs:
            material = self.flow.state['inventory']['materials'][output['material_id']]
            self.assertIn(source, material['parents'])
            self.assertIsNone(material['disposition'])
        current = self.flow.state['manual']['reactions'][self.REFERENCE]['current_material_id']
        self.assertEqual(ledger.remaining(self.flow.state, current),
                         {'value': None, 'unit': 'cells', 'knowledge': 'initial_unknown'})

    def test_issued_prepared_buffers_do_not_consume_their_unexecuted_stock_recipe(self):
        self.start()
        self.to_stage('S03')
        stocks = [value['material_id'] for name, value in self.bound_recipe['roles'].items()
                  if name.startswith('stock.') and value['material_id'] is not None]
        before = {identity: ledger.remaining(self.flow.state, identity) for identity in stocks}
        self.steps('S03', self.REFERENCE)
        self.assertEqual(before, {identity: ledger.remaining(self.flow.state, identity) for identity in stocks})

    def test_working_mix_preparation_books_stocks_once_then_doses_the_mixture(self):
        self.start(prepared_roles=('working.antibody_buffer',))
        identity = self.to_stage('S03')
        role = self.bound_recipe['roles']['working.antibody_buffer']
        stocks = {name: self.bound_recipe['roles'][name]['material_id'] for name in role['components']}
        before = {name: ledger.remaining(self.flow.state, material)['value'] for name, material in stocks.items()}
        self.assertNotIn(role['material_id'], self.flow.state['inventory']['materials'])
        preparation = self.prepare_mix('working.antibody_buffer', identity)
        for name, material in stocks.items():
            self.assertEqual(ledger.remaining(self.flow.state, material)['value'], before[name] - 10)
        self.steps('S03', self.REFERENCE)
        self.assertEqual(ledger.remaining(self.flow.state, role['material_id'])['value'], 995)
        for name, material in stocks.items():
            self.assertEqual(ledger.remaining(self.flow.state, material)['value'], before[name] - 10)
        self.assertEqual(self.flow.state['inventory']['materials'][role['material_id']]['kind'], 'intermediate')
        self.assertTrue(self.bindings.reagent_ready(self.flow.state, 'working.antibody_buffer'))
        self.assertEqual(self.flow.state['bookings'][preparation]['outcome'], 'performed')

    def test_addition_cannot_move_the_target_into_an_unrelated_vessel(self):
        self.start()
        stage = self.to_stage('S03')
        following = self.flow.recipe_next(stage)
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.act('begin_recipe_operation', stage_run_id=stage, step_id=following['step_id'],
                iteration=following['iteration'], operation='add', intent_id='Test.Wrong.Target',
                outputs=[{'material_id': 'Test.Wrong.Target.Output', 'kind': 'intermediate',
                    'vessel_id': self.spare_vessel(), 'role': 'wrong_target'}],
                retained_material_id='Test.Wrong.Target.Output')
        self.assertEqual(self.flow.state, before)

    def test_reaction_activation_and_stop_must_match_the_final_branch_recipe_before_any_journal_effect(self):
        materials, vessels, reactions = (copy.deepcopy(self.materials), copy.deepcopy(self.vessels),
                                        copy.deepcopy(self.reactions))
        next_vessel = self.next_vessel
        cases = [('activation_material_id', 'digestion_mix', 'issued'),
                 ('stop_material_id', 'stop_mix', 'issued'),
                 ('activation_material_id', 'digestion_mix', 'prepared_swap'),
                 ('stop_material_id', 'stop_mix', 'prepared_swap')]
        for index, (field, suffix, variant) in enumerate(cases):
            with self.subTest(field=field, variant=variant):
                self.materials, self.vessels, self.reactions = (copy.deepcopy(materials),
                    copy.deepcopy(vessels), copy.deepcopy(reactions))
                self.next_vessel = next_vessel
                profile = self.confirmed_recipe()
                if variant == 'issued':
                    self.reactions[self.REFERENCE][field] = profile['roles']['stock.h3k4me3_antibody']['material_id']
                else:
                    self.prepared(profile, 'h3k4me3.' + suffix)
                    self.prepared(profile, 'igg.' + suffix)
                    self.reactions[self.REFERENCE][field], self.reactions[self.IGG][field] = (
                        self.reactions[self.IGG][field], self.reactions[self.REFERENCE][field])
                with Journal(self.directory / ('wrong-role-%d.sqlite3' % index)) as journal:
                    with self.assertRaisesRegex(TaskError, 'pinned recipe role'):
                        self.create(recipe=profile, journal=journal, run_id='Test.Wrong.Recipe.%d' % index)
                    for table in ('runs', 'events', 'resources', 'artifacts'):
                        self.assertEqual(journal.connection.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
                    extension = journal.connection.execute(
                        "SELECT name FROM sqlite_master WHERE name='material_allocations'").fetchone()
                    self.assertIsNone(extension)

    def test_overdraw_is_archived_without_a_debit_and_requires_explicit_recipe_resolution(self):
        self.start()
        stage = self.to_stage('S03')
        following = self.flow.recipe_next(stage)
        target = following['target_material_id']
        target_quantity = ledger.remaining(self.flow.state, target)
        reagent = self.bound_recipe['roles']['working.activated_beads']['material_id']
        balance = ledger.remaining(self.flow.state, reagent)['value']
        intent, output = 'Test.Overdraw', 'Test.Overdraw.Retained'
        self.act('begin_recipe_operation', stage_run_id=stage, step_id=following['step_id'],
            iteration=following['iteration'], operation='add', intent_id=intent,
            outputs=[{'material_id': output, 'kind': 'intermediate',
                'vessel_id': following['target_vessel_id'], 'role': 'retained_fraction'}],
            retained_material_id=output)
        bad_inputs = [{'material_id': target, 'quantity': {'value': target_quantity['value'], 'unit': target_quantity['unit']}},
                      {'material_id': reagent, 'quantity': {'value': balance + 1, 'unit': 'uL'}}]
        data = {'intent_id': intent, 'actual_inputs': bad_inputs,
                'actual_outputs': [{'material_id': output, 'quantity': {'value': None, 'unit': 'cells'}}],
                'observations': {'performed': True}, 'reason': 'Explicit fixture-only rejected overdraw'}
        raw = b'Unmodified original record of the mismatched dose\r\n\x00\xff'
        with self.assertRaises(ObservationError):
            self.act('confirm_recipe_operation', artifact=raw, **data)
        self.assertEqual(self.journal.artifact(digest(raw)), raw)
        self.assertEqual(self.flow.state['bookings'][intent]['outcome'], 'intent')
        self.assertNotIn(output, self.flow.state['inventory']['materials'])
        self.assertIsNone(ledger.remaining(self.flow.state, reagent)['value'])
        corrected = copy.deepcopy(data);corrected['actual_inputs'][1]['quantity']['value'] = 5
        with self.assertRaises(TaskError):
            self.act('confirm_recipe_operation', **corrected)
        corrected['outcome'] = 'performed'
        self.act('resolve_recipe_operation', **corrected)
        self.assertEqual(ledger.remaining(self.flow.state, reagent)['value'], balance - 5)

    def test_prepared_stop_remains_recordable_after_external_activation_with_unknown_recipe_mixing(self):
        self.start(prepared_roles=('h3k4me3.stop_mix',))
        preparation_stage = self.to_stage('S03')
        role = self.bound_recipe['roles']['h3k4me3.stop_mix']
        self.assertFalse(self.bindings.protected_ready(self.flow.state, self.reactions[self.REFERENCE]['vessel_id']))
        self.prepare_mix('h3k4me3.stop_mix', preparation_stage)
        self.assertTrue(self.bindings.protected_ready(self.flow.state, self.reactions[self.REFERENCE]['vessel_id']))
        self.perform('S03', self.REFERENCE)
        following = self.flow.recipe_next(preparation_stage)
        pending = 'Test.Unclear.Earlier.Mixing'
        self.act('begin_recipe_operation', stage_run_id=preparation_stage, step_id=following['step_id'],
            iteration=following['iteration'], operation='mix', intent_id=pending)
        self.act('mark_recipe_unknown', intent_id=pending,
            reason='Explicit fixture-only interruption before the physical mixing receipt')
        self.act('record_external_activation', reaction_id=self.REFERENCE,
            actual_volume_ul=150, mixed=True,
            reason='Explicit fixture-only retrospective observation; no nominal stage completion is inferred')
        self.stop()
        state = self.flow.state
        self.assertEqual(state['manual']['reactions'][self.REFERENCE]['status'], 'stopped')
        self.assertEqual(state['recipe']['operations'][pending]['outcome'], 'unknown')
        self.assertEqual(state['recipe']['pending_observation'], pending)
        self.assertEqual(ledger.remaining(state, role['material_id'])['value'], 850)
        self.assertTrue(state['recovery_required'])

    def test_unknown_preparation_consumption_is_not_zero_and_cannot_qualify_a_new_dose(self):
        self.start(prepared_roles=('working.antibody_buffer',))
        identity = self.to_stage('S03')
        role = self.bound_recipe['roles']['working.antibody_buffer']
        intent = 'Test.Unknown.Preparation'
        self.act('begin_prepare_mix', stage_run_id=identity, recipe_role='working.antibody_buffer', intent_id=intent)
        request = self.flow.state['bookings'][intent]['request']
        inputs = [{'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
                  for item in request['inputs']]
        inputs[0]['quantity']['value'] = None
        self.act('confirm_prepare_mix', intent_id=intent, actual_inputs=inputs,
            actual_outputs=[{'material_id': role['material_id'], 'quantity': {'value': 1000, 'unit': 'uL'}}],
            reason='Explicit fixture observation: one consumed component amount is unknown')
        balance = ledger.remaining(self.flow.state, inputs[0]['material_id'])
        self.assertIsNone(balance['value'])
        self.assertEqual(balance['knowledge'], 'confirmed_quantity_unknown')
        self.assertFalse(self.bindings.reagent_ready(self.flow.state, 'working.antibody_buffer'))
        self.assertTrue(self.flow.state['recovery_required'])

    def test_a_completed_mixing_receipt_cannot_be_rewritten_as_nonperformance(self):
        self.start()
        self.to_stage('S03')
        self.perform('S03', self.REFERENCE)
        mixing = self.perform('S03', self.REFERENCE)
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.act('resolve_recipe_operation', intent_id=mixing, outcome='not_performed',
                actual_inputs=[], actual_outputs=[], observations={},
                reason='Attempt to erase an already observed physical effect')
        self.assertEqual(self.flow.state, before)

    def test_later_working_mix_yield_evidence_restores_readiness_without_redebiting_stocks(self):
        self.start(prepared_roles=('working.antibody_buffer',))
        stage = self.to_stage('S03')
        role = self.bound_recipe['roles']['working.antibody_buffer']
        intent = 'Test.Unknown.Yield.Preparation'
        self.act('begin_prepare_mix', stage_run_id=stage, recipe_role='working.antibody_buffer', intent_id=intent)
        request = self.flow.state['bookings'][intent]['request']
        inputs = [{'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
                  for item in request['inputs']]
        self.act('confirm_prepare_mix', intent_id=intent, actual_inputs=inputs,
            actual_outputs=[{'material_id': role['material_id'], 'quantity': {'value': None, 'unit': 'uL'}}],
            reason='Explicit fixture-only observed preparation with an unmeasured output volume')
        after = {item['material_id']: ledger.remaining(self.flow.state, item['material_id']) for item in inputs}
        self.assertIsNone(ledger.remaining(self.flow.state, role['material_id'])['value'])
        self.assertFalse(self.bindings.reagent_ready(self.flow.state, 'working.antibody_buffer'))
        self.act('resolve_prepared_output', intent_id=intent, quantity={'value': 1000, 'unit': 'uL'},
            reason='Explicit fixture-only subsequent measurement of the original prepared mixture')
        resolution = self.flow.state['bookings'][intent]['output_quantity_resolution']
        self.assertIsNone(resolution['original_quantity']['value'])
        self.assertEqual(after, {item['material_id']: ledger.remaining(self.flow.state, item['material_id']) for item in inputs})
        self.assertTrue(self.bindings.reagent_ready(self.flow.state, 'working.antibody_buffer'))
        self.act('resolve_deviation', hold_code='recipe_preparation_uncertain',
            reason='Explicit fixture-only assessment of later volume evidence', evidence_ref='decision_evidence')
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
            reason='Explicit fixture-only complete inventory after the yield measurement')
        self.assertIsNone(self.flow.state['recovery_required'])
        self.steps('S03', self.REFERENCE)
        self.assertEqual(ledger.remaining(self.flow.state, role['material_id'])['value'], 995)

    def test_explicit_nonperformance_allows_a_new_exact_preparation_attempt_without_new_allocations(self):
        self.start(prepared_roles=('working.antibody_buffer',))
        stage = self.to_stage('S03')
        initial_allocations = copy.deepcopy(self.journal.audit_material_allocations())
        role = self.bound_recipe['roles']['working.antibody_buffer']
        first = 'Test.Absent.Preparation'
        self.act('begin_prepare_mix', stage_run_id=stage, recipe_role='working.antibody_buffer', intent_id=first)
        self.act('resolve_recipe_operation', intent_id=first, outcome='not_performed',
            actual_inputs=[], actual_outputs=[], observations={},
            reason='Explicit fixture-only observation that no mixing or transfer occurred')
        self.assertNotIn(role['material_id'], self.flow.state['inventory']['materials'])
        self.prepare_mix('working.antibody_buffer', stage, intent='Test.New.Exact.Preparation')
        self.assertEqual(self.journal.audit_material_allocations(), initial_allocations)
        self.assertTrue(self.bindings.reagent_ready(self.flow.state, 'working.antibody_buffer'))

    def test_failed_confirmation_commits_neither_consumption_output_nor_observation_identity(self):
        self.start(prepared_roles=('working.antibody_buffer',))
        stage = self.to_stage('S03')
        intent = 'Test.Atomic.Preparation'
        self.act('begin_prepare_mix', stage_run_id=stage, recipe_role='working.antibody_buffer', intent_id=intent)
        before = self.flow.state
        role = self.bound_recipe['roles']['working.antibody_buffer']
        request = before['bookings'][intent]['request']
        data = {'intent_id': intent, 'actual_inputs': [
            {'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
            for item in request['inputs']], 'actual_outputs': [
            {'material_id': role['material_id'], 'quantity': copy.deepcopy(role['output_quantity'])}],
            'reason': 'Explicit fixture-only atomic preparation receipt'}
        observation = self.envelope()
        with patch.object(self.journal, 'append', side_effect=TaskError('Injected durable write failure')):
            with self.assertRaisesRegex(TaskError, 'Injected'):
                self.act('confirm_prepare_mix', envelope=observation, **data)
        self.assertEqual(self.flow.state, before)
        self.assertNotIn(role['material_id'], self.flow.state['inventory']['materials'])
        self.act('confirm_prepare_mix', envelope=observation, **data)
        self.assertEqual(self.flow.state['bookings'][intent]['outcome'], 'performed')

    def test_restart_after_unknown_mixing_preserves_the_same_intent_and_prevents_redosing(self):
        self.start()
        stage = self.to_stage('S03')
        addition = self.perform('S03', self.REFERENCE)
        following = self.flow.recipe_next(stage)
        intent = 'Test.Mixing.WithoutReceipt'
        self.act('begin_recipe_operation', stage_run_id=stage, step_id=following['step_id'],
            iteration=following['iteration'], operation='mix', intent_id=intent)
        self.act('mark_recipe_unknown', intent_id=intent, reason='Explicit fixture-only lost mixing receipt')
        balance = ledger.remaining(self.flow.state,
            self.bound_recipe['roles']['working.activated_beads']['material_id'])
        replacement = FakeClock(clock_id='Test.Recipe.Restart.Epoch', process_id='Test.Recipe.Restart.Writer')
        self.flow = self.runtime.CutRunManualRecipeWorkflow.open(
            self.journal, self.flow.run_id, resume=True, clock=replacement)
        self.assertTrue(self.flow.state['clock']['gap_required'])
        self.assertEqual(self.flow.state['recipe']['pending_observation'], intent)
        with self.assertRaises(TaskError):
            self.act('begin_recipe_operation', stage_run_id=stage, step_id=following['step_id'],
                iteration=following['iteration'], operation='add', intent_id='Test.Forbidden.Readdition')
        self.assertEqual(ledger.remaining(self.flow.state,
            self.bound_recipe['roles']['working.activated_beads']['material_id']), balance)
        self.assertEqual(self.flow.state['bookings'][addition]['outcome'], 'performed')
        self.act('resolve_recipe_operation', intent_id=intent, outcome='performed',
            actual_inputs=[], actual_outputs=[], observations={'performed': True, 'mixed': True},
            reason='Explicit fixture-only later observation of the original mixing action')
        self.assertIsNone(self.flow.state['recipe']['pending_observation'])
        self.assertTrue(self.flow.state['clock']['gap_required'])

    def test_column_loads_follow_actual_remainder_and_cannot_finish_after_one_partial_load(self):
        self.start()
        self.opening();self.ordinary('S02', self.INPUT)
        self.begin('S09', self.INPUT)
        self.perform('S09', self.INPUT);self.perform('S09', self.INPUT)
        self.phase('S09', self.INPUT, 'S09.input_preparation')
        self.steps('S09', self.INPUT, retained_ul=34)
        self.finish('S09', self.INPUT)
        stage = self.begin('S10', self.INPUT)
        self.perform('S10', self.INPUT);self.perform('S10', self.INPUT)
        source = self.flow.state['manual']['reactions'][self.INPUT]['current_material_id']
        self.assertEqual(ledger.remaining(self.flow.state, source)['value'], 39)
        loads = []
        while (following := self.flow.recipe_next(stage))['step_id'] == 'S10.column_load':
            operation = self.perform('S10', self.INPUT, next_operation=following)
            if following['operation'] == 'load':
                amount = next(item['quantity']['value'] for item in
                    self.flow.state['bookings'][operation]['actual_inputs'] if item['material_id'] == source)
                loads.append(amount)
            if len(loads) == 1 and following['operation'] == 'remove':
                with self.assertRaises(TaskError):self.finish('S10', self.INPUT)
        self.assertEqual(loads, [10, 10, 10, 9])
        self.assertEqual(ledger.remaining(self.flow.state, source)['value'], 0)
        role = self.flow.state['definition']['recipe_profile']['consumables']['input']
        self.assertEqual(self.flow.state['inventory']['materials'][
            self.flow.state['manual']['reactions'][self.INPUT]['current_material_id']]['vessel_id'], role['column_id'])
        self.assertFalse(any(item['quantity']['unit'] == 'columns' for booking in self.flow.state['bookings'].values()
                            for item in booking['actual_inputs']))

    def test_full_serial_wash_recipe_keeps_products_qc_and_explicit_dispositions_separate(self):
        self.start()
        self.opening();self.ordinary('S02', self.INPUT)
        self.begin('S09', self.INPUT)
        self.perform('S09', self.INPUT);self.perform('S09', self.INPUT)
        self.phase('S09', self.INPUT, 'S09.input_preparation')
        self.steps('S09', self.INPUT);self.finish('S09', self.INPUT)
        products = [self.purify(self.INPUT), self.branch(self.REFERENCE), self.branch(self.IGG)]
        self.qc()
        self.begin('S12')
        for identity, material in self.flow.state['inventory']['materials'].items():
            if material['disposition'] != 'consumed':
                self.act('set_disposition', material_id=identity, disposition='retained',
                    reason='Explicit fixture-only final product and fraction handover')
        self.act('confirm_inventory', observations=self.flow.inventory_observations())
        self.finish('S12')
        self.act('close_capture', workspace_clear=True, reason='Explicit fixture-only full recipe handover')
        report = self.flow.report()
        self.assertTrue(report['capture_completed'])
        self.assertFalse(report['reference_success']);self.assertFalse(report['execution_ready'])
        self.assertTrue(report['sop']['sequence_complete'])
        for identity in products:
            self.assertEqual(ledger.remaining(self.flow.state, identity)['value'], 6)
            self.assertEqual(self.flow.state['inventory']['materials'][identity]['disposition'], 'retained')
        self.assertTrue(ledger.audit(self.flow.state))
