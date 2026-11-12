"""Prospective recipe sources never turn manufacturer examples into local doses."""
import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cutrun_manual_recipe_sources as sources
from manual_tasks import Journal,TaskError,digest
import test_cutrun_manual_sop_sources as sop_tests
try:
    import jsonschema
except ImportError:
    jsonschema=None


class RecipeSourceTests(unittest.TestCase):
    def setUp(self):
        self.sop=sop_tests.SopSourceTests('test_defaults_keep_all_phase_values_unknown_without_effects');self.sop.setUp()
        self.addCleanup(self.sop.doCleanups);self.fixture=self.sop.fixture
        self.profile=json.loads(sources.SOURCE.read_text())
        self.names=('scripts/cutrun_manual_recipe_sources.py',sources.PROTOCOL,
            'model/cutrun-manual-recipe.profile.json',sources.PROFILE_SCHEMA,sources.PROTOCOL_SCHEMA)
        for name in self.names:
            target=self.fixture/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
        protocol=json.loads((self.fixture/sources.PROTOCOL).read_text())
        protocol['manufacturer']['source_sha256']=digest(self.sop.base.original.read_bytes())
        (self.fixture/sources.PROTOCOL).write_text(json.dumps(protocol))
        self.protocol=protocol
        for name,value in [('ROOT',self.fixture),('RUNTIME',self.names)]:
            p=patch.object(sources,name,value);p.start();self.addCleanup(p.stop)

    def confirmed(self):
        profile=copy.deepcopy(self.profile)
        profile['incoming_preparation'].update(mode='external',evidence_ref='decision_evidence')
        profile['permeabilization'].update(mode='external',evidence_ref='decision_evidence')
        for identity,binding in profile['roles'].items():
            binding.update(mode='issued',material_id='Test.Recipe.'+identity,vessel_id='Test.ReagentTube.'+identity,
                           lot_ref='Test.Lot',preparation_ref='Test.External.Preparation',evidence_ref='decision_evidence')
        for rows in self.protocol['stage_steps'].values():
            for step in rows:
                binding=profile['steps'][step['id']]
                skip=(step['id'].startswith('S02.') or step['id'].startswith('S03.permeabilization_')
                      or step['id'] in {'S03.bead_activation_wash','S03.bead_resuspension'})
                binding.update(enabled=not skip,repeat_count=None if skip or step['kind']=='load' else step['source_facts'].get('cycles',1),evidence_ref='decision_evidence')
                if not skip and (step['reagent_role'] is not None or step['kind']=='load'):
                    binding['quantity']['value']=150 if step['kind'] in {'activation','stop'} else 10
        for branch,binding in profile['consumables'].items():
            binding.update(column_id='Test.Column.'+branch,collection_vessel_id='Test.Collection.'+branch,
                           elution_vessel_id='Test.Elution.'+branch,preparation_ref='Test.Column.Prepared',evidence_ref='decision_evidence')
        return profile

    def compile(self,profile=None,*,open_base=False):
        return sources.compile_profile({'base_profile':self.sop.base.profile if open_base else self.sop.base.confirmed(),
            'sop_profile':self.sop.profile if open_base else self.sop.confirmed(),
            'recipe_profile':self.profile if profile is None else profile},
            original_pdf=None if open_base else self.sop.base.original,evidence_files=self.sop.base.evidence_files)

    def test_default_is_read_only_archiveable_and_preserves_every_unknown_quantity(self):
        before=copy.deepcopy(self.profile)
        with patch('sqlite3.connect',side_effect=AssertionError('store effect')),patch('socket.socket',side_effect=AssertionError('network effect')):
            result=self.compile(open_base=True)
        self.assertEqual(self.profile,before);self.assertTrue(result['can_archive'])
        self.assertFalse(result['can_claim_reference_success']);self.assertFalse(result['preparation_complete'])
        self.assertFalse(any(result['stage_readiness'].values()))
        def numbers(value):
            if isinstance(value,dict):
                for item in value.values():yield from numbers(item)
            elif isinstance(value,list):
                for item in value:yield from numbers(item)
            elif type(value) in (int,float):yield value
        self.assertEqual(list(numbers(self.profile)),[])

    def test_issued_working_mixtures_do_not_require_or_invent_stock_preparation_amounts(self):
        profile=self.confirmed();result=self.compile(profile)
        self.assertEqual(result['open_requirements'],[]);self.assertTrue(all(result['stage_readiness'].values()))
        self.assertFalse(result['can_claim_reference_success'])
        self.assertTrue(all(q['value'] is None for role in result['recipe_profile']['roles'].values() for q in role['components'].values()))

    def test_working_mixture_requires_external_preparation_proof_when_issued(self):
        for field in ('preparation_ref','lot_ref','evidence_ref'):
            profile=self.confirmed();profile['roles']['working.digitonin_buffer'][field]=None
            result=self.compile(profile)
            self.assertFalse(result['stage_readiness']['S05']);self.assertFalse(result['stage_readiness']['S06'])

    def test_in_run_preparation_requires_explicit_component_and_output_plans(self):
        profile=self.confirmed();role=profile['roles']['working.antibody_buffer'];role.update(mode='prepared',lot_ref=None)
        self.assertFalse(self.compile(profile)['stage_readiness']['S03'])
        for quantity in role['components'].values():quantity['value']=1
        role['output_quantity']['value']=10
        self.assertTrue(self.compile(profile)['stage_readiness']['S03'])
        role['components']['stock.pic']['value']=None
        self.assertFalse(self.compile(profile)['stage_readiness']['S03'])

    def test_low_cell_omission_is_an_explicit_evidenced_branch_not_zero_wash_default(self):
        profile=self.confirmed();profile['incoming_preparation']['mode']='perform'
        profile['cell_wash_branch'].update(value='low_cell_omit',evidence_ref='decision_evidence')
        for identity in ('S02.initial_separation','S02.cell_resuspension'):
            profile['steps'][identity].update(enabled=True,repeat_count=1)
        profile['steps']['S02.cell_resuspension']['quantity']['value']=10
        self.assertTrue(self.compile(profile)['stage_readiness']['S02'])
        profile['cell_wash_branch']['evidence_ref']=None
        self.assertFalse(self.compile(profile)['stage_readiness']['S02'])
        profile['cell_wash_branch']['value']='standard'
        with self.assertRaises(TaskError):self.compile(profile)

    def test_source_cycle_facts_are_distinct_from_null_local_repeat_choices(self):
        self.assertIsNone(self.profile['steps']['S06.preactivation_wash']['repeat_count'])
        self.assertEqual(self.protocol['stage_steps']['S06'][1]['source_facts']['cycles'],2)
        profile=self.confirmed();profile['steps']['S06.preactivation_wash']['repeat_count']=1
        with self.assertRaises(TaskError):self.compile(profile)

    def test_loading_is_driven_by_actual_remaining_material_not_a_fixed_example_count(self):
        profile=self.confirmed();profile['steps']['S10.column_load']['repeat_count']=3
        with self.assertRaisesRegex(TaskError,'actual remaining'):self.compile(profile)
        profile['steps']['S10.column_load']['repeat_count']=None
        self.assertTrue(self.compile(profile)['stage_readiness']['S10'])

    def test_dry_spin_has_no_new_reagent_dose_or_fictitious_wash_cycle(self):
        step=next(row for row in self.protocol['stage_steps']['S10'] if row['id']=='S10.column_dry')
        self.assertIsNone(step['reagent_role']);self.assertEqual(step['actions'],['dry'])
        self.assertIsNone(self.profile['steps'][step['id']]['quantity']['value'])

    def test_activation_and_stop_reuse_existing_dose_binding_and_block_critical_preparation(self):
        for identity in ('S07.activation','S08.stop'):
            profile=self.confirmed();profile['steps'][identity]['quantity']['value']=None
            result=self.compile(profile);self.assertFalse(result['stage_readiness']['S06']);self.assertFalse(result['stage_readiness']['S07'])
            profile['steps'][identity]['quantity']['value']=1
            with self.assertRaises(TaskError):self.compile(profile)
            for field in ('enabled','evidence_ref'):
                profile=self.confirmed();profile['steps'][identity][field]=None
                profile['steps'][identity]['quantity']['value']=1
                with self.subTest(step=identity,open_field=field),self.assertRaises(TaskError):self.compile(profile)

    def test_physical_consumables_are_distinct_non_quantity_bindings(self):
        profile=self.confirmed();profile['consumables']['input']['column_id']=profile['consumables']['igg']['column_id']
        with self.assertRaises(TaskError):self.compile(profile)
        self.assertNotIn('quantity',self.profile['consumables']['input'])

    def test_permeabilization_has_explicit_external_or_in_run_reagent_scope(self):
        profile=self.confirmed();profile['permeabilization']['evidence_ref']=None
        self.assertFalse(self.compile(profile)['stage_readiness']['S03'])
        profile=self.confirmed();profile['permeabilization']['mode']='perform'
        assay=[row for row in self.protocol['stage_steps']['S03'] if row['id'].startswith('S03.permeabilization_')]
        self.assertEqual([row['kind'] for row in assay],['split','dose','dose','dose','observe'])
        self.assertEqual([row['reagent_role'] for row in assay],[None,'working.permeabilization_wash','stock.digitonin','stock.trypan_blue',None])
        for row in assay:
            binding=profile['steps'][row['id']];binding.update(enabled=True,repeat_count=1)
            binding['quantity']['value']=None if row['kind']=='observe' else 10
        self.assertFalse(self.compile(profile)['stage_readiness']['S03'])
        for branch in ('h3k4me3','igg'):
            profile['consumables'][branch]['permeabilization_vessel_id']='Test.Assay.'+branch
        self.assertTrue(self.compile(profile)['stage_readiness']['S03'])
        profile['roles']['stock.trypan_blue']['evidence_ref']=None
        self.assertFalse(self.compile(profile)['stage_readiness']['S03'])

    def test_physical_column_claim_is_permanent_without_a_fabricated_liquid_material(self):
        profile=copy.deepcopy(self.profile)
        materials=[{'id':'Test.Input','kind':'sample','vessel_id':'Test.Tube',
                    'quantity':{'value':None,'unit':'cells'},'origin_id':None}]
        names=['Test.Tube',*[f'Test.Column.{branch}' for branch in profile['consumables']]]
        vessels=[{'id':name,'location':{'kind':'rack','rack_id':'Test.Rack','place_id':'P%02d'%index}}
                 for index,name in enumerate(names)]
        for branch,binding in profile['consumables'].items():binding['column_id']='Test.Column.'+branch
        definition=sources.load({'base_profile':self.sop.base.profile,'sop_profile':self.sop.profile,'recipe_profile':profile},
            materials=materials,vessels=vessels,clock_source_kind='system_clock')
        self.assertEqual({record['material_id'] for record in definition['material_allocations']},
                         {'consumable:Test.Column.'+branch for branch in profile['consumables']})
        self.assertEqual(definition['initial_materials'],materials)
        originals=definition.pop('_initial_artifacts')
        state={'format':'solidcraftbot.material-workflow-state/3','definition':definition,'resources':[]}
        with Journal(self.sop.base.directory/'column-claims.sqlite3') as journal:
            journal.create('Test.First',state,material_allocations=definition['material_allocations'],initial_artifacts=originals)
            self.assertTrue(journal.audit_material_allocations())
            with self.assertRaises(TaskError):
                journal.create('Test.Second',state,material_allocations=definition['material_allocations'])

    def test_invalid_closed_shapes_unknown_evidence_and_numeric_values_are_rejected(self):
        for mutate in [lambda p:p.update(execution_ready=True),lambda p:p['steps'].pop('S10.column_wash'),
                       lambda p:p['roles']['stock.water'].update(mode='prepared'),
                       lambda p:p['roles']['working.antibody_buffer']['components']['stock.pic'].update(value=True),
                       lambda p:p['steps']['S05.digitonin_wash']['quantity'].update(value=float('nan')),
                       lambda p:p['roles']['working.cell_wash'].update(evidence_ref='unregistered')]:
            profile=self.confirmed();mutate(profile)
            with self.subTest(mutate=mutate),self.assertRaises(TaskError):self.compile(profile)

    def test_role_identities_cannot_alias_or_reuse_synthetic_inputs(self):
        for identity in ('Test.Recipe.stock.water','SYN.Fixture'):
            profile=self.confirmed();profile['roles']['stock.pic']['material_id']=identity
            with self.assertRaises(TaskError):self.compile(profile)

    def test_mandatory_recipe_operations_actions_and_manufacturer_original_cannot_be_removed(self):
        path=self.fixture/sources.PROTOCOL;original=path.read_bytes()
        for mutate in [lambda p:p['stage_steps']['S05'].pop(1),lambda p:p['stage_steps']['S06'][1]['actions'].remove('remove'),
                       lambda p:p['manufacturer'].update(source_sha256='a'*64),
                       lambda p:p['stage_steps']['S03'][0].update(execution_scope='reaction')]:
            protocol=json.loads(original);mutate(protocol);path.write_text(json.dumps(protocol))
            with self.assertRaises(TaskError):self.compile(self.confirmed())
            path.write_bytes(original)

    def test_sources_are_detached_preserved_and_checked_after_parsing(self):
        result=self.compile(self.confirmed())
        original=(self.fixture/sources.PROTOCOL).read_bytes()
        self.assertEqual(result['evidence_artifacts'][digest(original)],original)
        result['recipe_profile']['steps']['S04.antibody_addition']['quantity']['value']=999
        self.assertEqual(self.profile['steps']['S04.antibody_addition']['quantity']['value'],None)
        read=sources.sop._read
        def change(source,default=None):
            value=read(source,default)
            if not isinstance(source,dict) and Path(source or default).name==Path(sources.PROTOCOL).name:
                path=self.fixture/sources.PROTOCOL;path.write_bytes(path.read_bytes()+b'\n')
            return value
        with patch.object(sources.sop,'_read',side_effect=change),self.assertRaises(TaskError):self.compile(self.confirmed())

    def test_load_uses_separate_recipe_engine_and_preserves_open_inventory(self):
        materials=[{'id':'Test.Input','kind':'sample','vessel_id':'Test.Tube','quantity':{'value':None,'unit':'cells'},'origin_id':None}]
        vessels=[{'id':'Test.Tube','location':{'kind':'rack','rack_id':'Test.Rack','place_id':'P01'}}]
        result=sources.load({'base_profile':self.sop.base.profile,'sop_profile':self.sop.profile,'recipe_profile':self.profile},
            materials=materials,vessels=vessels,clock_source_kind='system_clock')
        self.assertEqual(result['profile']['type'],'cutrun_manual_recipe/1')
        self.assertEqual(result['format'],'solidcraftbot.material-workflow-definition/3')
        self.assertEqual(result['initial_materials'],materials);self.assertFalse(result['preparation_plan']['execution_ready'])
        result.pop('_initial_artifacts');json.dumps(result,allow_nan=False)


@unittest.skipUnless(jsonschema,'jsonschema is not installed in this interpreter')
class RecipeSourceSchemaTests(unittest.TestCase):
    def test_schemas_and_shipped_default_sources(self):
        for source,schema in [('model/cutrun-manual-recipe.profile.json',sources.PROFILE_SCHEMA),(sources.PROTOCOL,sources.PROTOCOL_SCHEMA)]:
            validator=jsonschema.Draft202012Validator(json.loads((ROOT/schema).read_text()));jsonschema.Draft202012Validator.check_schema(validator.schema)
            validator.validate(json.loads((ROOT/source).read_text()))

    def test_schema_rejects_claimed_success_removed_steps_and_unitless_amounts(self):
        profile=json.loads(sources.SOURCE.read_text());validator=jsonschema.Draft202012Validator(json.loads((ROOT/sources.PROFILE_SCHEMA).read_text()))
        for mutate in [lambda p:p.update(execution_ready=True),lambda p:p['steps'].pop('S10.column_load'),
                       lambda p:p['roles']['working.cell_wash']['output_quantity'].update(unit='mL')]:
            value=copy.deepcopy(profile);mutate(value);self.assertTrue(list(validator.iter_errors(value)))
