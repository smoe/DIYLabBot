"""Admission and ordered handover of independently checked depot starters."""
import copy
import math

from building_fleet_control import preparation_digest
from building_fleet_departure import independent_starter_end, inside_departure_room, rectangular_starter_end
from building_fleet_departure_guard import GuardedHomeMap, check_departure_invariant
from building_fleet_departure_service import DepartureResourceServices
from building_fleet_depot import exact_home_rest
from building_fleet_model import scan_angular_allowance
from building_fleet_motion import Path


class PatrolDepartures:
    def __init__(self, world):
        if world.now != 0 or world._background_preparation is None:
            raise ValueError('Enable private departures only at checked live session startup')
        self.world = world
        self.tickets = {}
        self._private_drives = {}
        self._batch_promoted = False
        self.leader_action = self.leader_driver = None
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

    @property
    def ticket(self):
        """Next staged successor, whose handover also protects the remaining batch."""
        return next(iter(self.tickets.values()), None)

    def ticket_for(self, identity):
        return self.tickets.get(identity)

    def staged(self, identity):
        return identity in self.tickets

    def _prefix(self, protected_paths, follower_path, polygon):
        world = self.world
        limits = world.source['motion']['empty_linear_limits']
        bounds = dict(max_step_s=world.dt, velocity_mm_s=limits['velocity_mm_s'],
                      acceleration_mm_s2=limits['acceleration_mm_s2'])
        # A geometrically clear pair can still block each other's anonymous
        # scan when both leave their static homes. Include the controller's
        # full source sensing allowance in the branch admission, not its scans.
        sensor = world.sensor
        separation = max(world.nav.reserve, sensor['clearance_mm'] + sensor['range_error_mm']
                         + scan_angular_allowance(sensor) + world.source['geometry']['localization_tolerance_mm'])
        horizon = follower_path.ends[0]
        for path in protected_paths:
            n = independent_starter_end(path, follower_path, world.nav.radius, separation, **bounds)
            if n < horizon:
                n = max(n, rectangular_starter_end(path, follower_path, world.nav.envelope,
                                                   separation, **bounds))
            horizon = min(horizon, n)
            if horizon <= 1e-5:
                return 0.
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

    @staticmethod
    def _can_keep_corridor(action, resource, spans):
        return (not action.get('lift_phase')
                and action['terminal']['kind'] in ('capacity_home','home','lift_wait','capacity_wait')
                and bool(spans) and all(span['resource'] == resource for span in spans))

    def keeps_corridor(self, identity, resource):
        """Keep the same exclusive token through gaps until the verified handover."""
        ticket = self.ticket
        return ticket is not None and (identity,resource)==(ticket['leader'],ticket['resource'])

    def check_step_speeds(self, speed_bounds):
        """Enforce the fit assumption on the exact recorded world PVA."""
        batch = self.ticket
        if batch is None:
            return
        cap = self.world.source['motion']['empty_linear_limits']['velocity_mm_s']*(1+1e-6)
        for identity in (batch['leader'], *self.tickets):
            actual = speed_bounds[identity]['linear_mm_s']
            if not math.isfinite(actual) or not 0<=actual<=cap:
                raise RuntimeError('Actual depot step exceeds its guaranteed sweep speed: '+identity)

    def try_depart(self, identity, resource):
        world = self.world
        batch = self.ticket
        if self._batch_promoted or identity in self.tickets or (batch and batch['resource'] != resource):
            return False
        leader = world.resources.owners.get(resource)
        home = world.nav.homes[identity]
        if leader is None:
            return False
        first = world.vehicles[leader]
        action = first['action']
        if first['driver'] is None or not action or action['level'] != home['level']:
            return False
        keep_for_lift=getattr(world,'keeps_cabin_corridor',None)
        if keep_for_lift and keep_for_lift(leader,resource):
            return False
        state = world.planner.states[identity]
        signature = (first['leg_id'], tuple(m['mission_id'] for m in state['queue']),
                     state['admission_deferred'], state['requested'])
        if self.attempted.get(identity) == signature:
            return False
        self.attempted[identity] = signature
        # An intermediate release would expose a later part of this path to a
        # new owner. Check the full path, even if only its starter is installed.
        if not self._can_keep_corridor(action, resource,
                                       world.catalog.spans(action['level'], first['driver'].path)):
            return False
        # Each earlier staged vehicle may inherit the corridor while this new
        # starter is still on its private straight. Bind to their full paths.
        protected_paths = [first['driver'].path]
        for staged_action, driver in self._private_drives.values():
            if not self._can_keep_corridor(staged_action, resource,
                                           world.catalog.spans(home['level'], driver.path)):
                return False
            protected_paths.append(driver.path)
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
        horizon = self._prefix(protected_paths, path, world.depot_polygons[home['level'],home['area']])
        if horizon <= 1e-5 or horizon >= path.length-1e-5:
            return False
        if not world.resources.reserve_departure_successor(identity, resource, leader, world.now):
            return False
        actual = world.planner.next_action(own, world.now, grants)
        digest = preparation_digest(proposal)
        if preparation_digest(actual) != digest:
            raise RuntimeError('Nominated starter differs from the actual immutable mission action')
        self.tickets[identity] = dict(vehicle=identity, leader=leader, resource=resource,
            level=home['level'], area=home['area'], start_xy=path.position(0), end_xy=path.position(horizon),
            start_yaw=own['pose_mm_rad'][2], horizon_mm=horizon, action_sha256=digest,
            leader_leg=first['leg_id'], granted_s=world.now)
        world.start_drive(identity, actual)
        self.leader_action, self.leader_driver = action, first['driver']
        row = world.vehicles[identity]
        self._private_drives[identity] = row['action'], row['driver']
        return True

    def permits(self, identity, driver):
        t, world = self.ticket_for(identity), self.world
        if (t is None or identity not in world.resources.departure_successors.get(t['resource'], ())
                or world.resources.owners.get(t['resource']) != t['leader']
                or world.vehicles[t['leader']]['leg_id'] != t['leader_leg']
                or world.vehicles[t['leader']]['action'] is not self.leader_action
                or world.vehicles[t['leader']]['driver'] is not self.leader_driver
                or world.vehicles[identity]['action'] is not self._private_drives[identity][0]
                or driver is not self._private_drives[identity][1]
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
                or world.resources.departure_successors.get(resource, ()) != tuple(self.tickets)):
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
        ticket = self.ticket
        if not ticket or (ticket['leader'], ticket['resource']) != (leader,resource):
            return
        world = self.world
        successor = ticket['vehicle']
        if world.resources.owners.get(resource) != successor:
            raise RuntimeError('A staged departure lost its reserved corridor succession')
        action, driver = self._private_drives.pop(successor)
        del self.tickets[successor]
        self.handovers += 1
        self._batch_promoted = bool(self.tickets)
        self.leader_action, self.leader_driver = (action, driver) if self.tickets else (None,None)
        for pending in self.tickets.values():
            pending.update(leader=successor, leader_leg=world.vehicles[successor]['leg_id'])

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
                ticket = self.ticket_for(identity)
                room = ticket['area'] if ticket is not None else None
                world.depot_maps[identity].select_occupied_homes(excluded, private_room=room)
        return check_departure_invariant(states, world.nav.homes, world.depot_polygons, world.depot_aliases,
                                         world.resources.owners, world.nav.reserve, self.tickets.values())
