"""Bind an explicit synthetic CUT&RUN execution fixture to its E1/E2 sources.

No preparation phase is run here. Issued working mixtures and observed fixture
volumes are declarations; no recipe, physical stock or DNA yield is inferred.
"""

import copy
from pathlib import Path

import cutrun_preparation as preparation
import material_workflow_sources as material_sources
from manual_tasks import TaskError, digest, encoded
from manual_workflow import keys, text


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-synthetic-run.profile.json'
SCHEMA = ROOT / 'model/cutrun-synthetic-run.schema.json'
FORMAT = 'solidcraftbot.cutrun-synthetic-run/1'
SETTINGS = {'task_deadline_s': 's', 'phase_tolerance_s': 's', 'temperature_tolerance_deg_c': 'degC',
            'stop_window_s': 's', 'activation_service_s': 's'}
VOLUMES = ('reaction', 'supernatant', 'bead_remainder', 'column', 'eluate', 'residue')
FRACTION_VESSELS = ('supernatant', 'bead_remainder', 'column_residue')
RUNTIME = ('scripts/cutrun_workflow.py', 'scripts/run_cutrun_workflow.py',
           'scripts/cutrun_workflow_sources.py', 'model/cutrun-synthetic-run.schema.json')


def require(condition, message):
    if not condition:
        raise TaskError(message)


def _reference(reference, pins):
    keys(reference, 'source source_sha256', 'pinned CUT&RUN preparation')
    try:
        path = preparation.assembly.validate_reference(reference, root=ROOT)
        content = path.read_bytes()
    except (ValueError, OSError, TypeError) as error:
        raise TaskError('Invalid pinned preparation reference: ' + str(error)) from error
    require(digest(content) == reference['source_sha256'], 'Preparation source changed while reading')
    pins[str(path.relative_to(ROOT))] = digest(content)
    return preparation.parse_json(content)


def load(source=None):
    """Return an immutable-definition input for the common /2 material root."""
    source = SOURCE if source is None else source
    path = None if isinstance(source, dict) else Path(source)
    content = None if path is None else path.read_bytes()
    profile = copy.deepcopy(source) if path is None else preparation.parse_json(content)
    keys(profile, 'format id mode synthetic preparation settings stop_actors issued_reagents '
         'fraction_vessels bookkeeping_volumes_ul', 'synthetic CUT&RUN execution profile')
    require(profile['format'] == FORMAT and profile['mode'] == 'synthetic_only' and profile['synthetic'] is True,
            'Only an explicitly synthetic CUT&RUN execution fixture is supported')
    text(profile['id'], 'execution profile id')
    pins = {}
    source_profile = _reference(profile['preparation'], pins)
    require(isinstance(source_profile, dict) and source_profile.get('format') == 'solidcraftbot.cutrun-preparation/2',
            'CUT&RUN execution requires preparation version 2 with explicit activation/stop working-mixture roles')
    plan = preparation.compile_plan(source_profile)
    require(plan['planning_complete'], 'Complete synthetic preparation inputs are required for the execution fixture')
    facts = preparation.Facts(plan['manufacturer_references'])

    def number(fact, unit, label):
        value = facts.read(fact, unit, label, synthetic=True)
        require(value is not None and value > 0, 'Explicit positive synthetic value required at ' + label)
        return value

    keys(profile['settings'], ' '.join(SETTINGS), 'synthetic execution settings')
    settings = {name: number(profile['settings'][name], unit, 'settings.' + name) for name, unit in SETTINGS.items()}
    actors = preparation.strings(profile['stop_actors'], 'explicit synthetic stop actors')
    keys(profile['bookkeeping_volumes_ul'], ' '.join(VOLUMES), 'synthetic material boundary volumes')
    volumes = {name: number(profile['bookkeeping_volumes_ul'][name], 'uL', 'bookkeeping_volumes_ul.' + name)
               for name in VOLUMES}
    stop_service = plan['stop_plan']['service_time_per_branch_s']['value']
    require(stop_service is not None and settings['stop_window_s'] >= stop_service
            and settings['activation_service_s'] + stop_service <= settings['stop_window_s'],
            'Synthetic stop window cannot cover activation and the own-branch stop service')
    minimum_duration = sum(step['parameters'].get('duration_s', {}).get('value', 0)
                           for branch in plan['branches'] for step in branch['steps'])
    active_ids = {branch['id'] for branch in plan['branches'] if branch['workflow'] == 'cutrun'}
    minimum_duration += len(active_ids) * settings['activation_service_s']
    require(settings['task_deadline_s'] >= minimum_duration,
            'Synthetic task budget is shorter than the declared serial phase durations')
    qc_volume = sum(item['value'] for item in plan['qc']['aliquot_volumes_ul'].values())
    require(volumes['eluate'] >= qc_volume, 'Synthetic eluate receipt cannot supply the selected product QC aliquots')
    require(isinstance(profile['issued_reagents'], dict) and set(profile['issued_reagents']) == active_ids,
            'Separate activation and stop aliquots are required for exactly the active branches')
    all_ids = {branch['id'] for branch in plan['branches']}
    require(isinstance(profile['fraction_vessels'], dict) and set(profile['fraction_vessels']) == all_ids,
            'Explicit extra fraction vessels required for every branch')

    materials, bindings, protective = [], {}, {}
    vessel_ids = {identity for branch in plan['branches'] for identity in branch['vessels'].values()}
    product_locations = {}
    for branch in plan['branches']:
        identity = branch['id']
        count = number(branch['input_amount'], 'cells', 'preparation.branches.' + identity + '.input_amount')
        materials.append({'id': branch['input_material_id'],
            'kind': 'sample' if branch['role'] == 'reference' else 'control',
            'vessel_id': branch['vessels']['input'], 'quantity': {'value': count, 'unit': 'cells'}, 'origin_id': identity})
        product_locations[branch['vessels']['product']] = {'kind': 'rack', **copy.deepcopy(branch['output_location'])}
        extra = profile['fraction_vessels'][identity]
        keys(extra, ' '.join(FRACTION_VESSELS), 'extra fraction vessel bindings')
        for name, vessel in extra.items():
            text(vessel, 'fraction vessel identity')
            require(vessel not in vessel_ids, 'A fraction vessel aliases another physical vessel')
            vessel_ids.add(vessel)
        binding = {'activation_material_id': None, 'stop_material_id': None,
                   'fraction_vessels': copy.deepcopy(extra)}
        if identity in active_ids:
            mixtures = profile['issued_reagents'][identity]
            keys(mixtures, 'activation stop', 'branch-issued prepared working mixtures')
            for name, role in [('activation', 'activation_reagent'), ('stop', 'stop_buffer')]:
                mixture = mixtures[name]
                keys(mixture, 'material_id vessel_id quantity', 'issued working mixture')
                text(mixture['material_id'], 'issued mixture material id')
                text(mixture['vessel_id'], 'issued mixture vessel id')
                require(mixture['vessel_id'] not in vessel_ids, 'Issued mixture vessels cannot alias process vessels')
                vessel_ids.add(mixture['vessel_id'])
                available = number(mixture['quantity'], 'uL', 'issued_reagents.' + identity + '.' + name + '.quantity')
                step = next(item for item in branch['steps'] if item['reagent_role'] == role)
                required = step['parameters']['volume_ul']['value']
                require(required is not None and available >= required, 'Issued working mixture cannot supply its proposed dose')
                materials.append({'id': mixture['material_id'], 'kind': 'reagent', 'vessel_id': mixture['vessel_id'],
                                  'quantity': {'value': available, 'unit': 'uL'}, 'origin_id': profile['id']})
                binding[name + '_material_id'] = mixture['material_id']
            protective[branch['vessels']['reaction']] = binding['stop_material_id']
        bindings[identity] = binding
    ntc_vessel = plan['qc']['ntc']['vessel_id']
    require(ntc_vessel not in vessel_ids, 'PCR control vessel aliases a process vessel')
    vessel_ids.add(ntc_vessel)
    vessels = [{'id': identity, 'location': copy.deepcopy(product_locations.get(identity,
                    {'kind': 'rack', 'rack_id': 'SYN.CutRun.ExecutionRack', 'place_id': 'P%03d' % index}))}
               for index, identity in enumerate(sorted(vessel_ids), 1)]
    definition = material_sources.load('cutrun', source_profile, materials=materials, vessels=vessels,
                                       task_deadline_s=settings['task_deadline_s'])
    definition.update(format='solidcraftbot.material-workflow-definition/2', clock_mode='synthetic_intervals/1')
    definition['profile']['type'] = 'cutrun_synthetic/1'
    definition['execution_profile'] = copy.deepcopy(profile)
    definition['execution'] = {'profile_type': 'solidcraftbot.cutrun-synthetic-execution/1', **settings,
        'stop_service_s': stop_service, 'stop_actors': copy.deepcopy(actors), 'branches': bindings,
        'bookkeeping_volumes_ul': volumes, 'assumptions': copy.deepcopy(facts.assumptions)}
    definition['protective_stop_bindings'] = protective
    combined_pins = definition['source_files_sha256']
    combined_pins.update(pins)
    if path is not None and path.resolve().is_relative_to(ROOT.resolve()):
        combined_pins[str(path.resolve().relative_to(ROOT.resolve()))] = digest(content)
    for name in RUNTIME:
        file = ROOT / name
        require(file.is_file(), 'Missing CUT&RUN execution source: ' + name)
        combined_pins[name] = digest(file.read_bytes())
    definition['runtime_source_files'] = list(dict.fromkeys([*definition['runtime_source_files'], *RUNTIME]))
    preparation.verify_source_pins(combined_pins)
    definition['effective_execution_profile_sha256'] = digest(encoded(profile).encode())
    definition['effective_profile_sha256'] = digest(encoded({
        'material_definition_sha256': definition['effective_profile_sha256'],
        'execution_profile_sha256': definition['effective_execution_profile_sha256']}).encode())
    return definition


compile_definition = load
