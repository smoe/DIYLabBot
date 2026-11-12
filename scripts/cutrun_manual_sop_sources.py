"""Bind the SOP stage graph and prospective phase evidence without execution.

The existing manual profile remains its own source. This separate composite
contract adds no guessed laboratory values and migrates no existing run.
"""
import copy
import json
import math
from pathlib import Path

import cutrun_manual_sources as base
from manual_tasks import TaskError, digest, encoded


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-manual-sop.profile.json'
PROTOCOL = 'model/cutrun-manual-sop.protocol.json'
PROFILE_SCHEMA = 'model/cutrun-manual-sop.profile.schema.json'
PROTOCOL_SCHEMA = 'model/cutrun-manual-sop.protocol.schema.json'
FORMAT = 'solidcraftbot.cutrun-manual-sop-profile/1'
ENGINE = 'cutrun_manual_sop/1'
PHASES = ('S03.preparation', 'S04.antibody_incubation', 'S05.enzyme_incubation',
          'S07.digestion', 'S08.release', 'S08.separation',
          'S09.input_preparation', 'S10.purification')
PHASE_FIELDS = ('duration_min_s', 'duration_max_s', 'temperature_min_deg_c',
                'temperature_max_deg_c', 'time_qualification_ref',
                'temperature_qualification_ref', 'evidence_ref')
RUNTIME = tuple(dict.fromkeys((*base.RUNTIME, 'scripts/cutrun_manual_sop_sources.py',
           'scripts/cutrun_manual_sop_workflow.py', 'scripts/cutrun_sop_evidence.py',
           PROTOCOL, 'model/cutrun-manual-sop.profile.json', PROFILE_SCHEMA, PROTOCOL_SCHEMA)))


def require(condition, message):
    if not condition:
        raise TaskError(message)


def _keys(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields), 'Invalid fields for ' + label)


def _text(value, label):
    require(isinstance(value, str) and bool(value.strip()), 'Nonempty ' + label + ' required')
    return value


def _repo(name):
    path = (ROOT / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(ROOT.resolve()) and path.is_file(),
            'Repository SOP source missing: ' + name)
    return path


def _read(source, default=None):
    if isinstance(source, dict):
        value = copy.deepcopy(source)
        try:
            content = encoded(value).encode()
        except (TypeError, ValueError) as error:
            raise TaskError('Finite SOP source JSON required') from error
        return value, content, None
    try:
        path = Path(source) if source is not None else default
        content = path.read_bytes()
    except (OSError, TypeError, AttributeError) as error:
        raise TaskError('Cannot read explicitly selected SOP source') from error
    return base._json(content, 'manual SOP source'), content, path


def _selection(source):
    if source is None:
        return None, None
    _keys(source, ('base_profile', 'sop_profile'), 'composite manual SOP source')
    return source['base_profile'], source['sop_profile']


def _protocol():
    protocol, content, unused = _read(_repo(PROTOCOL))
    _keys(protocol, ('format', 'id', 'sop', 'global_stages', 'branch_sequences', 'stages'), 'SOP protocol')
    require(protocol['format'] == 'solidcraftbot.cutrun-manual-sop-protocol/1', 'Unknown SOP protocol format')
    _text(protocol['id'], 'SOP protocol identity')
    require(protocol['sop'] == {'id': 'SOP-CR-SKM29-H3K4me3', 'revision': '0.1'}, 'SOP draft 0.1 required')
    require(protocol['global_stages'] == ['S01', 'S11', 'S12'], 'Explicit opening, QC and handover stages required')
    _keys(protocol['stages'], base.STAGES, 'complete SOP stage graph')
    _keys(protocol['branch_sequences'], ('h3k4me3', 'igg', 'input'), 'SOP branch paths')
    covered, phases = set(protocol['global_stages']), {}
    for role, sequence in protocol['branch_sequences'].items():
        require(isinstance(sequence, list) and sequence and len(sequence) == len(set(sequence))
                and all(stage in base.STAGES and stage not in protocol['global_stages'] for stage in sequence),
                'Unique known branch stages required')
        require(sequence[0] == 'S02' and sequence[-1] == 'S10', 'Branch path must connect input and purification')
        require(sequence == sorted(sequence), 'SOP branch path cannot move backwards')
        if role == 'input':
            require(sequence == ['S02', 'S09', 'S10'], 'Input has no CUT&RUN activation branch')
        else:
            require('S09' not in sequence and all(stage in sequence for stage in ('S03','S04','S05','S06','S07','S08')),
                    'CUT&RUN branch needs preparation, binding, activation and stop')
        covered.update(sequence)
    require(covered == set(base.STAGES), 'Every SOP stage must be represented')
    for stage, record in protocol['stages'].items():
        _keys(record, ('scope', 'roles', 'phases', 'completion_evidence'), 'SOP stage ' + stage)
        require(record['scope'] == ('run' if stage in protocol['global_stages'] else 'reaction'), 'Wrong stage scope')
        expected = (['h3k4me3', 'igg', 'input', 'ntc'] if stage == 'S11' else
                    ['h3k4me3', 'igg', 'input'] if stage in {'S01', 'S12'} else
                    [role for role, path in protocol['branch_sequences'].items() if stage in path])
        require(record['roles'] == expected, 'SOP stage roles must match its branch paths')
        for name in ('phases', 'completion_evidence'):
            values = record[name]
            require(isinstance(values, list) and len(values) == len(set(values))
                    and all(isinstance(item, str) and item.strip() for item in values), 'Unique stage evidence names required')
        require(bool(record['completion_evidence']), 'A stage needs explicit completion evidence')
        require(record['phases'] == sorted(record['phases']), 'SOP phases must retain their required order')
        for phase in record['phases']:
            require(phase.startswith(stage + '.'), 'SOP phase belongs to another stage')
            require(phase not in phases, 'Phase belongs to more than one SOP stage')
            phases[phase] = stage
    require(set(phases) == set(PHASES), 'Mandatory SOP time/temperature phases cannot be removed')
    return protocol, content, phases


def _augment(compiled, source):
    protocol, protocol_bytes, phase_stages = _protocol()
    profile, profile_bytes, profile_path = _read(source, ROOT / 'model/cutrun-manual-sop.profile.json')
    _keys(profile, ('format', 'id', 'mode', 'synthetic', 'phase_requirements', 'qualifications'), 'manual SOP profile')
    require(profile['format'] == FORMAT and profile['mode'] == 'manual_observation' and profile['synthetic'] is False,
            'Separate manual SOP profile required')
    _text(profile['id'], 'SOP profile identity')
    _keys(profile['phase_requirements'], phase_stages, 'all SOP phase requirements')
    require(isinstance(profile['qualifications'], dict), 'Explicit prospective qualifications required')
    evidence_records = compiled['evidence_records']

    def evidence(value, label):
        _text(value, label)
        require(value in evidence_records, 'Unregistered original evidence reference: ' + value)

    for identity, qualification in profile['qualifications'].items():
        _text(identity, 'qualification identity')
        _keys(qualification, ('kind', 'source_id', 'relationship', 'evidence_ref'), 'prospective qualification')
        require(isinstance(qualification['kind'], str) and qualification['kind'] in {'time', 'temperature'}, 'Unknown qualification kind')
        _text(qualification['source_id'], 'qualified source identity')
        require(qualification['relationship'] is None or isinstance(qualification['relationship'], str)
                and qualification['relationship'] in {'sample_measurement', 'qualified_proxy', 'device_setpoint'},
                'Unknown specimen temperature relationship')
        require(qualification['kind'] != 'time' or qualification['relationship'] is None,
                'Time qualification does not assert a specimen temperature relationship')
        evidence(qualification['evidence_ref'], 'qualification evidence reference')
    requirements = copy.deepcopy(compiled['open_requirements'])
    readiness = copy.deepcopy(compiled['stage_readiness'])
    for phase, binding in profile['phase_requirements'].items():
        _keys(binding, PHASE_FIELDS, 'phase requirement ' + phase)
        ready = True
        for field in PHASE_FIELDS[:4]:
            value = binding[field]
            if value is None:
                ready = False
            else:
                try:
                    finite = type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    finite = False
                require(finite, 'Finite phase bound required: ' + field)
                require(not field.startswith('duration_') or value >= 0, 'Negative phase duration')
        for low, high in (('duration_min_s', 'duration_max_s'), ('temperature_min_deg_c', 'temperature_max_deg_c')):
            require(binding[low] is None or binding[high] is None or binding[low] <= binding[high],
                    'Reversed phase requirement interval: ' + phase)
        if binding['evidence_ref'] is None:
            ready = False
        else:
            evidence(binding['evidence_ref'], 'phase decision evidence')
        for field, kind in (('time_qualification_ref', 'time'), ('temperature_qualification_ref', 'temperature')):
            identity = binding[field]
            if identity is None:
                ready = False
                continue
            _text(identity, 'prospective qualification reference')
            require(identity in profile['qualifications'] and profile['qualifications'][identity]['kind'] == kind,
                    'Missing or mismatched prospective ' + kind + ' qualification')
            if kind == 'temperature' and profile['qualifications'][identity]['relationship'] not in {'sample_measurement', 'qualified_proxy'}:
                ready = False
        if not ready:
            stage = phase_stages[phase]
            affected = list(dict.fromkeys([stage, *(['S06', 'S07'] if stage in {'S07', 'S08'} else [])]))
            requirements.append({'id': 'sop.phase.' + phase, 'reason': 'Local time/temperature bounds or qualified original evidence remain open',
                                 'stage_ids': affected})
            for affected_stage in affected:
                readiness[affected_stage] = False
    pins = copy.deepcopy(compiled['source_files_sha256'])
    artifacts = dict(compiled['evidence_artifacts'])
    artifacts[digest(protocol_bytes)] = protocol_bytes
    artifacts[digest(profile_bytes)] = profile_bytes
    names = list(dict.fromkeys([*compiled['runtime_source_files'], *RUNTIME]))
    source_pins = {PROTOCOL: digest(protocol_bytes)}
    if profile_path is not None and profile_path.resolve().is_relative_to(ROOT.resolve()):
        source_pins[str(profile_path.resolve().relative_to(ROOT.resolve()))] = digest(profile_bytes)
    for name in RUNTIME:
        checksum = digest(_repo(name).read_bytes())
        require(name not in source_pins or source_pins[name] == checksum, 'SOP source changed after parsing: ' + name)
        require(name not in pins or pins[name] == checksum, 'Base source changed during SOP compilation: ' + name)
        pins[name] = checksum
    pins.update(source_pins)
    for name, checksum in pins.items():
        require(digest(_repo(name).read_bytes()) == checksum, 'SOP source changed during compilation: ' + name)
    return {**compiled, 'sop_protocol': protocol, 'sop_profile': profile, 'source_files_sha256': pins,
            'runtime_source_files': names, 'open_requirements': requirements, 'stage_readiness': readiness,
            'preparation_complete': not requirements, 'can_claim_reference_success': False,
            'evidence_artifacts': artifacts,
            'effective_profile_sha256': digest(encoded({'base': compiled['effective_profile_sha256'],
                                                       'protocol': protocol, 'profile': profile}).encode())}


def compile_profile(source=None, *, original_pdf=None, evidence_files=None):
    """Read-only preparation; missing phase bindings remain explicitly open."""
    base_source, sop_source = _selection(source)
    compiled = base.compile_profile(base_source, original_pdf=original_pdf, evidence_files=evidence_files)
    return _augment(compiled, sop_source)


def load(source=None, *, materials, vessels, clock_source_kind, original_pdf=None,
         evidence_files=None, protective_stop_bindings=None):
    """Freeze a new SOP engine while reusing the existing material /3 contract."""
    base_source, sop_source = _selection(source)
    definition = base.load(base_source, materials=materials, vessels=vessels, clock_source_kind=clock_source_kind,
                           original_pdf=original_pdf, evidence_files=evidence_files,
                           protective_stop_bindings=protective_stop_bindings)
    artifacts = definition.pop('_initial_artifacts')
    compiled = {name: copy.deepcopy(definition[name]) for name in
                ('manual_profile', 'source_files_sha256', 'runtime_source_files', 'open_requirements',
                 'stage_readiness', 'can_archive', 'can_claim_reference_success', 'preparation_complete',
                 'original_pdf_verified', 'evidence_records', 'effective_profile_sha256')}
    compiled['evidence_artifacts'] = artifacts
    augmented = _augment(compiled, sop_source)
    for name in ('sop_protocol', 'sop_profile', 'source_files_sha256', 'runtime_source_files',
                 'open_requirements', 'stage_readiness', 'preparation_complete', 'effective_profile_sha256'):
        definition[name] = augmented[name]
    definition['profile']['type'] = ENGINE
    definition['profile']['id'] = augmented['sop_profile']['id']
    definition['preparation_plan']['mode'] = 'manual_sop_contract'
    definition['_initial_artifacts'] = augmented['evidence_artifacts']
    return definition
