"""CUT&RUN preparation documents validate without remote schema resolution."""

import copy
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
try:
    from jsonschema import Draft202012Validator, ValidationError
    from referencing import Registry, Resource
except ImportError:
    Draft202012Validator = None


@unittest.skipIf(Draft202012Validator is None, 'Optional jsonschema development dependency required')
class CutrunSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = []
        for name in ['assembly-reference.schema.json', 'cutrun-automation.schema.json']:
            path = ROOT / 'model' / name
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri()
            resources.append((schema['$id'], Resource.from_contents(schema)))
            if name.startswith('cutrun-'):
                cutrun = schema
        cls.validator = Draft202012Validator(cutrun, registry=Registry().with_resources(resources))
        cls.profile = json.loads((ROOT / 'model/cutrun-automation.preparation.json').read_text())

    def test_all_three_source_documents_validate_with_local_references(self):
        for kind in ['catalog', 'protocol', 'preparation']:
            with self.subTest(kind=kind):
                path = ROOT / f'model/cutrun-automation.{kind}.json'
                self.validator.validate(json.loads(path.read_text()))

    def test_unpinned_references_or_execution_modes_are_rejected(self):
        for mutation in ['catalog_pin', 'protocol_pin', 'hardware', 'real']:
            profile = copy.deepcopy(self.profile)
            if mutation.endswith('_pin'):
                del profile[mutation.removesuffix('_pin')]['source_sha256']
            elif mutation == 'hardware':
                profile['mode'] = 'hardware'
            else:
                profile['synthetic'] = False
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValidationError):
                    self.validator.validate(profile)

    def test_unknown_profile_fields_do_not_silently_enable_execution(self):
        for field in ['execution_ready', 'execute', 'reserve_resources']:
            profile = copy.deepcopy(self.profile)
            profile[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validator.validate(profile)

    def test_facts_require_basis_and_unknown_values_are_explicitly_null(self):
        for mutation in ['missing_basis', 'missing_unit', 'unknown_nonnull', 'invalid_basis']:
            profile = copy.deepcopy(self.profile)
            fact = profile['branches'][0]['input_amount']
            if mutation == 'missing_basis':
                del fact['basis']
            elif mutation == 'missing_unit':
                del fact['unit']
            elif mutation == 'unknown_nonnull':
                fact['basis'] = 'unknown'
            else:
                fact['basis'] = 'measured_and_qualified'
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValidationError):
                    self.validator.validate(profile)

    def test_unknown_historical_source_is_valid_without_an_invented_checksum(self):
        profile = copy.deepcopy(self.profile)
        for field in ['historical_sop_revision', 'original_sop_sha256']:
            self.assertIsNone(profile['source_binding'][field]['value'])
            self.assertEqual(profile['source_binding'][field]['basis'], 'unknown')
        self.validator.validate(profile)

    def test_missing_branch_and_wrong_numeric_fact_types_are_rejected(self):
        for mutation in ['missing_branch', 'boolean_count', 'fractional_count', 'wrong_count_unit', 'boolean_duration']:
            profile = copy.deepcopy(self.profile)
            if mutation == 'missing_branch':
                profile['branches'].pop()
            elif mutation == 'boolean_count':
                profile['branches'][0]['input_amount']['value'] = True
            elif mutation == 'fractional_count':
                profile['branches'][0]['input_amount']['value'] = 1.5
            elif mutation == 'wrong_count_unit':
                profile['branches'][0]['input_amount']['unit'] = 'uL'
            else:
                profile['branches'][0]['parameter_values']['activate_digest']['duration_s']['value'] = True
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValidationError):
                    self.validator.validate(profile)

    def test_matching_legacy_v1_documents_retain_their_old_field_shapes(self):
        catalog = json.loads((ROOT / 'model/cutrun-automation.catalog.json').read_text())
        protocol = json.loads((ROOT / 'model/cutrun-automation.protocol.json').read_text())
        profile = copy.deepcopy(self.profile)
        catalog['format'] = 'solidcraftbot.cutrun-catalog/1'
        catalog['materials'].pop('activation_reagent')
        catalog['materials']['stop_buffer'].update(label='CUT&RUN 4X Stop Buffer', catalog_number='48105')
        protocol['format'] = 'solidcraftbot.cutrun-preparation-protocol/1'
        protocol['required_material_roles']['cutrun'].remove('activation_reagent')
        for operation in protocol['operations'].values():
            operation.pop('reagent_role')
        profile['format'] = 'solidcraftbot.cutrun-preparation/1'
        for branch in profile['branches']:
            branch['material_bindings'].pop('activation_reagent', None)
        for document in [catalog, protocol, profile]:
            with self.subTest(format=document['format']):
                self.validator.validate(document)

    def test_v2_requires_prepared_activation_and_stop_mixtures_without_stock_skus(self):
        baseline = json.loads((ROOT / 'model/cutrun-automation.catalog.json').read_text())
        for role in ['activation_reagent', 'stop_buffer']:
            catalog = copy.deepcopy(baseline)
            catalog['materials'][role]['catalog_number'] = '48105'
            with self.subTest(role=role):
                with self.assertRaises(ValidationError):
                    self.validator.validate(catalog)

    def test_operation_reagent_roles_are_required_only_in_v2(self):
        protocol = json.loads((ROOT / 'model/cutrun-automation.protocol.json').read_text())
        del protocol['operations']['activate_digest']['reagent_role']
        with self.assertRaises(ValidationError):
            self.validator.validate(protocol)
        protocol['format'] = 'solidcraftbot.cutrun-preparation-protocol/1'
        with self.assertRaises(ValidationError):
            self.validator.validate(protocol)


if __name__ == '__main__':
    unittest.main()
