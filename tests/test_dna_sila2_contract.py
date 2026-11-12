"""The additive DNA network FDL derives from pinned synthetic sources only."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_dna_quantification_sila2 as contract


class DNAContractTests(unittest.TestCase):
    def test_complete_command_parameters_derive_from_source_and_exclude_pause_injection(self):
        data = contract.load()
        root = ET.fromstring(contract.feature(data))
        self.assertEqual(root.findtext(contract.Q('Identifier')), 'DnaQuantificationWorkflow')
        self.assertEqual(root.get('FeatureVersion'), '1.0')
        commands = {node.findtext(contract.Q('Identifier')): node for node in root.findall(contract.Q('Command'))}
        self.assertEqual(set(commands), contract.COMMANDS)
        for source in data['commands']:
            node = commands[source['name']]
            fields = {parameter.findtext(contract.Q('Identifier')) for parameter in node.findall(contract.Q('Parameter'))}
            self.assertEqual(fields, {contract.camel(field['name']) for field in source['arguments']})
            self.assertIn('RequestIdentifier', fields)
            self.assertIn('RunIdentifier', fields)
            self.assertNotIn('PauseAfter', fields)
            self.assertEqual(node.findtext(contract.Q('Observable')), 'Yes' if source['observable'] else 'No')
        self.assertEqual({node.findtext(contract.Q('Identifier')) for node in root.findall(contract.Q('Property'))}, {'Status', 'Report'})
        self.assertIn('No hardware or ROS runtime', root.findtext(contract.Q('Description')))

    def test_profile_protocol_task_and_runtime_pins_are_all_present(self):
        data = contract.load()
        for name in ['dna_profile', 'dna_protocol', 'task_contract']:
            ref = data[name]
            self.assertEqual(ref['source_sha256'], contract.digest(ROOT / ref['source']))
            self.assertEqual(data['source_files_sha256'][ref['source']], ref['source_sha256'])
        for filename in ['scripts/dna_sila2_runtime.py', 'scripts/dna_sila2_server.py',
                         'scripts/dna_quantification.py', 'scripts/manual_tasks.py',
                         'scripts/dna_quantification_tasks.py', 'scripts/dna_quantification_execution.py',
                         'scripts/cf01_sila2_auth.py', 'scripts/cf01_sila2_client.py']:
            with self.subTest(source=filename):
                self.assertIn(filename, data['source_files_sha256'])
                self.assertEqual(data['source_files_sha256'][filename], contract.digest(ROOT / filename))

    def test_source_pin_drift_is_rejected_without_rewriting_historical_sources(self):
        data = json.loads(contract.SOURCE.read_text(encoding='utf-8'))
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-sila-contract-', dir=ROOT / 'exports') as folder:
            path = Path(folder) / 'profile.json'
            for name in ['dna_profile', 'dna_protocol', 'task_contract']:
                changed = copy.deepcopy(data)
                changed[name]['source_sha256'] = '0' * 64
                path.write_text(json.dumps(changed), encoding='utf-8')
                with self.subTest(source=name), self.assertRaisesRegex(ValueError, 'Changed DNA SiLA source'):
                    contract.load(path)
            changed = copy.deepcopy(data)
            changed['standard_features'][1]['source_sha256'] = '0' * 64
            path.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Changed standard feature'):
                contract.load(path)

    def test_lock_v1_and_archived_feature_bytes_are_retained(self):
        data = contract.load()
        lock = next(ref for ref in data['standard_features'] if ref['identifier'] == 'LockController')
        self.assertTrue(lock['source'].endswith('LockController-v1_0.sila.xml'))
        for ref in data['standard_features']:
            self.assertEqual(contract.digest(ROOT / ref['source']), ref['source_sha256'])

    def test_generation_is_confined_to_ignored_runtime_and_makes_no_execution_claim(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='dna-sila-generation-', dir=ROOT / 'exports') as folder:
            path = contract.build(Path(folder))
            report = json.loads((Path(folder) / 'generation-report.json').read_text())
            self.assertEqual(report['sha256'], contract.digest(path))
            for key in ['network_executed', 'hardware_executed', 'ros2_executed', 'schema_validated']:
                self.assertIs(report[key], False)
        with self.assertRaisesRegex(ValueError, 'exports'):
            contract.build(ROOT / 'docs/media')

    @unittest.skipUnless(importlib.util.find_spec('sila') and importlib.util.find_spec('xmlschema'),
                         'Install the pinned requirements/sila2-test.lock environment')
    def test_official_xsd_and_sdk_accept_generated_feature(self):
        import xmlschema
        from importlib.resources import files
        from sila.server import Feature
        source = contract.feature()
        xmlschema.XMLSchema(str(files('sila') / 'resources/FeatureDefinition.xsd')).validate(source)
        feature = Feature.from_definition(source)
        self.assertEqual(str(feature.fully_qualified_identifier), 'org.solidcraftbot/analytics/DnaQuantificationWorkflow/v1')


if __name__ == '__main__':
    unittest.main()
