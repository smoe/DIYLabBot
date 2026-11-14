"""Puregene sources keep physical fractions, provenance and timing unambiguous."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import puregene_extraction_sources as sources
from manual_tasks import TaskError, digest


class PuregeneSourcesTests(unittest.TestCase):
    def profile(self):
        return json.loads(sources.SOURCE.read_bytes())

    def test_selected_puregene_cell_protocol_has_independent_input_and_retained_product(self):
        value = sources.load()
        self.assertEqual(value['format'], 'solidcraftbot.material-workflow-definition/2')
        self.assertEqual(value['profile']['type'], 'puregene_synthetic/1')
        self.assertFalse(value['preparation_plan']['execution_ready'])
        self.assertEqual(value['declared_inputs'][0]['material_id'], 'SYN.Puregene.Cells01')
        self.assertEqual(value['products'][0]['material_id'], 'SYN.Puregene.DNAProduct01')
        self.assertEqual(len([item for item in value['initial_materials'] if item['kind'] == 'sample']), 1)
        self.assertNotIn('SYN.Source01.DNAAliquot', {item['id'] for item in value['initial_materials']})
        self.assertEqual(value['preparation_plan']['manufacturer_reference']['revision'], 'HB-0326-004, January 2022')

    def test_protein_and_dna_spins_keep_composites_in_their_real_tubes(self):
        steps = {item['id']: item for item in sources.load()['execution']['steps']}
        protein = steps['spin_protein_precipitate']
        dna = steps['spin_dna_precipitate']
        self.assertEqual(protein['inputs'], []); self.assertEqual(protein['outputs'], [])
        self.assertEqual(protein['retention_after']['retained'], 'supernatant')
        self.assertEqual(protein['retention_after']['vessel_id'], 'SYN.Puregene.InputTube01')
        self.assertEqual(dna['inputs'], []); self.assertEqual(dna['outputs'], [])
        self.assertEqual(dna['retention_after']['retained'], 'pellet')
        self.assertEqual(dna['retention_after']['vessel_id'], 'SYN.Puregene.PrecipitationTube01')
        self.assertEqual(dna['parameters']['rcf_min_x_g'], 13000)
        self.assertEqual(dna['parameters']['rcf_max_x_g'], 16000)

    def test_ipa_prefill_tip_aspiration_and_dispense_have_separate_material_effects(self):
        steps = sources.load()['execution']['steps']; ids = [item['id'] for item in steps]
        prefill = steps[ids.index('prepare_isopropanol_receiver')]
        aspiration = steps[ids.index('aspirate_dna_supernatant')]
        dispense = steps[ids.index('dispense_into_isopropanol')]
        self.assertLess(ids.index(prefill['id']), ids.index(aspiration['id']))
        self.assertLess(ids.index(aspiration['id']), ids.index(dispense['id']))
        self.assertEqual(len(aspiration['inputs']), 1)
        self.assertNotIn(prefill['outputs'][0]['material_id'], {item['material_id'] for item in aspiration['inputs']})
        self.assertEqual({item['vessel_id'] for item in aspiration['outputs']},
                         {'SYN.Puregene.TransferTip01', 'SYN.Puregene.InputTube01'})
        self.assertEqual({item['material_id'] for item in dispense['inputs']},
                         {prefill['outputs'][0]['material_id'], aspiration['outputs'][0]['material_id']})
        self.assertEqual(prefill['required_positive_outputs'], [prefill['outputs'][0]['material_id']])
        self.assertNotIn('retention_after', prefill)
        self.assertEqual(next(item['quantity'] for item in dispense['inputs']
                              if item['material_id'] == prefill['outputs'][0]['material_id']),
                         {'value': 300, 'unit': 'uL'})
        self.assertEqual(dispense['outputs'][0]['vessel_id'], 'SYN.Puregene.PrecipitationTube01')

    def test_waste_never_becomes_the_continuing_dna_stream(self):
        steps = {item['id']: item for item in sources.load()['execution']['steps']}
        for name, waste_vessel in [('remove_isopropanol_supernatant', 'SYN.Puregene.IPAWasteTube01'),
                                   ('remove_ethanol_wash', 'SYN.Puregene.EthanolWasteTube01')]:
            step = steps[name]
            self.assertEqual(step['outputs'][0]['vessel_id'], 'SYN.Puregene.PrecipitationTube01')
            self.assertEqual(step['outputs'][1]['vessel_id'], waste_vessel)
            self.assertEqual(step['retention_after']['material_id'], step['outputs'][0]['material_id'])
            self.assertEqual(step['retention_after']['retained'], 'pellet')
            self.assertEqual(step['fixture_actual_outputs'][0]['quantity'], {'value': None, 'unit': 'ng'})
        for step in steps.values():
            if step['outputs'] and step['id'] != 'prepare_isopropanol_receiver':
                self.assertEqual(step['retention_after']['material_id'], step['outputs'][0]['material_id'])
                self.assertEqual(step['retention_after']['vessel_id'], step['outputs'][0]['vessel_id'])
        self.assertIsNone(steps['confirm_dissolution']['retention_after']['pellet'])
        self.assertEqual(steps['confirm_dissolution']['retention_after']['supernatant'], 'hydrated_dna_solution')

    def test_overnight_has_explicit_fixture_scope_and_drying_is_not_a_qualified_limit(self):
        definition = sources.load(); steps = {item['id']: item for item in definition['execution']['steps']}
        overnight = steps['overnight_hydration']
        self.assertEqual(overnight['parameters']['duration_s'], 43200)
        self.assertEqual(overnight['parameter_scopes']['duration_s'],
                         'explicit_synthetic_fixture_not_manufacturer_defined_hours')
        source = json.loads(sources.PROTOCOL.read_bytes())
        raw = next(item for item in source['steps'] if item['id'] == 'overnight_hydration')
        self.assertIsNone(raw['parameters']['duration_s'])
        dry = steps['air_dry_pellet']
        self.assertEqual(dry['parameters']['duration_s'], 300)
        self.assertNotIn('duration_max_s', dry['parameters'])
        self.assertIn('pellet_not_overdried_confirmed', dry['required_checks'])

    def test_selected_rnase_branch_uses_own_issued_stock_and_real_parameter_order(self):
        profile = self.profile(); profile['rnase_selected'] = True
        with self.assertRaises(TaskError): sources.load(profile)
        profile['reagent_aliquots']['RNaseA'] = {'material_id': 'SYN.Puregene.RNase',
            'vessel_id': 'SYN.Puregene.RNaseTube', 'quantity': {'value': 10, 'unit': 'uL'}}
        steps = sources.load(profile)['execution']['steps']; ids = [item['id'] for item in steps]
        self.assertEqual(len(steps), 30)
        self.assertLess(ids.index('add_rnase'), ids.index('incubate_rnase'))
        self.assertLess(ids.index('cool_rnase'), ids.index('add_protein_precipitant'))
        self.assertEqual(next(item for item in steps if item['id'] == 'mix_rnase')['parameters']['inversion_count'], 25)

    def test_tapestation_binding_reuses_frozen_assay_and_separates_ladder_from_sample(self):
        value = sources.load(); qc = value['execution']['qc']
        self.assertEqual(qc['instrument_id'], 'TS01')
        self.assertEqual(qc['parameters'], qc['protocol']['assay']['preparation'])
        self.assertEqual(qc['sample']['effect']['inputs'][0]['material_id'], 'SYN.Puregene.DNAProduct01')
        self.assertNotIn('SYN.Puregene.DNAProduct01',
                         {item['material_id'] for item in qc['ladder']['effect']['inputs']})
        self.assertIsNone(qc['selected_model'])
        self.assertEqual(qc['policy_scope'], 'synthetic_fixture_only_not_manufacturer_or_biological_acceptance')

    def test_all_runtime_source_pins_and_independent_reagent_allocations_match_bytes(self):
        value = sources.load()
        for name, checksum in value['source_files_sha256'].items():
            self.assertEqual(digest((ROOT / name).read_bytes()), checksum, name)
        for name in ['scripts/extraction_workflow.py', 'scripts/extraction_qc_sources.py',
                     'scripts/extraction_demo.py', 'scripts/extraction_cli.py']:
            self.assertIn(name, value['runtime_source_files'])
        self.assertEqual(len(value['material_allocations']), 7)
        self.assertTrue(all(item['material_id'].startswith('SYN.Puregene.') for item in value['material_allocations']))

    def test_unknown_fields_hardware_modes_and_foreign_sources_are_rejected(self):
        for change in [{'mode': 'hardware'}, {'synthetic': False}, {'selected_model': '4200'}]:
            profile = self.profile(); profile.update(change)
            with self.subTest(change=change), self.assertRaises(TaskError): sources.load(profile)
        for ref_name in ['protocol', 'tapestation_protocol']:
            profile = self.profile(); profile[ref_name]['source_sha256'] = '0' * 64
            with self.assertRaises(TaskError): sources.load(profile)

    def test_input_scope_residual_amounts_and_known_issued_quantities_are_required(self):
        for count in [0, 999999, 2000001, 1000000.5, True, None]:
            profile = self.profile(); profile['input_quantity']['value'] = count
            with self.subTest(count=count), self.assertRaises(TaskError): sources.load(profile)
        profile = self.profile(); profile['residual_liquid_ul'] = 0
        with self.assertRaises(TaskError): sources.load(profile)
        for role, amount in [('Isopropanol', 299), ('TSBuffer', 19), ('TSLadder', None)]:
            profile = self.profile(); profile['reagent_aliquots'][role]['quantity']['value'] = amount
            with self.subTest(role=role), self.assertRaises(TaskError): sources.load(profile)

    def test_aliases_unknown_dna_units_and_too_short_deadlines_are_rejected(self):
        for mutation in [lambda p: p['extra_vessels'].update(transfer_tip=p['input_vessel_id']),
                         lambda p: p['fixture_output_quantities']['dna_pellet'].update(unit='uL'),
                         lambda p: p['settings'].update(task_deadline_s=43200),
                         lambda p: p['settings'].update(overnight_fixture_s=0)]:
            profile = self.profile(); mutation(profile)
            with self.assertRaises(TaskError): sources.load(profile)

    def test_formal_profile_and_protocol_schema_validate_current_sources(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('jsonschema and referencing required')
        schemas = {name: json.loads((ROOT / 'model' / name).read_bytes())
                   for name in ['assembly-reference.schema.json', 'puregene-extraction.schema.json']}
        registry = Registry().with_resources((name, Resource.from_contents(value)) for name, value in schemas.items())
        validator = Draft202012Validator(schemas['puregene-extraction.schema.json'], registry=registry)
        validator.validate(self.profile()); validator.validate(json.loads(sources.PROTOCOL.read_bytes()))
        wrong = self.profile(); wrong['input_quantity']['unit'] = 'uL'
        self.assertTrue(list(validator.iter_errors(wrong)))


if __name__ == '__main__':
    unittest.main()
