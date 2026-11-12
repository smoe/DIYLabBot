"""Input-only sonication planning; fixtures never qualify a laboratory recipe."""
import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import dna_sonication as sonication
import prepare_dna_sonication as cli
from manual_tasks import TaskError, digest

try:
    import jsonschema
except ImportError:
    jsonschema = None


class SonicationTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(sonication.SOURCE.read_bytes())
        self.protocol = json.loads((ROOT / self.profile['protocol']['source']).read_bytes())
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-sonication-test-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def complete(self):
        profile = copy.deepcopy(self.profile)
        values = {'cycles': 3, 'pulse_on_s': 7, 'between_pulses_s': 2, 'amplitude_percent': 30,
            'device_instance_id': 'SYN.Sonicator', 'firmware_revision': 'test-only-0',
            'vessel_article': 'Synthetic test tube', 'nominal_vessel_volume_ml': 1.5,
            'fill_volume_ul': 300, 'closed_vessel_fit_evidence_ref': 'SYN.Fit',
            'cooling_method': 'Synthetic cooling assumption', 'amplitude_evidence_ref': 'SYN.Amplitude',
            'temperature_reference_vessel_id': 'SYN.ReferenceTube',
            'temperature_mapping_evidence_ref': 'SYN.TemperatureMapping', 'temperature_limit_deg_c': 8,
            'empirical_protocol_evidence_ref': 'SYN.Empirical', 'input_size_evidence_ref': 'SYN.Size'}
        for name, value in values.items():
            profile['parameters'][name].update(value=value, basis='synthetic_assumption',
                source_refs=['hielscher_temperature'], note='Explicit test fixture assumption; no measured evidence.')
        return profile

    @contextlib.contextmanager
    def repinned_protocol(self, protocol):
        # A real isolated model/ tree preserves the production path and pin
        # validator. Only temporary fixture bytes are changed and re-pinned.
        for name in sonication.compile_plan()['source_files_sha256']:
            target = self.directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        path = self.directory / self.profile['protocol']['source']
        path.write_text(json.dumps(protocol, allow_nan=False))
        profile = copy.deepcopy(self.profile)
        profile['protocol']['source_sha256'] = digest(path.read_bytes())
        with patch.object(sonication, 'ROOT', self.directory), \
             patch.object(sonication.preparation, 'ROOT', self.directory):
            yield profile

    def call_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_default_remains_open_and_does_not_inherit_e1_pulses(self):
        plan = sonication.compile_plan()
        self.assertFalse(plan['planning_complete'])
        self.assertFalse(plan['execution_ready'])
        self.assertFalse(plan['local_qualification'])
        self.assertEqual(len(plan['open_requirements']), 17)
        self.assertTrue(all(item['value'] is None for item in plan['parameters'].values()))
        self.assertIsNone(plan['pulse_plan']['cycles'])
        self.assertIsNone(plan['pulse_plan']['total_on_s'])
        self.assertIsNone(plan['pulse_plan']['nominal_elapsed_s'])
        self.assertFalse(any(plan['effects'].values()))

    def test_links_original_input_identities_and_excludes_both_enriched_branches(self):
        plan = sonication.compile_plan()
        cutrun = sonication.preparation.compile_plan()
        branch = next(b for b in cutrun['branches'] if b['workflow'] == 'input')
        binding = plan['binding']
        self.assertEqual(binding['branch_id'], branch['id'])
        self.assertEqual(binding['origin_material_id'], branch['input_material_id'])
        self.assertEqual(binding['origin_vessel_id'], branch['vessels']['input'])
        self.assertEqual(binding['planned_process_vessel_id'], branch['vessels']['reaction'])
        self.assertEqual(binding['product_material_id'], branch['product_material_id'])
        self.assertEqual(binding['product_vessel_id'], branch['vessels']['product'])
        self.assertIsNone(binding['actual_runtime_material_id'])
        self.assertEqual(binding['operation'], 'sonicate_input')
        self.assertEqual(binding['size_check_operation'], 'check_input_size')
        self.assertEqual(set(binding['excluded_branch_ids']),
                         {b['id'] for b in cutrun['branches'] if b['workflow'] != 'input'})
        self.assertEqual(len(binding['excluded_branch_ids']), 2)
        self.assertEqual(plan['manual_binding'], {'stage': 'S09', 'decision': 'O04', 'status': 'open_not_an_approval'})

    def test_synthetic_complete_plan_computes_between_pulse_pauses_only(self):
        profile = self.complete()
        before = copy.deepcopy(profile)
        plan = sonication.compile_plan(profile)
        self.assertEqual(profile, before)
        self.assertTrue(plan['planning_complete'])
        self.assertFalse(plan['execution_ready'])
        pulse = plan['pulse_plan']
        self.assertEqual(pulse['total_on_s'], 21)
        self.assertEqual(pulse['total_between_pulses_s'], 4)
        self.assertEqual(pulse['nominal_elapsed_s'], 25)
        self.assertFalse(pulse['executed'])
        self.assertIsNone(pulse['energy_delivered_j'])
        self.assertEqual(len(plan['assumptions']), 17)
        plan['parameters']['cycles']['value'] = 900
        self.assertEqual(profile, before)

    def test_single_pulse_has_no_trailing_pause_and_zero_pause_is_explicit(self):
        profile = self.complete()
        profile['parameters']['cycles']['value'] = 1
        pulse = sonication.compile_plan(profile)['pulse_plan']
        self.assertEqual(pulse['total_between_pulses_s'], 0)
        self.assertEqual(pulse['nominal_elapsed_s'], 7)
        profile['parameters']['cycles']['value'] = 3
        profile['parameters']['between_pulses_s']['value'] = 0
        self.assertEqual(sonication.compile_plan(profile)['pulse_plan']['nominal_elapsed_s'], 21)

    def test_unknown_pause_preserves_known_on_time_without_inventing_elapsed_time(self):
        profile = self.complete()
        profile['parameters']['between_pulses_s'] = copy.deepcopy(self.profile['parameters']['between_pulses_s'])
        plan = sonication.compile_plan(profile)
        self.assertEqual(plan['pulse_plan']['total_on_s'], 21)
        self.assertIsNone(plan['pulse_plan']['nominal_elapsed_s'])
        self.assertFalse(plan['planning_complete'])

    def test_candidate_claims_are_not_sample_energy_or_temperature_evidence(self):
        plan = sonication.compile_plan(self.complete())
        candidate = plan['device_candidate']
        self.assertFalse(candidate['selected'])
        self.assertFalse(candidate['hardware_available'])
        self.assertEqual(candidate['manufacturer_claims']['maximum_vials']['value'], 10)
        self.assertEqual(candidate['manufacturer_claims']['nominal_power']['value'], 200)
        self.assertEqual(candidate['manufacturer_claims']['frequency']['value'], 26000)
        self.assertEqual(candidate['manufacturer_claims']['nominal_vessel_volumes']['value'], [0.5, 1, 1.5, 2])
        self.assertIsNone(plan['pulse_plan']['energy_delivered_j'])
        self.assertIn('reference_temperature_not_all_sample_temperatures', plan['execution_blockers'])

    def test_candidate_supported_sizes_do_not_replace_the_bound_e1_vessel_class(self):
        for volume in (0.5, 1, 2):
            with self.subTest(volume=volume):
                profile = self.complete()
                profile['parameters']['nominal_vessel_volume_ml']['value'] = volume
                with self.assertRaisesRegex(TaskError, 'pinned tube_1_5ml'):
                    sonication.compile_plan(profile)
        self.assertEqual(sonication.compile_plan(self.complete())['binding']['required_labware'], ['tube_1_5ml'])

    def test_size_comparison_and_column_constraint_remain_distinct_and_unobserved(self):
        size = sonication.compile_plan(self.complete())['fragment_size']
        self.assertEqual((size['comparison_target']['minimum'], size['comparison_target']['maximum']), (100, 600))
        self.assertEqual(size['column_maximum_exclusive_bp']['value'], 10000)
        self.assertIsNone(size['observed_result'])
        self.assertFalse(size['accepted'])
        self.assertIn('NanoDrop/Qubit', size['evidence_requirement'])

    def test_numeric_types_ranges_and_units_are_strict(self):
        cases = [('cycles', True), ('cycles', 0), ('cycles', 1.5), ('cycles', '3'),
            ('pulse_on_s', 0), ('pulse_on_s', -1), ('pulse_on_s', float('inf')),
            ('between_pulses_s', -1), ('between_pulses_s', True), ('amplitude_percent', 101),
            ('temperature_limit_deg_c', float('nan')), ('fill_volume_ul', 1501),
            ('nominal_vessel_volume_ml', 3)]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                profile = self.complete()
                profile['parameters'][name]['value'] = value
                with self.assertRaises((TaskError, ValueError, OverflowError)):
                    sonication.compile_plan(profile)
        profile = self.complete()
        profile['parameters']['pulse_on_s']['unit'] = 'min'
        with self.assertRaisesRegex(TaskError, 'unit'):
            sonication.compile_plan(profile)

    def test_identifiers_provenance_and_extra_fields_are_strict(self):
        for field in ['id', 'device_instance_id', 'input_size_evidence_ref']:
            with self.subTest(field=field):
                profile = self.complete()
                if field == 'id':
                    profile[field] = 'foreign/path'
                else:
                    profile['parameters'][field]['value'] = 'foreign/path'
                with self.assertRaises(TaskError):
                    sonication.compile_plan(profile)
        for change in [('basis', 'manufacturer_reported'), ('source_refs', ['unknown'])]:
            profile = self.complete()
            profile['parameters']['cycles'][change[0]] = change[1]
            with self.assertRaises(TaskError):
                sonication.compile_plan(profile)
        profile = self.complete()
        profile['execute'] = True
        with self.assertRaises(TaskError):
            sonication.compile_plan(profile)

    def test_repinned_protocol_cannot_change_implemented_unit_type_or_lower_bounds(self):
        for field, key, value in [('pulse_on_s', 'unit', 'min'), ('between_pulses_s', 'unit', 'ms'),
            ('cycles', 'kind', 'number'), ('cycles', 'minimum', 0),
            ('between_pulses_s', 'minimum', -1), ('amplitude_percent', 'maximum', 1000),
            ('nominal_vessel_volume_ml', 'unit', 'uL'), ('fill_volume_ul', 'unit', 'mL'),
            ('device_instance_id', 'kind', 'text')]:
            with self.subTest(field=field, key=key):
                protocol = copy.deepcopy(self.protocol)
                protocol['parameter_contract'][field][key] = value
                with self.repinned_protocol(protocol) as profile:
                    with self.assertRaisesRegex(TaskError, 'parameter|Percent'):
                        sonication.compile_plan(profile)

    def test_repinned_protocol_cannot_redirect_sonication_to_cutrun_branch(self):
        protocol = copy.deepcopy(self.protocol)
        protocol['binding']['workflow'] = 'cutrun'
        with self.repinned_protocol(protocol) as profile:
            with self.assertRaisesRegex(TaskError, 'separate CUT&RUN input'):
                sonication.compile_plan(profile)

    def test_missing_and_changed_pins_are_rejected(self):
        for name in ('protocol', 'preparation'):
            with self.subTest(name=name):
                profile = copy.deepcopy(self.profile)
                profile[name]['source_sha256'] = '0' * 64
                with self.assertRaises(TaskError):
                    sonication.compile_plan(profile)
                profile[name].pop('source_sha256')
                with self.assertRaises(TaskError):
                    sonication.compile_plan(profile)

    def test_real_source_byte_drift_is_rejected_without_writing_original(self):
        original = Path.read_bytes
        for name in [self.profile['protocol']['source'], self.profile['preparation']['source'],
                     'model/cutrun-automation.protocol.json']:
            with self.subTest(source=name):
                target = (ROOT / name).resolve()
                before = original(target)
                reads = []
                def drift(path):
                    if path.resolve() == target:
                        reads.append(path)
                        return before + b'\n'
                    return original(path)
                with patch.object(Path, 'read_bytes', drift):
                    with self.assertRaises(TaskError):
                        sonication.compile_plan()
                self.assertTrue(reads)
                self.assertEqual(original(target), before)

    def test_source_graph_covers_e1_and_new_helpers_and_matches_bytes(self):
        pins = sonication.compile_plan()['source_files_sha256']
        for name in ['model/dna-sonication.profile.json', 'model/dna-sonication.protocol.json',
            'model/cutrun-automation.preparation.json', 'model/cutrun-automation.protocol.json',
            'model/cutrun-automation.catalog.json', 'scripts/cutrun_preparation.py',
            *sonication.DEPENDENCIES]:
            with self.subTest(name=name):
                self.assertEqual(pins[name], digest((ROOT / name).read_bytes()))

    def test_source_changed_after_compilation_is_detected_by_final_recheck(self):
        original = Path.read_bytes
        target = (ROOT / self.profile['protocol']['source']).resolve()
        reads = 0
        def drift(path):
            nonlocal reads
            content = original(path)
            if path.resolve() == target:
                reads += 1
                if reads > 2:
                    return content + b'\n'
            return content
        with patch.object(Path, 'read_bytes', drift), self.assertRaisesRegex(TaskError, 'source changed'):
            sonication.compile_plan()
        self.assertGreater(reads, 2)

    def test_compile_has_no_store_subprocess_network_or_write_effects(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('Forbidden planning effect')
        original_open = Path.open
        def read_only(path, mode='r', *args, **kwargs):
            if any(letter in mode for letter in 'wax+'):
                forbidden()
            return original_open(path, mode, *args, **kwargs)
        with patch('manual_tasks.Journal', forbidden), patch.object(sqlite3, 'connect', forbidden), \
             patch.object(subprocess, 'Popen', forbidden), patch.object(socket, 'socket', forbidden), \
             patch.object(urllib.request, 'urlopen', forbidden), patch.object(Path, 'open', read_only), \
             patch.object(Path, 'mkdir', forbidden), patch.object(Path, 'write_bytes', forbidden), \
             patch.object(Path, 'write_text', forbidden):
            plan = sonication.compile_plan()
        self.assertFalse(any(plan['effects'].values()))

    @unittest.skipIf(jsonschema is None, 'jsonschema is not installed')
    def test_both_sources_validate_against_the_declared_schema(self):
        schema = json.loads((ROOT / sonication.SCHEMA).read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(self.profile)
        validator.validate(self.protocol)

    def test_cli_default_require_complete_and_invalid_inputs(self):
        self.assertEqual(self.call_cli()[0], 0)
        self.assertEqual(self.call_cli('--require-complete')[0], 2)
        self.assertEqual(self.call_cli('--execute')[0], 1)
        bad = self.directory / 'invalid.json'
        bad.write_text('{"format":NaN}')
        self.assertEqual(self.call_cli('--profile', str(bad))[0], 1)

    def test_cli_complete_synthetic_input_never_enables_execution(self):
        profile = self.directory / 'profile.json'
        profile.write_text(json.dumps(self.complete()))
        code, plan = self.call_cli('--profile', str(profile), '--require-complete')
        self.assertEqual(code, 0)
        self.assertFalse(plan['execution_ready'])
        self.assertFalse(any(plan['effects'].values()))

    def test_cli_output_is_new_json_under_exports_only(self):
        target = self.directory / 'plan.json'
        self.assertEqual(self.call_cli('--out', str(target))[0], 0)
        original = target.read_bytes()
        self.assertEqual(self.call_cli('--out', str(target))[0], 1)
        self.assertEqual(target.read_bytes(), original)
        with tempfile.TemporaryDirectory(prefix='dna-sonication-outside-') as outside:
            path = Path(outside) / 'plan.json'
            self.assertEqual(self.call_cli('--out', str(path))[0], 1)
            self.assertFalse(path.exists())
            link = self.directory / 'outside'
            link.symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.call_cli('--out', str(link / 'plan.json'))[0], 1)
        self.assertEqual(self.call_cli('--out', str(self.directory / 'bad.txt'))[0], 1)


if __name__ == '__main__':
    unittest.main()
