"""Reference-only T3 contract and private CLI bootstrap checks."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lab_transport_network_sources import SOURCE, PROTOCOL, SCHEMA, RUNTIME, DEFINITION_FORMAT, load, load_contract
from lab_transport_sources import load as load_t2
from manual_tasks import TaskError, digest


class NetworkSourceTests(unittest.TestCase):
    def profile(self): return json.loads(SOURCE.read_bytes())

    def test_only_interface_metadata_is_added_to_the_existing_t2_composition(self):
        before = load_t2(); after = load()
        self.assertEqual(after['format'], DEFINITION_FORMAT)
        for key in ['manifest', 'stages', 'transport', 'workspace', 'rack_places', 'rack_instance', 'work_area']:
            self.assertEqual(before[key], after[key], key)
        self.assertFalse({'inventory', 'samples', 'initial_materials', 'initial_vessels'} & set(self.profile()))
        self.assertEqual(after['network_interface']['contract']['paths'], load_contract()['paths'])

    def test_compilation_and_source_pins_do_not_mutate_or_reset_inputs(self):
        profile = self.profile(); original = copy.deepcopy(profile)
        definition = load(profile)
        self.assertEqual(profile, original)
        for name, sha in definition['source_files_sha256'].items():
            self.assertEqual(digest((ROOT / name).read_bytes()), sha, name)
        for name in [*RUNTIME, str(PROTOCOL.relative_to(ROOT)), str(SCHEMA.relative_to(ROOT)),
                     'model/synthetic-lab-workflow.transport.schema.json',
                     'model/async-lab-transport.schema.json']:
            self.assertIn(name, definition['source_files_sha256'])
        self.assertNotEqual(definition['effective_profile_sha256'], load_t2()['effective_profile_sha256'])

    def test_wrong_contract_versions_pins_and_inventory_fields_are_rejected(self):
        changes = [lambda p: p.update(format='solidcraftbot.lab-transport-network/2'),
                   lambda p: p.update(mode='physical'),
                   lambda p: p.update(inventory={}),
                   lambda p: p['workflow'].update(source_sha256='0' * 64),
                   lambda p: p['interface_protocol'].update(source_sha256='0' * 64)]
        for change in changes:
            profile = self.profile(); change(profile)
            with self.subTest(change=change), self.assertRaises(TaskError): load(profile)

    def test_t2_entry_point_rejects_the_network_composition(self):
        with self.assertRaises(TaskError): load_t2(SOURCE)
        with self.assertRaises(TaskError): load(ROOT / 'model/synthetic-lab-workflow.transport.json')

    def test_formal_profile_and_request_schemas_share_existing_identity_forms(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('jsonschema and referencing required for formal validation')
        schema = json.loads(SCHEMA.read_bytes())
        Draft202012Validator.check_schema(schema)
        registry = Registry().with_resources((name, Resource.from_contents(json.loads((ROOT / 'model' / name).read_bytes())))
            for name in ['synthetic-lab-workflow.schema.json', 'async-lab-transport.schema.json'])
        Draft202012Validator(schema, registry=registry).validate(self.profile())
        def validator(name):
            selected = {key: value for key, value in schema.items() if key != '$ref'}
            selected['$ref'] = '#/$defs/' + name
            return Draft202012Validator(selected, registry=registry)
        request = {'request_id': 'SYN.Request', 'grant_id': 'Grant01', 'operation': 'attest',
                   'args': {'job_id': 'Job01', 'role': 'pickup_accept', 'observation_id': 'Observation01',
                            'assignment_epoch': 2, 'handover_id': 'Handover01',
                            'manifest_sha256': '0' * 64, 'observed_rack_id': 'Rack', 'confirmed': True}}
        validator('request').validate(request)
        for mutation in ('principal', 'false_confirmation', 'epoch_bool'):
            bad = copy.deepcopy(request)
            if mutation == 'principal': bad['principal'] = 'SYN.Owner'
            elif mutation == 'false_confirmation': bad['args']['confirmed'] = False
            else: bad['args']['assignment_epoch'] = True
            self.assertTrue(list(validator('request').iter_errors(bad)), mutation)
        validator('login').validate({'username': 'Local Person', 'password': 'synthetic-password',
                                     'server_uuid': 'SYN.Server'})


class NetworkBootstrapTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='courier-cli-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'private'

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/run_lab_transport_network.py'),
                               '--directory', str(self.directory), *args], cwd=ROOT,
                              text=True, capture_output=True)

    def test_initialization_has_no_default_passwords_or_secret_output_and_never_resets(self):
        result = self.cli('init', '--run-id', 'SYN.T3.Bootstrap')
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertFalse(summary['synthetic_cf01_boundary_prepared'])
        self.assertFalse(summary['network_executed'])
        bootstrap = json.loads((self.directory / 'bootstrap.json').read_text())
        users = json.loads((self.directory / 'users.json').read_text())
        self.assertEqual(len(bootstrap['accounts']), len(users['users']))
        self.assertEqual(len({item['password'] for item in bootstrap['accounts']}), len(bootstrap['accounts']))
        for item in bootstrap['accounts']:
            self.assertGreaterEqual(len(item['password']), 24)
            self.assertNotIn(item['password'], result.stdout + result.stderr)
            self.assertNotIn(item['password'], (self.directory / 'users.json').read_text())
        original = (self.directory / 'service.json').read_bytes()
        second = self.cli('init', '--run-id', 'SYN.T3.Bootstrap')
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((self.directory / 'service.json').read_bytes(), original)
        if os.name != 'nt':
            for name in ['service.json', 'users.json', 'bootstrap.json', 'tls/server.key']:
                self.assertEqual(stat.S_IMODE((self.directory / name).stat().st_mode), 0o600, name)


if __name__ == '__main__':
    unittest.main()
