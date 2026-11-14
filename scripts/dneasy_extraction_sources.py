"""Compile one explicitly synthetic DNeasy 69504 cell-pellet workflow.

The existing extraction preparation remains unchanged and non-executable. This
adapter selects only its DNA lineage, binds individually confirmable operations
to the shared material ledger, and keeps invented fixture receipts separate
from manufacturer process parameters. No device or biochemical effect occurs.
"""
import copy
import math
from pathlib import Path

import assembly_model as assembly
import extraction_preparation as preparation
import material_ledger as ledger
import material_workflow_sources as material_sources
from extraction_qc_sources import build_tapestation_qc
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/dneasy-extraction.synthetic.json'
PROTOCOL = ROOT / 'model/dneasy-extraction.protocol.json'
SCHEMA = ROOT / 'model/dneasy-extraction.schema.json'
FORMAT = 'solidcraftbot.dneasy-extraction-synthetic/1'
ENGINE = 'dneasy_synthetic/1'
RUNTIME = tuple(dict.fromkeys((*material_sources.RUNTIME,
    'scripts/dneasy_extraction_sources.py', 'scripts/dneasy_extraction_workflow.py',
    'scripts/dneasy_extraction_demo.py', 'scripts/run_dneasy_extraction.py',
    'scripts/manual_workflow_cli.py', 'scripts/tapestation_results.py',
    'scripts/extraction_qc_sources.py', 'scripts/extraction_workflow.py',
    'scripts/extraction_demo.py', 'scripts/extraction_cli.py',
    'model/dneasy-extraction.schema.json', 'model/tapestation-gdna.schema.json')))
REAGENTS = {'PBS', 'ProteinaseK', 'AL', 'Ethanol', 'AW1', 'AW2', 'AE', 'TSBuffer', 'TSLadder'}
OUTPUT_TOKENS = {'suspension', 'pk_mix', 'rnase_mix', 'lysis_mix', 'binding_mix', 'loaded_column',
                 'bound_dna', 'bind_flowthrough', 'aw1_mix', 'aw1_bound_dna', 'aw1_flowthrough',
                 'aw2_mix', 'dry_dna', 'aw2_flowthrough', 'elution_mix', 'column_residue', 'product',
                 'ts_sample', 'ts_ladder'}


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
            'Finite positive number required for ' + label)
    return value


def quantity(value, label, *, unit=None, nullable=False):
    keys(value, 'value unit', label)
    require(value['unit'] in {'uL', 'ng', 'cells'}, 'Unsupported quantity unit at ' + label)
    if unit is not None:
        require(value['unit'] == unit, 'Wrong quantity unit at ' + label)
    if value['value'] is None:
        require(nullable, 'Known quantity required at ' + label)
    else:
        number(value['value'], label, zero=nullable)
        if value['unit'] == 'cells':
            require(value['value'] == int(value['value']), 'Integer cell count required')
    return copy.deepcopy(value)


def _reference(reference, pins, *, expected=None):
    keys(reference, 'source source_sha256', 'source reference')
    try:
        path = assembly.validate_reference(reference, root=ROOT)
        require(expected is None or path == expected.resolve(), 'Unexpected selected source')
        raw = path.read_bytes()
        value = preparation.parse_json(raw)
    except (OSError, ValueError, TypeError) as error:
        raise TaskError('Invalid DNeasy source reference') from error
    require(digest(raw) == reference['source_sha256'], 'Source changed while reading')
    pins[str(path.relative_to(ROOT))] = digest(raw)
    return value, path


def load(source=None):
    try:
        return _load(SOURCE if source is None else source)
    except TaskError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise TaskError('Invalid synthetic DNeasy composition: ' + str(error)) from error


def _load(source):
    path = None if isinstance(source, dict) else Path(source).resolve()
    require(path is None or path.is_relative_to(ROOT.resolve()), 'Repository execution profile required')
    raw = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else preparation.parse_json(raw)
    keys(profile, 'format id mode synthetic preparation protocol tapestation tapestation_protocol sample_id '
         'input_material_id input_quantity preservation_state rnase_selected settings reagent_aliquots '
         'extra_vessels fixture_output_quantities qc_policy fixture_scope', 'DNeasy fixture profile')
    require(profile['format'] == FORMAT and profile['mode'] == 'synthetic_only' and profile['synthetic'] is True,
            'Explicit synthetic DNeasy fixture required')
    text(profile['id'], 'profile identity'); text(profile['sample_id'], 'sample identity')
    text(profile['preservation_state'], 'synthetic input preservation state')
    text(profile['fixture_scope'], 'fixture assumption scope')
    require(type(profile['rnase_selected']) is bool, 'Explicit RNase branch selection required')
    pins = {}
    _, preparation_path = _reference(profile['preparation'], pins,
                                    expected=ROOT / 'model/extraction-automation.preparation.json')
    plan = preparation.compile_plan(preparation_path)
    require(plan['execution_ready'] is False and plan['sample_class'] == 'cultured_mammalian_cell_pellet',
            'Existing non-executable mammalian-cell preparation required')
    protocol, _ = _reference(profile['protocol'], pins, expected=PROTOCOL)
    keys(protocol, 'format id mode kit_id sample_class manufacturer_reference input_limit_cells '
         'branch_policy units steps limitations', 'DNeasy execution protocol')
    require(protocol['format'] == 'solidcraftbot.dneasy-extraction-protocol/1'
            and protocol['mode'] == 'synthetic_only'
            and protocol['kit_id'] == 'dneasy_blood_tissue_69504'
            and protocol['sample_class'] == plan['sample_class'], 'Selected 69504 cell protocol required')
    require(type(protocol['input_limit_cells']) is int and protocol['input_limit_cells'] == 5000000,
            'Selected cultured-cell input limit required')
    require(protocol['branch_policy'] == {'rnase': 'explicit_profile_selection_before_AL',
            'elution': 'single_elution_only', 'carryover': 'hold_and_reconcile_no_automatic_repeat'},
            'Unsupported extraction branch policy')
    instrument, _ = _reference(profile['tapestation'], pins, expected=ROOT / 'model/tapestation.shared.json')
    require(instrument['id'] == 'TS01' and instrument['handling'] == 'manual_only', 'Existing manual TS01 required')
    ts_protocol, _ = _reference(profile['tapestation_protocol'], pins,
                                expected=ROOT / 'model/tapestation-gdna.protocol.json')
    from tapestation_results import load_protocol
    verified_ts = load_protocol()
    require(ts_protocol['format'] == verified_ts['format']
            and pins['model/tapestation-gdna.protocol.json'] == verified_ts['source_sha256'],
            'Selected TapeStation gDNA protocol mismatch')
    dna = [entry for pair in plan['sample_pairs'] for analyte, entry in pair['processes'].items()
           if analyte == 'dna' and entry['lineage']['input_id'] == profile['input_material_id']]
    require(len(dna) == 1, 'Select exactly one declared DNA lineage; no RNA input is introduced')
    prepared = dna[0]; lineage = prepared['lineage']
    require(prepared['kit_id'] == protocol['kit_id'], 'Kit identity differs from existing preparation')
    amount = quantity(profile['input_quantity'], 'input quantity', unit='cells')
    require(amount['value'] <= protocol['input_limit_cells'], 'Fixture exceeds selected cell-protocol input limit')
    keys(profile['settings'], 'task_deadline_s', 'execution settings')
    deadline = number(profile['settings']['task_deadline_s'], 'task deadline')
    keys(profile['extra_vessels'], 'aw1_collection aw2_collection qc_sample qc_ladder', 'extra physical vessels')
    require(set(profile['fixture_output_quantities']) == OUTPUT_TOKENS, 'Complete explicit fixture receipts required')
    fixture = {name: quantity(value, 'fixture output ' + name, nullable=True)
               for name, value in profile['fixture_output_quantities'].items()}
    expected_reagents = REAGENTS | ({'RNaseA'} if profile['rnase_selected'] else set())
    require(isinstance(profile['reagent_aliquots'], dict)
            and set(profile['reagent_aliquots']) == expected_reagents, 'Explicit selected reagent aliquots required')
    sample_id = profile['sample_id']
    item = prepared['item_bindings']
    vessel_roles = {'input': lineage['input_vessel_id'], 'column': item['binding_column']['instance_id'],
                    'bind_collection': item['collection_vessel']['instance_id'],
                    'elution': lineage['product_vessel_id'],
                    'aw1_collection': profile['extra_vessels']['aw1_collection'],
                    'aw2_collection': profile['extra_vessels']['aw2_collection']}
    vessel_ids = [*vessel_roles.values(), profile['extra_vessels']['qc_sample'], profile['extra_vessels']['qc_ladder']]
    require(len(vessel_ids) == len(set(vessel_ids)), 'Process, collection and QC vessels must be distinct')
    materials = [{'id': lineage['input_id'], 'kind': 'sample', 'vessel_id': lineage['input_vessel_id'],
                  'quantity': amount, 'origin_id': lineage['origin_id']}]
    reagent_bindings = {}
    for role, issued in profile['reagent_aliquots'].items():
        keys(issued, 'material_id vessel_id quantity', 'issued reagent ' + role)
        text(issued['material_id'], 'issued material identity'); text(issued['vessel_id'], 'issued vessel identity')
        require(issued['vessel_id'] not in vessel_ids, 'Issued reagent aliases a process vessel')
        vessel_ids.append(issued['vessel_id'])
        materials.append({'id': issued['material_id'], 'kind': 'reagent', 'vessel_id': issued['vessel_id'],
                          'quantity': quantity(issued['quantity'], role + ' issued quantity', unit='uL'),
                          'origin_id': profile['id'] + '.SyntheticIssue'})
        reagent_bindings[role] = issued['material_id']
    require(len(vessel_ids) == len(set(vessel_ids)), 'Issued reagent vessels must be distinct')
    product_location = {'kind': 'rack', **copy.deepcopy(prepared['output_location'])}
    vessels = [{'id': identity, 'location': copy.deepcopy(product_location if identity == lineage['product_vessel_id'] else
                {'kind': 'rack', 'rack_id': profile['id'] + '.FixtureRack', 'place_id': 'P%03d' % index})}
               for index, identity in enumerate(vessel_ids, 1)]
    ledger.initial_inventory(materials, vessels)
    material_by_id = {value['id']: value for value in materials}
    previous = {'material_id': lineage['input_id'], 'unit': 'cells'}
    compiled_steps, dose_totals, seen = [], {}, set()
    output_identities = set(material_by_id) | set(vessel_ids)
    for step in protocol['steps']:
        keys(step, 'id kind phase operation when parameters required_checks inputs outputs', 'protocol step')
        require(step['id'] not in seen, 'Duplicate protocol step'); seen.add(step['id'])
        text(step['id'], 'protocol step identity'); text(step['operation'], 'semantic operation')
        require(step['kind'] in {'observation', 'effect', 'incubation'}
                and step['when'] in {'always', 'rnase_selected'}, 'Unsupported semantic step')
        require(step['phase'] in {entry['operation'] for entry in prepared['steps']}, 'Unknown E1 phase binding')
        if step['when'] == 'rnase_selected' and not profile['rnase_selected']:
            continue
        for key, value in step['parameters'].items():
            require(key in protocol['units'], 'Unknown parameter unit'); number(value, step['id'] + '.' + key)
        require(isinstance(step['required_checks'], list) and step['required_checks']
                and len(step['required_checks']) == len(set(step['required_checks'])), 'Explicit unique checks required')
        for check in step['required_checks']:
            text(check, 'required observation check')
        compiled = {key: copy.deepcopy(step[key]) for key in
                    ['id', 'kind', 'phase', 'operation', 'parameters', 'required_checks']}
        inputs, outputs, receipts = [], [], []
        for declaration in step['inputs']:
            keys(declaration, 'source quantity consume_all', 'protocol material input')
            current = declaration['source'] == 'current'
            identity = previous['material_id'] if current else reagent_bindings[declaration['source']]
            unit = previous['unit'] if current else 'uL'
            proposed = quantity(declaration['quantity'], 'planned material consumption', unit=unit, nullable=current)
            require(declaration['consume_all'] is current, 'Current intermediate is consumed completely; issued stocks partially')
            inputs.append({'material_id': identity, 'quantity': proposed, 'consume_all': current})
            if not current:
                dose_totals[identity] = dose_totals.get(identity, 0) + proposed['value']
        for declaration in step['outputs']:
            keys(declaration, 'token kind vessel_role role unit', 'protocol material output')
            token = declaration['token']
            require(token in fixture and fixture[token]['unit'] == declaration['unit'], 'Fixture receipt unit mismatch')
            identity = lineage['product_id'] if token == 'product' else sample_id + '.' + token
            require(identity not in output_identities, 'Output material identity aliases an existing process object')
            output_identities.add(identity)
            outputs.append({'material_id': identity, 'kind': declaration['kind'],
                            'vessel_id': vessel_roles[declaration['vessel_role']], 'role': declaration['role']})
            receipts.append({'material_id': identity, 'quantity': copy.deepcopy(fixture[token])})
        require((step['kind'] == 'effect') == bool(inputs and outputs), 'Effect shape differs from semantic kind')
        compiled.update(inputs=inputs, outputs=outputs, fixture_actual_outputs=receipts,
                        output_units={item['material_id']: item['quantity']['unit'] for item in receipts})
        if outputs:
            previous = {'material_id': outputs[0]['material_id'], 'unit': receipts[0]['quantity']['unit']}
        compiled_steps.append(compiled)
    require(previous['material_id'] == lineage['product_id'], 'Last extraction fraction must be the retained DNA product')
    minimum_s = sum(step['parameters'].get('duration_s', 0) for step in compiled_steps)
    require(deadline >= minimum_s, 'Task deadline cannot cover the declared serial process durations')
    qc = build_tapestation_qc(profile, instrument, ts_protocol, verified_ts, lineage,
                             reagent_bindings, material_by_id, output_identities, fixture, dose_totals)
    for identity, total in dose_totals.items():
        require(total <= material_by_id[identity]['quantity']['value'], 'Issued reagent cannot supply its declared planned doses')
    sample = {'input_material_id': lineage['input_id'], 'product_material_id': lineage['product_id'],
              'input_vessel_id': lineage['input_vessel_id'], 'column_vessel_id': vessel_roles['column'],
              'elution_vessel_id': lineage['product_vessel_id'],
              'fraction_vessels': {'bind': vessel_roles['bind_collection'], 'wash1': vessel_roles['aw1_collection'], 'wash2': vessel_roles['aw2_collection']},
              'reagent_bindings': reagent_bindings, 'qc_assay_vessel_id': profile['extra_vessels']['qc_sample']}
    declared = [{'material_id': lineage['input_id'], 'vessel_id': lineage['input_vessel_id'],
                 'role': 'dna', 'origin_id': lineage['origin_id']}]
    products = [{'material_id': lineage['product_id'], 'vessel_id': lineage['product_vessel_id'],
                 'role': 'dna', 'parent_material_id': lineage['input_id']}]
    allocations = [{'material_id': item['id'], 'vessel_id': item['vessel_id'],
                    'declaration_sha256': digest(encoded(item).encode())} for item in materials if item['kind'] == 'reagent']
    pins.update(plan['source_files_sha256'])
    if path is not None:
        pins[str(path.relative_to(ROOT))] = digest(raw)
    pins[str(SCHEMA.relative_to(ROOT))] = digest(SCHEMA.read_bytes())
    for name in RUNTIME:
        require((ROOT / name).is_file(), 'Missing DNeasy runtime source: ' + name)
        pins[name] = digest((ROOT / name).read_bytes())
    preparation.verify_source_pins(pins)
    return {'format': 'solidcraftbot.material-workflow-definition/2', 'domain': 'extraction',
            'profile': {'id': profile['id'], 'type': ENGINE, 'mode': 'synthetic_only',
                        'parameters': {'task_deadline_s': deadline}},
            'clock_mode': 'synthetic_events/1', 'preparation_plan': plan,
            'declared_inputs': declared, 'products': products, 'initial_materials': materials,
            'initial_vessels': vessels, 'material_allocations': allocations,
            'protective_stop_bindings': {},
            'execution_profile': copy.deepcopy(profile), 'runtime_source_files': list(RUNTIME),
            'execution': {'engine': ENGINE, 'kit_id': protocol['kit_id'], 'samples': {sample_id: sample},
                          'steps': compiled_steps, 'qc': qc, 'settings': copy.deepcopy(profile['settings']),
                          'rnase_selected': profile['rnase_selected'], 'limitations': copy.deepcopy(protocol['limitations'])},
            'source_files_sha256': pins,
            'effective_profile_sha256': digest(encoded({'preparation_sha256': plan['effective_preparation_sha256'],
                'profile': profile, 'protocol': protocol, 'tapestation_protocol': ts_protocol}).encode())}


compile_definition = load
