"""Canonical typed material projection for the opt-in shared material lifecycle.

All changes here are in-memory proposals. The common Journal commits the
booking, its inventory projection, resources and evidence in one transaction.
Legacy volume ledgers are not migrated or mirrored into this contract.
"""
import copy
import math
from contextlib import contextmanager
from functools import wraps

from manual_tasks import MATERIAL_DEFINITION_V2, MATERIAL_STATE_V2, TaskError, digest, encoded
from manual_workflow import ObservationError, keys, text

UNITS = {'uL', 'mg', 'ng', 'cells'}
KINDS = {'sample', 'control', 'reagent', 'product', 'byproduct', 'intermediate'}
DISPOSITIONS = {'retained', 'consumed', 'quarantined', 'discarded'}


def require(value, message):
    if not value:
        raise TaskError(message)


def validate_quantity(value, *, units=UNITS, zero=False):
    keys(value, 'value unit', 'typed quantity')
    require(isinstance(value['unit'], str) and value['unit'] in units, 'Unsupported quantity unit')
    number = value['value']
    if number is not None:
        require(type(number) in (int, float) and math.isfinite(number), 'Finite quantity required')
        require(number >= 0 if zero else number > 0, 'Nonnegative quantity required' if zero else 'Positive quantity required')
        if value['unit'] == 'cells':
            require(number == int(number), 'Integer cell count required')
    return copy.deepcopy(value)


# Public validator name retained for the common source adapter.
quantity = validate_quantity


def location(value):
    require(isinstance(value, dict), 'Physical location required')
    if value.get('kind') == 'rack':
        keys(value, 'kind rack_id place_id', 'rack location')
    elif value.get('kind') == 'logical':
        keys(value, 'kind holder_id place_id', 'holder location')
    elif value.get('kind') == 'operator':
        keys(value, 'kind actor_id', 'custody location')
    elif value.get('kind') == 'discarded':
        keys(value, 'kind', 'discarded vessel location')
    else:
        raise TaskError('Unsupported physical location')
    for item in value.values():
        text(item, 'location component')
    return copy.deepcopy(value)


def initial_inventory(materials, vessels):
    require(isinstance(materials, list) and materials, 'Initial material declarations required')
    require(isinstance(vessels, list) and vessels, 'Initial vessel declarations required')
    inventory = {'materials': {}, 'vessels': {}}
    identities, occupied = set(), set()
    for seed in vessels:
        keys(seed, 'id location', 'initial vessel')
        identity = text(seed['id'], 'vessel identity')
        require(identity not in identities, 'Duplicate material/vessel identity')
        identities.add(identity)
        place = location(seed['location'])
        require(place['kind'] != 'discarded' and encoded(place) not in occupied, 'Initial vessel place is duplicate or discarded')
        occupied.add(encoded(place))
        inventory['vessels'][identity] = {'id': identity, 'location': place, 'responsibility': None,
            'content_revision': 0, 'mass_confirmation_valid': False}
    used_vessels = set()
    for seed in materials:
        keys(seed, 'id kind vessel_id quantity origin_id', 'initial material')
        identity = text(seed['id'], 'material identity')
        require(identity not in identities, 'Duplicate material/vessel identity')
        identities.add(identity)
        require(seed['kind'] in {'sample', 'control', 'reagent'}, 'Only declared inputs and issued reagent aliquots can be introduced')
        vessel = seed['vessel_id']
        require(vessel in inventory['vessels'] and vessel not in used_vessels, 'Initial material needs its own declared vessel')
        used_vessels.add(vessel)
        if seed['origin_id'] is not None:
            text(seed['origin_id'], 'origin identity')
        inventory['materials'][identity] = {'id': identity, 'kind': seed['kind'], 'vessel_id': vessel,
            'source_vessel_id': vessel, 'initial_quantity': quantity(seed['quantity'], zero=True),
            'origin_id': seed['origin_id'], 'parents': [], 'role': 'issued_reagent' if seed['kind'] == 'reagent' else 'input',
            'disposition': None, 'disposition_confirmation': None, 'measurements': {}}
    return inventory


def _material(state, identity):
    text(identity, 'material identity')
    require(identity in state['inventory']['materials'], 'Unknown material: ' + identity)
    return state['inventory']['materials'][identity]


def remaining(state, material_id, exclude_intent=None):
    material = _material(state, material_id)
    initial = material['initial_quantity']
    amounts, uncertain = [], None
    for identity, booking in state['bookings'].items():
        if identity == exclude_intent:
            continue
        if not any(item['material_id'] == material_id for item in booking['request']['inputs']):
            continue
        if booking['outcome'] in {'intent', 'unknown'}:
            uncertain = 'unresolved_operation'
        elif booking['outcome'] == 'performed':
            for item in booking['actual_inputs']:
                if item['material_id'] == material_id:
                    if item['quantity']['value'] is None:
                        uncertain = uncertain or 'confirmed_quantity_unknown'
                    else:
                        amounts.append(item['quantity']['value'])
    value = None if uncertain or initial['value'] is None else initial['value'] - math.fsum(amounts)
    return {'value': value, 'unit': initial['unit'],
            'knowledge': uncertain or ('initial_unknown' if initial['value'] is None else 'known')}


def atomic(function):
    """Do not expose partially validated in-memory changes to any caller."""
    @wraps(function)
    def call(state, *args, **kwargs):
        proposal = copy.deepcopy(state)
        changed = function(proposal, *args, **kwargs)
        if changed is False:
            return False
        state.clear()
        state.update(proposal)
        return changed
    return call


def _invalidate(state, material):
    material['disposition_confirmation'] = None
    if material['disposition'] == 'retained':
        material['disposition'] = None
    vessel_id = material['vessel_id']
    if vessel_id is not None:
        state['inventory']['vessels'][vessel_id]['mass_confirmation_valid'] = False


def _touch(state, material):
    _invalidate(state, material)
    vessel_id = material['vessel_id']
    if vessel_id is not None:
        state['inventory']['vessels'][vessel_id]['content_revision'] += 1


def _receipt(actor_id, reason, **extra):
    text(actor_id, 'synthetic actor identity')
    text(reason, 'evidence reason')
    return {'actor_id': actor_id, 'reason': reason, 'evidence': 'synthetic_input', **extra}


def _protective_layout(state):
    require(state.get('format') == MATERIAL_STATE_V2
            and state.get('definition', {}).get('format') == MATERIAL_DEFINITION_V2,
            'Protective stops require the version-2 material contract')
    bindings = state['definition'].get('protective_stop_bindings')
    operations = state.get('protective_operations')
    require(isinstance(bindings, dict) and isinstance(operations, dict),
            'Declared protective stop bindings and operation references required')
    initial = {item['id']: item for item in state['definition']['initial_materials']}
    for vessel_id, material_id in bindings.items():
        text(vessel_id, 'protected reaction vessel');text(material_id, 'bound stop material')
        require(vessel_id in state['inventory']['vessels'], 'Unknown protected reaction vessel')
        material = _material(state, material_id)
        require(material_id in initial and initial[material_id]['kind'] == 'reagent'
                and material['kind'] == 'reagent' and material['role'] == 'issued_reagent'
                and not material['parents'], 'Protective stop needs a bound issued reagent aliquot')
    seen = set()
    for vessel_id, intent_id in operations.items():
        text(vessel_id, 'protected reaction vessel');text(intent_id, 'protective intent identity')
        require(vessel_id in bindings and intent_id not in seen, 'Unknown vessel or reused protective intent')
        seen.add(intent_id)
        booking = state['bookings'].get(intent_id)
        require(isinstance(booking, dict), 'Protective reference needs its canonical booking')
        require(booking.get('protective_vessel_id') == vessel_id, 'Protective booking vessel reference mismatch')
        require(booking['outcome'] in {'intent', 'unknown', 'performed', 'not_performed'},
                'Unsupported protective booking outcome')
        request = booking['request']
        keys(request, 'kind inputs outputs purpose', 'protective withdrawal request')
        text(request['purpose'], 'protective purpose')
        require(request['kind'] == 'withdrawal' and request['outputs'] == []
                and isinstance(request['inputs'], list) and len(request['inputs']) == 1,
                'Protective stop is one withdrawal without outputs')
        item = request['inputs'][0]
        keys(item, 'material_id quantity consume_all', 'protective input')
        require(item['material_id'] == bindings[vessel_id] and item['consume_all'] is False,
                'Protective stop must withdraw only from its bound issued aliquot')
        observed = quantity(item['quantity'])
        require(observed['unit'] == _material(state, item['material_id'])['initial_quantity']['unit'],
                'Protective withdrawal unit mismatch')
    for identity, booking in state['bookings'].items():
        if 'protective_vessel_id' in booking:
            require(operations.get(booking['protective_vessel_id']) == identity,
                    'A lifetime protective booking reference cannot be removed or replaced')
    return bindings, operations


def _unresolved_protective(state):
    if state.get('format') != MATERIAL_STATE_V2:
        return {}
    _, operations = _protective_layout(state)
    return {vessel: identity for vessel, identity in operations.items()
            if state['bookings'][identity]['outcome'] in {'intent', 'unknown'}}


@contextmanager
def _protective_pending(state, intent_id=None, *, beginning=False):
    """Select a canonical booking only on the caller's atomic cloned proposal.

    The normal pending reference is always restored; protected references stay
    untouched. No temporary context becomes persisted state or another balance.
    """
    pending = copy.deepcopy(state['pending_operation'])
    state['pending_operation'] = None if beginning else {'intent_id': intent_id}
    try:
        yield
    finally:
        state['pending_operation'] = pending


@atomic
def begin_effect(state, actor_id, intent_id, kind, inputs, outputs, purpose):
    text(intent_id, 'intent identity')
    require(not _unresolved_protective(state) or intent_id in state['bookings'],
            'Resolve protective stops before starting normal material work')
    return _begin_effect(state, actor_id, intent_id, kind, inputs, outputs, purpose)


def _begin_effect(state, actor_id, intent_id, kind, inputs, outputs, purpose):
    """Shared validation on an atomic caller's proposal; no write or commit."""
    text(intent_id, 'intent identity')
    text(purpose, 'material operation purpose')
    require(kind in {'withdrawal', 'transformation'}, 'Unsupported material operation')
    require(isinstance(inputs, list) and inputs, 'Material input declarations required')
    require(isinstance(outputs, list), 'Explicit output declarations required')
    request = {'kind': kind, 'inputs': copy.deepcopy(inputs), 'outputs': copy.deepcopy(outputs), 'purpose': purpose}
    try:
        fingerprint = digest(encoded(request).encode())
    except (TypeError, ValueError) as error:
        raise TaskError('Material intents require finite JSON quantities') from error
    existing = state['bookings'].get(intent_id)
    if existing:
        require(existing['request_sha256'] == fingerprint and existing['request'] == request, 'Conflicting intent identity')
        return False
    require(state['pending_operation'] is None, 'Resolve the pending material operation first')
    require(intent_id not in state['inventory']['materials'] and intent_id not in state['inventory']['vessels'],
            'Intent identity conflicts with an existing material or vessel')
    require((kind == 'withdrawal' and len(inputs) == 1 and not outputs)
            or (kind == 'transformation' and bool(outputs)), 'Wrong withdrawal/transformation shape')
    seen_inputs = set()
    for item in inputs:
        keys(item, 'material_id quantity consume_all', 'planned input consumption')
        identity = item['material_id']
        material = _material(state, identity)
        require(identity not in seen_inputs, 'Duplicate operation input')
        seen_inputs.add(identity)
        require(type(item['consume_all']) is bool, 'Explicit consume-all decision required')
        require(material['vessel_id'] is not None and material['disposition'] not in {'consumed', 'discarded', 'quarantined'},
                'Material is consumed, discarded or quarantined')
        planned = quantity(item['quantity'])
        balance = remaining(state, identity)
        require(planned['unit'] == balance['unit'], 'Consumption unit differs from material quantity')
        require(balance['knowledge'] != 'confirmed_quantity_unknown', 'Resolve unknown confirmed consumption first')
        if planned['value'] is not None and balance['value'] is not None:
            require(planned['value'] <= balance['value'] + 1e-9, 'Insufficient recorded quantity for planned consumption')
        _invalidate(state, material)
    all_ids = set(state['inventory']['materials']) | set(state['inventory']['vessels']) | set(state['bookings'])
    all_ids.add(intent_id)
    for old in state['bookings'].values():
        all_ids.update(item['material_id'] for item in old['request']['outputs'])
    output_ids, output_vessels = set(), set()
    for item in outputs:
        keys(item, 'material_id kind vessel_id role', 'planned material output')
        identity = text(item['material_id'], 'output material identity')
        require(identity not in all_ids and identity not in output_ids, 'Output identity has already been used')
        output_ids.add(identity)
        require(item['kind'] in {'product', 'byproduct', 'intermediate'}, 'Unsupported output material kind')
        text(item['role'], 'output fraction role')
        require(item['vessel_id'] in state['inventory']['vessels'] and item['vessel_id'] not in output_vessels,
                'Outputs need distinct declared physical vessels')
        require(state['inventory']['vessels'][item['vessel_id']]['location']['kind'] != 'discarded',
                'A discarded physical vessel cannot receive a new material')
        output_vessels.add(item['vessel_id'])
        for occupant_id, occupant in state['inventory']['materials'].items():
            if occupant['vessel_id'] != item['vessel_id']:
                continue
            planned_input = next((value for value in inputs if value['material_id'] == occupant_id), None)
            require(planned_input is not None, 'Output vessel contains unrelated material')
            balance = remaining(state, occupant_id)['value']
            amount = planned_input['quantity']['value']
            require(planned_input['consume_all'] or (balance is not None and amount is not None
                    and math.isclose(balance, amount, abs_tol=1e-9, rel_tol=0)),
                    'Same-vessel transformation must plan complete consumption of its previous material')
    state['bookings'][intent_id] = {'id': intent_id, 'request': request, 'request_sha256': fingerprint,
        'outcome': 'intent', 'actual_inputs': [], 'actual_outputs': [], 'confirmation': None,
        'quantity_resolutions': {}, 'actor_id': actor_id, 'created_at_s': state['logical_time_s'], 'confirmed_at_s': None}
    state['pending_operation'] = {'intent_id': intent_id}


def _pending(state, intent_id):
    text(intent_id, 'intent identity')
    booking = state['bookings'].get(intent_id)
    require(booking is not None, 'Unknown material intent')
    require(state['pending_operation'] == {'intent_id': intent_id}, 'Intent is not the current pending operation')
    return booking


def _actual(items, expected, state, *, outputs=False):
    require(isinstance(items, list), 'Explicit observed quantity list required')
    result = {}
    for item in items:
        keys(item, 'material_id quantity', 'confirmed typed material amount')
        identity = text(item['material_id'], 'confirmed material identity')
        require(identity in expected and identity not in result, 'Unknown, duplicate or foreign confirmed material')
        result[identity] = quantity(item['quantity'], zero=outputs)
        if not outputs:
            require(result[identity]['unit'] == _material(state, identity)['initial_quantity']['unit'], 'Actual consumption unit mismatch')
    require(set(result) == set(expected), 'Every declared material needs its own observed quantity')
    return result


@atomic
def confirm_effect(state, actor_id, intent_id, actual_inputs, actual_outputs, reason):
    text(reason, 'material effect evidence reason')
    confirmation = {'actual_inputs': copy.deepcopy(actual_inputs), 'actual_outputs': copy.deepcopy(actual_outputs), 'reason': reason}
    booking = state['bookings'].get(intent_id)
    require(booking is not None, 'Unknown material intent')
    if booking['outcome'] == 'performed':
        require(booking['confirmation'] == confirmation, 'Conflicting repeated effect confirmation')
        return False
    _pending(state, intent_id)
    require(booking['outcome'] in {'intent', 'unknown'}, 'Intent already resolved as not performed')
    request = booking['request']
    inputs = _actual(actual_inputs, {item['material_id'] for item in request['inputs']}, state)
    outputs = _actual(actual_outputs, {item['material_id'] for item in request['outputs']}, state, outputs=True)
    consumed = set()
    unknown_partial = set()
    for item in request['inputs']:
        identity = item['material_id']
        actual = inputs[identity]['value']
        available = remaining(state, identity, exclude_intent=intent_id)['value']
        if actual is not None and available is not None and actual > available + 1e-9:
            raise ObservationError('Confirmed consumption exceeds remaining quantity')
        if item['consume_all']:
            if available is not None and (actual is None or not math.isclose(actual, available, abs_tol=1e-9, rel_tol=0)):
                raise ObservationError('Consume-all observation disagrees with the known remaining quantity')
            consumed.add(identity)
        elif actual is not None and available is not None and math.isclose(actual, available, abs_tol=1e-9, rel_tol=0):
            consumed.add(identity)
        elif actual is None:
            unknown_partial.add(identity)
    output_vessels = {item['vessel_id'] for item in request['outputs']}
    for identity, material in state['inventory']['materials'].items():
        if material['vessel_id'] in output_vessels and identity not in consumed:
            raise ObservationError('Observed output vessel contains material that was not fully consumed')
    for identity in inputs:
        material = _material(state, identity)
        _touch(state, material)
        if identity in consumed:
            material.update(vessel_id=None, disposition='consumed',
                            disposition_confirmation=_receipt(actor_id, reason, intent_id=intent_id))
        elif identity in unknown_partial:
            material['disposition'] = 'quarantined'
    for item in request['outputs']:
        identity = item['material_id']
        require(identity not in state['inventory']['materials'], 'Output material already exists')
        state['inventory']['materials'][identity] = {'id': identity, 'kind': item['kind'],
            'vessel_id': item['vessel_id'], 'source_vessel_id': item['vessel_id'],
            'initial_quantity': outputs[identity], 'origin_id': None, 'parents': sorted(inputs),
            'role': item['role'], 'disposition': None, 'disposition_confirmation': None, 'measurements': {}}
        _touch(state, state['inventory']['materials'][identity])
    booking.update(outcome='performed', actual_inputs=copy.deepcopy(actual_inputs), actual_outputs=copy.deepcopy(actual_outputs),
                   confirmation=confirmation, confirmed_at_s=state['logical_time_s'])
    state['pending_operation'] = None


@atomic
def mark_unknown(state, actor_id, intent_id, reason):
    booking = _pending(state, intent_id)
    require(booking['outcome'] in {'intent', 'unknown'}, 'Cannot mark a resolved effect unknown')
    booking['outcome'] = 'unknown'
    booking['uncertainty'] = _receipt(actor_id, reason)
    state['recovery_required'] = 'material_effect_unknown'
    state['workspace_clear'] = False


@atomic
def not_performed(state, actor_id, intent_id, reason):
    booking = state['bookings'].get(intent_id)
    require(booking is not None, 'Unknown material intent')
    receipt = _receipt(actor_id, reason)
    if booking['outcome'] == 'not_performed':
        require(booking['nonperformance'] == receipt, 'Conflicting nonperformance receipt')
        return False
    _pending(state, intent_id)
    require(booking['outcome'] in {'intent', 'unknown'}, 'Effect is already performed')
    booking.update(outcome='not_performed', nonperformance=receipt, confirmed_at_s=state['logical_time_s'])
    state['pending_operation'] = None


def _protective_reference(state, intent_id):
    _, operations = _protective_layout(state)
    found = [vessel for vessel, identity in operations.items() if identity == intent_id]
    require(len(found) == 1, 'Unknown protective stop intent')
    return found[0]


@atomic
def begin_protective_stop(state, actor_id, intent_id, vessel_id, material_id, quantity, purpose='protective_stop'):
    bindings, operations = _protective_layout(state)
    text(intent_id, 'protective intent identity');text(vessel_id, 'protected reaction vessel')
    require(vessel_id in bindings and material_id == bindings[vessel_id], 'Wrong protective stop aliquot binding')
    previous = operations.get(vessel_id)
    require(previous is None or previous == intent_id, 'A reaction vessel has only one lifetime protective stop intent')
    require(previous is not None or intent_id not in state['bookings'], 'Protective intent identity was already used')
    for identity, booking in state['bookings'].items():
        if identity != intent_id and booking['outcome'] in {'intent', 'unknown'}:
            require(material_id not in {item['material_id'] for item in booking['request']['inputs']},
                    'Unresolved material input sets must be disjoint for a protective stop')
    with _protective_pending(state, beginning=True):
        changed = _begin_effect(state, actor_id, intent_id, 'withdrawal',
            [{'material_id': material_id, 'quantity': quantity, 'consume_all': False}], [], purpose)
    if changed is False:
        return False
    state['protective_operations'][vessel_id] = intent_id
    state['bookings'][intent_id]['protective_vessel_id'] = vessel_id


@atomic
def confirm_protective_stop(state, actor_id, intent_id, actual_inputs, reason):
    _protective_reference(state, intent_id)
    with _protective_pending(state, intent_id):
        return confirm_effect(state, actor_id, intent_id, actual_inputs, [], reason)


@atomic
def mark_protective_unknown(state, actor_id, intent_id, reason):
    _protective_reference(state, intent_id)
    with _protective_pending(state, intent_id):
        return mark_unknown(state, actor_id, intent_id, reason)


@atomic
def resolve_protective_stop(state, actor_id, intent_id, outcome, actual_inputs, reason):
    _protective_reference(state, intent_id)
    if outcome == 'performed':
        return confirm_protective_stop(state, actor_id, intent_id, actual_inputs, reason)
    require(actual_inputs is None or actual_inputs == [], 'A nonperformance/unknown receipt cannot invent quantities')
    if outcome == 'unknown':
        return mark_protective_unknown(state, actor_id, intent_id, reason)
    require(outcome == 'not_performed', 'Explicit protective performed, not_performed or unknown outcome required')
    with _protective_pending(state, intent_id):
        return not_performed(state, actor_id, intent_id, reason)


@atomic
def resolve_quantity(state, actor_id, intent_id, material_id, quantity, reason):
    booking = state['bookings'].get(intent_id)
    require(booking is not None and booking['outcome'] == 'performed', 'Confirmed effect required for quantity reconciliation')
    observed = validate_quantity(quantity)
    require(observed['value'] is not None, 'Quantity reconciliation requires a known observed amount')
    material = _material(state, material_id)
    require(observed['unit'] == material['initial_quantity']['unit'], 'Reconciled consumption unit mismatch')
    receipt = {'quantity': observed, 'reason': text(reason, 'quantity reconciliation reason')}
    old = booking['quantity_resolutions'].get(material_id)
    if old:
        require(old['receipt'] == receipt, 'Conflicting quantity reconciliation')
        return False
    values = [item for item in booking['actual_inputs'] if item['material_id'] == material_id]
    require(len(values) == 1 and values[0]['quantity']['value'] is None, 'Only an unknown confirmed consumption may be resolved')
    available = remaining(state, material_id, exclude_intent=intent_id)['value']
    if available is not None and observed['value'] > available + 1e-9:
        raise ObservationError('Reconciled consumption exceeds remaining quantity')
    request = next(item for item in booking['request']['inputs'] if item['material_id'] == material_id)
    if request['consume_all'] and available is not None and not math.isclose(observed['value'], available, abs_tol=1e-9, rel_tol=0):
        raise ObservationError('Reconciled consume-all amount disagrees with remaining quantity')
    values[0]['quantity'] = observed
    booking['quantity_resolutions'][material_id] = {'receipt': receipt, 'actor_id': actor_id, 'evidence': 'synthetic_input'}


@atomic
def set_disposition(state, actor_id, material_id, disposition, reason):
    require(state['pending_operation'] is None, 'Resolve pending effects before material disposition')
    require(not _unresolved_protective(state), 'Resolve protective stops before material disposition')
    require(disposition in DISPOSITIONS, 'Unsupported material disposition')
    material = _material(state, material_id)
    receipt = _receipt(actor_id, reason)
    if material['disposition_confirmation'] == receipt and material['disposition'] == disposition:
        return False
    require(material['disposition'] not in {'consumed', 'discarded'}, 'Consumed or discarded material disposition is terminal')
    balance = remaining(state, material_id)
    if disposition == 'consumed':
        require(balance['value'] is not None and math.isclose(balance['value'], 0, abs_tol=1e-9),
                'Unconfirmed full consumption cannot be inferred from an unknown or nonzero balance')
    if disposition == 'retained':
        require(balance['knowledge'] != 'confirmed_quantity_unknown', 'Unquantified confirmed consumption requires quarantine or reconciliation')
    material.update(disposition=disposition, disposition_confirmation=receipt)
    if disposition in {'consumed', 'discarded'}:
        _touch(state, material)
        material['vessel_id'] = None
        material['disposition_confirmation'] = receipt


@atomic
def record_measurement(state, actor_id, material_id, measurement_id, kind, quantity, reason):
    require(state['pending_operation'] is None, 'Resolve pending effects before confirming a material measurement')
    require(not _unresolved_protective(state), 'Resolve protective stops before confirming a material measurement')
    material = _material(state, material_id)
    require(material['vessel_id'] is not None, 'A material in a current vessel is required')
    require(kind in {'concentration', 'total_vessel_mass'}, 'Unsupported material measurement role')
    observed = validate_quantity(quantity, units={'ng/uL'} if kind == 'concentration' else {'mg', 'g'}, zero=True)
    text(measurement_id, 'measurement identity')
    receipt = {'id': measurement_id, 'kind': kind, 'quantity': observed, **_receipt(actor_id, reason),
               'vessel_id': material['vessel_id'],
               'content_revision': state['inventory']['vessels'][material['vessel_id']]['content_revision']}
    if measurement_id in material['measurements']:
        require(material['measurements'][measurement_id] == receipt, 'Conflicting material measurement identity')
        return False
    material['measurements'][measurement_id] = receipt
    if kind == 'total_vessel_mass':
        state['inventory']['vessels'][material['vessel_id']]['mass_confirmation_valid'] = observed['value'] is not None


def audit(state):
    """Check the canonical projection; no quantities are repaired or inferred."""
    inventory = state['inventory']
    require(set(inventory) == {'materials', 'vessels'}, 'One canonical material/vessel inventory required')
    occupied = set()
    initial = {item['id']: item for item in state['definition']['initial_materials']}
    require(set(initial) <= set(inventory['materials']), 'An introduced input or reagent material disappeared')
    initial_vessels = {item['id'] for item in state['definition']['initial_vessels']}
    require(set(inventory['vessels']) == initial_vessels, 'Physical vessels cannot be invented or silently removed')
    for identity, material in inventory['materials'].items():
        require(identity == material['id'] and material['kind'] in KINDS, 'Corrupt material identity or kind')
        quantity(material['initial_quantity'], zero=True)
        require(material['disposition'] is None or material['disposition'] in DISPOSITIONS, 'Corrupt material disposition')
        if not material['parents']:
            require(identity in initial and material['initial_quantity'] == initial[identity]['quantity']
                    and material['kind'] == initial[identity]['kind']
                    and material['source_vessel_id'] == initial[identity]['vessel_id']
                    and material['origin_id'] == initial[identity]['origin_id'], 'Initial material declaration cannot be reset')
        else:
            require(len(material['parents']) == len(set(material['parents']))
                    and all(parent in inventory['materials'] and parent != identity for parent in material['parents']), 'Broken material ancestry')
            introductions = [b for b in state['bookings'].values() if b['outcome'] == 'performed'
                             and any(item['material_id'] == identity for item in b['actual_outputs'])]
            require(len(introductions) == 1, 'Product must have exactly one confirmed introduction')
            actual = next(item['quantity'] for item in introductions[0]['actual_outputs'] if item['material_id'] == identity)
            require(actual == material['initial_quantity'], 'Product quantity projection changed')
            require(set(material['parents']) == {item['material_id'] for item in introductions[0]['request']['inputs']}, 'Product parent mismatch')
        vessel = material['vessel_id']
        if vessel is not None:
            require(vessel in inventory['vessels'] and vessel not in occupied, 'Material has a foreign or multiply occupied vessel')
            occupied.add(vessel)
        else:
            require(material['disposition'] in {'consumed', 'discarded'}, 'Unresolved material without a physical vessel')
        balance = remaining(state, identity)
        require(balance['value'] is None or balance['value'] >= -1e-9, 'Negative material balance')
    pending = [identity for identity, booking in state['bookings'].items() if booking['outcome'] in {'intent', 'unknown'}]
    if state.get('format') == MATERIAL_STATE_V2:
        _, protected = _protective_layout(state)
        unresolved = set(_unresolved_protective(state).values())
        normal = state['pending_operation']
        if normal is not None:
            keys(normal, 'intent_id', 'normal pending material operation')
            require(normal['intent_id'] in pending and normal['intent_id'] not in protected.values(),
                    'Normal pending operation conflicts with protected references')
        expected_pending = unresolved | ({normal['intent_id']} if normal else set())
        require(set(pending) == expected_pending, 'Pending normal/protective material operation mismatch')
        used_inputs = set()
        for identity in pending:
            current_inputs = {item['material_id'] for item in state['bookings'][identity]['request']['inputs']}
            require(not current_inputs & used_inputs, 'Unresolved material input sets must be disjoint')
            used_inputs.update(current_inputs)
    else:
        require(len(pending) <= 1 and state['pending_operation'] == ({'intent_id': pending[0]} if pending else None), 'Pending material operation mismatch')
    for identity, booking in state['bookings'].items():
        require(identity == booking['id'] and digest(encoded(booking['request']).encode()) == booking['request_sha256'], 'Corrupt material booking')
        require(booking['outcome'] in {'intent', 'unknown', 'performed', 'not_performed'}, 'Unsupported booking outcome')
        expected = {item['material_id'] for item in booking['request']['inputs']}
        require(expected <= set(inventory['materials']), 'Booking references foreign material')
        if booking['outcome'] == 'performed':
            _actual(booking['actual_inputs'], expected, state)
            _actual(booking['actual_outputs'], {item['material_id'] for item in booking['request']['outputs']}, state, outputs=True)
    return True
