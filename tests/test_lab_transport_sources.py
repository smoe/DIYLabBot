"""Reference-only opt-in topology and schema, without another sample inventory."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lab_transport_sources import SOURCE, SCHEMA, FORMAT, RUNTIME, load
from lab_workflow_sources import load as load_base
from manual_tasks import TaskError, digest


class LabTransportSourceTests(unittest.TestCase):
    def profile(self):
        return json.loads(SOURCE.read_bytes())

    def test_existing_manifest_stages_and_geometry_are_referenced_once(self):
        base = load_base()
        definition = load()
        self.assertEqual(definition['format'], FORMAT)
        for field in ('manifest', 'rack_instance', 'workspace', 'rack_places', 'stages', 'work_area'):
            self.assertEqual(definition[field], base[field], field)
        topology = definition['transport']['topology']
        self.assertEqual(topology['racks'], [{'id': 'Rack', 'initial_endpoint': 'LabA.CF01', 'closed': True}])
        self.assertEqual(len(definition['manifest']['samples']), 12)
        self.assertIsNone(definition['manifest']['samples'][2]['initial_volume_ul'])
        for field in ('samples', 'initial_materials', 'initial_vessels', 'inventory', 'quantities'):
            self.assertNotIn(field, self.profile())
            self.assertNotIn(field, topology)

    def test_compilation_does_not_mutate_the_reference_profile(self):
        profile = self.profile(); original = copy.deepcopy(profile)
        load(profile)
        self.assertEqual(profile, original)

    def test_all_new_and_existing_dependencies_are_pinned(self):
        definition = load()
        for name, expected in definition['source_files_sha256'].items():
            self.assertEqual(digest((ROOT / name).read_bytes()), expected, name)
        for name in [*RUNTIME, str(SOURCE.relative_to(ROOT)), str(SCHEMA.relative_to(ROOT)),
                     'model/synthetic-lab-workflow.manifest.json', 'model/async-lab-transport.protocol.json',
                     'model/async-lab-transport.schema.json']:
            self.assertIn(name, definition['source_files_sha256'])
        self.assertNotEqual(definition['effective_profile_sha256'], load_base()['effective_profile_sha256'])

    def test_foreign_versions_inventory_fields_and_source_pins_are_rejected(self):
        defects = [lambda p: p.update(format='solidcraftbot.synthetic-lab-transport-workflow/3'),
                   lambda p: p.update(mode='hardware'),
                   lambda p: p.update(initial_vessels=[]),
                   lambda p: p['transport_protocol'].update(source_sha256='0' * 64),
                   lambda p: p['workflow'].update(source_sha256='0' * 64)]
        for change in defects:
            with self.subTest(change=change):
                profile = self.profile(); change(profile)
                with self.assertRaises(TaskError): load(profile)

    def test_wrong_stage_order_route_aliases_and_unknown_resources_are_rejected(self):
        defects = [lambda p: p['routes'][0].update(target_stage='qubit'),
                   lambda p: p['routes'][1].update(id=p['routes'][0]['id']),
                   lambda p: p['routes'][1].update(source_endpoint='LabA.CF01'),
                   lambda p: p['routes'][0].update(agent_id='Unknown'),
                   lambda p: p['routes'][0].update(target_endpoint='Unknown'),
                   lambda p: p.update(rack_initial_endpoint='Unknown'),
                   lambda p: p['endpoints'][1].update({k: p['endpoints'][0][k]
                       for k in ('site_id', 'lab_id', 'holder_id', 'place_id')})]
        for change in defects:
            with self.subTest(change=change):
                profile = self.profile(); change(profile)
                with self.assertRaises(TaskError): load(profile)

    def test_new_and_old_compositions_require_explicit_entry_points(self):
        with self.assertRaises(TaskError): load_base(SOURCE)
        with self.assertRaises(TaskError): load(ROOT / 'model/synthetic-lab-workflow.shared.json')

    def test_schema_reuses_existing_endpoint_agent_and_reference_contracts(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('jsonschema and referencing required for formal schema validation')
        schema = json.loads(SCHEMA.read_bytes())
        Draft202012Validator.check_schema(schema)
        resources = []
        for name in ('synthetic-lab-workflow.schema.json', 'async-lab-transport.schema.json'):
            body = json.loads((ROOT / 'model' / name).read_bytes())
            resources.append((name, Resource.from_contents(body)))
        validator = Draft202012Validator(schema, registry=Registry().with_resources(resources))
        validator.validate(self.profile())
        bad = self.profile(); bad['agents'][0]['kind'] = 'teleporter_hardware'
        self.assertTrue(list(validator.iter_errors(bad)))


class LabTransportCLITests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='lab-transport-cli-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = self.folder / 'journal.sqlite3'

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_lab_transport_workflow.py'),
                                 '--store', str(self.store), *args], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return result

    def test_create_status_report_and_report_preservation_use_the_new_root(self):
        created = json.loads(self.cli('create', '--run-id', 'SYN.T2.CLI').stdout)
        self.assertIn('transport', created)
        status = json.loads(self.cli('status', 'SYN.T2.CLI').stdout)
        self.assertEqual(status['transport']['run_id'], 'SYN.T2.CLI')
        report = self.folder / 'report.json'
        self.cli('report', 'SYN.T2.CLI', '--out', str(report))
        original = report.read_bytes()
        self.assertFalse(json.loads(original)['passed'])
        self.cli('report', 'SYN.T2.CLI', '--out', str(report), success=False)
        self.assertEqual(report.read_bytes(), original)

    def test_writing_session_needs_explicit_resume(self):
        self.cli('create', '--run-id', 'SYN.T2.CLI')
        denied = self.cli('session', 'SYN.T2.CLI', success=False)
        self.assertIn('--resume', denied.stderr)


if __name__ == '__main__':
    unittest.main()
