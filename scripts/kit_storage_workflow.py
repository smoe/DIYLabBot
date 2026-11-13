"""One durable synthetic storage fixture; no stock, quantities, motion or hardware.

The geometry provider supplies identities and the route once. Each explicit
fixture_id names a separate synthetic test world, never a real inventory import.
Only the explicit demo helper fabricates observations; transitions require input.
"""
import copy
from pathlib import Path
import re
import uuid

import kit_storage_model as model
from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import ObservationError, resolve_store, text

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.kit-storage-fixture/1'
REPORT_FORMAT = 'solidcraftbot.kit-storage-report/1'
RUNTIME = ('scripts/kit_storage_workflow.py', 'scripts/manual_tasks.py',
           'scripts/manual_workflow.py', 'scripts/run_kit_storage.py')
KINDS = {'pickup': 'ready', 'setdown': 'captured', 'release': 'supported'}


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', value):
        raise TaskError('Explicit 1-96 character ASCII '+label+' required')
    return value


def run_id_for(fixture_id):
    """Canonical identity: init can never reset an existing fixture world."""
    return 'SYN.Storage.'+digest(identifier(fixture_id, 'fixture id').encode())


def _require(condition, message):
    if not condition:
        raise TaskError(message)


def _contents(definition):
    return [{key: item[key] for key in ('id', 'slot_id', 'material_id')}
            for item in definition['carrier']['symbolic_contents']]


def load_definition(source=None):
    spec = None if source is None else model.load(source)
    definition = copy.deepcopy(model.runtime_definition(spec))
    _require(isinstance(definition, dict), 'Storage definition required')
    carrier = definition['carrier']; locations = definition['locations']
    identifier(carrier['id'], 'carrier id')
    _require(set(locations) == {'source', 'handover'}, 'Two named storage places required')
    places = [identifier(locations[key]['id'], key+' place id') for key in ('source', 'handover')]
    _require(len(set(places)) == 2 and carrier['id'] not in places, 'Distinct carrier and places required')
    _require(definition['route'] == [places[0], places[1], places[0]], 'One supported out-and-back route required')
    contents = _contents(definition)
    _require(contents and len({item['id'] for item in contents}) == len(contents)
             and len({item['slot_id'] for item in contents}) == len(contents), 'Unique symbolic content identities and slots required')
    for item in contents:
        for key, value in item.items():
            identifier(value, 'content '+key)
    pins = definition['source_files_sha256']
    _require(isinstance(pins, dict) and pins, 'Storage source pins required')
    for name in RUNTIME:
        current = digest((ROOT/name).read_bytes())
        if name in pins:
            _require(pins[name] == current, 'Conflicting runtime source pin: '+name)
        pins[name] = current
    definition['runtime_source_files'] = list(RUNTIME)
    verify_sources(definition)
    return definition


def verify_sources(definition):
    for name, expected in definition['source_files_sha256'].items():
        path = (ROOT/name).resolve()
        if (not path.is_relative_to(ROOT) or not path.is_file()
                or digest(path.read_bytes()) != expected):
            raise TaskError('Pinned storage source changed; no implicit migration: '+name)


def resource_ids(fixture_id, definition):
    prefix = 'synthetic-storage:'+digest(fixture_id.encode())+':'
    names = ['carrier:'+definition['carrier']['id'], 'gripper:S01.AbstractGripper']
    names += ['content:'+item['id'] for item in _contents(definition)]
    names += ['place:'+item['id'] for item in definition['locations'].values()]
    return sorted(prefix+name for name in names)


def _arrangement(definition, phase, leg):
    route = definition['route']
    if phase in {'initial', 'ready'}:
        return {'location': route[leg], 'supported': True, 'gripper_holds': False}
    if phase == 'captured':
        return {'location': 'S01.AbstractGripper', 'supported': False, 'gripper_holds': True}
    if phase == 'supported':
        return {'location': route[leg+1], 'supported': True, 'gripper_holds': True}
    if phase == 'returned':
        return {'location': route[0], 'supported': True, 'gripper_holds': False}
    raise TaskError('Unknown storage phase')


def _scene(definition, arrangement):
    carrier_id = definition['carrier']['id']
    return {'carrier_id': carrier_id, 'contents': _contents(definition),
            'location': arrangement['location'], 'supported': arrangement['supported'],
            'places': {place['id']: carrier_id if arrangement['location'] == place['id'] else None
                       for place in definition['locations'].values()},
            'gripper': {'id': 'S01.AbstractGripper',
                        'carrier_id': carrier_id if arrangement['gripper_holds'] else None,
                        'empty': not arrangement['gripper_holds']}}


def synthetic_observation(state, observation_id, *, phase=None, leg=None):
    """Explicit demo/test input generator, never called to confirm a transition."""
    return {'fixture_id': state['fixture_id'], 'observation_id': observation_id, 'evidence': 'synthetic_observation',
            **_scene(state['definition'], _arrangement(state['definition'], phase or state['phase'],
                                                       state['leg'] if leg is None else leg))}


def _observe(state, observation, arrangement):
    expected_keys = {'fixture_id', 'observation_id', 'evidence', 'carrier_id', 'contents', 'location', 'supported', 'places', 'gripper'}
    if not isinstance(observation, dict) or set(observation) != expected_keys:
        raise ObservationError('Explicit whole-fixture synthetic observation required')
    identity = identifier(observation['observation_id'], 'observation id')
    if (observation['fixture_id'] != state['fixture_id']
            or observation['evidence'] != 'synthetic_observation' or identity in state['observations']):
        raise ObservationError('Fresh explicitly synthetic observation required')
    contents = observation['contents']
    if (not isinstance(contents, list) or any(not isinstance(item, dict)
            or set(item) != {'id', 'slot_id', 'material_id'} for item in contents)):
        raise ObservationError('Complete carrier/content/slot/material observations required')
    expected = _scene(state['definition'], arrangement)
    actual = {key: value for key, value in observation.items() if key not in {'fixture_id', 'observation_id', 'evidence'}}
    if (type(actual['supported']) is not bool or not isinstance(actual['gripper'], dict)
            or type(actual['gripper'].get('empty')) is not bool):
        raise ObservationError('Explicit support and gripper-empty booleans required')
    try:
        actual['contents'] = sorted(contents, key=lambda item: item['id'])
        expected['contents'] = sorted(expected['contents'], key=lambda item: item['id'])
        same = encoded(actual) == encoded(expected)
    except (TypeError, ValueError):
        same = False
    if not same:
        raise ObservationError('Carrier, full contents, occupancy, support or gripper observation mismatch')
    state['observations'].append(identity)


class StorageRunner:
    """Bounded serial fixture lifecycle using the existing durable journal."""
    def __init__(self, journal, fixture_id, session):
        self.journal, self.fixture_id, self.session = journal, fixture_id, session
        self.run_id = run_id_for(fixture_id)
        self._audit_state(self.journal.state(self.run_id)[0])

    @classmethod
    def init(cls, journal, fixture_id, source=None):
        definition = load_definition(source)
        session = uuid.uuid4().hex
        state = {'format': FORMAT, 'mode': 'synthetic_only', 'fixture_id': fixture_id,
                 'run_id': run_id_for(fixture_id), 'definition': definition,
                 'status': 'created', 'session': session, 'phase': 'initial', 'leg': 0,
                 'resources': [], 'pending': None, 'operations': [], 'observations': [],
                 'recovery_required': None, 'initial_confirmed': False}
        journal.create(state['run_id'], state, immutable_definition=True)
        return cls(journal, fixture_id, session)

    @classmethod
    def open(cls, journal, fixture_id, *, resume=False):
        run_id = run_id_for(fixture_id)
        state, revision = journal.state(run_id)
        cls._audit_state(state)
        verify_sources(state['definition'])
        if state['status'] == 'completed':
            return cls(journal, fixture_id, None)
        _require(resume is True, 'Explicit resume and reconciliation required')
        session = uuid.uuid4().hex
        state['session'] = session
        if state['initial_confirmed'] or state['pending']:
            state['status'] = 'held'
            state['recovery_required'] = state['recovery_required'] or 'session_restarted'
        journal.append(run_id, revision, 'session_opened', {'explicit_resume': True}, state)
        return cls(journal, fixture_id, session)

    @staticmethod
    def _audit_state(state):
        _require(state.get('format') == FORMAT and state.get('mode') == 'synthetic_only', 'Wrong storage fixture format')
        _require(state['run_id'] == run_id_for(state['fixture_id']), 'Fixture/run identity mismatch')
        phase, leg, status = state['phase'], state['leg'], state['status']
        _require(type(leg) is int and leg in {0, 1, 2}, 'Invalid storage route position')
        _require(phase in {'initial', 'ready', 'captured', 'supported', 'returned'}, 'Invalid storage phase')
        _require((phase == 'returned') == (leg == 2) and (phase != 'initial' or leg == 0), 'Storage phase/route mismatch')
        _require(status in {'created', 'active', 'held', 'completed'}, 'Invalid storage status')
        _require(type(state['initial_confirmed']) is bool and state['initial_confirmed'] == (phase != 'initial'), 'Initial confirmation mismatch')
        expected = resource_ids(state['fixture_id'], state['definition']) if state['initial_confirmed'] and status != 'completed' else []
        _require(state['resources'] == expected, 'Storage reservations differ from the fixture contract')
        _require((status != 'created' or phase == 'initial') and
                 (status != 'active' or state['initial_confirmed']) and
                 (status != 'completed' or (phase == 'returned' and state['pending'] is None and state['session'] is None)), 'Terminal/initial storage state mismatch')
        _require((status == 'held') == bool(state['recovery_required']), 'Held storage state requires reconciliation')
        _require(len(set(state['observations'])) == len(state['observations']), 'Duplicate storage observation')
        for observation_id in state['observations']:
            identifier(observation_id, 'stored observation id')
        ids = [item['operation_id'] for item in state['operations']]
        _require(len(set(ids)) == len(ids), 'Duplicate storage operation')
        sequence = [(index, kind) for index in range(len(state['definition']['route'])-1)
                    for kind in ('pickup', 'setdown', 'release')]
        _require(len(sequence) == 6, 'Two-leg source-derived storage route required')
        cursor = 0; receipts = []
        for operation in state['operations']:
            _require(set(operation) == {'operation_id', 'kind', 'leg', 'outcome', 'actor_id', 'observation_id'}, 'Incomplete storage receipt')
            identifier(operation['operation_id'], 'stored operation id')
            text(operation['actor_id'], 'receipt actor id')
            _require(cursor < len(sequence) and (operation['leg'], operation['kind']) == sequence[cursor], 'Storage receipt order differs from the route')
            _require(operation['outcome'] in {'performed', 'not_performed'}
                     and operation['observation_id'] in state['observations'], 'Storage receipt has no valid observation')
            receipts.append(operation['observation_id'])
            if operation['outcome'] == 'performed':
                cursor += 1
        _require(len(set(receipts)) == len(receipts), 'One observation cannot confirm two storage operations')
        expected_cursor = (6 if phase == 'returned' else 0 if phase == 'initial'
                           else 3*leg+{'ready': 0, 'captured': 1, 'supported': 2}[phase])
        _require(cursor == expected_cursor, 'Confirmed storage receipts do not support the phase')
        if state['pending'] is not None:
            pending = state['pending']
            _require(pending['kind'] in KINDS and KINDS[pending['kind']] == phase
                     and pending['leg'] == leg and pending['operation_id'] not in ids, 'Invalid pending storage intent')

    @property
    def state(self):
        state, _ = self.journal.get_current(self.run_id)
        self._audit_state(state)
        return state

    def _transition(self, kind, actor_id, update, payload=None, *, recovery=False):
        text(actor_id, 'synthetic actor id')
        before, revision = self.journal.get_current(self.run_id)
        self._audit_state(before); verify_sources(before['definition'])
        _require(self.session is not None and before['session'] == self.session, 'Stale storage session; explicitly resume')
        _require(before['status'] != 'completed', 'Storage fixture already completed; init cannot reset it')
        _require(recovery or before['status'] != 'held', 'Whole-fixture reconciliation required')
        state = copy.deepcopy(before)
        proof = {'actor_id': actor_id, 'evidence': 'synthetic_input', **(payload or {})}
        try:
            update(state)
        except ObservationError as error:
            before['status'] = 'held'; before['recovery_required'] = before['recovery_required'] or 'observation_mismatch'
            self.journal.append(self.run_id, revision, 'observation_rejected',
                                {**proof, 'command': kind, 'error': str(error)}, before)
            raise
        self._audit_state(state); verify_sources(state['definition'])
        self.journal.append(self.run_id, revision, kind, proof, state)
        return state

    def accept_initial(self, actor_id, observation):
        def update(state):
            _require(state['phase'] == 'initial' and not state['initial_confirmed'], 'Initial fixture already confirmed')
            _observe(state, observation, _arrangement(state['definition'], 'initial', 0))
            state.update(initial_confirmed=True, phase='ready', status='active',
                         resources=resource_ids(self.fixture_id, state['definition']))
        return self._transition('initial_observed', actor_id, update, {'observation': observation})

    def intent(self, actor_id, operation_id, kind):
        identifier(operation_id, 'operation id')
        _require(kind in KINDS, 'Unknown storage operation')
        def update(state):
            _require(state['phase'] == KINDS[kind] and state['leg'] < 2 and state['pending'] is None, 'Storage operation out of sequence')
            _require(operation_id not in {item['operation_id'] for item in state['operations']}, 'Operation id already used')
            state['pending'] = {'operation_id': operation_id, 'kind': kind, 'leg': state['leg']}
        return self._transition(kind+'_intent', actor_id, update, {'operation_id': operation_id})

    @staticmethod
    def _after(state, kind):
        phase, leg = {'pickup': 'captured', 'setdown': 'supported'}.get(kind), state['leg']
        if kind == 'release':
            leg += 1; phase = 'returned' if leg == 2 else 'ready'
        return phase, leg

    @staticmethod
    def _resolve(state, actor_id, operation_id, observation, performed):
        pending = state['pending']
        _require(pending is not None and pending['operation_id'] == operation_id, 'No matching pending storage intent')
        phase, leg = StorageRunner._after(state, pending['kind']) if performed else (state['phase'], state['leg'])
        _observe(state, observation, _arrangement(state['definition'], phase, leg))
        state['operations'].append({**pending, 'outcome': 'performed' if performed else 'not_performed',
                                    'actor_id': actor_id, 'observation_id': observation['observation_id']})
        state.update(phase=phase, leg=leg, pending=None)

    def confirm(self, actor_id, operation_id, observation):
        def update(state):
            self._resolve(state, actor_id, operation_id, observation, True)
        return self._transition('operation_confirmed', actor_id, update,
                                {'operation_id': operation_id, 'observation': observation})

    def reconcile(self, actor_id, observation, *, resolution, operation_id=None):
        _require(resolution in {'performed', 'not_performed', 'unchanged'}, 'Explicit storage resolution required')
        def update(state):
            _require(state['status'] == 'held', 'Storage fixture is not held')
            if state['pending'] is not None:
                _require(resolution != 'unchanged', 'Pending intent needs performed/not_performed resolution')
                self._resolve(state, actor_id, operation_id, observation, resolution == 'performed')
            else:
                _require(resolution == 'unchanged' and operation_id is None, 'No pending intent to resolve')
                _observe(state, observation, _arrangement(state['definition'], state['phase'], state['leg']))
            state.update(status='active' if state['initial_confirmed'] else 'created', recovery_required=None)
        return self._transition('fixture_reconciled', actor_id, update,
                                {'operation_id': operation_id, 'resolution': resolution, 'observation': observation}, recovery=True)

    def complete(self, actor_id, observation):
        def update(state):
            _require(state['phase'] == 'returned' and state['pending'] is None, 'Confirmed full return required')
            _observe(state, observation, _arrangement(state['definition'], 'returned', 2))
            state.update(status='completed', resources=[], session=None)
        result = self._transition('fixture_completed', actor_id, update, {'observation': observation})
        self.session = None
        return result

    def close(self):
        state, revision = self.journal.get_current(self.run_id)
        if self.session is not None and state['session'] == self.session:
            self._audit_state(state); verify_sources(state['definition'])
            state['session'] = None
            if state['initial_confirmed']:
                state.update(status='held', recovery_required=state['recovery_required'] or 'session_closed')
            self.journal.append(self.run_id, revision, 'session_closed', {}, state)
        self.session = None

    def report(self):
        trace = self.journal.history(self.run_id)
        for event in trace:
            self._audit_state(event['state'])
        state = trace[-1]['state']; verify_sources(state['definition'])
        owners = self.journal.owners()
        _require({key for key, owner in owners.items() if owner == self.run_id} == set(state['resources']), 'Journal resource ownership mismatch')
        scene = _scene(state['definition'], _arrangement(state['definition'], state['phase'], state['leg']))
        return {'format': REPORT_FORMAT, 'fixture_id': self.fixture_id, 'run_id': self.run_id,
                'mode': 'synthetic_only', 'status': state['status'], 'passed': state['status'] == 'completed',
                'phase': state['phase'], 'leg': state['leg'], 'scene': scene,
                'scene_basis': 'last_confirmed_synthetic_observation' if state['initial_confirmed'] else 'unobserved_fixture_declaration',
                'location_uncertain': bool(state['pending'] or state['recovery_required'] or not state['initial_confirmed']),
                'pending': state['pending'], 'operations': state['operations'], 'resources': state['resources'],
                'recovery_required': state['recovery_required'], 'initial_confirmed': state['initial_confirmed'],
                'route': state['definition']['route'], 'source_files_sha256': state['definition']['source_files_sha256'],
                'journal_head_sha256': trace[-1]['sha256'], 'trace': trace,
                'evidence': 'explicit synthetic fixture observations; no scans or physical execution',
                'cross_run_inventory': False, 'quantity_ledger': False, 'global_stock_fencing': False,
                'robot_motion_executed': False, 'hardware_executed': False, 'network_executed': False,
                'grasp_qualified': False, 'load_qualified': False, 'safety_function_qualified': False}


def run_demo(runner):
    """Generate positive observations only for this explicitly requested demo."""
    actor = 'SYN.Storage.Operator'
    runner.accept_initial(actor, synthetic_observation(runner.state, 'Initial'))
    for leg in range(2):
        for kind in ('pickup', 'setdown', 'release'):
            operation = 'Leg'+str(leg+1)+'.'+kind
            runner.intent(actor, operation, kind)
            phase, next_leg = runner._after(runner.state, kind)
            runner.confirm(actor, operation, synthetic_observation(runner.state, operation+'.Observed', phase=phase, leg=next_leg))
    runner.complete(actor, synthetic_observation(runner.state, 'Returned'))
    return runner.report()
