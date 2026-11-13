"""Pure T0 proposals for explicitly synthetic, agent-neutral whole-rack transport.

No I/O to an executor and no persistence occurs here. The owner must commit the
entire returned projection before dispatch and authorize principals externally.
"""
import copy
import json
from pathlib import Path
import re

import material_ledger as ledger
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/async-lab-transport.synthetic.json'
PROTOCOL = ROOT / 'model/async-lab-transport.protocol.json'
CONTRACT_SHA256 = digest(PROTOCOL.read_bytes())
PHASES = ('requested', 'reserved', 'pickup_pending', 'in_custody', 'delivery_pending', 'completed', 'cancelled', 'cancelled_reconciled')
STATE_FORMAT = 'solidcraftbot.async-lab-transport-state/1'
DEFINITION_FORMAT = 'solidcraftbot.async-lab-transport/1'
EMBEDDED_FORMAT = 'solidcraftbot.embedded-async-lab-transport/1'
EMBEDDED_FIELDS = ('format mode run_id session assignment_epoch rack_placements jobs inbox outbox requests resources').split()
ROLES = ('pickup_release', 'pickup_accept', 'delivery_release', 'delivery_accept')
TERMINAL = {'completed', 'cancelled', 'cancelled_reconciled'}
ENVELOPE_FIELDS = ('job_id run_id assignment_epoch rack_id manifest manifest_sha256 source_endpoint '
                   'target_endpoint agent_id agent_kind source_principal target_principal agent_principal '
                   'pickup_handover_id delivery_handover_id execution_mode contract_sha256').split()
OBSERVATION_FIELDS = ('observation_id job_id assignment_epoch handover_id role rack_id manifest_sha256 '
                      'source_endpoint target_endpoint agent_id evidence').split()


class DomainError(TaskError):
    pass


def require(condition, message):
    if not condition:
        raise DomainError(message)


def exact(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields.split() if isinstance(fields, str) else fields),
            'Exact ' + label + ' fields required')


def ident(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', value), 'Unambiguous identifier required')
    return value


def checksum(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value), 'SHA-256 required')


def reason_text(value):
    require(isinstance(value, str) and value.strip() and len(value) <= 2048
            and not any(ord(c) < 32 for c in value), 'Explicit single-line reason required')


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise DomainError('Nonfinite JSON constant: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def hashed(value):
    return digest(encoded(value).encode())


def load_contract():
    raw = PROTOCOL.read_bytes(); value = _json(raw)
    exact(value, 'format id mode roles phases execution_mode transport_time_s motion_executed hardware_executed limitations', 'protocol')
    require(value['format'] == 'solidcraftbot.async-lab-transport-protocol/1'
            and value['mode'] == 'synthetic_only' and value['roles'] == list(ROLES)
            and value['phases'] == list(PHASES)
            and value['execution_mode'] == 'teleportation_mock'
            and type(value['transport_time_s']) is int and value['transport_time_s'] == 0
            and value['motion_executed'] is False and value['hardware_executed'] is False,
            'Unsupported synthetic transport protocol')
    value['source_sha256'] = digest(raw)
    return value


def _items(definition, name):
    return {item['id']: item for item in definition[name]}


def _validate_definition(value):
    exact(value, 'format id mode owner_principal initial_materials initial_vessels racks endpoints agents protocol source_files_sha256', 'definition')
    require(value['format'] == DEFINITION_FORMAT and value['mode'] == 'synthetic_only', 'Unknown transport definition version')
    ident(value['id']); _validate_topology(value)
    racks = _items(value, 'racks')
    inventory = ledger.initial_inventory(value['initial_materials'], value['initial_vessels'])
    require(all(v['location']['kind'] == 'rack' and v['location']['rack_id'] in racks
                for v in inventory['vessels'].values()), 'Vessels must occupy declared rack slots')
    require(set(racks) == {v['location']['rack_id'] for v in inventory['vessels'].values()}, 'Every rack needs declared contents')
    require(len(value['initial_materials']) == len(value['initial_vessels']), 'Every fixture vessel needs one material')
    require(isinstance(value['source_files_sha256'], dict) and value['source_files_sha256'], 'Source pins required')
    for name, expected in value['source_files_sha256'].items():
        require(isinstance(name, str) and not Path(name).is_absolute() and '..' not in Path(name).parts, 'Relative source pin required')
        checksum(expected)


def _validate_topology(value):
    """Shared identities only; fixture inventory and owner inventory stay separate."""
    ident(value['owner_principal'])
    exact(value['protocol'], 'source source_sha256', 'protocol reference')
    require(value['protocol']['source'] == 'model/async-lab-transport.protocol.json', 'Unexpected protocol source')
    checksum(value['protocol']['source_sha256'])
    require(value['protocol']['source_sha256'] == CONTRACT_SHA256, 'Transport contract changed')
    for name, fields in [('racks', 'id initial_endpoint closed'),
                         ('endpoints', 'id site_id lab_id holder_id place_id principal'),
                         ('agents', 'id kind principal')]:
        require(isinstance(value[name], list) and value[name], 'Nonempty ' + name + ' required')
        for item in value[name]:
            exact(item, fields, name)
            for key, component in item.items():
                if key == 'closed': require(component is True, 'Only closed racks supported')
                elif key == 'kind': require(component in {'human', 'robot'}, 'Unknown agent kind')
                else: ident(component)
        require(len(_items(value, name)) == len(value[name]), 'Duplicate ' + name)
    endpoints = _items(value, 'endpoints'); racks = _items(value, 'racks')
    tuples = [(e['site_id'], e['lab_id'], e['holder_id'], e['place_id']) for e in endpoints.values()]
    require(len(tuples) == len(set(tuples)), 'Aliased endpoint identity')
    origins = [rack['initial_endpoint'] for rack in racks.values()]
    require(set(origins) <= set(endpoints) and len(origins) == len(set(origins)), 'Occupied or unknown initial rack endpoint')


def load_definition(source=SOURCE):
    source = Path(source).resolve()
    require(source.is_relative_to(ROOT), 'Repository definition required')
    raw = source.read_bytes(); value = _json(raw)
    require('source_files_sha256' not in value, 'Derived source pins must not be leading data')
    value['source_files_sha256'] = {str(source.relative_to(ROOT)): digest(raw)}
    for name in ['model/async-lab-transport.protocol.json', 'model/async-lab-transport.schema.json',
                 'scripts/async_transport_domain.py', 'scripts/material_ledger.py',
                 'scripts/manual_tasks.py', 'scripts/manual_workflow.py']:
        value['source_files_sha256'][name] = digest((ROOT / name).read_bytes())
    _validate_definition(value)
    require(value['protocol']['source_sha256'] == value['source_files_sha256']['model/async-lab-transport.protocol.json'],
            'Protocol reference and captured bytes differ')
    for name, expected in value['source_files_sha256'].items():
        require(digest((ROOT / name).read_bytes()) == expected, 'Source changed while loading: ' + name)
    return value


def initial_state(definition, run_id, session):
    _validate_definition(definition); ident(run_id); ident(session)
    state = {'format': STATE_FORMAT, 'mode': 'synthetic_only', 'run_id': run_id, 'session': session,
             'assignment_epoch': 1, 'definition': copy.deepcopy(definition), 'admitted': False,
             'inventory': {}, 'bookings': {}, 'rack_placements': {}, 'jobs': {},
             'pending_operation': None, 'inbox': {}, 'outbox': {}, 'requests': {}, 'resources': []}
    audit(state)
    return state


def manifest(state, rack_id):
    ident(rack_id)
    require(state['admitted'] and rack_id in _items(state['definition'], 'racks'), 'Admitted rack required')
    if '_manifests' in state:
        return copy.deepcopy(state['_manifests'][rack_id])
    inventory = state['inventory']; result = []
    for vessel in inventory['vessels'].values():
        place = vessel['location']
        if place.get('kind') != 'rack' or place['rack_id'] != rack_id: continue
        materials = sorted(({'material_id': m['id'], 'origin_id': m['origin_id']}
                            for m in inventory['materials'].values() if m['vessel_id'] == vessel['id']),
                           key=lambda item: item['material_id'])
        result.append({'place_id': place['place_id'], 'vessel_id': vessel['id'],
                       'content_revision': vessel['content_revision'], 'materials': materials})
    return sorted(result, key=lambda item: (item['place_id'], item['vessel_id']))


def _manifest(value):
    require(isinstance(value, list) and value, 'Nonempty manifest required')
    slots, vessels, materials = set(), set(), set()
    for item in value:
        exact(item, 'place_id vessel_id content_revision materials', 'manifest entry')
        ident(item['place_id']); ident(item['vessel_id'])
        require(type(item['content_revision']) is int and item['content_revision'] >= 0, 'Content revision required')
        require(item['place_id'] not in slots and item['vessel_id'] not in vessels, 'Duplicate manifest slot/vessel')
        slots.add(item['place_id']); vessels.add(item['vessel_id'])
        require(isinstance(item['materials'], list) and item['materials'], 'Material identities required')
        for material in item['materials']:
            exact(material, 'material_id origin_id', 'manifest material')
            ident(material['material_id'])
            if material['origin_id'] is not None: ident(material['origin_id'])
            require(material['material_id'] not in materials, 'Duplicate manifest material')
            materials.add(material['material_id'])


def _place_key(definition, endpoint_id):
    endpoint = _items(definition, 'endpoints')[endpoint_id]
    return 'place:' + '|'.join(endpoint[key] for key in ['site_id', 'lab_id', 'holder_id', 'place_id'])


def _job_claims(state, job):
    claims = ['rack:' + job['rack_id'], 'agent:' + job['agent_id'],
              _place_key(state['definition'], job['source_endpoint']),
              _place_key(state['definition'], job['target_endpoint'])]
    for item in job['manifest']:
        claims.append('vessel:' + item['vessel_id'])
        claims.extend('material:' + m['material_id'] for m in item['materials'])
    return sorted(claims)


def resources(state):
    if not state['admitted']: return []
    result = {'rack:' + rack for rack in state['rack_placements']}
    if '_manifests' in state:
        for items in state['_manifests'].values():
            result.update('vessel:' + item['vessel_id'] for item in items)
            result.update('material:' + material['material_id'] for item in items for material in item['materials'])
    else:
        result.add('fixture:' + state['definition']['id'])
        result.update('vessel:' + vessel for vessel in state['inventory']['vessels'])
        result.update('material:' + material for material in state['inventory']['materials'])
    for place in state['rack_placements'].values():
        if place['kind'] == 'endpoint': result.add(_place_key(state['definition'], place['endpoint_id']))
        else: result.add('agent:' + place['agent_id'])
    for job in state['jobs'].values(): result.update(job['claims'])
    return sorted(result)


def decode_envelope(value):
    value = copy.deepcopy(value); exact(value, ENVELOPE_FIELDS, 'transport envelope')
    for key in ENVELOPE_FIELDS:
        if key not in {'assignment_epoch', 'manifest', 'manifest_sha256', 'contract_sha256', 'agent_kind', 'execution_mode'}:
            ident(value[key])
    require(type(value['assignment_epoch']) is int and value['assignment_epoch'] > 0, 'Positive assignment epoch required')
    _manifest(value['manifest']); checksum(value['manifest_sha256']); checksum(value['contract_sha256'])
    require(value['manifest_sha256'] == hashed(value['manifest']), 'Manifest digest mismatch')
    require(value['contract_sha256'] == CONTRACT_SHA256, 'Unknown envelope contract')
    require(value['agent_kind'] in {'human', 'robot'} and value['execution_mode'] == 'teleportation_mock', 'Only synthetic mock executors supported')
    require(value['source_endpoint'] != value['target_endpoint'] and value['pickup_handover_id'] != value['delivery_handover_id'], 'Distinct endpoints and handovers required')
    return value


def envelope(state, job_id):
    job = state['jobs'][job_id]
    require(job['pickup_handover_id'] is not None, 'Prepared job required')
    definition = state['definition']; endpoints = _items(definition, 'endpoints'); agent = _items(definition, 'agents')[job['agent_id']]
    value = {key: copy.deepcopy(job[key]) for key in ['job_id', 'assignment_epoch', 'rack_id', 'manifest', 'manifest_sha256',
             'source_endpoint', 'target_endpoint', 'agent_id', 'pickup_handover_id', 'delivery_handover_id']}
    value.update(run_id=state['run_id'], agent_kind=agent['kind'], source_principal=endpoints[job['source_endpoint']]['principal'],
                 target_principal=endpoints[job['target_endpoint']]['principal'], agent_principal=agent['principal'],
                 execution_mode='teleportation_mock', contract_sha256=definition['protocol']['source_sha256'])
    return decode_envelope(value)


def principal_for(value, role):
    require(role in ROLES, 'Unknown observation role')
    return value['source_principal'] if role == 'pickup_release' else value['target_principal'] if role == 'delivery_accept' else value['agent_principal']


def observation_for(value, role, observation_id):
    value = decode_envelope(value); ident(observation_id); require(role in ROLES, 'Unknown observation role')
    evidence = 'synthetic_endpoint_attestation' if role in {'pickup_release', 'delivery_accept'} else (
        'synthetic_courier_attestation' if value['agent_kind'] == 'human' else 'synthetic_robot_attestation')
    return {'observation_id': observation_id, 'job_id': value['job_id'], 'assignment_epoch': value['assignment_epoch'],
            'handover_id': value['pickup_handover_id'] if role.startswith('pickup') else value['delivery_handover_id'],
            'role': role, 'rack_id': value['rack_id'], 'manifest_sha256': value['manifest_sha256'],
            'source_endpoint': value['source_endpoint'], 'target_endpoint': value['target_endpoint'],
            'agent_id': value['agent_id'], 'evidence': evidence}


def claim_for(value, claim_id):
    value = decode_envelope(value); ident(claim_id)
    return {'claim_id': claim_id, 'job_id': value['job_id'], 'assignment_epoch': value['assignment_epoch'],
            'envelope_sha256': hashed(value), 'evidence': 'worker_claim', 'outcome': 'claimed_performed',
            'execution_mode': 'teleportation_mock', 'transport_time_s': 0,
            'motion_executed': False, 'hardware_executed': False}


def _observation_types(value):
    exact(value, OBSERVATION_FIELDS, 'observation')
    require(type(value['assignment_epoch']) is int and value['assignment_epoch'] > 0,
            'Observation epoch must be a positive integer, not bool or float')


def _claim_types(value):
    exact(value, 'claim_id job_id assignment_epoch envelope_sha256 evidence outcome execution_mode transport_time_s motion_executed hardware_executed', 'worker claim')
    require(type(value['assignment_epoch']) is int and value['assignment_epoch'] > 0,
            'Claim epoch must be a positive integer, not bool or float')
    require(type(value['transport_time_s']) is int and value['transport_time_s'] == 0
            and value['motion_executed'] is False and value['hardware_executed'] is False,
            'Mock time must be integer zero and execution flags must be boolean false')


def _hold(job, reason):
    job['control'] = 'held'; job['hold_reason'] = job['hold_reason'] or reason


def _rack_uncontested(state, rack_id, current_job_id=None):
    require(not any(j['rack_id'] == rack_id and j['control'] == 'held'
                    for key, j in state['jobs'].items() if key != current_job_id),
            'Rack has unresolved historical custody observations')


def _finish(state, job, phase):
    job.update(phase=phase, control='active', hold_reason=None, claims=[])


def _drain(state, job):
    if any(other['rack_id'] == job['rack_id'] and other['control'] == 'held'
           for other in state['jobs'].values() if other['job_id'] != job['job_id']):
        _hold(job, 'rack_history_uncertain')
        return
    if job['control'] != 'active': return
    if all(role in job['receipts'] for role in ROLES[:2]) and job['phase'] == 'pickup_pending':
        state['rack_placements'][job['rack_id']] = {'kind': 'agent', 'agent_id': job['agent_id']}
        job['phase'] = 'in_custody'
        for role in ROLES[:2]: state['inbox'][job['receipts'][role]]['status'] = 'applied'
    if all(role in job['receipts'] for role in ROLES) and job['phase'] in {'in_custody', 'delivery_pending'}:
        state['rack_placements'][job['rack_id']] = {'kind': 'endpoint', 'endpoint_id': job['target_endpoint']}
        for role in ROLES: state['inbox'][job['receipts'][role]]['status'] = 'applied'
        if job['cancel_requested']:
            job['phase'] = 'delivery_pending'; _hold(job, 'cancel_disposition_required')
        else: _finish(state, job, 'completed')
    elif job['phase'] == 'in_custody' and any(role in job['receipts'] for role in ROLES[2:]):
        job['phase'] = 'delivery_pending'


def audit(state):
    exact(state, 'format mode run_id session assignment_epoch definition admitted inventory bookings pending_operation rack_placements jobs inbox outbox requests resources', 'root state')
    require(state['format'] == STATE_FORMAT and state['mode'] == 'synthetic_only', 'Unknown root version')
    ident(state['run_id']); ident(state['session'])
    require(type(state['assignment_epoch']) is int and state['assignment_epoch'] > 0 and type(state['admitted']) is bool, 'Invalid root epoch/admission')
    _validate_definition(state['definition'])
    require(all(isinstance(state[name], dict) for name in ['inventory', 'bookings', 'rack_placements', 'jobs', 'inbox', 'outbox', 'requests']), 'Root maps required')
    require(state['bookings'] == {} and state['pending_operation'] is None, 'Transport cannot book material changes')
    if not state['admitted']:
        require(not any(state[name] for name in ['inventory', 'rack_placements', 'jobs', 'inbox', 'outbox', 'resources']), 'Unadmitted fixture must be empty')
        return True
    expected = ledger.initial_inventory(state['definition']['initial_materials'], state['definition']['initial_vessels'])
    require(state['inventory'] == expected, 'Transport fixture inventory/content changed')
    return _audit_transport(state)


def _audit_transport(state, *, historical_terminal=False):
    """One queue/custody audit for both fixture and embedded owner contexts."""
    racks = _items(state['definition'], 'racks'); endpoints = _items(state['definition'], 'endpoints'); agents = _items(state['definition'], 'agents')
    require(set(state['rack_placements']) == set(racks), 'Rack placement completeness mismatch')
    occupied = set()
    for place in state['rack_placements'].values():
        if place.get('kind') == 'endpoint':
            exact(place, 'kind endpoint_id', 'rack placement'); require(place['endpoint_id'] in endpoints, 'Unknown endpoint')
        else:
            exact(place, 'kind agent_id', 'rack custody'); require(place['kind'] == 'agent' and place['agent_id'] in agents, 'Unknown rack custodian')
        require(encoded(place) not in occupied, 'Rack placement occupied twice'); occupied.add(encoded(place))
    claims = set()
    for job_id, job in state['jobs'].items():
        exact(job, 'job_id rack_id source_endpoint target_endpoint agent_id assignment_epoch manifest manifest_sha256 phase control hold_reason claims pickup_handover_id delivery_handover_id receipts cancel_requested cancel_reason reconciliations', 'job')
        require(job_id == job['job_id'], 'Job key mismatch'); ident(job_id)
        require(job['rack_id'] in racks and job['agent_id'] in agents and job['source_endpoint'] in endpoints
                and job['target_endpoint'] in endpoints and job['source_endpoint'] != job['target_endpoint'], 'Unknown or identical job endpoints')
        require(type(job['assignment_epoch']) is int and 0 < job['assignment_epoch'] <= state['assignment_epoch'], 'Invalid job epoch')
        _manifest(job['manifest'])
        require(job['manifest_sha256'] == hashed(job['manifest']), 'Job manifest digest drift')
        current_manifest = manifest(state, job['rack_id'])
        if historical_terminal and job['phase'] in TERMINAL:
            identities = lambda items: [{key: value for key, value in item.items() if key != 'content_revision'} for item in items]
            require(identities(job['manifest']) == identities(current_manifest), 'Historical job identity/slot drift')
        else:
            require(job['manifest'] == current_manifest, 'Job content/manifest drift')
        require(job['phase'] in PHASES and job['control'] in {'active', 'held'}, 'Invalid job phase/control')
        require((job['control'] == 'held') == bool(job['hold_reason']) and type(job['cancel_requested']) is bool, 'Invalid hold/cancel state')
        require(isinstance(job['receipts'], dict) and set(job['receipts']) <= set(ROLES) and isinstance(job['reconciliations'], list), 'Invalid job receipts')
        for observation in job['reconciliations']:
            exact(observation, 'outcome location manifest_sha256 reason principal evidence', 'reconciliation')
            require(observation['outcome'] in {'unknown', 'not_performed', 'performed'}
                    and observation['manifest_sha256'] == job['manifest_sha256']
                    and observation['principal'] == state['definition']['owner_principal']
                    and observation['evidence'] == 'synthetic_owner_reconciliation', 'Invalid owner reconciliation')
            reason_text(observation['reason'])
            if observation['outcome'] == 'unknown':
                require(observation['location'] is None, 'Unknown reconciliation cannot assert a place')
            else:
                require(observation['location'] in [
                    {'kind': 'endpoint', 'endpoint_id': job['source_endpoint']},
                    {'kind': 'endpoint', 'endpoint_id': job['target_endpoint']},
                    {'kind': 'agent', 'agent_id': job['agent_id']}], 'Unassigned reconciliation place')
        require(job['claims'] == ([] if job['phase'] in TERMINAL or job['phase'] == 'requested' else _job_claims(state, job)), 'Job claims inconsistent')
        require(not claims.intersection(job['claims']), 'Overlapping job subclaims'); claims.update(job['claims'])
        for role, observation_id in job['receipts'].items():
            entry = state['inbox'].get(observation_id)
            require(entry is not None and entry['observation'] == observation_for(envelope(state, job_id), role, observation_id)
                    and entry['principal'] == principal_for(envelope(state, job_id), role)
                    and entry['status'] in {'pending', 'applied'}, 'Missing/mismatched role receipt')
        if job['phase'] == 'completed':
            require(set(job['receipts']) == set(ROLES) and all(state['inbox'][i]['status'] == 'applied' for i in job['receipts'].values()), 'Completion requires four applied role receipts')
        if job['phase'] == 'cancelled':
            require(job['cancel_requested'] and job['cancel_reason'], 'Cancellation needs its explicit request')
        if job['phase'] == 'cancelled_reconciled':
            require(job['reconciliations'] and job['reconciliations'][-1]['outcome'] != 'unknown'
                    and job['reconciliations'][-1]['location']['kind'] == 'endpoint', 'Recovered cancellation needs supported disposition evidence')
        if job['phase'] in {'in_custody', 'delivery_pending'}:
            require(set(ROLES[:2]) <= set(job['receipts']), 'Custody phase requires both pickup receipts')
        if job['phase'] not in {'requested', 'reserved', 'cancelled', 'cancelled_reconciled'}:
            require(job['pickup_handover_id'] is not None and job['delivery_handover_id'] is not None, 'Phase requires authorized handovers')
        if job['pickup_handover_id'] is not None:
            env = envelope(state, job_id)
            require(job_id in state['outbox'] and state['outbox'][job_id]['envelope'] == env, 'Missing immutable outbox envelope')
    for key, entry in state['inbox'].items():
        exact(entry, 'observation principal status reason', 'inbox entry')
        _observation_types(entry['observation'])
        require(entry['status'] in {'pending', 'applied', 'duplicate', 'conflict', 'stale'} and isinstance(entry['observation'], dict), 'Invalid inbox status')
        require(key == entry['observation'].get('observation_id') or entry['status'] == 'conflict', 'Inbox identity mismatch')
    for job_id, entry in state['outbox'].items():
        exact(entry, 'envelope status claim', 'outbox entry')
        require(job_id in state['jobs'] and entry['status'] in {'pending', 'dispatched', 'uncertain', 'withdrawn'}, 'Invalid outbox state')
        decode_envelope(entry['envelope'])
        if entry['claim'] is not None:
            _claim_types(entry['claim'])
            require(entry['claim'] == claim_for(entry['envelope'], entry['claim'].get('claim_id')), 'Invalid outbox worker claim')
    require(state['resources'] == resources(state), 'Root resource projection mismatch')
    return True


def apply(state, operation, args, principal):
    """Return one detached proposal; caller commits atomically or discards it."""
    return _reduce(state, operation, args, principal, audit)


def _reduce(state, operation, args, principal, audit_context):
    """Shared transitions; callers supply only their inventory/context audit."""
    audit_context(state); ident(principal); require(isinstance(args, dict), 'Operation arguments required')
    result = copy.deepcopy(state); definition = result['definition']; owner = definition['owner_principal']
    shapes = {'admit': '', 'request': 'job_id rack_id target_endpoint agent_id', 'reserve': 'job_id',
              'prepare': 'job_id', 'mark_dispatched': 'job_id', 'worker_claim': 'job_id claim',
              'observe': 'job_id observation', 'cancel': 'job_id reason', 'resume': 'session',
              'reconcile': 'job_id outcome location manifest reason', 'hold': 'job_id reason'}
    require(operation in shapes, 'Unknown transport operation'); exact(args, shapes[operation], 'operation')
    if operation not in {'observe', 'worker_claim'}: require(principal == owner, 'Owner principal required')
    if operation == 'admit':
        require(not result['admitted'], 'Fixture already admitted')
        result['inventory'] = ledger.initial_inventory(definition['initial_materials'], definition['initial_vessels'])
        result['rack_placements'] = {r['id']: {'kind': 'endpoint', 'endpoint_id': r['initial_endpoint']} for r in definition['racks']}
        result['admitted'] = True
    elif operation == 'resume':
        ident(args['session']); require(args['session'] != result['session'], 'New explicit session required')
        result['session'] = args['session']; result['assignment_epoch'] += 1
        for job_id, job in result['jobs'].items():
            if job['phase'] not in TERMINAL:
                _hold(job, 'restart_reconciliation')
                if job_id in result['outbox']: result['outbox'][job_id]['status'] = 'uncertain'
    else:
        require(result['admitted'], 'Admit the synthetic fixture before use')
        job_id = ident(args['job_id'])
        if operation == 'request':
            require(job_id not in result['jobs'], 'Job already exists')
            rack_id = args['rack_id']; target = args['target_endpoint']; agent = args['agent_id']
            require(rack_id in result['rack_placements'] and target in _items(definition, 'endpoints') and agent in _items(definition, 'agents'), 'Unknown rack, endpoint or agent')
            _rack_uncontested(result, rack_id)
            place = result['rack_placements'][rack_id]
            require(place['kind'] == 'endpoint' and place['endpoint_id'] != target, 'Confirmed distinct source endpoint required')
            contents = manifest(result, rack_id)
            result['jobs'][job_id] = {'job_id': job_id, 'rack_id': rack_id, 'source_endpoint': place['endpoint_id'],
                'target_endpoint': target, 'agent_id': agent, 'assignment_epoch': result['assignment_epoch'],
                'manifest': contents, 'manifest_sha256': hashed(contents), 'phase': 'requested', 'control': 'active',
                'hold_reason': None, 'claims': [], 'pickup_handover_id': None, 'delivery_handover_id': None,
                'receipts': {}, 'cancel_requested': False, 'cancel_reason': None, 'reconciliations': []}
        else:
            require(job_id in result['jobs'], 'Unknown job'); job = result['jobs'][job_id]
            if operation == 'observe':
                observation = args['observation']; _observation_types(observation)
                observation_id = ident(observation['observation_id']); role = observation['role']
                require(role in ROLES and job['pickup_handover_id'] is not None, 'Authorized handover required')
                env = envelope(result, job_id)
                require(principal == principal_for(env, role), 'Principal cannot attest this handover role')
                previous = result['inbox'].get(observation_id)
                if (previous and previous['observation'] == observation and previous['principal'] == principal
                        and observation['job_id'] == job_id):
                    return result
                entry = {'observation': copy.deepcopy(observation), 'principal': principal, 'status': 'pending', 'reason': None}
                if previous:
                    key = observation_id + '.conflict.' + hashed({'observation': observation, 'principal': principal})[:16]
                    entry.update(status='conflict', reason='observation_id_reused'); result['inbox'][key] = entry
                    _hold(job, 'conflicting_observation')
                elif role in job['receipts'] and observation == observation_for(env, role, observation_id):
                    # A new request/message ID is not a second handover effect.
                    entry.update(status='duplicate', reason='duplicate_role')
                    result['inbox'][observation_id] = entry
                elif (observation != observation_for(env, role, observation_id)
                      or observation['assignment_epoch'] != result['assignment_epoch']
                      or result['outbox'][job_id]['status'] not in {'dispatched', 'uncertain'}
                      or job['phase'] in TERMINAL):
                    entry.update(status='stale' if observation['assignment_epoch'] != result['assignment_epoch'] else 'conflict', reason='binding_or_attempt_mismatch')
                    result['inbox'][observation_id] = entry; _hold(job, 'unresolved_observation')
                elif role in job['receipts']:
                    prior = result['inbox'][job['receipts'][role]]['observation']
                    # A new message ID cannot book the same role a second time.
                    same = {k: v for k, v in prior.items() if k != 'observation_id'} == {k: v for k, v in observation.items() if k != 'observation_id'}
                    entry.update(status='applied' if same else 'conflict', reason='duplicate_role' if same else 'role_conflict')
                    result['inbox'][observation_id] = entry
                    if not same: _hold(job, 'conflicting_role')
                else:
                    result['inbox'][observation_id] = entry; job['receipts'][role] = observation_id
                    _drain(result, job)
            elif operation == 'worker_claim':
                entry = result['outbox'].get(job_id); require(entry is not None and entry['status'] == 'dispatched', 'Dispatched job required')
                require(principal == entry['envelope']['agent_principal'], 'Assigned agent principal required')
                claim = args['claim']; _claim_types(claim)
                require(claim == claim_for(entry['envelope'], claim['claim_id']), 'Unbound or promoted worker claim')
                require(entry['claim'] is None or entry['claim'] == claim, 'Conflicting worker claim')
                entry['claim'] = copy.deepcopy(claim)
            elif operation == 'hold':
                reason_text(args['reason']); require(job['phase'] not in TERMINAL, 'Terminal job cannot be held')
                _hold(job, args['reason'])
                if job_id in result['outbox'] and result['outbox'][job_id]['status'] == 'dispatched':
                    result['outbox'][job_id]['status'] = 'uncertain'
            elif operation == 'cancel':
                reason_text(args['reason']); require(job['phase'] not in TERMINAL, 'Terminal job cannot be cancelled')
                job.update(cancel_requested=True, cancel_reason=args['reason'])
                outbox = result['outbox'].get(job_id)
                if outbox is None or outbox['status'] == 'pending':
                    if outbox: outbox['status'] = 'withdrawn'
                    _finish(result, job, 'cancelled')
                else: _hold(job, 'cancel_reconciliation')
            elif operation == 'reconcile':
                require(job['control'] == 'held' and job['phase'] not in TERMINAL, 'Held nonterminal job required')
                require(args['outcome'] in {'unknown', 'not_performed', 'performed'}, 'Explicit reconciliation outcome required')
                reason_text(args['reason']); require(args['manifest'] == job['manifest'], 'Complete current manifest required')
                place = args['location']
                if args['outcome'] == 'unknown':
                    require(place is None, 'Unknown outcome cannot assert a location')
                else:
                    require(isinstance(place, dict), 'Explicit current location required')
                    if args['outcome'] == 'not_performed':
                        require(place == {'kind': 'endpoint', 'endpoint_id': job['source_endpoint']}
                                and not any(role in job['receipts'] for role in ROLES), 'Nonperformance requires source and no performed handover receipt')
                        result['rack_placements'][job['rack_id']] = copy.deepcopy(place)
                        if job_id in result['outbox']: result['outbox'][job_id]['status'] = 'withdrawn'
                        _finish(result, job, 'cancelled_reconciled')
                    else:
                        require(place in [{'kind': 'endpoint', 'endpoint_id': job['source_endpoint']},
                                          {'kind': 'endpoint', 'endpoint_id': job['target_endpoint']},
                                          {'kind': 'agent', 'agent_id': job['agent_id']}], 'Unassigned reconciliation location')
                        # A controlled supported disposition is not a normal transport success.
                        result['rack_placements'][job['rack_id']] = copy.deepcopy(place)
                        if place['kind'] == 'endpoint':
                            for other_rack, other_place in result['rack_placements'].items():
                                require(other_rack == job['rack_id'] or other_place != place, 'Reconciliation target occupied')
                            _finish(result, job, 'cancelled_reconciled')
                job['reconciliations'].append({'outcome': args['outcome'], 'location': copy.deepcopy(place),
                    'manifest_sha256': job['manifest_sha256'], 'reason': args['reason'], 'principal': principal,
                    'evidence': 'synthetic_owner_reconciliation'})
            else:
                require(job['control'] == 'active' and not job['cancel_requested']
                        and job['assignment_epoch'] == result['assignment_epoch'], 'Held, cancelled or stale job')
                _rack_uncontested(result, job['rack_id'], job_id)
                if operation == 'reserve':
                    require(job['phase'] == 'requested', 'Requested job required')
                    require(result['rack_placements'][job['rack_id']] == {'kind': 'endpoint', 'endpoint_id': job['source_endpoint']}, 'Source rack moved')
                    require(not any(p == {'kind': 'endpoint', 'endpoint_id': job['target_endpoint']} for p in result['rack_placements'].values()), 'Target endpoint occupied')
                    claims = _job_claims(result, job)
                    require(not any(set(claims).intersection(j['claims']) for key, j in result['jobs'].items() if key != job_id), 'Job subclaim conflict')
                    job.update(phase='reserved', claims=claims)
                elif operation == 'prepare':
                    require(job['phase'] == 'reserved', 'Reserved job required')
                    handover = 'Handover.' + hashed({'run_id': result['run_id'], 'job_id': job_id,
                        'assignment_epoch': job['assignment_epoch'], 'manifest_sha256': job['manifest_sha256']})
                    job.update(phase='pickup_pending', pickup_handover_id=handover + '.Pickup', delivery_handover_id=handover + '.Delivery')
                    result['outbox'][job_id] = {'envelope': envelope(result, job_id), 'status': 'pending', 'claim': None}
                elif operation == 'mark_dispatched':
                    require(job['phase'] == 'pickup_pending' and result['outbox'][job_id]['status'] == 'pending', 'Pending outbox required; never redispatch uncertain work')
                    result['outbox'][job_id]['status'] = 'dispatched'
    result['resources'] = resources(result)
    audit_context(result)
    return result


def _embedded_header(queue):
    exact(queue, EMBEDDED_FIELDS, 'embedded queue')
    require(queue['format'] == EMBEDDED_FORMAT and queue['mode'] == 'synthetic_only', 'Unknown embedded queue version')
    ident(queue['run_id']); ident(queue['session'])
    require(type(queue['assignment_epoch']) is int and queue['assignment_epoch'] > 0, 'Invalid embedded queue epoch')
    require(all(isinstance(queue[name], dict) for name in ['rack_placements', 'jobs', 'inbox', 'outbox', 'requests']), 'Embedded queue maps required')


def _embedded_context(queue, topology, manifests):
    """Build a transient identity view, never a second serialized inventory."""
    _embedded_header(queue)
    exact(topology, 'owner_principal racks endpoints agents protocol', 'embedded topology')
    _validate_topology(topology)
    racks = _items(topology, 'racks')
    require(isinstance(manifests, dict) and set(manifests) == set(racks), 'Complete existing-rack manifests required')
    normalized = {}
    vessels, materials = set(), set()
    for rack_id, items in manifests.items():
        _manifest(items)
        for item in items:
            require(item['vessel_id'] not in vessels, 'Vessel appears in multiple payloads')
            vessels.add(item['vessel_id'])
            for material in item['materials']:
                require(material['material_id'] not in materials, 'Material appears in multiple payloads')
                materials.add(material['material_id'])
        normalized[rack_id] = sorted(copy.deepcopy(items), key=lambda item: (item['place_id'], item['vessel_id']))
        for item in normalized[rack_id]:
            item['materials'].sort(key=lambda material: material['material_id'])
    return {**copy.deepcopy(queue), 'definition': copy.deepcopy(topology), 'admitted': True, '_manifests': normalized}


def _audit_embedded_context(state):
    exact(state, [*EMBEDDED_FIELDS, 'definition', 'admitted', '_manifests'], 'embedded context')
    queue = {key: state[key] for key in EMBEDDED_FIELDS}
    _embedded_context(queue, state['definition'], state['_manifests'])
    require(state['admitted'] is True, 'Embedded context never introduces an inventory')
    return _audit_transport(state, historical_terminal=True)


def embedded_initial(topology, manifests, run_id, session):
    """Attach an empty queue to identities already owned by the caller.

    Admission, quantities and material introductions are exclusively owner
    concerns. The provider must supply the complete declared payload manifest
    and check physical readiness before requesting transport.
    """
    exact(topology, 'owner_principal racks endpoints agents protocol', 'embedded topology')
    _validate_topology(topology)
    queue = {'format': EMBEDDED_FORMAT, 'mode': 'synthetic_only', 'run_id': run_id,
             'session': session, 'assignment_epoch': 1, 'rack_placements': {
                 rack['id']: {'kind': 'endpoint', 'endpoint_id': rack['initial_endpoint']}
                 for rack in topology['racks']},
             'jobs': {}, 'inbox': {}, 'outbox': {}, 'requests': {}, 'resources': []}
    context = _embedded_context(queue, topology, manifests)
    queue['resources'] = resources(context)
    embedded_audit(queue, topology, manifests)
    return queue


def embedded_audit(queue, topology, manifests):
    """Audit a queue against current owner identities without changing either."""
    return _audit_embedded_context(_embedded_context(queue, topology, manifests))


def embedded_resources(queue, topology, manifests):
    """Required live owner holds; final owner release is the owner's decision."""
    context = _embedded_context(queue, topology, manifests)
    _audit_embedded_context(context)
    return resources(context)


def embedded_envelope(queue, job_id, topology):
    """Read the frozen assignment, including historical content revisions."""
    _embedded_header(queue)
    exact(topology, 'owner_principal racks endpoints agents protocol', 'embedded topology')
    _validate_topology(topology)
    ident(job_id); require(job_id in queue['jobs'], 'Unknown job')
    return envelope({**queue, 'definition': topology}, job_id)


def embedded_apply(queue, operation, args, principal, topology, manifests):
    """Return one queue proposal for the owner's existing atomic transaction."""
    require(operation != 'admit', 'Embedded transport cannot admit or reset inventory')
    context = _embedded_context(queue, topology, manifests)
    proposal = _reduce(context, operation, args, principal, _audit_embedded_context)
    return {key: copy.deepcopy(proposal[key]) for key in EMBEDDED_FIELDS}
