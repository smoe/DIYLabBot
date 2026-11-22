"""BF01 synthetic exclusive resources and source-bound lift service.

No service observation is a real sensor result. Vehicle-facing grants contain
only that vehicle's resource, slot and port; never another vehicle's pose.
"""
import copy
import math


def finite(value, minimum=0):
    if type(value) not in (float, int) or not math.isfinite(value) or value < minimum:
        raise ValueError('Finite in-range value required')
    return value


class ResourceServices:
    """FIFO resource tokens; at most one narrow resource held per vehicle."""
    KINDS = frozenset({'passage', 'room', 'depot'})

    def __init__(self, resources, waiting_places=None, maximum_queue=20):
        if not isinstance(resources, dict) or any(not isinstance(k, str) or not k or v not in self.KINDS for k, v in resources.items()):
            raise ValueError('Named passage/room/depot resources required')
        if type(maximum_queue) is not int or not 1 <= maximum_queue <= 20:
            raise ValueError('Bounded queue required')
        self.resources = dict(resources); self.maximum_queue = maximum_queue
        self.owners = {}; self.holds = {}; self.queues = {}; self.requests = {}; self.events = []
        self.waiting_places = copy.deepcopy(waiting_places or {}); self.wait_owners = {}; self.wait_holds = {}
        self.exit_wait_holds = {}; self.waiting_events = []
        self.next_wait_holds={};self.bookings={};self.mission_bookings={}
        self.active_bookings={};self.next_bookings={};self.wait_bindings={};self.booking_events=[]

    def request(self, vehicle, resource, now):
        finite(now)
        if resource not in self.resources or not isinstance(vehicle, str) or not vehicle:
            raise ValueError('Known resource and vehicle required')
        if vehicle in self.holds:
            if self.holds[vehicle] != resource:
                raise ValueError('Release the current narrow token before requesting another')
            return self.own_grants(vehicle)
        if vehicle in self.requests and self.requests[vehicle][0] != resource:
            raise ValueError('At most one queued narrow request per vehicle')
        queue = self.queues.setdefault(resource, [])
        if vehicle not in queue:
            if len(queue) >= self.maximum_queue:
                return {'status':'rejected_full', 'resource':resource}
            queue.append(vehicle); self.requests[vehicle] = (resource, now)
        self._grant(resource, now)
        return self.own_grants(vehicle)

    def _grant(self, resource, now):
        queue = self.queues.get(resource, [])
        if resource not in self.owners and queue:
            vehicle = queue.pop(0); _, requested = self.requests.pop(vehicle)
            self.owners[resource] = vehicle; self.holds[vehicle] = resource
            self.events.append({'vehicle_id':vehicle, 'event':'passage_granted', 'time_s':now,
                                'resource':resource, 'wait_s':now-requested})

    def release(self, vehicle, resource, now):
        finite(now)
        if self.owners.get(resource) != vehicle:
            raise ValueError('Only the owner can release a resource')
        del self.owners[resource]; del self.holds[vehicle]; self._grant(resource, now)

    def own_grants(self, vehicle):
        if vehicle in self.holds:
            return {'status':'granted', 'resource':self.holds[vehicle]}
        if vehicle in self.requests:
            return {'status':'waiting', 'resource':self.requests[vehicle][0]}
        return {'status':'none'}

    def request_waiting_place(self, vehicle, level):
        if level not in self.waiting_places:
            raise ValueError('Source-derived waiting places required at each level')
        if vehicle in self.wait_holds:
            held_level, index = self.wait_holds[vehicle]
            if held_level != level:
                raise ValueError('Release the old lift waiting place first')
            return {'status':'granted', 'level':level, 'slot':index, 'pose_mm':copy.deepcopy(self.waiting_places[level][index])}
        for index, place in enumerate(self.waiting_places[level]):
            key = (level, index)
            if key not in self.wait_owners:
                self.wait_owners[key] = vehicle; self.wait_holds[vehicle] = key
                return {'status':'granted', 'level':level, 'slot':index, 'pose_mm':copy.deepcopy(place)}
        return {'status':'rejected_full', 'level':level}

    def _waiting_grant(self, key, role, booking_id=None):
        level, index = key
        result={'status':'granted', 'level':level, 'slot':index,
                'pose_mm':copy.deepcopy(self.waiting_places[level][index]), 'role':role}
        if booking_id is not None:result.update(booking_id=booking_id,mission_id=self.bookings[booking_id]['mission_id'])
        return result

    def own_waiting_grants(self, vehicle):
        """Return only this vehicle's start/exit reservation, never peer data."""
        return {'start':self._waiting_grant(self.wait_holds[vehicle], 'start',self.wait_bindings.get(vehicle))
                    if vehicle in self.wait_holds else {'status':'none'},
                'destination':self._waiting_grant(self.exit_wait_holds[vehicle], 'destination',self.active_bookings.get(vehicle))
                    if vehicle in self.exit_wait_holds else {'status':'none'},
                'lookahead_destination':self._waiting_grant(self.next_wait_holds[vehicle], 'lookahead_destination',self.next_bookings.get(vehicle))
                    if vehicle in self.next_wait_holds else {'status':'none'}}

    def _free_bay(self,level):
        return next(((level,i)for i in range(len(self.waiting_places[level]))if(level,i)not in self.wait_owners),None)

    def can_book_mission(self,vehicle,start_level,destination_level,source_role='start'):
        if start_level==destination_level or start_level not in self.waiting_places or destination_level not in self.waiting_places:return False
        if source_role=='arrival':
            source=self.exit_wait_holds.get(vehicle)
            return (source is not None and source[0]==start_level and vehicle in self.active_bookings
                    and self.wait_owners.get(source)==vehicle
                    and self.bookings[self.active_bookings[vehicle]]['state']=='boarded'
                    and vehicle not in self.next_bookings and self._free_bay(destination_level)is not None)
        if source_role!='start':raise ValueError('Only current or incoming own source roles are supported')
        if vehicle in self.active_bookings or vehicle in self.exit_wait_holds:return False
        source=self.wait_holds.get(vehicle)
        if source is not None and self.wait_owners.get(source)!=vehicle:raise ValueError('Waiting ownership mismatch')
        return ((source is None or source[0]==start_level)and(source is not None or self._free_bay(start_level)is not None)
                and self._free_bay(destination_level)is not None)

    def _booking_event(self,event,booking,now):
        self.booking_events.append({'event':event,'time_s':now,**copy.deepcopy(booking)})

    def _bound_event(self,event,vehicle,key,role,booking,now):
        self.waiting_events.append({'event':event,'vehicle_id':vehicle,'level':key[0],'slot':key[1],
            'role':role,'booking_id':booking['booking_id'],'mission_id':booking['mission_id'],'time_s':now})

    def book_mission(self,vehicle,mission_id,start_level,destination_level,now,source_role='start'):
        """Fence all endpoints before issuing this immutable foreign mission."""
        finite(now)
        if not isinstance(mission_id,str)or not mission_id:raise ValueError('Named boundary mission required')
        if mission_id in self.mission_bookings:
            old=self.bookings[self.mission_bookings[mission_id]]
            if any(old[k]!=v for k,v in [('vehicle_id',vehicle),('from_level',start_level),('to_level',destination_level),('source_role',source_role)]):
                raise ValueError('A mission booking cannot change identity or route')
            return copy.deepcopy(old)
        if not self.can_book_mission(vehicle,start_level,destination_level,source_role):return None
        booking_id='booking-'+str(len(self.bookings)+1)
        if source_role=='arrival':
            start=self.exit_wait_holds[vehicle];end=self._free_bay(destination_level)
            self.next_wait_holds[vehicle]=end;self.next_bookings[vehicle]=booking_id;self.wait_owners[end]=vehicle
            state='conditional'
        else:
            start=self.wait_holds.get(vehicle)or self._free_bay(start_level);end=self._free_bay(destination_level)
            new_start=vehicle not in self.wait_holds
            if vehicle not in self.wait_holds:
                self.wait_holds[vehicle]=start;self.wait_owners[start]=vehicle
            self.exit_wait_holds[vehicle]=end;self.wait_owners[end]=vehicle;self.active_bookings[vehicle]=booking_id
            self.wait_bindings[vehicle]=booking_id;state='active'
        booking={'booking_id':booking_id,'vehicle_id':vehicle,'mission_id':mission_id,
            'from_level':start_level,'to_level':destination_level,'source_role':source_role,
            'start':{'level':start[0],'slot':start[1]},'destination':{'level':end[0],'slot':end[1]},
            'state':state,'created_s':now,'activated_s':now if state=='active'else None}
        self.bookings[booking_id]=booking;self.mission_bookings[mission_id]=booking_id
        if source_role=='start':self._bound_event('waiting_granted'if new_start else'waiting_bound',vehicle,start,'start',booking,now)
        self._bound_event('waiting_granted',vehicle,end,'lookahead_destination'if state=='conditional'else'destination',booking,now)
        self._booking_event('booking_fenced',booking,now)
        return copy.deepcopy(booking)

    def require_mission_booking(self,vehicle,mission_id,start_level,destination_level):
        bid=self.mission_bookings.get(mission_id);booking=self.bookings.get(bid)
        if (booking is None or self.active_bookings.get(vehicle)!=bid or booking['state']!='active'
                or booking['vehicle_id']!=vehicle or booking['from_level']!=start_level or booking['to_level']!=destination_level
                or self.wait_holds.get(vehicle)!=(booking['start']['level'],booking['start']['slot'])
                or self.exit_wait_holds.get(vehicle)!=(booking['destination']['level'],booking['destination']['slot'])
                or any(self.wait_owners.get((p['level'],p['slot']))!=vehicle for p in(booking['start'],booking['destination']))):
            raise ValueError('An active mission-bound source and destination booking is required')
        return copy.deepcopy(booking)

    def mark_mission_boarded(self,vehicle,mission_id,now):
        finite(now);bid=self.active_bookings.get(vehicle);booking=self.bookings.get(bid)
        if booking is None or booking['mission_id']!=mission_id or booking['state']!='active':raise ValueError('Own active boarding mission required')
        self.require_mission_booking(vehicle,mission_id,booking['from_level'],booking['to_level'])
        booking['state']='boarded';self._booking_event('booking_boarded',booking,now)

    def admit_lift_trip(self, vehicle, start_level, destination_level, now):
        """Atomically hold source and destination bays before a lift request.

        An already occupied current bay may be reused, but a destination claim
        is never acquired after departure. Both levels participate in one
        admission decision, eliminating partial cross-level hold-and-wait.
        The exit claim stays fenced until an actual body-clear observation
        promotes it to the vehicle's current-floor waiting reservation.
        """
        finite(now)
        if (not isinstance(vehicle,str) or not vehicle or start_level==destination_level
                or start_level not in self.waiting_places or destination_level not in self.waiting_places):
            raise ValueError('Known own vehicle and distinct source waiting levels required')
        current=self.wait_holds.get(vehicle);destination=self.exit_wait_holds.get(vehicle)
        if current is not None and current[0]!=start_level:
            raise ValueError('Release or promote the previous waiting grant before a new trip')
        if destination is not None and destination[0]!=destination_level:
            raise ValueError('An allocated destination bay cannot silently change')
        def available(level,old):
            if old is not None:
                if self.wait_owners.get(old)!=vehicle:raise ValueError('Waiting ownership mismatch')
                return old
            return next(((level,i)for i in range(len(self.waiting_places[level]))
                         if(level,i)not in self.wait_owners),None)
        start=available(start_level,current);end=available(destination_level,destination)
        if start is None or end is None:
            return {'status':'rejected_full','level':start_level if start is None else destination_level}
        for old,key,role,holds in ((current,start,'start',self.wait_holds),
                                   (destination,end,'destination',self.exit_wait_holds)):
            if old is None:
                self.wait_owners[key]=vehicle;holds[vehicle]=key
                self.waiting_events.append({'event':'waiting_granted','vehicle_id':vehicle,
                    'level':key[0],'slot':key[1],'role':role,'time_s':now})
        return {'status':'granted',**self.own_waiting_grants(vehicle)}

    def promote_destination_waiting_place(self,vehicle,level,now):
        finite(now)
        if vehicle in self.wait_holds or vehicle not in self.exit_wait_holds:
            raise ValueError('Promotion requires released source bay and allocated destination')
        key=self.exit_wait_holds[vehicle]
        if key[0]!=level or self.wait_owners.get(key)!=vehicle:
            raise ValueError('Destination promotion must match the observed own floor')
        bid=self.active_bookings.get(vehicle);next_id=self.next_bookings.get(vehicle)
        if bid is not None and self.bookings[bid]['state']!='boarded':
            raise ValueError('Body-clear promotion requires observed prior boarding')
        if next_id is not None:
            booking=self.bookings[next_id]
            if (booking['start']['level'],booking['start']['slot'])!=key or booking['state']!='conditional':
                raise ValueError('Conditional future source differs from observed arrival')
        del self.exit_wait_holds[vehicle];self.wait_holds[vehicle]=key
        self.waiting_events.append({'event':'waiting_promoted','vehicle_id':vehicle,
            'level':key[0],'slot':key[1],'role':'start','time_s':now})
        bid=self.active_bookings.pop(vehicle,None)
        if bid is not None:
            booking=self.bookings[bid]
            self.waiting_events[-1].update(booking_id=bid,mission_id=booking['mission_id'])
            booking['state']='arrived';self.wait_bindings[vehicle]=bid;self._booking_event('booking_arrived',booking,now)
        next_id=self.next_bookings.pop(vehicle,None)
        if next_id is not None:
            booking=self.bookings[next_id]
            end=self.next_wait_holds.pop(vehicle);self.exit_wait_holds[vehicle]=end
            self.active_bookings[vehicle]=next_id;self.wait_bindings[vehicle]=next_id
            booking.update(state='active',activated_s=now)
            self._bound_event('waiting_role_activated',vehicle,end,'destination',booking,now)
            self._bound_event('waiting_bound',vehicle,key,'start',booking,now)
            self._booking_event('booking_activated',booking,now)
        return self._waiting_grant(key,'start',self.wait_bindings.get(vehicle))

    def release_waiting_place(self, vehicle, now=None):
        if now is not None:finite(now)
        if vehicle not in self.wait_holds:
            raise ValueError('Vehicle has no lift waiting place')
        bound=self.wait_bindings.get(vehicle)
        if bound is not None and self.bookings[bound]['state']=='active':
            raise ValueError('An active trip source stays fenced until observed cabin parking')
        key = self.wait_holds.pop(vehicle); del self.wait_owners[key]
        bid=self.wait_bindings.pop(vehicle,None)
        if now is not None:
            self.waiting_events.append({'event':'waiting_released','vehicle_id':vehicle,
                'level':key[0],'slot':key[1],'role':'start','time_s':now})
            if bid is not None:self.waiting_events[-1].update(booking_id=bid,mission_id=self.bookings[bid]['mission_id'])


def cabin_lanes(interior_bounds_mm, footprint_mm, clearance_mm, maximum=2):
    """Fit no more than two X-oriented vehicles in measured interior bounds.

    The caller must obtain the interior from the native cabin cut, rather than
    its exterior bounding box. The result is not a surveyed capacity claim.
    """
    if type(maximum) is not int or maximum not in (1, 2):
        raise ValueError('Only one or two synthetic cabin lanes supported')
    if set(interior_bounds_mm) != {'min', 'max'} or len(footprint_mm) != 2:
        raise ValueError('Native cabin interior and XY footprint required')
    lo, hi = interior_bounds_mm['min'], interior_bounds_mm['max']
    if len(lo) != 3 or len(hi) != 3:
        raise ValueError('Three-dimensional native interior bounds required')
    for x in lo+hi: finite(x, -math.inf)
    length, width = [finite(v) for v in footprint_mm]; reserve = finite(clearance_mm)
    if length <= 0 or width <= 0 or any(b <= a for a, b in zip(lo, hi)):
        raise ValueError('Positive cabin dimensions and footprint required')
    if hi[0]-lo[0] < length+2*reserve or hi[1]-lo[1] < width+2*reserve:
        raise ValueError('No vehicle fits the cabin with declared clearance')
    count = 2 if maximum == 2 and hi[1]-lo[1] >= 2*width+3*reserve else 1
    middle_x, middle_y = (lo[0]+hi[0])/2, (lo[1]+hi[1])/2
    spacing = width+reserve
    return [{'slot':index, 'pose_mm':[middle_x, middle_y+(index-(count-1)/2)*spacing, lo[2]],
             'footprint_mm':list(footprint_mm), 'clearance_mm':reserve} for index in range(count)]


class LiftService:
    """Explicit acknowledgement-gated lift with collective directional batches.

    Time alone never boards, parks or exits a vehicle, or clears a door line.
    ``tick`` consumes an explicitly supplied synthetic light-curtain observation.
    A batch can stop only at destinations allocated to its parked passengers.
    """
    def __init__(self, elevator, door_duration_s, lanes, initial_level=None):
        self.speed = finite(elevator['speed_mm_s']); self.door_duration = finite(door_duration_s)
        if self.speed <= 0 or self.door_duration <= 0 or not lanes or len(lanes) > 2:
            raise ValueError('Positive source lift timing and proven cabin lanes required')
        self.ports = {p['id']:copy.deepcopy(p) for p in elevator['ports'] if p['active']}
        if not self.ports:
            raise ValueError('Active source lift ports required')
        self.level_z = {}
        for port in self.ports.values():
            z = finite(port['z_mm'], -math.inf); level = port['level_id']
            if level in self.level_z and self.level_z[level] != z:
                raise ValueError('Conflicting source lift level heights')
            self.level_z[level] = z
        self.level = initial_level or elevator['reference_level']
        if self.level not in self.level_z:
            raise ValueError('Active initial level required')
        self.lanes = copy.deepcopy(lanes); self.z = self.level_z[self.level]
        self.reference_z = finite(elevator.get('reference_z_mm', self.level_z[elevator['reference_level']]), -math.inf)
        self.now = 0; self.phase = 'idle'; self.phase_started = 0; self.transition = None
        self.doors_open = True; self.queue = []; self.requests = {}; self.batch = []
        self.events = []; self.schedule = []; self.trips = 0; self.occupied_trips = 0
        self.wait_times = []; self.maximum_occupancy = 0; self.total_trip_capacity = 0; self.total_trip_occupancy = 0

    def _port(self, level, side=None):
        candidates = [p for p in self.ports.values() if p['level_id'] == level and (side is None or p['side'] == side)]
        if len(candidates) != 1:
            raise ValueError('An unambiguous active port side is required')
        return candidates[0]

    def _event(self, vehicle, name, **details):
        self.events.append({'vehicle_id':vehicle, 'time_s':self.now, 'event':name, **details})

    def request(self, vehicle, start_level, destination_level, now, start_side=None, destination_side=None):
        finite(now)
        if now < self.now or start_level == destination_level:
            raise ValueError('Chronological request between distinct levels required')
        start = self._port(start_level, start_side); end = self._port(destination_level, destination_side)
        if vehicle in self.requests:
            old = self.requests[vehicle]
            if old['start_port'] != start['id'] or old['end_port'] != end['id']:
                raise ValueError('Active lift request cannot be silently changed')
            return self.own_grant(vehicle)
        if len(self.requests) >= 20:
            return {'status':'rejected_full'}
        self.requests[vehicle] = {'vehicle_id':vehicle, 'start_port':start['id'], 'end_port':end['id'],
            'requested_s':now, 'slot':None, 'boarded':False, 'parked':False, 'exited':False}
        self.queue.append(vehicle)
        self.events.append({'vehicle_id':vehicle, 'time_s':now, 'event':'lift_call', 'start_port':start['id'], 'destination_port':end['id']})
        return self.own_grant(vehicle)

    def own_grant(self, vehicle):
        r = self.requests.get(vehicle)
        if r is None:
            return {'status':'none'}
        grant = {'status':'waiting' if r['slot'] is None else 'assigned', 'start_port':r['start_port'], 'destination_port':r['end_port']}
        if r['slot'] is not None:
            grant.update(slot=r['slot'], cabin_pose_mm=copy.deepcopy(self.lanes[r['slot']]['pose_mm']))
        # A narrow physical doorway is crossed by one allocated lane at a
        # time. These own grants use only explicit parked/body-clear acks,
        # never peer positions or a fleet-wide traversal schedule.
        boarding=next((v for v in self.batch if not self.requests[v]['parked']),None)
        alighting=next((v for v in self.batch if self.requests[v]['parked']and not self.requests[v]['exited']
                        and self.ports[self.requests[v]['end_port']]['level_id']==self.level),None)
        grant['boarding_ready'] = (r['slot'] is not None and self.phase == 'boarding' and self.doors_open
                                   and self.ports[r['start_port']]['level_id'] == self.level and not r['boarded']
                                   and boarding==vehicle)
        grant['exit_ready'] = (r['parked'] and not r['exited'] and self.phase == 'alighting' and self.doors_open
                              and self.ports[r['end_port']]['level_id'] == self.level and alighting==vehicle)
        return grant

    def _phase(self, name):
        self.phase = name; self.phase_started = self.now

    def _start_travel(self, target, purpose):
        if self.doors_open:
            raise ValueError('Lift cannot travel with open doors')
        z0, z1 = self.z, self.level_z[target]
        duration = 1.875*abs(z1-z0)/self.speed
        self.transition = {'start_s':self.now, 'end_s':self.now+duration,
            'from_z_mm':z0, 'to_z_mm':z1, 'to_level':target, 'purpose':purpose}
        self.schedule.append({'kind':'travel', **self.transition})
        self.trips += 1; boarded = sum(self.requests[v]['parked'] and not self.requests[v]['exited'] for v in self.batch)
        self.occupied_trips += bool(boarded); self.total_trip_capacity += len(self.lanes); self.total_trip_occupancy += boarded
        for vehicle in self.batch:
            if self.requests[vehicle]['parked'] and not self.requests[vehicle]['exited']:
                self._event(vehicle, 'lift_departed', destination_level=target)
        self._phase('travelling')

    def _begin_batch(self):
        if not self.queue:
            return
        first = self.requests[self.queue[0]]; start = self.ports[first['start_port']]
        direction = math.copysign(1, self.level_z[self.ports[first['end_port']]['level_id']]-start['z_mm'])
        chosen = []
        for vehicle in self.queue:
            r = self.requests[vehicle]; target = self.ports[r['end_port']]
            if r['start_port'] == first['start_port'] and direction*(target['z_mm']-start['z_mm']) > 0:
                chosen.append(vehicle)
                if len(chosen) == len(self.lanes): break
        self.batch = chosen
        for index, vehicle in enumerate(chosen):
            self.queue.remove(vehicle); self.requests[vehicle]['slot'] = index
            self._event(vehicle, 'lift_slot_assigned', slot=index, start_port=first['start_port'])
        if self.level == start['level_id']:
            self._phase('boarding' if self.doors_open else 'opening_pickup')
        else:
            self._phase('closing_pickup')

    def tick(self, now, door_line_clear):
        finite(now)
        if now < self.now or type(door_line_clear) is not bool:
            raise ValueError('Monotonic clock and explicit synthetic door observation required')
        self.now = now
        if self.phase == 'idle': self._begin_batch()
        if self.phase.startswith('closing'):
            if not door_line_clear:
                # No progress toward door closure without a continuously clear line.
                self.phase_started = now; return
            if self.phase == 'closing_passengers' and any(not self.requests[v]['parked'] for v in self.batch if not self.requests[v]['exited']):
                raise ValueError('Cannot close before all assigned vehicles report parked')
            if now-self.phase_started >= self.door_duration-1e-9:
                self.doors_open = False
                self.schedule.append({'kind':'doors', 'start_s':self.phase_started, 'end_s':round(self.phase_started+self.door_duration,9), 'level':self.level, 'target':'closed'})
                if self.phase == 'closing_pickup':
                    target = self.ports[self.requests[self.batch[0]]['start_port']]['level_id']; purpose = 'pickup'
                else:
                    destinations = {self.ports[self.requests[v]['end_port']]['level_id'] for v in self.batch if not self.requests[v]['exited']}
                    target = min(destinations, key=lambda level:abs(self.level_z[level]-self.z)); purpose = 'passengers'
                self._start_travel(target, purpose)
        elif self.phase == 'travelling':
            t = self.transition; u = min(1, (now-t['start_s'])/(t['end_s']-t['start_s']))
            self.z = t['from_z_mm']+(t['to_z_mm']-t['from_z_mm'])*(10*u**3-15*u**4+6*u**5)
            if u >= 1:
                self.level = t['to_level']; self.z = t['to_z_mm']; self._phase('opening_pickup' if t['purpose'] == 'pickup' else 'opening_exit')
        elif self.phase.startswith('opening') and now-self.phase_started >= self.door_duration-1e-9:
            self.doors_open = True
            self.schedule.append({'kind':'doors', 'start_s':self.phase_started, 'end_s':round(self.phase_started+self.door_duration,9), 'level':self.level, 'target':'open'})
            self._phase('boarding' if self.phase == 'opening_pickup' else 'alighting')

    def board(self, vehicle, own_scan_clear):
        r = self.requests.get(vehicle)
        if type(own_scan_clear) is not bool or not own_scan_clear or not r or not(self.own_grant(vehicle).get('boarding_ready')or r.get('boarded')) or self.phase!='boarding':
            return {'status':'rejected_not_ready'}
        if r['boarded']:
            return {'status':'accepted', 'slot':r['slot']}
        r['boarded'] = True; self._event(vehicle, 'lift_boarded', slot=r['slot'])
        return {'status':'accepted', 'slot':r['slot']}

    def park(self, vehicle):
        r = self.requests.get(vehicle)
        if not r or not r['boarded'] or self.phase != 'boarding' or not self.doors_open:
            raise ValueError('Parking requires confirmed boarding with open doors')
        if r['parked']:
            return
        r['parked'] = True; self.wait_times.append(self.now-r['requested_s'])
        self.maximum_occupancy = max(self.maximum_occupancy, sum(self.requests[v]['parked'] for v in self.batch))
        if all(self.requests[v]['parked'] for v in self.batch): self._phase('closing_passengers')

    def exit(self, vehicle, own_scan_clear):
        r = self.requests.get(vehicle)
        if type(own_scan_clear) is not bool or not own_scan_clear or not r or not self.own_grant(vehicle).get('exit_ready'):
            return {'status':'rejected_not_ready'}
        start, end = self.ports[r['start_port']], self.ports[r['end_port']]
        result = {'status':'accepted', 'port':end['id'], 'direction':'reverse' if start['side'] == end['side'] else 'forward'}
        r['exited'] = True; self._event(vehicle, 'lift_exited', port=end['id'], direction=result['direction'])
        exiting = [v for v in self.batch if self.ports[self.requests[v]['end_port']]['level_id'] == self.level]
        if all(self.requests[v]['exited'] for v in exiting):
            if all(self.requests[v]['exited'] for v in self.batch):
                for v in self.batch: del self.requests[v]
                self.batch = []; self._phase('idle')
            else:
                self._phase('closing_passengers')
        return result

    def attached_pose(self, vehicle):
        r = self.requests.get(vehicle)
        if not r or not r['boarded'] or r['exited']:
            raise ValueError('Only an aboard vehicle is absolutely cabin-bound')
        result = copy.deepcopy(self.lanes[r['slot']]['pose_mm']); result[2] += self.z-self.reference_z
        return result

    def snapshot(self):
        # Service status goes to the event stream/control room, not controllers.
        fraction = 1.0 if self.doors_open else 0.0
        if self.phase.startswith(('opening', 'closing')):
            u = min(1, max(0, (self.now-self.phase_started)/self.door_duration))
            fraction = 10*u**3-15*u**4+6*u**5
            if self.phase.startswith('closing'): fraction = 1-fraction
        return {'time_s':self.now, 'phase':self.phase, 'level':self.level, 'z_mm':self.z,
                'doors_open':self.doors_open and self.phase not in ('closing_pickup','closing_passengers'),
                'door_open_fraction':fraction,
                'active_ports':[p['id'] for p in self.ports.values() if p['level_id'] == self.level] if fraction > 0 else []}

    def statistics(self):
        return {'trips':self.trips, 'occupied_trips':self.occupied_trips, 'maximum_occupancy':self.maximum_occupancy,
                'mean_wait_s':sum(self.wait_times)/len(self.wait_times) if self.wait_times else None,
                'maximum_wait_s':max(self.wait_times, default=None),
                'utilization':self.total_trip_occupancy/self.total_trip_capacity if self.total_trip_capacity else 0,
                'pending_requests':len(self.requests)}
