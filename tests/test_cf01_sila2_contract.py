"""The network v2 contract is derived without changing historical/local inputs."""
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
import build_cf01_sila2 as contract


class SiLAContractTests(unittest.TestCase):
    def setUp(self):
        self.data = contract.load()
        self.root = ET.fromstring(contract.feature(self.data))

    def test_network_version_and_standard_metadata_do_not_rewrite_local_contract(self):
        self.assertEqual(self.root.get('FeatureVersion'), '2.0')
        self.assertEqual(self.root.get('SiLA2Version'), '1.1')
        self.assertEqual(len(self.root.findall(contract.Q('Command'))), 13)
        identifiers = [n.text for n in self.root.iter(contract.Q('Identifier'))]
        self.assertNotIn('ControlToken', identifiers)
        self.assertNotIn('AcquireControl', identifiers)
        self.assertIn('RequestIdentifier', identifiers)
        self.assertEqual(self.data[1]['protocol']['transport']['feature_version'], '1.0')

    def test_status_errors_and_command_specific_domain_errors(self):
        commands = {c.findtext(contract.Q('Identifier')): c for c in self.root.findall(contract.Q('Command'))}
        self.assertIsNone(commands['GetStatus'].find(contract.Q('DefinedExecutionErrors')))
        close = commands['CloseLid'].find(contract.Q('DefinedExecutionErrors'))
        self.assertIn('LidObstructed', [n.text for n in close])
        index = commands['IndexRotor'].find(contract.Q('DefinedExecutionErrors'))
        self.assertNotIn('LidObstructed', [n.text for n in index])

    def test_units_ranges_and_rotor_capacity_follow_shared_source(self):
        profile, sources, commands = copy.deepcopy(self.data)
        sources['station']['rotor']['slots'] = 8
        root = ET.fromstring(contract.feature((profile, sources, commands)))
        index = next(c for c in root.findall(contract.Q('Command')) if c.findtext(contract.Q('Identifier')) == 'IndexRotor')
        self.assertEqual(index.findtext('.//' + contract.Q('MaximalInclusive')), '8')
        labels = [n.text for n in root.iter(contract.Q('Label'))]
        self.assertEqual(set(labels), {'g', 's', 'x g'})
        self.assertIn('Dimensionless', [n.text for n in root.iter(contract.Q('SIUnit'))])

    def test_source_pin_drift_and_missing_error_contract_are_rejected(self):
        profile = copy.deepcopy(self.data[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            for source in ['protocol', 'network_batch']:
                with self.subTest(source=source):
                    profile = copy.deepcopy(self.data[0])
                    profile[source]['source_sha256'] = '0' * 64
                    path.write_text(json.dumps(profile))
                    with self.assertRaisesRegex(ValueError, 'Changed shared source'):
                        contract.load(path)
            profile = copy.deepcopy(self.data[0])
            del profile['command_errors']['status']
            path.write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, 'Every network command'):
                contract.load(path)

    @unittest.skipUnless(importlib.util.find_spec('sila') and importlib.util.find_spec('xmlschema'), 'Install requirements/sila2-test.in')
    def test_generated_fdl_passes_sdk_and_official_schema(self):
        import xmlschema
        from importlib.resources import files
        from sila.server import Feature
        text = contract.feature(self.data)
        xmlschema.XMLSchema(str(files('sila') / 'resources/FeatureDefinition.xsd')).validate(text)
        feature = Feature.from_definition(text)
        self.assertEqual(str(feature.fully_qualified_identifier), 'org.solidcraftbot/centrifugation/CentrifugeControl/v2')
        observation = contract.simulation_feature(self.data)
        xmlschema.XMLSchema(str(files('sila') / 'resources/FeatureDefinition.xsd')).validate(observation)
        self.assertEqual(str(Feature.from_definition(observation).fully_qualified_identifier),
                         'org.solidcraftbot/centrifugation/SyntheticRobotObservation/v1')


if __name__ == '__main__':
    unittest.main()
