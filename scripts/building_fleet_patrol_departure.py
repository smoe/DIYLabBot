"""Admission of one independently checked depot starter alongside a patrol leg."""
import copy

from building_fleet_control import preparation_digest
from building_fleet_departure import independent_starter_end, inside_departure_room
from building_fleet_departure_guard import GuardedHomeMap, check_departure_invariant
from building_fleet_departure_service import DepartureResourceServices
from building_fleet_depot import exact_home_rest
from building_fleet_motion import Path


class PatrolDepartures:
    def __init__(self, world):
        if world.now != 0 or world._background_preparation is None:
            raise ValueError('Enable private departures only at checked live session startup')
        self.world = world
        self.ticket = None
        self.leader_action = self.follower_action = None
        self.leader_driver = self.follower_driver = None
        self.attempted = {}
        self.last_unavailable = {}
        self.handovers = 0
        # Before the first model tick no mission, token or bay has been issued.
        world.resources = DepartureResourceServices(world.catalog.resources, world.nav.waits)
        world.resources.enable_depot_departures(world.depot_aliases.values())
        tolerance = world.sensor['range_error_mm'] + world.source['geometry']['localization_tolerance_mm']
        world.depot_maps = {identity: GuardedHomeMap(identity, world.nav.homes, world.nav.envelope,
                                                   world.depot_aliases, tolerance)
                            for identity in world.vehicles}

    def staged(self, identity):
        return self.ticket is not None and self.ticket['vehicle'] == identity

    def _prefix(self, leader_driver, follower_path, polygon):
        world = self.world
        limits = world.source['motion']['empty_linear_limits']
        bounds = dict(max_step_s=world.dt, velocity_mm_s=limits['velocity_mm_s'],
                      acceleration_mm_s2=limits['acceleration_mm_s2'])
        horizon = independent_starter_end(leader_driver.path, follower_path,
                                          world.nav.radius, world.nav.reserve, **bounds)
        margin = world.nav.radius + world.nav.reserve
        if horizon > 0 and inside_departure_room(follower_path, horizon, polygon, margin, **bounds):
            return horizon
        # The complete body and fit tube must stay in the original private room.
        lower, upper = 0., horizon
        while upper - lower > .01:
            middle = (lower + upper) / 2
            if inside_departure_room(follower_path, middle, polygon, margin, **bounds):
                lower = middle
            else:
                upper = middle
        return lower

    def try_depart(self, identity, resource):
        world = self.world
        if self.ticket is not None:
            return False
        leader = world.resources.owners.get(resource)
        home = world.nav.homes[identity]
        if leader is None or home['area'] == world.nav.homes[leader]['area']:
            return False
        first = world.vehicles[leader]
        action = first['action']
        if (first['driver'] is None or not action or action.get('lift_phase')
                or action['level'] != home['level']
                or action['terminal']['kind'] not in ('capacity_home','home','lift_wait','capacity_wait')):
            return False
        # Only a lease covering the leader's whole remaining leg may nominate.
        # An intermediate release would expose its later return to a new owner.
        spans = first['gate'].spans
        if (len(spans) != 1 or spans[0]['resource'] != resource or spans[0]['start_progress_mm'] != 0
                or abs(spans[0]['end_progress_mm']-first['driver'].goal) > 1e-6):
            return False
        state = world.planner.states[identity]
        signature = (first['leg_id'], tuple(m['mission_id'] for m in state['queue']),
                     state['admission_deferred'], state['requested'])
        if self.attempted.get(identity) == signature:
            return False
        self.attempted[identity] = signature
        own, grants = world.own(identity), world.own_grants(identity)
        preview = copy.copy(world.planner)
        preview.states = {identity: copy.deepcopy(state)}
        proposal = preview.next_action(own, world.now, grants)
        if proposal['kind'] == 'request_mission':
            request = world.planner.next_action(own, world.now, grants)
            result = world.request_mission(identity, request['from_level'], world.now)
            world.planner.on_action_result(identity, request, result, world.now)
            return False
        if (proposal['kind'] != 'drive' or proposal.get('lift_phase') or proposal['reverse']
                or proposal['level'] != home['level']):
            return False
        path = Path(proposal['points_mm'], proposal['corner_trim_mm'], proposal.get('corner_trim_caps'))
        horizon = self._prefix(first['driver'], path, world.depot_polygons[home['level'],home['area']])
        if horizon <= 1e-5 or horizon >= path.length-1e-5:
            return False
        if not world.resources.reserve_departure_successor(identity, resource, leader, world.now):
            return False
        actual = world.planner.next_action(own, world.now, grants)
        digest = preparation_digest(proposal)
        if preparation_digest(actual) != digest:
            raise RuntimeError('Nominated starter differs from the actual immutable mission action')
        self.ticket = dict(vehicle=identity, leader=leader, resource=resource, level=home['level'],
                           area=home['area'], start_xy=path.position(0), end_xy=path.position(horizon),
                           start_yaw=own['pose_mm_rad'][2], horizon_mm=horizon, action_sha256=digest,
                           leader_leg=first['leg_id'], granted_s=world.now)
        world.start_drive(identity, actual)
        self.leader_action, self.leader_driver = action, first['driver']
        row = world.vehicles[identity]
        self.follower_action, self.follower_driver = row['action'], row['driver']
        return True

    def permits(self, identity, driver):
        t, world = self.ticket, self.world
        if (not self.staged(identity) or world.resources.departure_successors.get(t['resource']) != identity
                or world.resources.owners.get(t['resource']) != t['leader']
                or world.vehicles[t['leader']]['leg_id'] != t['leader_leg']
                or world.vehicles[t['leader']]['action'] is not self.leader_action
                or world.vehicles[t['leader']]['driver'] is not self.leader_driver
                or world.vehicles[identity]['action'] is not self.follower_action
                or driver is not self.follower_driver
                or driver is not world.vehicles[identity]['driver'] or driver.joined_nominal
                or not driver.awaiting_continuation or driver.certified_horizon_mm > t['horizon_mm']+1e-5):
            raise RuntimeError('Private departure lost its bounded action or resource')
        return True

    def check_release(self, leader, resource):
        t, world = self.ticket, self.world
        if not t or (leader, resource) != (t['leader'], t['resource']):
            return
        row = world.vehicles[leader]
        if (row['leg_id'] != t['leader_leg'] or world.resources.owners.get(resource) != leader
                or world.resources.departure_successors.get(resource) != t['vehicle']):
            raise RuntimeError('Private departure has lost its reserved handover')
        driver = row['driver']
        terminal = self.leader_action['terminal']
        if driver is None:
            if (terminal['kind'] != 'home' or row.get('last_terminal') != terminal
                    or not exact_home_rest(leader, world.depot_states()[leader], world.nav.homes)):
                raise RuntimeError('Private departure handover requires the observed terminal home rest')
            return
        if (driver is not self.leader_driver or row['action'] is not self.leader_action
                or driver.mode != 'arrived' or abs(driver.y-driver.goal) > 1e-6
                or abs(driver.v) > 1e-8 or abs(driver.a) > 1e-8):
            raise RuntimeError('Private departure handover requires arrival at the original terminal')
        if terminal['kind'] in ('capacity_wait', 'lift_wait'):
            world.require_own_waiting_pose(leader, terminal['slot'])
        elif not exact_home_rest(leader, world.depot_states()[leader], world.nav.homes):
            raise RuntimeError('Private departure handover requires exact home rest')

    def released(self, leader, resource):
        if self.ticket and self.ticket['leader'] == leader and self.ticket['resource'] == resource:
            if self.world.resources.owners.get(resource) != self.ticket['vehicle']:
                raise RuntimeError('A staged departure lost its reserved corridor succession')
            self.ticket = None
            self.leader_action = self.follower_action = None
            self.leader_driver = self.follower_driver = None
            self.handovers += 1

    def audit(self):
        world = self.world
        states = world.depot_states()
        for identity, state in states.items():
            if world.vehicles[identity]['driver'] is not None or not exact_home_rest(identity,state,world.nav.homes):
                self.last_unavailable[identity] = world.now
        expiry = world.now - world.sensor['stale_after_s'] - world.dt
        excluded = {identity for identity, last in self.last_unavailable.items() if last >= expiry}
        for identity, row in world.vehicles.items():
            if row['driver'] is not None:
                room = self.ticket['area'] if self.staged(identity) else None
                world.depot_maps[identity].select_occupied_homes(excluded, private_room=room)
        return check_departure_invariant(states, world.nav.homes, world.depot_polygons, world.depot_aliases,
                                         world.resources.owners, world.nav.reserve, self.ticket)
