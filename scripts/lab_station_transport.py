"""Durable TR01 task transfers in one explicit synthetic world, without drive I/O.

Cargo identities are projections of the extraction source, never a second stock
ledger. Only demo_observation fabricates observations, outside the transitions.
"""
import copy
import json
from pathlib import Path
import re
import uuid

from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import ObservationError, resolve_store, text
import sample_transport_model as transporter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/lab-station-transport.protocol.json'
FORMAT = 'solidcraftbot.lab-station-transfer-state/1'
PHASES = {'load': 'at_source', 'travel': 'loaded', 'unload': 'arrived'}


def require(condition, message):
    if not condition:
        raise TaskError(message)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', value),
            'Explicit 1–96 character ASCII identifier required')
    return value


def verify_sources(definition):
    for name, expected in definition['source_files_sha256'].items():
        path = (ROOT/name).resolve()
        require(path.is_relative_to(ROOT) and path.is_file()
                and digest(path.read_bytes()) == expected, 'Source changed; no implicit migration: '+name)


def load_definition():
    definition = json.loads(SOURCE.read_text())
    require(definition['format'] == 'solidcraftbot.lab-station-transport/1'
            and definition['mode'] == 'synthetic_only', 'Synthetic station transfer source required')
    pins = {str(SOURCE.relative_to(ROOT)): digest(SOURCE.read_bytes())}
    # Recursively pin referenced model contracts, including nested compositions.
    def references(value):
        if isinstance(value, dict):
            if 'source' in value and 'source_sha256' in value:
                path = (ROOT/value['source']).resolve()
                require(path.is_relative_to(ROOT) and path.is_file(), 'Repository source required')
                require(digest(path.read_bytes()) == value['source_sha256'], 'Reference pin mismatch: '+value['source'])
                if value['source'] not in pins:
                    pins[value['source']] = value['source_sha256']
                    references(json.loads(path.read_text()))
            for item in value.values():
                references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)
    references(definition['sources'])
    for name in ('model/lab-station-transport.schema.json', 'scripts/lab_station_transport.py', 'scripts/run_lab_station_transport.py',
                 'scripts/manual_tasks.py', 'scripts/manual_workflow.py', 'scripts/sample_transport_model.py',
                 'scripts/robot_spec.py'):
        pins[name] = digest((ROOT/name).read_bytes())
    definition['source_files_sha256'] = pins
    vehicle = definition['vehicle']
    tr = transporter.load(ROOT/definition['sources']['transporter']['source'])
    variants = {item['id']: item for item in tr['variants']}
    require(vehicle['variant'] in variants and vehicle['load_frame'] == tr['handoff_requirements']['deck_frame_id'],
            'Unknown TR01 variant or load frame')
    variant = variants[vehicle['variant']]
    bay = vehicle['cassette_bay']
    require(type(bay) is int and 1 <= bay <= len(variant['bays']) and variant['bays'][bay-1] == 'tube24',
            'Tube cassette bay required')
    geometry = transporter.expanded(tr, transporter.parameters(tr), variant)
    places = sorted(body['id'] for body in geometry['bodies']
                    if body['role'] == 'closed_tube_reference_envelope' and body['id'].startswith('B'+str(bay)+'_'))
    require(len(places) == 24, 'Source-derived tube cassette places required')
    reference = definition['cargo_reference']
    extraction = json.loads((ROOT/definition['sources'][reference['source_key']]['source']).read_text())
    pair = extraction['sample_pairs'][reference['sample_pair_index']]
    product = reference['product']
    process = pair['processes'][product]
    definition['cargo'] = {'sample_id': pair[product+'_product_id'], 'vessel_id': process['items']['elution_vessel'],
                           'origin': process['output_location'], 'cassette_place_id': places[0]}
    route = definition['demo_route']
    stations = definition['stations']
    require(len(route) >= 2 and route[0] == route[-1] and set(route) == set(stations)
            and all(a != b for a, b in zip(route, route[1:])), 'Connected out-and-back station route required')
    for station, item in stations.items():
        identifier(station)
        require(item['source_key'] in definition['sources']
                and item['handoff'] == 'synthetic_operator_confirmation'
                and item['registered_parking_pose'] == {'source_key':'motion','station_id':station},
                'Source-bound geometric parking reference required')
    geometry = json.loads((ROOT/definition['sources']['motion']['source']).read_text())
    require(set(geometry['stations']) == set(stations), 'Geometric station identities differ')
    require([(r['from'],r['to']) for r in geometry['routes']] == list(zip(route,route[1:])),
            'Task route and geometric route differ')
    verify_sources(definition)
    return definition


def run_id_for(world_id):
    return 'SYN.StationTransfers.'+digest(identifier(world_id).encode())


def resources(world_id, definition):
    # One declared synthetic world shares its vehicle/cargo/stations across sessions.
    prefix = 'synthetic-station-transfer:'+identifier(world_id)+':'
    return sorted(prefix+name for name in ['vehicle:'+definition['vehicle']['id'],
                  'vessel:'+definition['cargo']['vessel_id'],
                  *['station:'+station for station in definition['stations']]])


def arrangement(state, phase=None, leg=None):
    phase = phase or state['phase']
    leg = state['leg'] if leg is None else leg
    definition = state['definition']; route = definition['demo_route']
    station = route[leg] if phase in {'at_source', 'loaded', 'completed'} else route[leg+1]
    on_vehicle = phase in {'loaded', 'arrived'}
    return {'vehicle_at': station, 'cargo_at': definition['vehicle']['load_frame'] if on_vehicle else station,
            'parking_reference': definition['stations'][station]['registered_parking_pose'],
            'cargo': definition['cargo'], 'cargo_on_vehicle': on_vehicle,
            'stationary': True, 'holding_confirmed': True,
            'closure_and_retention_confirmed': True, 'local_registration_confirmed': True,
            'handoff_area_clear': True, 'station_release_confirmed': True,
            'receiving_station_ready': True}


def demo_observation(state, observation_id, *, phase=None, leg=None):
    """Explicit synthetic demo input; no state transition calls this helper."""
    return {'world_id': state['world_id'], 'observation_id': observation_id,
            'evidence': 'synthetic_operator_confirmation', **arrangement(state, phase, leg)}


def observe(state, observation, phase, leg):
    if not isinstance(observation, dict):
        raise ObservationError('Complete observation required')
    expected = {'world_id': state['world_id'], 'observation_id': observation.get('observation_id'),
                'evidence': 'synthetic_operator_confirmation', **arrangement(state, phase, leg)}
    identity = observation.get('observation_id')
    if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', identity)
            or identity in state['observations'] or encoded(observation) != encoded(expected)):
        raise ObservationError('Fresh complete cargo, origin, retention, holding and station observation required')
    state['observations'].append(identity)


class TransportRunner:
    def __init__(self, journal, world_id, session):
        self.journal, self.world_id, self.session = journal, world_id, session
        self.run_id = run_id_for(world_id)
        self.audit(journal.state(self.run_id)[0])

    @classmethod
    def init(cls, journal, world_id):
        definition = load_definition(); session = uuid.uuid4().hex
        state = {'format': FORMAT, 'mode': 'synthetic_only', 'run_id': run_id_for(world_id),
                 'world_id': world_id, 'definition': definition, 'session': session,
                 'status': 'created', 'phase': 'at_source', 'leg': 0, 'accepted': False,
                 'pending': None, 'operations': [], 'observations': [], 'resources': [], 'hold_reason': None}
        journal.create(state['run_id'], state, immutable_definition=True)
        return cls(journal, world_id, session)

    @classmethod
    def open(cls, journal, world_id, *, resume=False):
        state, revision = journal.state(run_id_for(world_id)); cls.audit(state)
        verify_sources(state['definition'])
        if state['status'] == 'completed':
            return cls(journal, world_id, None)
        require(resume is True, 'Explicit resume required')
        state['session'] = uuid.uuid4().hex
        state.update(status='held', hold_reason=state['hold_reason'] or 'session_restarted')
        journal.append(state['run_id'], revision, 'session_opened', {'resume': True}, state)
        return cls(journal, world_id, state['session'])

    @staticmethod
    def audit(state):
        require(state['format'] == FORMAT and state['mode'] == 'synthetic_only'
                and state['run_id'] == run_id_for(state['world_id']), 'Wrong transfer world')
        end = len(state['definition']['demo_route'])-1
        leg, phase = state['leg'], state['phase']
        require(type(leg) is int and 0 <= leg <= end and phase in {*PHASES.values(), 'completed'}, 'Invalid route phase')
        require((phase == 'completed') == (leg == end), 'Route completion mismatch')
        require(state['status'] in {'created', 'active', 'held', 'completed'}
                and (state['status'] == 'held') == bool(state['hold_reason']), 'Invalid hold state')
        require((state['status'] == 'completed') == (phase == 'completed'), 'Terminal state mismatch')
        require(state['accepted'] or (leg == 0 and phase == 'at_source' and not state['operations']), 'Unobserved initial state')
        expected = resources(state['world_id'], state['definition']) if state['accepted'] and phase != 'completed' else []
        require(state['resources'] == expected, 'Resource reservation mismatch')
        require(len(set(state['observations'])) == len(state['observations']), 'Reused observation')
        cursor = 0; ids = set(); receipts = set()
        for op in state['operations']:
            require(op['operation_id'] not in ids and op['observation_id'] in state['observations']
                    and op['observation_id'] not in receipts, 'Invalid or reused receipt')
            require((op['leg'], op['kind']) == (cursor//3, ('load', 'travel', 'unload')[cursor%3]), 'Receipt order mismatch')
            require(op['outcome'] in {'performed', 'not_performed'}, 'Unknown operation outcome')
            ids.add(op['operation_id']); receipts.add(op['observation_id'])
            cursor += op['outcome'] == 'performed'
        require(cursor == (3*end if phase == 'completed' else 3*leg+{'at_source':0, 'loaded':1, 'arrived':2}[phase]),
                'Phase unsupported by receipts')
        if state['pending']:
            pending = state['pending']
            require(state['accepted'] and phase != 'completed' and pending['kind'] in PHASES
                    and PHASES[pending['kind']] == phase and pending['leg'] == leg
                    and pending['operation_id'] not in ids, 'Invalid pending intent')
        if phase == 'completed':
            require(state['pending'] is None and state['session'] is None, 'Terminal pending operation')

    @property
    def state(self):
        state, _ = self.journal.get_current(self.run_id); self.audit(state)
        return state

    def transition(self, event, actor, change, payload=None, *, recovery=False):
        text(actor, 'actor')
        before, revision = self.journal.get_current(self.run_id)
        self.audit(before); verify_sources(before['definition'])
        require(self.session is not None and before['session'] == self.session, 'Stale session; explicitly resume')
        require(before['status'] != 'completed' and (recovery or before['status'] != 'held'), 'Held or completed transfer')
        after = copy.deepcopy(before)
        proof = {'actor_id': actor, **(payload or {})}
        try:
            change(after)
        except ObservationError as error:
            before.update(status='held', hold_reason=before['hold_reason'] or 'observation_mismatch')
            self.journal.append(self.run_id, revision, 'observation_rejected', {**proof, 'error':str(error)}, before)
            raise
        self.audit(after); verify_sources(after['definition'])
        self.journal.append(self.run_id, revision, event, proof, after)
        return after

    def accept(self, actor, observation):
        def change(state):
            require(not state['accepted'], 'Cargo already accepted')
            observe(state, observation, state['phase'], state['leg'])
            state.update(accepted=True, status='active', resources=resources(self.world_id, state['definition']))
        return self.transition('cargo_accepted', actor, change, {'observation':observation})

    def intent(self, actor, operation_id, kind):
        identifier(operation_id)
        require(kind in PHASES, 'Unsupported transport operation')
        def change(state):
            require(state['accepted'] and state['phase'] == PHASES[kind] and state['pending'] is None, 'Operation out of sequence')
            require(operation_id not in {op['operation_id'] for op in state['operations']}, 'Operation already used')
            state['pending'] = {'operation_id':operation_id, 'kind':kind, 'leg':state['leg']}
        return self.transition(kind+'_intent', actor, change, {'operation_id':operation_id})

    @staticmethod
    def after(state):
        kind = state['pending']['kind']; leg = state['leg']
        if kind == 'unload':
            leg += 1
            return ('completed' if leg == len(state['definition']['demo_route'])-1 else 'at_source'), leg
        return {'load':'loaded', 'travel':'arrived'}[kind], leg

    @staticmethod
    def resolve(state, actor, operation_id, observation, performed):
        pending = state['pending']
        require(pending is not None and pending['operation_id'] == operation_id, 'Matching durable intent required')
        phase, leg = TransportRunner.after(state) if performed else (state['phase'], state['leg'])
        observe(state, observation, phase, leg)
        state['operations'].append({**pending, 'actor_id':actor, 'observation_id':observation['observation_id'],
                                    'outcome':'performed' if performed else 'not_performed'})
        state.update(phase=phase, leg=leg, pending=None)
        if phase == 'completed':
            state.update(status='completed', session=None, resources=[], hold_reason=None)

    def confirm(self, actor, operation_id, observation):
        return self.transition('operation_confirmed', actor,
            lambda state: self.resolve(state, actor, operation_id, observation, True),
            {'operation_id':operation_id, 'observation':observation})

    def reconcile(self, actor, observation, *, resolution, operation_id=None):
        require(resolution in {'performed', 'not_performed', 'unchanged'}, 'Explicit resolution required')
        def change(state):
            require(state['status'] == 'held', 'No hold to reconcile')
            if state['pending']:
                require(resolution != 'unchanged', 'Pending intent needs explicit outcome')
                self.resolve(state, actor, operation_id, observation, resolution == 'performed')
            else:
                require(resolution == 'unchanged' and operation_id is None, 'No pending operation')
                observe(state, observation, state['phase'], state['leg'])
            if state['status'] != 'completed':
                state.update(status='active' if state['accepted'] else 'created', hold_reason=None)
        return self.transition('transfer_reconciled', actor, change,
            {'resolution':resolution, 'operation_id':operation_id, 'observation':observation}, recovery=True)

    def report(self):
        history = self.journal.history(self.run_id)
        for event in history:
            self.audit(event['state'])
        state = history[-1]['state']; verify_sources(state['definition'])
        require({key for key, owner in self.journal.owners().items() if owner == self.run_id}
                == set(state['resources']), 'Reservation ownership mismatch')
        return {'format':'solidcraftbot.lab-station-transfer-report/1', 'world_id':self.world_id,
                'mode':'synthetic_only', 'status':state['status'], 'passed':state['status'] == 'completed',
                'route':state['definition']['demo_route'], 'vehicle':state['definition']['vehicle'],
                'last_confirmed_arrangement':arrangement(state), 'location_uncertain':bool(state['pending'] or state['hold_reason'] or not state['accepted']),
                'pending':state['pending'], 'operations':state['operations'], 'resources':state['resources'],
                'hold_reason':state['hold_reason'], 'source_files_sha256':state['definition']['source_files_sha256'],
                'journal_head_sha256':history[-1]['sha256'], 'event_count':len(history),
                'robot_motion_executed':False, 'hardware_executed':False, 'network_executed':False,
                'instrument_processes_executed':False, 'quantity_ledger':False,
                'limitations':state['definition']['limitations']}


def run_demo(runner):
    actor = 'SYN.Transport.Operator'
    runner.accept(actor, demo_observation(runner.state, 'Initial'))
    for leg in range(len(runner.state['definition']['demo_route'])-1):
        for kind in PHASES:
            operation = 'Leg'+str(leg)+'.'+kind
            runner.intent(actor, operation, kind)
            phase, next_leg = runner.after(runner.state)
            runner.confirm(actor, operation, demo_observation(runner.state, operation+'.Observed', phase=phase, leg=next_leg))
    return runner.report()
