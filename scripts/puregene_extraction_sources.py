"""Compile source-bound synthetic Puregene cell extraction and fraction routing.

No physical protocol is executed. Composite tube contents remain one material
until an explicitly confirmed transfer produces separate canonical fractions.
"""
import copy
import math
from pathlib import Path

import assembly_model as assembly
import extraction_preparation as preparation
from extraction_qc_sources import build_tapestation_qc
import material_ledger as ledger
import material_workflow_sources as material_sources
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/puregene-extraction.synthetic.json'
PROTOCOL = ROOT / 'model/puregene-extraction.protocol.json'
SCHEMA = ROOT / 'model/puregene-extraction.schema.json'
FORMAT = 'solidcraftbot.puregene-extraction-synthetic/1'
ENGINE = 'puregene_synthetic/1'
RUNTIME = tuple(dict.fromkeys((*material_sources.RUNTIME,
    'scripts/puregene_extraction_sources.py', 'scripts/puregene_extraction_workflow.py',
    'scripts/puregene_extraction_demo.py', 'scripts/run_puregene_extraction.py',
    'scripts/extraction_qc_sources.py', 'scripts/extraction_workflow.py',
    'scripts/extraction_demo.py', 'scripts/extraction_cli.py',
    'scripts/manual_workflow_cli.py', 'scripts/tapestation_results.py',
    'model/puregene-extraction.schema.json', 'model/tapestation-gdna.schema.json')))
REAGENTS = {'CellLysis', 'ProteinPrecipitation', 'DNAHydration', 'Isopropanol', 'Ethanol70', 'TSBuffer', 'TSLadder'}
OUTPUT_TOKENS = {'lysate', 'rnase_lysate', 'protein_composite', 'ipa_charge', 'dna_supernatant',
                 'protein_pellet', 'dna_ipa_composite', 'dna_pellet', 'isopropanol_waste',
                 'ethanol_wash_composite', 'washed_dna_pellet', 'ethanol_waste',
                 'hydrating_dna', 'product', 'ts_sample', 'ts_ladder'}


def require(condition, message):
    if not condition:
        raise TaskError(message)


def keys(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names.split()), 'Invalid fields for ' + label)


def text(value, label):
    require(isinstance(value, str) and value.strip() and len(value) <= 160, 'Nonempty ' + label + ' required')
    return value


def number(value, label, *, zero=False):
    require(type(value) in (int, float) and math.isfinite(value) and (value >= 0 if zero else value > 0),
            'Finite positive ' + label + ' required')
    return value


def quantity(value, label, *, unit=None, nullable=False):
    keys(value, 'value unit', label)
    require(value['unit'] in {'uL', 'ng', 'cells'}, 'Unsupported quantity unit at ' + label)
    require(unit is None or value['unit'] == unit, 'Wrong quantity unit at ' + label)
    if value['value'] is None:
        require(nullable, 'Known quantity required at ' + label)
    else:
        number(value['value'], label, zero=nullable)
        if value['unit'] == 'cells':
            require(value['value'] == int(value['value']), 'Integer cell count required')
    return copy.deepcopy(value)


def reference(value, pins, expected):
    keys(value, 'source source_sha256', 'source reference')
    path = assembly.validate_reference(value, root=ROOT)
    require(path == expected.resolve(), 'Unexpected Puregene source selection')
    raw = path.read_bytes()
    require(digest(raw) == value['source_sha256'], 'Source changed while reading')
    pins[str(path.relative_to(ROOT))] = digest(raw)
    return preparation.parse_json(raw)


def load(source=None):
    try:
        return _load(SOURCE if source is None else source)
    except TaskError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise TaskError('Invalid synthetic Puregene composition: ' + str(error)) from error


def _load(source):
    path = None if isinstance(source, dict) else Path(source).resolve()
    require(path is None or path.is_relative_to(ROOT.resolve()), 'Repository execution profile required')
    raw = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else preparation.parse_json(raw)
    keys(profile, 'format id mode synthetic protocol tapestation tapestation_protocol sample_id origin_id '
         'input_material_id input_vessel_id input_quantity residual_liquid_ul preservation_state '
         'product_material_id product_vessel_id rnase_selected settings reagent_aliquots extra_vessels '
         'fixture_output_quantities qc_policy fixture_scope', 'Puregene fixture profile')
    require(profile['format'] == FORMAT and profile['mode'] == 'synthetic_only' and profile['synthetic'] is True,
            'Explicit synthetic Puregene fixture required')
    for name in ('id', 'sample_id', 'origin_id', 'input_material_id', 'input_vessel_id',
                 'product_material_id', 'product_vessel_id', 'preservation_state'):
        text(profile[name], name)
    require(isinstance(profile['fixture_scope'], str) and profile['fixture_scope'].strip()
            and len(profile['fixture_scope']) <= 2048, 'Explicit fixture assumption scope required')
    require(type(profile['rnase_selected']) is bool, 'Explicit RNase selection required')
    require(profile['residual_liquid_ul'] == 20 and type(profile['residual_liquid_ul']) in (int, float),
            'This small-scale fixture requires explicitly declared 20 uL residual liquid')
    pins = {}
    protocol = reference(profile['protocol'], pins, PROTOCOL)
    keys(protocol, 'format id mode kit_id kit sample_class manufacturer_reference input_range_cells '
         'branch_policy units steps limitations', 'Puregene protocol')
    require(protocol['format'] == 'solidcraftbot.puregene-extraction-protocol/1'
            and protocol['mode'] == 'synthetic_only' and protocol['kit_id'] == 'puregene_cell_158043'
            and protocol['sample_class'] == 'cultured_mammalian_cell_pellet', 'Selected Puregene cell protocol required')
    require(protocol['input_range_cells'] == {'minimum': 1000000, 'maximum': 2000000},
            'Small cultured-cell protocol range required')
    amount = quantity(profile['input_quantity'], 'input quantity', unit='cells')
    require(1000000 <= amount['value'] <= 2000000, 'Cell count outside the selected microcentrifuge protocol')
    require(protocol['branch_policy']['scale'] == 'microcentrifuge_1_2_million_cells_only'
            and protocol['branch_policy']['transfer'] == 'synthetic_pipetting_adaptation_of_manual_pouring',
            'Explicit small-scale transfer adaptation required')
    document = protocol['manufacturer_reference']
    require(document['revision'] == 'HB-0326-004, January 2022' and document['pages'] == '30-33'
            and document['consulted_document_sha256'] == '2fcb8a8315c675b387bfd2e83b8a6ce814eae8a162cf74d14f9dd53df7fc3d39',
            'Consulted Puregene handbook revision must remain explicit')
    instrument = reference(profile['tapestation'], pins, ROOT / 'model/tapestation.shared.json')
    require(instrument['id'] == 'TS01' and instrument['handling'] == 'manual_only', 'Existing manual TS01 required')
    ts_protocol = reference(profile['tapestation_protocol'], pins, ROOT / 'model/tapestation-gdna.protocol.json')
    from tapestation_results import load_protocol
    verified_ts = load_protocol()
    require(pins['model/tapestation-gdna.protocol.json'] == verified_ts['source_sha256'], 'TapeStation contract pin mismatch')
    keys(profile['settings'], 'task_deadline_s overnight_fixture_s', 'execution settings')
    for name, value in profile['settings'].items(): number(value, name)
    require(set(profile['fixture_output_quantities']) == OUTPUT_TOKENS, 'Explicit complete fixture output receipts required')
    fixture = {name: quantity(value, 'fixture output ' + name, nullable=True)
               for name, value in profile['fixture_output_quantities'].items()}
    require(set(profile['reagent_aliquots']) == REAGENTS | ({'RNaseA'} if profile['rnase_selected'] else set()),
            'Explicit issued aliquots for selected reagent roles required')
    keys(profile['extra_vessels'], 'precipitation transfer_tip ipa_waste ethanol_waste qc_sample qc_ladder',
         'extra physical vessels')
    roles = {'input': profile['input_vessel_id'], 'product': profile['product_vessel_id'],
             **copy.deepcopy(profile['extra_vessels'])}
    vessel_ids = list(roles.values())
    require(len(vessel_ids) == len(set(vessel_ids)), 'Process, transfer and waste vessels must be distinct')
    materials = [{'id': profile['input_material_id'], 'kind': 'sample', 'vessel_id': profile['input_vessel_id'],
                  'quantity': amount, 'origin_id': profile['origin_id']}]
    reagent_bindings = {}
    for role, issued in profile['reagent_aliquots'].items():
        keys(issued, 'material_id vessel_id quantity', 'issued reagent ' + role)
        text(issued['material_id'], 'issued material'); text(issued['vessel_id'], 'issued vessel')
        require(issued['vessel_id'] not in vessel_ids, 'Issued reagent aliases a process vessel')
        vessel_ids.append(issued['vessel_id'])
        materials.append({'id': issued['material_id'], 'kind': 'reagent', 'vessel_id': issued['vessel_id'],
                          'quantity': quantity(issued['quantity'], role + ' issued quantity', unit='uL'),
                          'origin_id': profile['id'] + '.SyntheticIssue'})
        reagent_bindings[role] = issued['material_id']
    vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': profile['id'] + '.FixtureRack',
                                          'place_id': 'P%03d' % index}}
               for index, identity in enumerate(vessel_ids, 1)]
    ledger.initial_inventory(materials, vessels)
    material_by_id = {item['id']: item for item in materials}
    output_ids = set(material_by_id) | set(vessel_ids)
    tokens = {'input': {'material_id': profile['input_material_id'], 'unit': 'cells',
                        'vessel_id': profile['input_vessel_id'], 'kind': 'sample'}}
    live = {'input'}
    current = 'input'
    compiled_steps, doses, seen = [], {}, set()
    for step in protocol['steps']:
        keys(step, 'id kind phase operation when parameters parameter_bindings required_checks inputs outputs '
             'current_after retention_after required_positive_outputs', 'protocol step')
        require(step['id'] not in seen, 'Duplicate phase identity'); seen.add(step['id'])
        text(step['id'], 'phase identity'); text(step['operation'], 'semantic operation')
        require(step['kind'] in {'observation', 'effect', 'incubation'}
                and step['when'] in {'always', 'rnase_selected'}, 'Unsupported phase kind or branch')
        if step['when'] == 'rnase_selected' and not profile['rnase_selected']: continue
        params = copy.deepcopy(step['parameters'])
        bound = step['parameter_bindings']
        require(isinstance(bound, dict) and set(bound) == {name for name, value in params.items() if value is None},
                'Only unspecified manufacturer timing may bind an explicit fixture value')
        scopes = {}
        for name, value in params.items():
            require(name in protocol['units'], 'Unknown parameter unit')
            if value is None:
                require(bound[name] == 'overnight_fixture_s' and step['id'] == 'overnight_hydration'
                        and name == 'duration_s', 'Only overnight timing is an open source parameter')
                params[name] = profile['settings'][bound[name]]
                scopes[name] = 'explicit_synthetic_fixture_not_manufacturer_defined_hours'
            number(params[name], 'phase parameter ' + name)
            if name == 'inversion_count': require(params[name] == int(params[name]), 'Integer inversion count required')
        require(isinstance(step['required_checks'], list) and step['required_checks']
                and len(set(step['required_checks'])) == len(step['required_checks']), 'Unique positive phase checks required')
        for check in step['required_checks']: text(check, 'required check')
        inputs, outputs, receipts, consumed = [], [], [], set()
        for item in step['inputs']:
            keys(item, 'source quantity consume_all', 'protocol input')
            source_name = item['source']
            token = current if source_name == 'current' else source_name[6:] if source_name.startswith('token:') else None
            if token is not None:
                require(token in live, 'Protocol input was not produced or already consumed')
                source_info = tokens[token]
                require(item['consume_all'] is True, 'Intermediate transfers require explicit complete consumption')
                proposed = quantity(item['quantity'], 'intermediate consumption', unit=source_info['unit'], nullable=True)
                identity = source_info['material_id']; consumed.add(token)
            else:
                require(source_name in reagent_bindings and item['consume_all'] is False, 'Unknown reagent or invalid stock consumption')
                identity = reagent_bindings[source_name]
                proposed = quantity(item['quantity'], 'reagent dose', unit='uL')
                doses[identity] = doses.get(identity, 0) + proposed['value']
            inputs.append({'material_id': identity, 'quantity': proposed, 'consume_all': item['consume_all']})
        require(len({item['material_id'] for item in inputs}) == len(inputs), 'Duplicate effect input')
        live -= consumed
        for item in step['outputs']:
            keys(item, 'token kind vessel_role role unit', 'protocol output')
            token = item['token']; require(token in fixture and token not in tokens, 'Unknown or reused output token')
            require(item['kind'] in {'intermediate', 'byproduct', 'product'} and item['vessel_role'] in roles,
                    'Unknown fraction kind or physical vessel')
            require(fixture[token]['unit'] == item['unit'], 'Fixture output unit differs from source fraction')
            identity = profile['product_material_id'] if token == 'product' else profile['sample_id'] + '.' + token
            require(identity not in output_ids, 'Output aliases an existing process identity'); output_ids.add(identity)
            vessel = roles[item['vessel_role']]
            require(all(tokens[other]['vessel_id'] != vessel for other in live), 'Two live fractions cannot occupy one physical vessel')
            tokens[token] = {'material_id': identity, 'unit': item['unit'], 'vessel_id': vessel, 'kind': item['kind']}
            live.add(token)
            outputs.append({'material_id': identity, 'kind': item['kind'], 'vessel_id': vessel, 'role': item['role']})
            receipts.append({'material_id': identity, 'quantity': copy.deepcopy(fixture[token])})
        require((step['kind'] == 'effect') == bool(inputs and outputs), 'Effect kind requires declared material inputs and outputs')
        if step['current_after'] is not None:
            require(step['current_after'] in live and tokens[step['current_after']]['kind'] != 'byproduct',
                    'The continuing DNA stream cannot be consumed material or waste')
            current = step['current_after']
        require(current in live, 'The DNA stream was consumed without an explicit continuing fraction')
        compiled = {name: copy.deepcopy(step[name]) for name in ['id', 'kind', 'phase', 'operation', 'required_checks']}
        compiled.update(parameters=params, inputs=inputs, outputs=outputs, fixture_actual_outputs=receipts,
                        output_units={item['material_id']: item['quantity']['unit'] for item in receipts})
        required_positive = step['required_positive_outputs']
        require(isinstance(required_positive, list) and len(set(required_positive)) == len(required_positive)
                and set(required_positive) <= {item['token'] for item in step['outputs']},
                'Positive-output requirements must name unique outputs of this effect')
        if required_positive:
            compiled['required_positive_outputs'] = [tokens[token]['material_id'] for token in required_positive]
        if scopes: compiled['parameter_scopes'] = scopes
        retention = step['retention_after']
        require(step['current_after'] is None or retention is not None
                and retention['material_token'] == current,
                'A DNA-stream transformation must refresh retention to its live resulting material')
        if retention is not None:
            keys(retention, 'material_token vessel_role pellet supernatant retained state', 'fraction retention')
            token = retention['material_token']; require(token in live, 'Retention metadata needs a live fraction')
            require(retention['vessel_role'] in roles and tokens[token]['vessel_id'] == roles[retention['vessel_role']],
                    'Retention physical vessel mismatch')
            require(retention['retained'] in {'pellet', 'supernatant', 'all'}, 'Unknown retained fraction')
            compiled['retention_after'] = {'material_id': tokens[token]['material_id'], 'vessel_id': tokens[token]['vessel_id'],
                **{name: copy.deepcopy(retention[name]) for name in ['pellet', 'supernatant', 'retained', 'state']}}
        compiled_steps.append(compiled)
    require(current == 'product' and tokens[current]['material_id'] == profile['product_material_id'],
            'The protocol must end with the retained hydrated DNA product')
    minimum_s = sum(step['parameters'].get('duration_s', 0) for step in compiled_steps)
    require(profile['settings']['task_deadline_s'] > minimum_s + ts_protocol['assay']['preparation']['buffer_equilibration_s'],
            'Task deadline cannot cover the declared extraction and QC preparation')
    lineage = {'input_id': profile['input_material_id'], 'input_vessel_id': profile['input_vessel_id'],
               'product_id': profile['product_material_id'], 'product_vessel_id': profile['product_vessel_id'],
               'origin_id': profile['origin_id']}
    qc = build_tapestation_qc(profile, instrument, ts_protocol, verified_ts, lineage,
                             reagent_bindings, material_by_id, output_ids, fixture, doses)
    for identity, total in doses.items():
        require(total <= material_by_id[identity]['quantity']['value'], 'Issued reagent cannot supply planned doses')
    sample = {'input_material_id': profile['input_material_id'], 'product_material_id': profile['product_material_id'],
              'input_vessel_id': profile['input_vessel_id'], 'product_vessel_id': profile['product_vessel_id'],
              'elution_vessel_id': profile['product_vessel_id'], 'reagent_bindings': reagent_bindings,
              'fraction_vessels': copy.deepcopy(roles), 'qc_assay_vessel_id': roles['qc_sample']}
    plan = {'format': 'solidcraftbot.puregene-preparation-plan/1', 'id': profile['id'] + '.Preparation',
            'mode': 'preparation_only', 'synthetic': True, 'execution_ready': False,
            'execution_blockers': ['local_sop_unqualified', 'providers_and_pellet_handling_unqualified',
                                   'manufacturer_overnight_hours_unspecified'],
            'lineage': [lineage], 'manufacturer_reference': copy.deepcopy(document)}
    allocations = [{'material_id': item['id'], 'vessel_id': item['vessel_id'],
                    'declaration_sha256': digest(encoded(item).encode())} for item in materials if item['kind'] == 'reagent']
    if path is not None: pins[str(path.relative_to(ROOT))] = digest(raw)
    pins[str(SCHEMA.relative_to(ROOT))] = digest(SCHEMA.read_bytes())
    for name in RUNTIME:
        require((ROOT / name).is_file(), 'Missing Puregene runtime source: ' + name)
        pins[name] = digest((ROOT / name).read_bytes())
    preparation.verify_source_pins(pins)
    return {'format': 'solidcraftbot.material-workflow-definition/2', 'domain': 'extraction',
            'profile': {'id': profile['id'], 'type': ENGINE, 'mode': 'synthetic_only',
                        'parameters': {'task_deadline_s': profile['settings']['task_deadline_s']}},
            'clock_mode': 'synthetic_events/1', 'preparation_plan': plan,
            'declared_inputs': [{'material_id': profile['input_material_id'], 'vessel_id': profile['input_vessel_id'],
                                 'role': 'dna', 'origin_id': profile['origin_id']}],
            'products': [{'material_id': profile['product_material_id'], 'vessel_id': profile['product_vessel_id'],
                          'role': 'dna', 'parent_material_id': profile['input_material_id']}],
            'initial_materials': materials, 'initial_vessels': vessels, 'material_allocations': allocations,
            'protective_stop_bindings': {}, 'execution_profile': profile, 'runtime_source_files': list(RUNTIME),
            'execution': {'engine': ENGINE, 'kit_id': protocol['kit_id'], 'samples': {profile['sample_id']: sample},
                          'steps': compiled_steps, 'qc': qc, 'rnase_selected': profile['rnase_selected'],
                          'settings': copy.deepcopy(profile['settings']), 'work_area_id': 'SYN.Puregene.WorkArea',
                          'limitations': copy.deepcopy(protocol['limitations'])},
            'source_files_sha256': pins,
            'effective_profile_sha256': digest(encoded({'profile': profile, 'protocol': protocol,
                'tapestation_protocol': ts_protocol}).encode())}


compile_definition = load
