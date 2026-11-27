"""Opt-in continuous BF01 patrol and empty-vehicle recruitment exercise.

The seeded reference runner remains unchanged. This adapter reuses its exact
50-ms control loop, own scans, stopping proofs, geometry checks and services.
Pickup/delivery are acknowledged visits to existing inspection targets; they
do not represent a load, handover, material booking or workflow execution.
"""
import copy
import bisect
import math
import re
import uuid

from building_fleet_dispatch import Dispatcher
from building_fleet_control import F
from building_fleet_motion import Path
from building_fleet_runner import WorldRunner
from building_fleet_model import control_step_s, patrol_source


SNAPSHOT_FORMAT = 'solidcraftbot.building-fleet-live-snapshot/1'
_REQUEST_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z')
_MAX_JOBS = 1000
_MAX_MESSAGES = 100000
_MAX_PVA_POINTS = 1000000


class PatrolStorageLimit(RuntimeError):
    """Visible session boundary; retained controller evidence is never cropped."""


def target_key(value):
    """Accept a declared target identity, never arbitrary scene coordinates."""
    if isinstance(value, dict) and set(value) == {'level', 'area'}:
        value = (value['level'], value['area'])
    if (not isinstance(value, (tuple, list)) or len(value) != 2 or
            any(not isinstance(v, str) or not v for v in value)):
        raise ValueError('A declared level/area target is required')
    return tuple(value)


class PatrolDispatcher(Dispatcher):
    """Received coverage and own ETA bids only; no peer/world pose access."""
    def __init__(self, source, homes):
        super().__init__(source, homes)
        self.last_visit = {key: None for key in self.targets}
        self.clock_s = 0.
        self.jobs = {}
        self.vehicle_jobs = {}
        self.job_missions = {}
        self.resume_targets = {}

    def ready_to_return(self, now):
        return False

    def request_job(self, pickup, delivery, request_id, now):
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('Finite nonnegative request time required')
        pickup, delivery = target_key(pickup), target_key(delivery)
        if pickup not in self.targets or delivery not in self.targets:
            raise ValueError('Pickup and delivery must be existing BF01 targets')
        if pickup == delivery:
            raise ValueError('The recruitment exercise needs different targets')
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise ValueError('A bounded stable request ID is required')
        if request_id in self.jobs:
            row = self.jobs[request_id]
            if (target_key(row['pickup']), target_key(row['delivery'])) != (pickup, delivery):
                raise ValueError('A request ID cannot change pickup or delivery')
            return copy.deepcopy(row)
        if len(self.jobs) >= _MAX_JOBS:
            raise ValueError('Recruitment session job limit reached; retain IDs and start a new session')
        row = {'request_id': request_id, 'created_s': now, 'status': 'queued',
               'pickup': {'level': pickup[0], 'area': pickup[1]},
               'delivery': {'level': delivery[0], 'area': delivery[1]},
               'vehicle_id': None, 'eta_s': None, 'bids': [], 'pickup_mission_id': None,
               'delivery_mission_id': None}
        self.jobs[request_id] = row
        return copy.deepcopy(row)

    def queued_jobs(self):
        return [row for row in self.jobs.values() if row['status'] == 'queued']

    def recruit(self, request_id, bids, now):
        """Atomically choose one finite own bid; repeated calls cannot steal it."""
        row = self.jobs[request_id]
        if row['status'] != 'queued':
            return copy.deepcopy(row)
        accepted = []
        seen = set()
        for bid in bids:
            if (not isinstance(bid, dict) or set(bid) != {'vehicle_id', 'eta_s'} or
                    bid['vehicle_id'] not in self.homes or bid['vehicle_id'] in seen or
                    type(bid['eta_s']) not in (int, float) or
                    not math.isfinite(bid['eta_s']) or bid['eta_s'] < 0):
                raise ValueError('Unique finite own arrival-time bids are required')
            seen.add(bid['vehicle_id'])
            if bid['vehicle_id'] not in self.vehicle_jobs:
                accepted.append(copy.deepcopy(bid))
        accepted.sort(key=lambda bid: (bid['eta_s'], bid['vehicle_id']))
        row['bids'] = accepted
        if accepted:
            winner = accepted[0]['vehicle_id']
            self.vehicle_jobs[winner] = request_id
            row.update(vehicle_id=winner, recruited_s=now, status='recruited', eta_s=accepted[0]['eta_s'])
        return copy.deepcopy(row)

    def assign(self, vehicle_id, own_level, now, lift_wait_available=True, *,
               admissible_levels=None, book_goal=None):
        if vehicle_id not in self.homes or not math.isfinite(now) or now < 0:
            raise ValueError('Known own vehicle and finite nonnegative time required')
        allowed = set(admissible_levels) if admissible_levels is not None else None
        request_id = self.vehicle_jobs.get(vehicle_id)
        stage = None
        if request_id is not None:
            job = self.jobs[request_id]
            stage = next((s for s in ('pickup', 'delivery') if job[s+'_mission_id'] is None), None)
            if stage is None:
                return None
            key = target_key(job[stage])
            if allowed is not None and key[0] not in allowed:
                return None
            goal = copy.deepcopy(self.targets[key])
        else:
            # Existing committed patrols finish. Do not add lookahead work
            # while an unassigned process is waiting for a safe diversion.
            if self.queued_jobs():
                return None
            candidates = [key for key in self.targets if
                          (key[0] in allowed if allowed is not None else
                           lift_wait_available or key[0] == own_level)]
            resume = self.resume_targets.get(vehicle_id)
            if resume is not None:
                candidates = [key for key in candidates if key == resume]
            if not candidates:
                return None
            def priority(key):
                last = self.last_visit[key]
                return (last if last is not None else -math.inf, self.planned[key])
            best = min(map(priority, candidates))
            candidates = sorted(key for key in candidates if priority(key) == best)
            key = self.random.choices(candidates,
                    weights=[self.targets[key]['weight'] for key in candidates], k=1)[0]
            goal = copy.deepcopy(self.targets[key])
        identifier = 'mission-'+str(self.counter+1)
        booking = None
        if book_goal is not None and goal['level'] != own_level:
            booking = book_goal(identifier, copy.deepcopy(goal))
            if booking is None:
                return None
        self.counter += 1
        self.planned[key] += 1
        message = {'mission_id': identifier, 'vehicle_id': vehicle_id,
                   'assigned_s': now, 'goal': goal}
        if book_goal is not None:
            message.update(booking_id=booking['booking_id'] if booking is not None else None,
                           source_level=own_level)
        self.missions[identifier] = message
        if stage is not None:
            job[stage+'_mission_id'] = identifier
            job[stage+'_issued_s'] = now
            self.job_missions[identifier] = (request_id, stage)
        return copy.deepcopy(message)

    def acknowledge(self, vehicle_id, mission_id):
        super().acknowledge(vehicle_id, mission_id)
        if mission_id in self.job_missions:
            request_id, stage = self.job_missions[mission_id]
            row = self.jobs[request_id]
            row.setdefault(stage+'_acknowledged_s', self.clock_s)
            if row['status'] != 'completed':
                row['status'] = stage+'_acknowledged'

    def receive_completion(self, vehicle_id, mission_id):
        if mission_id in self.job_missions:
            request_id, stage = self.job_missions[mission_id]
            if stage == 'delivery' and 'pickup_completed_s' not in self.jobs[request_id]:
                raise ValueError('Delivery cannot precede received pickup completion')
        fresh = super().receive_completion(vehicle_id, mission_id)
        if not fresh:
            return False
        goal = self.missions[mission_id]['goal']
        if goal['kind'] == 'inspection_pass':
            self.last_visit[goal['level'], goal['area']] = self.clock_s
        if mission_id in self.job_missions:
            request_id, stage = self.job_missions[mission_id]
            row = self.jobs[request_id]
            row[stage+'_completed_s'] = self.clock_s
            row['status'] = 'pickup_observed' if stage == 'pickup' else 'completed'
            if stage == 'delivery':
                row['completed_s'] = self.clock_s
                del self.vehicle_jobs[vehicle_id]
        return True

    def coverage(self):
        return [{**row, 'last_visit_s': self.last_visit[row['level'], row['area']]}
                for row in super().coverage()]


class PatrolWorldRunner(WorldRunner):
    """The existing BF01 world, stepped live with a separate patrol policy."""
    departures = None

    def enable_private_departures(self):
        from building_fleet_patrol_departure import PatrolDepartures
        if self.departures is not None:
            raise RuntimeError('Private departure service already initialized')
        self.departures = PatrolDepartures(self)

    def check_depot_invariant(self):
        if self.departures is None:
            return super().check_depot_invariant()
        self.depot_invariant_checks += self.departures.audit()

    def release_resource(self, identity, resource, now):
        if self.departures is not None:
            self.departures.check_release(identity, resource)
        super().release_resource(identity, resource, now)
        if self.departures is not None:
            self.departures.released(identity, resource)

    def finish_drive(self, identity):
        super().finish_drive(identity)
        ticket = self.departures.ticket if self.departures is not None else None
        row = self.vehicles[identity]
        # A patrol can receive another job at home. Complete the already
        # reserved handover before the old owner can acquire its next leg.
        if (ticket and ticket['leader'] == identity and row['driver'] is None
                and row['phase'] == 'home' and row['last_terminal']['kind'] == 'home'):
            self.release_resource(identity, ticket['resource'], self.now)

    def __init__(self, source, nav, graph, catalog, planner, profile, **kwargs):
        if (profile.get('format') != 'solidcraftbot.building-fleet-patrol/1' or
                profile.get('patrol', {}).get('termination') != 'explicit_stop' or
                profile.get('patrol', {}).get('selection') != 'oldest_received_visit' or
                profile.get('patrol', {}).get('startup') not in ('first_received_camera_frames','own_received_camera_frame') or
                profile.get('recruitment', {}).get('pickup_delivery') != 'empty_inspection_visits'):
            raise ValueError('Explicit continuous empty-patrol profile required')
        self.profile = copy.deepcopy(profile)
        self.variable_corner_speed = profile['patrol'].get('corner_timing') == 'variable_progress'
        from building_fleet_runtime_cache import bind_active_fleet
        prepared = {'nav': nav, 'graph': graph, 'catalog': catalog, 'planner': planner}
        if 'geometry_checker' in kwargs:
            prepared['geometry_checks'] = kwargs['geometry_checker']
        active = bind_active_fleet(prepared, source, profile)
        if 'geometry_checks' in active:
            kwargs['geometry_checker'] = active['geometry_checks']
        nav, graph, catalog, planner = (active[key] for key in ('nav', 'graph', 'catalog', 'planner'))
        # The archival /2 audit contract still has the 50 ms clock.
        runtime_source = patrol_source(source, profile) if kwargs.get('output_dir') is None else source
        super().__init__(runtime_source, nav, graph, catalog, planner, **kwargs)
        self.dt = control_step_s(runtime_source)
        if self.dt > .05:
            self.planner.smooth_live_lift_wait = True
            self.planner.ground_boarding = self.profile['patrol'].get('ground_boarding')
            self.planner.basement_alighting = self.profile['patrol'].get('basement_alighting')
            self.planner.basement_departure = self.profile['patrol'].get('basement_departure')
        self._last_control_start_s = -.05
        self.dispatcher = PatrolDispatcher(source, nav.homes)
        self.session_id = uuid.uuid4().hex
        self.paused = False
        self.step_index = 0
        self._scene_history = {}
        self._capture_scenes = {}
        self._camera_frames = {}
        self._live_lift_rows = {}
        self._lift_discontinuity_s = -math.inf
        self._deferred_patrol = {}
        self._startup_ready = False
        self._startup_seen_frames = set()
        self._first_perception_on_scan = self._startup_policy() == 'own_received_camera_frame'

    def _startup_policy(self):
        return getattr(self,'profile',{}).get('patrol',{}).get('startup','first_received_camera_frames')

    def _own_startup_ready(self,identity):
        if self._startup_policy()=='first_received_camera_frames':return self._startup_ready
        return identity in getattr(self,'_startup_seen_frames',set())or identity in self._camera_frames

    def request_mission(self,identity,level,now):
        if self._startup_policy()=='own_received_camera_frame'and not self._own_startup_ready(identity):
            return {'status':'pending_own_camera'}
        return super().request_mission(identity,level,now)

    def set_paused(self, paused):
        if type(paused) is not bool:
            raise ValueError('Explicit pause state required')
        self.paused = paused

    def request_job(self, pickup, delivery, request_id):
        return self.dispatcher.request_job(pickup, delivery, request_id, self.now)

    def eligible(self, identity):
        """Only observed stationary boundaries without unfinished commitments."""
        if not self._own_startup_ready(identity):return False
        row = self.vehicles[identity]
        state = self.planner.states[identity]
        if (identity in self.dispatcher.vehicle_jobs or row['driver'] is not None or
                row['aboard'] or row['mission_pending'] or state['active'] is not None or
                row['phase'] not in ('home', 'capacity_home', 'capacity_wait', 'landing')):
            return False
        queued = [m for m in state['queue'] if m['mission_id'] not in state['completed']]
        if any(m['goal']['kind'] != 'inspection_pass' or m['goal']['level'] != row['level'] or
               m['mission_id'] in self.dispatcher.job_missions for m in queued):
            return False
        # Conditional bookings and actual cabin/waiting obligations are not
        # canceled to make a vehicle appear available for a process.
        return (identity not in self.resources.active_bookings and
                identity not in self.resources.next_bookings and
                self.lift.own_grant(identity).get('status') == 'none')

    def _departure(self, identity):
        own = self.own(identity)
        if own['home']:
            return [own['pose_mm_rad'][:2], self.nav.homes[identity]['departure_xy_mm']]
        state = self.planner.states[identity]
        terminal = state['terminal'] or {}
        if terminal.get('kind') in ('capacity_wait', 'same_side_exit_stop'):
            slot = terminal['slot']
            if self.planner.port_paths is not None:
                return self.planner.port_paths.waiting_departure(own['level'], slot)['points_mm']
            return list(reversed(self.planner.wait_approaches[own['level'], slot][0]))
        return [own['pose_mm_rad'][:2]]

    def _travel_estimate(self, points):
        """Source-map route ETA estimate, not a guaranteed arrival deadline.

        The conservative source zone speed and source acceleration/jerk ramp
        allowance rank bids without relaxing or recompiling actual motion.
        Actual motion still uses the original PVA compiler and scan cap.
        """
        points = [list(p) for i, p in enumerate(points) if not i or p != points[i-1]]
        if len(points) < 2:
            return 0.
        path = Path(points, self.planner.trim_mm)
        limits = self.source['motion']['empty_linear_limits']
        velocity = min(limits['velocity_mm_s'], self.source['motion']['zone_velocity_mm_s'])
        ramp = velocity/limits['acceleration_mm_s2']+limits['acceleration_mm_s2']/limits['jerk_mm_s3']
        return path.length/velocity+2*ramp

    def own_bid(self, identity, pickup):
        """Return this vehicle's scalar route bid; never another vehicle's pose."""
        if not self.eligible(identity):
            return None
        key = target_key(pickup)
        if key not in self.nav.inspections:
            return None
        own = self.own(identity)
        level = own['level']
        prefix = self._departure(identity)
        lift_time = 0.
        try:
            if key[0] != level:
                if not self.resources.can_book_mission(identity, level, key[0], 'start'):
                    return None
                approaches = self.planner.wait_approaches
                start_times = []
                for slot in range(len(self.nav.waits[level])):
                    for ending in approaches[level, slot]:
                        route = self.graph.route(level, prefix[-1], ending[0])
                        start_times.append(self._travel_estimate(prefix+route['points_mm'][1:]+ending[1:]))
                start_time = min(start_times)
                # Published lift-service state is aggregated. It reveals no
                # peer poses and does not constitute boarding permission.
                lift_time = (start_time+1.875*abs(self.lift.z-self.nav.level_z[level])/self.lift.speed+
                    1.875*abs(self.nav.level_z[key[0]]-self.nav.level_z[level])/self.lift.speed+
                    4*self.lift.door_duration+
                    len(self.lift.requests)*(2*self.lift.door_duration+
                        1.875*abs(self.nav.level_z[key[0]]-self.nav.level_z[level])/self.lift.speed))
                level = key[0]
                prefix = [self.nav.road_hubs[level]]
            candidates = []
            for loop in self.planner.variants[key]:
                route = self.graph.route(level, prefix[-1], loop[0])
                candidates.append(lift_time+self._travel_estimate(prefix+route['points_mm'][1:]+loop[1:]))
            eta = min(candidates)
        except (ValueError, KeyError):
            return None
        return {'vehicle_id': identity, 'eta_s': eta}

    def recruit_pending(self):
        for job in self.dispatcher.queued_jobs():
            bids = [bid for identity in self.vehicles
                    if (bid := self.own_bid(identity, job['pickup'])) is not None]
            result = self.dispatcher.recruit(job['request_id'], bids, self.now)
            identity = result['vehicle_id']
            if identity is not None:
                self._defer_local_patrol(identity)

    def _defer_local_patrol(self, identity):
        """Preserve received, unstarted own local intents behind a process job.

        No mission is canceled or reissued. Active curves, pending downlinks
        and foreign reservations are never changed by this priority switch.
        """
        row = self.vehicles[identity]
        state = self.planner.states[identity]
        if row['driver'] is not None or row['aboard'] or row['mission_pending'] or state['active'] is not None:
            raise RuntimeError('Patrol deferral requires an observed stationary own boundary')
        queued = [m for m in state['queue'] if m['mission_id'] not in state['completed']]
        if any(m['goal']['kind'] != 'inspection_pass' or m['goal']['level'] != row['level'] or
               m['mission_id'] in self.dispatcher.job_missions for m in queued):
            raise RuntimeError('Foreign and process commitments cannot be deferred')
        deferred = self._deferred_patrol.setdefault(identity, [])
        known = {mission['mission_id'] for mission in deferred}
        deferred.extend(copy.deepcopy(mission) for mission in queued if mission['mission_id'] not in known)
        moved = {mission['mission_id'] for mission in queued}
        state['queue'] = [mission for mission in state['queue'] if mission['mission_id'] not in moved]
        state['requested'] = False

    def _restore_local_patrol(self):
        for identity in list(self._deferred_patrol):
            if identity in self.dispatcher.vehicle_jobs:
                continue
            state = self.planner.states[identity]
            deferred = self._deferred_patrol[identity]
            if deferred and self.vehicles[identity]['level'] != deferred[0]['goal']['level']:
                goal = deferred[0]['goal']
                # An originally local assignment must stay local. A process
                # may finish on another floor, so return with a NEW fenced
                # mission before restoring the old immutable own intent.
                self.dispatcher.resume_targets[identity] = (goal['level'], goal['area'])
                continue
            self.dispatcher.resume_targets.pop(identity, None)
            present = {mission['mission_id'] for mission in state['queue']}
            state['queue'].extend(mission for mission in self._deferred_patrol.pop(identity)
                if mission['mission_id'] not in present and mission['mission_id'] not in state['completed'])

    def idle_action(self, identity):
        """Admit a home departure before preparing its expensive nominal curve.

        Queued vehicles can stage on privately checked straights with an
        ordered handover. Entry to the shared corridor still needs its token.
        """
        row = self.vehicles[identity]
        if self._startup_policy()=='own_received_camera_frame'and not self._own_startup_ready(identity):
            row['hold_reason']='await_own_received_camera_frame'
            row['hold_condition']='first_actual_own_perception_delivery'
            return
        state = self.planner.states[identity]
        queued = any(mission['mission_id'] not in state['completed'] for mission in state['queue'])
        if (not row.get('done', False) and row['driver'] is None and not row['aboard'] and
                not row['mission_pending'] and queued and self.own(identity)['home']):
            home = self.nav.homes[identity]
            resource = self.depot_aliases[home['level'], home['area']]
            grant = self.resources.request(identity, resource, self.now)
            self.drain_resource_events()
            if grant['status'] != 'granted':
                if self.departures is not None and self.departures.try_depart(identity,resource):
                    return
                row['hold_reason'] = 'resource_wait'
                row['hold_condition'] = 'own_depot_departure_grant'
                return
        return super().idle_action(identity)

    def _states(self, *, diagnostics=True):
        states = []
        for identity, row in sorted(self.vehicles.items()):
            driver = row['driver']
            state = {'id': identity, 'pose_xyz_mm': [*row['pose_mm_rad'][:2], row['z_mm']],
                 'yaw_rad': row['pose_mm_rad'][2], 'level_id': row['level'],
                 'mode': row['phase'], 'attached_cabin': row['aboard'],
                 'job_id': self.dispatcher.vehicle_jobs.get(identity),
                 'own_route_horizon_mm': getattr(driver, 'certified_horizon_mm', None),
                 'awaiting_checked_continuation': getattr(driver, 'awaiting_continuation', False)}
            if diagnostics:
                # Resource ownership is presentation-only and never enters a vehicle observation.
                request = self.resources.requests.get(identity)
                requested = request[0] if request else None
                held = self.resources.holds.get(identity)
                reason = getattr(driver, 'reason', None)
                hold_reason, condition = None, None
                if driver is None:
                    hold_reason, condition = row['hold_reason'], row['hold_condition']
                elif driver.mode == 'waiting':
                    hold_reason = reason
                    condition = {'await_checked_continuation': 'checked_continuation_at_observed_pva',
                                 'resource_wait': 'own_exclusive_resource_grant',
                                 'next_step_stop_unproven': 'checked_next_step_and_stop'}.get(
                                     reason, 'fresh_clear_anonymous_scan')
                state.update(controller_mode=getattr(driver, 'mode', None), controller_reason=reason,
                             progress_mm=getattr(driver, 'y', None), goal_mm=getattr(driver, 'goal', None),
                             hold_reason=hold_reason, hold_condition=condition, held_resource=held,
                             requested_resource=requested, resource_holder=self.resources.owners.get(requested or held),
                             queue_position=self.resources.queues[requested].index(identity)+1 if request else None)
                if self.departures is not None and driver is not None:
                    # Retained only when the last executed step consumed this exact stop witness.
                    fallback=getattr(driver,'_fallback',None)
                    if fallback and fallback['start_s']==self._last_control_start_s and driver.now==self.now:
                        clock=fallback['clock']
                        state['executed_step_stop']={'start_s':fallback['start_s'],'end_s':driver.now,
                            'captured_s':fallback['anchor']['captured_s'],
                            'stop_progress_mm':fallback['origin_mm']+clock.points[-1][F[0]][0],
                            'horizon_mm':driver.certified_horizon_mm}
                if self.departures is not None and self.departures.staged(identity):
                    state['private_departure_horizon_mm'] = driver.certified_horizon_mm
                    if driver.mode == 'waiting' and abs(driver.y-driver.certified_horizon_mm)<1e-5:
                        state.update(hold_reason='resource_wait',hold_condition='observed_corridor_handover')
            states.append(state)
        return states

    def _lift_state(self):
        values = self.lift_values()
        elevator_id = self.nav.mesh.manifest['elevator']['object_id']
        return {'z_mm': values[elevator_id],
                'door_values': {key: value for key, value in values.items() if key != elevator_id}}

    def _remember_lift_phase(self):
        """Retain original source quintics, never linearize cabin or doors."""
        phase = self.lift.phase
        if phase == 'travelling':
            row = {'kind': 'travel', **copy.deepcopy(self.lift.transition)}
            key = ('travel', row['start_s'])
        elif phase.startswith(('opening', 'closing')):
            target = 'open' if phase.startswith('opening') else 'closed'
            initial = 'closed' if target == 'open' else 'open'
            objects = {obj['id']: obj for obj in self.nav.mesh.manifest['objects']
                       if obj.get('mechanism') == 'lift_door'}
            ids = {ident for port in self.lift.ports.values()
                   if port['level_id'] == self.lift.level
                   for ident in port.get('door_object_ids', [])}
            row = {'kind': 'doors', 'start_s': self.lift.phase_started,
                   'end_s': self.lift.phase_started+self.lift.door_duration,
                   'level': self.lift.level, 'target': target,
                   'from_values': {ident: objects[ident]['states'][initial] for ident in ids},
                   'target_values': {ident: objects[ident]['states'][target] for ident in ids}}
            key = ('doors', row['start_s'], self.lift.level, target)
        else:
            return
        self._live_lift_rows[key] = row
        self._live_lift_rows = {key: value for key, value in self._live_lift_rows.items()
                                if value['end_s'] >= self.now-2.}

    def executed_window(self):
        """One second of actual PVA knots and source lift polynomials only.

        A polynomial's original endpoint can be later than the executed end;
        its domain is still restricted to this window by the display. Door
        curtain resets may create a source-state discontinuity, so that short
        interval falls back to observed snapshots instead of interpolation.
        """
        history_s = 2. if self.dt>.05 else 1.
        if self.now <= 0 or self.now-self._lift_discontinuity_s < history_s:
            return None
        start = max(0., round(self.now-history_s, 3))
        initial = self._scene_history.get(start)
        if initial is None:
            return None
        trajectories = []
        for identity, vehicle in sorted(self.vehicles.items()):
            episodes = []
            for episode in vehicle['episodes']:
                if episode['end_s'] <= start or episode['start_s'] >= self.now:
                    continue
                times = [point['time_s'] for point in episode['points']]
                index = max(0, bisect.bisect_right(times, start)-1)
                points = episode['points'][index:]
                if len(points) < 2:
                    continue
                episodes.append({'mode': episode['mode'], 'level_id': episode['level_id'],
                    'attached_cabin': episode['attached_cabin'],
                    'start_s': points[0]['time_s'], 'end_s': points[-1]['time_s'],
                    'points': copy.deepcopy(points)})
            if not episodes or episodes[0]['start_s'] > start or episodes[-1]['end_s'] < self.now:
                return None
            trajectories.append({'vehicle_id': identity, 'episodes': episodes})
        return {'start_s': start, 'end_s': self.now,
            'levels': [{'id': level, 'z_mm': z} for level, z in self.nav.level_z.items()],
            'trajectories': trajectories, 'lift_initial_state': copy.deepcopy(initial['lift']),
            'lift_schedule': copy.deepcopy(sorted((row for row in self._live_lift_rows.values()
                if row['start_s'] <= self.now and row['end_s'] >= start),
                key=lambda row: row['start_s']))}

    def observe(self, step):
        self._scene_history[self.now] = {'states': self._states(diagnostics=False), 'lift': self._lift_state()}
        sequences = {identity: row['capture_seq'] for identity, row in self.vehicles.items()}
        if self.dt>.05:
            now_ms=round(self.now*1000)
            previous_ms=round(self._last_control_start_s*1000)
            result=super().observe(step,capture_due=now_ms%100==50,
                heartbeat_due=now_ms//1000!=previous_ms//1000,
                perception_due=now_ms//500!=previous_ms//500)
        else:
            result=super().observe(step)
        for identity, row in self.vehicles.items():
            if row['capture_seq'] == sequences[identity]:
                continue
            reference = identity+'-camera-'+str(row['capture_seq'])
            capture = self.camera_captures[reference]
            scene = self._scene_history.get(capture['captured_s'])
            if scene is None:
                raise RuntimeError('Camera capture lacks its original simultaneous scene')
            self._capture_scenes[reference] = scene
        horizon = max(2. if self.dt>.05 else 1., 2*self.sensor['stale_after_s'])+self.sensor['latency_s']+self.dt
        self._scene_history = {at: scene for at, scene in self._scene_history.items()
                               if at >= self.now-horizon}
        return result

    def deliver_messages(self, now):
        self.dispatcher.clock_s = now
        before = len(self.control_room.messages)
        super().deliver_messages(now)
        self._restore_local_patrol()
        for message in self.control_room.messages[before:]:
            if message['kind'] != 'perception':
                continue
            reference = message['payload']['camera_ref']
            capture = self.camera_captures[reference]
            scene = self._capture_scenes[reference]
            self._camera_frames[message['vehicle_id']] = {
                'vehicle_id': message['vehicle_id'], 'camera_ref': reference,
                **copy.deepcopy(capture), 'received_s': message['received_s'],
                **copy.deepcopy(scene)}
        # Keep received originals and undelivered radio captures only. A lift
        # blackout retains its captures until actual delivery after reconnect.
        retained = {frame['camera_ref'] for frame in self._camera_frames.values()}
        for _, _, _, message in self.uplink.pending:
            if message['kind'] == 'perception':
                retained.add(message['payload']['camera_ref'])
        for messages in self.uplink.buffer.values():
            retained.update(m['payload']['camera_ref'] for m in messages if m['kind'] == 'perception')
        self._capture_scenes = {ref: scene for ref, scene in self._capture_scenes.items() if ref in retained}
        self.camera_captures = {ref: capture for ref, capture in self.camera_captures.items() if ref in retained}

    def _can_use_long_step(self):
        return (self.lift.phase=='idle' and not self.lift.requests
                and all(not row['aboard'] and row['level']==self.source['depot']['level']
                        and not (row['action'] or {}).get('lift_phase')
                        for row in self.vehicles.values()))

    def capture_interval(self,start,end,curves,previous,lift):
        # Evaluate anonymous lidar against simultaneous executed poses.
        # A long interval is admitted only with stationary lift geometry.
        final_lift=self.lift_snapshot()
        if any(final_lift[key]!=value for key,value in lift.items() if key!='time_s'):
            raise RuntimeError('Long-step scan requires stationary lift state')
        for stamp in range(round(start*1000)+50,round(end*1000),100):
            at=stamp/1000
            truth={}
            for identity,row in previous.items():
                jet=curves[identity].evaluate(at)
                truth[identity]={**row,'pose_mm':list(jet[F[0]])}
                self.capture_history[identity][at]={
                    'pose_mm_rad':truth[identity]['pose_mm'][:], 'level':row['level'],
                    'z_mm':row['z_mm'], 'aboard':False,
                    'own_rest':not any(jet[F[1]]) and not any(jet[F[2]])}
            states=self._states(diagnostics=False)
            for state in states:
                row=truth[state['id']]
                state.update(pose_xyz_mm=[*row['pose_mm'][:2],row['z_mm']],yaw_rad=row['pose_mm'][2])
            self._scene_history[at]={'states':states,'lift':self._lift_state()}
            self.capture_scans(truth,at,lift)

    def step(self):
        """Advance one presentation tick through fully checked control intervals."""
        if self.paused:
            return self.now
        end=round(self.now+self.dt,3)
        while self.now<end:
            self._step_once(end)
        return self.now

    def _step_once(self,end):
        points = sum(len(episode['points']) for row in self.vehicles.values()
                     for episode in row['episodes'])
        points += sum(len(row['driver'].recorded) for row in self.vehicles.values()
                      if row['driver'] is not None)
        if len(self.control_room.messages) >= _MAX_MESSAGES or points >= _MAX_PVA_POINTS:
            raise PatrolStorageLimit('Live session storage limit reached; retained evidence remains intact. '
                                     'Start a new session to continue the development exercise.')
        self.deliver_messages(self.now)
        if not hasattr(self,'_startup_seen_frames'):self._startup_seen_frames=set()
        self._startup_seen_frames.update(self._camera_frames)
        if not self._startup_ready:
            self._startup_ready = set(self.vehicles) <= self._startup_seen_frames
            if not self._startup_ready and self._startup_policy()=='first_received_camera_frames':
                # Once-only readiness is an observed communication condition,
                # not a demonstration pause or fabricated camera receipt.
                self.observe(self.step_index)
                return self._advance_tick(end)
        self.recruit_pending()
        for identity in sorted(self.vehicles,
                               key=lambda identity: (identity not in self.dispatcher.vehicle_jobs, identity)):
            if not self._own_startup_ready(identity):continue
            if self.vehicles[identity]['aboard'] and not self.vehicles[identity]['mission_pending']:
                self.request_mission(identity, self.vehicles[identity]['level'], self.now)
            self.idle_action(identity)
        self.observe(self.step_index)
        return self._advance_tick(end)

    def _advance_tick(self,target):
        end=target if (self.dt>.05 and self._can_use_long_step()
                       and round(self.now*1000)%400==0) else round(self.now+.05,3)
        self._last_control_start_s=self.now
        phase = getattr(self.lift, 'phase', None)
        before = (phase, getattr(self.lift, 'phase_started', None))
        if phase is not None:
            self._remember_lift_phase()
        self.advance_world(end)
        if phase is not None:
            if (phase.startswith('closing') and self.lift.phase == phase and
                    self.lift.phase_started != before[1]):
                self._lift_discontinuity_s = self.now
            self._remember_lift_phase()
        self.step_index += 1
        return self.now

    def snapshot(self):
        """Bounded presentation state; no prediction or full-run qualification."""
        return {'format': SNAPSHOT_FORMAT, 'session_id': self.session_id,
                'vehicle_count': len(self.vehicles),
                'model_time_s': self.now, 'paused': self.paused,
                'startup_ready': self._startup_ready,
                'startup_phase': ('active' if self._startup_ready else 'independent_vehicle_startup'
                    if self._startup_policy()=='own_received_camera_frame'else 'awaiting_first_received_camera_frames'),
                'background_preparation': (self._background_preparation.snapshot()
                    if getattr(self,'_background_preparation',None)is not None else None),
                'states': self._states(), 'lift': self._lift_state(),
                'executed_window': self.executed_window(),
                'room_route_object_ids': sorted(self.route_door_ids),
                'targets': [{'level': key[0], 'area': key[1], 'basis': row['basis']}
                            for key, row in self.dispatcher.targets.items()],
                'jobs': copy.deepcopy(list(self.dispatcher.jobs.values())),
                'coverage': self.dispatcher.coverage(),
                'camera_frames': copy.deepcopy(list(self._camera_frames.values())),
                'received_messages': copy.deepcopy(self.control_room.messages[-200:]),
                'qualification': copy.deepcopy(self.profile.get('qualification', {})),
                'recruitment_scope': 'empty target visits; no loads, handovers, material ledger or workflow binding',
                'storage_limits': {'jobs': _MAX_JOBS, 'received_messages': _MAX_MESSAGES,
                                   'retained_pva_points': _MAX_PVA_POINTS},
                'eta_basis': 'source-map route length, source speed/acceleration/jerk allowance and aggregated lift timing; estimate, not guaranteed arrival'}
