"""Device-operation views over one DNA run's canonical vessel inventory.

Contexts are isolated measurement attempts, not new stores or volume credits.
The coordinator journals their transitions and reserves each sample withdrawal
after the existing device handler creates its intent in that same transition.
"""
from collections.abc import MutableMapping
import copy

from manual_tasks import TaskError, digest, encoded
from manual_workflow import ObservationError, text
from nanodrop_manual import NanoDropOperations
from qubit_manual import QubitOperations
from dna_quantification_ledger import remaining, confirm_withdrawal


def _local_places(definition):
    places = copy.deepcopy(definition['places'])
    for place in places:
        place['geometry_id'] = place.get('geometry_id', place['id'])
        place['id'] = place.get('place_id', place['id'])
    return places


def make_context(root, device, attempt_id, sample_id, source_vessel_id):
    """Bind one existing material to one uniquely named device attempt."""
    if device not in ADAPTERS:
        raise TaskError('Unknown DNA measurement device')
    for value, label in [(attempt_id, 'attempt id'), (sample_id, 'sample id'),
                         (source_vessel_id, 'source vessel id')]:
        text(value, label)
    identity = attempt_id + '.' + device
    if identity in root['contexts']:
        raise TaskError('Device context identity was already used')
    source = root['inventory']['vessels'].get(source_vessel_id)
    if (not source or source.get('sample_id') != sample_id
            or source.get('kind') not in {'original', 'dilution'}):
        raise TaskError('A matching original or prediluted DNA source is required')
    if (source.get('volume_uncertain') is True or any(
            row['source_vessel_id'] == source_vessel_id and row['outcome'] in {'intent', 'unknown'}
            for row in root['bookings'].values())):
        raise TaskError('Resolve the source withdrawal before a new device context')
    home = source.get('home')
    if (not isinstance(home, dict) or home.get('kind') != 'rack'
            or any(not isinstance(home.get(key), str) or not home[key].strip()
                   for key in ('rack_id', 'place_id')) or source.get('location') != home):
        raise TaskError('Observe the DNA source at its declared rack place before measurement')
    definition = copy.deepcopy(root['definition']['devices'][device])
    definition['places'] = _local_places(definition)
    place = next((p for p in definition['places'] if p['id'] == home.get('place_id')), None)
    if place is None:
        raise TaskError('The source home is not a declared rack place')
    profile = definition['profile']
    source_profile = profile['id']
    profile['id'] = identity
    profile['rack']['id'] = home['rack_id']
    # The values below identify the operation input. Its available volume is
    # always read from the root ledger, never initialized from this projection.
    profile['samples'] = [{'id': sample_id, 'vessel_id': source_vessel_id,
                           'rack_slot': place['slot'], 'initial_volume_ul': None}]
    definition['effective_profile_sha256'] = digest(encoded(profile).encode())
    definition['runtime_projection'] = {'context_id': identity,
        'source_profile_id': source_profile, 'source_vessel_id': source_vessel_id,
        'volume_source': 'canonical_root_inventory_and_bookings'}
    adapter_type = ADAPTERS[device]
    local = {'status': 'ready', 'actor_id': None, 'attempt_id': identity,
             'deadline_s': None, 'rack_ready': True, 'workspace_clear': False,
             'recovery_required': None, 'session': None, 'planned_measurements': {},
             'measurements': {}, 'imports': {}, 'results': {}, 'result_review': None,
             **adapter_type._initial_extra(identity, definition)}
    local.pop('derived_vessels', None)
    local.pop('logical_time_s', None)
    if device == 'nanodrop':
        local['planned_measurements'][sample_id] = identity + '.A01.M001'
    context = {'id': identity, 'device': device, 'attempt_id': attempt_id,
               'sample_id': sample_id, 'source_vessel_id': source_vessel_id,
               'definition': definition, 'local': local, 'derived_vessel_ids': []}
    root['contexts'][identity] = context
    return context


class SourceSampleView(MutableMapping):
    """The selected input may be a dilution; it remains the same root vessel."""
    def __init__(self, root, context):
        self.root, self.context = root, context
        self.vessel = root['inventory']['vessels'][context['source_vessel_id']]

    def __getitem__(self, key):
        sample = self.context['definition']['profile']['samples'][0]
        fixed = {'id': self.context['sample_id'], 'vessel_id': self.context['source_vessel_id'],
                 'rack_slot': sample['rack_slot'],
                 'original_place_id': self.vessel['home']['place_id'],
                 'initial_volume_ul': self.vessel['initial_volume_ul']}
        if key == 'remaining_volume_ul':
            return remaining(self.root, self.context['source_vessel_id'])
        if key in fixed:
            return fixed[key]
        if key in {'return_confirmation', 'mass_confirmation_valid'}:
            return self.vessel.get(key, None if key == 'return_confirmation' else False)
        return self.vessel[key]

    def __setitem__(self, key, value):
        if key in {'id', 'sample_id', 'vessel_id', 'rack_slot', 'original_place_id',
                   'home', 'initial_volume_ul', 'remaining_volume_ul'}:
            raise TaskError('Source identities and volume projections are read only')
        self.vessel[key] = value
        if key == 'volume_uncertain' and value:
            self.vessel['mass_confirmation_valid'] = False

    def __delitem__(self, key):
        raise TaskError('Source vessel history cannot be deleted')

    def __iter__(self):
        return iter(dict.fromkeys([*self.vessel, 'id', 'vessel_id', 'rack_slot',
            'original_place_id', 'initial_volume_ul', 'remaining_volume_ul',
            'return_confirmation', 'mass_confirmation_valid']))

    def __len__(self):
        return sum(1 for _ in self)


class SamplesView(MutableMapping):
    def __init__(self, root, context):
        self.root, self.context = root, context

    def __getitem__(self, key):
        if key != self.context['sample_id']:
            raise KeyError(key)
        return SourceSampleView(self.root, self.context)

    def __iter__(self):
        return iter([self.context['sample_id']])

    def __len__(self):
        return 1

    def __setitem__(self, key, value):
        raise TaskError('Device source mapping is immutable')

    def __delitem__(self, key):
        raise TaskError('Device source mapping is immutable')


class DerivedVesselsView(MutableMapping):
    """Only this context's assay/standard tubes; other material stays in root."""
    def __init__(self, root, context):
        self.root, self.context = root, context

    def __getitem__(self, key):
        if key not in self.context['derived_vessel_ids']:
            raise KeyError(key)
        return self.root['inventory']['vessels'][key]

    def __iter__(self):
        return iter(self.context['derived_vessel_ids'])

    def __len__(self):
        return len(self.context['derived_vessel_ids'])

    def __setitem__(self, key, value):
        if key in self.root['inventory']['vessels']:
            raise TaskError('Vessel identity was already used in this DNA run')
        if not isinstance(value, dict) or value.get('id') != key:
            raise TaskError('Matching derived vessel identity required')
        self.root['inventory']['vessels'][key] = {**value, 'origin': 'derived',
            'context_id': self.context['id'],
            'responsibility': {'kind': 'actor', 'actor_id': self.context['local']['actor_id']}}
        self.context['derived_vessel_ids'].append(key)

    def __delitem__(self, key):
        raise TaskError('Derived vessels must retain their history')


class ContextState(MutableMapping):
    """Runtime view only; samples and balances are never serialized here."""
    def __init__(self, root, context_id):
        self.root, self.context = root, root['contexts'][context_id]
        self.local = self.context['local']
        self.definition = self.context['definition']

    def __getitem__(self, key):
        if key == 'samples': return SamplesView(self.root, self.context)
        if key == 'derived_vessels': return DerivedVesselsView(self.root, self.context)
        if key == 'resources': return self.root['resources']
        if key == 'definition': return self.definition
        if key == 'logical_time_s': return self.root['logical_time_s']
        if key == 'run_id': return self.context['id']
        if key in {'deadline_s', 'deadline_unix_s'}: return self.local['deadline_s']
        return self.local[key]

    def __setitem__(self, key, value):
        if key in {'samples', 'derived_vessels', 'definition', 'run_id'}:
            raise TaskError('Device context projections are read only')
        if key in {'resources', 'logical_time_s'}: self.root[key] = value
        elif key in {'deadline_s', 'deadline_unix_s'}: self.local['deadline_s'] = value
        else: self.local[key] = value

    def __delitem__(self, key):
        if key not in self.local:
            raise TaskError('Device context projections cannot be deleted')
        del self.local[key]

    def __iter__(self):
        return iter(set(self.local) | {'samples', 'derived_vessels', 'resources',
                                      'definition', 'logical_time_s', 'run_id'})

    def __len__(self):
        return sum(1 for _ in self)


class ContextAdapter:
    EVENT_CLOCK = True
    DEADLINE_FIELD = 'deadline_s'

    def __init__(self, flow, root, context_id):
        self.flow, self.root = flow, root
        self.context = root['contexts'][context_id]
        self.journal, self.run_id = flow.journal, context_id
        self.state = ContextState(root, context_id)

    def _now(self, state):
        return self.root['logical_time_s']

    def _check_withdrawal(self, state, sample_id):
        source = state['samples'][sample_id]['vessel_id']
        if any(row['source_vessel_id'] == source and row['outcome'] in {'intent', 'unknown'}
               for row in self.root['bookings'].values()):
            raise TaskError('Resolve the previous withdrawal before measuring again')
        super()._check_withdrawal(state, sample_id)

    def _consume(self, state, sample_id, volume_ul, deviation_reason=None):
        pending = self._pending(state)
        if not pending or sample_id != self.context['sample_id']:
            raise TaskError('A matching persisted sample withdrawal is required')
        booking = self.root['bookings'].get(pending['intent_id'])
        if (not booking or booking['source_vessel_id'] != self.context['source_vessel_id']
                or booking['stage_id'] != self.context['id']
                or booking['attempt_id'] != self.context['attempt_id']):
            raise TaskError('A matching context withdrawal intent is required')
        confirm_withdrawal(self.root, pending['intent_id'], volume_ul, reason=deviation_reason)

    @staticmethod
    def _finish_lifecycle(state, status):
        state.local.update(status=status, workspace_clear=True, session=None)


class NanoDropAdapter(ContextAdapter, NanoDropOperations):
    @staticmethod
    def _pending(state):
        return state['pending_measurement']


class QubitAdapter(ContextAdapter, QubitOperations):
    def holder_places(self):
        definition = self.state['definition']
        candidates = self.root['definition'].get('qubit_holder_places')
        if candidates is None:
            candidates = definition['profile']['logical_places']
        instrument_id = definition['profile']['instrument']['id']
        return [{'holder_id': p['holder_id'], 'place_id': p['place_id']} for p in candidates
                if p.get('role', 'holder_slot') == 'holder_slot' and p['holder_id'] != instrument_id]

    def _begin_preparation(self, state, actor_id, kind, target_id, vessel_id,
                           observed_vessel_id, holder_id, place_id, empty_tube_confirmed):
        if {'holder_id': holder_id, 'place_id': place_id} not in self.holder_places():
            raise TaskError('A holder slot is required; the Qubit chamber is not storage')
        super()._begin_preparation(state, actor_id, kind, target_id, vessel_id,
                                  observed_vessel_id, holder_id, place_id, empty_tube_confirmed)

    def _begin_measurement(self, state, actor_id, preparation_id, measurement_id,
                           observed_vessel_id, calibration_id=None):
        vessel = state['derived_vessels'].get(observed_vessel_id)
        holders = [{'kind': 'logical', **place} for place in self.holder_places()]
        if not vessel or vessel['location'] not in holders:
            raise TaskError('Observe the prepared tube at a holder before measuring')
        super()._begin_measurement(state, actor_id, preparation_id, measurement_id,
                                  observed_vessel_id, calibration_id)
        state['pending_operation']['return_place'] = copy.deepcopy(vessel['location'])

    def _finish_measurement(self, state, intent_id, observed_vessel_id, returned_to_holder):
        pending = self._pending(state)
        if pending and pending['kind'] == 'measurement' and pending['intent_id'] == intent_id:
            vessel = state['derived_vessels'].get(observed_vessel_id)
            if returned_to_holder is True and vessel and vessel['location'] != pending['return_place']:
                raise ObservationError('Return the measured tube to its recorded holder, not the chamber')
        super()._finish_measurement(state, intent_id, observed_vessel_id, returned_to_holder)


ADAPTERS = {'nanodrop': NanoDropAdapter, 'qubit': QubitAdapter}


def build_adapter(flow, root, context_id):
    try:
        context = root['contexts'][context_id]
        adapter = ADAPTERS[context['device']]
    except KeyError as error:
        raise TaskError('Unknown DNA device context') from error
    return adapter(flow, root, context_id)
