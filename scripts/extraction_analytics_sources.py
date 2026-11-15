"""Source-bound extraction products enter shared NanoDrop/Qubit/TapeStation QC.

This compiler never imports the DNA quantification fixture's sample inventory.
It projects device operation definitions onto the extraction product instead.
"""
import copy
import re
from pathlib import Path

import assembly_model as assembly
import dna_quantification_sources
import dneasy_extraction_sources
import extraction_preparation as preparation
import material_ledger as ledger
import puregene_extraction_sources
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/extraction-analytics.dneasy.json'
PROTOCOL = ROOT / 'model/extraction-analytics.protocol.json'
SCHEMA = ROOT / 'model/extraction-analytics.schema.json'
ENGINE = 'extraction_analytics_synthetic/1'
FORMAT = 'solidcraftbot.extraction-analytics-profile/1'
FAMILIES = {'dneasy': dneasy_extraction_sources, 'puregene': puregene_extraction_sources}
RUNTIME = ('scripts/extraction_analytics_sources.py', 'scripts/extraction_analytics_workflow.py',
           'scripts/extraction_analytics_stages.py', 'scripts/extraction_analytics_demo.py',
           'scripts/run_extraction_analytics.py', 'scripts/dna_quantification_demo.py',
           'model/extraction-analytics.schema.json')


def require(value, message):
    if not value:
        raise TaskError(message)


def keys(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names.split()), 'Invalid fields for ' + label)


def text(value, label, maximum=160):
    require(isinstance(value, str) and value.strip() and len(value) <= maximum, 'Explicit ' + label + ' required')
    return value


def _reference(value, expected, pins):
    keys(value, 'source source_sha256', 'analytics source reference')
    path = assembly.validate_reference(value, root=ROOT)
    require(path == expected.resolve() and path.suffix == '.json', 'Unexpected extraction analytics source selection')
    raw = path.read_bytes()
    require(digest(raw) == value['source_sha256'], 'Analytics source changed while reading')
    pins[str(path.relative_to(ROOT))] = digest(raw)
    return path, preparation.parse_json(raw)


def load(source=None):
    try:
        return _load(SOURCE if source is None else source)
    except TaskError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise TaskError('Invalid extraction analytics composition: ' + str(error)) from error


def _load(source):
    path = None if isinstance(source, dict) else Path(source).resolve()
    require(path is None or path.is_relative_to(ROOT.resolve()), 'Repository analytics profile required')
    raw = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else preparation.parse_json(raw)
    keys(profile, 'format id mode family extraction quantification protocol issued_reagents fixture_scope', 'analytics profile')
    require(profile['format'] == FORMAT and profile['mode'] == 'synthetic_only'
            and profile['family'] in FAMILIES, 'Explicit supported synthetic extraction family required')
    text(profile['id'], 'analytics profile identity'); text(profile['fixture_scope'], 'synthetic issue scope', 2048)
    pins = {}
    _, protocol = _reference(profile['protocol'], PROTOCOL, pins)
    keys(protocol, 'format id mode sequence input_policy measurement_policy qubit_working_solution_policy '
         'identity_policy consumption_policy limitations', 'analytics protocol')
    require(protocol['format'] == 'solidcraftbot.extraction-analytics-protocol/1'
            and protocol['mode'] == 'synthetic_only'
            and protocol['sequence'] == ['extraction', 'nanodrop', 'qubit', 'tapestation'], 'Fixed extraction and QC sequence required')
    require(type(protocol['measurement_policy'].get('predilution')) is bool
            and type(protocol['measurement_policy'].get('attempts_per_device')) is int, 'Explicit boolean and integer measurement policy required')
    require(protocol['input_policy'] == 'retained_extraction_product_in_same_root'
            and protocol['identity_policy'] == 'source_sample_and_product_material_vessel_home'
            and protocol['consumption_policy'] == 'canonical_material_ledger_only'
            and protocol['qubit_working_solution_policy'] == 'explicit_preprepared_synthetic_issue_no_mixing_qualification'
            and protocol['measurement_policy'] == {'source': 'undiluted_product_only', 'attempts_per_device': 1,
                'predilution': False, 'release': 'all_devices_reviewed_and_accounted'},
            'Single undiluted measurement pair and explicit issued working solution required')
    require(isinstance(protocol['limitations'], list) and protocol['limitations'], 'Qualification limits required')
    for item in protocol['limitations']: text(item, 'qualification limit', 2048)
    family = FAMILIES[profile['family']]
    extraction_path, _ = _reference(profile['extraction'], family.SOURCE, pins)
    definition = family.load(extraction_path)
    pins.update(definition['source_files_sha256'])
    quantification_path, _ = _reference(profile['quantification'], dna_quantification_sources.SOURCE, pins)
    quantification = dna_quantification_sources.load(quantification_path)
    pins.update(quantification['source_files_sha256'])
    require(quantification['protocol']['sequence'] == ['nanodrop', 'qubit'], 'Existing paired DNA measurement sequence required')
    samples = definition['execution']['samples']
    require(len(samples) == 1 and len(definition['products']) == 1, 'One existing extraction product required')
    sample_id, sample = next(iter(samples.items()))
    product_id = sample['product_material_id']
    product_vessel = sample.get('product_vessel_id', sample.get('elution_vessel_id'))
    product = definition['products'][0]
    require(product['material_id'] == product_id and product['vessel_id'] == product_vessel,
            'Extraction product identity differs from its sample binding')
    vessels = {v['id']: v for v in definition['initial_vessels']}
    require(product_vessel in vessels and vessels[product_vessel]['location']['kind'] == 'rack',
            'Existing product vessel needs an explicit original fixture rack place')
    home = copy.deepcopy(vessels[product_vessel]['location'])
    devices = copy.deepcopy(quantification['devices'])
    require(devices['nanodrop']['profile']['instrument']['type'] == 'nanodrop_one_wifi'
            and devices['qubit']['profile']['instrument']['type'] == 'qubit_4',
            'Only the existing NanoDrop One and Qubit 4 HS definitions are selected')
    for device, compiled in devices.items():
        p = compiled['profile']
        p['id'] = profile['id'] + '.' + device
        p['rack']['id'] = home['rack_id']
        p['samples'] = [{'id': sample_id, 'vessel_id': product_vessel, 'rack_slot': 1, 'initial_volume_ul': None}]
        # These Pnnn places are explicitly declared extraction fixture locations,
        # not a geometric registration in the guided-rack CAD definition.
        compiled['places'] = [{'id': home['place_id'], 'slot': 1}]
        compiled['runtime_projection'] = {'source_profile_id': quantification['devices'][device]['profile']['id'],
            'source_material_id': product_id, 'source_vessel_id': product_vessel,
            'quantity_source': 'canonical_material_ledger_only', 'place_scope': 'existing_synthetic_extraction_fixture_not_cad_registration'}
        compiled['effective_profile_sha256'] = digest(encoded(p).encode())
    qb = devices['qubit']['profile']['parameters']
    fixture_products = [item['quantity'] for step in definition['execution']['steps']
                        for item in step.get('fixture_actual_outputs', []) if item['material_id'] == product_id]
    require(len(fixture_products) == 1, 'Exactly one existing extraction product fixture receipt required')
    product_receipt = fixture_products[0]
    ts_volume = next(item['quantity']['value'] for item in definition['execution']['qc']['sample']['effect']['inputs']
                     if item['material_id'] == product_id)
    required_product = devices['nanodrop']['profile']['parameters']['sample_volume_ul'] + qb['sample_volume_ul'] + ts_volume
    require(product_receipt['unit'] == 'uL' and product_receipt['value'] is not None
            and product_receipt['value'] >= required_product,
            'Existing synthetic product fixture cannot supply all declared QC withdrawals')
    standards = devices['qubit']['protocol']['assay']['standards']
    standard_ids = {s['id'] for s in standards}
    require(standard_ids == {'SYN.StandardLow', 'SYN.StandardHigh'} and len(standards) == 2, 'Existing two-standard Qubit recipe required')
    holders = [p for p in devices['qubit']['profile']['logical_places']
               if p['holder_id'] != devices['qubit']['profile']['instrument']['id']]
    require(len(holders) >= 3 and len({encoded(p) for p in holders}) == len(holders),
            'Three distinct non-instrument Qubit holder positions required')
    keys(profile['issued_reagents'], 'working_solution standards', 'issued Qubit reagents')
    require(isinstance(profile['issued_reagents']['standards'], dict)
            and set(profile['issued_reagents']['standards']) == standard_ids, 'Every Qubit standard needs its own issued stock')
    needed_ws = qb['assay_total_volume_ul'] - qb['sample_volume_ul'] + len(standards) * (
        qb['assay_total_volume_ul'] - qb['standard_volume_ul'])
    bindings = {'working_solution': None, 'standards': {}}
    occupied_ids = {v['id'] for v in definition['initial_vessels']} | {m['id'] for m in definition['initial_materials']} | set(samples)
    for step in definition['execution']['steps']:
        occupied_ids.update(item['material_id'] for item in step['outputs'])
    for role in ('sample', 'ladder'):
        occupied_ids.update(item['material_id'] for item in definition['execution']['qc'][role]['effect']['outputs'])
    issues = [('working_solution', profile['issued_reagents']['working_solution'], needed_ws)] + [
        (standard['id'], profile['issued_reagents']['standards'][standard['id']], qb['standard_volume_ul']) for standard in standards]
    for role, issue, required in issues:
        keys(issue, 'material_id vessel_id quantity location', 'issued Qubit stock')
        identity, vessel = text(issue['material_id'], 'issued material identity'), text(issue['vessel_id'], 'issued stock vessel')
        require(identity != vessel and identity not in occupied_ids and vessel not in occupied_ids, 'Issued Qubit stock aliases existing material or vessel')
        occupied_ids.update((identity, vessel))
        amount = ledger.quantity(issue['quantity'])
        require(amount['unit'] == 'uL' and amount['value'] is not None and amount['value'] >= required,
                'Known issued Qubit quantity must supply its complete selected recipe')
        location = ledger.location(issue['location'])
        for key, value in location.items(): text(value, 'issued stock location ' + key)
        require(location['kind'] == 'logical' and location['holder_id'] != devices['qubit']['profile']['instrument']['id'],
                'Issued stocks need declared storage positions, not the Qubit chamber')
        material = {'id': identity, 'kind': 'reagent', 'vessel_id': vessel,
                    'quantity': amount, 'origin_id': profile['id'] + '.SyntheticIssue'}
        definition['initial_materials'].append(material)
        definition['initial_vessels'].append({'id': vessel, 'location': location})
        definition['material_allocations'].append({'material_id': identity, 'vessel_id': vessel,
            'declaration_sha256': digest(encoded(material).encode())})
        if role == 'working_solution': bindings['working_solution'] = identity
        else: bindings['standards'][role] = identity
    # The old standalone stock names are declarations, not issued material.
    # Resolve them once at this adapter boundary to this Root's real stocks.
    qb_projection = devices['qubit']['runtime_projection']
    qb_projection['source_standard_stock_ids'] = {s['id']: s['stock_id'] for s in standards}
    for standard in standards:
        standard['stock_id'] = bindings['standards'][standard['id']]
    # Validate a single canonical inventory, including globally distinct places.
    ledger.initial_inventory(definition['initial_materials'], definition['initial_vessels'])
    for holder in holders[:3]:
        require({'kind': 'logical', **holder} not in [v['location'] for v in definition['initial_vessels']],
                'Selected assay holder place is already occupied by an initial process vessel')
    definition['profile'].update(id=profile['id'], type=ENGINE)
    definition['execution']['engine'] = ENGINE
    definition['execution']['analytics'] = {'profile_id': profile['id'], 'family': profile['family'],
        'sample_id': sample_id, 'product_material_id': product_id, 'product_vessel_id': product_vessel,
        'product_home': home, 'sequence': ['nanodrop', 'qubit'], 'devices': devices,
        'assays': copy.deepcopy(quantification['protocol']['assays']), 'reagent_bindings': bindings,
        'context_ids': {}, 'qubit_tubes': {}}
    definition['analytics_profile'] = copy.deepcopy(profile)
    definition['analytics_protocol'] = copy.deepcopy(protocol)
    definition['effective_profile_sha256'] = digest(encoded({'extraction': definition['effective_profile_sha256'],
        'analytics_profile': profile, 'analytics_protocol': protocol}).encode())
    if path is not None: pins[str(path.relative_to(ROOT))] = digest(raw)
    for name in RUNTIME:
        require((ROOT / name).is_file(), 'Missing extraction analytics runtime source: ' + name)
        pins[name] = digest((ROOT / name).read_bytes())
    preparation.verify_source_pins(pins)
    definition['source_files_sha256'] = pins
    definition['runtime_source_files'] = sorted(set(definition['runtime_source_files']) | set(RUNTIME)
        | {'scripts/' + name for name in dna_quantification_sources.RUNTIME})
    return definition


def bind_run(definition, run_id):
    """Pure creation-time binding of context IDs and actual empty assay tubes."""
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id), 'Explicit valid run identity required')
    result = copy.deepcopy(definition)
    require(result.get('profile', {}).get('type') == ENGINE and result.get('format') == 'solidcraftbot.material-workflow-definition/2',
            'Only the new extraction analytics definition may bind a run')
    analytics = result['execution']['analytics']
    expected = {'nanodrop': run_id + '.NanoDrop', 'qubit': run_id + '.Qubit'}
    targets = ['standard:' + s['id'] for s in analytics['devices']['qubit']['protocol']['assay']['standards']] + [
        'sample:' + analytics['sample_id']]
    expected_tubes = {target: expected['qubit'] + '.A01.P%04d.Tube' % index
                      for index, target in enumerate(targets, 1)}
    if analytics['context_ids']:
        require(analytics['context_ids'] == expected and analytics['qubit_tubes'] == expected_tubes,
                'Analytics definition is already bound to another run or assay tube mapping')
        require(all(compiled['profile']['id'] == expected[name]
                    for name, compiled in analytics['devices'].items()), 'Bound device context identity changed')
        ledger.initial_inventory(result['initial_materials'], result['initial_vessels'])
        require(set(expected_tubes.values()) <= {v['id'] for v in result['initial_vessels']},
                'Bound physical assay tubes are missing')
        return result
    require(not analytics['qubit_tubes'], 'An unbound analytics definition cannot contain assay tube mappings')
    analytics['context_ids'] = expected
    occupied = {v['id'] for v in result['initial_vessels']} | {m['id'] for m in result['initial_materials']}
    for step in result['execution']['steps']:
        occupied.update(item['material_id'] for item in step['outputs'])
    for role in ('sample', 'ladder'):
        occupied.update(item['material_id'] for item in result['execution']['qc'][role]['effect']['outputs'])
    qb = analytics['devices']['qubit']
    holders = [p for p in qb['profile']['logical_places'] if p['holder_id'] != qb['profile']['instrument']['id']]
    for index, target in enumerate(targets, 1):
        tube = expected['qubit'] + '.A01.P%04d.Tube' % index
        require(tube not in occupied and tube + '.Assay' not in occupied, 'Run-scoped assay identity aliases existing material or vessel')
        occupied.update((tube, tube + '.Assay'))
        result['initial_vessels'].append({'id': tube, 'location': {'kind': 'logical', **holders[index - 1]}})
        analytics['qubit_tubes'][target] = tube
    for device in ('nanodrop', 'qubit'):
        compiled = analytics['devices'][device]
        compiled['profile']['id'] = expected[device]
        compiled['effective_profile_sha256'] = digest(encoded(compiled['profile']).encode())
    ledger.initial_inventory(result['initial_materials'], result['initial_vessels'])
    result['effective_profile_sha256'] = digest(encoded({'source_effective_profile_sha256': result['effective_profile_sha256'],
        'run_id': run_id, 'context_ids': expected, 'qubit_tubes': analytics['qubit_tubes']}).encode())
    return result
