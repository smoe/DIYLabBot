"""CUT&RUN preparation binds requirements without performing laboratory effects."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cutrun_preparation as model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CutrunPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        names = [
            'model/cutrun-automation.catalog.json',
            'model/cutrun-automation.protocol.json',
            'model/cutrun-automation.preparation.json',
            'model/cutrun-automation.schema.json',
            'model/assembly-reference.schema.json',
            'scripts/cutrun_preparation.py',
            'scripts/prepare_cutrun_automation.py',
            'scripts/extraction_preparation.py',
            'scripts/assembly_model.py',
            'scripts/robot_spec.py',
            'scripts/manual_workflow.py',
            'scripts/manual_tasks.py',
        ]
        for name in names:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        self.profile = json.loads(model.SOURCE.read_text())
        self.catalog_path = self.root / self.profile['catalog']['source']
        self.protocol_path = self.root / self.profile['protocol']['source']
        self.catalog = json.loads(self.catalog_path.read_text())
        self.protocol = json.loads(self.protocol_path.read_text())
        root_patch = patch.object(model, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def bind(self):
        for field, value, path in [
            ('catalog', self.catalog, self.catalog_path),
            ('protocol', self.protocol, self.protocol_path),
        ]:
            path.write_text(json.dumps(value, indent=2) + '\n')
            self.profile[field]['source_sha256'] = sha(path)

    def compile(self):
        self.bind()
        return model.compile_plan(self.profile)

    def test_default_synthetic_plan_is_complete_but_cannot_execute(self):
        plan = self.compile()
        self.assertEqual(plan['format'], 'solidcraftbot.cutrun-preparation-plan/1')
        self.assertEqual(plan['mode'], 'preparation_only')
        self.assertIs(plan['synthetic'], True)
        self.assertIs(plan['planning_complete'], True)
        self.assertIs(plan['execution_ready'], False)
        self.assertEqual(plan['open_requirements'], [])
        self.assertTrue(plan['execution_blockers'])
        self.assertTrue(plan['assumptions'])
        self.assertTrue(all(record['path'] and record['basis'] for record in plan['assumptions']))
        self.assertTrue(plan['effects'])
        self.assertTrue(all(value is False for value in plan['effects'].values()))

    def test_pinned_sources_and_effective_input_digest_are_reported(self):
        plan = self.compile()
        for name, checksum in plan['source_files_sha256'].items():
            self.assertEqual(checksum, sha(self.root / name), name)
        self.assertIn('model/cutrun-automation.catalog.json', plan['source_files_sha256'])
        self.assertIn('model/cutrun-automation.protocol.json', plan['source_files_sha256'])
        self.assertEqual(len(plan['effective_preparation_sha256']), 64)
        changed = copy.deepcopy(self.profile)
        changed['id'] += '.Other'
        self.assertNotEqual(
            model.compile_plan(changed)['effective_preparation_sha256'],
            plan['effective_preparation_sha256'],
        )

    def test_stale_or_missing_reference_pin_cannot_be_accepted(self):
        self.bind()
        for field in ['catalog', 'protocol']:
            for mutation in ['stale', 'missing']:
                profile = copy.deepcopy(self.profile)
                if mutation == 'stale':
                    profile[field]['source_sha256'] = '0' * 64
                else:
                    del profile[field]['source_sha256']
                with self.subTest(field=field, mutation=mutation):
                    with self.assertRaises(model.TaskError):
                        model.compile_plan(profile)

    def test_source_references_cannot_escape_project_through_absolute_paths_or_symlinks(self):
        self.bind()
        absolute = copy.deepcopy(self.profile)
        absolute['catalog']['source'] = str(self.catalog_path)
        with self.assertRaises(model.TaskError):
            model.compile_plan(absolute)
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory) / 'catalog.json'
            foreign.write_bytes(self.catalog_path.read_bytes())
            link = self.root / 'model/outside-catalog.json'
            link.symlink_to(foreign)
            profile = copy.deepcopy(self.profile)
            profile['catalog']['source'] = str(link.relative_to(self.root))
            with self.assertRaises(model.TaskError):
                model.compile_plan(profile)

    def test_profile_swap_between_parse_and_pin_is_detected(self):
        self.bind()
        path = self.root / 'model/request.json'
        path.write_text(json.dumps(self.profile))
        original = Path.read_bytes
        swapped = []

        def read_then_swap(candidate):
            content = original(candidate)
            if candidate == path and not swapped:
                changed = copy.deepcopy(self.profile)
                changed['id'] += '.ChangedAfterRead'
                path.write_text(json.dumps(changed))
                swapped.append(True)
            return content

        with patch.object(Path, 'read_bytes', read_then_swap):
            with self.assertRaisesRegex(model.TaskError, '[Ss]ource changed'):
                model.compile_plan(path)

    def test_hardware_mode_and_unmarked_real_input_are_rejected(self):
        self.bind()
        for field, value in [('mode', 'hardware'), ('synthetic', False)]:
            profile = copy.deepcopy(self.profile)
            profile[field] = value
            with self.subTest(field=field):
                with self.assertRaises(model.TaskError):
                    model.compile_plan(profile)

    def test_reaction_materials_and_output_places_cannot_alias(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['input_material', 'product_material', 'output_place', 'duplicate_branch']:
            self.profile = copy.deepcopy(baseline)
            first, second = self.profile['branches'][:2]
            if mutation == 'input_material':
                second['input_material_id'] = first['input_material_id']
            elif mutation == 'product_material':
                second['product_material_id'] = first['product_material_id']
            elif mutation == 'output_place':
                second['output_location'] = copy.deepcopy(first['output_location'])
            else:
                self.profile['branches'].append(copy.deepcopy(first))
            with self.subTest(mutation=mutation):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_same_local_output_slot_in_another_rack_is_a_distinct_place(self):
        first, second = self.profile['branches'][:2]
        second['output_location'] = copy.deepcopy(first['output_location'])
        second['output_location']['rack_id'] = 'SYN.AnotherProductRack'
        self.assertTrue(self.compile()['planning_complete'])

    def test_cell_count_rejects_booleans_nonfinite_fractional_and_volume_units(self):
        baseline = copy.deepcopy(self.profile)
        for field, value in [
            ('value', True), ('value', float('nan')), ('value', float('inf')),
            ('value', 0), ('value', -1), ('value', 1.5), ('unit', 'uL'),
        ]:
            self.profile = copy.deepcopy(baseline)
            self.profile['branches'][0]['input_amount'][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_unknown_input_count_is_open_and_is_not_reported_as_zero(self):
        amount = self.profile['branches'][0]['input_amount']
        amount['value'] = None
        amount['basis'] = 'unknown'
        plan = self.compile()
        self.assertFalse(plan['planning_complete'])
        self.assertFalse(plan['execution_ready'])
        self.assertTrue(any('input_amount' in item['path'] for item in plan['open_requirements']))
        self.assertIsNone(plan['branches'][0]['input_amount']['value'])

    def test_input_is_separate_and_products_have_distinct_retained_lineages(self):
        plan = self.compile()
        branches = {branch['role']: branch for branch in plan['branches']}
        self.assertEqual(set(branches), {'reference', 'negative_control', 'input'})
        for role, branch in branches.items():
            operations = [step['operation'] for step in branch['steps']]
            self.assertEqual(operations[-1], 'handover_qc')
            self.assertNotEqual(branch['input_material_id'], branch['product_material_id'])
            if role == 'input':
                self.assertIn('sonicate_input', operations)
                self.assertIn('check_input_size', operations)
                self.assertNotIn('activate_digest', operations)
            else:
                self.assertIn('activate_digest', operations)
                self.assertIn('stop_reaction', operations)
                release = next(step for step in branch['steps'] if step['operation'] == 'isolate_product')
                self.assertEqual(release['retained_fraction'], 'supernatant')

    def test_missing_or_unknown_parameter_stays_open_without_silent_defaults(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['missing', 'unknown']:
            self.profile = copy.deepcopy(baseline)
            values = self.profile['branches'][0]['parameter_values']['activate_digest']
            if mutation == 'missing':
                del values['duration_s']
            else:
                values['duration_s']['value'] = None
                values['duration_s']['basis'] = 'unknown'
            with self.subTest(mutation=mutation):
                plan = self.compile()
                self.assertFalse(plan['planning_complete'])
                self.assertTrue(any('activate_digest' in item['path'] and 'duration_s' in item['path']
                                    for item in plan['open_requirements']))

    def test_parameter_fact_requires_provenance_and_consistent_units(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['missing_basis', 'false_unknown', 'wrong_unit', 'unknown_reference', 'noninteger_cycles']:
            self.profile = copy.deepcopy(baseline)
            values = self.profile['branches'][0]['parameter_values']
            fact = values['activate_digest']['duration_s']
            if mutation == 'missing_basis':
                del fact['basis']
            elif mutation == 'false_unknown':
                fact['basis'] = 'unknown'
            elif mutation == 'wrong_unit':
                fact['unit'] = 'uL'
            elif mutation == 'unknown_reference':
                fact['source_refs'] = ['unregistered_source']
            else:
                values['wash_column']['cycles']['value'] = 1.5
            with self.subTest(mutation=mutation):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_wrong_control_input_or_antibody_role_is_rejected(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['control_role', 'input_workflow', 'reference_antibody', 'missing_input', 'ntc_role']:
            self.profile = copy.deepcopy(baseline)
            if mutation == 'control_role':
                self.profile['branches'][1]['role'] = 'reference'
            elif mutation == 'input_workflow':
                self.profile['branches'][2]['workflow'] = 'cutrun'
            elif mutation == 'reference_antibody':
                self.profile['branches'][0]['material_bindings']['primary_antibody'] = 'igg_antibody'
            elif mutation == 'missing_input':
                self.profile['branches'].pop()
            else:
                self.profile['qc']['ntc']['role'] = 'negative_control'
            with self.subTest(mutation=mutation):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_qc_requires_selected_methods_and_correct_reaction_references(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['fluorometry_only', 'library_qc', 'wrong_input', 'wrong_reference', 'wrong_target']:
            self.profile = copy.deepcopy(baseline)
            qc = self.profile['qc']
            if mutation == 'fluorometry_only':
                qc['methods'] = ['fluorometry']
            elif mutation == 'library_qc':
                qc['methods'] = ['library_fragment_analysis', 'fluorometry']
            elif mutation == 'wrong_input':
                qc['input_branch_id'] = qc['reference_branch_id']
            elif mutation == 'wrong_reference':
                qc['reference_branch_id'] = qc['negative_branch_id']
            else:
                qc['target'] = 'PATZ1'
            with self.subTest(mutation=mutation):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_wrong_retained_fraction_is_rejected_at_product_transitions(self):
        baseline = copy.deepcopy(self.protocol)
        for phase in ['release_fragments', 'isolate_product', 'bind_column', 'wash_column', 'dry_column', 'elute', 'handover_qc']:
            self.protocol = copy.deepcopy(baseline)
            self.protocol['operations'][phase]['retained_fraction'] = 'cells'
            with self.subTest(phase=phase):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_missing_stop_or_input_sonication_phase_is_rejected(self):
        baseline = copy.deepcopy(self.protocol)
        for workflow, phase in [('cutrun', 'stop_reaction'), ('input', 'sonicate_input'), ('input', 'check_input_size'),
                                ('cutrun', 'dry_column'), ('input', 'dry_column')]:
            self.protocol = copy.deepcopy(baseline)
            self.protocol['workflows'][workflow]['steps'].remove(phase)
            with self.subTest(workflow=workflow, phase=phase):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_repinned_protocol_cannot_remove_mandatory_operation_parameters(self):
        original_protocol = copy.deepcopy(self.protocol)
        original_profile = copy.deepcopy(self.profile)
        for phase in ['activate_digest', 'stop_reaction', 'check_input_size']:
            self.protocol = copy.deepcopy(original_protocol)
            self.profile = copy.deepcopy(original_profile)
            self.protocol['operations'][phase]['parameters'] = []
            for branch in self.profile['branches']:
                if phase in branch['parameter_values']:
                    branch['parameter_values'][phase] = {}
            with self.subTest(phase=phase):
                with self.assertRaisesRegex(model.TaskError, '[Mm]andatory.*parameter'):
                    self.compile()

    def test_repinned_protocol_cannot_remove_column_labware_requirements(self):
        self.protocol['operations']['bind_column']['required_labware'] = ['tube_1_5ml']
        centrifuge = next(provider for provider in self.profile['providers']
                          if provider['id'] == 'SYN.CooledCentrifuge')
        centrifuge['labware'] = ['tube_1_5ml']
        with self.assertRaises(model.TaskError):
            self.compile()

    def test_input_size_range_must_stay_below_selected_cleanup_limit(self):
        baseline = copy.deepcopy(self.profile)
        limit = self.protocol['input_size_contract']['maximum_exclusive_bp']['value']
        for maximum in [limit, limit + 1]:
            self.profile = copy.deepcopy(baseline)
            size = self.profile['branches'][2]['parameter_values']['check_input_size']
            size['size_max_bp']['value'] = maximum
            with self.subTest(maximum=maximum):
                with self.assertRaises(model.TaskError):
                    self.compile()
        self.profile = copy.deepcopy(baseline)
        self.profile['branches'][2]['parameter_values']['check_input_size']['size_max_bp']['value'] = limit - 1
        self.assertTrue(self.compile()['planning_complete'])

    def test_unknown_input_cleanup_size_limit_cannot_complete_planning(self):
        limit = self.protocol['input_size_contract']['maximum_exclusive_bp']
        limit['value'] = None
        limit['basis'] = 'unknown'
        plan = self.compile()
        self.assertFalse(plan['planning_complete'])
        self.assertFalse(plan['execution_ready'])
        self.assertTrue(any('maximum_exclusive_bp' in item['path'] for item in plan['open_requirements']))

    def test_software_hold_cannot_replace_stopping_and_input_cannot_be_activated(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['software_hold', 'active_input', 'wrong_stop_material', 'stop_volume_mismatch']:
            self.profile = copy.deepcopy(baseline)
            stop = self.profile['stop_plan']
            if mutation == 'software_hold':
                stop['software_hold_is_chemical_stop']['value'] = True
            elif mutation == 'active_input':
                stop['active_branch_ids'].append(self.profile['branches'][2]['id'])
            elif mutation == 'wrong_stop_material':
                stop['material_id'] = 'eluent'
            else:
                stop['dose_per_branch_ul']['value'] += 1
            with self.subTest(mutation=mutation):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_missing_stop_access_mixing_fallback_or_throughput_blocks_complete_plan(self):
        baseline = copy.deepcopy(self.profile)
        for field in ['access', 'mixing', 'manual_fallback', 'time_budget_s']:
            self.profile = copy.deepcopy(baseline)
            self.profile['stop_plan'][field]['value'] = 1 if field == 'time_budget_s' else False
            with self.subTest(field=field):
                try:
                    plan = self.compile()
                except model.TaskError:
                    continue
                self.assertFalse(plan['planning_complete'])
                self.assertFalse(plan['execution_ready'])
                self.assertTrue(plan['open_requirements'])

    def test_provider_capability_labware_and_numeric_limits_are_enforced(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ['wrong_capability', 'wrong_labware', 'rcf', 'temperature', 'volume', 'qualified']:
            self.profile = copy.deepcopy(baseline)
            providers = {provider['id']: provider for provider in self.profile['providers']}
            centrifuge = providers['SYN.CooledCentrifuge']
            if mutation == 'wrong_capability':
                self.profile['capability_bindings']['reaction_stopping'] = 'SYN.Sonicator'
            elif mutation == 'wrong_labware':
                centrifuge['labware'].remove('spin_column')
            elif mutation == 'rcf':
                centrifuge['limits']['rcf_x_g']['max']['value'] = 16000
            elif mutation == 'temperature':
                centrifuge['limits']['temperature_deg_c']['min']['value'] = 10
            elif mutation == 'volume':
                providers['SYN.ManualBench']['limits']['volume_ul']['max']['value'] = 20
            else:
                centrifuge['status'] = 'qualified'
            with self.subTest(mutation=mutation):
                with self.assertRaises(model.TaskError):
                    self.compile()

    def test_missing_provider_binding_stays_open_while_unknown_provider_is_rejected(self):
        del self.profile['capability_bindings']['reaction_stopping']
        plan = self.compile()
        self.assertFalse(plan['planning_complete'])
        self.assertTrue(any('stop_reaction.provider' in item['path'] for item in plan['open_requirements']))
        self.profile['capability_bindings']['reaction_stopping'] = 'UNREGISTERED.Provider'
        with self.assertRaises(model.TaskError):
            self.compile()

    def test_comparison_revision_cannot_be_presented_as_historical_study_evidence(self):
        fact = self.profile['source_binding']['historical_sop_revision']
        fact['value'] = '09/2026'
        fact['basis'] = 'publication_reported'
        fact['source_refs'] = ['tp73_paper']
        with self.assertRaises(model.TaskError):
            self.compile()

    def test_stop_service_budget_cannot_omit_required_branch_service_time(self):
        stop = self.profile['stop_plan']
        stop['service_time_per_branch_s']['value'] = 1
        stop['time_budget_s']['value'] = 2
        for branch in self.profile['branches']:
            if branch['workflow'] == 'cutrun':
                branch['parameter_values']['stop_reaction']['duration_s']['value'] = 60
        with self.assertRaises(model.TaskError):
            self.compile()

    def test_qc_withdrawals_are_planned_from_products_without_debiting_originals(self):
        plan = self.compile()
        products = {branch['product_material_id']: branch['vessels']['product']
                    for branch in self.profile['branches']}
        originals = {branch['input_material_id'] for branch in self.profile['branches']}
        withdrawals = plan['qc']['planned_withdrawals']
        self.assertTrue(withdrawals)
        for withdrawal in withdrawals:
            self.assertIn(withdrawal['parent_material_id'], products)
            self.assertNotIn(withdrawal['parent_material_id'], originals)
            self.assertEqual(withdrawal['source_vessel_id'], products[withdrawal['parent_material_id']])
            self.assertEqual(withdrawal['amount']['unit'], 'uL')
            self.assertEqual(withdrawal['amount']['basis'], 'synthetic_assumption')
            self.assertFalse(plan['execution_ready'])
        self.assertTrue(all(value is False for value in plan['effects'].values()))

    def test_combined_qc_aliquots_cannot_exceed_proposed_product_elution(self):
        elution = self.profile['branches'][0]['parameter_values']['elute']['volume_ul']['value']
        self.profile['qc']['aliquot_volumes_ul']['fluorometry']['value'] = elution
        self.assertGreater(self.profile['qc']['aliquot_volumes_ul']['qpcr']['value'], 0)
        with self.assertRaisesRegex(model.TaskError, 'QC aliquots exceed'):
            self.compile()

    def test_unknown_required_stop_fact_stays_open_without_assuming_a_stop_route(self):
        baseline = copy.deepcopy(self.profile)
        for field in ['access', 'mixing', 'manual_fallback', 'dose_per_branch_ul',
                      'time_budget_s', 'service_time_per_branch_s']:
            self.profile = copy.deepcopy(baseline)
            self.profile['stop_plan'][field]['value'] = None
            self.profile['stop_plan'][field]['basis'] = 'unknown'
            with self.subTest(field=field):
                plan = self.compile()
                self.assertFalse(plan['planning_complete'])
                self.assertFalse(plan['execution_ready'])
                self.assertTrue(any(item['path'] == 'stop_plan.' + field for item in plan['open_requirements']))
                self.assertIsNone(plan['stop_plan'][field]['value'])

    def test_compile_is_detached_and_has_no_inventory_or_device_effects(self):
        self.bind()
        before = copy.deepcopy(self.profile)
        files = {str(path.relative_to(self.root)): sha(path)
                 for path in self.root.rglob('*') if path.is_file()}
        with (
            patch('manual_tasks.Journal.__init__', side_effect=AssertionError('Journal construction')),
            patch('manual_tasks.Journal.create', side_effect=AssertionError('Journal creation')),
            patch('manual_tasks.Journal.append', side_effect=AssertionError('Journal write')),
            patch('sqlite3.connect', side_effect=AssertionError('Database effect')),
            patch('socket.socket', side_effect=AssertionError('Network effect')),
            patch('subprocess.run', side_effect=AssertionError('Device/CAD effect')),
        ):
            plan = model.compile_plan(self.profile)
        self.assertEqual(self.profile, before)
        self.assertEqual(files, {str(path.relative_to(self.root)): sha(path)
                                for path in self.root.rglob('*') if path.is_file()})
        original = copy.deepcopy(plan)
        plan['assumptions'].clear()
        plan['effects']['test_mutation'] = True
        self.assertEqual(model.compile_plan(self.profile), original)


class CutrunCliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, '-B', str(ROOT / 'scripts/prepare_cutrun_automation.py'), *arguments],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_default_output_is_complete_synthetic_json_without_execution(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertTrue(plan['planning_complete'])
        self.assertFalse(plan['execution_ready'])
        result = self.run_cli('--require-complete')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['execution_ready'])

    def test_require_complete_returns_two_for_an_explicitly_unknown_required_input(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'exports') as directory:
            profile = json.loads(model.SOURCE.read_text())
            profile['branches'][0]['input_amount']['value'] = None
            profile['branches'][0]['input_amount']['basis'] = 'unknown'
            path = Path(directory) / 'incomplete-profile.json'
            path.write_text(json.dumps(profile) + '\n')
            original = path.read_bytes()
            result = self.run_cli('--profile', str(path), '--require-complete')
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            plan = json.loads(result.stdout)
            self.assertFalse(plan['planning_complete'])
            self.assertFalse(plan['execution_ready'])
            self.assertTrue(plan['open_requirements'])
            self.assertEqual(path.read_bytes(), original)

    def test_reports_are_written_only_to_explicit_ignored_exports(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'exports') as directory:
            path = Path(directory) / 'plan.json'
            result = self.run_cli('--out', str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text()), json.loads(result.stdout))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            result = self.run_cli('--out', str(path))
            self.assertEqual(result.returncode, 1)
            self.assertIn('error', json.loads(result.stdout))
            self.assertFalse(path.exists())

    def test_execution_argument_is_not_supported(self):
        result = self.run_cli('--execute')
        self.assertEqual(result.returncode, 1)
        self.assertIn('error', json.loads(result.stdout))

    def test_output_never_overwrites_existing_files_or_escapes_through_symlinks(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'exports') as directory:
            path = Path(directory) / 'existing.json'
            original = b'{"existing": "preserve these bytes"}\n'
            path.write_bytes(original)
            result = self.run_cli('--out', str(path))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(path.read_bytes(), original)
            wrong_suffix = Path(directory) / 'not-a-json-report.sqlite3'
            result = self.run_cli('--out', str(wrong_suffix))
            self.assertEqual(result.returncode, 1)
            self.assertFalse(wrong_suffix.exists())
            with tempfile.TemporaryDirectory() as outside:
                link = Path(directory) / 'outside'
                link.symlink_to(Path(outside), target_is_directory=True)
                result = self.run_cli('--out', str(link / 'plan.json'))
                self.assertEqual(result.returncode, 1)
                self.assertFalse((Path(outside) / 'plan.json').exists())


if __name__ == '__main__':
    unittest.main()
