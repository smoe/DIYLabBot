"""Source-home scan surfaces and truth checks for private depot starters."""
import math

from building_fleet_depot import FixedHomeMap, check_invariant
from building_fleet_navigation import point_in_polygon
from building_fleet_sim import footprint, point_segment_distance, polygon_distance, polygon_segment_distance


class GuardedHomeMap(FixedHomeMap):
    """Select only source homes still proved immobile over retained scans."""

    def __init__(self, own_identity, homes, envelope, aliases, tolerance_mm):
        super().__init__(own_identity, homes, envelope, aliases, tolerance_mm)
        self._identity = own_identity
        self._homes = homes
        self._envelope = envelope
        self._aliases = aliases
        home = homes[own_identity]
        self._room = (home['level'],home['area'])
        self._excluded = frozenset()
        self._private_room = None
        self._own_grant = {'status':'none'}

    def select_occupied_homes(self, excluded, private_room=None):
        """Update static surface eligibility; this issues no resource token."""
        if private_room == self._room[1]:
            private_room = self._room
        if private_room is not None and private_room != self._room:
            raise ValueError('Private depot matching requires the original own room')
        excluded = frozenset(excluded)
        if not excluded.issubset(self._homes):
            raise ValueError('Expected only source home identifiers')
        if excluded == self._excluded and private_room == self._private_room:
            return
        occupied = {key:home for key,home in self._homes.items()
                    if key not in excluded and (private_room is None or (home['level'],home['area']) == private_room)}
        self.indexes = FixedHomeMap(self._identity, occupied, self._envelope,
                                    self._aliases, self.tolerance).indexes
        self._excluded = excluded
        self._private_room = private_room
        self.set_own_grant(self._own_grant)

    def set_own_grant(self, grant):
        super().set_own_grant(grant)
        self._own_grant = dict(grant)
        if (self._private_room is not None and grant.get('status') == 'waiting'
                and grant.get('resource') == self._aliases[self._room]):
            # This index contains only immutable surfaces in the reserved private room.
            # The independent passage service and controller still observe "waiting".
            self.grant = grant['resource']


def _check_private_starter(states, homes, room_polygons, aliases, owners, reserve_mm, ticket):
    vehicle, leader = ticket['vehicle'], ticket['leader']
    room = (ticket['level'], ticket['area'])
    resource = ticket['resource']
    if (not resource or aliases.get(room) != resource or owners.get(resource) != leader
            or vehicle == leader or leader not in states or vehicle not in states or vehicle not in homes):
        raise RuntimeError('A private starter requires its existing leader and current depot reservation')
    home = homes[vehicle]
    state = states[vehicle]
    if ((home['level'],home['area']) != room or state['level'] != room[0] or state.get('aboard',False)):
        raise RuntimeError('Private starter left its source room or floor')
    start, end = ticket['start_xy'], ticket['end_xy']
    x,y,yaw = state['pose_mm']
    heading = ticket['start_yaw']
    velocity = state['velocity_mm_rad_s']
    acceleration = state['acceleration_mm_rad_s2']
    if not all(math.isfinite(v) for v in (*start,*end,x,y,yaw,heading,*velocity,*acceleration,reserve_mm)):
        raise RuntimeError('Private starter needs finite observed PVA and source geometry')
    dx,dy = end[0]-start[0], end[1]-start[1]
    length = math.hypot(dx,dy)
    if (reserve_mm < 0 or length <= 1e-6 or math.dist(start,home['pose_mm_rad'][:2]) > 1e-6
            or abs(math.remainder(heading-home['pose_mm_rad'][2],2*math.pi)) > 1e-6
            or abs(math.remainder(yaw-heading,2*math.pi)) > 1e-6
            or point_segment_distance((x,y),start,end) > 1e-6):
        raise RuntimeError('Observed private starter pose left its source-bound straight segment')
    dx,dy = dx/length,dy/length
    if (abs(math.sin(heading)*dx-math.cos(heading)*dy) > 1e-6
            or velocity[0]*dx+velocity[1]*dy < -1e-7
            or any(abs(dx*jet[1]-dy*jet[0]) > 1e-6 or abs(jet[2]) > 1e-7
                   for jet in (velocity,acceleration))):
        raise RuntimeError('Observed private starter PVA left its permitted direction')
    body = footprint(state)
    boundary = room_polygons[room]
    if (not all(point_in_polygon(corner,boundary) for corner in body)
            or any(polygon_segment_distance(body,a,b) < max(1e-8,reserve_mm-1e-6)
                   for a,b in zip(boundary,boundary[1:]+boundary[:1]))
            or any(key != room and key[0] == room[0] and polygon_distance(body,polygon) <= reserve_mm+1e-7
                   for key,polygon in room_polygons.items())):
        raise RuntimeError('Private starter footprint or its clearance reached a room boundary')


def check_departure_invariant(states, homes, room_polygons, aliases, owners, reserve_mm, tickets):
    """Keep every unticketed occupant under the original home/owner invariant."""
    staged = set()
    for ticket in tickets:
        if ticket['vehicle'] in staged:
            raise RuntimeError('A private starter may have only one live ticket')
        _check_private_starter(states, homes, room_polygons, aliases, owners, reserve_mm, ticket)
        staged.add(ticket['vehicle'])
    ordinary = {key:row for key,row in states.items() if key not in staged}
    return len(staged) + check_invariant(ordinary, homes, room_polygons, aliases, owners, reserve_mm)
