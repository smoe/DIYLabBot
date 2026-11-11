"""Read-only preparation of separate synthetic RNA/DNA extraction aliquots.

This compiles requirements, not laboratory actions. It never constructs a
journal, reserves a resource, books material or predicts an extraction yield.
"""
import copy
import json
import math
from pathlib import Path

import assembly_model as assembly
from manual_tasks import TaskError, digest, encoded
from manual_workflow import keys, positive, text

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/extraction-automation.preparation.json'
SCHEMA = ROOT / 'model/extraction-automation.schema.json'
FORMAT = 'solidcraftbot.extraction-preparation-plan/1'
ANALYTES = ('rna', 'dna')
UNITS = {'uL', 's', 'degC', 'x_g', 'count'}
PARAMETER_CONTRACT = {'volume_ul': 'uL', 'duration_s': 's', 'temperature_deg_c': 'degC',
                      'rcf_x_g': 'x_g', 'cycles': 'count'}
FRACTIONS = {'input', 'flow_through', 'column', 'eluate', 'product'}
COMMON_ITEMS = {'input_vessel', 'binding_column', 'collection_vessel', 'elution_vessel'}
ITEM_ROLES = {'binding_column': 'binding_column', 'collection_vessel': 'collection_tube',
              'elution_vessel': 'elution_tube', 'gdna_column': 'gdna_column',
              'gdna_collection_vessel': 'gdna_collection_tube'}


def require(value, message):
    if not value:
        raise TaskError(message)


def object_keys(value, expected, label):
    keys(value, ' '.join(expected), label)


def string_list(value, label, *, nonempty=True):
    require(isinstance(value, list) and (value or not nonempty), label + ' must be a list')
    for item in value:
        text(item, label)
    require(len(value) == len(set(value)), 'Duplicate ' + label)
    return value


def parse_json(content):
    def invalid(value):
        raise TaskError('Non-finite JSON value: ' + value)
    try:
        return json.loads(content, parse_constant=invalid)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TaskError('Invalid preparation JSON: ' + str(error)) from error


def read_reference(ref, pins):
    keys(ref, 'source source_sha256', 'pinned model reference')
    try:
        path = assembly.validate_reference(ref, root=ROOT)
    except (ValueError, TypeError, OSError) as error:
        raise TaskError('Invalid pinned model reference: ' + str(error)) from error
    content = path.read_bytes()
    require(digest(content) == ref['source_sha256'], 'Source changed while reading: ' + ref['source'])
    pins[str(path.relative_to(ROOT))] = digest(content)
    return parse_json(content)


def verify_source_pins(pins):
    for name, checksum in pins.items():
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT.resolve()) and path.is_file()
                and digest(path.read_bytes()) == checksum, 'Preparation source changed: ' + name)


def validate_catalog(catalog):
    keys(catalog, 'format status references materials kits automation_reference', 'extraction catalog')
    require(catalog['format'] == 'solidcraftbot.extraction-catalog/1'
            and catalog['status'] == 'preparation_only', 'Preparation-only kit catalog required')
    refs = catalog['references']
    require(isinstance(refs, dict) and refs, 'Manufacturer references required')
    for identity, ref in refs.items():
        text(identity, 'manufacturer reference id')
        keys(ref, 'url revision accessed_on scope', 'manufacturer reference')
        for field in ('url', 'accessed_on', 'scope'):
            text(ref[field], field)
        if ref['revision'] is not None:
            text(ref['revision'], 'manufacturer document revision')
    def references(value):
        string_list(value, 'manufacturer source references')
        require(set(value) <= set(refs), 'Unknown manufacturer source reference')
    materials = catalog['materials']
    require(isinstance(materials, dict) and materials, 'Declared material roles required')
    for identity, material in materials.items():
        text(identity, 'material id')
        keys(material, 'label kind supply source_refs', 'material descriptor')
        text(material['label'], 'material label')
        require(isinstance(material['kind'], str) and material['kind'] in {'reagent', 'column', 'vessel', 'tip', 'holder'}, 'Unsupported material kind')
        require(isinstance(material['supply'], str) and material['supply'] in {'kit', 'kit_or_protocol_selected', 'additional_protocol_specific'},
                'Unsupported material supply declaration')
        references(material['source_refs'])
    require(isinstance(catalog['kits'], dict) and len(catalog['kits']) == len(ANALYTES), 'One kit per analyte required')
    analytes = set()
    for identity, kit in catalog['kits'].items():
        text(identity, 'kit id')
        keys(kit, 'manufacturer name catalog_number analyte method sample_classes source_refs roles additional_materials limitations', 'kit')
        analyte = kit['analyte']
        require(isinstance(analyte, str) and analyte in ANALYTES and analyte not in analytes, 'Exactly one kit per RNA/DNA analyte required')
        analytes.add(analyte);text(kit['manufacturer'], 'kit manufacturer')
        number = text(kit['catalog_number'], 'kit catalog number')
        require(all('0' <= char <= '9' for char in number) and kit['method'] == 'silica_spin_column', 'Digit SKU and spin-column method required')
        text(kit['name'], 'kit name')
        string_list(kit['sample_classes'], 'kit sample classes')
        references(kit['source_refs'])
        require(isinstance(kit['roles'], dict) and kit['roles'], 'Kit role bindings required')
        for role, material in kit['roles'].items():
            text(role, 'kit role')
            require(isinstance(material, str) and material in materials, 'Unknown kit role material')
        required = {'binding_column', 'collection_tube', 'elution_tube', 'wash_buffer_1', 'wash_buffer_2', 'eluent'}
        if analyte == 'rna':
            required |= {'stabilizer', 'lysis_buffer', 'gdna_column', 'gdna_collection_tube'}
        else:
            required |= {'protease', 'lysis_binding_buffer'}
        require(required <= set(kit['roles']), 'Missing mandatory kit roles')
        for role in ('binding_column', 'gdna_column'):
            if role in kit['roles']:
                require(materials[kit['roles'][role]]['kind'] == 'column', 'Column role requires a column material')
        for role in ('collection_tube', 'elution_tube', 'gdna_collection_tube'):
            if role in kit['roles']:
                require(materials[kit['roles'][role]]['kind'] == 'vessel', 'Tube role requires a vessel material')
        if analyte == 'rna':
            require(kit['roles']['gdna_column'] != kit['roles']['binding_column'], 'gDNA and RNA-binding columns differ')
        string_list(kit['additional_materials'], 'additional materials')
        require(set(kit['additional_materials']) <= set(materials), 'Unknown additional material')
        string_list(kit['limitations'], 'kit limitations')
    auto = catalog['automation_reference']
    keys(auto, 'platform status source_refs note', 'automation reference')
    text(auto['platform'], 'reference platform')
    require(auto['status'] == 'manufacturer_reference_only', 'A reference platform is not a qualified provider')
    references(auto['source_refs']);text(auto['note'], 'automation reference note')


def validate_protocol(protocol, catalog):
    keys(protocol, 'format mode operations parameter_units workflows integration_targets limitations', 'preparation protocol')
    require(protocol['format'] == 'solidcraftbot.extraction-preparation-protocol/1'
            and protocol['mode'] == 'preparation_only', 'Preparation-only protocol required')
    units = protocol['parameter_units']
    require(units == PARAMETER_CONTRACT, 'Parameter-unit contract mismatch')
    for name, unit in units.items():
        text(name, 'parameter name')
        require(isinstance(unit, str) and unit in UNITS, 'Unsupported parameter unit')
    operations = protocol['operations']
    require(isinstance(operations, dict) and operations, 'Abstract operations required')
    for identity, op in operations.items():
        text(identity, 'operation id')
        keys(op, 'capability purpose parameters retained_fraction', 'abstract operation')
        text(op['capability'], 'capability');text(op['purpose'], 'operation purpose')
        string_list(op['parameters'], 'operation parameters', nonempty=False)
        require(set(op['parameters']) <= set(units), 'Operation parameter has no declared unit')
        require(isinstance(op['retained_fraction'], str) and op['retained_fraction'] in FRACTIONS, 'Unknown retained fraction')
    require(isinstance(protocol['workflows'], dict) and set(protocol['workflows']) == set(ANALYTES),
            'Separate RNA and DNA workflows required')
    for analyte, workflow in protocol['workflows'].items():
        keys(workflow, 'kit_id steps source_refs', 'extraction workflow')
        require(isinstance(workflow['kit_id'], str) and workflow['kit_id'] in catalog['kits']
                and catalog['kits'][workflow['kit_id']]['analyte'] == analyte, 'Workflow bound to the wrong kit/analyte')
        steps = string_list(workflow['steps'], 'workflow steps')
        require(set(steps) <= set(operations), 'Undefined workflow operation')
        string_list(workflow['source_refs'], 'workflow source references')
        require(set(workflow['source_refs']) <= set(catalog['references']), 'Unknown workflow source reference')
        # Semantic dependencies, not a second executable copy of either SOP.
        dependencies = [('prepare_input', 'lyse_homogenize'), ('lyse_homogenize', 'condition_binding'),
                        ('condition_binding', 'bind_column'), ('bind_column', 'wash_column'),
                        ('wash_column', 'dry_column'), ('dry_column', 'elute'), ('elute', 'handover_qc')]
        if analyte == 'rna':
            dependencies += [('prepare_input', 'stabilize_rna'), ('stabilize_rna', 'lyse_homogenize'),
                             ('lyse_homogenize', 'remove_gdna'), ('remove_gdna', 'condition_binding')]
        else:
            dependencies += [('prepare_input', 'decide_rnase'), ('decide_rnase', 'lyse_homogenize')]
        for first, second in dependencies:
            require(first in steps and second in steps and steps.index(first) < steps.index(second),
                    'Missing or misordered mandatory phase: ' + first + ' before ' + second)
        require(steps[0] == 'prepare_input' and steps[-1] == 'handover_qc', 'Input and product handover must bound the process')
    for identity, fraction in {'remove_gdna': 'flow_through', 'bind_column': 'column',
                               'wash_column': 'column', 'dry_column': 'column', 'elute': 'eluate',
                               'handover_qc': 'product'}.items():
        require(operations[identity]['retained_fraction'] == fraction, 'Wrong retained fraction for ' + identity)
    targets = protocol['integration_targets']
    keys(targets, 'lifecycle journal ledger qc_profiles', 'future integration targets')
    for field in ('lifecycle', 'journal', 'ledger'):
        text(targets[field], field)
    string_list(targets['qc_profiles'], 'future QC profiles')
    string_list(protocol['limitations'], 'protocol limitations')


def load(source=SOURCE):
    """Return a detached source snapshot; caller dictionaries are never changed."""
    path = None if isinstance(source, dict) else Path(source)
    content = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else parse_json(content)
    keys(profile, 'format id mode catalog protocol sample_class pairing_policy synthetic sample_pairs', 'preparation profile')
    require(profile['format'] == 'solidcraftbot.extraction-preparation/1' and profile['mode'] == 'preparation_only'
            and profile['synthetic'] is True, 'Only a synthetic preparation profile is supported')
    text(profile['id'], 'preparation id')
    require(profile['sample_class'] == 'cultured_mammalian_cell_pellet'
            and profile['pairing_policy'] == 'separate_input_aliquots', 'Separate mammalian-cell aliquots required')
    pins = {}
    catalog = read_reference(profile['catalog'], pins);validate_catalog(catalog)
    protocol = read_reference(profile['protocol'], pins);validate_protocol(protocol, catalog)
    if path is not None and path.resolve().is_relative_to(ROOT.resolve()):
        pins[str(path.resolve().relative_to(ROOT.resolve()))] = digest(content)
    for name in ('scripts/extraction_preparation.py', 'scripts/prepare_extraction_automation.py',
                 'scripts/assembly_model.py', 'scripts/robot_spec.py', 'scripts/manual_workflow.py',
                 'scripts/manual_tasks.py', 'model/extraction-automation.schema.json', 'model/assembly-reference.schema.json'):
        pins[name] = digest((ROOT / name).read_bytes())
    verify_source_pins(pins)
    try:
        preparation_hash = digest(encoded(profile).encode())
    except (ValueError, TypeError) as error:
        raise TaskError('Preparation must contain finite JSON values') from error
    return {'preparation': profile, 'catalog': catalog, 'protocol': protocol,
            'source_files_sha256': pins, 'effective_preparation_sha256': preparation_hash}


def compile_plan(source=SOURCE):
    definition = load(source);profile = definition['preparation'];catalog = definition['catalog'];protocol = definition['protocol']
    pins = definition['source_files_sha256'];identities = set();locations = set();pairs = [];lineage = [];open_requirements = []
    require(isinstance(profile['sample_pairs'], list) and profile['sample_pairs'], 'At least one paired input required')
    def register(identity):
        text(identity, 'material/vessel identity')
        require(identity not in identities, 'Reused material or vessel identity: ' + identity)
        identities.add(identity)
    def missing(path, kind):
        open_requirements.append({'path': path, 'kind': kind})
    for index, pair in enumerate(profile['sample_pairs']):
        keys(pair, 'origin_id rna_input_id dna_input_id rna_product_id dna_product_id processes', 'sample pair')
        for field in ('origin_id', 'rna_input_id', 'dna_input_id', 'rna_product_id', 'dna_product_id'):
            register(pair[field])
        require(isinstance(pair['processes'], dict) and set(pair['processes']) == set(ANALYTES), 'Both separate processes required')
        processes = {}
        for analyte in ANALYTES:
            process = pair['processes'][analyte];path = 'sample_pairs[%d].processes.%s' % (index, analyte)
            keys(process, 'sop preservation_state input_amount parameter_values providers items output_location', 'process preparation')
            workflow = protocol['workflows'][analyte];kit = catalog['kits'][workflow['kit_id']]
            require(profile['sample_class'] in kit['sample_classes'], 'Selected kit does not declare this material class')
            sop = process['sop']
            if sop is None:
                missing(path + '.sop', 'selected_sop_required')
            else:
                keys(sop, 'id revision source', 'selected SOP')
                text(sop['id'], 'SOP id');text(sop['revision'], 'SOP revision')
                document = read_reference(sop['source'], pins)
                require(isinstance(document, dict) and document.get('id') == sop['id']
                        and document.get('revision') == sop['revision'], 'SOP source id/revision mismatch')
            if process['preservation_state'] is None:
                missing(path + '.preservation_state', 'preservation_state_required')
            else:
                text(process['preservation_state'], 'preservation state')
            amount = process['input_amount']
            if amount is None:
                missing(path + '.input_amount', 'input_amount_required')
            else:
                keys(amount, 'value unit', 'input amount')
                require(isinstance(amount['unit'], str) and amount['unit'] in {'mg', 'cells'}, 'Input amount must declare mg or cells')
                positive(amount['value'], 'input amount')
                if amount['unit'] == 'cells':
                    require(amount['value'] == int(amount['value']), 'Cell count must be a positive integer')
            expected_items = COMMON_ITEMS | ({'gdna_column', 'gdna_collection_vessel'} if analyte == 'rna' else set())
            object_keys(process['items'], expected_items, 'process items')
            for identity in process['items'].values():
                register(identity)
            keys(process['output_location'], 'rack_id place_id', 'output rack place')
            location = process['output_location']
            for value in location.values():text(value, 'rack/place id')
            place = (location['rack_id'], location['place_id'])
            require(place not in locations, 'Duplicate output rack instance/place pair');locations.add(place)
            values = process['parameter_values'];providers = process['providers']
            require(isinstance(values, dict) and set(values) <= set(workflow['steps']), 'Unknown parameter step')
            capabilities = {protocol['operations'][step]['capability'] for step in workflow['steps']}
            require(isinstance(providers, dict) and set(providers) <= capabilities, 'Unknown provider capability')
            for capability, provider in providers.items():text(provider, 'proposed provider id')
            for capability in sorted(capabilities - set(providers)):
                missing(path + '.providers.' + capability, 'provider_proposal_required')
            steps = []
            for step_id in workflow['steps']:
                operation = protocol['operations'][step_id];parameters = operation['parameters']
                if step_id in values and values[step_id] is not None:
                    object_keys(values[step_id], parameters, 'complete step parameter map')
                step_values = values.get(step_id) or {}
                prepared = {}
                for parameter in parameters:
                    value = step_values.get(parameter);unit = protocol['parameter_units'][parameter]
                    if value is None:
                        missing(path + '.parameter_values.' + step_id + '.' + parameter, 'parameter_required')
                    else:
                        require(type(value) in (int, float) and math.isfinite(value), 'Finite numeric parameter required')
                        if unit == 'count' or parameter == 'cycles':
                            require(value > 0 and value == int(value), 'Cycles/count must be a positive integer')
                        elif unit != 'degC':
                            positive(value, parameter)
                    prepared[parameter] = {'value': value, 'unit': unit}
                steps.append({'operation': step_id, 'capability': operation['capability'], 'purpose': operation['purpose'],
                              'retained_fraction': operation['retained_fraction'], 'parameters': prepared,
                              'provider': {'instance_id': providers.get(operation['capability']), 'status': 'proposed_unvalidated'}})
            material_requirements = [
                {'role': role, 'material_id': identity, **copy.deepcopy(catalog['materials'][identity]),
                 'status': 'declared_role_only_no_stock_booking'} for role, identity in kit['roles'].items()]
            material_requirements += [
                {'role': None, 'material_id': identity, **copy.deepcopy(catalog['materials'][identity]),
                 'status': 'additional_sop_selection_required_no_stock_booking'} for identity in kit['additional_materials']]
            item_bindings = {role: {'instance_id': identity, 'material_id': kit['roles'][ITEM_ROLES[role]] if role in ITEM_ROLES else None,
                                    'status': 'planned_unobserved'} for role, identity in process['items'].items()}
            edge = {'origin_id': pair['origin_id'], 'input_id': pair[analyte + '_input_id'],
                    'product_id': pair[analyte + '_product_id'], 'analyte': analyte,
                    'input_vessel_id': process['items']['input_vessel'], 'product_vessel_id': process['items']['elution_vessel']}
            lineage.append(edge)
            processes[analyte] = {'kit_id': workflow['kit_id'], 'kit': copy.deepcopy(kit), 'sop': copy.deepcopy(sop),
                'preservation_state': process['preservation_state'], 'input_amount': copy.deepcopy(amount),
                'lineage': copy.deepcopy(edge), 'output_location': copy.deepcopy(location), 'item_bindings': item_bindings,
                'provisional_role_bindings': {'lysate_container': {'instance_id': process['items']['input_vessel'],
                                                                 'status': 'input_vessel_reuse_requires_selected_sop_check'}},
                'material_requirements': material_requirements,
                'capability_requirements': [{'capability': capability, 'provider_instance_id': providers.get(capability),
                                             'status': 'proposed_unvalidated'} for capability in sorted(capabilities)], 'steps': steps}
        pairs.append({'origin_id': pair['origin_id'], 'processes': processes})
    verify_source_pins(pins)
    return {'format': FORMAT, 'id': profile['id'], 'mode': 'preparation_only', 'synthetic': True,
            'sample_class': profile['sample_class'], 'pairing_policy': profile['pairing_policy'],
            'planning_complete': not open_requirements, 'execution_ready': False,
            'open_requirements': open_requirements,
            'execution_blockers': ['extraction_execution_unimplemented', 'providers_and_labware_unqualified',
                                   'provisional_lysate_container_role', 'qc_integration_unimplemented'],
            'sample_pairs': pairs, 'lineage': lineage, 'manufacturer_references': copy.deepcopy(catalog['references']),
            'automation_reference': copy.deepcopy(catalog['automation_reference']),
            'integration_targets': copy.deepcopy(protocol['integration_targets']),
            'source_files_sha256': copy.deepcopy(pins), 'effective_preparation_sha256': definition['effective_preparation_sha256'],
            'effects': {'hardware_executed': False, 'network_executed': False, 'inventory_booked': False,
                        'resources_reserved': False, 'journal_written': False, 'yield_predicted': False},
            'limitations': copy.deepcopy(protocol['limitations'])}
