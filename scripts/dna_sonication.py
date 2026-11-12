"""Effect-free input-sonication composition over the existing CUT&RUN plan.

No device, journal or material root is constructed. Known settings in this
version are synthetic planning assumptions, never laboratory observations.
"""
import copy
import math
from pathlib import Path
import re

import cutrun_preparation as preparation
from manual_tasks import TaskError, digest, encoded
from manual_workflow import keys, text

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/dna-sonication.profile.json'
SCHEMA = 'model/dna-sonication.schema.json'
# Implemented field semantics, not defaults or a second experimental recipe.
PARAMETERS = {'cycles': ('count', 'integer'), 'pulse_on_s': ('s', 'number'),
    'between_pulses_s': ('s', 'number'), 'amplitude_percent': ('percent', 'number'),
    'device_instance_id': ('text', 'identifier'), 'firmware_revision': ('text', 'text'),
    'vessel_article': ('text', 'text'), 'nominal_vessel_volume_ml': ('mL', 'number'),
    'fill_volume_ul': ('uL', 'number'), 'closed_vessel_fit_evidence_ref': ('text', 'identifier'),
    'cooling_method': ('text', 'text'), 'amplitude_evidence_ref': ('text', 'identifier'),
    'temperature_reference_vessel_id': ('text', 'identifier'),
    'temperature_mapping_evidence_ref': ('text', 'identifier'), 'temperature_limit_deg_c': ('degC', 'number'),
    'empirical_protocol_evidence_ref': ('text', 'identifier'), 'input_size_evidence_ref': ('text', 'identifier')}
DEPENDENCIES = ('scripts/dna_sonication.py', 'scripts/prepare_dna_sonication.py', SCHEMA)


def require(condition, message):
    if not condition:
        raise TaskError(message)


def identifier(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]*', value),
            'Explicit identifier required: ' + label)
    return value


def _parameter(fact, spec, name, references, open_requirements, assumptions):
    keys(fact, 'value unit basis source_refs note', 'parameter ' + name)
    require(fact['unit'] == spec['unit'], 'Wrong parameter unit: ' + name)
    text(fact['note'], 'parameter provenance note')
    refs = preparation.strings(fact['source_refs'], 'parameter references', nonempty=False)
    require(set(refs) <= set(references), 'Unknown parameter reference: ' + name)
    value = fact['value']
    if value is None:
        require(fact['basis'] == 'unknown' and not refs, 'Null must remain explicitly unknown: ' + name)
        open_requirements.append({'path': 'parameters.' + name, 'kind': 'local_binding_required'})
        return None
    require(fact['basis'] == 'synthetic_assumption' and refs,
            'Only explicit synthetic planning assumptions are supported: ' + name)
    kind = spec['kind']
    if kind in {'text', 'identifier'}:
        text(value, name)
        if kind == 'identifier':
            identifier(value, name)
    else:
        require(type(value) in (int, float) and math.isfinite(value), 'Finite numeric parameter required: ' + name)
        if kind == 'integer':
            require(value == int(value), 'Integer parameter required: ' + name)
        require(spec['minimum'] is None or value >= spec['minimum'], 'Parameter below minimum: ' + name)
        require(spec['maximum'] is None or value <= spec['maximum'], 'Parameter above maximum: ' + name)
        if name in {'pulse_on_s', 'nominal_vessel_volume_ml', 'fill_volume_ul'}:
            require(value > 0, 'Positive parameter required: ' + name)
    assumptions.append({'path': 'parameters.' + name, **copy.deepcopy(fact)})
    return value


def _reference(reference, pins):
    # Reuse the existing safe path resolver and byte-pin verification.
    return preparation.read_reference(reference, pins)


def _protocol(data):
    keys(data, 'format id mode references binding device_candidate parameter_contract pulse_timing fragment_size limitations',
         'sonication protocol')
    require(data['format'] == 'solidcraftbot.dna-sonication-protocol/1'
            and data['mode'] == 'preparation_only', 'Unsupported sonication protocol')
    identifier(data['id'], 'protocol')
    require(data['binding'] == {'workflow': 'input', 'operation': 'sonicate_input',
        'size_check_operation': 'check_input_size', 'manual_stage': 'S09', 'manual_decision': 'O04'},
        'Sonication is restricted to the separate CUT&RUN input')
    require(data['pulse_timing'] == {'pause_policy': 'between_pulses_only',
        'duration_basis': 'logical_plan_seconds', 'device_duty_cycle_mapping': 'unbound'},
        'Unsupported pulse timing semantics')
    references = data['references']
    require(isinstance(references, dict) and references, 'Sonication source references required')
    for name, reference in references.items():
        identifier(name, 'source reference')
        keys(reference, 'url accessed_on scope', 'manufacturer reference')
        require(isinstance(reference['url'], str) and reference['url'].startswith('https://'),
                'HTTPS reference required')
        text(reference['accessed_on'], 'reference access date')
        text(reference['scope'], 'reference scope')
    candidate = data['device_candidate']
    keys(candidate, 'id manufacturer processor accessory selected hardware_available coupling manufacturer_claims',
         'device candidate')
    identifier(candidate['id'], 'candidate')
    require(candidate['selected'] is False and candidate['hardware_available'] is False
            and candidate['coupling'] == 'indirect_closed_vessel', 'Unqualified closed-vessel candidate required')
    for field in ('manufacturer', 'processor', 'accessory'):
        text(candidate[field], field)
    claims = candidate['manufacturer_claims']
    units = {'nominal_power': 'W', 'frequency': 'Hz', 'maximum_vials': 'count', 'nominal_vessel_volumes': 'mL'}
    keys(claims, ' '.join(units), 'manufacturer claims')
    for name, claim in claims.items():
        keys(claim, 'value unit basis source_ref', name)
        require(claim['unit'] == units[name] and claim['basis'] == 'manufacturer_reported'
                and claim['source_ref'] in references, 'Invalid manufacturer claim: ' + name)
        values = claim['value'] if name == 'nominal_vessel_volumes' else [claim['value']]
        require(isinstance(values, list) and values, 'Manufacturer claim values required')
        for value in values:
            require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                    'Positive finite manufacturer claim required')
        if name == 'maximum_vials':
            require(type(claim['value']) is int, 'Integer vial capacity required')
    specs = data['parameter_contract']
    require(isinstance(specs, dict) and set(specs) == set(PARAMETERS), 'Complete sonication parameter contract required')
    for name, spec in specs.items():
        keys(spec, 'unit kind minimum maximum', 'parameter contract ' + name)
        require((spec['unit'], spec['kind']) == PARAMETERS[name], 'Unsupported parameter semantics: ' + name)
        for bound in ('minimum', 'maximum'):
            value = spec[bound]
            require(value is None or type(value) in (int, float) and math.isfinite(value), 'Finite bound required')
        require(spec['minimum'] is None or spec['maximum'] is None or spec['minimum'] <= spec['maximum'],
                'Reversed parameter bounds')
        if name in {'cycles', 'pulse_on_s', 'between_pulses_s', 'amplitude_percent',
                    'nominal_vessel_volume_ml', 'fill_volume_ul'}:
            require(spec['minimum'] is not None and spec['minimum'] >= (1 if name == 'cycles' else 0),
                    'Unsupported lower parameter bound: ' + name)
        if name == 'amplitude_percent':
            require(spec['maximum'] is not None and spec['maximum'] <= 100, 'Percent cannot exceed 100')
    fragment = data['fragment_size']
    keys(fragment, 'comparison_target column_limit concentration_devices_are_size_evidence', 'size requirements')
    target = fragment['comparison_target']
    keys(target, 'minimum maximum unit basis source_ref', 'comparison size target')
    require(target['unit'] == 'bp' and target['basis'] == 'manufacturer_comparison'
            and target['source_ref'] in references, 'Comparison size provenance required')
    require(type(target['minimum']) is int and type(target['maximum']) is int
            and 0 < target['minimum'] < target['maximum'], 'Ordered comparison size target required')
    require(fragment['column_limit'] == 'derive_from_pinned_cutrun_protocol'
            and fragment['concentration_devices_are_size_evidence'] is False,
            'Size evidence must remain separate from concentration')
    preparation.strings(data['limitations'], 'sonication limitations')


def compile_plan(source=SOURCE):
    """Describe one existing input branch; a complete plan still executes nothing."""
    path = None if isinstance(source, dict) else Path(source)
    content = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else preparation.parse_json(content)
    keys(profile, 'format id mode synthetic protocol preparation parameters', 'sonication profile')
    require(profile['format'] == 'solidcraftbot.dna-sonication-profile/1'
            and profile['mode'] == 'preparation_only' and profile['synthetic'] is True,
            'Only an explicitly synthetic sonication planning profile is supported')
    identifier(profile['id'], 'profile')
    pins = {}
    protocol = _reference(profile['protocol'], pins)
    _protocol(protocol)
    original = _reference(profile['preparation'], pins)
    cutrun = preparation.compile_plan(original)
    pins.update(cutrun['source_files_sha256'])
    cutrun_protocol = _reference(original['protocol'], pins)
    if path is not None and path.resolve().is_relative_to(ROOT.resolve()):
        pins[str(path.resolve().relative_to(ROOT.resolve()))] = digest(content)
    for name in DEPENDENCIES:
        pins[name] = digest((ROOT / name).read_bytes())
    # No source keys or inherited synthetic recipe values are used as local settings.
    open_requirements, assumptions = [], []
    specs = protocol['parameter_contract']
    require(isinstance(profile['parameters'], dict) and set(profile['parameters']) == set(specs),
            'Exactly the declared sonication parameters are required')
    values = {}
    for name, spec in specs.items():
        values[name] = _parameter(profile['parameters'][name], spec, name, protocol['references'],
                                  open_requirements, assumptions)
    nominal, fill = values['nominal_vessel_volume_ml'], values['fill_volume_ul']
    claims = protocol['device_candidate']['manufacturer_claims']
    require(nominal is None or nominal in claims['nominal_vessel_volumes']['value'],
            'Vessel nominal volume is outside the candidate documentation')
    require(nominal is None or fill is None or fill <= nominal * 1000,
            'Fill exceeds nominal vessel volume; fit still needs independent evidence')
    branches = [branch for branch in cutrun['branches'] if branch['workflow'] == 'input']
    require(len(branches) == 1, 'Exactly one independently identified input branch required')
    branch = branches[0]
    required_labware = cutrun_protocol['operations']['sonicate_input']['required_labware']
    require(required_labware == ['tube_1_5ml'], 'Unsupported input sonication vessel-class contract')
    # Interpret the existing semantic labware class; do not change its vessel
    # identity or silently substitute another advertised VialTweeter tube size.
    require(nominal is None or nominal == 1.5, 'Nominal volume contradicts the pinned tube_1_5ml input class')
    for other in cutrun['branches']:
        for field in ('id', 'input_material_id', 'product_material_id'):
            identifier(other[field], field)
        for identity in other['vessels'].values():
            identifier(identity, 'CUT&RUN vessel')
        names = [step['operation'] for step in other['steps']]
        require(('sonicate_input' in names) == (other['workflow'] == 'input'), 'Never sonicate an enriched CUT&RUN branch')
    steps = [step['operation'] for step in branch['steps']]
    require('check_input_size' in steps and steps.index('sonicate_input') < steps.index('check_input_size'),
            'Input size evidence must follow its sonication proposal')
    limit = cutrun_protocol['input_size_contract']['maximum_exclusive_bp']
    target = protocol['fragment_size']['comparison_target']
    require(limit['value'] is None or target['maximum'] < limit['value'], 'Comparison target contradicts column model')
    cycles, on, pause = (values[name] for name in ('cycles', 'pulse_on_s', 'between_pulses_s'))
    total_on = None if cycles is None or on is None else cycles * on
    total_pause = None if cycles is None or pause is None else (cycles - 1) * pause
    elapsed = None if total_on is None or total_pause is None else total_on + total_pause
    for value in (total_on, total_pause, elapsed):
        require(value is None or math.isfinite(value), 'Derived pulse duration is not finite')
    open_requirements.extend({'path': 'cutrun.' + item['path'], 'kind': item['kind']}
                             for item in cutrun['open_requirements'])
    preparation.verify_source_pins(pins)
    return {'format': 'solidcraftbot.dna-sonication-plan/1', 'id': profile['id'],
        'mode': 'preparation_only', 'synthetic': True, 'planning_complete': not open_requirements,
        'execution_ready': False, 'local_qualification': False,
        'open_requirements': open_requirements, 'assumptions': assumptions,
        'source_files_sha256': pins, 'effective_profile_sha256': digest(encoded(profile).encode()),
        'binding': {**copy.deepcopy(protocol['binding']), 'cutrun_preparation_id': cutrun['id'],
            'branch_id': branch['id'], 'origin_material_id': branch['input_material_id'],
            'origin_vessel_id': branch['vessels']['input'], 'planned_process_vessel_id': branch['vessels']['reaction'],
            'product_material_id': branch['product_material_id'], 'product_vessel_id': branch['vessels']['product'],
            'required_labware': copy.deepcopy(required_labware),
            'actual_runtime_material_id': None, 'material_effect': 'none',
            'excluded_branch_ids': [other['id'] for other in cutrun['branches'] if other is not branch]},
        'device_candidate': copy.deepcopy(protocol['device_candidate']),
        'parameters': copy.deepcopy(profile['parameters']),
        'pulse_plan': {**copy.deepcopy(protocol['pulse_timing']), 'cycles': cycles,
            'pulse_on_s': on, 'between_pulses_s': pause, 'total_on_s': total_on,
            'total_between_pulses_s': total_pause, 'nominal_elapsed_s': elapsed,
            'energy_delivered_j': None, 'executed': False},
        'fragment_size': {'comparison_target': copy.deepcopy(target),
            'column_maximum_exclusive_bp': copy.deepcopy(limit),
            'observed_result': None, 'accepted': False,
            'evidence_requirement': 'Independent identified size result; NanoDrop/Qubit concentration is insufficient'},
        'manual_binding': {'stage': 'S09', 'decision': 'O04', 'status': 'open_not_an_approval'},
        'effects': {'hardware_executed': False, 'network_executed': False, 'ros_executed': False,
            'inventory_booked': False, 'resources_reserved': False, 'journal_written': False},
        'execution_blockers': ['local_sonication_and_labware_unqualified', 'amplitude_and_cooling_unqualified',
            'reference_temperature_not_all_sample_temperatures', 'input_fragment_size_evidence_required',
            'root_effect_binding_unimplemented', 'model_firmware_command_and_receipt_contract_unbound'],
        'references': copy.deepcopy(protocol['references']), 'limitations': copy.deepcopy(protocol['limitations'])}
