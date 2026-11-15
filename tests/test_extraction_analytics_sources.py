"""Opt-in analytics sources preserve extraction identity and one material stock."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import extraction_analytics_sources as sources
import dna_quantification_sources
import dneasy_extraction_sources
import puregene_extraction_sources
from manual_tasks import TaskError, digest


class ExtractionAnalyticsSourcesTests(unittest.TestCase):
    def profile(self, family='dneasy'):
        return json.loads((ROOT / ('model/extraction-analytics.' + family + '.json')).read_bytes())

    def load(self, family='dneasy'):
        return sources.load(self.profile(family))

    def test_both_families_keep_one_original_input_and_the_same_product(self):
        for family, loader in [('dneasy', dneasy_extraction_sources.load), ('puregene', puregene_extraction_sources.load)]:
            with self.subTest(family=family):
                old, value = loader(), self.load(family)
                self.assertEqual(value['format'], 'solidcraftbot.material-workflow-definition/2')
                self.assertEqual(value['profile']['type'], sources.ENGINE)
                self.assertEqual(value['declared_inputs'], old['declared_inputs'])
                self.assertEqual(value['products'], old['products'])
                self.assertEqual(value['execution']['samples'], old['execution']['samples'])
                samples = [m for m in value['initial_materials'] if m['kind'] == 'sample']
                self.assertEqual(samples, [m for m in old['initial_materials'] if m['kind'] == 'sample'])
                self.assertFalse(any(m['id'] == value['products'][0]['material_id'] for m in value['initial_materials']))
                self.assertFalse(any(m['vessel_id'] == 'SYN.DNA.Tube01' for m in value['initial_materials']))

    def test_existing_extraction_recipe_tapestation_and_source_pins_are_retained(self):
        for family, loader in [('dneasy', dneasy_extraction_sources.load), ('puregene', puregene_extraction_sources.load)]:
            old, value = loader(), self.load(family)
            self.assertEqual(value['execution']['steps'], old['execution']['steps'])
            self.assertEqual(value['execution']['qc'], old['execution']['qc'])
            self.assertEqual(value['preparation_plan'], old['preparation_plan'])
            self.assertFalse(value['preparation_plan']['execution_ready'])
            for name, checksum in old['source_files_sha256'].items():
                self.assertEqual(value['source_files_sha256'][name], checksum)

    def test_device_definitions_bind_the_actual_product_home_without_initial_volume(self):
        quant = dna_quantification_sources.load()
        for family in ('dneasy', 'puregene'):
            value = self.load(family); analytics = value['execution']['analytics']
            self.assertEqual(analytics['sequence'], ['nanodrop', 'qubit'])
            for name, device in analytics['devices'].items():
                sample = device['profile']['samples'][0]
                self.assertEqual(device['profile']['samples'], [{'id': analytics['sample_id'],
                    'vessel_id': analytics['product_vessel_id'], 'rack_slot': 1, 'initial_volume_ul': None}])
                self.assertEqual(device['profile']['rack']['id'], analytics['product_home']['rack_id'])
                self.assertEqual(device['places'], [{'id': analytics['product_home']['place_id'], 'slot': 1}])
                self.assertEqual(device['profile']['parameters'], quant['devices'][name]['profile']['parameters'])
                self.assertIn('not_cad_registration', device['runtime_projection']['place_scope'])
            self.assertEqual(analytics['assays'], quant['protocol']['assays'])
            self.assertEqual(analytics['devices']['qubit']['profile']['parameters']['assay_total_volume_ul'], 200)

    def test_explicit_working_solution_and_standard_stocks_have_one_allocation_each(self):
        issued = []
        for family in ('dneasy', 'puregene'):
            value = self.load(family); a = value['execution']['analytics']; materials = {m['id']: m for m in value['initial_materials']}
            roles = [a['reagent_bindings']['working_solution'], *a['reagent_bindings']['standards'].values()]
            self.assertEqual(len(set(roles)), 3)
            for identity in roles:
                self.assertEqual(materials[identity]['kind'], 'reagent')
                self.assertEqual(materials[identity]['quantity']['unit'], 'uL')
                self.assertEqual(len([r for r in value['material_allocations'] if r['material_id'] == identity]), 1)
            self.assertEqual(materials[roles[0]]['quantity']['value'], 1000)
            for standard in a['devices']['qubit']['protocol']['assay']['standards']:
                self.assertEqual(standard['stock_id'], a['reagent_bindings']['standards'][standard['id']])
                self.assertNotEqual(standard['stock_id'], a['devices']['qubit']['runtime_projection']['source_standard_stock_ids'][standard['id']])
            issued.append(set(roles))
        self.assertFalse(issued[0] & issued[1])

    def test_run_binding_is_pure_and_declares_real_empty_tubes_matching_preparation_ids(self):
        for family in ('dneasy', 'puregene'):
            definition = self.load(family); before = copy.deepcopy(definition)
            bound = sources.bind_run(definition, 'SYN.Analytics.Unit01')
            self.assertEqual(definition, before)
            a = bound['execution']['analytics']; self.assertEqual(a['context_ids']['qubit'], 'SYN.Analytics.Unit01.Qubit')
            expected = ['SYN.Analytics.Unit01.Qubit.A01.P%04d.Tube' % n for n in (1, 2, 3)]
            self.assertEqual(list(a['qubit_tubes'].values()), expected)
            self.assertEqual(len(bound['initial_vessels']), len(definition['initial_vessels']) + 3)
            self.assertEqual(bound['initial_materials'], definition['initial_materials'])
            for tube in expected:
                vessel = next(v for v in bound['initial_vessels'] if v['id'] == tube)
                self.assertEqual(vessel['location']['kind'], 'logical')
                self.assertNotEqual(vessel['location']['holder_id'], a['devices']['qubit']['profile']['instrument']['id'])
                self.assertFalse(any(m['vessel_id'] == tube for m in bound['initial_materials']))
            self.assertEqual(sources.bind_run(bound, 'SYN.Analytics.Unit01'), bound)

    def test_binding_rejects_foreign_engine_other_runs_and_invalid_run_identity(self):
        definition = self.load()
        bound = sources.bind_run(definition, 'SYN.Analytics.Unit01')
        with self.assertRaises(TaskError): sources.bind_run(bound, 'SYN.Analytics.Unit02')
        wrong = copy.deepcopy(bound); wrong['execution']['analytics']['qubit_tubes']['standard:SYN.StandardLow'] = wrong['products'][0]['vessel_id']
        with self.assertRaises(TaskError): sources.bind_run(wrong, 'SYN.Analytics.Unit01')
        with self.assertRaises(TaskError): sources.bind_run(dneasy_extraction_sources.load(), 'SYN.Analytics.Unit01')
        for identity in ('', '../bad', 'x' * 65, None):
            with self.subTest(identity=identity), self.assertRaises(TaskError): sources.bind_run(definition, identity)

    def test_unknown_fields_non_synthetic_mode_and_wrong_family_reference_are_rejected(self):
        for mutate in [lambda p: p.update(extra=True), lambda p: p.update(mode='hardware'),
                       lambda p: p.update(family='puregene'), lambda p: p.update(family='other'),
                       lambda p: p.update(fixture_scope=''),
                       lambda p: p['issued_reagents'].update(extra={})]:
            p = self.profile(); mutate(p)
            with self.assertRaises(TaskError): sources.load(p)

    def test_all_issued_stocks_need_finite_sufficient_known_volume(self):
        for role in ('working_solution', 'SYN.StandardLow', 'SYN.StandardHigh'):
            for amount in (None, 0, 1, -1, float('inf'), True):
                p = self.profile()
                issue = p['issued_reagents']['working_solution'] if role == 'working_solution' else p['issued_reagents']['standards'][role]
                issue['quantity']['value'] = amount
                with self.subTest(role=role, amount=amount), self.assertRaises(TaskError): sources.load(p)
        p = self.profile(); p['issued_reagents']['working_solution']['quantity']['unit'] = 'ng'
        with self.assertRaises(TaskError): sources.load(p)

    def test_material_vessel_future_product_and_location_aliases_are_rejected(self):
        base = dneasy_extraction_sources.load()
        aliases = [base['initial_materials'][0]['id'], base['initial_vessels'][0]['id'], base['products'][0]['material_id']]
        for alias in aliases:
            for field in ('material_id', 'vessel_id'):
                p = self.profile(); p['issued_reagents']['working_solution'][field] = alias
                with self.subTest(alias=alias, field=field), self.assertRaises(TaskError): sources.load(p)
        p = self.profile(); p['issued_reagents']['standards']['SYN.StandardLow']['location'] = p['issued_reagents']['working_solution']['location']
        with self.assertRaises(TaskError): sources.load(p)
        p = self.profile(); p['issued_reagents']['working_solution']['location']['holder_id'] = 'SYN.Qubit401'
        with self.assertRaises(TaskError): sources.load(p)

    def test_wrong_source_hash_foreign_source_or_binary_reference_is_rejected(self):
        for field in ('extraction', 'quantification', 'protocol'):
            p = self.profile(); p[field]['source_sha256'] = '0' * 64
            with self.subTest(field=field), self.assertRaises(TaskError): sources.load(p)
        for path in ('model/robot.json', '../README.md', 'docs/media/robot-demo.mp4'):
            p = self.profile(); p['quantification']['source'] = path
            with self.subTest(path=path), self.assertRaises(TaskError): sources.load(p)

    def test_runtime_source_pins_match_and_synthetic_product_can_supply_all_three_draws(self):
        for family in ('dneasy', 'puregene'):
            value = self.load(family)
            for name, checksum in value['source_files_sha256'].items():
                self.assertEqual(digest((ROOT / name).read_bytes()), checksum, name)
            self.assertTrue(set(sources.RUNTIME) <= set(value['runtime_source_files']))
            self.assertTrue(set(sources.RUNTIME) <= set(value['source_files_sha256']))
            self.assertEqual(value['clock_mode'], 'synthetic_events/1')
        base = dneasy_extraction_sources.load()
        product_id = base['products'][0]['material_id']
        for step in base['execution']['steps']:
            for receipt in step.get('fixture_actual_outputs', []):
                if receipt['material_id'] == product_id: receipt['quantity']['value'] = 3
        with patch.object(dneasy_extraction_sources, 'load', return_value=base), self.assertRaises(TaskError):
            self.load()

    def test_formal_schema_accepts_all_new_sources_and_rejects_extra_recipe_values(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema required')
        validator = Draft202012Validator(json.loads(sources.SCHEMA.read_bytes()))
        validator.check_schema(validator.schema)
        validator.validate(self.profile()); validator.validate(self.profile('puregene'))
        validator.validate(json.loads(sources.PROTOCOL.read_bytes()))
        p = self.profile(); p['issued_reagents']['working_solution']['quantity']['value'] = None
        self.assertTrue(list(validator.iter_errors(p)))
        p = self.profile(); p['sample_volume_ul'] = 5
        self.assertTrue(list(validator.iter_errors(p)))


if __name__ == '__main__':
    unittest.main()
