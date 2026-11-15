"""Pinned additive extraction feature; no device or network execution claims."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_dna_quantification_sila2 as old_contract
import build_extraction_analytics_sila2 as contract
from manual_tasks import TaskError


class ExtractionAnalyticsContractTests(unittest.TestCase):
    def mutate(self, change):
        data = json.loads(contract.SOURCE.read_text())
        change(data)
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='extraction-sila-contract-', dir=ROOT / 'exports') as directory:
            path = Path(directory) / 'contract.json'
            path.write_text(json.dumps(data))
            return contract.load(path)

    def test_exact_additive_feature_and_high_level_closed_command_surface(self):
        data = contract.load()
        root = ET.fromstring(contract.feature(data))
        self.assertEqual(root.findtext(contract.Q('Identifier')), 'ExtractionAnalyticsWorkflow')
        self.assertEqual(root.get('FeatureVersion'), '1.0')
        self.assertEqual(root.get('MaturityLevel'), 'Draft')
        commands = {node.findtext(contract.Q('Identifier')): node for node in root.findall(contract.Q('Command'))}
        self.assertEqual(set(commands), contract.COMMANDS)
        expected = {'CreateRun': ['request_identifier', 'run_identifier', 'family_identifier'],
            'RunUntilDecision': ['request_identifier', 'run_identifier'],
            'ResumeRun': ['request_identifier', 'run_identifier', 'resume'],
            'ReconcileRun': ['request_identifier', 'run_identifier', 'observation_json'],
            'CancelRun': ['request_identifier', 'run_identifier', 'reason'],
            'FinishCancel': ['request_identifier', 'run_identifier', 'observation_json']}
        for source in data['commands']:
            self.assertEqual([field['name'] for field in source['arguments']], expected[source['name']])
            fields = [node.findtext(contract.Q('Identifier')) for node in commands[source['name']].findall(contract.Q('Parameter'))]
            self.assertEqual(fields, [contract.camel(name) for name in expected[source['name']]])
            self.assertEqual(commands[source['name']].findtext(contract.Q('Observable')),
                             'Yes' if source['name'] == 'RunUntilDecision' else 'No')
        self.assertEqual({node.findtext(contract.Q('Identifier')) for node in root.findall(contract.Q('Property'))}, {'Status', 'Report'})
        self.assertIn('No hardware or ROS runtime', root.findtext(contract.Q('Description')))
        self.assertNotIn('Act', commands)
        self.assertNotIn('AdvanceTime', commands)
        self.assertNotIn('ConfirmMeasurement', commands)

    def test_both_families_reference_existing_single_material_roots(self):
        data = contract.load()
        self.assertEqual(set(data['definitions']), {'dneasy', 'puregene'})
        for family, definition in data['definitions'].items():
            self.assertEqual(data['families'][family]['source'], 'model/extraction-analytics.' + family + '.json')
            self.assertEqual(definition['execution']['analytics']['family'], family)
            self.assertEqual(definition['profile']['type'], 'extraction_analytics_synthetic/1')
            self.assertEqual(len([item for item in definition['initial_materials'] if item['kind'] == 'sample']), 1)
            self.assertEqual(len(definition['products']), 1)
            self.assertEqual(definition['products'][0]['material_id'], definition['execution']['analytics']['product_material_id'])

    def test_complete_runtime_family_and_standard_source_pins_are_current(self):
        data = contract.load()
        contract.verify_source_files(data['source_files_sha256'])
        for name in ['scripts/extraction_analytics_sila2_control.py', 'scripts/extraction_analytics_sila2_runtime.py',
                     'scripts/extraction_analytics_sila2_execution.py', 'scripts/dna_sila2_server.py',
                     'scripts/dna_sila2_runtime.py', 'scripts/run_dna_sila2.py', 'scripts/cf01_sila2_auth.py',
                     'scripts/material_ledger.py', 'scripts/manual_tasks.py', 'scripts/extraction_analytics_workflow.py',
                     'model/extraction-analytics.dneasy.json', 'model/extraction-analytics.puregene.json',
                     'model/extraction-analytics-sila2.schema.json', 'requirements/sila2-test.lock']:
            self.assertIn(name, data['source_files_sha256'])
            self.assertEqual(data['source_files_sha256'][name], contract.digest(ROOT / name))

    def test_source_pin_drift_is_rejected_without_changing_original_sources(self):
        for label in ['dneasy', 'puregene', 'analytics_protocol', 'standard_provenance']:
            def change(data):
                ref = data['families'][label] if label in {'dneasy', 'puregene'} else data[label]
                ref['source_sha256'] = '0' * 64
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, 'Changed extraction SiLA source'):
                self.mutate(change)

    def test_arbitrary_family_paths_and_extra_wire_fields_are_rejected(self):
        def foreign(data):
            name = 'model/dna-quantification.synthetic.json'
            data['families']['dneasy'] = {'source': name, 'source_sha256': contract.digest(ROOT / name)}
        with self.assertRaisesRegex(ValueError, 'Unsupported extraction SiLA source selection'):
            self.mutate(foreign)
        def extra(data):
            data['commands'][1]['arguments'].append({'name': 'pause_after', 'type': 'string', 'description': 'Not public'})
        with self.assertRaisesRegex(ValueError, 'Unsupported extraction SiLA contract field'):
            self.mutate(extra)
        with self.assertRaisesRegex(ValueError, 'Unexpected fields'):
            self.mutate(lambda data: data.update(act={}))

    def test_legacy_generated_fdl_and_archived_standards_stay_unchanged(self):
        expected = '8711c419c5c9ae2ebce26f93fe2b7c377cb1e62da9339c755ea2e300c49b0268'
        self.assertEqual(hashlib.sha256(old_contract.feature().encode()).hexdigest(), expected)
        data = contract.load()
        provenance = json.loads((ROOT / data['standard_provenance']['source']).read_text())
        self.assertEqual(data['standard_features'], provenance['files'])
        self.assertEqual(data['standard_features'], old_contract.load()['standard_features'])
        for ref in data['standard_features']:
            self.assertEqual(contract.digest(ROOT / ref['source']), ref['source_sha256'])
        lock = next(ref for ref in data['standard_features'] if ref['identifier'] == 'LockController')
        self.assertTrue(lock['source'].endswith('LockController-v1_0.sila.xml'))

    def test_known_readiness_limits_and_finite_publication_interval_required(self):
        for value in (0, -1, 2, True, float('nan')):
            with self.subTest(value=value), self.assertRaises((ValueError, TaskError)):
                self.mutate(lambda data: data.update(publish_interval_s=value))
        with self.assertRaisesRegex(ValueError, 'qualification limits'):
            self.mutate(lambda data: data.update(limitations=[]))
        with self.assertRaisesRegex(ValueError, 'Unsupported extraction SiLA contract field'):
            self.mutate(lambda data: data.update(hardware_available=True))

    def test_generation_is_confined_to_exports_and_makes_no_execution_claim(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='extraction-sila-generation-', dir=ROOT / 'exports') as directory:
            generated = contract.build(directory)
            self.assertEqual(generated.name, 'ExtractionAnalyticsWorkflow-v1_0.sila.xml')
            report = json.loads((Path(directory) / 'generation-report.json').read_text())
            self.assertEqual(report['sha256'], contract.digest(generated))
            self.assertTrue(report['simulation_only'])
            for name in ('schema_validated', 'network_executed', 'hardware_executed', 'ros2_executed'):
                self.assertIs(report[name], False)
        with self.assertRaisesRegex(ValueError, 'exports'):
            contract.build(ROOT / 'docs/media')

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Requires the pinned test environment')
    def test_formal_protocol_schema_matches_current_profile(self):
        import jsonschema
        schema = json.loads(contract.SCHEMA.read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(json.loads(contract.SOURCE.read_text()))

    @unittest.skipUnless(importlib.util.find_spec('sila') and importlib.util.find_spec('xmlschema'),
                         'Requires the pinned SiLA test environment; skip is not conformance evidence')
    def test_official_xsd_and_sdk_accept_the_additive_feature(self):
        import xmlschema
        from importlib.resources import files
        from sila.server import Feature
        source = contract.feature()
        xmlschema.XMLSchema(str(files('sila') / 'resources/FeatureDefinition.xsd')).validate(source)
        feature = Feature.from_definition(source)
        self.assertEqual(str(feature.fully_qualified_identifier), 'org.solidcraftbot/analytics/ExtractionAnalyticsWorkflow/v1')


if __name__ == '__main__':
    unittest.main()
