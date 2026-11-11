"""The extraction preparation contracts use local shared schema references."""
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
class ExtractionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = []
        for name in ['assembly-reference.schema.json', 'extraction-automation.schema.json']:
            path = ROOT / 'model' / name
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri()
            resources.append((schema['$id'], Resource.from_contents(schema)))
            if name.startswith('extraction-'):
                extraction = schema
        cls.validator = Draft202012Validator(extraction, registry=Registry().with_resources(resources))
        cls.profile = json.loads((ROOT / 'model/extraction-automation.preparation.json').read_text())

    def test_all_three_source_documents_validate_without_network_resolution(self):
        for kind in ['catalog', 'protocol', 'preparation']:
            with self.subTest(kind=kind):
                self.validator.validate(json.loads((ROOT / ('model/extraction-automation.' + kind + '.json')).read_text()))

    def test_missing_source_pin_and_unimplemented_execution_mode_are_rejected(self):
        for change in ['pin', 'mode', 'synthetic']:
            value = copy.deepcopy(self.profile)
            if change == 'pin':
                del value['catalog']['source_sha256']
            elif change == 'mode':
                value['mode'] = 'hardware'
            else:
                value['synthetic'] = False
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.validator.validate(value)

    def test_rna_requires_its_distinct_gdna_column_and_collection_role(self):
        for role in ['gdna_column', 'gdna_collection_vessel']:
            value = copy.deepcopy(self.profile)
            del value['sample_pairs'][0]['processes']['rna']['items'][role]
            with self.subTest(role=role), self.assertRaises(ValidationError):
                self.validator.validate(value)

    def test_unknown_rpm_parameter_fractional_cycles_and_boolean_amount_are_rejected(self):
        for change in ['rpm', 'cycles', 'boolean']:
            value = copy.deepcopy(self.profile)
            process = value['sample_pairs'][0]['processes']['dna']
            if change == 'rpm':
                process['parameter_values']['bind_column'] = {'rpm': 8000}
            elif change == 'cycles':
                process['parameter_values']['wash_column'] = {'cycles': 1.5}
            else:
                process['input_amount'] = {'value': True, 'unit': 'cells'}
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.validator.validate(value)


if __name__ == '__main__':
    unittest.main()
