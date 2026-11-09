"""Pinned sources and derived inputs for one synthetic three-instrument workflow.

The manifest is the only original sample/vessel/initial-volume declaration.
Legacy stage profiles remain independent fixtures; their sample lists are not
imported into the integrated batch. This module generates no CAD geometry.
"""
import copy
import json
from pathlib import Path

import assembly_model as assembly
import cf01_rack_batch as cf01
import centrifuge_model as centrifuge
import nanodrop_manual as nanodrop
import qubit_manual as qubit
import rack_slots
import synthetic_workspace as spatial
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, keys, positive, text

SOURCE = ROOT / 'model/synthetic-lab-workflow.shared.json'
SCHEMA = ROOT / 'model/synthetic-lab-workflow.schema.json'
FORMAT = 'solidcraftbot.synthetic-lab-workflow/1'
MANIFEST_FORMAT = 'solidcraftbot.synthetic-lab-manifest/1'
STAGES = ['cf01', 'nanodrop', 'qubit']


def validate_manifest(manifest, rack_instance, places):
    """Validate canonical local places and a full batch for the current CF01."""
    keys(manifest, 'format id rack_instance samples', 'integrated manifest')
    if manifest['format'] != MANIFEST_FORMAT:
        raise TaskError('Unsupported integrated manifest format')
    text(manifest['id'], 'manifest id')
    if manifest['rack_instance'] != rack_instance:
        raise TaskError('Manifest must reference the composed rack instance')
    samples = manifest['samples']
    if not isinstance(samples, list) or len(samples) != 12 or len(places) != 12:
        raise TaskError('Current CF01 stage requires twelve original vessels')
    for sample in samples:
        keys(sample, 'sample_id vessel_id rack_place_id initial_volume_ul', 'manifest sample')
        for field in ['sample_id', 'vessel_id', 'rack_place_id']:
            text(sample[field], field)
        if sample['initial_volume_ul'] is not None:
            positive(sample['initial_volume_ul'], 'initial volume', zero=True)
    for field in ['sample_id', 'vessel_id', 'rack_place_id']:
        if len({sample[field] for sample in samples}) != len(samples):
            raise TaskError('Duplicate manifest ' + field)
    if {sample['rack_place_id'] for sample in samples} != {place['place_id'] for place in places}:
        raise TaskError('Manifest must cover every local rack place exactly once')
    by_place = {place['place_id']: place['slot'] for place in places}
    return {**copy.deepcopy(manifest), 'samples': sorted(
        copy.deepcopy(samples), key=lambda sample: by_place[sample['rack_place_id']])}


def validate_mass_confirmation(record):
    """Check the new runtime record; current revision/clock belong to the root."""
    keys(record, 'confirmation_id vessel_id mass_g content_revision actor_id time_s evidence',
         'synthetic mass confirmation')
    for field in ['confirmation_id', 'vessel_id', 'actor_id']:
        text(record[field], field)
    positive(record['mass_g'], 'synthetic total vessel mass in g')
    positive(record['time_s'], 'mass confirmation process time', zero=True)
    if type(record['content_revision']) is not int or record['content_revision'] < 0:
        raise TaskError('Nonnegative integer content revision required')
    if record['evidence'] != 'synthetic_input':
        raise TaskError('Only explicit synthetic mass evidence is supported')
    return copy.deepcopy(record)


def build_cf01_profile(definition, confirmations, content_revisions, now_s=None):
    """Derive CF01 input only from complete, current runtime mass confirmations.

    The legacy profile remains a fictitious simulation input. Confirmation
    provenance is kept by the integrated root, never represented as scale I/O.
    """
    samples = definition['manifest']['samples']
    expected = {sample['vessel_id'] for sample in samples}
    if (not isinstance(confirmations, dict) or set(confirmations) != expected
            or not isinstance(content_revisions, dict) or set(content_revisions) != expected):
        raise TaskError('Current mass confirmations for every original vessel required')
    if now_s is not None:
        positive(now_s, 'current process time', zero=True)
    records = {}
    for vessel_id, value in confirmations.items():
        record = validate_mass_confirmation(value)
        if record['vessel_id'] != vessel_id:
            raise TaskError('Mass confirmation vessel identity mismatch')
        if (type(content_revisions[vessel_id]) is not int
                or content_revisions[vessel_id] != record['content_revision']):
            raise TaskError('Mass confirmation content revision is stale')
        if now_s is not None and record['time_s'] > now_s:
            raise TaskError('Mass confirmation is in the future')
        records[vessel_id] = record
    if len({record['confirmation_id'] for record in records.values()}) != len(records):
        raise TaskError('Duplicate mass confirmation id')
    sample_to_vessel = {sample['sample_id']: sample['vessel_id'] for sample in samples}
    profile = copy.deepcopy(definition['stages']['cf01']['profile'])
    for sample in profile['samples']:
        sample['mass_g'] = records[sample_to_vessel[sample['id']]]['mass_g']
    try:
        cf01.validate(profile)
    except (ValueError, KeyError, TypeError) as error:
        raise TaskError('Invalid derived CF01 input: ' + str(error)) from error
    return profile


def _place_roles(values, profile, capacity):
    if not isinstance(values, list):
        raise TaskError('Explicit integrated Qubit place roles required')
    known = {(place['holder_id'], place['place_id']) for place in profile['logical_places']}
    observed, holders, chambers = set(), [], []
    for place in values:
        keys(place, 'holder_id place_id role', 'Qubit place role')
        pair = (text(place['holder_id'], 'holder id'), text(place['place_id'], 'place id'))
        if pair not in known or pair in observed:
            raise TaskError('Unknown or duplicate Qubit place role')
        observed.add(pair)
        if place['role'] == 'holder_slot':
            if place['holder_id'] == profile['instrument']['id']:
                raise TaskError('Measurement chamber cannot be a preparation holder')
            holders.append(place)
        elif place['role'] == 'measurement_chamber':
            if pair != (profile['instrument']['id'], 'Chamber'):
                raise TaskError('Measurement chamber must reference the Qubit instrument')
            chambers.append(place)
        else:
            raise TaskError('Unsupported integrated Qubit place role')
    if observed != known or len(holders) != capacity or len(chambers) != 1:
        raise TaskError('Every Qubit place needs its declared role and twelve holder slots')
    return copy.deepcopy(values)


def load(source=SOURCE, runtime_sources=()):
    """Compile immutable stage inputs; neither initialise nor reset run balances.

    ``runtime_sources`` lets the coordinator add its own entry-point files to
    the pinned manifest. ``stages['cf01']['profile']`` deliberately contains
    null masses and is not executable until ``build_cf01_profile`` succeeds.
    """
    try:
        return _load(source, runtime_sources)
    except TaskError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TaskError('Invalid integrated workflow source: ' + str(error)) from error


def _load(source, runtime_sources):
    path = None if isinstance(source, dict) else Path(source)
    if path is not None and not path.resolve().is_relative_to(ROOT):
        raise TaskError('Integrated workflow profile must remain in the project')
    profile = copy.deepcopy(source) if path is None else json.loads(path.read_text(encoding='utf-8'))
    keys(profile, 'format id mode units clock_mode task_deadline_s manifest workspace bindings '
         'stage_order stage_profiles qubit_place_roles limitations', 'integrated workflow')
    if profile['format'] != FORMAT or profile['mode'] != 'synthetic_only':
        raise TaskError('Only the integrated synthetic workflow is supported')
    text(profile['id'], 'workflow id')
    if profile['units'] != {'volume': 'uL', 'mass': 'g', 'time': 's'}:
        raise TaskError('Explicit uL/g/s workflow units required')
    if profile['clock_mode'] != 'synthetic_events/1':
        raise TaskError('Integrated process clock must be synthetic_events/1')
    positive(profile['task_deadline_s'], 'root task deadline')
    if profile['stage_order'] != STAGES:
        raise TaskError('First integrated workflow order is CF01, NanoDrop, Qubit')
    if not isinstance(profile['limitations'], list) or not profile['limitations']:
        raise TaskError('Explicit synthetic limitations required')
    for limitation in profile['limitations']:
        text(limitation, 'limitation')
    sources = {}

    def remember(file):
        file = Path(file).resolve()
        if not file.is_relative_to(ROOT):
            raise TaskError('Workflow dependency must remain in the project')
        sources[str(file.relative_to(ROOT))] = digest(file.read_bytes())

    def read(ref):
        keys(ref, 'source source_sha256', 'pinned workflow reference')
        file = assembly.validate_reference(ref)
        remember(file)
        return json.loads(file.read_text(encoding='utf-8'))

    read(profile['workspace'])
    workspace = spatial.load(assembly.validate_reference(profile['workspace']))
    for file in spatial.source_dependencies(workspace):
        remember(file)
    bindings = profile['bindings']
    keys(bindings, 'rack_instance arm_instance station_instance work_area', 'workflow bindings')
    for field, asset in [('rack_instance', 'rack'), ('arm_instance', 'arm'), ('station_instance', 'centrifuge')]:
        value = text(bindings[field], field)
        if value not in workspace['devices'] or workspace['devices'][value]['asset'] != asset:
            raise TaskError('Workflow binding must reference the composed ' + asset + ' instance')
    # The existing CF01 adapter addresses these stable scene IDs explicitly.
    if (bindings['rack_instance'], bindings['arm_instance'], bindings['station_instance']) != ('Rack', 'Arm', 'CF01'):
        raise TaskError('Current CF01 requires the existing Rack, Arm and CF01 instances')
    keys(bindings['work_area'], 'id frame', 'shared work area')
    area = bindings['work_area']
    text(area['id'], 'work area id')
    if area['frame'] not in workspace['frames']:
        raise TaskError('Shared work area requires a composed bench frame')
    rack_ref = workspace['devices'][bindings['rack_instance']]['source']
    rack = read(rack_ref)
    places = rack_slots.places(rack)
    manifest = validate_manifest(read(profile['manifest']), bindings['rack_instance'], places)
    slot_by_place = {place['place_id']: place['slot'] for place in places}
    legacy_samples = [{'id': sample['sample_id'], 'vessel_id': sample['vessel_id'],
                       'rack_slot': slot_by_place[sample['rack_place_id']],
                       'initial_volume_ul': sample['initial_volume_ul']} for sample in manifest['samples']]
    keys(profile['stage_profiles'], 'cf01 nanodrop qubit', 'stage profile references')
    raw = {stage: read(ref) for stage, ref in profile['stage_profiles'].items()}
    if raw['cf01']['workspace'] != profile['workspace']:
        raise TaskError('CF01 and integrated workflow must use the same spatial composition')
    cf01.validate(raw['cf01'])
    read(raw['cf01']['station_contract'])
    stages = {}
    for name, loader in [('nanodrop', nanodrop.load_profile), ('qubit', qubit.load_profile)]:
        stage = copy.deepcopy(raw[name])
        if stage['rack']['definition'] != rack_ref:
            raise TaskError('Stage rack definition differs from the composed rack')
        if stage['workspace']['id'] != area['id'] or stage['workspace']['frame'] != area['frame']:
            raise TaskError('Stage must bind the same logical work area and bench frame')
        for field in ['environment', 'furniture', 'furnishings']:
            if stage['workspace'][field] != workspace['spec']['sources'][field]:
                raise TaskError('Stage must reference the same shared ' + field)
        legacy = {'rack_instance': stage['rack']['id'], 'work_area': stage['workspace']['id']}
        stage['samples'] = copy.deepcopy(legacy_samples)
        stage['rack']['id'] = bindings['rack_instance']
        stage['workspace']['id'] = area['id']
        stage['id'] = profile['id'] + '.' + name
        definition = loader(stage)
        definition['legacy_bindings'] = legacy
        stages[name] = definition
        sources.update(definition['source_files_sha256'])
    roles = _place_roles(profile['qubit_place_roles'], stages['qubit']['profile'], len(places))
    cf_profile = copy.deepcopy(raw['cf01'])
    old_slots = {sample['rack_slot']: sample['rotor_slot'] for sample in cf_profile['samples']}
    cf_profile['id'] = profile['id'] + '.cf01'
    cf_profile['samples'] = [{'id': sample['id'], 'rack_slot': sample['rack_slot'],
                              'rotor_slot': old_slots[sample['rack_slot']], 'mass_g': None}
                             for sample in legacy_samples]
    stages['cf01'] = {'profile': cf_profile, 'mass_source': 'integrated_synthetic_confirmation',
                      'required_capacity': len(places), 'protocol': read(raw['cf01']['station_contract'])}
    incubation = stages['qubit']['profile']['parameters']['incubation_min_s']
    # Only a declared lower bound: abstract handling may take additional time.
    serial_incubation = incubation * len(manifest['samples'])
    qubit_parameters = stages['qubit']['profile']['parameters']
    if (qubit_parameters['task_deadline_s'] <= incubation + serial_incubation
            or qubit_parameters['calibration_validity_s'] <= serial_incubation):
        raise TaskError('Qubit timing must cover twelve serial preparations')
    braking = centrifuge.load()['mechanisms']['braking']['simulation_stop_s']
    minimum_time = cf_profile['spin']['duration_s'] + braking + incubation + serial_incubation
    if profile['task_deadline_s'] <= minimum_time:
        raise TaskError('Root deadline cannot cover the declared workflow minimum')
    instruments = [bindings['rack_instance'], bindings['arm_instance'], bindings['station_instance'],
                   stages['nanodrop']['profile']['instrument']['id'], stages['qubit']['profile']['instrument']['id']]
    if len(set(instruments)) != len(instruments):
        raise TaskError('Composed instrument instance ids must be distinct')
    runtime = list(dict.fromkeys([
        *stages['nanodrop']['runtime_source_files'], *stages['qubit']['runtime_source_files'],
        'scripts/lab_workflow_sources.py', 'model/synthetic-lab-workflow.schema.json',
        'scripts/cf01_rack_batch.py', 'scripts/centrifuge_control.py',
        'scripts/centrifuge_protocol.py', 'scripts/centrifuge_model.py',
        'scripts/centrifuge_mechanisms.py', 'scripts/robot_spec.py',
        'scripts/synthetic_workspace.py', 'scripts/assembly_model.py',
        'scripts/furniture_model.py', *runtime_sources]))
    for file in runtime:
        remember(assembly.project_path(file))
    if path is not None and path.resolve().is_relative_to(ROOT):
        remember(path)
    return {'format': FORMAT, 'profile': profile, 'manifest': manifest,
            'stages': {stage: stages[stage] for stage in STAGES},
            'workspace': workspace, 'rack_places': places, 'rack_instance': bindings['rack_instance'],
            'work_area': copy.deepcopy(area), 'qubit_places': roles,
            'source_files_sha256': sources, 'runtime_source_files': runtime,
            'effective_profile_sha256': digest(encoded(profile).encode())}
