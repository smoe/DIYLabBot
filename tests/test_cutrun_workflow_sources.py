"""Execution fixtures preserve E1 provenance before creating any journal run."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cutrun_preparation
import cutrun_workflow_sources as sources
from cutrun_workflow import CutRunWorkflow
from manual_tasks import Journal, TaskError

try:
    from jsonschema import Draft202012Validator, ValidationError
    from referencing import Registry, Resource
except ImportError:
    Draft202012Validator = None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CutrunWorkflowSourcesTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(sources.SOURCE.read_text())

    def assert_invalid_before_creation(self, profile):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / 'tasks.sqlite3') as journal:
                with self.assertRaises(TaskError):
                    CutRunWorkflow.create(journal, source=profile, run_id='SYN.Source.Invalid')
                for table in ['runs', 'events', 'resources', 'artifacts']:
                    self.assertEqual(journal.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_default_definition_has_closed_versions_roles_and_source_pins(self):
        definition = sources.load()
        self.assertEqual(definition['format'], 'solidcraftbot.material-workflow-definition/2')
        self.assertEqual(definition['profile']['type'], 'cutrun_synthetic/1')
        self.assertEqual(definition['clock_mode'], 'synthetic_intervals/1')
        self.assertEqual(definition['preparation_plan']['format'], 'solidcraftbot.cutrun-preparation-plan/2')
        self.assertFalse(definition['preparation_plan']['execution_ready'])
        self.assertEqual(len(definition['initial_materials']), 7)
        self.assertEqual(len(definition['material_allocations']), 4)
        self.assertEqual(len(definition['protective_stop_bindings']), 2)
        for name in sources.RUNTIME:
            self.assertIn(name, definition['runtime_source_files'])
            self.assertEqual(definition['source_files_sha256'][name], sha(ROOT / name))
        self.assertEqual(definition['source_files_sha256']['model/cutrun-automation.preparation.json'],
                         sha(ROOT / 'model/cutrun-automation.preparation.json'))
        self.assertEqual(len(definition['effective_execution_profile_sha256']), 64)

    def test_all_new_fixture_numbers_retain_explicit_synthetic_fact_annotations(self):
        groups = [self.profile['settings'], self.profile['bookkeeping_volumes_ul']]
        facts = [fact for group in groups for fact in group.values()]
        facts += [mixture['quantity'] for branch in self.profile['issued_reagents'].values()
                  for mixture in branch.values()]
        for fact in facts:
            self.assertEqual(fact['basis'], 'synthetic_assumption')
            self.assertEqual(fact['source_refs'], ['synthetic_execution'])
            self.assertTrue(fact['note'])
            self.assertGreater(fact['value'], 0)
        definition = sources.load(self.profile)
        for assumption in definition['execution']['assumptions']:
            self.assertEqual(assumption['basis'], 'synthetic_assumption')
        for branch in definition['preparation_plan']['branches']:
            binding = definition['execution']['branches'][branch['id']]
            if branch['workflow'] == 'input':
                self.assertIsNone(binding['activation_material_id'])
                self.assertIsNone(binding['stop_material_id'])
            else:
                self.assertNotEqual(binding['activation_material_id'], binding['stop_material_id'])
                self.assertEqual(definition['protective_stop_bindings'][branch['vessels']['reaction']],
                                 binding['stop_material_id'])

    def test_loading_is_detached_and_has_no_journal_database_network_or_file_writes(self):
        original = copy.deepcopy(self.profile)
        with (
            patch('manual_tasks.Journal.__init__', side_effect=AssertionError('Journal construction')),
            patch('sqlite3.connect', side_effect=AssertionError('Database effect')),
            patch('socket.socket', side_effect=AssertionError('Network effect')),
            patch('subprocess.run', side_effect=AssertionError('Process effect')),
            patch.object(Path, 'write_bytes', side_effect=AssertionError('Source write')),
            patch.object(Path, 'write_text', side_effect=AssertionError('Source write')),
        ):
            definition = sources.load(self.profile)
        self.assertEqual(self.profile, original)
        expected = copy.deepcopy(definition)
        definition['execution']['bookkeeping_volumes_ul']['reaction'] = 99999
        definition['initial_materials'][0]['quantity']['value'] = 0
        definition['execution_profile']['settings']['stop_window_s']['value'] = 1
        self.assertEqual(sources.load(self.profile), expected)

    def test_invalid_versions_mode_and_preparation_pins_leave_no_run(self):
        for mutation in ['format', 'mode', 'real', 'pin', 'missing_pin', 'unknown_field']:
            profile = copy.deepcopy(self.profile)
            if mutation == 'format':
                profile['format'] = 'solidcraftbot.cutrun-synthetic-run/2'
            elif mutation == 'mode':
                profile['mode'] = 'hardware'
            elif mutation == 'real':
                profile['synthetic'] = False
            elif mutation == 'pin':
                profile['preparation']['source_sha256'] = '0' * 64
            elif mutation == 'missing_pin':
                del profile['preparation']['source_sha256']
            else:
                profile['execute_hardware'] = True
            with self.subTest(mutation=mutation):
                self.assert_invalid_before_creation(profile)

    def test_impossible_stop_window_and_serial_task_budget_leave_no_run(self):
        for field, value in [('stop_window_s', 60), ('stop_window_s', 64), ('task_deadline_s', 1000)]:
            profile = copy.deepcopy(self.profile)
            profile['settings'][field]['value'] = value
            with self.subTest(field=field, value=value):
                self.assert_invalid_before_creation(profile)
        profile = copy.deepcopy(self.profile)
        profile['settings']['stop_window_s']['value'] = 70
        self.assertEqual(sources.load(profile)['execution']['stop_window_s'], 70)

    def test_unknown_or_nonfinite_model_settings_cannot_create_a_run(self):
        for mutation in ['unknown', 'wrong_unit', 'nonfinite', 'unmarked']:
            profile = copy.deepcopy(self.profile)
            fact = profile['settings']['phase_tolerance_s']
            if mutation == 'unknown':
                fact.update(value=None, basis='unknown')
            elif mutation == 'wrong_unit':
                fact['unit'] = 'uL'
            elif mutation == 'nonfinite':
                fact['value'] = float('nan')
            else:
                fact['basis'] = 'publication_reported'
            with self.subTest(mutation=mutation):
                self.assert_invalid_before_creation(profile)

    def test_missing_shared_or_insufficient_issued_aliquots_leave_no_run(self):
        active = list(self.profile['issued_reagents'])
        for mutation in ['missing_branch', 'missing_activation', 'shared_material', 'shared_vessel', 'insufficient']:
            profile = copy.deepcopy(self.profile)
            mixtures = profile['issued_reagents']
            if mutation == 'missing_branch':
                del mixtures[active[0]]
            elif mutation == 'missing_activation':
                del mixtures[active[0]]['activation']
            elif mutation == 'shared_material':
                mixtures[active[1]]['stop']['material_id'] = mixtures[active[0]]['stop']['material_id']
            elif mutation == 'shared_vessel':
                mixtures[active[1]]['stop']['vessel_id'] = mixtures[active[0]]['stop']['vessel_id']
            else:
                mixtures[active[0]]['activation']['quantity']['value'] = 1
            with self.subTest(mutation=mutation):
                self.assert_invalid_before_creation(profile)

    def test_fraction_vessels_cannot_alias_each_other_or_other_branch_process_vessels(self):
        plan = cutrun_preparation.compile_plan()
        first, second = plan['branches'][:2]
        for mutation in ['same_branch', 'other_branch', 'missing_branch']:
            profile = copy.deepcopy(self.profile)
            fractions = profile['fraction_vessels']
            if mutation == 'same_branch':
                fractions[first['id']]['column_residue'] = fractions[first['id']]['bead_remainder']
            elif mutation == 'other_branch':
                fractions[first['id']]['supernatant'] = second['vessels']['reaction']
            else:
                del fractions[second['id']]
            with self.subTest(mutation=mutation):
                self.assert_invalid_before_creation(profile)

    def test_bookkeeping_eluate_must_supply_both_selected_qc_aliquots(self):
        profile = copy.deepcopy(self.profile)
        profile['bookkeeping_volumes_ul']['eluate']['value'] = 2
        self.assert_invalid_before_creation(profile)

    def test_genuine_legacy_e1_sources_still_compile_but_cannot_supply_e3_activation_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory).resolve()
            folder = temporary_root / 'model'
            folder.mkdir()
            for name in cutrun_preparation.DEPENDENCIES:
                destination = temporary_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, destination)
            catalog = json.loads((ROOT / 'model/cutrun-automation.catalog.json').read_text())
            protocol = json.loads((ROOT / 'model/cutrun-automation.protocol.json').read_text())
            preparation = json.loads((ROOT / 'model/cutrun-automation.preparation.json').read_text())
            catalog['format'] = 'solidcraftbot.cutrun-catalog/1'
            catalog['materials'].pop('activation_reagent')
            catalog['materials']['stop_buffer'].update(label='CUT&RUN 4X Stop Buffer', catalog_number='48105')
            protocol['format'] = 'solidcraftbot.cutrun-preparation-protocol/1'
            protocol['required_material_roles']['cutrun'].remove('activation_reagent')
            for operation in protocol['operations'].values():
                operation.pop('reagent_role')
            preparation['format'] = 'solidcraftbot.cutrun-preparation/1'
            for branch in preparation['branches']:
                branch['material_bindings'].pop('activation_reagent', None)
            for name, document in [('catalog', catalog), ('protocol', protocol)]:
                path = folder / (name + '.json')
                path.write_text(json.dumps(document) + '\n')
                preparation[name] = {'source': str(path.relative_to(temporary_root)), 'source_sha256': sha(path)}
            path = folder / 'preparation.json'
            path.write_text(json.dumps(preparation) + '\n')
            profile = copy.deepcopy(self.profile)
            profile['preparation'] = {'source': str(path.relative_to(temporary_root)), 'source_sha256': sha(path)}
            with patch.object(cutrun_preparation, 'ROOT', temporary_root), patch.object(sources, 'ROOT', temporary_root):
                self.assertEqual(cutrun_preparation.compile_plan(path)['format'], 'solidcraftbot.cutrun-preparation-plan/1')
                self.assert_invalid_before_creation(profile)


@unittest.skipIf(Draft202012Validator is None, 'Optional jsonschema development dependency required')
class CutrunExecutionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = []
        for name in ['assembly-reference.schema.json', 'cutrun-automation.schema.json', 'cutrun-synthetic-run.schema.json']:
            path = ROOT / 'model' / name
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri()
            resources.append((schema['$id'], Resource.from_contents(schema)))
            if name == 'cutrun-synthetic-run.schema.json':
                selected = schema
        cls.validator = Draft202012Validator(selected, registry=Registry().with_resources(resources))
        cls.profile = json.loads(sources.SOURCE.read_text())

    def test_default_execution_profile_validates_without_network_references(self):
        self.validator.validate(self.profile)

    def test_unknown_unmarked_or_untyped_settings_are_rejected(self):
        for mutation in ['basis', 'unit', 'null', 'boolean']:
            profile = copy.deepcopy(self.profile)
            fact = profile['settings']['activation_service_s']
            if mutation == 'basis':
                fact['basis'] = 'owner_confirmed'
            elif mutation == 'unit':
                fact['unit'] = 'uL'
            elif mutation == 'null':
                fact.update(value=None, basis='unknown')
            else:
                fact['value'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                self.validator.validate(profile)

    def test_preparation_pin_and_per_branch_issued_mixture_shapes_are_required(self):
        active = next(iter(self.profile['issued_reagents']))
        for mutation in ['pin', 'mixture', 'vessel', 'execution']:
            profile = copy.deepcopy(self.profile)
            if mutation == 'pin':
                del profile['preparation']['source_sha256']
            elif mutation == 'mixture':
                del profile['issued_reagents'][active]['stop']
            elif mutation == 'vessel':
                del profile['issued_reagents'][active]['activation']['vessel_id']
            else:
                profile['execute_hardware'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                self.validator.validate(profile)


if __name__ == '__main__':
    unittest.main()
