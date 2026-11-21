"""Deterministic synthetic radio and a received-message-only BF01 control room.

The radio is not a transport protocol or a device adapter.  Payload poses are
the sender's estimates; they are never supplied to another vehicle.
"""
import copy
import hashlib
import heapq
import json
import math
from pathlib import Path

FORMAT = 'solidcraftbot.fleet-telemetry/1'
EVENTS = frozenset('mission_assigned leg_started area_entered door_passed inspection_completed yield_retreat home_reached obstacle_detected protective_stop resumed passage_wait passage_granted lift_call lift_slot_assigned lift_boarded lift_departed lift_exited comm_lost comm_restored'.split())
FIELDS = frozenset('seq vehicle_id sent_s received_s kind payload delivered_late'.split())


def finite(value, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError('Finite number in range required')
    return value


def identifier(value):
    if not isinstance(value, str) or not value.startswith('BF') or len(value) != 4 or not value[2:].isdigit() or not 1 <= int(value[2:]) <= 20:
        raise ValueError('BF01..BF20 vehicle ID required')
    return value


def pose(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError('Own [x, y, yaw] pose required')
    for number in value:
        finite(number, -math.inf)


def validate_payload(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError('Telemetry payload must be an object')
    if kind == 'heartbeat':
        if set(payload) != {'pose_mm', 'level', 'area', 'mode', 'speed_mm_s'}:
            raise ValueError('Unexpected heartbeat fields')
        pose(payload['pose_mm']); finite(payload['speed_mm_s'])
        if any(not isinstance(payload[k], str) or not payload[k] for k in ('level', 'area', 'mode')):
            raise ValueError('Heartbeat labels required')
    elif kind == 'event':
        if set(payload) != {'event', 'details'} or payload['event'] not in EVENTS or not isinstance(payload['details'], dict):
            raise ValueError('Unknown event or event fields')
        if payload['event'] == 'inspection_completed':
            details = payload['details']
            if set(details) not in ({'level','area'},{'level','area','mission_id'}) or any(not isinstance(details[k],str)or not details[k]for k in details):
                raise ValueError('Inspection coverage requires a reported level and area')
    elif kind == 'perception':
        if set(payload) != {'captured_s', 'pose_mm', 'level', 'scan', 'camera_ref'}:
            raise ValueError('Unexpected perception fields')
        finite(payload['captured_s']); pose(payload['pose_mm'])
        if not isinstance(payload['level'], str) or not payload['level'] or not isinstance(payload['camera_ref'], str) or not payload['camera_ref']:
            raise ValueError('Perception level and camera reference required')
        scan = payload['scan']
        if not isinstance(scan, dict) or set(scan) != {'return_count', 'nearest_mm', 'bearing_rad'} or type(scan['return_count']) is not int or scan['return_count'] < 0:
            raise ValueError('Anonymous scan summary required')
        if scan['return_count']:
            finite(scan['nearest_mm']); finite(scan['bearing_rad'], -math.inf)
        elif scan['nearest_mm'] is not None or scan['bearing_rad'] is not None:
            raise ValueError('Empty scan has no nearest return')
    else:
        raise ValueError('Unknown telemetry kind')
    # No NaN, custom objects, or shared mutable world references survive the port.
    json.dumps(payload, allow_nan=False)
    return payload


def validate(message):
    if not isinstance(message, dict) or set(message) != FIELDS:
        raise ValueError('Unexpected telemetry envelope')
    identifier(message['vehicle_id'])
    if type(message['seq']) is not int or message['seq'] < 1 or type(message['delivered_late']) is not bool:
        raise ValueError('Positive sequence and explicit delivery flag required')
    finite(message['sent_s']); finite(message['received_s'])
    if message['received_s'] < message['sent_s']:
        raise ValueError('Receipt cannot precede sending')
    validate_payload(message['kind'], message['payload'])
    if message['kind'] == 'perception' and message['payload']['captured_s'] > message['sent_s']:
        raise ValueError('Perception cannot be captured after it was sent')
    return message


class Channel:
    """Seeded arithmetic jitter, ordered per sender, with explicit blackouts.

    A blackout buffers messages without changing their original sender time.
    Its beginning/end are external simulated connectivity observations, not a
    timeout that authorizes a physical action.  ``deliver`` is the only output
    port used by the control room.
    """
    def __init__(self, latency_range_s, seed, late_after_s):
        if not isinstance(latency_range_s, (list, tuple)) or len(latency_range_s) != 2:
            raise ValueError('Latency interval required')
        self.low, self.high = [finite(v) for v in latency_range_s]
        if self.low > self.high or type(seed) is not int:
            raise ValueError('Ordered latency and integer seed required')
        self.seed = seed; self.late_after = finite(late_after_s)
        self.sequence = {}; self.connected = {}; self.buffer = {}; self.pending = []
        self.last_due = {}; self.sent_time = {}; self.outages = {}; self.events = []
        self.latencies = []; self.delivered_late = 0; self.maximum_buffered = 0

    def _latency(self, vehicle, seq):
        digest = hashlib.sha256(f'{self.seed}:{vehicle}:{seq}'.encode()).digest()
        fraction = int.from_bytes(digest[:8], 'big') / (2**64-1)
        return self.low+(self.high-self.low)*fraction

    def _schedule(self, message, release_s):
        vehicle = message['vehicle_id']
        due = max(release_s+self._latency(vehicle, message['seq']), self.last_due.get(vehicle, release_s))
        self.last_due[vehicle] = due
        heapq.heappush(self.pending, (due, vehicle, message['seq'], message))

    def emit(self, vehicle, kind, payload, sent_s):
        identifier(vehicle); finite(sent_s); validate_payload(kind, payload)
        if sent_s < self.sent_time.get(vehicle, 0):
            raise ValueError('Sender time moved backwards')
        self.sent_time[vehicle] = sent_s
        sequence = self.sequence.get(vehicle, 0)+1; self.sequence[vehicle] = sequence
        message = {'seq': sequence, 'vehicle_id': vehicle, 'sent_s': sent_s,
                   'received_s': sent_s, 'kind': kind, 'payload': copy.deepcopy(payload), 'delivered_late': False}
        if self.connected.get(vehicle, True):
            self._schedule(message, sent_s)
        else:
            self.buffer.setdefault(vehicle, []).append(message)
            self.maximum_buffered = max(self.maximum_buffered, sum(map(len, self.buffer.values())))
        return sequence

    def set_connected(self, vehicle, connected, now):
        identifier(vehicle); finite(now)
        if type(connected) is not bool or now < self.sent_time.get(vehicle, 0):
            raise ValueError('Connectivity must be explicit and chronological')
        if self.connected.get(vehicle, True) == connected:
            return
        self.connected[vehicle] = connected
        if not connected:
            self.outages[vehicle] = now
            # An in-flight packet cannot be delivered during the blackout.
            retained = []
            while self.pending:
                due, sender, seq, message = heapq.heappop(self.pending)
                if sender == vehicle and due >= now:
                    self.buffer.setdefault(vehicle, []).append(message)
                else:
                    retained.append((due, sender, seq, message))
            self.pending = retained; heapq.heapify(self.pending)
            self.emit(vehicle, 'event', {'event':'comm_lost', 'details':{'basis':'synthetic_lift_radio_blackout'}}, now)
        else:
            began = self.outages.pop(vehicle)
            self.events.append({'vehicle_id':vehicle, 'start_s':began, 'end_s':now, 'duration_s':now-began})
            for message in sorted(self.buffer.pop(vehicle, []), key=lambda m:m['seq']):
                self._schedule(message, now)
            self.emit(vehicle, 'event', {'event':'comm_restored', 'details':{'outage_duration_s':now-began}}, now)

    def deliver(self, now):
        finite(now); messages = []
        while self.pending and self.pending[0][0] <= now:
            due, vehicle, _, message = heapq.heappop(self.pending)
            if not self.connected.get(vehicle, True):
                self.buffer.setdefault(vehicle, []).append(message)
                continue
            message = copy.deepcopy(message); message['received_s'] = due
            message['delivered_late'] = due-message['sent_s'] > self.late_after
            validate(message); messages.append(message)
            self.latencies.append(due-message['sent_s']); self.delivered_late += message['delivered_late']
        return messages

    def statistics(self):
        return {'sent':sum(self.sequence.values()), 'received':len(self.latencies),
                'buffered':sum(map(len, self.buffer.values())), 'pending':len(self.pending),
                'late':self.delivered_late, 'maximum_buffered':self.maximum_buffered,
                'latency_min_s':min(self.latencies, default=None), 'latency_max_s':max(self.latencies, default=None),
                'latency_mean_s':sum(self.latencies)/len(self.latencies) if self.latencies else None,
                'outages':copy.deepcopy(self.events), 'active_outages':dict(self.outages)}


class ReceivedControlRoom:
    """A reducer with no simulator, sensor, service, or truth reference."""
    def __init__(self):
        self.sequence = {}; self.vehicles = {}; self.events = []; self.messages = []; self.coverage = set(); self.duplicates = 0

    def receive(self, message):
        validate(message); message = copy.deepcopy(message)
        vehicle, seq = message['vehicle_id'], message['seq']
        if seq <= self.sequence.get(vehicle, 0):
            self.duplicates += 1; return False
        self.sequence[vehicle] = seq; self.messages.append(message)
        state = self.vehicles.setdefault(vehicle, {'last_received_s':None, 'last_sent_s':None, 'connected':True,
            'heartbeat':None, 'perception':None, 'mission':None, 'last_event':None})
        state['last_received_s'] = message['received_s']; state['last_sent_s'] = message['sent_s']
        kind, payload = message['kind'], message['payload']
        if kind == 'heartbeat': state['heartbeat'] = payload
        elif kind == 'perception': state['perception'] = payload
        else:
            event = payload['event']; state['last_event'] = payload; self.events.append(message)
            if event == 'mission_assigned': state['mission'] = payload['details']
            if event == 'comm_lost': state['connected'] = False
            if event == 'comm_restored': state['connected'] = True
            if event == 'inspection_completed':
                details = payload['details']
                self.coverage.add((details['level'], details['area']))
        return True

    def snapshot(self, now):
        finite(now); states = copy.deepcopy(self.vehicles)
        for state in states.values():
            state['message_age_s'] = max(0, now-state['last_sent_s'])
        return {'vehicles':states, 'coverage':[{'level':level, 'area':area} for level, area in sorted(self.coverage)],
                'events':copy.deepcopy(self.events), 'duplicates':self.duplicates}

    def write_jsonl(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            for message in self.messages:
                stream.write(json.dumps(message, sort_keys=True, allow_nan=False)+'\n')
