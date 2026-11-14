"""DNeasy execution composition preserves E1 and binds one canonical DNA world."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dneasy_extraction_sources as sources
from manual_tasks import TaskError, digest


class DNeasySourcesTests(unittest.TestCase):
    def profile(self):
        return json.loads(sources.SOURCE.read_bytes())

    def test_only_existing_dna_lineage_is_bound_and_preparation_limits_survive(self):
        value = sources.load()
        self.assertEqual(value['format'], 'solidcraftbot.material-workflow-definition/2')
        self.assertEqual(value['profile']['type'], 'dneasy_synthetic/1')
        self.assertEqual(value['clock_mode'], 'synthetic_events/1')
        self.assertFalse(value['preparation_plan']['execution_ready'])
        self.assertIn('extraction_execution_unimplemented', value['preparation_plan']['execution_blockers'])
        self.assertEqual([entry['role'] for entry in value['declared_inputs']], ['dna'])
        self.assertEqual([entry['material_id'] for entry in value['declared_inputs']], ['SYN.Source01.DNAAliquot'])
        self.assertEqual(value['products'][0]['material_id'], 'SYN.Source01.DNAExtract')
        self.assertNotIn('SYN.Source01.RNAAliquot', {entry['id'] for entry in value['initial_materials']})

    def test_individual_operations_preserve_order_timing_rcf_and_unknown_dna_mass(self):
        steps = sources.load()['execution']['steps']
        ids = [entry['id'] for entry in steps]
        self.assertLess(ids.index('rnase_decision'), ids.index('add_al'))
        self.assertLess(ids.index('mix_al'), ids.index('incubate_lysis'))
        self.assertLess(ids.index('change_collection_aw1'), ids.index('add_aw1'))
        self.assertLess(ids.index('change_collection_aw2'), ids.index('add_aw2'))
        self.assertLess(ids.index('move_to_elution_tube'), ids.index('add_ae'))
        self.assertEqual(ids[-1], 'spin_elute')
        bound = next(entry for entry in steps if entry['id'] == 'spin_bind')
        self.assertEqual(bound['parameters']['rcf_min_x_g'], 6000)
        self.assertEqual(bound['fixture_actual_outputs'][0]['quantity'], {'value': None, 'unit': 'ng'})
        drying = next(entry for entry in steps if entry['id'] == 'spin_aw2_dry')
        self.assertEqual(drying['parameters']['rcf_min_x_g'], 20000)
        self.assertEqual(drying['parameters']['duration_s'], 180)
        self.assertNotIn('add_rnase', ids)

    def test_selected_rnase_requires_its_issued_aliquot_and_precedes_lysis(self):
        profile = self.profile(); profile['rnase_selected'] = True
        with self.assertRaises(TaskError):
            sources.load(profile)
        profile['reagent_aliquots']['RNaseA'] = {'material_id': 'SYN.RNaseA', 'vessel_id': 'SYN.RNaseATube',
                                               'quantity': {'value': 20, 'unit': 'uL'}}
        value = sources.load(profile)
        steps = value['execution']['steps']; ids = [entry['id'] for entry in steps]
        self.assertLess(ids.index('add_rnase'), ids.index('incubate_rnase'))
        self.assertLess(ids.index('incubate_rnase'), ids.index('add_al'))
        self.assertEqual(next(entry for entry in steps if entry['id'] == 'incubate_rnase')['parameters']['duration_s'], 120)

    def test_qc_uses_ts01_source_and_separate_ladder_ancestry_and_consumption(self):
        value = sources.load(); qc = value['execution']['qc']
        self.assertEqual(qc['instrument_id'], 'TS01')
        self.assertEqual(qc['planning_reference'], '4200 TapeStation')
        self.assertIsNone(qc['selected_model'])
        self.assertEqual(qc['assay_id'], 'GenomicDNA.ScreenTape')
        self.assertEqual(qc['parameters'], qc['protocol']['assay']['preparation'])
        sample_inputs = qc['sample']['effect']['inputs']
        ladder_inputs = qc['ladder']['effect']['inputs']
        self.assertEqual(sample_inputs[0]['material_id'], 'SYN.Source01.DNAExtract')
        self.assertEqual(sample_inputs[0]['quantity'], {'value': 1.0, 'unit': 'uL'})
        self.assertNotIn('SYN.Source01.DNAExtract', {entry['material_id'] for entry in ladder_inputs})
        self.assertEqual(sample_inputs[1]['material_id'], ladder_inputs[1]['material_id'])
        self.assertEqual(sample_inputs[1]['quantity']['value'] + ladder_inputs[1]['quantity']['value'], 20)
        self.assertNotEqual(qc['sample']['lane_id'], qc['ladder']['lane_id'])
        self.assertEqual(qc['policy_scope'], 'synthetic_fixture_only_not_manufacturer_or_biological_acceptance')

    def test_all_runtime_and_model_pins_match_actual_bytes(self):
        value = sources.load()
        for name, checksum in value['source_files_sha256'].items():
            self.assertEqual(digest((ROOT / name).read_bytes()), checksum, name)
        self.assertIn('scripts/dneasy_extraction_workflow.py', value['runtime_source_files'])
        self.assertIn('scripts/run_dneasy_extraction.py', value['runtime_source_files'])
        self.assertIn('scripts/tapestation_results.py', value['runtime_source_files'])

    def test_mode_extra_fields_and_wrong_lineage_are_rejected(self):
        for change in [{'mode': 'hardware'}, {'synthetic': False}, {'input_material_id': 'SYN.Source01.RNAAliquot'},
                       {'selected_model': '4200'}]:
            with self.subTest(change=change):
                profile = self.profile(); profile.update(change)
                with self.assertRaises(TaskError):
                    sources.load(profile)

    def test_cell_count_must_be_positive_integral_and_within_selected_protocol(self):
        for amount in [0, -1, 0.5, 5000001, True, None]:
            with self.subTest(amount=amount):
                profile = self.profile(); profile['input_quantity']['value'] = amount
                with self.assertRaises(TaskError):
                    sources.load(profile)

    def test_physical_collection_and_reagent_vessels_cannot_alias(self):
        for mutation in [lambda profile: profile['extra_vessels'].update(aw1_collection='SYN.DNA.Collection01'),
                         lambda profile: profile['reagent_aliquots']['AE'].update(vessel_id='SYN.DNA.Column01')]:
            profile = self.profile(); mutation(profile)
            with self.assertRaises(TaskError):
                sources.load(profile)

    def test_declared_fixture_units_and_insufficient_issued_reagents_are_rejected(self):
        profile = self.profile(); profile['fixture_output_quantities']['bound_dna']['unit'] = 'uL'
        with self.assertRaises(TaskError):
            sources.load(profile)
        for role, volume in [('AW2', 499), ('TSBuffer', 19), ('TSLadder', 0.5)]:
            with self.subTest(role=role):
                profile = self.profile(); profile['reagent_aliquots'][role]['quantity']['value'] = volume
                with self.assertRaises(TaskError):
                    sources.load(profile)

    def test_source_pins_and_source_selection_are_not_self_reported(self):
        profile = self.profile(); profile['protocol']['source_sha256'] = '0' * 64
        with self.assertRaises(TaskError):
            sources.load(profile)
        profile = self.profile(); profile['tapestation']['source'] = 'model/robot.json'
        with self.assertRaises(TaskError):
            sources.load(profile)

    def test_budget_and_qc_policy_have_explicit_finite_bounds(self):
        profile = self.profile(); profile['settings']['task_deadline_s'] = 1
        with self.assertRaises(TaskError):
            sources.load(profile)
        for change in [{'minimum_din': 11}, {'minimum_din': True}, {'minimum_fragment_size_bp': 0}]:
            profile = self.profile(); profile['qc_policy'].update(change)
            with self.assertRaises(TaskError):
                sources.load(profile)

    def test_formal_profile_and_protocol_schemas_match_current_sources(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('jsonschema and referencing required for formal source checks')
        schemas = {name: json.loads((ROOT / 'model' / name).read_text())
                   for name in ['assembly-reference.schema.json', 'dneasy-extraction.schema.json']}
        registry = Registry().with_resources((name, Resource.from_contents(value)) for name, value in schemas.items())
        validator = Draft202012Validator(schemas['dneasy-extraction.schema.json'], registry=registry)
        validator.validate(self.profile())
        validator.validate(json.loads(sources.PROTOCOL.read_text()))
        bad = self.profile(); bad['input_quantity']['unit'] = 'uL'
        self.assertTrue(list(validator.iter_errors(bad)))


if __name__ == '__main__':
    unittest.main()
