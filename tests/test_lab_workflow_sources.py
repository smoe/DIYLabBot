"""Shared original identities and pinned synthetic workflow input contracts."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import TaskError, digest
from lab_workflow_sources import (SOURCE, SCHEMA, STAGES, load, validate_manifest,
                                  validate_mass_confirmation, build_cf01_profile)
from cf01_rack_batch import Runner


class IntegratedSourceTests(unittest.TestCase):
    def setUp(self):
        self.definition = load()

    def profile(self):
        return json.loads(SOURCE.read_text())

    def masses(self):
        return {sample['vessel_id']: {
            'confirmation_id': 'SYN.Mass.' + sample['vessel_id'],
            'vessel_id': sample['vessel_id'], 'mass_g': 2.0,
            'content_revision': 0, 'actor_id': 'SYN.Operator01',
            'time_s': 0, 'evidence': 'synthetic_input'}
            for sample in self.definition['manifest']['samples']}

    def revisions(self):
        return {sample['vessel_id']: 0 for sample in self.definition['manifest']['samples']}

    def test_one_manifest_generates_all_twelve_original_stage_inputs(self):
        definition = self.definition
        manifest = definition['manifest']
        self.assertEqual(list(definition['stages']), STAGES)
        self.assertEqual(len(manifest['samples']), 12)
        self.assertEqual(manifest['samples'][2]['vessel_id'], 'Tube03')
        self.assertIsNone(manifest['samples'][2]['initial_volume_ul'])
        self.assertEqual(definition['rack_instance'], 'Rack')
        for name in ['nanodrop', 'qubit']:
            profile = definition['stages'][name]['profile']
            self.assertEqual(profile['rack']['id'], 'Rack')
            self.assertEqual(profile['workspace']['id'], definition['work_area']['id'])
            self.assertEqual([s['id'] for s in profile['samples']], [s['sample_id'] for s in manifest['samples']])
            self.assertEqual([s['vessel_id'] for s in profile['samples']], [s['vessel_id'] for s in manifest['samples']])
            self.assertEqual([s['initial_volume_ul'] for s in profile['samples']], [s['initial_volume_ul'] for s in manifest['samples']])
        self.assertEqual([s['id'] for s in definition['stages']['cf01']['profile']['samples']],
                         [s['sample_id'] for s in manifest['samples']])

    def test_legacy_geometry_places_and_profile_fixtures_remain_unchanged(self):
        before = {name: (ROOT / ('model/' + name + '-manual.synthetic.json')).read_bytes()
                  for name in ['nanodrop', 'qubit-4']}
        definition = load()
        for name, content in before.items():
            profile = json.loads(content)
            self.assertEqual(len(profile['samples']), 3)
            self.assertEqual(profile['rack']['id'], 'SYN.NanoDropRack01')
            self.assertEqual((ROOT / ('model/' + name + '-manual.synthetic.json')).read_bytes(), content)
        for name in ['nanodrop', 'qubit']:
            places = definition['stages'][name]['places']
            self.assertEqual(places[0]['id'], 'CF01.OutputRack.Slot01')
            self.assertEqual(places[0]['place_id'], 'Slot01')
            self.assertEqual(definition['stages'][name]['legacy_bindings']['rack_instance'], 'SYN.NanoDropRack01')

    def test_all_sources_and_runtime_inputs_are_bound_to_current_bytes(self):
        definition = self.definition
        for file, checksum in definition['source_files_sha256'].items():
            self.assertEqual(digest((ROOT / file).read_bytes()), checksum, file)
        self.assertIn('model/synthetic-lab-workflow.manifest.json', definition['source_files_sha256'])
        for file in ['scripts/lab_workflow_sources.py', 'scripts/manual_workflow.py',
                     'scripts/nanodrop_manual.py', 'scripts/qubit_manual.py',
                     'scripts/cf01_rack_batch.py', 'scripts/centrifuge_control.py']:
            self.assertIn(file, definition['runtime_source_files'])
        extended = load(runtime_sources=['scripts/lab_workflow_sources.py'])
        self.assertEqual(extended['runtime_source_files'].count('scripts/lab_workflow_sources.py'), 1)

    def test_compilation_does_not_mutate_the_caller_profile(self):
        profile = self.profile()
        before = copy.deepcopy(profile)
        load(profile)
        self.assertEqual(profile, before)

    def test_duplicate_or_foreign_manifest_identities_and_places_are_rejected(self):
        for field in ['sample_id', 'vessel_id', 'rack_place_id']:
            manifest = copy.deepcopy(self.definition['manifest'])
            manifest['samples'][1][field] = manifest['samples'][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(TaskError, 'Duplicate'):
                validate_manifest(manifest, 'Rack', self.definition['rack_places'])
        for defect in ['count', 'rack', 'place', 'volume']:
            manifest = copy.deepcopy(self.definition['manifest'])
            if defect == 'count':
                manifest['samples'].pop()
            elif defect == 'rack':
                manifest['rack_instance'] = 'A different rack'
            elif defect == 'place':
                manifest['samples'][0]['rack_place_id'] = 'CF01.OutputRack.Slot01'
            else:
                manifest['samples'][0]['initial_volume_ul'] = -1
            with self.subTest(defect=defect), self.assertRaises(TaskError):
                validate_manifest(manifest, 'Rack', self.definition['rack_places'])

    def test_foreign_rack_and_work_area_bindings_are_rejected(self):
        for defect in ['rack', 'arm', 'station', 'area', 'frame']:
            profile = self.profile()
            if defect in ['rack', 'arm', 'station']:
                profile['bindings'][defect + '_instance'] = 'Unknown'
            elif defect == 'area':
                profile['bindings']['work_area']['id'] = 'Another logical area'
            else:
                profile['bindings']['work_area']['frame'] = 'Unknown frame'
            with self.subTest(defect=defect), self.assertRaises(TaskError):
                load(profile)

    def test_source_hash_changes_and_missing_pins_are_rejected(self):
        for defect in ['hash', 'missing', 'outside']:
            profile = self.profile()
            if defect == 'hash':
                profile['manifest']['source_sha256'] = '0' * 64
            elif defect == 'missing':
                del profile['stage_profiles']['qubit']['source_sha256']
            else:
                profile['manifest']['source'] = '../outside.json'
            with self.subTest(defect=defect), self.assertRaises(TaskError):
                load(profile)

    def test_external_profile_file_cannot_escape_the_source_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            external = Path(folder) / 'workflow.json'
            external.write_text(json.dumps(self.profile()))
            with self.assertRaisesRegex(TaskError, 'remain in the project'):
                load(external)

    def test_clock_and_deadline_contract_are_declared_before_initialization(self):
        self.assertEqual(self.definition['profile']['clock_mode'], 'synthetic_events/1')
        for field, value in [('clock_mode', 'wall_clock'), ('task_deadline_s', True),
                             ('task_deadline_s', float('nan')), ('task_deadline_s', 1),
                             ('stage_order', ['qubit', 'cf01', 'nanodrop'])]:
            profile = self.profile()
            profile[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(TaskError):
                load(profile)

    def test_qubit_chamber_is_an_explicit_measurement_role_not_an_extra_holder(self):
        roles = self.definition['qubit_places']
        self.assertEqual(sum(p['role'] == 'holder_slot' for p in roles), 12)
        chamber, = [p for p in roles if p['role'] == 'measurement_chamber']
        self.assertEqual(chamber['holder_id'], self.definition['stages']['qubit']['profile']['instrument']['id'])
        for defect in ['chamber_as_holder', 'holder_as_chamber', 'missing', 'duplicate', 'unknown_role']:
            profile = self.profile()
            values = profile['qubit_place_roles']
            if defect == 'chamber_as_holder':
                values[-1]['role'] = 'holder_slot'
            elif defect == 'holder_as_chamber':
                values[0]['role'] = 'measurement_chamber'
            elif defect == 'missing':
                values.pop()
            elif defect == 'duplicate':
                values.append(copy.deepcopy(values[0]))
            else:
                values[0]['role'] = 'unspecified'
            with self.subTest(defect=defect), self.assertRaises(TaskError):
                load(profile)

    def test_cf01_input_cannot_run_without_runtime_mass_confirmations(self):
        profile = self.definition['stages']['cf01']['profile']
        self.assertTrue(all(s['mass_g'] is None for s in profile['samples']))
        with self.assertRaises(ValueError):
            Runner(profile)
        with self.assertRaises(TaskError):
            build_cf01_profile(self.definition, {}, self.revisions())

    def test_current_synthetic_mass_confirmations_derive_a_valid_cf01_input(self):
        masses = self.masses()
        profile = build_cf01_profile(self.definition, masses, self.revisions(), now_s=0)
        self.assertTrue(all(s['mass_g'] == 2 for s in profile['samples']))
        self.assertTrue(Runner(profile).run()['passed'])
        self.assertTrue(all(s['mass_g'] is None for s in self.definition['stages']['cf01']['profile']['samples']))
        self.assertEqual(profile['mock_assumptions']['mass_source'], 'fictitious_profile')

    def test_mass_confirmation_identity_revision_time_and_uniqueness_are_checked(self):
        for defect in ['vessel', 'revision', 'future', 'duplicate', 'evidence', 'nonfinite', 'boolean_revision']:
            masses = self.masses()
            record = masses['Tube01']
            if defect == 'vessel':
                record['vessel_id'] = 'Tube02'
            elif defect == 'revision':
                record['content_revision'] = 1
            elif defect == 'future':
                record['time_s'] = 1
            elif defect == 'duplicate':
                record['confirmation_id'] = masses['Tube02']['confirmation_id']
            elif defect == 'evidence':
                record['evidence'] = 'hardware_scale'
            elif defect == 'nonfinite':
                record['mass_g'] = float('inf')
            else:
                record['content_revision'] = True
            with self.subTest(defect=defect), self.assertRaises(TaskError):
                build_cf01_profile(self.definition, masses, self.revisions(), now_s=0)

    def test_mass_confirmation_validation_returns_an_independent_record(self):
        original = self.masses()['Tube01']
        checked = validate_mass_confirmation(original)
        checked['mass_g'] = 5
        self.assertEqual(original['mass_g'], 2)

    def test_schema_is_json_and_declares_all_three_new_contracts(self):
        schema = json.loads(SCHEMA.read_text())
        self.assertEqual(schema['properties']['format']['const'], self.definition['format'])
        self.assertEqual(schema['$defs']['manifest']['properties']['format']['const'],
                         self.definition['manifest']['format'])
        self.assertEqual(schema['$defs']['mass_confirmation']['properties']['evidence']['const'], 'synthetic_input')
        self.assertFalse(schema['additionalProperties'])


if __name__ == '__main__':
    unittest.main()
