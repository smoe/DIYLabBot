"""Prospective full-stage requirements remain separate from observed outcomes."""
import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cutrun_manual_sop_sources as sources
from manual_tasks import TaskError, digest
import test_cutrun_manual_sources as base_tests

try:
    import jsonschema
except ImportError:
    jsonschema = None


class SopSourceTests(unittest.TestCase):
    def setUp(self):
        self.base = base_tests.ManualSourceTests('test_default_is_archiveable_with_unknowns_and_no_ready_stages')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.profile = json.loads(sources.SOURCE.read_text())
        self.fixture = self.base.fixture_root.resolve()
        names = ('scripts/cutrun_manual_sop_sources.py', sources.PROTOCOL,
                 'model/cutrun-manual-sop.profile.json', sources.PROFILE_SCHEMA, sources.PROTOCOL_SCHEMA)
        for name in names:
            target = self.fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for name, value in [('ROOT', self.fixture), ('RUNTIME', names)]:
            modification = patch.object(sources, name, value)
            modification.start();self.addCleanup(modification.stop)

    def confirmed(self):
        profile = copy.deepcopy(self.profile)
        profile['qualifications'] = {
            'Test.Time': {'kind': 'time', 'source_id': 'Test.Clock', 'relationship': None,
                          'evidence_ref': 'decision_evidence'},
            'Test.Temperature': {'kind': 'temperature', 'source_id': 'Test.Probe',
                                 'relationship': 'qualified_proxy', 'evidence_ref': 'decision_evidence'}}
        for binding in profile['phase_requirements'].values():
            binding.update(duration_min_s=10, duration_max_s=20,
                temperature_min_deg_c=3, temperature_max_deg_c=5,
                time_qualification_ref='Test.Time', temperature_qualification_ref='Test.Temperature',
                evidence_ref='decision_evidence')
        return profile

    def compile(self, profile=None, *, base_profile=None, original=True):
        return sources.compile_profile({'base_profile': self.base.confirmed() if base_profile is None else base_profile,
                                        'sop_profile': self.profile if profile is None else profile},
            original_pdf=self.base.original if original else None, evidence_files=self.base.evidence_files)

    def test_defaults_keep_all_phase_values_unknown_without_effects(self):
        before = copy.deepcopy(self.profile)
        with patch('sqlite3.connect', side_effect=AssertionError('database effect')), \
             patch('subprocess.run', side_effect=AssertionError('subprocess effect')), \
             patch('socket.socket', side_effect=AssertionError('network effect')):
            result = self.compile(base_profile=self.base.profile, original=False)
        self.assertTrue(result['can_archive']);self.assertFalse(result['preparation_complete'])
        self.assertFalse(result['can_claim_reference_success'])
        self.assertFalse(any(result['stage_readiness'].values()))
        self.assertEqual(self.profile, before)
        self.assertTrue(all(value is None for binding in result['sop_profile']['phase_requirements'].values()
                            for value in binding.values()))

    def test_complete_test_bindings_are_ready_but_not_reference_success(self):
        result = self.compile(self.confirmed())
        self.assertEqual(result['open_requirements'], [])
        self.assertTrue(all(result['stage_readiness'].values()))
        self.assertTrue(result['preparation_complete']);self.assertFalse(result['can_claim_reference_success'])

    def test_graph_distinguishes_early_input_from_activation_and_contains_all_stages(self):
        protocol = self.compile()['sop_protocol']
        self.assertEqual(protocol['global_stages'], ['S01','S11','S12'])
        self.assertEqual(protocol['branch_sequences']['input'], ['S02','S09','S10'])
        self.assertEqual(protocol['branch_sequences']['h3k4me3'], protocol['branch_sequences']['igg'])
        self.assertNotIn('input', protocol['stages']['S07']['roles'])
        self.assertEqual(protocol['stages']['S08']['phases'], ['S08.release','S08.separation'])
        self.assertEqual(set(protocol['stages']), {'S%02d' % i for i in range(1,13)})
        self.assertTrue(all(stage['completion_evidence'] for stage in protocol['stages'].values()))

    def test_each_missing_phase_bound_blocks_its_stage_and_critical_preparation(self):
        for phase in self.profile['phase_requirements']:
            for field in sources.PHASE_FIELDS:
                profile = self.confirmed();profile['phase_requirements'][phase][field] = None
                with self.subTest(phase=phase, field=field):
                    result = self.compile(profile)
                    self.assertFalse(result['stage_readiness'][phase[:3]])
                    if phase.startswith(('S07.', 'S08.')):
                        self.assertFalse(result['stage_readiness']['S06'])
                        self.assertFalse(result['stage_readiness']['S07'])

    def test_setpoint_or_unknown_relationship_cannot_qualify_sample_temperature(self):
        for relationship in ('device_setpoint', None):
            profile = self.confirmed();profile['qualifications']['Test.Temperature']['relationship'] = relationship
            result = self.compile(profile)
            self.assertFalse(result['stage_readiness']['S04'])
            self.assertFalse(result['preparation_complete'])
            self.assertTrue(result['can_archive'])

    def test_unknown_original_evidence_or_wrong_qualification_kind_is_rejected(self):
        mutations = [lambda p:p['qualifications']['Test.Time'].update(evidence_ref='Missing'),
            lambda p:p['phase_requirements']['S07.digestion'].update(evidence_ref='Missing'),
            lambda p:p['phase_requirements']['S07.digestion'].update(time_qualification_ref='Missing'),
            lambda p:p['phase_requirements']['S07.digestion'].update(time_qualification_ref='Test.Temperature')]
        for mutate in mutations:
            profile = self.confirmed();mutate(profile)
            with self.assertRaises(TaskError):self.compile(profile)

    def test_invalid_ranges_and_nonfinite_or_boolean_bounds_are_rejected(self):
        for field, value in [('duration_min_s', -1), ('duration_max_s', float('inf')),
                             ('duration_min_s', True), ('temperature_min_deg_c', float('nan')),
                             ('duration_min_s', 30), ('temperature_max_deg_c', 1)]:
            profile = self.confirmed();profile['phase_requirements']['S04.antibody_incubation'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(TaskError):self.compile(profile)

    def test_negative_temperature_interval_is_valid_when_explicitly_bound(self):
        profile = self.confirmed()
        profile['phase_requirements']['S09.input_preparation'].update(temperature_min_deg_c=-21,temperature_max_deg_c=-19)
        self.assertTrue(self.compile(profile)['stage_readiness']['S09'])

    def test_closed_profile_does_not_accept_claimed_execution_or_removed_phases(self):
        for mutate in [lambda p:p.update(execution_ready=True), lambda p:p.update(synthetic=True),
                       lambda p:p['phase_requirements'].pop('S08.release'),
                       lambda p:p['qualifications']['Test.Time'].update(relationship='sample_measurement')]:
            profile = self.confirmed();mutate(profile)
            with self.assertRaises(TaskError):self.compile(profile)
        with self.assertRaises(TaskError):sources.compile_profile(self.profile)

    def test_source_bytes_are_preserved_detached_and_pinned(self):
        result = sources.compile_profile({'base_profile':self.base.confirmed(),
            'sop_profile':self.fixture/'model/cutrun-manual-sop.profile.json'},
            original_pdf=self.base.original,evidence_files=self.base.evidence_files)
        for name in (sources.PROTOCOL, 'model/cutrun-manual-sop.profile.json'):
            original = (self.fixture/name).read_bytes()
            self.assertIn(digest(original), result['evidence_artifacts'])
            self.assertEqual(result['source_files_sha256'][name], digest(original))
        result['sop_protocol']['stages']['S04']['phases'].clear()
        self.assertEqual(self.compile()['sop_protocol']['stages']['S04']['phases'], ['S04.antibody_incubation'])

    def test_protocol_cannot_remove_or_reassign_mandatory_time_temperature_phases(self):
        path=self.fixture/sources.PROTOCOL;original=path.read_bytes()
        for mutate in [lambda p:p['stages']['S04'].update(phases=[]),
                       lambda p:p['stages']['S08']['phases'].reverse(),
                       lambda p:p['stages']['S03'].update(phases=['S04.antibody_incubation'])]:
            protocol=json.loads(original);mutate(protocol)
            path.write_text(json.dumps(protocol))
            with self.assertRaises(TaskError):self.compile()
            path.write_bytes(original)

    def test_protocol_changed_after_parse_is_rejected(self):
        original = sources._read
        def change(source, default=None):
            result = original(source, default)
            if not isinstance(source, dict) and Path(source or default).name == 'cutrun-manual-sop.protocol.json':
                path = self.fixture/sources.PROTOCOL;path.write_bytes(path.read_bytes()+b'\n')
            return result
        with patch.object(sources, '_read', side_effect=change):
            with self.assertRaisesRegex(TaskError, 'changed after parsing'):self.compile()

    def test_load_reuses_closed_material_contract_and_archives_sop_sources(self):
        materials = [{'id':'Test.Input','kind':'sample','vessel_id':'Test.Tube',
                      'quantity':{'value':None,'unit':'cells'},'origin_id':None}]
        vessels = [{'id':'Test.Tube','location':{'kind':'rack','rack_id':'Test.Rack','place_id':'P01'}}]
        result = sources.load({'base_profile':self.base.profile,'sop_profile':self.profile},
            materials=materials,vessels=vessels,clock_source_kind='system_clock')
        self.assertEqual(result['format'],'solidcraftbot.material-workflow-definition/3')
        self.assertEqual(result['profile']['type'],'cutrun_manual_sop/1')
        self.assertEqual(result['initial_materials'],materials)
        self.assertFalse(result['preparation_plan']['execution_ready'])
        self.assertEqual(result['preparation_plan']['mode'],'manual_sop_contract')
        self.assertTrue(result['_initial_artifacts'])
        self.assertTrue(all(value is None for binding in result['sop_profile']['phase_requirements'].values() for value in binding.values()))
        result.pop('_initial_artifacts');json.dumps(result,allow_nan=False)


@unittest.skipUnless(jsonschema, 'jsonschema is not installed in this interpreter')
class SopSchemaTests(unittest.TestCase):
    def test_schema_definitions_and_default_sources(self):
        for source, schema in [('model/cutrun-manual-sop.profile.json',sources.PROFILE_SCHEMA),
                               (sources.PROTOCOL,sources.PROTOCOL_SCHEMA)]:
            validator = jsonschema.Draft202012Validator(json.loads((ROOT/schema).read_text()))
            jsonschema.Draft202012Validator.check_schema(validator.schema)
            validator.validate(json.loads((ROOT/source).read_text()))

    def test_schema_rejects_unknown_fields_and_non_numeric_bounds(self):
        profile=json.loads(sources.SOURCE.read_text())
        validator=jsonschema.Draft202012Validator(json.loads((ROOT/sources.PROFILE_SCHEMA).read_text()))
        for mutate in [lambda p:p.update(execution_ready=True),
                       lambda p:p['phase_requirements']['S07.digestion'].update(duration_min_s='30 minutes'),
                       lambda p:p['phase_requirements'].pop('S08.release')]:
            example=copy.deepcopy(profile);mutate(example)
            self.assertTrue(list(validator.iter_errors(example)))
