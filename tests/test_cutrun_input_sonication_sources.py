"""Fixture composition must preserve real blockers and the genuine pin guards."""
import copy
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cutrun_input_sonication_sources as sources
from manual_tasks import TaskError, digest

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


class InputSonicationSourceTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(sources.SOURCE.read_bytes())

    def test_default_preserves_real_open_requirements_and_disabled_sonication(self):
        result = sources.compile_profile()
        self.assertFalse(result['runtime_profile']['enabled'])
        self.assertTrue(result['test_fixture_only'])
        self.assertFalse(result['original_pdf_verified'])
        self.assertFalse(result['preparation_complete'])
        self.assertFalse(result['can_claim_reference_success'])
        self.assertEqual(result['open_requirements'], result['raw_open_requirements'])
        self.assertIn('manufacturer_original', {item['id'] for item in result['raw_open_requirements']})
        self.assertTrue(all(value is False for value in result['real_stage_readiness'].values()))
        self.assertFalse(result['synthetic_gate_readiness']['S09'])
        self.assertTrue(all(item['value'] is None for item in result['sonication_plan']['parameters'].values()))

    def test_source_graph_covers_all_new_runtime_and_transitive_model_sources(self):
        result = sources.compile_profile()
        expected = set(sources.RUNTIME) | set(sources.REFS.values())
        self.assertLessEqual(expected, set(result['runtime_source_files']))
        self.assertLessEqual(set(result['sonication_plan']['source_files_sha256']),
                             set(result['runtime_source_files']))
        for name in result['runtime_source_files']:
            with self.subTest(source=name):
                content = (ROOT / name).read_bytes()
                checksum = digest(content)
                self.assertEqual(result['source_files_sha256'][name], checksum)
                self.assertEqual(result['evidence_artifacts'][checksum], content)

    def test_invalid_scope_mode_bindings_and_unknown_fields_are_rejected(self):
        changes = [('mode', 'manual_observation'), ('enabled', 1), ('scope', {'stage_id': 'S07'})]
        for field, value in changes:
            profile = copy.deepcopy(self.profile);profile[field] = value
            with self.subTest(field=field), self.assertRaises(TaskError):
                sources.compile_profile({'runtime_profile': profile})
        for field, value in [('vessel_class', 'tube_2ml'), ('sonicator_place_id', ''),
                             ('input_reaction_id', '')]:
            profile = copy.deepcopy(self.profile);profile['bindings'][field] = value
            with self.subTest(binding=field), self.assertRaises(TaskError):
                sources.compile_profile({'runtime_profile': profile})
        profile = copy.deepcopy(self.profile);profile['execution_ready'] = True
        with self.assertRaises(TaskError):
            sources.compile_profile({'runtime_profile': profile})

    def test_real_clock_and_manufacturer_pdf_substitute_are_rejected_before_load(self):
        with self.assertRaisesRegex(TaskError, 'test clock'):
            sources.load(materials=[], vessels=[], clock_source_kind='system_clock')
        with self.assertRaisesRegex(TaskError, 'manufacturer PDF'):
            sources.compile_profile(original_pdf=ROOT / 'does-not-exist.pdf')

    def test_wrong_source_pin_or_redirect_is_rejected(self):
        profile = copy.deepcopy(self.profile)
        profile['sources']['sop_profile']['source_sha256'] = '0' * 64
        with self.assertRaises(TaskError):
            sources.compile_profile({'runtime_profile': profile})
        profile = copy.deepcopy(self.profile)
        profile['sources']['sonication_profile']['source'] = 'model/dna-quantification.synthetic.json'
        with self.assertRaisesRegex(TaskError, 'Unsupported fixture source reference'):
            sources.compile_profile({'runtime_profile': profile})

    def test_reused_helper_byte_drift_is_detected_by_final_guard_without_writing_it(self):
        name = 'scripts/cutrun_input_sonication_workflow.py'
        path = (ROOT / name).resolve();original = Path.read_bytes
        content = original(path);calls = []

        def drift(file):
            result = original(file)
            if file.resolve() == path:
                calls.append(file)
                if len(calls) >= 2:
                    return result + b'\n'
            return result

        with patch.object(Path, 'read_bytes', drift):
            with self.assertRaisesRegex(TaskError, 'Input sonication source changed: ' + name):
                sources.compile_profile()
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(original(path), content)

    def test_compilation_has_no_database_network_subprocess_or_source_write(self):
        before = sources.SOURCE.read_bytes()
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('database effect')), \
             patch.object(socket, 'socket', side_effect=AssertionError('network effect')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('subprocess effect')), \
             patch.object(Path, 'write_bytes', side_effect=AssertionError('file effect')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('file effect')):
            result = sources.compile_profile()
        self.assertFalse(result['can_claim_reference_success'])
        self.assertEqual(sources.SOURCE.read_bytes(), before)

    def test_independent_results_and_effective_override_digest(self):
        first = sources.compile_profile()
        first['runtime_profile']['bindings']['sonicator_place_id'] = 'Changed'
        second = sources.compile_profile()
        self.assertEqual(second['runtime_profile']['bindings']['sonicator_place_id'], 'V01')
        profile = copy.deepcopy(self.profile);profile['id'] += '.ExplicitOverride'
        third = sources.compile_profile({'runtime_profile': profile})
        self.assertNotEqual(second['effective_profile_sha256'], third['effective_profile_sha256'])

    def test_private_override_original_bytes_and_effective_values_are_both_preserved(self):
        profile = copy.deepcopy(self.profile);profile['id'] += '.PrivateOriginal'
        sonic = json.loads((ROOT / sources.REFS['sonication_profile']).read_bytes())
        sonic['id'] += '.PrivateOriginal'
        originals = {'runtime_profile': b'\n \n' + json.dumps(profile, indent=3).encode() + b'\n',
                     'sonication_source': b' \n' + json.dumps(sonic, indent=4).encode() + b'\n\n'}
        with tempfile.TemporaryDirectory(prefix='private-sonication-source-') as directory:
            paths = {}
            for name, content in originals.items():
                path = Path(directory) / (name + '.json');path.write_bytes(content);paths[name] = path
            result = sources.compile_profile(paths)
            expected = {'runtime_profile_sha256': 'runtime_profile',
                        'sonication_profile_sha256': 'sonication_source'}
            for label, name in expected.items():
                checksum = result['fixture_source_artifacts'][label]
                self.assertEqual(checksum, digest(originals[name]))
                self.assertEqual(result['evidence_artifacts'][checksum], originals[name])
                self.assertEqual(paths[name].read_bytes(), originals[name])
            self.assertEqual(result['runtime_profile']['id'], profile['id'])
            self.assertEqual(result['sonication_plan']['id'], sonic['id'])

    @staticmethod
    def fixture_source():
        # Reuse the product's explicitly fictitious source builder without
        # constructing a journal or inventing another recipe in this test.
        from cutrun_input_sonication_demo import FixtureSession, fixture_values
        fixture = FixtureSession.__new__(FixtureSession)
        fixture.fixture = fixture_values()
        fixture.prefix = 'Test.SourceFixture'
        fixture.actor = fixture.fixture['actor_id']
        fixture.reaction_id = fixture.prefix + '.Reaction.Input'
        fixture.device_id = fixture.prefix + '.Sonicator'
        fixture.time_basis = 'Test.SourceFixture.Clock'
        return fixture._source()

    @staticmethod
    def compile_fixture(source):
        return sources.compile_profile(source, evidence_files={
            'decision_evidence': ROOT / 'model/cutrun-input-sonication.fixture.json'})

    def test_s09_temperature_contract_cannot_exceed_the_sonication_limit(self):
        source = self.fixture_source()
        good = self.compile_fixture(source)
        self.assertTrue(good['synthetic_gate_readiness']['S09'])
        self.assertFalse(good['real_stage_readiness']['S09'])
        source['manual_source']['sop_profile']['phase_requirements']['S09.input_preparation'].update(
            temperature_min_deg_c=15, temperature_max_deg_c=25)
        self.assertEqual(source['sonication_source']['parameters']['temperature_limit_deg_c']['value'], 8)
        with self.assertRaisesRegex(TaskError, 'S09 temperature bound exceeds the declared sonication limit'):
            self.compile_fixture(source)

    def test_temperature_limit_boundary_is_explicit_and_unknowns_do_not_become_defaults(self):
        source = self.fixture_source()
        source['manual_source']['sop_profile']['phase_requirements']['S09.input_preparation']['temperature_max_deg_c'] = 8
        self.assertTrue(self.compile_fixture(source)['synthetic_gate_readiness']['S09'])
        for missing in ('sop_limit', 'sonication_limit'):
            altered = copy.deepcopy(source)
            if missing == 'sop_limit':
                altered['manual_source']['sop_profile']['phase_requirements']['S09.input_preparation']['temperature_max_deg_c'] = None
            else:
                altered['sonication_source']['parameters']['temperature_limit_deg_c'].update(
                    value=None, basis='unknown', source_refs=[])
            with self.subTest(missing=missing):
                self.assertFalse(self.compile_fixture(altered)['synthetic_gate_readiness']['S09'])

    @unittest.skipIf(Draft202012Validator is None, 'jsonschema is unavailable')
    def test_schema_and_default_source_validate(self):
        schema = json.loads((ROOT / sources.SCHEMA).read_bytes())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(self.profile)
        profile = copy.deepcopy(self.profile);profile['enabled'] = 1
        self.assertTrue(list(validator.iter_errors(profile)))


if __name__ == '__main__':
    unittest.main()
