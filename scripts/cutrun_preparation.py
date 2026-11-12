"""Pure CUT&RUN planning: no journal, stock, reservation or device execution.

The supported case is a synthetic SK-Mel-29/H3K4me3 reference. Facts retain
their provenance; complete synthetic inputs never qualify a laboratory run.
"""
import copy
import json
import math
from pathlib import Path

import assembly_model as assembly
from manual_tasks import TaskError, digest, encoded
from manual_workflow import keys, text

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-automation.preparation.json'
SCHEMA = ROOT / 'model/cutrun-automation.schema.json'
FORMAT = 'solidcraftbot.cutrun-preparation-plan/2'
PARAMETER_UNITS = {'volume_ul': 'uL', 'duration_s': 's', 'temperature_deg_c': 'degC',
                   'rcf_x_g': 'x_g', 'cycles': 'count', 'size_min_bp': 'bp', 'size_max_bp': 'bp'}
BASES = {'owner_confirmed', 'publication_reported', 'synthetic_assumption', 'unknown'}
DEPENDENCIES = ('scripts/cutrun_preparation.py', 'scripts/prepare_cutrun_automation.py',
                'scripts/assembly_model.py', 'scripts/robot_spec.py', 'scripts/manual_tasks.py',
                'scripts/manual_workflow.py', 'model/cutrun-automation.schema.json',
                'model/assembly-reference.schema.json')
# Semantic roles of this version, not a second recipe or parameter table.
FRACTIONS = dict.fromkeys(('bind_cona', 'bind_antibody', 'bind_enzyme', 'activate_digest', 'stop_reaction'), 'beads')
FRACTIONS.update(dict.fromkeys(('release_fragments', 'isolate_product', 'prepare_cleanup',
                               'lyse_input', 'sonicate_input', 'clarify_input', 'check_input_size'), 'supernatant'))
FRACTIONS.update({'prepare_cells': 'cells', 'prepare_input': 'cells', 'bind_column': 'column',
                  'wash_column': 'column', 'dry_column': 'column', 'elute': 'eluate', 'handover_qc': 'product'})
CRITICAL_CAPABILITIES = {'activate_digest': 'reaction_activation', 'stop_reaction': 'reaction_stopping',
                         'isolate_product': 'magnetic_separation', 'sonicate_input': 'input_sonication',
                         'clarify_input': 'cooled_centrifugation', 'check_input_size': 'fragment_size_check',
                         'bind_column': 'column_centrifugation', 'dry_column': 'column_centrifugation'}
CRITICAL_CAPABILITIES.update({'prepare_cells': 'specimen_preparation', 'prepare_input': 'specimen_preparation',
    'bind_cona': 'bead_binding', 'bind_antibody': 'antibody_binding', 'bind_enzyme': 'enzyme_binding',
    'release_fragments': 'fragment_release', 'prepare_cleanup': 'cleanup_preparation',
    'wash_column': 'column_washing', 'elute': 'eluate_collection', 'handover_qc': 'product_handover',
    'lyse_input': 'input_lysis'})
REQUIRED_PARAMETERS = dict.fromkeys(('bind_cona', 'bind_antibody', 'bind_enzyme', 'activate_digest',
                                     'stop_reaction', 'prepare_cleanup', 'lyse_input'),
                                    {'volume_ul', 'duration_s', 'temperature_deg_c'})
REQUIRED_PARAMETERS.update({'prepare_cells': set(), 'prepare_input': set(), 'handover_qc': set(),
    'release_fragments': {'duration_s', 'temperature_deg_c'}, 'isolate_product': {'duration_s'},
    'bind_column': {'volume_ul', 'rcf_x_g', 'duration_s'}, 'elute': {'volume_ul', 'rcf_x_g', 'duration_s'},
    'wash_column': {'volume_ul', 'cycles', 'rcf_x_g', 'duration_s'}, 'dry_column': {'rcf_x_g', 'duration_s'},
    'sonicate_input': {'cycles', 'duration_s', 'temperature_deg_c'},
    'clarify_input': {'rcf_x_g', 'duration_s', 'temperature_deg_c'},
    'check_input_size': {'size_min_bp', 'size_max_bp'}})


def require(condition, message):
    if not condition:
        raise TaskError(message)


def strings(value, label, *, nonempty=True):
    require(isinstance(value, list) and (bool(value) or not nonempty), label + ' must be a list')
    for item in value:
        text(item, label)
    require(len(value) == len(set(value)), 'Duplicate ' + label)
    return value


def parse_json(content):
    def invalid(value):
        raise TaskError('Non-finite JSON value: ' + value)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    try:
        return json.loads(content, parse_constant=invalid, object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TaskError('Invalid CUT&RUN preparation JSON: ' + str(error)) from error


def read_reference(ref, pins):
    keys(ref, 'source source_sha256', 'pinned CUT&RUN model reference')
    try:
        path = assembly.validate_reference(ref, root=ROOT)
        content = path.read_bytes()
    except (ValueError, TypeError, OSError) as error:
        raise TaskError('Invalid pinned CUT&RUN source: ' + str(error)) from error
    checksum = digest(content)
    require(checksum == ref['source_sha256'], 'Source changed while reading: ' + ref['source'])
    pins[str(path.relative_to(ROOT))] = checksum
    return parse_json(content)


def verify_source_pins(pins):
    for name, checksum in pins.items():
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT.resolve()) and path.is_file()
                and digest(path.read_bytes()) == checksum, 'Preparation source changed: ' + name)


def contract_version(value, prefix):
    require(isinstance(value, str) and value in {prefix + '/1', prefix + '/2'},
            'Unsupported CUT&RUN contract version')
    return value.rsplit('/', 1)[1]


def load(source=SOURCE):
    """Return a detached, pinned snapshot without constructing any runtime object."""
    path = None if isinstance(source, dict) else Path(source)
    content = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else parse_json(content)
    keys(profile, 'format id mode synthetic catalog protocol context selection source_binding providers '
         'capability_bindings branches qc stop_plan', 'CUT&RUN preparation')
    version = contract_version(profile['format'], 'solidcraftbot.cutrun-preparation')
    require(profile['mode'] == 'preparation_only' and profile['synthetic'] is True,
            'Only the synthetic preparation-only CUT&RUN contract is supported')
    text(profile['id'], 'preparation id')
    pins = {}
    catalog = read_reference(profile['catalog'], pins)
    protocol = read_reference(profile['protocol'], pins)
    require(contract_version(catalog.get('format'), 'solidcraftbot.cutrun-catalog') == version
            and contract_version(protocol.get('format'), 'solidcraftbot.cutrun-preparation-protocol') == version,
            'Mixed CUT&RUN preparation/catalog/protocol versions are not supported')
    if path is not None and path.resolve().is_relative_to(ROOT.resolve()):
        pins[str(path.resolve().relative_to(ROOT.resolve()))] = digest(content)
    for name in DEPENDENCIES:
        pins[name] = digest((ROOT / name).read_bytes())
    try:
        effective = digest(encoded(profile).encode())
    except (TypeError, ValueError) as error:
        raise TaskError('Preparation must contain finite JSON values') from error
    verify_source_pins(pins)
    return {'preparation': profile, 'catalog': catalog, 'protocol': protocol,
            'source_files_sha256': pins, 'effective_preparation_sha256': effective}


class Facts:
    def __init__(self, references):
        self.references = references
        self.open_requirements = []
        self.assumptions = []

    def missing(self, path, kind='parameter_required'):
        item = {'path': path, 'kind': kind}
        if item not in self.open_requirements:
            self.open_requirements.append(item)

    def read(self, fact, unit, path, *, kind='number', planning=True, synthetic=False):
        if fact is None:
            if planning:
                self.missing(path)
            return None
        keys(fact, 'value unit basis source_refs note', 'provenance fact at ' + path)
        require(fact['unit'] == unit, 'Wrong unit at ' + path + ': expected ' + unit)
        require(isinstance(fact['basis'], str) and fact['basis'] in BASES, 'Unsupported fact basis at ' + path)
        text(fact['note'], 'fact note at ' + path)
        refs = strings(fact['source_refs'], 'fact source references', nonempty=False)
        require(set(refs) <= set(self.references), 'Unknown fact source reference at ' + path)
        value = fact['value']
        if value is None:
            require(fact['basis'] == 'unknown', 'Null must remain explicitly unknown at ' + path)
            if planning:
                self.missing(path)
            return None
        require(fact['basis'] != 'unknown', 'Unknown fact must have null value at ' + path)
        require(bool(refs), 'A known fact needs its source reference at ' + path)
        if synthetic:
            require(fact['basis'] == 'synthetic_assumption', 'Unresolved model parameter needs a synthetic assumption at ' + path)
        if kind == 'text':
            text(value, path)
        elif kind == 'bool':
            require(type(value) is bool, 'Boolean fact required at ' + path)
        else:
            require(type(value) in (int, float) and math.isfinite(value), 'Finite numeric fact required at ' + path)
            if unit != 'degC':
                require(value > 0, 'Positive numeric fact required at ' + path)
            if unit in {'count', 'cells', 'bp'}:
                require(value == int(value), 'Integer ' + unit + ' required at ' + path)
        if fact['basis'] == 'synthetic_assumption':
            self.assumptions.append({'path': path, **copy.deepcopy(fact)})
        return value


def validate_catalog(catalog):
    keys(catalog, 'format status references materials kits limitations', 'CUT&RUN catalog')
    version = contract_version(catalog['format'], 'solidcraftbot.cutrun-catalog')
    require(catalog['status'] == 'preparation_only', 'Preparation-only CUT&RUN catalog required')
    refs = catalog['references']
    require(isinstance(refs, dict) and refs, 'Source references required')
    for identity, ref in refs.items():
        text(identity, 'reference id')
        keys(ref, 'url revision accessed_on scope', 'source reference metadata')
        for field in ('accessed_on', 'scope'):
            text(ref[field], field)
        for field in ('url', 'revision'):
            if ref[field] is not None:
                text(ref[field], field)
    for field in ('materials', 'kits'):
        require(isinstance(catalog[field], dict) and catalog[field], field + ' required')
        for identity, item in catalog[field].items():
            text(identity, field + ' id')
            fields = ('label kind catalog_number source_refs' if field == 'materials'
                      else 'manufacturer name catalog_number source_refs')
            keys(item, fields, 'catalog ' + field)
            for name in (('label', 'kind') if field == 'materials' else ('manufacturer', 'name')):
                text(item[name], name)
            if item['catalog_number'] is not None:
                text(item['catalog_number'], 'catalog number')
            require(set(strings(item['source_refs'], 'catalog source references')) <= set(refs), 'Unknown catalog source')
    strings(catalog['limitations'], 'catalog limitations')
    if version == '2':
        for role in ('activation_reagent', 'stop_buffer'):
            require(role in catalog['materials'] and catalog['materials'][role]['kind'] == 'reagent'
                    and catalog['materials'][role]['catalog_number'] is None,
                    'Prepared activation/stop reagent roles require an explicit generic mixture without a stock SKU')
    else:
        require('activation_reagent' not in catalog['materials'], 'Activation reagent role requires CUT&RUN catalog version 2')


def validate_protocol(protocol, catalog):
    keys(protocol, 'format mode parameter_units operations workflows fraction_contract qc_contract '
         'required_material_roles stop_contract input_size_contract integration_targets limitations', 'CUT&RUN protocol')
    version = contract_version(protocol['format'], 'solidcraftbot.cutrun-preparation-protocol')
    require(contract_version(catalog['format'], 'solidcraftbot.cutrun-catalog') == version,
            'Mixed CUT&RUN catalog/protocol versions are not supported')
    require(protocol['mode'] == 'preparation_only', 'Preparation-only CUT&RUN protocol required')
    require(protocol['parameter_units'] == PARAMETER_UNITS, 'Parameter-unit contract mismatch')
    operations = protocol['operations']
    require(isinstance(operations, dict) and set(operations) == set(FRACTIONS), 'Missing or unsupported CUT&RUN operation')
    require(protocol['fraction_contract'] == FRACTIONS, 'Retained fraction contract mismatch')
    for identity, operation in operations.items():
        fields = 'capability purpose parameters retained_fraction required_labware'
        keys(operation, fields + (' reagent_role' if version == '2' else ''), 'operation ' + identity)
        if version == '2':
            expected_reagent = {'activate_digest': 'activation_reagent', 'stop_reaction': 'stop_buffer'}.get(identity)
            require(operation['reagent_role'] == expected_reagent, 'Wrong activation/stop reagent role for ' + identity)
        text(operation['capability'], 'capability')
        text(operation['purpose'], 'purpose')
        require(set(strings(operation['parameters'], 'operation parameters', nonempty=False)) == REQUIRED_PARAMETERS[identity],
                'Missing or unknown mandatory operation parameter for ' + identity)
        require(operation['retained_fraction'] == FRACTIONS[identity], 'Wrong retained fraction for ' + identity)
        if identity in CRITICAL_CAPABILITIES:
            require(operation['capability'] == CRITICAL_CAPABILITIES[identity], 'Wrong capability for ' + identity)
        strings(operation['required_labware'], 'required labware')
        expected_labware = ({'spin_column', 'collection_tube'} if identity in {'bind_column', 'wash_column', 'dry_column'}
                            else {'spin_column', 'collection_tube', 'tube_1_5ml'} if identity == 'elute' else {'tube_1_5ml'})
        require(set(operation['required_labware']) == expected_labware, 'Missing mandatory operation labware for ' + identity)
    keys(protocol['workflows'], 'cutrun input', 'separate workflows')
    cleanup = ['bind_column', 'wash_column', 'dry_column', 'elute', 'handover_qc']
    required = {'cutrun': ['prepare_cells', 'bind_cona', 'bind_antibody', 'bind_enzyme', 'activate_digest',
                            'stop_reaction', 'release_fragments', 'isolate_product', 'prepare_cleanup'] + cleanup,
                'input': ['prepare_input', 'lyse_input', 'sonicate_input', 'clarify_input', 'check_input_size'] + cleanup}
    for name, workflow in protocol['workflows'].items():
        keys(workflow, 'steps source_refs', 'workflow ' + name)
        steps = strings(workflow['steps'], 'workflow steps')
        require(set(steps) == set(required[name]), 'Missing mandatory phase or wrong input/CUT&RUN branch')
        for first, second in zip(required[name], required[name][1:]):
            require(steps.index(first) < steps.index(second), 'Misordered mandatory phase: ' + first + ' before ' + second)
        require(set(strings(workflow['source_refs'], 'workflow sources')) <= set(catalog['references']), 'Unknown workflow source')
    require(protocol['qc_contract'] == {'required_methods': ['fluorometry', 'qpcr'],
            'ntc_role': 'pcr_no_template_control', 'target': 'H3K4me3', 'input_required': True}, 'Wrong QC contract')
    require(protocol['stop_contract'] == {'capability': 'reaction_stopping', 'material_id': 'stop_buffer',
            'active_roles': ['reference', 'negative_control'], 'software_hold_is_chemical_stop': False}, 'Wrong stop contract')
    keys(protocol['input_size_contract'], 'cleanup_id maximum_exclusive_bp', 'column input size contract')
    require(protocol['input_size_contract']['cleanup_id'] == 'cst_14209', 'Wrong input size cleanup binding')
    expected = {'cutrun': {'con_a_beads', 'primary_antibody', 'enzyme', 'stop_buffer', 'purification_column', 'eluent',
                           'extraction_buffer', 'proteinase_k', 'rnase_a'},
                'input': {'extraction_buffer', 'proteinase_k', 'rnase_a', 'purification_column', 'eluent'}}
    if version == '2':
        expected['cutrun'].add('activation_reagent')
    keys(protocol['required_material_roles'], 'cutrun input', 'material roles')
    for workflow, roles in expected.items():
        require(set(strings(protocol['required_material_roles'][workflow], 'material roles')) == roles, 'Missing material role')
    keys(protocol['integration_targets'], 'lifecycle journal ledger', 'future integration targets')
    for value in protocol['integration_targets'].values():
        text(value, 'future integration target')
    strings(protocol['limitations'], 'protocol limitations')


def compile_plan(source=SOURCE):
    definition = load(source)
    profile, catalog, protocol = (definition[key] for key in ('preparation', 'catalog', 'protocol'))
    validate_catalog(catalog)
    validate_protocol(protocol, catalog)
    version = contract_version(profile['format'], 'solidcraftbot.cutrun-preparation')
    facts = Facts(catalog['references'])
    input_size_limit = facts.read(protocol['input_size_contract']['maximum_exclusive_bp'], 'bp',
                                 'protocol.input_size_contract.maximum_exclusive_bp', synthetic=True)
    context = profile['context']
    keys(context, 'sample_class cell_line preservation reference_target purpose', 'reference context')
    expected_context = {'sample_class': 'cultured_melanoma_cells', 'cell_line': 'SK-Mel-29',
                        'preservation': 'fresh_unfixed', 'reference_target': 'H3K4me3', 'purpose': 'in_silico_reference'}
    for field, expected in expected_context.items():
        value = facts.read(context[field], 'text', 'context.' + field, kind='text',
                           synthetic=field in {'cell_line', 'preservation'})
        require(value is None or value == expected, 'Unsupported or contradictory reference ' + field)
    selection = profile['selection']
    keys(selection, 'kit_id cleanup_id incubation normalization', 'selected variant')
    require(selection['kit_id'] == 'cst_86652' and selection['kit_id'] in catalog['kits'], 'Wrong reference kit binding')
    require(selection['cleanup_id'] == 'cst_14209' and selection['cleanup_id'] in catalog['kits'], 'Unsupported cleanup variant')
    incubation = facts.read(selection['incubation'], 'text', 'selection.incubation', kind='text', synthetic=True)
    require(incubation in {None, 'synthetic_4c'}, 'Unsupported incubation variant')
    normalization = facts.read(selection['normalization'], 'text', 'selection.normalization', kind='text', synthetic=True)
    require(normalization in {None, 'none'}, 'Unsupported normalization variant for the single-condition reference')
    binding = profile['source_binding']
    keys(binding, 'comparison_reference historical_sop_revision original_sop_sha256', 'SOP source binding')
    require(isinstance(binding['comparison_reference'], str)
            and binding['comparison_reference'] in catalog['references'], 'Unknown comparison reference')
    for name, unit in (('historical_sop_revision', 'text'), ('original_sop_sha256', 'sha256')):
        value = facts.read(binding[name], unit, 'source_binding.' + name, kind='text', planning=False)
        require(value is None, 'Historical SOP evidence is unresolved; a current comparison is not the historical SOP')

    providers = {}
    require(isinstance(profile['providers'], list), 'Provider proposals must be a list')
    capabilities = {op['capability'] for op in protocol['operations'].values()} | {'fluorometry', 'qpcr'}
    for index, provider in enumerate(profile['providers']):
        keys(provider, 'id status capabilities labware limits', 'provider proposal')
        identity = text(provider['id'], 'provider id')
        require(identity not in providers, 'Duplicate provider id')
        require(provider['status'] == 'proposed_synthetic_unqualified', 'Provider must remain a synthetic unqualified proposal')
        require(set(strings(provider['capabilities'], 'provider capabilities')) <= capabilities, 'Unknown provider capability')
        strings(provider['labware'], 'provider labware')
        require(isinstance(provider['limits'], dict) and set(provider['limits']) <= {'volume_ul', 'temperature_deg_c', 'rcf_x_g'},
                'Unknown provider limit')
        limits = {}
        for parameter, bounds in provider['limits'].items():
            keys(bounds, 'min max', 'provider bounds')
            limits[parameter] = {}
            for boundary in ('min', 'max'):
                path = f'providers[{index}].limits.{parameter}.{boundary}'
                limits[parameter][boundary] = facts.read(bounds[boundary], PARAMETER_UNITS[parameter], path, synthetic=True)
            low, high = limits[parameter]['min'], limits[parameter]['max']
            require(low is None or high is None or low <= high, 'Reversed provider bounds')
        providers[identity] = {'definition': provider, 'limits': limits}
    bindings = profile['capability_bindings']
    require(isinstance(bindings, dict) and set(bindings) <= capabilities, 'Unknown capability binding')
    for capability, identity in bindings.items():
        text(identity, 'bound provider id')
        require(identity in providers, 'Unknown bound provider')
        require(capability in providers[identity]['definition']['capabilities'], 'Provider lacks bound capability: ' + capability)

    def provider_for(capability, path, labware=(), parameters=None):
        identity = bindings.get(capability)
        if identity is None:
            facts.missing(path + '.provider', 'provider_proposal_required')
            return None
        provider = providers[identity]
        require(set(labware) <= set(provider['definition']['labware']), 'Provider lacks required labware at ' + path)
        for parameter, value in (parameters or {}).items():
            if parameter not in {'volume_ul', 'temperature_deg_c', 'rcf_x_g'}:
                continue
            bounds = provider['limits'].get(parameter)
            if bounds is None:
                facts.missing(path + '.provider.limits.' + parameter, 'provider_limit_required')
            elif value is not None and all(bound is not None for bound in bounds.values()):
                require(bounds['min'] <= value <= bounds['max'], 'Provider limit exceeded at ' + path + '.' + parameter)
        return identity

    identities, locations, branches, lineage, by_role = set(), set(), [], [], {}
    def register(value):
        text(value, 'planned identity')
        require(value not in identities, 'Reused material, vessel or branch identity: ' + value)
        identities.add(value)
    require(isinstance(profile['branches'], list), 'Branches must be a list')
    for index, branch in enumerate(profile['branches']):
        path = f'branches[{index}]'
        keys(branch, 'id role workflow input_material_id product_material_id vessels output_location '
             'input_amount material_bindings parameter_values', 'planned branch')
        role = branch['role']
        require(isinstance(role, str) and role in {'reference', 'negative_control', 'input'} and role not in by_role,
                'Missing, duplicate or unsupported control role')
        by_role[role] = branch
        workflow = 'input' if role == 'input' else 'cutrun'
        require(branch['workflow'] == workflow, 'Input and CUT&RUN control workflows cannot be interchanged')
        for name in ('id', 'input_material_id', 'product_material_id'):
            register(branch[name])
        keys(branch['vessels'], 'input reaction column collection product', 'planned process vessels')
        for identity in branch['vessels'].values():
            register(identity)
        keys(branch['output_location'], 'rack_id place_id', 'output location')
        for value in branch['output_location'].values():
            text(value, 'rack/place id')
        location = (branch['output_location']['rack_id'], branch['output_location']['place_id'])
        require(location not in locations, 'Duplicate output rack instance/place pair')
        locations.add(location)
        facts.read(branch['input_amount'], 'cells', path + '.input_amount', synthetic=True)
        materials = branch['material_bindings']
        expected_roles = protocol['required_material_roles'][workflow]
        keys(materials, ' '.join(expected_roles), 'branch material bindings')
        for name, identity in materials.items():
            expected = ('h3k4me3_antibody' if role == 'reference' else 'igg_antibody') if name == 'primary_antibody' else name
            require(isinstance(identity, str) and identity in catalog['materials'] and identity == expected,
                    'Wrong material or antibody role binding: ' + name)
            kind = ('antibody' if name == 'primary_antibody' else 'column' if name == 'purification_column'
                    else 'beads' if name == 'con_a_beads' else 'enzyme' if name == 'enzyme' else 'reagent')
            require(catalog['materials'][identity]['kind'] == kind, 'Wrong catalog material kind for ' + name)
        steps = []
        values = branch['parameter_values']
        step_ids = protocol['workflows'][workflow]['steps']
        require(isinstance(values, dict) and set(values) <= set(step_ids), 'Unknown parameter step')
        for step in step_ids:
            operation = protocol['operations'][step]
            raw = values.get(step)
            require(raw is None or isinstance(raw, dict), 'Step parameter map required')
            raw = {} if raw is None else raw
            require(set(raw) <= set(operation['parameters']), 'Unknown step parameter')
            parameters = {name: facts.read(raw.get(name), PARAMETER_UNITS[name], path + '.parameter_values.' + step + '.' + name,
                                            synthetic=True) for name in operation['parameters']}
            if step == 'bind_antibody' and incubation == 'synthetic_4c':
                require(parameters.get('temperature_deg_c') in {None, 4}, 'Incubation selection contradicts branch temperature')
            if step == 'check_input_size':
                low, high = parameters.get('size_min_bp'), parameters.get('size_max_bp')
                require(low is None or high is None or low < high, 'Input fragment size interval is reversed')
                require(input_size_limit is None or high is None or high < input_size_limit,
                        'Input fragment size is incompatible with selected column cleanup')
            provider = provider_for(operation['capability'], path + '.' + step, operation['required_labware'], parameters)
            parameter_facts = {name: copy.deepcopy(raw.get(name)) if raw.get(name) is not None else
                {'value': None, 'unit': PARAMETER_UNITS[name], 'basis': 'unknown', 'source_refs': [],
                 'note': 'No planning value supplied; no default or observation is inferred.'}
                for name in operation['parameters']}
            compiled_step = {'operation': step, 'capability': operation['capability'], 'purpose': operation['purpose'],
                          'retained_fraction': operation['retained_fraction'], 'parameters': parameter_facts,
                          'provider': {'instance_id': provider, 'status': 'proposed_synthetic_unqualified'}}
            if version == '2':
                compiled_step['reagent_role'] = operation['reagent_role']
            steps.append(compiled_step)
        edge = {key: branch[key] for key in ('id', 'input_material_id', 'product_material_id')}
        edge.update({'input_vessel_id': branch['vessels']['input'], 'product_vessel_id': branch['vessels']['product'],
                     'status': 'planned_unobserved', 'product_disposition': 'retain'})
        lineage.append(edge)
        branches.append({**copy.deepcopy(branch), 'steps': steps, 'disposition': 'retain_product',
                         'material_requirements': [{'role': name, 'material_id': identity,
                             **copy.deepcopy(catalog['materials'][identity]), 'status': 'proposed_synthetic_role_no_stock_booking'}
                             for name, identity in materials.items()]})
    require(set(by_role) == {'reference', 'negative_control', 'input'}, 'All reference, negative control and input branches are required')

    qc = profile['qc']
    keys(qc, 'methods target primer_set ntc input_branch_id negative_branch_id reference_branch_id assay '
         'biological_threshold aliquot_volumes_ul', 'product QC plan')
    require(set(strings(qc['methods'], 'QC methods')) == {'fluorometry', 'qpcr'} and qc['target'] == 'H3K4me3',
            'Wrong QC method or target for purified reference DNA')
    for field, role in (('input_branch_id', 'input'), ('negative_branch_id', 'negative_control'), ('reference_branch_id', 'reference')):
        require(qc[field] == by_role[role]['id'], 'QC control association mismatch')
    keys(qc['ntc'], 'id vessel_id role', 'PCR no-template control')
    require(qc['ntc']['role'] == 'pcr_no_template_control', 'PCR NTC is a separate control, not a CUT&RUN branch')
    register(qc['ntc']['id'])
    register(qc['ntc']['vessel_id'])
    for name in ('primer_set', 'assay'):
        facts.read(qc[name], 'text', 'qc.' + name, kind='text', synthetic=True)
    threshold = facts.read(qc['biological_threshold'], 'text', 'qc.biological_threshold', kind='text', planning=False)
    require(threshold is None, 'Biological success cannot be inferred by the synthetic preflight')
    keys(qc['aliquot_volumes_ul'], 'fluorometry qpcr', 'QC aliquot quantities')
    aliquots = {}
    for method in qc['methods']:
        volume = facts.read(qc['aliquot_volumes_ul'][method], 'uL', 'qc.aliquot_volumes_ul.' + method, synthetic=True)
        provider_for(method, 'qc.' + method, ['qubit_assay_tube' if method == 'fluorometry' else 'qpcr_tube'], {'volume_ul': volume})
        aliquots[method] = volume
    if all(value is not None for value in aliquots.values()):
        for branch in profile['branches']:
            elution = (branch['parameter_values'].get('elute') or {}).get('volume_ul')
            if elution is not None and elution['value'] is not None:
                require(sum(aliquots.values()) <= elution['value'], 'Planned QC aliquots exceed proposed elution volume')
    withdrawals = [{'branch_id': branch['id'], 'parent_material_id': branch['product_material_id'],
                    'source_vessel_id': branch['vessels']['product'], 'method': method,
                    'amount': copy.deepcopy(qc['aliquot_volumes_ul'][method]), 'status': 'planned_only_no_booking'}
                   for branch in profile['branches'] for method in qc['methods']]

    stop = profile['stop_plan']
    keys(stop, 'material_id provider_id access mixing manual_fallback software_hold_is_chemical_stop active_branch_ids '
         'dose_per_branch_ul time_budget_s service_time_per_branch_s', 'reaction stop plan')
    require(stop['material_id'] == 'stop_buffer' and stop['material_id'] in catalog['materials'], 'Missing or wrong stop material')
    active = strings(stop['active_branch_ids'], 'active branch ids')
    expected_active = {by_role[role]['id'] for role in ('reference', 'negative_control')}
    require(set(active) == expected_active, 'Stop plan must cover exactly both active CUT&RUN branches')
    for field in ('access', 'mixing', 'manual_fallback', 'software_hold_is_chemical_stop'):
        value = facts.read(stop[field], 'bool', 'stop_plan.' + field, kind='bool', synthetic=True)
        expected = field != 'software_hold_is_chemical_stop'
        require(value is None or value is expected, 'Invalid stop plan: ' + field)
    dose = facts.read(stop['dose_per_branch_ul'], 'uL', 'stop_plan.dose_per_branch_ul', synthetic=True)
    budget = facts.read(stop['time_budget_s'], 's', 'stop_plan.time_budget_s', synthetic=True)
    service = facts.read(stop['service_time_per_branch_s'], 's', 'stop_plan.service_time_per_branch_s', synthetic=True)
    provider = provider_for('reaction_stopping', 'stop_plan', ['tube_1_5ml'], {'volume_ul': dose})
    require(stop['provider_id'] == provider or provider is None, 'Stop provider differs from capability binding')
    for branch in profile['branches']:
        if branch['id'] in expected_active:
            value = branch['parameter_values'].get('stop_reaction') or {}
            step_dose = value.get('volume_ul')
            if dose is not None and step_dose is not None and step_dose['value'] is not None:
                require(dose == step_dose['value'], 'Stop plan dose contradicts branch dose')
            step_time = value.get('duration_s')
            if service is not None and step_time is not None and step_time['value'] is not None:
                require(step_time['value'] <= service, 'Stop service time cannot omit required branch stop duration')
    required_service = None if service is None else len(active) * service
    require(budget is None or required_service is None or required_service <= budget, 'Stop throughput exceeds time budget')
    verify_source_pins(definition['source_files_sha256'])
    return {'format': 'solidcraftbot.cutrun-preparation-plan/' + version,
            'id': profile['id'], 'mode': 'preparation_only', 'synthetic': True,
            'planning_complete': not facts.open_requirements, 'execution_ready': False,
            'open_requirements': facts.open_requirements, 'assumptions': facts.assumptions,
            'execution_blockers': ['cutrun_execution_unimplemented', 'material_lifecycle_execution_binding_unimplemented',
                'historical_sop_and_original_source_unbound', 'providers_and_labware_unqualified',
                'qc_integration_unimplemented', 'biological_acceptance_undefined'],
            'context': copy.deepcopy(context), 'selection': copy.deepcopy(selection), 'source_binding': copy.deepcopy(binding),
            'branches': branches, 'lineage': lineage, 'qc': {**copy.deepcopy(qc), 'planned_withdrawals': withdrawals},
            'stop_plan': {**copy.deepcopy(stop), 'required_service_s': required_service,
                'required_volume_ul': None if dose is None else len(active) * dose, 'resources_reserved': False,
                'assessment': 'synthetic_requirements_only_not_a_watchdog_or_reaction_stop'},
            'capability_requirements': [{'capability': capability, 'provider_instance_id': bindings.get(capability),
                'status': 'proposed_synthetic_unqualified'} for capability in sorted(capabilities)],
            'manufacturer_references': copy.deepcopy(catalog['references']),
            'integration_targets': copy.deepcopy(protocol['integration_targets']),
            'source_files_sha256': copy.deepcopy(definition['source_files_sha256']),
            'effective_preparation_sha256': definition['effective_preparation_sha256'],
            'effects': {'hardware_executed': False, 'network_executed': False, 'inventory_booked': False,
                'resources_reserved': False, 'journal_written': False, 'yield_predicted': False},
            'limitations': copy.deepcopy(protocol['limitations'])}
