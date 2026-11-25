"""Bind phase-specific S09 observations to the existing manual recipe definition."""

import copy
import math
from pathlib import Path

import cutrun_manual_recipe_sources as recipe
import cutrun_manual_sop_sources as sop
from manual_tasks import digest, encoded
from manual_workflow import keys, text


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'model/cutrun-manual-sop-v2.profile.json'
PROTOCOL = 'model/cutrun-manual-sop-v2.protocol.json'
PREFLIGHT = 'model/cutrun-automation-v3.preparation.json'
PROFILE_FORMAT = 'solidcraftbot.cutrun-manual-sop-profile/2'
PROTOCOL_FORMAT = 'solidcraftbot.cutrun-manual-sop-protocol/2'
ENGINE = 'cutrun_manual_recipe/2'
LYSIS, SONICATION, CLARIFICATION = ('S09.extraction_lysis', 'S09.input_preparation', 'S09.supernatant_clarification')
PHASES = (LYSIS, SONICATION, CLARIFICATION)
MODES = {'manual_observation': 'system_clock', 'test_fixture': 'test_clock'}
BINDINGS = ('input_reaction_id', 'device_instance_id', 'sonicator_place_id', 'cycles', 'pulse_on_s',
            'between_pulses_s', 'amplitude_percent', 'fill_volume_ul', 'plan_evidence_ref',
            'size_minimum_bp', 'size_maximum_bp', 'size_criteria_evidence_ref')
RUNTIME = ('scripts/cutrun_manual_recipe_v2_sources.py', 'scripts/cutrun_manual_recipe_v2_workflow.py',
           'scripts/cutrun_input_sonication_workflow.py', 'scripts/cutrun_input_sonication_sources.py',
           'scripts/run_cutrun_manual_v2.py', 'model/cutrun-manual-sop-v2.schema.json', SOURCE, PROTOCOL)
require = recipe.require


def selection(source):
    if source is None:
        return {'base_profile': None, 'sop_profile': None, 'recipe_profile': None, 'input_profile': None}
    keys(source, 'base_profile sop_profile recipe_profile input_profile', 'consolidated manual source')
    return source


def _pinned(reference, name, pins, artifacts):
    keys(reference, 'source source_sha256', 'pinned source reference')
    require(reference['source'] == name, 'Unexpected source path for ' + name)
    path = (ROOT / name).resolve()
    require(path.is_relative_to(ROOT.resolve()), 'Source must remain inside the repository')
    data, content, _ = sop._read(path)
    checksum = digest(content)
    require(checksum == reference['source_sha256'] and pins.get(name, checksum) == checksum,
            'Source revision changed: ' + name)
    pins[name] = checksum
    artifacts[checksum] = content
    return data


def _local_plan(profile, evidence_records, phases):
    data = profile['input_sonication']
    keys(data, ' '.join(BINDINGS), 'local sonication and fragment-size bindings')
    for name in ('input_reaction_id', 'device_instance_id', 'sonicator_place_id'):
        if data[name] is not None:
            text(data[name], 'actual ' + name)
    for name in ('plan_evidence_ref', 'size_criteria_evidence_ref'):
        if data[name] is not None:
            text(data[name], name)
            require(data[name] in evidence_records, 'Missing original local evidence: ' + name)
    cycles = data['cycles']
    require(cycles is None or type(cycles) is int and cycles > 0, 'Positive integer pulse count required')
    for name in ('pulse_on_s', 'between_pulses_s', 'amplitude_percent', 'fill_volume_ul',
                 'size_minimum_bp', 'size_maximum_bp'):
        value = data[name]
        require(value is None or type(value) in (int, float) and math.isfinite(value)
                and (value >= 0 if name == 'between_pulses_s' else value > 0), 'Invalid local ' + name)
    require(data['amplitude_percent'] is None or data['amplitude_percent'] <= 100, 'Amplitude exceeds percentage range')
    low, high = data['size_minimum_bp'], data['size_maximum_bp']
    require(low is None or high is None or low <= high, 'Reversed fragment-size criteria')
    on, pause = data['pulse_on_s'], data['between_pulses_s']
    try:
        elapsed = None if None in (cycles, on, pause) else cycles * on + (cycles - 1) * pause
        finite = elapsed is None or math.isfinite(elapsed)
    except OverflowError:
        finite = False
    require(finite, 'Finite pulse duration required')
    phase_max = phases[SONICATION]['duration_max_s']
    require(elapsed is None or phase_max is None or elapsed <= phase_max, 'Pulse plan exceeds the locally bound phase duration')
    return {
        'planning_complete': all(data[name] is not None for name in BINDINGS),
        'parameters': {name: {'value': data[name]} for name in ('device_instance_id', 'fill_volume_ul')},
        'pulse_plan': {'cycles': cycles, 'pulse_on_s': on, 'between_pulses_s': pause,
                       'amplitude_percent': data['amplitude_percent'], 'nominal_elapsed_s': elapsed,
                       'plan_evidence_ref': data['plan_evidence_ref'], 'executed': False},
        'fragment_size': {'comparison_target': {'minimum': low, 'maximum': high, 'unit': 'bp',
                                               'evidence_ref': data['size_criteria_evidence_ref']},
                          'column_maximum_exclusive_bp': {'value': None}},
    }


def _augment(compiled, selected, artifacts):
    profile, content, path = sop._read(selected, ROOT / SOURCE)
    keys(profile, 'format id mode protocol phase_requirements input_sonication', 'consolidated SOP profile')
    require(profile['format'] == PROFILE_FORMAT and profile['mode'] in MODES, 'Explicit consolidated SOP version and mode required')
    text(profile['id'], 'consolidated profile identity')
    phases = profile['phase_requirements']
    keys(phases, ' '.join(PHASES), 'three input phase requirements')
    pins = dict(compiled['source_files_sha256'])
    protocol = _pinned(profile['protocol'], PROTOCOL, pins, artifacts)
    keys(protocol, 'format sop base_protocol preflight recipe_protocol s09_phases', 'consolidated SOP protocol')
    require(protocol['format'] == PROTOCOL_FORMAT and protocol['sop'] == compiled['sop_protocol']['sop']
            and protocol['s09_phases'] == list(PHASES), 'Mandatory ordered S09 phase contract required')
    for field, name in [('base_protocol', sop.PROTOCOL), ('recipe_protocol', recipe.PROTOCOL), ('preflight', PREFLIGHT)]:
        _pinned(protocol[field], name, pins, artifacts)

    # Reuse the frozen /1 compiler for each local interval binding. Its only
    # original S09 slot is a validation input here, never a persisted /1 run.
    source = copy.deepcopy(compiled['sop_profile'])
    base_requirements = [item for item in compiled['open_requirements'] if item['id'] != 'sop.phase.' + SONICATION]
    requirements = list(base_requirements)
    for phase, binding in phases.items():
        source['phase_requirements'][SONICATION] = binding
        validated = sop._augment({**compiled, 'evidence_artifacts': artifacts,
                                 'open_requirements': base_requirements}, source)
        for item in validated['open_requirements']:
            if item['id'] == 'sop.phase.' + SONICATION:
                candidate = {**item, 'id': 'sop.phase.' + phase}
                if candidate not in requirements:
                    requirements.append(candidate)
    plan = _local_plan(profile, compiled['evidence_records'], phases)
    if not plan['planning_complete']:
        requirements.append({'id': 'input_sonication', 'stage_ids': ['S09'],
                             'reason': 'Actual sonicator, pulse plan and fragment-size criteria remain open'})
    fixture = profile['mode'] == 'test_fixture'
    require(not fixture or not compiled['original_pdf_verified'], 'Fixture mode does not accept a manufacturer PDF')
    blocked = {stage for item in requirements if not (fixture and item['id'] == 'manufacturer_original')
               for stage in item['stage_ids']}
    gates = {stage: stage not in blocked for stage in compiled['stage_readiness']}
    effective_protocol = copy.deepcopy(compiled['sop_protocol'])
    effective_protocol['format'] = PROTOCOL_FORMAT
    effective_protocol['stages']['S09']['phases'] = list(PHASES)
    effective_profile = copy.deepcopy(compiled['sop_profile'])
    effective_profile['format'] = PROFILE_FORMAT
    effective_profile['phase_requirements'].update(phases)
    artifacts[digest(content)] = content
    if path is not None and path.resolve().is_relative_to(ROOT):
        pins[str(path.resolve().relative_to(ROOT))] = digest(content)
    for name in RUNTIME:
        checksum = digest((ROOT / name).read_bytes())
        require(pins.get(name, checksum) == checksum, 'Runtime source changed during consolidation: ' + name)
        pins[name] = checksum
    for name, checksum in pins.items():
        require(digest((ROOT / name).read_bytes()) == checksum, 'Source changed during consolidation: ' + name)
    return {
        **compiled, 'sop_protocol': effective_protocol, 'sop_profile': effective_profile,
        'runtime_engine': ENGINE,
        'runtime_profile': {'enabled': True, 'mode': profile['mode'],
                            'bindings': {name: profile['input_sonication'][name] for name in ('input_reaction_id', 'sonicator_place_id')}},
        'sonication_plan': plan, 'clock_source_kind': MODES[profile['mode']],
        'test_fixture_only': fixture, 'source_files_sha256': pins,
        'runtime_source_files': list(dict.fromkeys([*compiled['runtime_source_files'], *pins])),
        'open_requirements': requirements, 'stage_readiness': gates,
        'raw_open_requirements': requirements,
        'synthetic_gate_readiness': gates if fixture else {},
        'real_stage_readiness': dict.fromkeys(gates, False) if fixture else gates,
        'preparation_complete': not fixture and not requirements,
        'effective_profile_sha256': digest(encoded({'base': compiled['effective_profile_sha256'],
                                                   'profile': profile, 'protocol': protocol}).encode()),
    }


def compile_profile(source=None, **kwargs):
    selected = selection(source)
    compiled = recipe.compile_profile({key: selected[key] for key in ('base_profile', 'sop_profile', 'recipe_profile')}, **kwargs)
    return _augment(compiled, selected['input_profile'], compiled['evidence_artifacts'])


def load(source=None, *, clock_source_kind, **kwargs):
    selected = selection(source)
    definition = recipe.load({key: selected[key] for key in ('base_profile', 'sop_profile', 'recipe_profile')},
                             clock_source_kind=clock_source_kind, **kwargs)
    combined = _augment(definition, selected['input_profile'], definition['_initial_artifacts'])
    require(combined['clock_source_kind'] == clock_source_kind, 'Profile mode and clock source must agree')
    # The shared ledger uses this legacy profile type to select its prepared
    # mixture and protective-stop invariants. The executing engine is separate.
    combined['preparation_plan']['mode'] = 'manual_recipe_input_contract'
    return combined
