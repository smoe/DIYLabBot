"""Pinned opt-in transport topology over the existing synthetic lab manifest.

This compiler introduces no sample, vessel, volume or second inventory. Logical
handover places are synthetic; the existing CAD composition is not relocated.
"""
import copy
import json
from pathlib import Path

import assembly_model as assembly
import async_transport_domain as domain
from lab_workflow_sources import load as load_workflow, STAGES
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/synthetic-lab-workflow.transport.json'
SCHEMA = ROOT / 'model/synthetic-lab-workflow.transport.schema.json'
FORMAT = 'solidcraftbot.synthetic-lab-transport-workflow/2'
RUNTIME = ('scripts/lab_transport_sources.py', 'scripts/lab_transport_workflow.py',
           'scripts/run_lab_transport_workflow.py', 'scripts/lab_workflow.py',
           'scripts/lab_workflow_ledger.py', 'scripts/lab_workflow_stages.py',
           'scripts/run_lab_workflow.py', 'scripts/async_transport_domain.py',
           'scripts/async_transport_adapters.py', 'scripts/async_transport.py',
           'scripts/material_ledger.py')


def load(source=SOURCE, runtime_sources=()):
    """Compile references, never initialize an existing owner's stock."""
    try:
        return _load(source, runtime_sources)
    except TaskError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise TaskError('Invalid lab transport composition: ' + str(error)) from error


def _load(source, runtime_sources):
    path = None if isinstance(source, dict) else Path(source).resolve()
    if path is not None:
        domain.require(path.is_relative_to(ROOT), 'Repository transport composition required')
    profile = copy.deepcopy(source) if path is None else domain._json(path.read_bytes())
    domain.exact(profile, 'format id mode workflow transport_protocol owner_principal '
                 'rack_initial_endpoint endpoints agents routes limitations', 'lab transport composition')
    domain.require(profile['format'] == FORMAT and profile['mode'] == 'synthetic_only',
                   'Explicit synthetic transport workflow version required')
    domain.ident(profile['id']); domain.ident(profile['owner_principal'])
    domain.ident(profile['rack_initial_endpoint'])
    for key in ('workflow', 'transport_protocol'):
        domain.exact(profile[key], 'source source_sha256', key + ' reference')
    workflow_path = assembly.validate_reference(profile['workflow'])
    protocol_path = assembly.validate_reference(profile['transport_protocol'])
    domain.require(protocol_path == domain.PROTOCOL.resolve(), 'Existing transport protocol required')
    contract = domain.load_contract()
    domain.require(profile['transport_protocol']['source_sha256'] == contract['source_sha256'],
                   'Transport protocol pin mismatch')
    runtime = list(dict.fromkeys([*RUNTIME, *runtime_sources]))
    definition = load_workflow(workflow_path, runtime_sources=runtime)
    topology = {'owner_principal': profile['owner_principal'],
                'racks': [{'id': definition['rack_instance'],
                           'initial_endpoint': profile['rack_initial_endpoint'], 'closed': True}],
                'endpoints': copy.deepcopy(profile['endpoints']),
                'agents': copy.deepcopy(profile['agents']),
                'protocol': copy.deepcopy(profile['transport_protocol'])}
    # Structural validation reuses the embedded provider. This detached identity
    # view has no volumes, no material admission and no persistent inventory.
    manifests = {definition['rack_instance']: [
        {'place_id': sample['rack_place_id'], 'vessel_id': sample['vessel_id'],
         'content_revision': 0,
         'materials': [{'material_id': sample['sample_id'], 'origin_id': None}]}
        for sample in definition['manifest']['samples']]}
    domain.embedded_initial(topology, manifests, 'SYN.Transport.SourceCheck', 'SourceCheck')
    routes = profile['routes']
    domain.require(isinstance(routes, list) and len(routes) == len(STAGES) - 1,
                   'One transport route per existing stage boundary required')
    endpoints = {item['id'] for item in topology['endpoints']}
    agents = {item['id'] for item in topology['agents']}
    ids = set()
    previous = profile['rack_initial_endpoint']
    for index, route in enumerate(routes):
        domain.exact(route, 'id source_stage target_stage source_endpoint target_endpoint agent_id', 'stage route')
        for value in route.values(): domain.ident(value)
        domain.require(route['id'] not in ids, 'Duplicate route identity')
        ids.add(route['id'])
        domain.require((route['source_stage'], route['target_stage']) == tuple(STAGES[index:index + 2]),
                       'Routes must preserve CF01, NanoDrop, Qubit order')
        domain.require(route['source_endpoint'] == previous
                       and route['source_endpoint'] in endpoints
                       and route['target_endpoint'] in endpoints
                       and route['source_endpoint'] != route['target_endpoint']
                       and route['agent_id'] in agents, 'Unknown or discontinuous transport route')
        previous = route['target_endpoint']
    domain.require(isinstance(profile['limitations'], list) and bool(profile['limitations']),
                   'Explicit transport limitations required')
    for limitation in profile['limitations']: domain.reason_text(limitation)
    definition['format'] = FORMAT
    definition['transport'] = {'topology': topology, 'routes': copy.deepcopy(routes),
                               'profile': copy.deepcopy(profile)}
    pins = definition['source_files_sha256']
    for file in [SCHEMA, ROOT / 'model/async-lab-transport.schema.json',
                 protocol_path, *([path] if path is not None else [])]:
        pins[str(file.relative_to(ROOT))] = digest(file.read_bytes())
    definition['effective_profile_sha256'] = digest(encoded({
        'workflow': definition['effective_profile_sha256'], 'transport': profile}).encode())
    for name, expected in pins.items():
        file = (ROOT / name).resolve()
        domain.require(file.is_relative_to(ROOT) and file.is_file()
                       and digest(file.read_bytes()) == expected, 'Source changed during transport compilation: ' + name)
    return definition
