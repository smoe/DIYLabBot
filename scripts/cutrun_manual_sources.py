"""Read-only source binding for the manual CUT&RUN capture contract.

No synthetic preparation compiler is used. Missing laboratory decisions remain
open, and no quantities, time limits, approvals or successful outcomes are
inferred. Transient artifact bytes returned by this module must be removed from
the JSON definition and committed atomically by the common Journal factory.
"""

import copy
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import material_ledger
import material_workflow_sources
from manual_tasks import TaskError, digest, encoded


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-manual-runtime.profile.json'
SCHEMA = 'model/cutrun-manual-runtime.schema.json'
FORMAT = 'solidcraftbot.cutrun-manual-runtime-profile/1'
STAGES = tuple('S%02d' % index for index in range(1, 13))
DECISIONS = tuple('O%02d' % index for index in range(1, 12))
ROLE_TYPES = {'h3k4me3': 'reference', 'igg': 'negative_control', 'input': 'input', 'ntc': 'pcr_ntc'}
UNITS = {'task_deadline_s': 's', 'activation_volume_ul': 'uL', 'stop_volume_ul': 'uL',
         'activation_duration_s': 's', 'stop_window_s': 's', 'temperature_tolerance_deg_c': 'degC',
         'activation_temperature_deg_c': 'degC', 'phase_tolerance_s': 's', 'input_cells': 'cells'}
GLOBAL_DECISIONS = ['O06', 'O07', 'O08', 'O09', 'O11']
LOCAL_DECISIONS = {'S01': [], 'S02': ['O01', 'O02'], 'S03': ['O01', 'O02', 'O03', 'O10'],
                   'S04': ['O03'], 'S05': ['O03'], 'S06': ['O03', 'O05'],
                   'S07': ['O03', 'O05'], 'S08': ['O03', 'O05'], 'S09': ['O04'],
                   'S10': ['O03', 'O04'], 'S11': ['O08'], 'S12': ['O07']}
STAGE_PARAMETERS = {'S02': ['input_cells'], 'S06': list(UNITS), 'S07': list(UNITS),
                    'S08': ['stop_volume_ul', 'stop_window_s', 'temperature_tolerance_deg_c',
                            'phase_tolerance_s', 'task_deadline_s']}
SECTIONS = {'S01': '5. Manuelle Arbeitsfolge und Aufzeichnungen',
            'S02': '4. Material-, Gefäß- und Arbeitsplatzplan',
            'S03': '3.2 Quellengeprüfte Eckwerte',
            'S04': '5. Manuelle Arbeitsfolge und Aufzeichnungen',
            'S05': '5. Manuelle Arbeitsfolge und Aufzeichnungen',
            'S06': '6. Stopp, Unterbrechung und Abweichungen',
            'S07': '6. Stopp, Unterbrechung und Abweichungen',
            'S08': '6. Stopp, Unterbrechung und Abweichungen',
            'S09': '3.1 Lokale Auswahl in Fassung 0.1',
            'S10': '5. Manuelle Arbeitsfolge und Aufzeichnungen',
            'S11': '7. Produkt-QC und Abschlusskriterien',
            'S12': '7. Produkt-QC und Abschlusskriterien'}
RUNTIME = tuple(dict.fromkeys((*material_workflow_sources.RUNTIME,
    'scripts/material_evidence.py', 'scripts/manual_process_clock.py',
    'scripts/cutrun_manual_sources.py', 'scripts/cutrun_manual_workflow.py',
    'scripts/run_cutrun_manual.py', SCHEMA)))


def require(condition, message):
    if not condition:
        raise TaskError(message)


def keys(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names), 'Invalid fields for ' + label)


def text(value, label):
    require(isinstance(value, str) and value.strip(), 'Nonempty ' + label + ' required')
    return value


def optional_text(value, label):
    if value is not None:
        text(value, label)


def _json(content, label):
    try:
        return json.loads(content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                          object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as error:
        raise TaskError('Invalid JSON in ' + label) from error


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate object field')
        result[key] = value
    return result


def _read(path, label):
    try:
        return Path(path).read_bytes()
    except (OSError, TypeError, ValueError) as error:
        raise TaskError('Cannot read ' + label) from error


def _repo_file(name):
    text(name, 'repository source path')
    path = (ROOT / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(ROOT.resolve()) and path.is_file(),
            'Source must be a repository file: ' + name)
    return path


def _checksum(value, label):
    require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'SHA-256 required for ' + label)


def _confirmed_time(value):
    text(value, 'decision confirmation time')
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value),
            'Decision confirmation time requires an ISO 8601 timestamp with timezone')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'Decision confirmation time requires a timezone')
        require(parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc),
                'Decision confirmation time cannot be in the future')
    except ValueError as error:
        raise TaskError('Invalid decision confirmation time') from error


def compile_profile(source=None, *, original_pdf=None, evidence_files=None):
    """Return a detached preparation view and transient original artifact bytes.

    Evidence records identify supplied bytes, not authenticated people or
    laboratory approvals. Unknown values are accepted as unresolved bindings.
    """
    path = None
    if isinstance(source, dict):
        profile = copy.deepcopy(source)
        try:
            profile_bytes = encoded(profile).encode()
        except (TypeError, ValueError) as error:
            raise TaskError('Manual profile must contain finite JSON values') from error
    else:
        path = Path(source) if source is not None else SOURCE
        profile_bytes = _read(path, 'manual profile')
        profile = _json(profile_bytes, 'manual profile')
    keys(profile, ('format', 'id', 'mode', 'synthetic', 'sources', 'context', 'roles', 'stage_bindings',
                   'parameters', 'local_decisions', 'qc_plan', 'handover_plan'), 'manual profile')
    require(profile['format'] == FORMAT and profile['mode'] == 'manual_observation'
            and profile['synthetic'] is False, 'Explicit manual observation profile required')
    text(profile['id'], 'manual profile identity')
    keys(profile['sources'], ('sop', 'manufacturer'), 'manual source bindings')
    sop, manufacturer = profile['sources']['sop'], profile['sources']['manufacturer']
    keys(sop, ('source', 'source_sha256', 'id', 'revision'), 'local SOP source')
    require(sop['source'] == 'docs/cutrun-manual-sop-draft.md'
            and sop['id'] == 'SOP-CR-SKM29-H3K4me3' and sop['revision'] == '0.1',
            'Manual capture version 1 binds the reviewed SOP draft 0.1')
    _checksum(sop['source_sha256'], 'SOP')
    sop_bytes = _read(_repo_file(sop['source']), 'SOP source')
    require(digest(sop_bytes) == sop['source_sha256'], 'SOP source changed')
    keys(manufacturer, ('url', 'source_sha256', 'datasheet_revision', 'protocol_revision'),
         'manufacturer source')
    require(manufacturer['url'] == 'https://media.cellsignal.com/pdf/86652.pdf'
            and manufacturer['datasheet_revision'] == '9'
            and manufacturer['protocol_revision'] == '09/2026',
            'Explicit current manufacturer draft reference required; historical equivalence is not established')
    _checksum(manufacturer['source_sha256'], 'manufacturer original')
    try:
        sop_text = sop_bytes.decode('utf-8')
    except UnicodeError as error:
        raise TaskError('The bound SOP must be readable UTF-8 text') from error
    original_hash = re.search(r'Ihre \*\*SHA-256\*\* lautet:\s*\x60{3}text\s*([0-9a-f]{64})\s*\x60{3}', sop_text)
    require(original_hash is not None and manufacturer['source_sha256'] == original_hash.group(1),
            'Manufacturer original checksum must match the original declared in the bound SOP')
    artifacts = {digest(sop_bytes): sop_bytes, digest(profile_bytes): profile_bytes}
    evidence_records = {}
    require(evidence_files is None or isinstance(evidence_files, dict), 'Evidence files must map explicit IDs to files')
    for identity, file in (evidence_files or {}).items():
        text(identity, 'evidence identity')
        content = _read(file, 'explicit evidence file')
        checksum = digest(content)
        artifacts[checksum] = content
        evidence_records[identity] = {'sha256': checksum, 'size_bytes': len(content)}
    original_verified = original_pdf is not None
    if original_verified:
        original = _read(original_pdf, 'explicit manufacturer original')
        require(digest(original) == manufacturer['source_sha256'], 'Manufacturer original checksum mismatch')
        require(original.startswith(b'%PDF-'), 'Manufacturer original must be a PDF')
        artifacts[digest(original)] = original

    def evidence(identity, label):
        text(identity, label + ' evidence reference')
        require(identity in evidence_records, 'Unregistered evidence reference for ' + label)

    keys(profile['context'], ('cell_line', 'target', 'culture_id', 'material_state', 'condition_id'), 'manual context')
    require(profile['context']['cell_line'] == 'SK-Mel-29' and profile['context']['target'] == 'H3K4me3',
            'The selected manual reference is SK-Mel-29/H3K4me3')
    for name in ('culture_id', 'material_state', 'condition_id'):
        optional_text(profile['context'][name], name)
    require(profile['context']['material_state'] in (None, 'fresh_unfixed'),
            'SOP draft 0.1 binds fresh, unfixed material; a different state requires a reviewed SOP revision')
    keys(profile['roles'], ROLE_TYPES, 'manual role bindings')
    material_ids, vessel_ids = set(), set()
    for name, role in ROLE_TYPES.items():
        binding = profile['roles'][name]
        keys(binding, ('role', 'material_id', 'vessel_id'), name + ' role')
        require(binding['role'] == role, 'Manual control roles cannot be substituted')
        for field, seen in [('material_id', material_ids), ('vessel_id', vessel_ids)]:
            value = binding[field]
            optional_text(value, field)
            if value is not None:
                require(value not in seen and not value.startswith('SYN.'), 'Real role identity is duplicate or synthetic')
                seen.add(value)
        require(name != 'ntc' or binding['material_id'] is None, 'PCR NTC cannot debit a sample material')
    keys(profile['local_decisions'], DECISIONS, 'local decisions')
    confirmed = set()
    for identity, decision in profile['local_decisions'].items():
        keys(decision, ('status', 'value', 'actor_id', 'confirmed_at', 'evidence_ref'), identity)
        require(isinstance(decision['status'], str) and decision['status'] in {'open', 'confirmed'},
                'Unsupported local decision state')
        if decision['status'] == 'open':
            require(all(decision[name] is None for name in ('value', 'actor_id', 'confirmed_at', 'evidence_ref')),
                    'An open decision cannot carry a claimed approval')
        else:
            require(decision['value'] is not None and decision['value'] != '' and decision['value'] != {}
                    and decision['value'] != [],
                    'Confirmed decision requires explicit content')
            text(decision['actor_id'], 'confirming actor')
            _confirmed_time(decision['confirmed_at'])
            evidence(decision['evidence_ref'], identity)
            confirmed.add(identity)
    keys(profile['parameters'], UNITS, 'manual laboratory parameters')
    parameter_ready = set()
    for name, unit in UNITS.items():
        fact = profile['parameters'][name]
        keys(fact, ('value', 'unit', 'basis', 'source_ref', 'evidence_ref'), name)
        require(fact['unit'] == unit and isinstance(fact['basis'], str) and fact['basis'] in
                {'unknown', 'manufacturer_reported', 'local_proposal', 'locally_confirmed'},
                'Invalid fact basis or unit: ' + name)
        require(fact['source_ref'] is None or isinstance(fact['source_ref'], str)
                and fact['source_ref'] in {'sop', 'manufacturer'}, 'Unknown fact source: ' + name)
        if fact['basis'] == 'unknown':
            require(fact['value'] is None and fact['source_ref'] is None and fact['evidence_ref'] is None,
                    'Unknown parameter must retain null value and provenance')
            continue
        number = fact['value']
        require(type(number) in (int, float) and math.isfinite(number), 'Finite explicit parameter required: ' + name)
        require(number >= 0 if name == 'activation_temperature_deg_c' else number > 0,
                'Invalid parameter range: ' + name)
        if name == 'input_cells':
            require(number == int(number), 'Input cell count must be an integer')
        if fact['evidence_ref'] is not None:
            evidence(fact['evidence_ref'], name)
        if fact['basis'] == 'locally_confirmed':
            evidence(fact['evidence_ref'], name)
            parameter_ready.add(name)
        elif fact['basis'] == 'manufacturer_reported':
            require(fact['source_ref'] == 'manufacturer', 'Manufacturer fact requires manufacturer provenance')
        else:
            require(fact['source_ref'] is not None, 'Local proposal requires its source reference')

    keys(profile['stage_bindings'], STAGES, 'SOP stage bindings')
    for stage in STAGES:
        binding = profile['stage_bindings'][stage]
        keys(binding, ('sop_step', 'source_ref', 'section', 'required_decisions', 'required_parameters'), stage)
        require(binding == {'sop_step': stage, 'source_ref': 'sop', 'section': SECTIONS[stage],
                            'required_decisions': GLOBAL_DECISIONS + LOCAL_DECISIONS[stage],
                            'required_parameters': STAGE_PARAMETERS.get(stage, [])},
                'Mandatory SOP stage requirements cannot be removed or reassigned: ' + stage)
    qc = profile['qc_plan']
    keys(qc, ('evaluation_mode', 'scope', 'roles'), 'manual QC plan')
    require(qc['evaluation_mode'] == 'manual_review' and qc['scope'] == 'raw_dna',
            'QC must retain explicit raw-DNA/manual-review scope')
    keys(qc['roles'], ROLE_TYPES, 'QC roles')
    for name, plan in qc['roles'].items():
        keys(plan, ('methods', 'assay_id', 'criteria', 'limits', 'evidence_ref'), name + ' QC')
        require(plan['methods'] == (['qpcr'] if name == 'ntc' else ['fluorometry', 'qpcr']),
                'Role-specific manual QC methods required')
        optional_text(plan['assay_id'], 'QC assay')
        require(plan['criteria'] is None or isinstance(plan['criteria'], dict), 'QC criteria must be an explicit record')
        require(plan['limits'] is None or isinstance(plan['limits'], dict), 'QC limits must be an explicit record')
        if plan['evidence_ref'] is not None:
            evidence(plan['evidence_ref'], name + ' QC')
    handover = profile['handover_plan']
    keys(handover, ('recipient_id', 'storage_location', 'conditions', 'evidence_ref'), 'product handover plan')
    optional_text(handover['recipient_id'], 'handover recipient')
    optional_text(handover['conditions'], 'storage conditions')
    require(handover['storage_location'] is None or isinstance(handover['storage_location'], dict),
            'Storage location must be an explicit record')
    if handover['evidence_ref'] is not None:
        evidence(handover['evidence_ref'], 'handover')

    requirements = []

    def opened(identity, reason, stages):
        requirements.append({'id': identity, 'reason': reason, 'stage_ids': list(stages)})

    if not original_verified:
        opened('manufacturer_original', 'The explicitly supplied, checksum-matching manufacturer PDF is missing', STAGES)
    for identity in DECISIONS:
        if identity not in confirmed:
            opened(identity, 'Local decision remains open; no approval is inferred',
                   [stage for stage in STAGES if identity in profile['stage_bindings'][stage]['required_decisions']])
    for name in UNITS:
        if name not in parameter_ready:
            opened('parameter.' + name, 'Explicit locally confirmed parameter binding required',
                   [stage for stage in STAGES if name in profile['stage_bindings'][stage]['required_parameters']])
    for name in ('culture_id', 'material_state', 'condition_id'):
        if profile['context'][name] is None:
            opened('context.' + name, 'Actual local culture/condition binding remains unknown', STAGES[1:])
    for name, binding in profile['roles'].items():
        fields = ('vessel_id',) if name == 'ntc' else ('material_id', 'vessel_id')
        if any(binding[field] is None for field in fields):
            opened('role.' + name, 'Actual material/vessel identity remains unbound', STAGES[1:] if name != 'ntc' else STAGES)
    for name, plan in qc['roles'].items():
        if not all(plan[field] for field in ('assay_id', 'criteria', 'limits', 'evidence_ref')):
            opened('qc.' + name, 'Prospective role-specific raw-DNA QC plan remains incomplete', STAGES)
    if not all(handover.values()):
        opened('handover', 'Prospective product acceptance/storage plan remains incomplete', STAGES)
    blocked = {stage for requirement in requirements for stage in requirement['stage_ids']}
    pins = {sop['source']: digest(sop_bytes)}
    if path is not None and path.resolve().is_relative_to(ROOT.resolve()):
        pins[str(path.resolve().relative_to(ROOT.resolve()))] = digest(profile_bytes)
    for name in RUNTIME:
        pins[name] = digest(_read(_repo_file(name), 'manual runtime source'))
    # Re-read repository dependencies after compilation to detect source changes.
    for name, checksum in pins.items():
        require(digest(_read(_repo_file(name), 'source verification')) == checksum,
                'Manual source changed during compilation: ' + name)
    return {'manual_profile': copy.deepcopy(profile), 'source_files_sha256': pins,
            'runtime_source_files': list(RUNTIME), 'open_requirements': requirements,
            'stage_readiness': {stage: stage not in blocked for stage in STAGES},
            'can_archive': True, 'can_claim_reference_success': False,
            'preparation_complete': not requirements, 'original_pdf_verified': original_verified,
            'evidence_records': copy.deepcopy(evidence_records), 'evidence_artifacts': artifacts,
            'effective_profile_sha256': digest(encoded(profile).encode())}


def load(source=None, *, materials, vessels, clock_source_kind, original_pdf=None, evidence_files=None,
         protective_stop_bindings=None):
    """Freeze the manual capture definition and transient initial artifact bytes."""
    require(isinstance(clock_source_kind, str) and clock_source_kind in {'system_clock', 'test_clock'},
            'Explicit system_clock or test_clock required')
    compiled = compile_profile(source, original_pdf=original_pdf, evidence_files=evidence_files)
    initial_materials, initial_vessels = copy.deepcopy(materials), copy.deepcopy(vessels)
    inventory = material_ledger.initial_inventory(initial_materials, initial_vessels)
    for seed in [*initial_materials, *initial_vessels]:
        require(not seed['id'].startswith('SYN.'), 'Synthetic fixture identities cannot become real manual material bindings')
    protective = copy.deepcopy(protective_stop_bindings if protective_stop_bindings is not None else {})
    require(isinstance(protective, dict), 'Protective stop bindings must be explicit vessel/material pairs')
    require(all(isinstance(vessel, str) and isinstance(material, str) for vessel, material in protective.items()),
            'Protective stop bindings require vessel/material identities')
    require(len(set(protective.values())) == len(protective), 'Each reaction needs its own issued stop aliquot')
    for vessel, material in protective.items():
        require(vessel in inventory['vessels'] and material in inventory['materials']
                and inventory['materials'][material]['kind'] == 'reagent'
                and inventory['materials'][material]['initial_quantity']['unit'] == 'uL',
                'Protective stop binding requires a declared vessel and an issued liquid reagent')
    for name, binding in compiled['manual_profile']['roles'].items():
        material, vessel = binding['material_id'], binding['vessel_id']
        if material is not None:
            require(material in inventory['materials'] and inventory['materials'][material]['vessel_id'] == vessel
                    and inventory['materials'][material]['kind'] in {'sample', 'control'},
                    'Manual role must bind its actual declared input material and vessel')
        if vessel is not None:
            require(vessel in inventory['vessels'], 'Manual role vessel is not in the explicit inventory')
            if name == 'ntc':
                require(not any(item['vessel_id'] == vessel for item in inventory['materials'].values()),
                        'PCR NTC vessel must contain no sample material')
    allocations = [{'material_id': item['id'], 'vessel_id': item['vessel_id'],
                    'declaration_sha256': digest(encoded(item).encode())}
                   for item in initial_materials if item['kind'] == 'reagent']
    definition = {'format': 'solidcraftbot.material-workflow-definition/3', 'domain': 'cutrun_manual',
        'profile': {'id': compiled['manual_profile']['id'], 'type': 'cutrun_manual_capture/1',
                    'mode': 'manual_observation',
                    'parameters': {'task_deadline_s': compiled['manual_profile']['parameters']['task_deadline_s']['value']}},
        'clock_mode': 'real_observations/1', 'clock_source_kind': clock_source_kind,
        'preparation_plan': {'execution_ready': False, 'mode': 'manual_contract'},
        'declared_inputs': [], 'products': [], 'initial_materials': initial_materials,
        'initial_vessels': initial_vessels, 'material_allocations': allocations,
        'protective_stop_bindings': protective}
    for name in ('manual_profile', 'stage_readiness', 'open_requirements', 'source_files_sha256',
                 'runtime_source_files', 'can_archive', 'can_claim_reference_success',
                 'preparation_complete', 'original_pdf_verified', 'evidence_records'):
        definition[name] = copy.deepcopy(compiled[name])
    definition['effective_profile_sha256'] = digest(encoded({
        'manual_profile_sha256': compiled['effective_profile_sha256'], 'materials': initial_materials,
        'vessels': initial_vessels, 'clock_source_kind': clock_source_kind,
        'protective_stop_bindings': protective}).encode())
    definition['_initial_artifacts'] = dict(compiled['evidence_artifacts'])
    return definition
