"""Offline wire, provenance and source-drift boundaries for the S09 adapter."""
import copy
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_cutrun_input_sonication_sila2 as contract


class SonicationContractTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)

    def source(self):
        return json.loads(contract.SOURCE.read_text(encoding='utf-8'))

    def changed(self, data):
        with tempfile.TemporaryDirectory(prefix='sonication-contract-', dir=ROOT / 'exports') as folder:
            path = Path(folder) / 'protocol.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            return contract.load(path)

    def test_wire_exposes_only_root_decisions_and_explicit_scenario_creation(self):
        root = ET.fromstring(contract.feature(self.source()))
        self.assertEqual(root.attrib, {'SiLA2Version': '1.1', 'FeatureVersion': '1.0',
            'MaturityLevel': 'Draft', 'Originator': 'org.solidcraftbot',
            'Category': 'analytics', 'Locale': 'en-us'})
        self.assertEqual(root.findtext(contract.Q('Identifier')), 'CutRunInputSonicationWorkflow')
        common = [('RequestIdentifier', 'String'), ('RunIdentifier', 'String')]
        expected = {'CreateRun': common + [('ScenarioIdentifier', 'String')],
                    'RunUntilDecision': common,
                    'ResumeRun': common + [('Resume', 'Boolean')],
                    'ReconcileRun': common + [('ObservationJson', 'String')],
                    'CancelRun': common + [('Reason', 'String')],
                    'FinishCancel': common + [('ObservationJson', 'String')]}
        commands = {node.findtext(contract.Q('Identifier')): node
                    for node in root.findall(contract.Q('Command'))}
        self.assertEqual(set(commands), set(expected))
        errors = {'WorkflowRejected', 'RecoveryRequired', 'ReconciliationRequired',
                  'CommandCanceled', 'PersistenceFailure'}
        for name, fields in expected.items():
            node = commands[name]
            with self.subTest(command=name):
                self.assertEqual([(item.findtext(contract.Q('Identifier')),
                                   item.findtext(contract.Q('DataType') + '/' + contract.Q('Basic')))
                                  for item in node.findall(contract.Q('Parameter'))], fields)
                self.assertEqual(node.findtext(contract.Q('Observable')),
                                 'Yes' if name == 'RunUntilDecision' else 'No')
                self.assertEqual([item.findtext(contract.Q('Identifier'))
                                  for item in node.findall(contract.Q('Response'))], ['StatusJson'])
                self.assertEqual([item.findtext(contract.Q('Identifier'))
                                  for item in node.findall(contract.Q('IntermediateResponse'))],
                                 ['StatusJson'] if name == 'RunUntilDecision' else [])
                for item in [*node.findall(contract.Q('Response')),
                             *node.findall(contract.Q('IntermediateResponse'))]:
                    self.assertEqual(item.findtext(contract.Q('DataType') + '/' + contract.Q('Basic')), 'String')
                self.assertEqual({item.text for item in node.findall(
                    contract.Q('DefinedExecutionErrors') + '/' + contract.Q('Identifier'))}, errors)
        self.assertEqual({node.findtext(contract.Q('Identifier'))
                          for node in root.findall(contract.Q('DefinedExecutionError'))}, errors)
        self.assertEqual({node.findtext(contract.Q('Identifier')): node.findtext(contract.Q('Observable'))
                          for node in root.findall(contract.Q('Property'))}, {'Status': 'Yes', 'Report': 'No'})
        for node in root.findall(contract.Q('Property')):
            self.assertEqual(node.findtext(contract.Q('DataType') + '/' + contract.Q('Basic')), 'String')
        self.assertIn('No hardware or ROS runtime', root.findtext(contract.Q('Description')))

    def test_wire_drift_and_false_simulation_claims_are_rejected_before_runtime(self):
        data = self.source()
        variants = []
        for name, value in [('simulation_only', False), ('hardware_available', True),
                            ('hardware_available', 0), ('mode', 'hardware'),
                            ('publish_interval_s', float('inf'))]:
            changed = copy.deepcopy(data)
            changed[name] = value
            variants.append((name, changed))
        for value in ['pause_after', 'physical_confirmation']:
            changed = copy.deepcopy(data)
            changed['commands'][1]['arguments'].append(
                {'name': value, 'type': 'bool', 'description': 'forbidden wire input'})
            variants.append((value, changed))
        changed = copy.deepcopy(data)
        changed['commands'].append({'name': 'Act', 'observable': False, 'arguments': []})
        variants.append(('Act', changed))
        changed = copy.deepcopy(data)
        changed['commands'][1]['arguments'].append(copy.deepcopy(data['commands'][0]['arguments'][2]))
        variants.append(('scenario outside CreateRun', changed))
        for name, changed in variants:
            with self.subTest(drift=name), self.assertRaises(ValueError):
                self.changed(changed)

    def test_composition_fixture_and_archived_standard_pins_are_mandatory(self):
        data = self.source()
        for name in ['composition_profile', 'fixture', 'standard_provenance']:
            changed = copy.deepcopy(data)
            changed[name]['source_sha256'] = '0' * 64
            with self.subTest(reference=name), self.assertRaises(ValueError):
                self.changed(changed)
        changed = copy.deepcopy(data)
        changed['composition_profile'] = copy.deepcopy(data['fixture'])
        with self.assertRaisesRegex(ValueError, 'Unsupported S09 SiLA source'):
            self.changed(changed)
        changed = copy.deepcopy(data)
        changed['standard_features'][1]['source_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.changed(changed)
        provenance = json.loads((ROOT / data['standard_provenance']['source']).read_text())
        self.assertEqual(data['standard_features'], provenance['files'])
        lock = next(ref for ref in data['standard_features'] if ref['identifier'] == 'LockController')
        self.assertEqual(lock['source'], 'interfaces/sila2/standard/LockController-v1_0.sila.xml')
        for ref in data['standard_features']:
            self.assertEqual(contract.digest(ROOT / ref['source']), ref['source_sha256'])

    def test_closure_includes_root_fixture_helpers_and_contract_validation_sources(self):
        data = contract.load()
        pins = data['source_files_sha256']
        for name in ['model/cutrun-input-sonication.profile.json',
                     'model/cutrun-input-sonication.fixture.json',
                     'model/cutrun-input-sonication-sila2.protocol.json',
                     'model/cutrun-input-sonication-sila2.schema.json',
                     'model/cutrun-manual-sop.protocol.json', 'model/dna-sonication.protocol.json',
                     'scripts/material_ledger.py', 'scripts/manual_tasks.py',
                     'scripts/sonication_sila2_runtime.py', 'scripts/sonication_sila2_server.py',
                     'scripts/cutrun_input_sonication_control.py',
                     'scripts/cf01_sila2_auth.py', 'scripts/cf01_sila2_client.py',
                     'scripts/furniture_model.py', 'scripts/rack_slots.py',
                     'interfaces/sila2/standard/provenance.json', 'requirements/sila2-test.lock']:
            with self.subTest(source=name):
                self.assertIn(name, pins)
                self.assertEqual(pins[name], contract.digest(ROOT / name))
        contract.verify_source_files(pins)
        self.assertNotIn('scripts/dna_sila2_runtime.py', pins)
        self.assertNotIn('scripts/cf01_sila2_runtime.py', pins)

    def test_frozen_closure_rejects_helper_and_contract_schema_drift(self):
        pins = contract.load()['source_files_sha256']
        read_bytes = Path.read_bytes
        for name in ['scripts/cf01_sila2_auth.py', 'scripts/cf01_sila2_client.py',
                     'model/cutrun-input-sonication-sila2.schema.json',
                     'model/cutrun-input-sonication-sila2.protocol.json']:
            target = ROOT / name

            def changed_bytes(path):
                content = read_bytes(path)
                return content + b'\n' if path == target else content

            with self.subTest(source=name), patch.object(Path, 'read_bytes', changed_bytes):
                with self.assertRaisesRegex(ValueError, re.escape(name)):
                    contract.verify_source_files(pins)

    def test_build_is_deterministic_confined_to_exports_and_makes_no_execution_claim(self):
        with tempfile.TemporaryDirectory(prefix='sonication-generation-', dir=ROOT / 'exports') as folder:
            path = contract.build(folder)
            before = path.read_bytes()
            report_path = Path(folder) / 'generation-report.json'
            before_report = report_path.read_bytes()
            self.assertEqual(contract.build(folder), path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(before_report, report_path.read_bytes())
            report = json.loads(before_report)
            self.assertEqual(report['sha256'], contract.digest(path))
            self.assertIs(report['simulation_only'], True)
            self.assertIs(report['test_fixture_only'], True)
            for name in ['schema_validated', 'network_executed', 'hardware_executed', 'ros2_executed']:
                self.assertIs(report[name], False)
        with self.assertRaisesRegex(ValueError, 'exports'):
            contract.build(ROOT / 'docs/media')
        with tempfile.TemporaryDirectory(prefix='sonication-symlink-', dir=ROOT / 'exports') as folder:
            link = Path(folder) / 'outside'
            link.symlink_to(ROOT / 'docs/media', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'exports'):
                contract.build(link)

    def test_protocol_does_not_change_geometry_gallery_classification(self):
        import render_model_gallery as gallery
        self.assertNotIn(str(contract.SOURCE.relative_to(ROOT)), gallery.expected_model_sources())
        self.assertEqual(gallery.NON_GEOMETRIC_SHARED_FORMATS,
                         {'solidcraftbot.cf01-sila2/1', 'solidcraftbot.dna-sila2/1'})

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'),
                         'Use the pinned requirements/sila2-test.lock environment')
    def test_json_schema_accepts_contract_and_rejects_wire_expansion(self):
        import jsonschema
        schema = json.loads(contract.SCHEMA.read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(self.source())
        changed = self.source()
        changed['commands'][1]['arguments'].append(
            {'name': 'scenario_identifier', 'type': 'string', 'description': 'late mutation'})
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(changed)

    @unittest.skipUnless(importlib.util.find_spec('sila') and importlib.util.find_spec('xmlschema'),
                         'Use the pinned requirements/sila2-test.lock environment')
    def test_exact_generated_fdl_validates_offline_with_pinned_sdk_xsd(self):
        from importlib.resources import files
        import xmlschema
        from sila.server import Feature
        lock = (ROOT / 'requirements/sila2-test.lock').read_text()
        for name in ['unitelabs-sila', 'xmlschema']:
            version = re.search('^' + re.escape(name) + r'==([^\s]+)', lock, re.MULTILINE).group(1)
            self.assertEqual(importlib.metadata.version(name), version)
        with tempfile.TemporaryDirectory(prefix='sonication-xsd-', dir=ROOT / 'exports') as folder:
            target = contract.build(folder)
            source = target.read_text(encoding='utf-8')
            with patch('socket.socket', side_effect=AssertionError('Offline validation opened a socket')):
                xmlschema.XMLSchema(str(files('sila') / 'resources/FeatureDefinition.xsd'),
                                    allow='local').validate(source)
                feature = Feature.from_definition(source)
            self.assertEqual(str(feature.fully_qualified_identifier),
                             'org.solidcraftbot/analytics/CutRunInputSonicationWorkflow/v1')


if __name__ == '__main__':
    unittest.main()
