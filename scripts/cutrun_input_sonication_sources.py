"""Freeze an explicit test-only S09 composition on the existing material root.

The unchanged manual SOP compiler retains its real open requirements. Only
this separate fixture engine may use a synthetic gate map; no manufacturer
original, local qualification or laboratory approval is manufactured.
"""
import copy
from pathlib import Path

import assembly_model
import cutrun_manual_sources as base
import cutrun_manual_sop_sources as sop
import dna_sonication
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-input-sonication.profile.json'
SCHEMA = 'model/cutrun-input-sonication.schema.json'
ENGINE = 'input_sonication_mock/1'
RUNTIME = ('scripts/cutrun_input_sonication_sources.py',
           'scripts/cutrun_input_sonication_workflow.py',
           'scripts/run_cutrun_input_sonication.py',
           'scripts/cutrun_input_sonication_demo.py',
           'model/cutrun-input-sonication.profile.json',
           'model/cutrun-input-sonication.fixture.json', SCHEMA)
REFS = {'manual_profile': 'model/cutrun-manual-runtime.profile.json',
        'sop_profile': 'model/cutrun-manual-sop.profile.json',
        'sop_protocol': 'model/cutrun-manual-sop.protocol.json',
        'sonication_profile': 'model/dna-sonication.profile.json'}
SCOPE = {'stage_id': 'S09', 'phase_id': 'S09.input_preparation',
         'decision_id': 'O04', 'role': 'input'}
FIXTURE_STAGES = frozenset({'S01', 'S02', 'S09'})


def require(condition, message):
    if not condition:
        raise TaskError(message)


def _read(value, default):
    if isinstance(value, dict):
        data = copy.deepcopy(value)
        try:
            return data, encoded(data).encode(), None
        except (TypeError, ValueError) as error:
            raise TaskError('Finite fixture profile JSON required') from error
    path = default if value is None else Path(value)
    content = path.read_bytes()
    return base._json(content, 'input sonication fixture source'), content, path


def _reference(ref, name, pins, artifacts):
    base.keys(ref, ('source', 'source_sha256'), 'fixture source reference')
    require(ref['source'] == REFS[name], 'Unsupported fixture source reference: ' + name)
    try:
        path = assembly_model.validate_reference(ref, root=ROOT)
        content = path.read_bytes()
    except (ValueError, TypeError, OSError) as error:
        raise TaskError('Invalid fixture source reference: ' + name) from error
    checksum = digest(content)
    require(checksum == ref['source_sha256'], 'Fixture source changed: ' + name)
    pins[ref['source']] = checksum
    artifacts[checksum] = content
    return base._json(content, name)


def _selection(source):
    if source is None:
        return None, None, None
    if not isinstance(source, dict):
        return source, None, None
    allowed = {'runtime_profile', 'manual_source', 'sonication_source'}
    require(set(source) <= allowed, 'Unknown input-sonication source selection')
    return (source.get('runtime_profile'), source.get('manual_source'),
            source.get('sonication_source'))


def _verify(pins):
    for name, checksum in pins.items():
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT.resolve()) and path.is_file()
                and digest(path.read_bytes()) == checksum,
                'Input sonication source changed: ' + name)


def compile_profile(source=None, *, original_pdf=None, evidence_files=None):
    """Read-only fixture composition; all real laboratory gates stay open."""
    require(original_pdf is None, 'The fixture engine does not accept a manufacturer PDF substitute')
    runtime_source, manual_source, sonication_source = _selection(source)
    profile, profile_bytes, profile_path = _read(runtime_source, SOURCE)
    base.keys(profile, ('format', 'id', 'mode', 'enabled', 'bindings', 'sources', 'scope'),
              'input sonication fixture profile')
    require(profile['format'] == 'solidcraftbot.cutrun-input-sonication-profile/1'
            and profile['mode'] == 'test_fixture_only', 'Explicit test-only sonication profile required')
    base.text(profile['id'], 'fixture profile identity')
    require(type(profile['enabled']) is bool, 'Explicit optional sonication selection required')
    require(profile['scope'] == SCOPE, 'Only the separate S09 input scope is supported')
    base.keys(profile['bindings'], ('input_reaction_id', 'vessel_class', 'sonicator_place_id'), 'fixture identity bindings')
    require(profile['bindings']['vessel_class'] == 'tube_1_5ml', 'Explicit 1.5 ml fixture class required')
    base.text(profile['bindings']['sonicator_place_id'], 'declared sonicator fixture place')
    identity = profile['bindings']['input_reaction_id']
    if identity is not None:
        base.text(identity, 'fixture input reaction identity')
    base.keys(profile['sources'], REFS, 'fixture pinned sources')
    pins, artifacts = {}, {}
    defaults = {name: _reference(profile['sources'][name], name, pins, artifacts) for name in REFS}
    if manual_source is None:
        manual_source = {'base_profile': defaults['manual_profile'], 'sop_profile': defaults['sop_profile']}
    compiled = sop.compile_profile(manual_source, original_pdf=None, evidence_files=evidence_files)
    plan_source = defaults['sonication_profile'] if sonication_source is None else sonication_source
    sonic_profile, sonic_bytes, sonic_path = _read(plan_source, dna_sonication.SOURCE)
    plan = dna_sonication.compile_plan(sonic_profile)
    phase_temperature = compiled['sop_profile']['phase_requirements']['S09.input_preparation']['temperature_max_deg_c']
    sonication_limit = plan['parameters']['temperature_limit_deg_c']['value']
    require(phase_temperature is None or sonication_limit is None or phase_temperature <= sonication_limit,
            'S09 temperature bound exceeds the declared sonication limit')
    for incoming in (compiled['source_files_sha256'], plan['source_files_sha256']):
        for name, checksum in incoming.items():
            require(name not in pins or pins[name] == checksum,
                    'Source changed while composing input sonication: ' + name)
            pins[name] = checksum
    artifacts.update(compiled['evidence_artifacts'])
    artifacts[digest(profile_bytes)] = profile_bytes
    artifacts[digest(sonic_bytes)] = sonic_bytes
    # Preserve actual effective overrides as fixture originals, never as a
    # rewritten manufacturer document or a historical source replacement.
    for value in (profile, sonic_profile, compiled['manual_profile'], compiled['sop_profile']):
        content = encoded(value).encode()
        artifacts[digest(content)] = content
    if profile_path is not None and profile_path.resolve().is_relative_to(ROOT.resolve()):
        pins[str(profile_path.resolve().relative_to(ROOT.resolve()))] = digest(profile_bytes)
    if sonic_path is not None and sonic_path.resolve().is_relative_to(ROOT.resolve()):
        name = str(sonic_path.resolve().relative_to(ROOT.resolve()))
        require(name not in pins or pins[name] == digest(sonic_bytes),
                'Sonication override source changed after reading')
        pins[name] = digest(sonic_bytes)
    names = list(dict.fromkeys([*compiled['runtime_source_files'], *pins, *RUNTIME]))
    for name in names:
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT.resolve()) and path.is_file(), 'Fixture runtime source missing: ' + name)
        content = path.read_bytes()
        checksum = digest(content)
        require(name not in pins or pins[name] == checksum, 'Fixture source changed after parsing: ' + name)
        pins[name] = checksum
        artifacts[checksum] = content
    _verify(pins)
    raw_requirements = copy.deepcopy(compiled['open_requirements'])
    synthetic = {stage: stage in FIXTURE_STAGES for stage in base.STAGES}
    for item in raw_requirements:
        if item['id'] != 'manufacturer_original':
            for stage in item['stage_ids']:
                synthetic[stage] = False
    if (not profile['enabled'] or identity is None or not plan['planning_complete']
            or phase_temperature is None or sonication_limit is None):
        synthetic['S09'] = False
    return {**compiled, 'runtime_profile': profile, 'sonication_plan': plan,
        'source_files_sha256': pins, 'runtime_source_files': names, 'evidence_artifacts': artifacts,
        'raw_open_requirements': raw_requirements,
        'real_stage_readiness': copy.deepcopy(compiled['stage_readiness']),
        'synthetic_gate_readiness': synthetic,
        'fixture_source_artifacts': {'runtime_profile_sha256': digest(profile_bytes),
                                     'sonication_profile_sha256': digest(sonic_bytes)},
        'preparation_complete': False, 'can_claim_reference_success': False,
        'test_fixture_only': True, 'original_pdf_verified': False,
        'effective_profile_sha256': digest(encoded({'manual': compiled['effective_profile_sha256'],
            'runtime_profile': profile, 'sonication_profile': plan['effective_profile_sha256']}).encode())}


def load(source=None, *, materials, vessels, clock_source_kind, original_pdf=None,
         evidence_files=None, protective_stop_bindings=None):
    require(clock_source_kind == 'test_clock', 'Input sonication mock requires an explicit test clock')
    require(original_pdf is None, 'The fixture engine cannot authenticate a manufacturer PDF')
    runtime_source, manual_source, sonication_source = _selection(source)
    # Resolve defaults once, then use exactly the same effective source inputs
    # for the existing immutable material definition and the new composition.
    compiled = compile_profile(source, original_pdf=None, evidence_files=evidence_files)
    if manual_source is None:
        manual_source = {'base_profile': compiled['manual_profile'], 'sop_profile': compiled['sop_profile']}
    definition = sop.load(manual_source, materials=materials, vessels=vessels,
        clock_source_kind=clock_source_kind, original_pdf=None, evidence_files=evidence_files,
        protective_stop_bindings=protective_stop_bindings)
    artifacts = definition.pop('_initial_artifacts')
    for name, checksum in definition['source_files_sha256'].items():
        require(compiled['source_files_sha256'].get(name) == checksum,
                'SOP source changed during fixture definition: ' + name)
    artifacts.update(compiled['evidence_artifacts'])
    for name in ('runtime_profile', 'sonication_plan', 'raw_open_requirements',
                 'real_stage_readiness', 'synthetic_gate_readiness', 'source_files_sha256',
                 'runtime_source_files', 'effective_profile_sha256', 'test_fixture_only',
                 'fixture_source_artifacts'):
        definition[name] = copy.deepcopy(compiled[name])
    definition['stage_readiness'] = copy.deepcopy(compiled['synthetic_gate_readiness'])
    definition['open_requirements'] = copy.deepcopy(compiled['raw_open_requirements'])
    definition['preparation_complete'] = False
    definition['original_pdf_verified'] = False
    definition['can_claim_reference_success'] = False
    definition['profile']['type'] = ENGINE
    definition['profile']['id'] = compiled['runtime_profile']['id']
    definition['preparation_plan']['mode'] = 'input_sonication_test_fixture_only'
    definition['_initial_artifacts'] = artifacts
    _verify(definition['source_files_sha256'])
    return definition
