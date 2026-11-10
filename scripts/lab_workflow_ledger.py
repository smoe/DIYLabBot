"""Canonical inventory and checked consumption projections for one synthetic run.

Compatibility views translate legacy manual handlers at the adapter boundary;
they are never separately serialized or used as another inventory ledger.
"""
from collections.abc import MutableMapping
import copy
import math

from manual_tasks import TaskError
from manual_workflow import ObservationError, positive


def manifest_samples(root):
    return {sample['sample_id']: sample for sample in root['definition']['manifest']['samples']}


def original_location(root, sample_id):
    return {'kind': 'rack', 'rack_id': root['definition']['rack_instance'],
            'place_id': manifest_samples(root)[sample_id]['rack_place_id']}


def initial_inventory(definition):
    return {'vessels': {sample['vessel_id']: {
        'id': sample['vessel_id'], 'origin': 'original', 'sample_id': sample['sample_id'],
        'location': {'kind': 'rack', 'rack_id': definition['rack_instance'], 'place_id': sample['rack_place_id']},
        'observed_location': None, 'responsibility': None, 'content_revision': 0,
        'volume_uncertain': False, 'mass_confirmation_valid': False,
        'mass_confirmation_id': None, 'return_confirmation': None}
        for sample in definition['manifest']['samples']}}


def remaining(root, sample_id, exclude_intent=None):
    initial = manifest_samples(root)[sample_id]['initial_volume_ul']
    if initial is None:
        return None
    records = [record for key, record in root['bookings'].items()
               if key != exclude_intent and record['sample_id'] == sample_id]
    if any(record['outcome'] == 'unknown' for record in records):
        return None
    return initial - math.fsum(record['actual_volume_ul'] for record in records
                               if record['outcome'] == 'performed')


def begin_withdrawal(root, stage_id, pending, sample_id, target):
    identity = pending['intent_id']
    if identity in root['bookings']:
        raise TaskError('Consumption intent identity already exists')
    sample = manifest_samples(root)[sample_id]
    root['bookings'][identity] = {
        'id': identity, 'run_id': root['run_id'], 'stage_id': stage_id,
        'attempt_id': root['stages'][stage_id]['attempt_id'], 'sample_id': sample_id,
        'source_vessel_id': sample['vessel_id'], 'target': copy.deepcopy(target),
        'planned_volume_ul': root['definition']['stages'][stage_id]['profile']['parameters']['sample_volume_ul'],
        'actual_volume_ul': None, 'unit': 'uL', 'outcome': 'intent',
        'created_at_s': root['logical_time_s'], 'confirmed_at_s': None,
        'actor_id': root['stages'][stage_id]['actor_id'], 'evidence': 'synthetic_input'}
    vessel = root['inventory']['vessels'][sample['vessel_id']]
    vessel['volume_uncertain'] = True
    vessel['mass_confirmation_valid'] = False


def confirm_withdrawal(root, stage_id, pending, sample_id, volume_ul, reason):
    positive(volume_ul, 'withdrawn volume in uL')
    record = root['bookings'].get(pending['intent_id'])
    if not record or record['stage_id'] != stage_id or record['sample_id'] != sample_id:
        raise TaskError('Unknown or foreign consumption intent')
    if record['outcome'] not in {'intent', 'unknown'}:
        raise TaskError('Consumption intent already resolved')
    planned = record['planned_volume_ul']
    if not math.isclose(volume_ul, planned, rel_tol=0, abs_tol=1e-9) and (not isinstance(reason, str) or not reason.strip()):
        raise TaskError('Reason for volume deviation required')
    available = remaining(root, sample_id, exclude_intent=record['id'])
    if available is not None and volume_ul > available:
        raise ObservationError('Withdrawal exceeds remaining volume')
    record.update(outcome='performed', actual_volume_ul=volume_ul,
                  confirmed_at_s=root['logical_time_s'], deviation_reason=reason)
    vessel = root['inventory']['vessels'][record['source_vessel_id']]
    vessel['content_revision'] += 1
    vessel['mass_confirmation_valid'] = False
    vessel['volume_uncertain'] = False


class SampleView(MutableMapping):
    def __init__(self, root, sample_id):
        self.root, self.sample_id = root, sample_id
        self.sample = manifest_samples(root)[sample_id]
        self.vessel = root['inventory']['vessels'][self.sample['vessel_id']]

    def __getitem__(self, key):
        fixed = {'id': self.sample_id, 'vessel_id': self.sample['vessel_id'],
                 'rack_slot': int(self.sample['rack_place_id'][4:]),
                 'original_place_id': self.sample['rack_place_id'],
                 'initial_volume_ul': self.sample['initial_volume_ul']}
        if key == 'remaining_volume_ul':
            return remaining(self.root, self.sample_id)
        return fixed[key] if key in fixed else self.vessel[key]

    def __setitem__(self, key, value):
        if key in {'id', 'vessel_id', 'rack_slot', 'original_place_id', 'initial_volume_ul', 'remaining_volume_ul'}:
            raise TaskError('Manifest identities and volume projections are read only')
        self.vessel[key] = value
        if key == 'volume_uncertain' and value:
            self.vessel['mass_confirmation_valid'] = False

    def __delitem__(self, key):
        raise TaskError('Original vessel fields cannot be deleted')

    def __iter__(self):
        return iter(['id', 'vessel_id', 'rack_slot', 'original_place_id', 'initial_volume_ul',
                     'remaining_volume_ul', 'location', 'volume_uncertain',
                     'mass_confirmation_valid', 'return_confirmation'])

    def __len__(self):
        return sum(1 for _ in self)


class SamplesView(MutableMapping):
    def __init__(self, root):
        self.root = root

    def __getitem__(self, key):
        if key not in manifest_samples(self.root):
            raise KeyError(key)
        return SampleView(self.root, key)

    def __iter__(self):
        return iter(manifest_samples(self.root))

    def __len__(self):
        return len(manifest_samples(self.root))

    def __setitem__(self, key, value):
        raise TaskError('The manifest cannot be changed during a run')

    def __delitem__(self, key):
        raise TaskError('Original samples cannot be deleted')


class DerivedVesselsView(MutableMapping):
    def __init__(self, root):
        self.root = root

    def __getitem__(self, key):
        value = self.root['inventory']['vessels'][key]
        if value['origin'] == 'original':
            raise KeyError(key)
        return value

    def __iter__(self):
        return (key for key, value in self.root['inventory']['vessels'].items() if value['origin'] != 'original')

    def __len__(self):
        return sum(1 for _ in self)

    def __setitem__(self, key, value):
        if key in self.root['inventory']['vessels']:
            raise TaskError('Vessel identity was already used')
        actor = self.root['stages'][self.root['active_stage']]['actor_id']
        self.root['inventory']['vessels'][key] = {**value, 'origin': 'derived',
            'responsibility': {'kind':'actor','actor_id':actor}}

    def __delitem__(self, key):
        raise TaskError('Derived vessels must retain their history')


class StageState(MutableMapping):
    """Explicit legacy operation view over root inventory and one local stage."""
    def __init__(self, root, stage_id):
        self.root, self.stage_id = root, stage_id
        self.local = root['stages'][stage_id]
        self.definition = copy.deepcopy(root['definition']['stages'][stage_id])
        for place in self.definition['places']:
            place['geometry_id'], place['id'] = place['id'], place['place_id']

    def __getitem__(self, key):
        if key == 'samples': return SamplesView(self.root)
        if key == 'derived_vessels': return DerivedVesselsView(self.root)
        if key == 'resources': return self.root['resources']
        if key == 'definition': return self.definition
        if key == 'logical_time_s': return self.root['logical_time_s']
        if key in {'deadline_s', 'deadline_unix_s'}: return self.local['deadline_s']
        if key == 'run_id': return self.root['run_id'] + '.' + self.stage_id
        return self.local[key]

    def __setitem__(self, key, value):
        if key == 'resources': self.root[key] = value
        elif key == 'logical_time_s': self.root[key] = value
        elif key in {'deadline_s', 'deadline_unix_s'}: self.local['deadline_s'] = value
        else: self.local[key] = value

    def __delitem__(self, key):
        del self.local[key]

    def __iter__(self):
        return iter(set(self.local) | {'samples', 'derived_vessels', 'resources', 'definition', 'logical_time_s', 'run_id'})

    def __len__(self):
        return len(set(iter(self)))
