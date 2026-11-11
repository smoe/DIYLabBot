"""Preparation contracts stay synthetic, source-bound and free of lab effects."""
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
import extraction_preparation as model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ('model/extraction-automation.catalog.json', 'model/extraction-automation.protocol.json',
                     'model/extraction-automation.schema.json', 'model/assembly-reference.schema.json',
                     'scripts/extraction_preparation.py', 'scripts/prepare_extraction_automation.py',
                     'scripts/assembly_model.py', 'scripts/robot_spec.py', 'scripts/manual_workflow.py', 'scripts/manual_tasks.py'):
            target = self.root / name;target.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(ROOT / name, target)
        self.profile = json.loads(model.SOURCE.read_text())
        self.catalog_path = self.root / self.profile['catalog']['source']
        self.protocol_path = self.root / self.profile['protocol']['source']
        self.catalog = json.loads(self.catalog_path.read_text());self.protocol = json.loads(self.protocol_path.read_text())
        change = patch.object(model, 'ROOT', self.root);change.start();self.addCleanup(change.stop)

    def bind(self):
        for field, value, path in (('catalog', self.catalog, self.catalog_path), ('protocol', self.protocol, self.protocol_path)):
            path.write_text(json.dumps(value, indent=2) + '\n')
            self.profile[field]['source_sha256'] = sha(path)

    def compile(self):
        self.bind();return model.compile_plan(self.profile)

    def complete(self):
        path = self.root / 'model/sops/synthetic-cell-pellets.json';path.parent.mkdir()
        path.write_text(json.dumps({'id': 'SYN.Cells', 'revision': '1', 'synthetic': True}) + '\n')
        for analyte, process in self.profile['sample_pairs'][0]['processes'].items():
            process['sop'] = {'id': 'SYN.Cells', 'revision': '1', 'source': {
                'source': str(path.relative_to(self.root)), 'source_sha256': sha(path)}}
            process['preservation_state'] = 'SYN.selected-pellet-state'
            process['input_amount'] = {'value': 1000, 'unit': 'cells'}
            for step in self.protocol['workflows'][analyte]['steps']:
                operation = self.protocol['operations'][step]
                process['parameter_values'][step] = {key: (-4 if self.protocol['parameter_units'][key] == 'degC' else 1)
                                                     for key in operation['parameters']}
                process['providers'][operation['capability']] = 'SYN.ManualProvider'

    def test_default_draft_preserves_both_lineages_and_open_inputs_without_execution(self):
        plan = self.compile();self.assertFalse(plan['planning_complete']);self.assertFalse(plan['execution_ready'])
        self.assertEqual(len(plan['lineage']), 2);self.assertTrue(plan['open_requirements'])
        self.assertEqual({edge['origin_id'] for edge in plan['lineage']}, {'SYN.Source01'})
        self.assertEqual(len({edge['input_id'] for edge in plan['lineage']}), 2)
        self.assertEqual(len({edge['product_id'] for edge in plan['lineage']}), 2)
        self.assertTrue(all(value is False for value in plan['effects'].values()))
        rna = plan['sample_pairs'][0]['processes']['rna']
        self.assertEqual(next(s for s in rna['steps'] if s['operation'] == 'remove_gdna')['retained_fraction'], 'flow_through')
        self.assertEqual(rna['provisional_role_bindings']['lysate_container']['instance_id'], rna['item_bindings']['input_vessel']['instance_id'])
        self.assertTrue(all('quantity' not in item for item in rna['material_requirements']))

    def test_complete_inputs_remain_planning_only_and_cf01_is_only_a_proposal(self):
        self.complete()
        for process in self.profile['sample_pairs'][0]['processes'].values():
            process['providers']['column_centrifugation'] = 'CF01'
        plan = self.compile();self.assertTrue(plan['planning_complete']);self.assertFalse(plan['execution_ready'])
        self.assertEqual(plan['open_requirements'], [])
        self.assertIn('extraction_execution_unimplemented', plan['execution_blockers'])
        self.assertTrue(all(step['provider']['status'] == 'proposed_unvalidated'
                            for pair in plan['sample_pairs'] for p in pair['processes'].values() for step in p['steps']))
        self.assertTrue(any(name.endswith('synthetic-cell-pellets.json') for name in plan['source_files_sha256']))

    def test_missing_step_null_step_and_null_values_all_remain_open(self):
        self.complete();process = self.profile['sample_pairs'][0]['processes']['rna']
        for value in ('absent', None, {k: None for k in self.protocol['operations']['elute']['parameters']}):
            if value == 'absent':process['parameter_values'].pop('elute', None)
            else:process['parameter_values']['elute'] = value
            with self.subTest(value=value):
                plan = self.compile();self.assertFalse(plan['planning_complete'])
                self.assertEqual(sum('.rna.parameter_values.elute.' in r['path'] for r in plan['open_requirements']), 3)

    def test_reference_pin_changes_and_missing_pin_are_rejected(self):
        self.bind()
        for mutation in ('stale', 'missing'):
            profile = copy.deepcopy(self.profile)
            if mutation == 'stale':profile['catalog']['source_sha256'] = '0' * 64
            else:del profile['catalog']['source_sha256']
            with self.subTest(mutation=mutation), self.assertRaises(model.TaskError):model.compile_plan(profile)

    def test_profile_swap_between_parse_and_pin_cannot_hide_changed_bytes(self):
        self.bind();path = self.root/'model/request.json';path.write_text(json.dumps(self.profile))
        original = Path.read_bytes;swapped = []
        def read_then_swap(value):
            content = original(value)
            if value == path and not swapped:
                changed = copy.deepcopy(self.profile);changed['id'] = 'SYN.ChangedAfterRead'
                path.write_text(json.dumps(changed));swapped.append(True)
            return content
        with patch.object(Path, 'read_bytes', read_then_swap), self.assertRaisesRegex(model.TaskError, 'source changed'):
            model.compile_plan(path)

    def test_catalog_controls_sku_metadata_without_a_second_code_register(self):
        self.catalog['kits']['rneasy_protect_cell_74624']['catalog_number'] = '12345'
        plan = self.compile()
        self.assertEqual(plan['sample_pairs'][0]['processes']['rna']['kit']['catalog_number'], '12345')

    def test_dna_rna_kit_swap_and_duplicate_analyte_are_rejected(self):
        original = copy.deepcopy(self.protocol)
        self.protocol['workflows']['rna']['kit_id'] = self.protocol['workflows']['dna']['kit_id']
        with self.assertRaisesRegex(model.TaskError, 'wrong kit/analyte'):self.compile()
        self.protocol = original;self.catalog['kits']['dneasy_blood_tissue_69504']['analyte'] = 'rna'
        with self.assertRaises(model.TaskError):self.compile()

    def test_global_ids_and_pairing_cannot_alias_materials_or_vessels(self):
        baseline = copy.deepcopy(self.profile)
        for mutation in ('input', 'product_vessel', 'origin', 'second_pair'):
            self.profile = copy.deepcopy(baseline);pair = self.profile['sample_pairs'][0]
            if mutation == 'input':pair['dna_input_id'] = pair['rna_input_id']
            elif mutation == 'product_vessel':pair['processes']['dna']['items']['input_vessel'] = pair['rna_product_id']
            elif mutation == 'origin':pair['rna_input_id'] = pair['origin_id']
            else:self.profile['sample_pairs'].append(copy.deepcopy(pair))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(model.TaskError, 'Reused'):self.compile()

    def test_rna_gdna_flow_through_has_a_distinct_required_collection_vessel(self):
        items = self.profile['sample_pairs'][0]['processes']['rna']['items'];original = copy.deepcopy(items)
        items['gdna_collection_vessel'] = items['collection_vessel']
        with self.assertRaisesRegex(model.TaskError, 'Reused'):self.compile()
        items.clear();items.update(original);del items['gdna_collection_vessel']
        with self.assertRaises(model.TaskError):self.compile()

    def test_output_places_are_unique_by_rack_instance_and_slot(self):
        processes = self.profile['sample_pairs'][0]['processes']
        processes['dna']['output_location'] = copy.deepcopy(processes['rna']['output_location'])
        with self.assertRaisesRegex(model.TaskError, 'Duplicate output'):self.compile()
        processes['dna']['output_location']['rack_id'] = 'SYN.OtherRack'
        self.assertFalse(self.compile()['execution_ready'])

    def test_missing_or_reordered_mandatory_phases_are_rejected(self):
        original = copy.deepcopy(self.protocol)
        for phase in ('remove_gdna', 'wash_column', 'dry_column', 'condition_binding'):
            self.protocol = copy.deepcopy(original);self.protocol['workflows']['rna']['steps'].remove(phase)
            with self.subTest(phase=phase), self.assertRaisesRegex(model.TaskError, 'mandatory phase'):self.compile()
        self.protocol = copy.deepcopy(original);steps = self.protocol['workflows']['dna']['steps']
        i,j=steps.index('elute'),steps.index('bind_column');steps[i],steps[j]=steps[j],steps[i]
        with self.assertRaises(model.TaskError):self.compile()

    def test_dna_rnase_decision_after_lysis_is_rejected(self):
        steps = self.protocol['workflows']['dna']['steps'];steps.remove('decide_rnase')
        steps.insert(steps.index('lyse_homogenize') + 1, 'decide_rnase')
        with self.assertRaisesRegex(model.TaskError, 'decide_rnase before lyse_homogenize'):self.compile()

    def test_discarding_rna_gdna_flow_through_or_column_fraction_is_rejected(self):
        original = copy.deepcopy(self.protocol)
        for phase in ('remove_gdna', 'bind_column', 'wash_column', 'dry_column', 'elute'):
            self.protocol = copy.deepcopy(original);self.protocol['operations'][phase]['retained_fraction'] = 'input'
            with self.subTest(phase=phase), self.assertRaisesRegex(model.TaskError, 'retained fraction'):self.compile()

    def test_units_partial_maps_unknown_parameters_and_provider_qualification_are_rejected(self):
        self.complete();baseline = copy.deepcopy(self.profile);original = copy.deepcopy(self.protocol)
        for mutation in ('unit', 'partial', 'unknown_parameter', 'provider', 'unknown_provider', 'unknown_step'):
            self.profile = copy.deepcopy(baseline);self.protocol = copy.deepcopy(original)
            p = self.profile['sample_pairs'][0]['processes']['rna']
            if mutation == 'unit':self.protocol['parameter_units']['rcf_x_g'] = 's'
            elif mutation == 'partial':del p['parameter_values']['elute']['duration_s']
            elif mutation == 'unknown_parameter':p['parameter_values']['elute']['volume_ml'] = 1
            elif mutation == 'provider':p['providers']['column_centrifugation'] = {'instance_id':'CF01','qualified':True}
            elif mutation == 'unknown_provider':p['providers']['real_qualified'] = 'CF01'
            else:p['parameter_values']['execute_robot'] = {}
            with self.subTest(mutation=mutation), self.assertRaises(model.TaskError):self.compile()

    def test_boolean_nonfinite_and_fractional_counts_are_rejected_but_celsius_can_be_negative(self):
        self.complete();baseline = copy.deepcopy(self.profile)
        for parameter, value in [('volume_ul', True), ('volume_ul', float('nan')), ('volume_ul', float('inf')),
                                 ('volume_ul', 0), ('cycles', 1.5), ('cycles', False), ('duration_s', -1)]:
            self.profile = copy.deepcopy(baseline);p = self.profile['sample_pairs'][0]['processes']['rna']
            step = 'wash_column' if parameter == 'cycles' else 'bind_column'
            p['parameter_values'][step][parameter] = value
            with self.subTest(parameter=parameter, value=value), self.assertRaises(model.TaskError):self.compile()
        self.profile = baseline;self.assertTrue(self.compile()['planning_complete'])

    def test_input_amount_unit_finite_number_and_integer_cell_count_are_checked(self):
        original = copy.deepcopy(self.profile)
        for amount in ({'value':1,'unit':'uL'}, {'value':True,'unit':'mg'}, {'value':float('nan'),'unit':'mg'},
                       {'value':1.5,'unit':'cells'}, {'value':0,'unit':'cells'}, {'value':-1,'unit':'mg'}):
            self.profile = copy.deepcopy(original);self.profile['sample_pairs'][0]['processes']['dna']['input_amount'] = amount
            with self.subTest(amount=amount), self.assertRaises(model.TaskError):self.compile()
        for amount in ({'value':1.5,'unit':'mg'}, {'value':1000.0,'unit':'cells'}):
            self.profile = copy.deepcopy(original);self.profile['sample_pairs'][0]['processes']['dna']['input_amount'] = amount
            self.assertFalse(self.compile()['execution_ready'])

    def test_sop_content_identity_revision_and_pins_are_required(self):
        self.complete();baseline = copy.deepcopy(self.profile)
        for mutation in ('id', 'revision', 'pin', 'catalog_as_sop'):
            self.profile = copy.deepcopy(baseline);sop = self.profile['sample_pairs'][0]['processes']['rna']['sop']
            if mutation == 'id':sop['id'] = 'OTHER'
            elif mutation == 'revision':sop['revision'] = '2'
            elif mutation == 'pin':sop['source']['source_sha256'] = '0' * 64
            else:sop['source'] = copy.deepcopy(self.profile['catalog'])
            with self.subTest(mutation=mutation), self.assertRaises(model.TaskError):self.compile()

    def test_snapshot_and_return_values_do_not_alias_and_there_are_no_runtime_effects(self):
        self.bind();before = copy.deepcopy(self.profile);files = {str(p):sha(p) for p in self.root.rglob('*') if p.is_file()}
        with (patch('manual_tasks.Journal.create', side_effect=AssertionError('Journal effect')),
              patch('manual_tasks.Journal.append', side_effect=AssertionError('Journal effect')),
              patch('sqlite3.connect', side_effect=AssertionError('Database effect')),
              patch('socket.socket', side_effect=AssertionError('Network effect')),
              patch('subprocess.run', side_effect=AssertionError('Device/CAD effect'))):
            plan = model.compile_plan(self.profile)
        self.assertEqual(self.profile, before)
        self.assertEqual(files, {str(p):sha(p) for p in self.root.rglob('*') if p.is_file()})
        plan['sample_pairs'][0]['processes']['rna']['kit']['name'] = 'mutated result'
        second = model.compile_plan(self.profile)
        self.assertNotEqual(second['sample_pairs'][0]['processes']['rna']['kit']['name'], 'mutated result')
        for name in ('scripts/assembly_model.py','scripts/robot_spec.py','scripts/manual_tasks.py','scripts/manual_workflow.py'):
            self.assertIn(name, second['source_files_sha256'])


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(ROOT/'scripts/prepare_extraction_automation.py'), *arguments],
                              cwd=ROOT, capture_output=True, text=True)

    def test_default_draft_is_json_and_complete_mode_exits_two(self):
        result = self.run_cli();self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['planning_complete'])
        result = self.run_cli('--require-complete');self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)['execution_ready'])

    def test_output_is_only_written_under_ignored_exports_and_invalid_args_exit_one(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'exports') as directory:
            path = Path(directory)/'plan.json';result = self.run_cli('--out', str(path))
            self.assertEqual(result.returncode, 0, result.stderr);self.assertEqual(json.loads(path.read_text()), json.loads(result.stdout))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'plan.json';result = self.run_cli('--out', str(path))
            self.assertEqual(result.returncode, 1);self.assertIn('error', json.loads(result.stdout));self.assertFalse(path.exists())
        result = self.run_cli('--execute');self.assertEqual(result.returncode, 1);self.assertIn('error', json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
