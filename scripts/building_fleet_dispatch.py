"""Seeded assignment only; no vehicle control or world-position access."""
import copy
import random


class Dispatcher:
    """Coverage is based on received completion events, not planned visits.

    The dispatcher can assign an early successor while a leg is underway. It
    never receives peer poses; lift waiting availability is a service response.
    """
    def __init__(self, source, homes):
        self.source = source
        self.random = random.Random(source['missions']['seed'])
        self.targets = {(r['level'], r['area']): copy.deepcopy(r)
                        for r in source['missions']['targets']}
        self.visits = {key: 0 for key in self.targets}
        self.planned = {key: 0 for key in self.targets}
        self.homes = copy.deepcopy(homes)
        self.missions = {}
        self.acks = set()
        self.completed = set()
        self.returning = False
        self.counter = 0

    def assign(self, vehicle_id, own_level, now, lift_wait_available=True):
        if vehicle_id not in self.homes:
            raise ValueError('Unknown own home')
        if now > self.source['missions']['maximum_duration_s']:
            raise RuntimeError('BF01 maximum duration exceeded; seed retained')
        coverage = all(self.visits[k] >= r['minimum_visits'] for k, r in self.targets.items())
        if coverage and now >= self.source['missions']['minimum_duration_s']:
            self.returning = True
        self.counter += 1
        identifier = 'mission-'+str(self.counter)
        if self.returning:
            goal = {'kind': 'home', **copy.deepcopy(self.homes[vehicle_id])}
        else:
            candidates = [k for k in self.targets if lift_wait_available or k[0] == own_level]
            if not candidates:
                raise RuntimeError('No permitted same-level successor while lift waiting area is full')
            # Prefer missing coverage, then those not already assigned. No seed
            # switching and no random calls in vehicle/sensor/service modules.
            priority = min((self.visits[k] > 0, self.planned[k]) for k in candidates)
            candidates = sorted(k for k in candidates if (self.visits[k] > 0, self.planned[k]) == priority)
            weights = [self.targets[k]['weight'] for k in candidates]
            key = self.random.choices(candidates, weights=weights, k=1)[0]
            self.planned[key] += 1
            goal = copy.deepcopy(self.targets[key])
        message = {'mission_id': identifier, 'vehicle_id': vehicle_id, 'assigned_s': now, 'goal': goal}
        self.missions[identifier] = message
        return copy.deepcopy(message)

    def acknowledge(self, vehicle_id, mission_id):
        message = self.missions.get(mission_id)
        if message is None or message['vehicle_id'] != vehicle_id:
            raise ValueError('Mission acknowledgement does not belong to vehicle')
        self.acks.add(mission_id)

    def receive_completion(self, vehicle_id, mission_id):
        message = self.missions.get(mission_id)
        if not message or message['vehicle_id'] != vehicle_id or mission_id not in self.acks:
            raise ValueError('Unknown/unacknowledged own completion')
        if mission_id in self.completed:
            return False
        self.completed.add(mission_id)
        goal = message['goal']
        if goal['kind'] == 'inspection_pass':
            key = goal['level'], goal['area']
            self.visits[key] += 1
            self.planned[key] -= 1
        return True

    def coverage(self):
        return [{'level': k[0], 'area': k[1], 'visits': self.visits[k], 'basis': self.targets[k]['basis']}
                for k in sorted(self.targets)]
