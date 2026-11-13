"""Explicit T3 interface binding over the existing T2 laboratory composition."""
import copy
from pathlib import Path

import assembly_model as assembly
import async_transport_domain as domain
from lab_transport_sources import load as load_transport
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/synthetic-lab-workflow.network.json'
PROTOCOL = ROOT / 'model/lab-transport-network.protocol.json'
SCHEMA = ROOT / 'model/lab-transport-network.schema.json'
PROFILE_FORMAT = 'solidcraftbot.lab-transport-network/1'
DEFINITION_FORMAT = 'solidcraftbot.synthetic-lab-network-workflow/3'
RUNTIME = ('scripts/lab_transport_network_sources.py', 'scripts/lab_transport_network.py',
           'scripts/lab_transport_access.py', 'scripts/lab_transport_http.py',
           'scripts/run_lab_transport_network.py', 'scripts/cf01_sila2_auth.py',
           'scripts/lab_transport_courier.html', 'scripts/lab_transport_courier.js',
           'scripts/lab_transport_courier.css')


def load_contract():
    raw = PROTOCOL.read_bytes()
    value = domain._json(raw)
    domain.exact(value, 'format id protocol paths operations roles limits limitations', 'T3 network contract')
    domain.require(value['format'] == 'solidcraftbot.lab-transport-network-protocol/1'
                   and value['id'] == 'LabTransportNetwork.T3'
                   and value['protocol'] == 'https-json/1', 'Unsupported courier network contract')
    domain.exact(value['paths'], 'info login logout session snapshot requests receipt_prefix', 'HTTP paths')
    for path in value['paths'].values():
        domain.require(isinstance(path, str) and path.startswith('/api/')
                       and all(char.isascii() and (char.isalpha() or char == '/') for char in path),
                       'Same-origin literal API path required')
    domain.require(len(set(value['paths'].values())) == len(value['paths']), 'Duplicate network path')
    domain.require(value['paths']['receipt_prefix'] == value['paths']['requests'] + '/', 'Receipt path must extend request path')
    domain.require(value['operations'] == ['resume', 'prepare_route', 'dispatch', 'attest', 'hold', 'cancel', 'reconcile']
                   and value['roles'] == ['owner', 'observer', 'endpoint', 'agent'], 'Unsupported network operations or grants')
    limits = value['limits']
    domain.exact(limits, 'max_body_bytes max_response_bytes token_lifetime_s password_iterations_min request_timeout_s', 'network limits')
    for name, number in limits.items():
        domain.require(type(number) is int and number > 0, 'Positive integer network limit required: ' + name)
    domain.require(limits['password_iterations_min'] == 600000
                   and limits['token_lifetime_s'] == 900
                   and limits['max_body_bytes'] <= 65536
                   and limits['max_response_bytes'] <= 2097152, 'Unsupported security or message limits')
    domain.require(isinstance(value['limitations'], list) and bool(value['limitations']), 'Network limitations required')
    for limitation in value['limitations']: domain.reason_text(limitation)
    value['source_sha256'] = digest(raw)
    return value


def load(source=SOURCE, runtime_sources=()):
    try:
        return _load(source, runtime_sources)
    except TaskError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise TaskError('Invalid courier network composition: ' + str(error)) from error


def _load(source, runtime_sources):
    path = None if isinstance(source, dict) else Path(source).resolve()
    if path is not None: domain.require(path.is_relative_to(ROOT), 'Repository network composition required')
    profile = copy.deepcopy(source) if path is None else domain._json(path.read_bytes())
    domain.exact(profile, 'format id mode workflow interface_protocol limitations', 'network composition')
    domain.require(profile['format'] == PROFILE_FORMAT and profile['mode'] == 'synthetic_only',
                   'Explicit synthetic T3 composition required')
    domain.ident(profile['id'])
    for key in ('workflow', 'interface_protocol'):
        domain.exact(profile[key], 'source source_sha256', key + ' reference')
    workflow = assembly.validate_reference(profile['workflow'])
    protocol = assembly.validate_reference(profile['interface_protocol'])
    domain.require(protocol == PROTOCOL.resolve(), 'Selected network protocol required')
    contract = load_contract()
    domain.require(profile['interface_protocol']['source_sha256'] == contract['source_sha256'], 'Network contract pin mismatch')
    domain.require(isinstance(profile['limitations'], list) and bool(profile['limitations']), 'Network limitations required')
    for limitation in profile['limitations']: domain.reason_text(limitation)
    definition = load_transport(workflow, runtime_sources=list(dict.fromkeys([*RUNTIME, *runtime_sources])))
    definition['format'] = DEFINITION_FORMAT
    definition['network_interface'] = {'profile': profile, 'contract': contract}
    for file in [PROTOCOL, SCHEMA, *([path] if path is not None else [])]:
        definition['source_files_sha256'][str(file.relative_to(ROOT))] = digest(file.read_bytes())
    definition['effective_profile_sha256'] = digest(encoded({
        'workflow': definition['effective_profile_sha256'], 'network': profile}).encode())
    for name, expected in definition['source_files_sha256'].items():
        file = (ROOT / name).resolve()
        domain.require(file.is_relative_to(ROOT) and file.is_file()
                       and digest(file.read_bytes()) == expected, 'Source changed during network compilation: ' + name)
    return definition
