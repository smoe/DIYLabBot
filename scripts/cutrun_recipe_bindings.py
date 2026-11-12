"""Run-local working-reagent bindings on the existing material /3 ledger.

Prepared mixtures remain canonical ``intermediate`` materials.  This module
does not introduce quantities, relabel issued aliquots, or maintain a balance.
Only the opt-in recipe engine may bind a protective stop to such a mixture.
"""
import copy

from manual_tasks import TaskError, digest, encoded


ENGINE = 'cutrun_manual_recipe/1'
FEATURE = 'solidcraftbot.recipe-protective-bindings/1'


def require(value, message):
    if not value:
        raise TaskError(message)


def _roles(profile):
    roles = profile.get('roles') if isinstance(profile, dict) else None
    require(isinstance(roles, dict), 'Explicit recipe reagent roles required')
    return roles


def _planned_quantity(value):
    import material_ledger
    return material_ledger.quantity(value, units={'uL'})


def _prepared(profile, role_id, inventory, visiting=None):
    roles = _roles(profile)
    require(role_id in roles, 'Unknown recipe reagent role')
    role = roles[role_id]
    visiting = set() if visiting is None else set(visiting)
    require(role_id not in visiting, 'Cyclic working reagent preparation')
    visiting.add(role_id)
    identity, vessel = role.get('material_id'), role.get('vessel_id')
    require(isinstance(identity, str) and identity.strip() and isinstance(vessel, str)
            and vessel in inventory['vessels'], 'Identified recipe material and declared vessel required')
    if role.get('mode') in {'issued', None} and identity in inventory['materials']:
        material = inventory['materials'].get(identity)
        require(material is not None and material['kind'] == 'reagent'
                and material['vessel_id'] == vessel and not material['parents'],
                'Issued recipe material must match its actual initial reagent aliquot')
        require(material['initial_quantity']['unit'] == 'uL', 'Liquid recipe reagent quantities require uL')
        return
    require(role.get('mode') == 'prepared', 'Recipe reagent source remains open')
    require(identity not in inventory['materials'], 'Prepared reagent cannot relabel an initial material')
    require(not any(item['vessel_id'] == vessel for item in inventory['materials'].values()),
            'Prepared reagent needs an initially empty declared vessel')
    require(all(role.get(field) is None or isinstance(role[field], str) and role[field].strip()
                for field in ('preparation_ref', 'evidence_ref')),
            'Prepared recipe references must stay explicitly open or identified')
    components = role.get('components')
    require(isinstance(components, dict) and bool(components), 'Explicit working reagent components required')
    _planned_quantity(role.get('output_quantity'))
    for component, planned in components.items():
        _planned_quantity(planned)
        _prepared(profile, component, inventory, visiting)


def validate_reagent_binding(inventory, recipe_profile, item, key):
    """Factory hook: accept actual issued aliquots or explicitly planned mixes.

    An open default profile may still archive an actual issued aliquot.  An
    absent physical material cannot be invented from an open role.
    """
    identity = item[key]
    matches = [(name, role) for name, role in _roles(recipe_profile).items()
               if role.get('material_id') == identity]
    require(len(matches) <= 1, 'A reagent identity cannot represent multiple recipe roles')
    material = inventory['materials'].get(identity)
    if material is not None:
        require(material['kind'] == 'reagent', 'A reaction needs an actual issued reagent or planned working mixture')
        if matches:
            name, role = matches[0]
            require(role.get('mode') != 'prepared', 'Prepared reagent cannot reuse an initial aliquot')
            if role.get('mode') == 'issued':
                _prepared(recipe_profile, name, inventory)
        return None if not matches else matches[0][0]
    require(len(matches) == 1 and matches[0][1].get('mode') == 'prepared',
            'Future reaction reagent must be an explicit prepared recipe output')
    _prepared(recipe_profile, matches[0][0], inventory)
    return matches[0][0]


def _declaration(protocol, profile, role_id):
    return {'role_id': role_id, 'protocol': protocol['reagent_roles'][role_id],
            'binding': profile['roles'][role_id]}


def augment_definition(definition, recipe_protocol, recipe_profile, protective_stop_bindings):
    """Pin and permanently allocate planned working-mixture identities.

    These are allocations of future identities, not declarations that the
    material already physically exists or has an observed quantity.
    """
    import material_ledger
    require(definition.get('format') == 'solidcraftbot.material-workflow-definition/3'
            and definition.get('profile', {}).get('type') == ENGINE,
            'Planned recipe reagents require the separate recipe /3 engine')
    inventory = material_ledger.initial_inventory(definition['initial_materials'], definition['initial_vessels'])
    roles = _roles(recipe_profile)
    require(isinstance(recipe_protocol, dict) and isinstance(recipe_protocol.get('reagent_roles'), dict),
            'Pinned recipe reagent protocol required')
    require(set(roles) == set(recipe_protocol['reagent_roles']), 'Recipe role bindings must match the pinned protocol')
    identities, vessels, prepared = set(), set(), {}
    allocations = copy.deepcopy(definition['material_allocations'])
    allocated_materials = {item['material_id'] for item in allocations}
    allocated_vessels = {item['vessel_id'] for item in allocations}
    for role_id, role in roles.items():
        identity, vessel = role.get('material_id'), role.get('vessel_id')
        if identity is not None:
            require(identity not in identities, 'Recipe roles need unique material identities')
            identities.add(identity)
        if vessel is not None:
            require(vessel not in vessels, 'Recipe roles need unique reagent vessels')
            vessels.add(vessel)
        if role.get('mode') not in {'issued', 'prepared'}:
            continue
        _prepared(recipe_profile, role_id, inventory)
        if role['mode'] == 'issued':
            require(identity in allocated_materials and vessel in allocated_vessels,
                    'Issued reagent must retain its initial permanent allocation')
            continue
        require(recipe_protocol['reagent_roles'][role_id].get('kind') == 'working',
                'Only working reagent roles can be prepared in the run')
        expected = recipe_protocol['reagent_roles'][role_id].get('components')
        require(isinstance(expected, list) and set(role['components']) == set(expected),
                'Working mixture components must match the pinned recipe role')
        require(identity not in allocated_materials and vessel not in allocated_vessels,
                'Prepared material/vessel allocation is already used')
        checksum = digest(encoded(_declaration(recipe_protocol, recipe_profile, role_id)).encode())
        prepared[identity] = {'role_id': role_id, 'vessel_id': vessel, 'declaration_sha256': checksum,
            'components': {name: roles[name]['material_id'] for name in role['components']}}
        allocations.append({'material_id': identity, 'vessel_id': vessel, 'declaration_sha256': checksum})
        allocated_materials.add(identity);allocated_vessels.add(vessel)
    require(isinstance(protective_stop_bindings, dict), 'Explicit protective reaction bindings required')
    require(len(set(protective_stop_bindings.values())) == len(protective_stop_bindings),
            'Each reaction needs a distinct stop material')
    for vessel_id, material_id in protective_stop_bindings.items():
        require(vessel_id in inventory['vessels'], 'Unknown protected reaction vessel')
        material = inventory['materials'].get(material_id)
        require(material_id in prepared or material is not None and material['kind'] == 'reagent',
                'A protective source must be an actual issued aliquot or allocated prepared mixture')
    definition['recipe_protocol'] = copy.deepcopy(recipe_protocol)
    definition['recipe_profile'] = copy.deepcopy(recipe_profile)
    definition['recipe_protective_bindings'] = {'format': FEATURE, 'prepared': prepared}
    definition['material_allocations'] = allocations
    definition['protective_stop_bindings'] = copy.deepcopy(protective_stop_bindings)
    return definition


def _feature(state):
    definition = state.get('definition', {})
    feature = definition.get('recipe_protective_bindings')
    require(state.get('format') == 'solidcraftbot.material-workflow-state/3'
            and definition.get('format') == 'solidcraftbot.material-workflow-definition/3'
            and definition.get('profile', {}).get('type') == ENGINE
            and isinstance(feature, dict) and set(feature) == {'format', 'prepared'}
            and feature['format'] == FEATURE and isinstance(feature['prepared'], dict),
            'Pinned recipe protective-binding extension required')
    return definition, feature


def _prepared_declaration(state, identity):
    definition, feature = _feature(state)
    declaration = feature['prepared'].get(identity)
    require(isinstance(declaration, dict) and set(declaration) == {'role_id', 'vessel_id', 'declaration_sha256', 'components'},
            'Unknown planned working reagent')
    role_id = declaration['role_id']
    role = definition['recipe_profile']['roles'][role_id]
    require(role['mode'] == 'prepared' and role['material_id'] == identity
            and role['vessel_id'] == declaration['vessel_id']
            and digest(encoded(_declaration(definition['recipe_protocol'], definition['recipe_profile'], role_id)).encode()) == declaration['declaration_sha256']
            and declaration['components'] == {name: definition['recipe_profile']['roles'][name]['material_id'] for name in role['components']},
            'Prepared reagent declaration changed')
    expected_allocation = {'material_id': identity, 'vessel_id': declaration['vessel_id'],
                           'declaration_sha256': declaration['declaration_sha256']}
    require(expected_allocation in definition['material_allocations'], 'Prepared reagent identity allocation is missing')
    return definition, feature, declaration, role


def _prepared_introduction(state, identity, visiting=None):
    definition, feature, declaration, role = _prepared_declaration(state, identity)
    role_id = declaration['role_id']
    material = state['inventory']['materials'].get(identity)
    require(material is not None and material['kind'] == 'intermediate' and material['role'] == 'working_reagent'
            and material['source_vessel_id'] == declaration['vessel_id'], 'Prepared reagent material projection mismatch')
    introductions = [booking for booking in state['bookings'].values() if booking['outcome'] == 'performed'
                     and any(item['material_id'] == identity for item in booking['request']['outputs'])]
    require(len(introductions) == 1, 'Working mixture needs one confirmed canonical preparation')
    booking = introductions[0]
    request = booking['request']
    outputs = request['outputs']
    action = state.get('manual', {}).get('actions', {}).get(booking['id'])
    components = (action.get('component_materials', declaration['components'])
                  if isinstance(action, dict) else declaration['components'])
    require(isinstance(components, dict) and set(components) == set(declaration['components']),
            'Working reagent needs its named actual component identities')
    for component_role, component_id in components.items():
        _validate_role_material(state, component_role, component_id)
    require(request['kind'] == 'transformation' and request['purpose'] == 'recipe_preparation:' + role_id
            and outputs == [{'material_id': identity, 'kind': 'intermediate',
                             'vessel_id': declaration['vessel_id'], 'role': 'working_reagent'}]
            and set(material['parents']) == set(components.values())
            and {item['material_id'] for item in request['inputs']} == set(components.values())
            and isinstance(action, dict) and action.get('operation') == 'recipe_preparation'
            and action.get('recipe_role') == role_id, 'Working reagent has no matching recipe preparation receipt')
    require(booking['actual_outputs'] == [{'material_id': identity, 'quantity': material['initial_quantity']}],
            'Working reagent quantity differs from its canonical observed introduction')
    visiting = set() if visiting is None else set(visiting)
    require(identity not in visiting, 'Cyclic prepared reagent ancestry')
    visiting.add(identity)
    for parent in components.values():
        if parent in feature['prepared']:
            _prepared_introduction(state, parent, visiting)
        else:
            component_role = next(name for name, value in components.items() if value == parent)
            original = definition['recipe_profile']['roles'][component_role]['material_id']
            initial = next((item for item in definition['initial_materials'] if item['id'] == original), None)
            require(initial is not None and initial['kind'] == 'reagent', 'Working reagent parent is not an issued stock')
    return role_id, material, booking


def _validate_role_material(state, role_id, identity, visiting=None):
    """Verify a retained stock-role descendant against canonical wash effects."""
    definition, feature = _feature(state)
    roles = definition['recipe_profile']['roles']
    require(role_id in roles, 'Unknown reagent role alias')
    original = roles[role_id].get('material_id')
    require(isinstance(identity, str) and isinstance(original, str), 'Identified reagent role material required')
    if identity == original:
        return identity
    visiting = set() if visiting is None else set(visiting)
    require(identity not in visiting, 'Cyclic retained reagent role ancestry')
    visiting.add(identity)
    material = state['inventory']['materials'].get(identity)
    require(material is not None and material['kind'] == 'intermediate', 'Role alias is not a retained working intermediate')
    introductions = [booking for booking in state['bookings'].values() if booking['outcome'] == 'performed'
                     and any(item['material_id'] == identity for item in booking['request']['outputs'])]
    require(len(introductions) == 1, 'Retained reagent needs one canonical introduction')
    booking = introductions[0]
    action = state.get('manual', {}).get('actions', {}).get(booking['id'], {})
    step_id = action.get('recipe_step_id')
    step = next((item for steps in definition['recipe_protocol']['stage_steps'].values()
                 for item in steps if item['id'] == step_id), None)
    require(action.get('operation') == 'recipe_material' and action.get('recipe_target_role') == role_id
            and action.get('retained_material_id') == identity
            and isinstance(step_id, str) and isinstance(step, dict) and step['target_role'] == role_id
            and booking['request']['kind'] == 'transformation'
            and booking['request']['purpose'].startswith('recipe_operation:' + step_id)
            and set(material['parents']) == {item['material_id'] for item in booking['request']['inputs']},
            'Role alias has no matching canonical retained recipe effect')
    candidates = []
    for parent in material['parents']:
        if parent == original:
            candidates.append(parent)
            continue
        previous = next((candidate for candidate in state['bookings'].values()
                         if candidate['outcome'] == 'performed'
                         and any(item['material_id'] == parent for item in candidate['request']['outputs'])), None)
        parent_action = {} if previous is None else state.get('manual', {}).get('actions', {}).get(previous['id'], {})
        if parent_action.get('recipe_target_role') == role_id:
            candidates.append(parent)
    require(len(candidates) == 1, 'Retained reagent alias needs one matching source role ancestor')
    _validate_role_material(state, role_id, candidates[0], visiting)
    return identity


def resolve_role_material(state, role_id):
    definition, unused = _feature(state)
    require(role_id in definition['recipe_profile']['roles'], 'Unknown recipe reagent role')
    original = definition['recipe_profile']['roles'][role_id].get('material_id')
    identity = state.get('recipe', {}).get('role_materials', {}).get(role_id, original)
    if identity is None and original is None:
        return None
    return _validate_role_material(state, role_id, identity)


def validate_protective_source(state, vessel_id, material_id):
    """Structural audit only; unknown quantities remain readable and recoverable."""
    definition, feature = _feature(state)
    if material_id in feature['prepared']:
        _prepared_declaration(state, material_id)
        if material_id not in state['inventory']['materials']:
            require(vessel_id not in state['protective_operations'], 'A protective operation cannot use an unprepared source')
            return
        _prepared_introduction(state, material_id)
        return
    initial = next((item for item in definition['initial_materials'] if item['id'] == material_id), None)
    material = state['inventory']['materials'].get(material_id)
    require(initial is not None and initial['kind'] == 'reagent' and material is not None
            and material['kind'] == 'reagent' and material['role'] == 'issued_reagent'
            and not material['parents'], 'Protective stop needs an issued aliquot or confirmed planned mixture')


def _preparation_ready(state, identity, visiting=None):
    definition, feature = _feature(state)
    visiting = set() if visiting is None else set(visiting)
    require(identity not in visiting, 'Cyclic prepared reagent readiness')
    visiting.add(identity)
    role_id, material, booking = _prepared_introduction(state, identity)
    roles = definition['recipe_profile']['roles']
    role = roles[role_id]
    actual = {item['material_id']: item['quantity'] for item in booking['actual_inputs']}
    declaration = feature['prepared'][identity]
    components = state['manual']['actions'][booking['id']].get('component_materials', declaration['components'])
    planned = {components[name]: quantity for name, quantity in role['components'].items()}
    observed = next(item['quantity'] for item in booking['actual_outputs'] if item['material_id'] == identity)
    if (any(quantity['value'] is None for quantity in role['components'].values())
            or role['output_quantity']['value'] is None
            or any(role.get(name) is None for name in ('preparation_ref', 'evidence_ref'))
            or actual != planned or observed != role['output_quantity']):
        return False
    return all(_preparation_ready(state, component, visiting) for component in planned
               if component in feature['prepared'])


def _retained_role_conformant(state, role_id, identity, visiting):
    """Retained material can carry a nonconformant wash into a later mixture."""
    definition, unused = _feature(state)
    _validate_role_material(state, role_id, identity)
    original = definition['recipe_profile']['roles'][role_id]['material_id']
    if identity == original:
        return True
    booking = next(booking for booking in state['bookings'].values() if booking['outcome'] == 'performed'
                   and any(item['material_id'] == identity for item in booking['request']['outputs']))
    parents = []
    for entry in booking['request']['inputs']:
        parent = entry['material_id']
        if parent == original:
            parents.append(parent)
        else:
            previous = next((item for item in state['bookings'].values() if item['outcome'] == 'performed'
                             and any(output['material_id'] == parent for output in item['request']['outputs'])), None)
            action = {} if previous is None else state['manual']['actions'].get(previous['id'], {})
            if action.get('recipe_target_role') == role_id:
                parents.append(parent)
    require(len(parents) == 1, 'Retained recipe source needs one proved role ancestor')
    target = parents[0]
    actual = {item['material_id']: item['quantity'] for item in booking['actual_inputs']}
    for entry in booking['request']['inputs']:
        if entry['material_id'] != target and (entry['quantity']['value'] is None
                or actual.get(entry['material_id']) != entry['quantity']):
            return False
    return _retained_role_conformant(state, role_id, target, visiting)


def _source_preparation_conformant(state, role_id, identity, visiting):
    """Check prospective provenance and preparation independently of live stock.

    Exhausting a correctly prepared source does not invalidate its historical
    recipe. Unknown or mismatched component observations never qualify it.
    """
    definition, unused = _feature(state)
    roles = definition['recipe_profile']['roles']
    require(role_id in roles, 'Unknown recipe reagent role')
    role = roles[role_id]
    if role.get('mode') not in {'issued', 'prepared'} or role.get('material_id') is None:
        return False
    visiting = set(visiting)
    require(role_id not in visiting, 'Cyclic prospective reagent preparation')
    visiting.add(role_id)
    if role.get('evidence_ref') is None:
        return False
    if role['mode'] == 'issued':
        if role.get('lot_ref') is None:
            return False
        if (definition['recipe_protocol']['reagent_roles'][role_id].get('kind') == 'working'
                and role.get('preparation_ref') is None):
            return False
        original = role['material_id']
        initial = next((item for item in definition['initial_materials'] if item['id'] == original), None)
        require(initial is not None and initial['kind'] == 'reagent'
                and initial['vessel_id'] == role['vessel_id'], 'Issued recipe provenance differs from its immutable declaration')
        material = state['inventory']['materials'].get(original)
        require(material is not None and material['kind'] == 'reagent' and not material['parents'],
                'Issued reagent role was relabeled')
        return _retained_role_conformant(state, role_id, identity, visiting)
    require(identity == role['material_id'], 'Prepared mixture snapshot differs from its allocated identity')
    if identity not in state['inventory']['materials'] or not _preparation_ready(state, identity):
        return False
    unused_role, unused_material, booking = _prepared_introduction(state, identity)
    components = state['manual']['actions'][booking['id']].get('component_materials',
        definition['recipe_protective_bindings']['prepared'][identity]['components'])
    return all(_source_preparation_conformant(state, component, components[component], visiting)
               for component in role['components'])


def preparation_conformant(state, role_id):
    """Historical recipe conformance, including the actual component snapshots.

    Exhaustion does not erase a valid preparation. Conversely, a retained stock
    fraction with contradictory wash consumption never becomes qualified by a
    subsequent correctly proportioned mixture.
    """
    definition, unused = _feature(state)
    require(role_id in definition['recipe_profile']['roles'], 'Unknown recipe reagent role')
    role = definition['recipe_profile']['roles'][role_id]
    if role.get('mode') not in {'issued', 'prepared'} or role.get('material_id') is None:
        return False
    identity = resolve_role_material(state, role_id)
    return _source_preparation_conformant(state, role_id, identity, set())


def reagent_ready(state, role_id):
    """Whether the pinned material's observed preparation supports a new dose.

    This uses canonical ledger observations; it never writes or estimates a
    yield, concentration, unmeasured component or remaining amount.
    """
    import material_ledger
    definition, feature = _feature(state)
    roles = definition['recipe_profile']['roles']
    require(role_id in roles, 'Unknown recipe reagent role')
    role = roles[role_id]
    if role.get('mode') not in {'issued', 'prepared'} or role.get('material_id') is None:
        return False
    if not preparation_conformant(state, role_id):
        return False
    identity = resolve_role_material(state, role_id)
    material = state['inventory']['materials'].get(identity)
    if role.get('mode') not in {'issued', 'prepared'} or material is None:
        return False
    if material['vessel_id'] != role.get('vessel_id') or material['disposition'] in {'consumed', 'discarded', 'quarantined'}:
        return False
    balance = material_ledger.remaining(state, identity)
    if balance['value'] is None or balance['value'] <= 0 or balance['unit'] != 'uL':
        return False
    if role['mode'] == 'issued':
        if identity == role['material_id']:
            require(material['kind'] == 'reagent' and material['role'] == 'issued_reagent' and not material['parents'],
                    'Issued reagent role was relabeled')
        return True
    prepared_role, material, booking = _prepared_introduction(state, identity)
    require(prepared_role == role_id, 'Prepared role identity mismatch')
    # Correctly consumed components need no positive balance after preparation.
    return _preparation_ready(state, identity)


def protected_ready(state, vessel_id):
    definition, feature = _feature(state)
    material_id = definition['protective_stop_bindings'].get(vessel_id)
    require(material_id is not None, 'Unknown protected reaction vessel')
    matches = [name for name, role in definition['recipe_profile']['roles'].items() if role.get('material_id') == material_id]
    if not matches:
        validate_protective_source(state, vessel_id, material_id)
        import material_ledger
        material = state['inventory']['materials'][material_id]
        balance = material_ledger.remaining(state, material_id)
        return material['vessel_id'] is not None and material['disposition'] not in {'consumed', 'discarded', 'quarantined'} and balance['value'] is not None and balance['value'] > 0
    require(len(matches) == 1, 'Ambiguous protective reagent role')
    return reagent_ready(state, matches[0])


def can_retry_preparation_output(state, previous, output, request):
    """A proved nonperformed attempt did not physically introduce its output.

    The immutable future identity stays allocated to this run. Only the exact
    same prepared-reagent declaration can be attempted after explicit absence
    evidence; arbitrary output IDs and unresolved attempts remain reserved.
    """
    definition, feature = _feature(state)
    identity = output.get('material_id')
    if identity not in feature['prepared'] or identity in state['inventory']['materials']:
        return False
    unused, unused_feature, declaration, unused_role = _prepared_declaration(state, identity)
    role_id = declaration['role_id']
    expected = {'material_id': identity, 'kind': 'intermediate',
                'vessel_id': declaration['vessel_id'], 'role': 'working_reagent'}
    action = state.get('manual', {}).get('actions', {}).get(previous['id'], {})
    return (previous['outcome'] == 'not_performed' and isinstance(previous.get('nonperformance'), dict)
        and action.get('operation') == 'recipe_preparation' and action.get('recipe_role') == role_id
        and output == expected and previous['request']['kind'] == request['kind'] == 'transformation'
        and previous['request']['purpose'] == request['purpose'] == 'recipe_preparation:' + role_id
        and previous['request']['outputs'] == request['outputs'] == [expected])


def _resolve_prepared_output(state, actor_id, intent_id, quantity, reason):
    import material_ledger
    from manual_workflow import ObservationError
    _feature(state)
    booking = state['bookings'].get(intent_id)
    require(isinstance(booking, dict) and booking['outcome'] == 'performed',
            'A performed canonical preparation with an unknown observed yield is required')
    require(len(booking['request']['outputs']) == 1, 'One prepared mixture output required')
    identity = booking['request']['outputs'][0]['material_id']
    unused_role, material, introduced = _prepared_introduction(state, identity)
    require(introduced['id'] == intent_id, 'Quantity evidence belongs to a different preparation')
    observed = material_ledger.quantity(quantity, units={'uL'}, zero=True)
    require(observed['value'] is not None, 'A resolved working mixture yield must be explicitly known')
    import material_evidence
    resolution = {'material_id': identity, 'quantity': observed,
                  'receipt': material_evidence.receipt(state, actor_id, reason),
                  'original_quantity': {'value': None, 'unit': 'uL'}}
    if booking.get('output_quantity_resolution') is not None:
        require(booking['output_quantity_resolution'] == resolution, 'Conflicting prepared output quantity reconciliation')
        return False
    require(material['initial_quantity'] == {'value': None, 'unit': 'uL'},
            'Known preparation yields cannot be rewritten as a reconciliation')
    require(not any(candidate['outcome'] in {'intent', 'unknown'} and
                    any(item['material_id'] == identity for item in candidate['request']['inputs'])
                    for candidate in state['bookings'].values()),
            'Resolve outstanding mixture uses before reconciling its output quantity')
    material['initial_quantity'] = copy.deepcopy(observed)
    booking['actual_outputs'] = [{'material_id': identity, 'quantity': copy.deepcopy(observed)}]
    booking['output_quantity_resolution'] = resolution
    balance = material_ledger.remaining(state, identity)
    if balance['value'] is not None and balance['value'] < -1e-9:
        raise ObservationError('Observed preparation yield is below its already confirmed consumption')
    material_ledger.audit(state)


def resolve_prepared_output(state, actor_id, intent_id, quantity, reason):
    """Attach later observed yield evidence atomically without another debit."""
    import material_ledger
    return material_ledger.atomic(_resolve_prepared_output)(state, actor_id, intent_id, quantity, reason)
