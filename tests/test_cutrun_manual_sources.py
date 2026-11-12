"""Source readiness is independent of observed outcomes and laboratory defaults."""

import copy
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import cutrun_manual_sources as sources
from manual_tasks import TaskError, digest

try:
    import jsonschema
except ImportError:
    jsonschema = None


class ManualSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cutrun-manual-sources-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.profile = json.loads(sources.SOURCE.read_text())
        self.original = self.directory / 'manufacturer.pdf'
        self.original.write_bytes(b'%PDF-1.7\nexplicit unit-test source, not a laboratory original\n')
        original_hash = self.profile['sources']['manufacturer']['source_sha256']
        self.profile['sources']['manufacturer']['source_sha256'] = digest(self.original.read_bytes())
        # A different manufacturer original can only be bound through different,
        # explicitly pinned SOP bytes too. This is an isolated test repository,
        # not a mutation of the production SOP or a bypass of its verifier.
        self.fixture_root = self.directory / 'repository'
        for name in ('docs', 'model', 'scripts'):
            (self.fixture_root / name).mkdir(parents=True)
        sop_name = self.profile['sources']['sop']['source']
        sop_bytes = (ROOT / sop_name).read_bytes().replace(original_hash.encode(),
                            self.profile['sources']['manufacturer']['source_sha256'].encode())
        (self.fixture_root / sop_name).write_bytes(sop_bytes)
        self.profile['sources']['sop']['source_sha256'] = digest(sop_bytes)
        for name in ('scripts/cutrun_manual_sources.py', sources.SCHEMA):
            shutil.copyfile(ROOT / name, self.fixture_root / name)
        self.root_patch = mock.patch.object(sources, 'ROOT', self.fixture_root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.evidence = self.directory / 'decision.txt'
        self.evidence.write_bytes(b'Explicit test decision evidence; not an authenticated approval.\n')
        self.evidence_files = {'decision_evidence': self.evidence}
        # Other agents may be implementing the runtime in parallel. Source
        # semantics do not depend on those files; final integration checks pin
        # the complete unpatched RUNTIME separately.
        self.runtime = mock.patch.object(sources, 'RUNTIME',
                                        ('scripts/cutrun_manual_sources.py', sources.SCHEMA))
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def compile(self, profile=None, **kwargs):
        return sources.compile_profile(self.profile if profile is None else profile, **kwargs)

    def confirmed(self):
        profile = copy.deepcopy(self.profile)
        for decision in profile['local_decisions'].values():
            decision.update(status='confirmed', value={'decision': 'Explicit test-only selection'},
                            actor_id='Test.Operator', confirmed_at='2026-01-01T12:00:00Z',
                            evidence_ref='decision_evidence')
        values = {'task_deadline_s': 100000, 'activation_volume_ul': 150, 'stop_volume_ul': 150,
                  'activation_duration_s': 1800, 'stop_window_s': 120,
                  'temperature_tolerance_deg_c': 1, 'activation_temperature_deg_c': 4,
                  'phase_tolerance_s': 60, 'input_cells': 10000}
        for name, fact in profile['parameters'].items():
            fact.update(value=values[name], basis='locally_confirmed', source_ref='sop',
                        evidence_ref='decision_evidence')
        profile['context'].update(culture_id='Test.Culture', material_state='fresh_unfixed',
                                  condition_id='Test.Baseline')
        for name, binding in profile['roles'].items():
            binding.update(material_id=None if name == 'ntc' else 'Test.' + name,
                           vessel_id='Test.' + name + '.Tube')
        for name, plan in profile['qc_plan']['roles'].items():
            plan.update(assay_id='Test.RawDNA.' + name,
                        criteria={'review_rule': 'Role-specific prospective test criterion'},
                        limits={'censoring': 'Preserve not-detected/below-LOQ; no invented zero'},
                        evidence_ref='decision_evidence')
        profile['handover_plan'].update(recipient_id='Test.Recipient',
            storage_location={'rack_id': 'Test.ProductRack', 'place_id': 'P01'},
            conditions='Explicit test storage conditions', evidence_ref='decision_evidence')
        return profile

    def test_default_is_archiveable_with_unknowns_and_no_ready_stages(self):
        result = self.compile()
        self.assertTrue(result['can_archive'])
        self.assertFalse(result['preparation_complete'])
        self.assertFalse(result['can_claim_reference_success'])
        self.assertEqual(set(result['stage_readiness']), set(sources.STAGES))
        self.assertFalse(any(result['stage_readiness'].values()))
        self.assertTrue(all(fact['value'] is None for fact in result['manual_profile']['parameters'].values()))
        self.assertTrue(any(item['id'] == 'manufacturer_original' for item in result['open_requirements']))
        self.assertNotIn(digest(self.original.read_bytes()), result['evidence_artifacts'])

    def test_supplied_original_and_evidence_preserve_exact_bytes(self):
        result = self.compile(original_pdf=self.original, evidence_files=self.evidence_files)
        self.assertTrue(result['original_pdf_verified'])
        self.assertEqual(result['evidence_artifacts'][digest(self.original.read_bytes())], self.original.read_bytes())
        record = result['evidence_records']['decision_evidence']
        self.assertEqual(record, {'sha256': digest(self.evidence.read_bytes()),
                                  'size_bytes': len(self.evidence.read_bytes())})
        self.assertNotIn(str(self.directory), json.dumps(result['evidence_records']))
        self.assertIn(self.profile['sources']['sop']['source_sha256'], result['evidence_artifacts'])

    def test_complete_bindings_are_ready_without_claiming_reference_success(self):
        result = self.compile(self.confirmed(), original_pdf=self.original, evidence_files=self.evidence_files)
        self.assertEqual(result['open_requirements'], [])
        self.assertTrue(all(result['stage_readiness'].values()))
        self.assertTrue(result['preparation_complete'])
        self.assertFalse(result['can_claim_reference_success'])

    def test_unknown_stop_window_blocks_activation_even_with_confirmed_decisions(self):
        profile = self.confirmed()
        profile['parameters']['stop_window_s'].update(value=None, basis='unknown', source_ref=None, evidence_ref=None)
        result = self.compile(profile, original_pdf=self.original, evidence_files=self.evidence_files)
        self.assertTrue(result['stage_readiness']['S04'])
        self.assertFalse(result['stage_readiness']['S06'])
        self.assertFalse(result['stage_readiness']['S07'])
        self.assertFalse(result['stage_readiness']['S08'])

    def test_manufacturer_value_or_proposal_is_not_local_parameter_confirmation(self):
        for basis in ('manufacturer_reported', 'local_proposal'):
            with self.subTest(basis=basis):
                profile = self.confirmed()
                profile['parameters']['stop_window_s'].update(basis=basis, source_ref='manufacturer',
                                                             evidence_ref=None)
                result = self.compile(profile, original_pdf=self.original, evidence_files=self.evidence_files)
                self.assertFalse(result['stage_readiness']['S07'])

    def test_missing_actual_roles_context_and_qc_remain_open(self):
        profile = self.confirmed()
        profile['context']['culture_id'] = None
        profile['roles']['igg']['material_id'] = None
        profile['qc_plan']['roles']['ntc']['criteria'] = None
        result = self.compile(profile, original_pdf=self.original, evidence_files=self.evidence_files)
        identities = {item['id'] for item in result['open_requirements']}
        self.assertTrue({'context.culture_id', 'role.igg', 'qc.ntc'} <= identities)

    def test_unregistered_or_future_approval_is_rejected(self):
        for update in ({'evidence_ref': 'missing'}, {'confirmed_at': '2999-01-01T00:00:00Z'},
                       {'confirmed_at': '2026-01-01T00:00:00'},
                       {'confirmed_at': '2026-01-01 00:00:00+00:00'}, {'actor_id': ''}, {'value': None}):
            with self.subTest(update=update):
                profile = self.confirmed()
                profile['local_decisions']['O11'].update(update)
                with self.assertRaises(TaskError):
                    self.compile(profile, original_pdf=self.original, evidence_files=self.evidence_files)

    def test_malformed_unknown_or_parameter_quantities_are_rejected(self):
        for update in ({'value': 0}, {'value': True}, {'value': math.inf},
                       {'unit': 'mg'}, {'basis': 'synthetic_assumption'}, {'source_ref': {}}):
            with self.subTest(update=update):
                profile = copy.deepcopy(self.profile)
                profile['parameters']['activation_volume_ul'].update(update)
                with self.assertRaises(TaskError):
                    self.compile(profile)
        profile = self.confirmed()
        profile['parameters']['input_cells']['value'] = 0.5
        with self.assertRaises(TaskError):
            self.compile(profile, original_pdf=self.original, evidence_files=self.evidence_files)

    def test_mandatory_stage_gates_cannot_be_stripped_or_reassigned(self):
        for field, value in (('required_decisions', []), ('required_parameters', []),
                             ('source_ref', 'synthetic'), ('sop_step', 'S01')):
            with self.subTest(field=field):
                profile = copy.deepcopy(self.profile)
                profile['stage_bindings']['S07'][field] = value
                with self.assertRaises(TaskError):
                    self.compile(profile)

    def test_control_roles_and_actual_identity_aliases_are_rejected(self):
        for mutate in (
            lambda p: p['roles']['igg'].update(role='reference'),
            lambda p: p['roles']['ntc'].update(material_id='Test.input'),
            lambda p: p['roles']['igg'].update(vessel_id='Test.h3k4me3.Tube'),
            lambda p: p['roles']['input'].update(material_id='SYN.CUTRUN.Input'),
        ):
            profile = self.confirmed()
            mutate(profile)
            with self.assertRaises(TaskError):
                self.compile(profile, original_pdf=self.original, evidence_files=self.evidence_files)

    def test_source_hashes_and_closed_shapes_reject_substitution(self):
        mutations = (
            lambda p: p['sources']['sop'].update(source_sha256='0' * 64),
            lambda p: p['sources']['sop'].update(source='../outside.md'),
            lambda p: p['sources']['manufacturer'].update(protocol_revision='2025'),
            lambda p: p['sources']['manufacturer'].update(source_sha256='1' * 64),
            lambda p: p['context'].update(material_state='fixed'),
            lambda p: p.update(synthetic=True),
            lambda p: p.update(execution_ready=True),
            lambda p: p['local_decisions'].update(O12={'status': 'confirmed'}),
        )
        for mutate in mutations:
            profile = copy.deepcopy(self.profile)
            mutate(profile)
            with self.assertRaises(TaskError):
                self.compile(profile)
        with self.assertRaises(TaskError):
            sources.compile_profile(self.profile, original_pdf=self.evidence)

    def test_profile_source_is_detached_and_read_only(self):
        before = copy.deepcopy(self.profile)
        snapshots = {path: path.read_bytes() for path in (self.original, self.evidence, sources.SOURCE)}
        with mock.patch('manual_tasks.Journal', side_effect=AssertionError('journal effect')), \
             mock.patch('sqlite3.connect', side_effect=AssertionError('database effect')), \
             mock.patch('socket.socket', side_effect=AssertionError('network effect')), \
             mock.patch('subprocess.run', side_effect=AssertionError('subprocess effect')), \
             mock.patch.object(Path, 'write_bytes', side_effect=AssertionError('file effect')), \
             mock.patch.object(Path, 'write_text', side_effect=AssertionError('file effect')):
            result = self.compile(original_pdf=self.original, evidence_files=self.evidence_files)
        self.assertEqual(self.profile, before)
        result['manual_profile']['parameters']['stop_window_s']['value'] = 999
        self.assertEqual(self.profile, before)
        self.assertEqual(snapshots, {path: path.read_bytes() for path in snapshots})

    def test_source_change_during_compilation_is_rejected(self):
        original_read = sources._read
        sop_reads = 0

        def changing(path, label):
            nonlocal sop_reads
            content = original_read(path, label)
            if Path(path).name == 'cutrun-manual-sop-draft.md':
                sop_reads += 1
                if sop_reads > 1:
                    return content + b'\nchanged'
            return content

        with mock.patch.object(sources, '_read', side_effect=changing):
            with self.assertRaisesRegex(TaskError, 'changed during compilation'):
                self.compile()

    def test_json_duplicate_fields_are_rejected(self):
        profile_file = self.directory / 'duplicate.json'
        profile_file.write_text('{"format":"one","format":"two"}')
        with self.assertRaises(TaskError):
            sources.compile_profile(profile_file)

    def test_load_keeps_explicit_inventory_and_transient_artifacts(self):
        materials = [{'id': 'Test.Input', 'kind': 'sample', 'vessel_id': 'Test.InputTube',
                      'quantity': {'value': None, 'unit': 'cells'}, 'origin_id': 'Test.Culture'},
                     {'id': 'Test.Stop', 'kind': 'reagent', 'vessel_id': 'Test.StopTube',
                      'quantity': {'value': None, 'unit': 'uL'}, 'origin_id': 'Test.Issued'}]
        vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': 'Test.Rack', 'place_id': 'P%d' % index}}
                   for index, identity in enumerate(('Test.InputTube', 'Test.StopTube', 'Test.ReactionTube'), 1)]
        definition = sources.load(self.profile, materials=materials, vessels=vessels, clock_source_kind='test_clock',
            original_pdf=self.original, protective_stop_bindings={'Test.ReactionTube': 'Test.Stop'})
        self.assertEqual(definition['format'], 'solidcraftbot.material-workflow-definition/3')
        self.assertEqual(definition['profile']['type'], 'cutrun_manual_capture/1')
        self.assertEqual(definition['clock_mode'], 'real_observations/1')
        self.assertEqual(definition['clock_source_kind'], 'test_clock')
        self.assertEqual(definition['initial_materials'], materials)
        self.assertIsNone(definition['profile']['parameters']['task_deadline_s'])
        self.assertEqual(definition['products'], [])
        self.assertEqual(len(definition['material_allocations']), 1)
        self.assertTrue(definition['_initial_artifacts'])
        self.assertEqual(definition['protective_stop_bindings'], {'Test.ReactionTube': 'Test.Stop'})
        definition.pop('_initial_artifacts')
        json.dumps(definition, allow_nan=False)

    def test_load_rejects_synthetic_clock_and_shared_protective_aliquots(self):
        materials = [{'id': 'Test.Stop', 'kind': 'reagent', 'vessel_id': 'Test.StopTube',
                      'quantity': {'value': 300, 'unit': 'uL'}, 'origin_id': None}]
        vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': 'Test.Rack', 'place_id': 'P%d' % index}}
                   for index, identity in enumerate(('Test.StopTube', 'Test.R1', 'Test.R2'), 1)]
        for arguments in ({'clock_source_kind': 'synthetic_events/1'},
                          {'clock_source_kind': 'system_clock',
                           'protective_stop_bindings': {'Test.R1': 'Test.Stop', 'Test.R2': 'Test.Stop'}},
                          {'clock_source_kind': 'system_clock', 'protective_stop_bindings': []}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(TaskError):
                    sources.load(self.profile, materials=materials, vessels=vessels, **arguments)


@unittest.skipUnless(jsonschema, 'jsonschema is not installed in this interpreter')
class ManualSourceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / sources.SCHEMA).read_text())
        self.profile = json.loads(sources.SOURCE.read_text())
        self.validator = jsonschema.Draft202012Validator(self.schema,
                                                        format_checker=jsonschema.FormatChecker())

    def test_schema_itself_and_default_profile(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.profile)

    def test_schema_rejects_claimed_approval_and_nonnull_unknowns(self):
        for mutate in (
            lambda p: p['local_decisions']['O11'].update(status='confirmed'),
            lambda p: p['parameters']['stop_window_s'].update(value=180),
            lambda p: p['parameters']['input_cells'].update(basis='synthetic_assumption'),
            lambda p: p['stage_bindings']['S07'].update(required_parameters=[]),
            lambda p: p.update(synthetic=True),
            lambda p: p['local_decisions'].update(O12={'status': 'confirmed'}),
        ):
            profile = copy.deepcopy(self.profile)
            mutate(profile)
            self.assertTrue(list(self.validator.iter_errors(profile)))


if __name__ == '__main__':
    unittest.main()
