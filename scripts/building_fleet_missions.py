"""Own-state BF01 mission composition on an immutable source route map.

This planner receives no world, peer poses, random generator or sensor results.
Inspection marks are passage events in a longer C2 leg, never rest endpoints.
Geometry proposed here still requires the exported curve and native audits.
"""
import copy
import itertools
import math

import building_fleet_model as model
from building_fleet_motion import Path
from building_fleet_services import cabin_lanes


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite own-state number required')
    return float(value)


def _xy(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('Finite source XY point required')
    return [_number(v) for v in value]


def _same(a, b):
    return math.dist(a, b) < 1e-7


def _append(points, rows):
    start = len(points)-1
    for point in rows:
        point = _xy(point)
        if not points or not _same(points[-1], point):
            points.append(point)
    return max(0, start)


def inspection_variants(inspection):
    """Phase-shift an ordinary closed loop; preserve the fixed L01 connector."""
    points = [_xy(p) for p in inspection['points_mm']]
    if inspection.get('connector_source') or not _same(points[0], points[-1]):
        return [points]
    # Mid-edge anchors retain exactly the same loop and permit either incoming
    # corridor direction without a compulsory reversal at a corner endpoint.
    ring = points[:-1]
    variants = []
    for index in range(min(2, len(ring))):
        a, b = ring[index], ring[(index+1) % len(ring)]
        middle = [(a[k]+b[k])/2 for k in range(2)]
        loop = [middle, *ring[index+1:], *ring[:index+1], middle]
        variants.extend([loop, list(reversed(loop))])
    return variants


def _diagonal_port_points(wait, inside, park, port, settings):
    """Build the landing and lane transition in boarding point order."""
    outward = math.copysign(1., port['exit_eye_mm'][0]-port['plane_x_mm'])
    lead = wait[0]-outward*settings['departure_lead_mm']
    align = port['plane_x_mm']+outward*settings['alignment_from_port_mm']
    crossing_y = park[1]+settings['aperture_center_fraction']*(port['cabin_entry_mm'][1]-park[1])
    if outward*(lead-align) <= 0 or outward*(align-inside[0]) <= 0:
        raise ValueError('Diagonal port route needs a lead on the landing and a lane alignment inside')
    # The motion compiler blends the landing turn into a near-axial
    # aperture crossing and retains both source headings.
    return [wait, [lead, wait[1]], [align, crossing_y], inside, park]


def waypoint_progress(path, points):
    """Monotone event locations on the actual shared Path pieces.

    A rounded waypoint is acknowledged after its blend. Repeated XY locations
    on a closed inspection therefore cannot be mistaken for first arrival.
    """
    result = [0.]
    cursor = 0
    previous = 0.
    for index, point in enumerate(points[1:-1], 1):
        incoming = [point[k]-points[index-1][k] for k in range(2)]
        outgoing = [points[index+1][k]-point[k] for k in range(2)]
        cross = incoming[0]*outgoing[1]-incoming[1]*outgoing[0]
        straight = (abs(cross) <= 1e-9*math.hypot(*incoming)*math.hypot(*outgoing)
                    and sum(a*b for a, b in zip(incoming, outgoing)) > 0)
        found = None
        for j in range(cursor, len(path.pieces)):
            piece = path.pieces[j]
            before = path.ends[j-1] if j else 0.
            controls = piece['controls']
            if not straight and len(controls) == 8 and _same(controls[3][:2], point):
                found = path.ends[j], j+1
                break
            if straight and len(controls) == 2:
                a, b = [row[:2] for row in controls]
                d = [b[k]-a[k] for k in range(2)]
                norm = sum(v*v for v in d)
                u = sum((point[k]-a[k])*d[k] for k in range(2))/norm
                projected = [a[k]+u*d[k] for k in range(2)]
                progress = before+u*piece['weight']
                if -1e-9 <= u <= 1+1e-9 and math.dist(point, projected) < 1e-6 and progress >= previous-1e-7:
                    found = progress, j
                    break
        if found is None:
            raise ValueError('Source waypoint has no monotone location on shared Path')
        previous, cursor = found
        result.append(previous)
    result.append(path.length)
    return result


def _path(points, trim, corner_trim_caps=None):
    path = Path(points, trim,corner_trim_caps=corner_trim_caps)
    for j, piece in enumerate(path.pieces):
        before = path.ends[j-1] if j else 0.
        # Explicitly reject a reversal/cusp; a route knot may not disguise a
        # stop, discontinuous yaw or turn on the spot.
        for u in (0., .5, 1.):
            path.evaluate(min(path.length, before+u*piece['weight']))
    return path


class MissionPlanner:
    """Per-vehicle own assignments, own localization and own grants only."""
    SNAPSHOT_FIELDS = frozenset({'vehicle_id', 'pose_mm_rad', 'level', 'z_mm',
                                 'phase', 'aboard', 'home', 'mission_pending'})

    def __init__(self, source, nav, graph):
        self.source, self.nav, self.graph = source, nav, graph
        self.trim_mm = (model.reference(source,'angular_profile')['curve']['corner_trim_mm']
                        if 'sources' in source else nav.corner_trim_mm)
        self.states = {vehicle: {'queue': [], 'seen': {}, 'completed': set(),
                        'active': None, 'terminal': None, 'done': False,
                        'requested': False, 'admission_deferred':False, 'home_confirmation': None} for vehicle in nav.homes}
        self.ports = copy.deepcopy(model.lift_route_ports(source, nav.mesh.manifest['elevator']['ports']))
        sensor = nav.sensor
        perception_gap = (sensor['clearance_mm']+sensor['range_error_mm']
                          +sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))
                          +source['geometry']['localization_tolerance_mm'])
        self.passing_gap_mm = max(nav.reserve, perception_gap)+nav.navigation_margin_mm
        self.cabin_lanes_override = cabin_lanes(nav.cabin_interior_mm,
            [nav.envelope['length_mm'], nav.envelope['width_mm']], self.passing_gap_mm,
            maximum=source['lift']['maximum_capacity'])
        self.port_paths=None
        if 'sources'in source:
            from building_fleet_port_paths import PortPaths
            self.port_paths=PortPaths(source,nav)
        self.variants = {key: inspection_variants(row) for key, row in nav.inspections.items()}
        self.wait_approaches = {}
        self.prepare_endpoints()

    def prepare_endpoints(self):
        if getattr(self.graph, 'sealed', False):
            raise ValueError('Construct mission planner before sealing static route graph')
        for (level, _), variants in self.variants.items():
            for points in variants:
                self.graph.add_endpoint(level, points[0]); self.graph.add_endpoint(level, points[-1])
        for level, waits in self.nav.waits.items():
            for slot, wait in enumerate(waits):
                paths = self._waiting_approaches(level, slot)
                if not paths:
                    raise ValueError('No source-free private waiting approach: '+level+'/'+str(slot))
                self.wait_approaches[level, slot] = paths
                for points in paths:
                    self.graph.add_endpoint(level, points[0])

    def _private_free(self, level, points, own_slot):
        """Conservative preliminary map check, never a final C2 certificate."""
        grid = self.nav.grids[level]
        threshold = self.nav.radius+self.nav.reserve
        from building_fleet_sim import point_segment_distance
        from building_fleet_navigation import point_in_polygon
        others = [poly for i, poly in enumerate(self.nav.waiting_bay_polygons[level]) if i != own_slot]
        for a, b in zip(points, points[1:]):
            if not grid.line_free(a, b, threshold):
                return False
            # The entire vehicle disc stays outside every OTHER reserved bay;
            # only this vehicle's assigned waiting bay is an access exception.
            for poly in others:
                if point_in_polygon(a, poly) or point_in_polygon(b, poly):
                    return False
                from building_fleet_runner import intersections
                if any(intersections(a, b, c, d) for c, d in zip(poly, poly[1:]+poly[:1])):
                    return False
                distance = min([point_segment_distance(p, a, b) for p in poly]
                               +[point_segment_distance(p, c, d) for p in (a, b)
                                 for c, d in zip(poly, poly[1:]+poly[:1])])
                if distance < threshold:
                    return False
        return True

    def _waiting_approaches(self, level, slot):
        wait = self.nav.waits[level][slot]
        sign = 1 if math.cos(wait[2]) > 0 else -1
        hub = self.nav.road_hubs[level]
        candidates = []
        # The ordinary endpoint remains outside all fixed bay footprints.
        for distance in (2*self.nav.radius+self.nav.reserve,):
            lead = [wait[0]-sign*distance, wait[1]]
            if not self.nav._straight_hits(level, lead, lead):
                candidates.append([lead, wait[:2]])
        # A private side approach is needed where a wall precludes the rear
        # disc-sized lead. The hub is already outside every fixed waiting bay.
        candidates.append([hub, [hub[0], wait[1]], wait[:2]])
        result = []
        for rows in candidates:
            points = []; _append(points, rows)
            if len(points) < 2 or (points[-1][0]-points[-2][0])*sign <= 0:
                continue
            if self._private_free(level, points, slot):
                try: _path(points, self.trim_mm)
                except ValueError: continue
                result.append(points)
        return result

    def prepared_routes(self):
        """Expose only immutable source-map proposals for static conflict closure."""
        routes=[]
        for (level,area),variants in self.variants.items():
            inspection=self.nav.inspections[level,area]
            for points in variants:
                routes.append({'level':level,'points_mm':copy.deepcopy(points),
                    'corner_trim_mm':self.trim_mm,'resources':[{'id':inspection.get('resource',level+'.room.'+area),
                        'kind':'room','start_index':0,'end_index':len(points)-1,'areas':[area]}]})
        for (level,slot),variants in self.wait_approaches.items():
            for points in variants:
                routes.append({'level':level,'points_mm':copy.deepcopy(points),
                    'corner_trim_mm':self.trim_mm,'resources':[],
                    'private_waiting_slot':slot,'curve_qualified':False})
        for home in self.nav.homes.values():
            for points in ([home['pose_mm_rad'][:2],home['departure_xy_mm']],
                           [home['arrival_xy_mm'],home['pose_mm_rad'][:2]],home.get('aisle_loop_mm',[])):
                if len(points)>1:routes.append({'level':home['level'],'points_mm':copy.deepcopy(points),
                    'corner_trim_mm':self.trim_mm,'resources':[],'curve_qualified':False})
        if self.port_paths is not None:
            for level,places in self.nav.waits.items():
                for slot in range(len(places)):
                    routes.append({**self.port_paths.waiting_departure(level,slot),'resources':[],
                        'private_waiting_slot':slot,'curve_qualified':False})
                    for cabin in range(len(self.cabin_lanes_override)):
                        board=self.port_paths.boarding(level,slot,cabin,self.cabin_lanes_override)
                        exit_row=self.port_paths.alighting(level,slot,cabin,self.cabin_lanes_override)
                        for row in(board,exit_row):
                            routes.append({**row,'resources':[],'private_waiting_slot':slot,'curve_qualified':False})
                        for approach in self.wait_approaches[level,slot]:
                            points=copy.deepcopy(exit_row['points_mm']);_append(points,list(reversed(approach)))
                            routes.append({**exit_row,'points_mm':points,'resources':[],
                                'private_waiting_slot':slot,'curve_qualified':False})
        return routes

    def _state(self, vehicle):
        if vehicle not in self.states:
            raise ValueError('Unknown own vehicle')
        return self.states[vehicle]

    def receive_assignment(self, vehicle, mission):
        state = self._state(vehicle)
        required={'mission_id','vehicle_id','assigned_s','goal'}
        if (not isinstance(mission, dict) or not required<=set(mission)or set(mission)-required-{'source_level','booking_id'}
                or mission.get('vehicle_id') != vehicle):
            raise ValueError('Assignment must identify its own vehicle')
        if _number(mission['assigned_s']) < 0:
            raise ValueError('Nonnegative mission assignment time required')
        mid = mission.get('mission_id')
        if not isinstance(mid, str) or not mid:
            raise ValueError('Named own mission required')
        if mid in state['seen']:
            if state['seen'][mid] != mission:
                raise ValueError('Conflicting replay of own assignment')
            return False
        goal = mission.get('goal', {})
        if 'source_level'in mission:
            if mission['source_level']not in self.ports:raise ValueError('Known own assignment source level required')
            if goal.get('level')!=mission['source_level']:
                if not isinstance(mission.get('booking_id'),str)or not mission['booking_id']:raise ValueError('Foreign mission requires its fenced booking')
            elif mission.get('booking_id')is not None:raise ValueError('A local goal must not claim a foreign booking')
        if goal.get('kind') == 'inspection_pass':
            if (goal.get('level'), goal.get('area')) not in self.variants:
                raise ValueError('Assignment is outside source inspection map')
            expected = next((row for row in self.source.get('missions', {}).get('targets', [])
                             if (row['level'], row['area']) == (goal['level'], goal['area'])), None)
            if expected is not None and goal != expected:
                raise ValueError('Inspection goal differs from the immutable source target')
        elif goal.get('kind') == 'home':
            home = self.nav.homes[vehicle]
            if set(goal) != {'kind', *home} or any(goal.get(k) != v for k, v in home.items()):
                raise ValueError('Home goal must reference this vehicle own source home')
        else:
            raise ValueError('Unknown mission kind')
        state['seen'][mid] = copy.deepcopy(mission)
        state['queue'].append(copy.deepcopy(mission)); state['requested'] = False;state['admission_deferred']=False
        return True

    def _snapshot(self, own):
        if not isinstance(own, dict) or set(own) != self.SNAPSHOT_FIELDS:
            raise ValueError('Closed own-localization snapshot required; peer/world fields prohibited')
        self._state(own['vehicle_id'])
        if len(own['pose_mm_rad']) != 3:
            raise ValueError('Own XYZ-independent planar pose required')
        for value in [*own['pose_mm_rad'], own['z_mm']]: _number(value)
        if own['level'] not in self.ports or any(type(own[k]) is not bool for k in ('aboard', 'home', 'mission_pending')):
            raise ValueError('Own observed level and flags required')
        if abs(own['z_mm']-self.nav.level_z[own['level']]) > self.source['geometry']['localization_tolerance_mm'] and not own['aboard']:
            raise ValueError('Unboarded own pose not on observed floor')

    def _request(self, own, level):
        state = self.states[own['vehicle_id']]
        if own['mission_pending'] or state['requested']:
            return {'kind': 'hold', 'reason': 'own_assignment_downlink_pending', 'condition': 'own_received_assignment'}
        state['requested'] = True
        return {'kind': 'request_mission', 'from_level': level}

    def _wait(self, own, grants, destination):
        grant = grants.get('waiting_place', {'status': 'none'})
        if grant.get('status') != 'granted' or grant.get('level') != own['level']:
            return {'kind': 'request_wait', 'level': own['level'], 'to_level': destination}
        slot = grant['slot']
        if type(slot) is not int or not 0 <= slot < len(self.nav.waits[own['level']]):
            raise ValueError('Own waiting grant refers to nonexistent source slot')
        if not _same(grant['pose_mm'][:2], self.nav.waits[own['level']][slot][:2]):
            raise ValueError('Own waiting grant pose differs from source bay')
        return slot

    def _drive(self, vehicle, level, points, zones, marks, terminal, reverse=False, lift_phase=None,
               initial_yaw=None, corner_trim_caps=None, *, variable_corner_speed=False):
        trim = self.trim_mm
        path = _path(points, trim,corner_trim_caps)
        if initial_yaw is not None:
            actual = path.evaluate(0)[0][2]+(math.pi if reverse else 0.)
            if abs(math.atan2(math.sin(actual-initial_yaw), math.cos(actual-initial_yaw))) > 1e-6:
                raise ValueError('New drive would rotate own stationary vehicle instead of preserving heading')
        progress = waypoint_progress(path, points)
        markers = [{**copy.deepcopy(mark), 'progress_mm': progress[mark['point_index']]} for mark in marks]
        markers.sort(key=lambda mark:mark['progress_mm'])
        action = {'kind': 'drive', 'level': level, 'points_mm': points,
                  'zone_segments': zones, 'markers': markers, 'terminal': terminal,
                  'reverse': reverse, 'allow_lift': lift_phase is not None,
                  'corner_trim_mm': trim, 'prefetch_level': terminal.get('to_level', level)}
        if path.corner_trim_caps:action['corner_trim_caps']=copy.deepcopy(path.corner_trim_caps)
        if variable_corner_speed:
            action['variable_corner_speed'] = True
        if lift_phase is not None:
            action['lift_phase'] = copy.deepcopy(lift_phase)
            action['port_id'] = lift_phase['start_port' if lift_phase['kind'] == 'boarding' else 'destination_port']
            action['cabin_slot'] = lift_phase['slot']
        self.states[vehicle]['active'] = copy.deepcopy(action)
        return action

    def _home_observed(self, own):
        home = self.nav.homes[own['vehicle_id']]
        expected = home['pose_mm_rad']; actual = own['pose_mm_rad']
        tolerance = self.source['geometry']['localization_tolerance_mm']
        return (own['home'] and own['level'] == home['level']
                and math.dist(actual[:2], expected[:2]) <= tolerance
                and abs(math.atan2(math.sin(actual[2]-expected[2]), math.cos(actual[2]-expected[2]))) < 1e-6)

    def _smooth_lift_wait_approach(self, level, points, zones, marks, corner_caps):
        """Remove a short same-direction bend before the straight bay entry."""
        if len(points) < 4:
            return points
        removed = len(points)-3
        if (any(zone['end_index'] >= removed for zone in zones)
                or any(mark['point_index'] >= removed for mark in marks)
                or any(row['point_index'] >= removed for row in corner_caps or [])):
            return points
        first, bend, lead, bay = points[-4:]
        if math.dist(bend, lead) > self.trim_mm:
            return points
        def turn(a, b, c):
            incoming = [b[i]-a[i] for i in range(2)]
            outgoing = [c[i]-b[i] for i in range(2)]
            return math.atan2(incoming[0]*outgoing[1]-incoming[1]*outgoing[0],
                              sum(x*y for x,y in zip(incoming,outgoing)))
        left, right = turn(first,bend,lead),turn(bend,lead,bay)
        if left*right <= 0 or abs(left+right) >= math.pi:
            return points
        if not self.graph.shortcut_clear(level,first,lead):
            return points
        # The complete candidate still needs the usual continuous geometry,
        # floor support, resource spans and controller braking certificates.
        return points[:removed]+points[removed+1:]

    def _smooth_foyer_wait_approach(self, level, points, zones, marks, corner_caps, settings):
        """Sweep around the first waiting bay and keep the straight parking lead."""
        join = len(points) - 3 - settings['bypassed_waypoints']
        if (join < 1 or any(zone['end_index'] > join for zone in zones)
                or any(mark['point_index'] >= join for mark in marks)
                or any(cap['point_index'] >= join for cap in corner_caps or [])):
            return points
        others = [polygon for slot, polygon in enumerate(self.nav.waiting_bay_polygons[level])
                  if slot != settings['waiting_slot']]
        required = self.nav.reserve + self.port_paths.mesh_error + self.nav.navigation_margin_mm
        sweep = [*points[join-1:join+1], *points[-2:]]
        candidate = [*points[:join+1], *points[-2:]]
        try:
            if not self.graph.shortcut_clear(level, points[join], points[-2]):
                return points
            if others and not self.port_paths._bay_sweep_clear(sweep, others, required):
                return points
            _path(candidate, self.trim_mm, corner_caps)
        except ValueError:
            # Reject an invalid candidate without discarding the source approach.
            return points
        return candidate

    def _shorten_basement_departure(self, points, zones, prefix_count, settings):
        """Bypass the hub while keeping the door lead and other reserved bays clear."""
        join = prefix_count - 1 + settings['join_route_index']
        if join < 3 or join >= len(points) - 1 or any(zone['start_index'] < join for zone in zones):
            return points
        lead = points[1]
        port = self.ports['KG']
        outward = math.copysign(1., port['exit_eye_mm'][0] - port['plane_x_mm'])
        offset_x, offset_y = settings['turn_offset_mm']
        shoulder = [lead[0] + outward * offset_x, lead[1] + offset_y]
        if outward * (points[join][0] - lead[0]) <= 0:
            return points
        proposed = [points[0], lead, shoulder, *points[join:]]
        others = [polygon for i, polygon in enumerate(self.nav.waiting_bay_polygons['KG'])
                  if i != settings['waiting_slot']]
        required = self.nav.reserve + self.port_paths.mesh_error + self.nav.navigation_margin_mm
        if others and not self.port_paths._bay_sweep_clear(proposed[:5], others, required):
            return points
        # Keep distributed resource boundaries on their original source waypoints.
        for zone in zones:
            zone['start_index'] += 3 - join
            zone['end_index'] += 3 - join
        return proposed

    def _shorten_basement_return(self, points, zones, marks, slot, bypassed_waypoints):
        """Keep the bay's straight park-in heading and bypass the corridor dogleg."""
        join = len(points) - 3 - bypassed_waypoints
        if (join < 1 or any(zone['end_index'] >= join for zone in zones)
                or any(mark['point_index'] >= join for mark in marks)):
            return points
        bay_entry = [*points[join-1:join+1], *points[-2:]]
        others = [polygon for i, polygon in enumerate(self.nav.waiting_bay_polygons['KG']) if i != slot]
        required = self.nav.reserve + self.port_paths.mesh_error + self.nav.navigation_margin_mm
        if others and not self.port_paths._bay_sweep_clear(bay_entry, others, required):
            return points
        return [*points[:join+1], *points[-2:]]

    def _floor_leg(self, own, grants, prefix=None, prefix_marks=None, lift_phase=None, prefix_caps=None,
                   basement_departure=None):
        vehicle, level = own['vehicle_id'], own['level']; state = self.states[vehicle]
        queue = [m for m in state['queue'] if m['mission_id'] not in state['completed']]
        inspections = []; boundary = None
        for mission in queue:
            goal = mission['goal']
            if goal['level'] != level or goal['kind'] == 'home':
                boundary = mission; break
            inspections.append(mission)
        if boundary is None:
            if not inspections and not prefix:return self._request(own,level)
            if not prefix and not state['admission_deferred']:return self._request(own,level)
            waiting=grants.get('waiting_place',{})
            if waiting.get('status')=='granted'and waiting.get('level')==level:
                slot=waiting['slot'];endpoints=self.wait_approaches[level,slot]
                terminal={'kind':'capacity_wait','level':level,'slot':slot}
            elif level==self.nav.homes[vehicle]['level']:
                home=self.nav.homes[vehicle];endpoints=[[home['arrival_xy_mm'],home['pose_mm_rad'][:2]]]
                terminal={'kind':'capacity_home','level':level}
            else:raise ValueError('No owned capacity endpoint on the current foreign floor')
        elif boundary['goal']['level'] != level:
            goal=boundary['goal']
            slot = self._wait(own, grants, goal['level'])
            if isinstance(slot, dict): return slot
            endpoints = self.wait_approaches[level, slot]
            terminal = {'kind': 'lift_wait', 'level': level, 'slot': slot, 'to_level': goal['level'],
                        'mission_id':boundary['mission_id'],'booking_id':boundary.get('booking_id')}
        else:
            home = self.nav.homes[vehicle]
            endpoints = [[home['arrival_xy_mm'], home['pose_mm_rad'][:2]]]
            terminal = {'kind': 'home', 'mission_id': boundary['mission_id']}
        initial = list(prefix or [own['pose_mm_rad'][:2]])
        if not prefix and self._home_observed(own):
            _append(initial, [self.nav.homes[vehicle]['departure_xy_mm']])
        choices = [self.variants[level, m['goal']['area']] for m in inspections]
        if basement_departure and choices:
            preferred = basement_departure['inspection_variant']
            variants = choices[0]
            if preferred < len(variants):
                choices[0] = [variants[preferred], *variants[:preferred], *variants[preferred+1:]]
        # Every choice follows source route/inspection pieces. Reject cusps,
        # rather than creating a stop at a mission or arbitrary waypoint.
        failures = []
        for selected in itertools.product(*choices) if choices else [()]:
            for ending in endpoints:
                points = copy.deepcopy(initial); zones = []; marks = copy.deepcopy(prefix_marks or [])
                try:
                    for mission, loop in zip(inspections, selected):
                        route = self.graph.route(level, points[-1], loop[0])
                        offset = _append(points, route['points_mm'])
                        zones.extend({**z, 'start_index': z['start_index']+offset, 'end_index': z['end_index']+offset} for z in route.get('zone_segments', []))
                        if basement_departure and mission is inspections[0]:
                            points = self._shorten_basement_departure(points, zones, len(initial), basement_departure)
                        before_loop=len(points)-1;_append(points, loop)
                        witness_index=len(points)-1
                        if hasattr(self.nav,'polygons'):
                            from building_fleet_navigation import point_in_polygon
                            polygon=self.nav.polygons[level][mission['goal']['area']]
                            witnesses=[i for i in range(before_loop+1,len(points))if point_in_polygon(points[i],polygon)]
                            if not witnesses:raise ValueError('Source inspection has no actual interior waypoint')
                            witness_index=witnesses[-1]
                        marks.append({'point_index': witness_index, 'event': 'inspection_completed',
                                      'mission_id': mission['mission_id'],
                                      'details': {'mission_id': mission['mission_id'], 'level': level,
                                                  'area': mission['goal']['area'], 'basis': mission['goal']['basis']}})
                    route = self.graph.route(level, points[-1], ending[0])
                    offset = _append(points, route['points_mm'])
                    zones.extend({**z, 'start_index': z['start_index']+offset, 'end_index': z['end_index']+offset} for z in route.get('zone_segments', []))
                    _append(points, ending)
                    if (getattr(self,'smooth_live_lift_wait',False) and terminal['kind']=='lift_wait'
                            and level==self.source['depot']['level'] and len(ending)==2):
                        approach = getattr(self, 'foyer_wait_approach', None)
                        smoothed = points
                        if self.port_paths is not None and approach and terminal['slot'] == approach['waiting_slot']:
                            smoothed = self._smooth_foyer_wait_approach(level, points, zones, marks,
                                                                      prefix_caps, approach)
                        points = (self._smooth_lift_wait_approach(level, points, zones, marks, prefix_caps)
                                  if smoothed is points else smoothed)
                    basement_return = getattr(self, 'basement_return', None)
                    if (basement_return and basement_departure and len(ending) == 2
                            and terminal['kind'] == 'lift_wait'
                            and terminal['slot'] == basement_departure['waiting_slot']):
                        points = self._shorten_basement_return(points, zones, marks, terminal['slot'],
                                                               basement_return['bypassed_waypoints'])
                    if terminal['kind']in('home','capacity_home')and prefix and grants.get('waiting_place',{}).get('status')=='granted':
                        waiting=grants['waiting_place']
                        marks.append({'point_index':len(prefix)-1,'event':'waiting_place_released',
                                      'details':{'level':waiting['level'],'slot':waiting['slot']}})
                    action = self._drive(vehicle, level, points, zones, marks, terminal, lift_phase=lift_phase,
                                         initial_yaw=own['pose_mm_rad'][2],corner_trim_caps=prefix_caps)
                    return action
                except ValueError as error:
                    failures.append(str(error))
        raise ValueError('No continuous own mission concatenation: '+str(failures[:3]))

    def _lift_metadata(self, grant, phase):
        required = ('slot', 'start_port', 'destination_port')
        if any(k not in grant for k in required):
            raise ValueError('Allocated own lift slot and active ports required')
        ports = {p['id']: p for p in self.ports.values()}
        if grant['start_port'] not in ports or grant['destination_port'] not in ports:
            raise ValueError('Only own source-active lift ports permitted')
        if ports[grant['start_port']]['level_id'] == ports[grant['destination_port']]['level_id']:
            raise ValueError('Own lift allocation must connect distinct source levels')
        if type(grant['slot']) is not int or not 0 <= grant['slot'] < len(self.cabin_lanes_override):
            raise ValueError('Own physical cabin slot required')
        return {'kind': phase, 'slot': grant['slot'], 'start_port': grant['start_port'],
                'destination_port': grant['destination_port'],
                'boarding_ready': grant.get('boarding_ready') is True,
                'exit_ready': grant.get('exit_ready') is True,
                'same_side': ports[grant['start_port']]['side'] == ports[grant['destination_port']]['side']}

    def _inside_align(self, port):
        direction = 1 if port['cabin_entry_mm'][0] > port['exit_eye_mm'][0] else -1
        bound = self.nav.cabin_interior_mm['min' if direction > 0 else 'max'][0]
        park_x = self.cabin_lanes_override[0]['pose_mm'][0]
        clear_wall = bound+direction*(self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm)
        clear_parked = park_x-direction*(self.nav.envelope['length_mm']+self.passing_gap_mm)
        if (clear_parked-clear_wall)*direction <= 0:
            raise ValueError('Cabin has no clear lane-shift strip before an occupied slot')
        return (clear_wall+clear_parked)/2, direction

    def _board(self, own, grant):
        if grant.get('boarding_ready') is not True:
            return {'kind': 'hold', 'reason': 'own_lift_boarding_not_ready', 'condition': 'own_open_active_port_and_slot'}
        meta = self._lift_metadata(grant, 'boarding')
        port = self.ports[own['level']]
        if port['id'] != meta['start_port']:
            raise ValueError('Boarding port differs from own floor')
        slot = meta['slot']
        if type(slot) is not int or not 0 <= slot < len(self.cabin_lanes_override):
            raise ValueError('Allocated source cabin lane required')
        park = self.cabin_lanes_override[slot]['pose_mm'][:2]
        if not _same(park, grant['cabin_pose_mm'][:2]):
            raise ValueError('Lift and mission planner disagree on physical cabin lane')
        if self.port_paths is not None:
            waiting_slot=next((i for i,wait in enumerate(self.nav.waits[own['level']])if _same(wait[:2],own['pose_mm_rad'][:2])),None)
            if waiting_slot is None:raise ValueError('Boarding requires the actual own source waiting pose')
            geometry=self.port_paths.boarding(own['level'],waiting_slot,slot,self.cabin_lanes_override)
            points, caps = geometry['points_mm'], geometry['corner_trim_caps']
            settings = getattr(self, 'ground_boarding', None)
            if own['level'] == 'KG' and getattr(self, 'basement_return', None):
                # Drive the checked basement exit geometry in the other direction.
                settings = self.basement_alighting
            elif settings is not None:
                if own['level'] != self.source['depot']['level']:
                    settings = None
                elif waiting_slot != settings['waiting_slot']:
                    settings = getattr(self, 'ground_boarding_alternate', None)
            diagonal = (settings is not None and waiting_slot == settings['waiting_slot']
                        and slot == settings['cabin_slot'])
            if diagonal:
                points = _diagonal_port_points(points[0], points[-2], park, port, settings)
                caps = []
            return self._drive(own['vehicle_id'],own['level'],points,[],[],
                {'kind':'cabin_park','slot':slot,'from_level':own['level'],
                 'to_level':next(p['level_id']for p in self.ports.values()if p['id']==meta['destination_port'])},
                lift_phase=meta,initial_yaw=own['pose_mm_rad'][2],corner_trim_caps=caps,
                variable_corner_speed=diagonal)
        x, _ = self._inside_align(port); centre_y = port['cabin_entry_mm'][1]
        outside = port['plane_x_mm']+(1 if port['exit_eye_mm'][0] > port['plane_x_mm'] else -1)*(port['wall_thickness_mm']/2+self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm)
        points = []; _append(points, [own['pose_mm_rad'][:2], [outside, own['pose_mm_rad'][1]],
                         [outside, centre_y], [x, centre_y], [x, park[1]], park])
        return self._drive(own['vehicle_id'], own['level'], points, [], [],
            {'kind': 'cabin_park', 'slot': slot, 'from_level': own['level'],
             'to_level': next(p['level_id'] for p in self.ports.values() if p['id'] == meta['destination_port'])},
            lift_phase=meta, initial_yaw=own['pose_mm_rad'][2])

    def _alight(self, own, grants):
        grant = grants.get('lift', {'status': 'none'})
        meta = self._lift_metadata(grant, 'alighting')
        if not meta['exit_ready']:
            return {'kind': 'hold', 'reason': 'own_lift_exit_not_ready', 'condition': 'own_open_destination_port'}
        port = self.ports[own['level']]
        if port['id'] != meta['destination_port']:
            raise ValueError('Exit port differs from observed own floor')
        if self.port_paths is not None:
            waiting=grants.get('waiting_place',{})
            if waiting.get('status')!='granted'or waiting.get('level')!=own['level']:
                raise ValueError('An arrival requires its own preallocated destination bay')
            slot=waiting['slot'];geometry=self.port_paths.alighting(own['level'],slot,meta['slot'],self.cabin_lanes_override)
            points, caps = geometry['points_mm'], geometry['corner_trim_caps']
            body_clear = geometry['body_clear_waypoint_on_reverse']
            settings = getattr(self, 'basement_alighting', None)
            diagonal = (settings is not None and own['level'] == 'KG' and meta['same_side']
                        and slot == settings['waiting_slot'] and meta['slot'] == settings['cabin_slot'])
            if diagonal:
                points = list(reversed(_diagonal_port_points(points[-1], points[1], points[0], port, settings)))
                caps = []
                # Acknowledge after the final landing blend. The runner
                # independently checks actual body clearance and its scan.
                body_clear = len(points)-2
            marks=[{'point_index':body_clear,'event':'lift_exited',
                'details':{'direction':'reverse'if meta['same_side']else'forward'}}]
            if meta['same_side']:
                return self._drive(own['vehicle_id'],own['level'],points,[],marks,
                    {'kind':'same_side_exit_stop','level':own['level'],'slot':slot},True,meta,
                    initial_yaw=own['pose_mm_rad'][2],corner_trim_caps=caps,
                    variable_corner_speed=diagonal)
            failures=[]
            for approach in self.wait_approaches[own['level'],slot]:
                prefix=copy.deepcopy(geometry['points_mm']);_append(prefix,list(reversed(approach)))
                try:return self._floor_leg(own,grants,prefix,marks,meta,geometry['corner_trim_caps'])
                except ValueError as error:failures.append(str(error))
            raise ValueError('No continuous own private exit approach: '+str(failures[:3]))
        x, direction = self._inside_align(port)
        outside_sign = -direction
        outside_x = port['plane_x_mm']+outside_sign*(port['wall_thickness_mm']/2+self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm)
        centre_y = port['cabin_entry_mm'][1]
        start = own['pose_mm_rad'][:2]
        points = []; _append(points, [start, [x, start[1]], [x, centre_y], [outside_x, centre_y]])
        if meta['same_side']:
            waiting = grants.get('waiting_place', {'status': 'none'})
            if waiting.get('status') != 'granted' or waiting.get('level') != own['level']:
                raise ValueError('A same-side arrival lacks its preallocated destination bay')
            slot = waiting['slot']; wait = self.nav.waits[own['level']][slot]
            _append(points, [[outside_x, wait[1]], wait[:2]])
            marks = [{'point_index': 3, 'event': 'lift_exited', 'details': {'direction': 'reverse'}}]
            return self._drive(own['vehicle_id'], own['level'], points, [], marks,
                {'kind': 'same_side_exit_stop', 'level': own['level'], 'slot': slot}, True, meta,
                initial_yaw=own['pose_mm_rad'][2])
        # Preserve the drive through body-clear and into the next inspection.
        # A public endpoint outside every bay is joined by source grid space;
        # the native/lift-stage audits must qualify this proposed prefix.
        hub = self.nav.road_hubs[own['level']]
        _append(points, [[hub[0], centre_y], hub])
        marks = [{'point_index': 3, 'event': 'lift_exited', 'details': {'direction': 'forward'}}]
        return self._floor_leg(own, grants, points, marks, meta)

    def next_action(self, own_snapshot, now, own_grants):
        self._snapshot(own_snapshot); _number(now)
        own = own_snapshot; state = self.states[own['vehicle_id']]
        if not isinstance(own_grants, dict) or set(own_grants)-{'waiting_place', 'lift'}:
            raise ValueError('Only own resource grants accepted')
        if state['active'] is not None:
            raise ValueError('A drive must return its observed action result before replanning')
        if state['done']:
            return {'kind': 'hold', 'reason': 'own_home_completed', 'condition': 'final_home'}
        if own['aboard']:
            return self._alight(own, own_grants)
        queue = [m for m in state['queue'] if m['mission_id'] not in state['completed']]
        if not queue:
            return self._request(own, own['level'])
        goal = queue[0]['goal']
        terminal = state['terminal']
        if terminal and terminal['kind']=='capacity_wait'and goal['level']!=own['level']:
            state['terminal']={'kind':'lift_wait','level':own['level'],'slot':terminal['slot'],
                'to_level':goal['level'],'mission_id':queue[0]['mission_id'],'booking_id':queue[0].get('booking_id')}
            terminal=state['terminal']
        if terminal and terminal['kind']in('same_side_exit_stop','capacity_wait'):
            slot = terminal['slot']; wait = self.nav.waits[own['level']][slot]
            if self.port_paths is not None:
                departure=self.port_paths.waiting_departure(own['level'],slot)
                if not _same(departure['points_mm'][0],own['pose_mm_rad'][:2]):
                    raise ValueError('Waiting departure must begin at the observed own bay')
                settings = getattr(self, 'basement_departure', None)
                waiting = own_grants.get('waiting_place', {})
                use_shorter_departure = (
                    settings and terminal['kind'] == 'same_side_exit_stop'
                    and own['level'] == goal['level'] == waiting.get('level') == 'KG'
                    and goal['kind'] == 'inspection_pass' and goal['area'] == settings['target_area']
                    and slot == settings['waiting_slot'] == waiting.get('slot')
                    and waiting.get('status') == 'granted' and waiting.get('role') == 'start'
                    and not departure['corner_trim_caps'])
                return self._floor_leg(own, own_grants, departure['points_mm'],
                                       prefix_caps=departure['corner_trim_caps'],
                                       basement_departure=settings if use_shorter_departure else None)
            port = self.ports[own['level']]; direction = 1 if math.cos(wait[2]) > 0 else -1
            clear_x = port['plane_x_mm']-direction*(port['wall_thickness_mm']/2+self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm)
            hub = self.nav.road_hubs[own['level']]
            prefix = []; _append(prefix, [own['pose_mm_rad'][:2], [clear_x, wait[1]], [clear_x, hub[1]], hub])
            return self._floor_leg(own, own_grants, prefix)
        if goal['kind'] == 'home' and goal['level'] == own['level'] and self._home_observed(own):
            state['home_confirmation'] = queue[0]['mission_id']
            return {'kind': 'complete', 'mission_id': queue[0]['mission_id']}
        if terminal and terminal['kind'] == 'lift_wait':
            lift = own_grants.get('lift', {'status': 'none'})
            if lift.get('status') == 'none':
                return {'kind': 'call_lift', 'from_level': own['level'], 'to_level': terminal['to_level'],
                        'mission_id':terminal['mission_id'],'booking_id':terminal.get('booking_id')}
            return self._board(own, lift)
        return self._floor_leg(own, own_grants)

    def on_action_result(self, vehicle, action, result, now):
        state = self._state(vehicle); _number(now)
        if not isinstance(result, dict):
            raise ValueError('Observed action result required')
        if action['kind'] == 'drive':
            if state['active'] != action:
                raise ValueError('Drive result does not match this vehicle active action')
            if result.get('status') not in ('arrived', 'completed', 'accepted'):
                raise ValueError('Unconfirmed drive arrival cannot advance mission state')
            state['active'] = None; state['terminal'] = copy.deepcopy(action['terminal'])
        elif action['kind']=='request_mission':
            if result.get('status')in('pending_admission','already_queued','already_queued_foreign'):state['requested']=False
            if result.get('status')=='pending_admission':state['admission_deferred']=True
        elif action['kind'] == 'complete':
            if state['home_confirmation'] != action.get('mission_id'):
                raise ValueError('Home completion was not issued from an observed own home pose')
            if result.get('status') not in ('completed', 'accepted'):
                raise ValueError('Home completion needs explicit observed result')
            state['completed'].add(action['mission_id']); state['done'] = True

    def on_event(self, vehicle, event, details, now):
        state = self._state(vehicle); _number(now)
        if event == 'inspection_completed':
            mid = details.get('mission_id')
            mission = state['seen'].get(mid)
            if mission is None or mission['goal']['kind'] != 'inspection_pass':
                raise ValueError('Inspection event must identify an assigned own mission')
            goal = mission['goal']
            if any(details.get(k) != goal[k] for k in ('level', 'area', 'basis')):
                raise ValueError('Inspection event identity differs from own mission')
            active = state['active']
            if active is None or not any(m['event'] == event and m.get('mission_id') == mid for m in active['markers']):
                raise ValueError('Inspection completion was not an event of the active drive')
            state['completed'].add(mid)
