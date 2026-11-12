"""Pinned wash and reagent contracts on the common manual SOP/material sources.

Compiler output is a read-only plan. Local recipe choices, amounts, identities,
preparations and source evidence remain explicit; no manufacturer example becomes
an observed dose or an approved local execution parameter.
"""
import copy
import math
from pathlib import Path

import cutrun_manual_sop_sources as sop
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-manual-recipe.profile.json'
PROTOCOL = 'model/cutrun-manual-recipe.protocol.json'
PROFILE_SCHEMA = 'model/cutrun-manual-recipe.profile.schema.json'
PROTOCOL_SCHEMA = 'model/cutrun-manual-recipe.protocol.schema.json'
FORMAT = 'solidcraftbot.cutrun-manual-recipe-profile/1'
ENGINE = 'cutrun_manual_recipe/1'
RUNTIME = tuple(dict.fromkeys((*sop.RUNTIME, 'scripts/cutrun_manual_recipe_sources.py',
    'scripts/cutrun_manual_recipe_workflow.py', 'scripts/cutrun_recipe_bindings.py',
    PROTOCOL, 'model/cutrun-manual-recipe.profile.json', PROFILE_SCHEMA, PROTOCOL_SCHEMA)))
KINDS = {'wash', 'dose', 'remove', 'load', 'dry', 'elute', 'activation', 'stop', 'split', 'observe'}
MANDATORY = {
    'S02': ('initial_separation', 'cell_wash', 'cell_resuspension'),
    'S03': ('bead_activation_wash', 'bead_resuspension', 'permeabilization_aliquot',
            'permeabilization_buffer', 'permeabilization_digitonin', 'permeabilization_dye',
            'permeabilization_read', 'bead_addition', 'binding_medium_removal', 'antibody_buffer_addition'),
    'S04': ('antibody_addition',),
    'S05': ('antibody_medium_removal', 'digitonin_wash', 'enzyme_addition'),
    'S06': ('enzyme_medium_removal', 'preactivation_wash'),
    'S07': ('activation',), 'S08': ('stop', 'released_fraction'),
    'S09': ('input_extraction_addition', 'clarified_fraction'),
    'S10': ('binding_buffer_addition', 'column_load', 'column_wash', 'column_dry', 'column_elution')}
ROLE_FIELDS = ('mode', 'material_id', 'vessel_id', 'lot_ref', 'preparation_ref', 'evidence_ref', 'components', 'output_quantity')
STEP_FIELDS = ('enabled', 'repeat_count', 'quantity', 'evidence_ref')


def require(condition, message):
    if not condition: raise TaskError(message)


def keys(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields), 'Invalid fields for ' + label)


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), 'Nonempty ' + label + ' required')
    return value


def optional(value, label):
    if value is not None: text(value, label)


def _repo(name):
    path = (ROOT / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(ROOT.resolve()) and path.is_file(), 'Recipe source missing: ' + name)
    return path


def _selection(source):
    if source is None: return None, None, None
    keys(source, ('base_profile', 'sop_profile', 'recipe_profile'), 'composite manual recipe source')
    return source['base_profile'], source['sop_profile'], source['recipe_profile']


def load_recipe_profile(source=None):
    """Read detached factory bindings; full validation is performed by load()."""
    unused, unused2, selected = _selection(source)
    value, unused_bytes, unused_path = sop._read(selected, ROOT / 'model/cutrun-manual-recipe.profile.json')
    keys(value, ('format', 'id', 'mode', 'synthetic', 'incoming_preparation', 'cell_wash_branch', 'permeabilization', 'roles', 'steps', 'consumables'), 'recipe profile')
    return value


def recipe_profile(source=None):
    """Factory-facing alias for the detached prospective recipe bindings."""
    return load_recipe_profile(source)


def _quantity(value, label):
    keys(value, ('value', 'unit'), label)
    require(value['unit'] == 'uL', 'Liquid recipe quantities require explicit uL')
    number = value['value']
    if number is not None:
        try: valid = type(number) in (int, float) and math.isfinite(number) and number > 0
        except OverflowError: valid = False
        require(valid, 'Finite positive ' + label + ' required')
    return number is not None


def _protocol():
    protocol, content, unused = sop._read(_repo(PROTOCOL))
    keys(protocol, ('format', 'id', 'sop', 'manufacturer', 'scope', 'reagent_roles', 'stage_steps'), 'recipe protocol')
    require(protocol['format'] == 'solidcraftbot.cutrun-manual-recipe-protocol/1', 'Unknown recipe protocol format')
    require(protocol['sop'] == {'id': 'SOP-CR-SKM29-H3K4me3', 'revision': '0.1'}, 'SOP draft 0.1 recipe binding required')
    require(protocol['scope'] == {'material_state':'fresh_unfixed','purification':'VII-A',
        'input':'VI plus locally confirmed sonication','normalization':'without_spike_in',
        'permeabilization':'Appendix A identity conflict O10 must be resolved'}, 'Recipe variant cannot silently switch')
    roles = protocol['reagent_roles'];require(isinstance(roles, dict) and roles, 'Reagent roles required')
    for identity, role in roles.items():
        text(identity, 'recipe role');keys(role, ('kind','components','source_ref','source_section','pages','manufacturer_article'), 'recipe reagent role')
        require(role['kind'] in {'stock','working'} and role['source_ref'] == 'R2', 'Explicit stock or working reagent role required')
        text(role['source_section'], 'manufacturer section')
        require(isinstance(role['components'], list) and len(role['components']) == len(set(role['components']))
                and all(item in roles and item != identity for item in role['components']), 'Known distinct recipe component roles required')
        require(bool(role['components']) == (role['kind'] == 'working'), 'Working reagents need components; stocks are leaves')
    def visit(identity, path):
        require(identity not in path, 'Cyclic recipe components')
        for child in roles[identity]['components']: visit(child, {*path, identity})
    for identity in roles:visit(identity,set())
    keys(protocol['stage_steps'], MANDATORY, 'complete selected recipe stage groups')
    for stage, suffixes in MANDATORY.items():
        steps=protocol['stage_steps'][stage]
        require(isinstance(steps,list) and [row.get('id') for row in steps] == [stage+'.'+suffix for suffix in suffixes], 'Recipe steps cannot be omitted or reordered')
        for row in steps:
            keys(row, ('id','kind','roles','reagent_role','target_role','source_section','pages','source_facts','execution_scope','actions'), 'recipe step')
            require(row['kind'] in KINDS and row['execution_scope'] in {'run','reaction'}, 'Supported semantic recipe operation required')
            require(isinstance(row['roles'],list) and row['roles'] and len(row['roles']) == len(set(row['roles']))
                    and set(row['roles']) <= {'h3k4me3','igg','input'}, 'Explicit applicable recipe branches required')
            refs=row['reagent_role'].values() if isinstance(row['reagent_role'],dict) else [row['reagent_role']]
            require(all(item is None or item in roles for item in refs), 'Unknown recipe dose role')
            require(row['target_role'] in (None,'assay.permeabilization') or row['target_role'] in roles, 'Unknown separate recipe target')
            require(isinstance(row['source_facts'],dict) and isinstance(row['actions'],list) and row['actions'], 'Explicit operations and source facts required')
            expected_actions={'wash':['add','separate','remove'] if row['id']=='S10.column_wash' else ['add','mix','separate','remove'],
                'dose':['add','mix'],'remove':['separate','remove'],'load':['load','separate','remove'],
                'dry':['dry'],'elute':['add','separate','remove'],'activation':['adopt'],'stop':['adopt'],
                'split':['split'],'observe':['observe']}[row['kind']]
            require(row['actions']==expected_actions,'Semantic recipe sub-actions cannot be omitted or reordered')
            require(row['execution_scope']==('run' if row['id'] in {'S03.bead_activation_wash','S03.bead_resuspension'} else 'reaction'),
                    'Shared reagent preparation must not repeat per reaction')
            if isinstance(row['reagent_role'],dict):require(set(row['reagent_role'])==set(row['roles']),'Dose role map must cover every applicable reaction')
            text(row['source_section'],'step source section')
            require(isinstance(row['pages'],list) and row['pages'] and all(type(page) is int and page>0 for page in row['pages']), 'Positive source page references required')
    return protocol,content


def _augment(compiled, selected):
    protocol,protocol_bytes=_protocol()
    manufacturer=compiled['manual_profile']['sources']['manufacturer']
    require(protocol['manufacturer'] == {name:manufacturer[name] for name in ('url','source_sha256','protocol_revision')}, 'Recipe manufacturer original differs from the bound SOP')
    profile,profile_bytes,path=sop._read(selected, ROOT/'model/cutrun-manual-recipe.profile.json')
    keys(profile, ('format','id','mode','synthetic','incoming_preparation','cell_wash_branch','permeabilization','roles','steps','consumables'), 'recipe profile')
    require(profile['format']==FORMAT and profile['mode']=='manual_observation' and profile['synthetic'] is False, 'Separate manual recipe profile required')
    text(profile['id'],'recipe profile identity')
    evidence_records=compiled['evidence_records']
    def evidence(ref,label):
        if ref is None:return False
        text(ref,label);require(ref in evidence_records,'Unregistered recipe evidence reference: '+ref);return True
    keys(profile['incoming_preparation'], ('mode','evidence_ref'), 'incoming preparation')
    require(profile['incoming_preparation']['mode'] in (None,'perform','external'), 'Explicit incoming preparation mode required')
    incoming_ready=evidence(profile['incoming_preparation']['evidence_ref'],'incoming preparation evidence') and profile['incoming_preparation']['mode'] is not None
    keys(profile['cell_wash_branch'], ('value','evidence_ref'), 'cell wash branch')
    require(profile['cell_wash_branch']['value'] in (None,'standard','low_cell_omit'), 'Explicit cell wash variant required')
    wash_ready=evidence(profile['cell_wash_branch']['evidence_ref'],'cell wash branch evidence') and profile['cell_wash_branch']['value'] is not None
    keys(profile['permeabilization'],('mode','evidence_ref'),'permeabilization assay choice')
    require(profile['permeabilization']['mode'] in (None,'perform','external'),'Explicit assay performance or external evidence required')
    assay_ready=evidence(profile['permeabilization']['evidence_ref'],'permeabilization evidence') and profile['permeabilization']['mode'] is not None
    roles=protocol['reagent_roles'];keys(profile['roles'],roles,'all reagent role bindings')
    material_ids=set();vessel_ids=set();role_ready={}
    for identity,binding in profile['roles'].items():
        keys(binding,ROLE_FIELDS,'recipe role '+identity)
        require(binding['mode'] in (None,'issued','prepared'),'Unknown reagent binding mode')
        require(roles[identity]['kind']!='stock' or binding['mode']!='prepared','Stock role cannot be a prepared working mixture')
        for field,seen in (('material_id',material_ids),('vessel_id',vessel_ids)):
            value=binding[field];optional(value,field)
            if value is not None:
                require(value not in seen and not value.startswith('SYN.'),'Recipe identities must be unique and not synthetic')
                seen.add(value)
        optional(binding['lot_ref'],'issued lot');optional(binding['preparation_ref'],'preparation reference')
        proof=evidence(binding['evidence_ref'],'reagent binding evidence')
        keys(binding['components'], roles[identity]['components'], 'exact working reagent components')
        components=all([_quantity(value,'planned component amount') for value in binding['components'].values()])
        output=_quantity(binding['output_quantity'],'planned working reagent output')
        ready=proof and all(binding[name] is not None for name in ('material_id','vessel_id'))
        if binding['mode']=='issued':ready=ready and binding['lot_ref'] is not None and (roles[identity]['kind']=='stock' or binding['preparation_ref'] is not None)
        elif binding['mode']=='prepared':ready=ready and binding['preparation_ref'] is not None and components and output
        else:ready=False
        role_ready[identity]=ready
    requirements=copy.deepcopy(compiled['open_requirements']);readiness=copy.deepcopy(compiled['stage_readiness'])
    def opened(identity,reason,stages):
        stages=list(dict.fromkeys(stages));requirements.append({'id':'recipe.'+identity,'reason':reason,'stage_ids':stages})
        for stage in stages:readiness[stage]=False
    if not incoming_ready:opened('incoming','Incoming preparation must be performed or externally evidenced',['S02'])
    if profile['incoming_preparation']['mode']!='external' and not wash_ready:opened('cell_wash_branch','Local standard/low-cell wash branch remains open',['S02'])
    if not assay_ready:opened('permeabilization','Permeabilization must be performed with actual reagent evidence or explicitly evidenced externally',['S03'])
    all_steps={row['id']:row for rows in protocol['stage_steps'].values() for row in rows};keys(profile['steps'],all_steps,'all recipe operation bindings')
    used={}
    for identity,binding in profile['steps'].items():
        row=all_steps[identity];stage=identity[:3];affected=[stage,*(['S06','S07'] if stage in {'S07','S08'} else [])]
        keys(binding,STEP_FIELDS,'recipe step '+identity)
        require(binding['enabled'] is None or type(binding['enabled']) is bool,'Explicit enabled/disabled recipe step required')
        count=binding['repeat_count'];require(count is None or type(count) is int and count>=0,'Integer local repeat count required')
        amount=_quantity(binding['quantity'],'planned recipe dose/batch capacity')
        if row['kind'] in {'activation','stop'} and amount:
            parameter='activation_volume_ul' if row['kind']=='activation' else 'stop_volume_ul'
            expected=compiled['manual_profile']['parameters'][parameter]['value']
            require(expected is None or binding['quantity']['value']==expected,
                    'Recipe dose differs from the bound activation/stop dose')
        proof=evidence(binding['evidence_ref'],'step decision evidence')
        ready=proof and binding['enabled'] is not None
        externally_prepared=stage=='S02' and profile['incoming_preparation']['mode']=='external'
        omit_wash=identity=='S02.cell_wash' and profile['cell_wash_branch']['value']=='low_cell_omit'
        external_beads=identity in {'S03.bead_activation_wash','S03.bead_resuspension'} and profile['roles']['working.activated_beads']['mode']=='issued'
        external_assay=identity.startswith('S03.permeabilization_') and profile['permeabilization']['mode']=='external'
        skip=externally_prepared or omit_wash or external_beads or external_assay
        if binding['enabled'] is False:require(skip,'A required recipe operation cannot be silently disabled')
        if ready and binding['enabled']:
            require(not skip,'Recipe operation contradicts the selected external/omit branch')
            if row['kind']=='load':require(count is None,'Column loading is driven by actual remaining material, not a fixed repeat count')
            else:
                if count is None:ready=False
                else:
                    require(count>0,'An enabled recipe operation needs a positive repeat count')
                    expected=row['source_facts'].get('cycles',row['source_facts'].get('standard_cycles',1))
                    require(count==expected,'Local repeat choice disagrees with the selected pinned source branch')
            if row['reagent_role'] is not None or row['kind'] in {'load','split'}:ready=ready and amount
            refs=row['reagent_role'].values() if isinstance(row['reagent_role'],dict) else [row['reagent_role']]
            for role_id in refs:
                if role_id is not None:used.setdefault(role_id,set()).update(affected)
            if row['target_role'] not in (None,'assay.permeabilization'):used.setdefault(row['target_role'],set()).update(affected)
        elif binding['enabled'] is False:
            require(count in (None,0),'A skipped recipe operation cannot claim performed repetitions')
        if not ready:opened('step.'+identity,'Local recipe operation choice, repeat count, quantity or evidence remains open',affected)
    def add_dependencies(identity,stages,path):
        require(identity not in path,'Cyclic prepared recipe roles')
        if not role_ready[identity]:opened('role.'+identity,'Reagent identity, preparation or prospective quantity remains open',stages)
        if profile['roles'][identity]['mode']=='prepared':
            for child in roles[identity]['components']:add_dependencies(child,stages,{*path,identity})
    for identity,stages in used.items():add_dependencies(identity,stages,set())
    keys(profile['consumables'],('h3k4me3','igg','input'),'physical column/collection/elution bindings')
    physical=set()
    for branch,binding in profile['consumables'].items():
        keys(binding,('column_id','collection_vessel_id','elution_vessel_id','permeabilization_vessel_id','preparation_ref','evidence_ref'),'column consumables')
        ready=evidence(binding['evidence_ref'],'column preparation evidence')
        for field in ('column_id','collection_vessel_id','elution_vessel_id'):
            value=binding[field];optional(value,field)
            if value is None:ready=False
            else:require(value not in physical,'Physical purification consumables must be distinct');physical.add(value)
        optional(binding['preparation_ref'],'column preparation reference');ready=ready and binding['preparation_ref'] is not None
        if not ready:opened('consumables.'+branch,'Column and physical receiver preparation remain unbound',['S10'])
        assay_vessel=binding['permeabilization_vessel_id'];optional(assay_vessel,'separate permeabilization vessel')
        if assay_vessel is not None:
            require(assay_vessel not in physical,'Assay and purification vessels must be distinct');physical.add(assay_vessel)
        if branch!='input' and profile['permeabilization']['mode']=='perform' and assay_vessel is None:
            opened('permeabilization_vessel.'+branch,'An in-run assay needs its identified separate physical vessel',['S03'])
    pins=copy.deepcopy(compiled['source_files_sha256']);artifacts=dict(compiled['evidence_artifacts'])
    artifacts[digest(protocol_bytes)]=protocol_bytes;artifacts[digest(profile_bytes)]=profile_bytes
    parsed={PROTOCOL:digest(protocol_bytes)}
    if path is not None and path.resolve().is_relative_to(ROOT.resolve()):parsed[str(path.resolve().relative_to(ROOT.resolve()))]=digest(profile_bytes)
    for name in RUNTIME:
        checksum=digest(_repo(name).read_bytes());require(name not in parsed or parsed[name]==checksum,'Recipe source changed after parsing: '+name)
        require(name not in pins or pins[name]==checksum,'Base source changed during recipe compilation: '+name);pins[name]=checksum
    pins.update(parsed)
    for name,value in pins.items():require(digest(_repo(name).read_bytes())==value,'Recipe source changed during compilation: '+name)
    return {**compiled,'recipe_protocol':protocol,'recipe_profile':profile,'source_files_sha256':pins,
        'runtime_source_files':list(dict.fromkeys([*compiled['runtime_source_files'],*RUNTIME])),
        'open_requirements':requirements,'stage_readiness':readiness,'preparation_complete':not requirements,
        'can_claim_reference_success':False,'evidence_artifacts':artifacts,
        'effective_profile_sha256':digest(encoded({'base':compiled['effective_profile_sha256'],'protocol':protocol,'profile':profile}).encode())}


def compile_profile(source=None,*,original_pdf=None,evidence_files=None):
    base_profile,sop_profile,recipe_profile=_selection(source)
    return _augment(sop.compile_profile({'base_profile':base_profile,'sop_profile':sop_profile},original_pdf=original_pdf,evidence_files=evidence_files),recipe_profile)


def load(source=None,*,materials,vessels,clock_source_kind,original_pdf=None,evidence_files=None,protective_stop_bindings=None):
    base_profile,sop_profile,recipe_profile=_selection(source)
    actual={item['id'] for item in materials};protective={} if protective_stop_bindings is None else protective_stop_bindings
    definition=sop.load({'base_profile':base_profile,'sop_profile':sop_profile},materials=materials,vessels=vessels,
        clock_source_kind=clock_source_kind,original_pdf=original_pdf,evidence_files=evidence_files,
        protective_stop_bindings={vessel:material for vessel,material in protective.items() if material in actual})
    artifacts=definition.pop('_initial_artifacts')
    compiled={name:copy.deepcopy(definition[name]) for name in ('manual_profile','sop_protocol','sop_profile','source_files_sha256',
        'runtime_source_files','open_requirements','stage_readiness','can_archive','can_claim_reference_success',
        'preparation_complete','original_pdf_verified','evidence_records','effective_profile_sha256')}
    compiled['evidence_artifacts']=artifacts;augmented=_augment(compiled,recipe_profile)
    for name in ('recipe_protocol','recipe_profile','source_files_sha256','runtime_source_files','open_requirements',
                 'stage_readiness','preparation_complete','effective_profile_sha256'):definition[name]=augmented[name]
    definition['profile']['type']=ENGINE;definition['profile']['id']=augmented['recipe_profile']['id']
    definition['preparation_plan']['mode']='manual_recipe_contract';definition['_initial_artifacts']=augmented['evidence_artifacts']
    from cutrun_recipe_bindings import augment_definition
    definition=augment_definition(definition,augmented['recipe_protocol'],augmented['recipe_profile'],protective)
    allocated_materials={item['material_id'] for item in definition['material_allocations']}
    allocated_vessels={item['vessel_id'] for item in definition['material_allocations']}
    initial_vessels={item['id'] for item in vessels};occupied={item['vessel_id'] for item in materials}
    for branch,binding in augmented['recipe_profile']['consumables'].items():
        assay=binding['permeabilization_vessel_id']
        if assay is not None:
            require(assay in initial_vessels and assay not in occupied,
                    'Assay receiver must be an actual identified empty physical vessel')
        column=binding['column_id']
        if column is None:continue
        identity='consumable:'+column
        require(column in initial_vessels and column not in occupied,'Column must be an actual identified empty physical vessel')
        require(column not in allocated_vessels and identity not in allocated_materials,'Column identity is already allocated')
        definition['material_allocations'].append({'material_id':identity,'vessel_id':column,
            'declaration_sha256':digest(encoded({'kind':'purification_column','role':branch,'binding':binding}).encode())})
        allocated_materials.add(identity);allocated_vessels.add(column)
    return definition
