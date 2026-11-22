"""Independent BF01 issued-mission, receipt and fenced-booking replay.

No dispatcher, planner or runtime state is imported. Original assignments,
received radio events and observed lift acknowledgments must agree by ID.
Physical occupancy and native geometry remain separate mandatory audits.
"""
import collections
import copy
import math

import building_fleet_comm as comm
import building_fleet_depot as depot

# The BF01 task defines a deterministic 50 ms world integration clock.
WORLD_STEP_S=.05
BOOK_FIELDS=frozenset({'booking_id','vehicle_id','mission_id','from_level','to_level',
    'source_role','start','destination','state','created_s','activated_s'})
IMMUTABLE_BOOK_FIELDS=BOOK_FIELDS-{'state','activated_s'}


def _fields(row,fields,label):
    if type(row)is not dict or set(row)!=set(fields):raise ValueError('Unexpected '+label+' fields')


def _time(value,duration):
    if type(value)not in(int,float)or not math.isfinite(value)or not 0<=value<=duration:
        raise ValueError('Finite bounded mission time required')
    return value


def _tick(value):
    """First actual world tick at or after a wire delivery, without rounding early."""
    index=max(0,math.floor(value/WORLD_STEP_S))
    result=round(index*WORLD_STEP_S,3)
    if result<value:result=round((index+1)*WORLD_STEP_S,3)
    return result


def _records(rows,assignments,duration,label):
    result={}
    for row in rows:
        _fields(row,{'vehicle_id','mission_id','received_s'},label)
        mid=row['mission_id'];t=_time(row['received_s'],duration)
        if mid not in assignments or row['vehicle_id']!=assignments[mid]['vehicle_id']or mid in result:
            raise ValueError('Unique own '+label+' must identify the original issued mission')
        if t<assignments[mid]['assigned_s']:raise ValueError(label+' precedes issuance')
        result[mid]=t
    if set(result)!=set(assignments):raise ValueError('Every issued mission needs its own '+label)
    return result


def _downlink(assignments,messages,source,duration):
    """Replay the real channel contract and its original sender-time blackouts."""
    channel=comm.Channel(source['communication']['latency_s'],source['missions']['seed'],
                         max(source['communication']['latency_s']))
    changes=collections.defaultdict(list);issued=collections.defaultdict(list)
    for message in messages:
        if message['kind']=='event'and message['payload']['event']in('comm_lost','comm_restored'):
            t=_time(message['sent_s'],duration)
            if _tick(t)!=t:raise ValueError('Connectivity observations need actual world ticks')
            changes[t].append((message['vehicle_id'],message['payload']['event']=='comm_restored'))
    for mission in assignments.values():issued[mission['assigned_s']].append(mission)
    receipts={}
    for step in range(round(duration/WORLD_STEP_S)+1):
        now=round(step*WORLD_STEP_S,3)
        for vehicle,connected in changes.get(now,()):channel.set_connected(vehicle,connected,now)
        for message in channel.deliver(now):
            if message['kind']=='event'and message['payload']['event']=='mission_assigned':
                mid=message['payload']['details']['mission']['mission_id']
                if mid in receipts:raise ValueError('Duplicate own assignment downlink')
                receipts[mid]=now
        # Runtime processes received messages before issuing new work that tick.
        for mission in issued.get(now,()):
            channel.emit(mission['vehicle_id'],'event',
                {'event':'mission_assigned','details':{'mission':mission}},now)
    if set(receipts)!=set(assignments)or channel.pending or any(channel.buffer.values()):
        raise ValueError('Every original assignment downlink must actually be received')
    return receipts


def check_assignments(program,trajectories,navigation,source):
    """Bind all foreign missions to prior fences and observed lift lifecycles."""
    duration=_time(program['duration_s'],source['missions']['maximum_duration_s'])
    if _tick(duration)!=duration:raise ValueError('Complete world time must use the task integration clock')
    by_vehicle={t.identity:t for t in trajectories};targets={(r['level'],r['area']):r for r in source['missions']['targets']}
    assignments={};foreign_by_booking={};previous=-math.inf
    for row in program['mission_assignments']:
        _fields(row,{'mission_id','vehicle_id','assigned_s','goal','source_level','booking_id'},'issued mission')
        mid=row['mission_id'];vehicle=row['vehicle_id'];t=_time(row['assigned_s'],duration)
        if not isinstance(mid,str)or not mid or mid in assignments or vehicle not in by_vehicle:
            raise ValueError('Unique original issued mission and own vehicle required')
        if t<previous or _tick(t)!=t:raise ValueError('Issued missions must retain original chronological world ticks')
        previous=t;goal=row['goal']
        if type(goal)is not dict:raise ValueError('An issued goal must retain its source object')
        if goal.get('kind')=='inspection_pass':
            if targets.get((goal.get('level'),goal.get('area')))!=goal:raise ValueError('Issued inspection differs from its source target')
        elif goal!={'kind':'home',**navigation.homes[vehicle]}:
            raise ValueError('Issued final home differs from the own source home')
        if row['source_level']not in navigation.level_z:raise ValueError('Known issued source floor required')
        foreign=goal['level']!=row['source_level']
        if foreign!=(isinstance(row['booking_id'],str)and bool(row['booking_id'])):
            raise ValueError('Only a foreign issued mission has a named endpoint booking')
        if not foreign and row['booking_id']is not None:raise ValueError('Local mission must not claim a foreign booking')
        if foreign:
            if row['booking_id']in foreign_by_booking:
                raise ValueError('Each foreign booking must bind exactly one issued mission')
            foreign_by_booking[row['booking_id']]=mid
        assignments[mid]=copy.deepcopy(row)
    if not assignments:raise ValueError('An actual fleet needs issued missions')
    receipts=_records(program['mission_receipts'],assignments,duration,'assignment receipt')
    acknowledgments=_records(program['mission_acknowledgements'],assignments,duration,'received acknowledgment')
    if receipts!=_downlink(assignments,program['received_messages'],source,duration):
        raise ValueError('Own assignment receipts differ from the original seeded downlink replay')
    ack_messages={};completions={}
    for message in program['received_messages']:
        if message['kind']!='event':continue
        event=message['payload']['event'];details=message['payload']['details']
        if event not in('mission_assigned','inspection_completed','home_reached'):continue
        comm.validate(message);mid=details.get('mission_id');mission=assignments.get(mid)
        if mission is None or message['vehicle_id']!=mission['vehicle_id']:
            raise ValueError('Received event does not identify its original own mission')
        if message['sent_s']<receipts[mid]:raise ValueError('Own mission event precedes actual assignment receipt')
        if event=='mission_assigned':
            expected={'mission_id':mid,'goal':mission['goal'],'source_level':mission['source_level'],
                      'booking_id':mission['booking_id'],'acknowledged':True}
            if details!=expected or mid in ack_messages or message['sent_s']!=receipts[mid]:
                raise ValueError('Own acknowledgment differs from the immutable issued assignment')
            if acknowledgments[mid]!=_tick(message['received_s']):
                raise ValueError('Acknowledgment processing differs from its actual received wire message')
            ack_messages[mid]=message
        else:
            if mid in completions:raise ValueError('Duplicate mission completion')
            if (event=='inspection_completed')!=(mission['goal']['kind']=='inspection_pass'):
                raise ValueError('Capacity or inspection mission cannot masquerade as final home')
            if details.get('level')!=mission['goal']['level']or(event=='inspection_completed'and details.get('area')!=mission['goal']['area']):
                raise ValueError('Completion goal differs from the original mission')
            completions[mid]=message
    if set(ack_messages)!=set(assignments)or set(completions)!=set(assignments):
        raise ValueError('Every issued mission must be acknowledged and completed exactly once')
    witnesses={r['mission_id']:r for r in program['inspection_witnesses']}
    if len(witnesses)!=len(program['inspection_witnesses']):raise ValueError('Duplicate actual mission witness')
    homes=collections.Counter()
    for mid,mission in assignments.items():
        message=completions[mid];goal=mission['goal']
        if ack_messages[mid]['received_s']>message['received_s']:
            raise ValueError('Dispatcher completion precedes the received own acknowledgment')
        if goal['kind']=='inspection_pass':
            witness=witnesses.get(mid)
            if witness is None or any(witness[k]!=v for k,v in(
                    ('vehicle_id',mission['vehicle_id']),('level',goal['level']),('area',goal['area']),('time_s',message['sent_s']))):
                raise ValueError('Actual inspection witness must bind the same issued mission ID')
        else:
            homes[mission['vehicle_id']]+=1
            trajectory=by_vehicle[mission['vehicle_id']];episode=trajectory.episode(message['sent_s'])
            raw=episode['curve'].evaluate(message['sent_s'])
            state={'level':episode['level_id'],'aboard':episode['attached_cabin'],'pose_mm':raw[depot.floor.F[0]],
                   'velocity_mm_rad_s':raw[depot.floor.F[1]],'acceleration_mm_rad_s2':raw[depot.floor.F[2]]}
            if (episode.get('mode')!='hold'or episode.get('hold_reason')!='home'or
                    not depot.exact_home_rest(mission['vehicle_id'],state,navigation.homes)):
                raise ValueError('Final mission completion lacks its actual own source home rest')
            if mission['assigned_s']<source['missions']['minimum_duration_s']:
                raise ValueError('Final return was issued before the source minimum model duration')
            received_counts=collections.Counter((assignments[k]['goal']['level'],assignments[k]['goal']['area'])
                for k,event in completions.items()if assignments[k]['goal']['kind']=='inspection_pass'
                and _tick(event['received_s'])<=mission['assigned_s'])
            if any(received_counts[key]<target['minimum_visits']for key,target in targets.items()):
                raise ValueError('Final return was issued before received source target coverage')
    if set(witnesses)!={mid for mid,m in assignments.items()if m['goal']['kind']=='inspection_pass'}:
        raise ValueError('No unissued inspection witness may qualify coverage')
    if set(homes)!=set(by_vehicle)or any(n!=1 for n in homes.values()):raise ValueError('Each vehicle needs exactly one issued final-home completion')

    events=program['booking_events'];states={};active={};conditional={};arrivals={};boarded={};arrived={}
    previous=-math.inf;fenced={}
    for row in events:
        _fields(row,BOOK_FIELDS|{'event','time_s'},'booking event')
        t=_time(row['time_s'],duration);bid=row['booking_id'];vehicle=row['vehicle_id'];kind=row['event']
        if t<previous:raise ValueError('Booking observations must retain their original order')
        previous=t;mission=assignments.get(row['mission_id'])
        if mission is None or mission['vehicle_id']!=vehicle or mission['booking_id']!=bid:
            raise ValueError('Booking must bind its original issued foreign mission')
        if row['from_level']!=mission['source_level']or row['to_level']!=mission['goal']['level']or row['from_level']==row['to_level']:
            raise ValueError('Booking changed the issued source/destination')
        for key,level in(('start',row['from_level']),('destination',row['to_level'])):
            place=row[key];_fields(place,{'level','slot'},'booking bay')
            if place['level']!=level or type(place['slot'])is not int or not 0<=place['slot']<len(navigation.waits[level]):
                raise ValueError('Booking bay differs from the source waiting layout')
        old=states.get(bid)
        if old is not None and any(old[k]!=row[k]for k in IMMUTABLE_BOOK_FIELDS):
            raise ValueError('An immutable mission booking changed identity or endpoints')
        if kind=='booking_fenced':
            if old is not None or row['created_s']!=t or t>mission['assigned_s']:
                raise ValueError('Foreign endpoints were not fenced before issuance')
            if row['source_role']=='start':
                if vehicle in active or vehicle in conditional or row['state']!='active'or row['activated_s']!=t:
                    raise ValueError('Only one current foreign boundary may be active')
                episode=by_vehicle[vehicle].episode(t)
                if episode['level_id']!=row['from_level']or episode['attached_cabin']:
                    raise ValueError('Current source booking is not on the observed own floor')
                active[vehicle]=bid
            elif row['source_role']=='arrival':
                incoming=states.get(active.get(vehicle))
                if (incoming is None or incoming['state']!='boarded'or incoming['destination']!=row['start']
                        or vehicle in conditional or row['state']!='conditional'or row['activated_s']is not None):
                    raise ValueError('Only one successor may use the already-boarded incoming destination')
                conditional[vehicle]=bid
            else:raise ValueError('Unknown booking source role')
            fenced[bid]=t
        elif kind=='booking_boarded':
            if old is None or old['state']!='active'or row['state']!='boarded'or active.get(vehicle)!=bid or row['activated_s']!=old['activated_s']:
                raise ValueError('Boarding needs this active mission booking')
            boarded[bid]=t
        elif kind=='booking_arrived':
            if old is None or old['state']!='boarded'or row['state']!='arrived'or active.get(vehicle)!=bid or row['activated_s']!=old['activated_s']:
                raise ValueError('Arrival needs this observed boarded mission')
            del active[vehicle];arrivals[vehicle]=(row['destination'],t);arrived[bid]=t
        elif kind=='booking_activated':
            if (old is None or old['state']!='conditional'or row['state']!='active'or conditional.get(vehicle)!=bid
                    or vehicle in active or arrivals.get(vehicle)!=(row['start'],t)or row['activated_s']!=t):
                raise ValueError('A successor activates only at observed full body-clear arrival')
            del conditional[vehicle];active[vehicle]=bid
        else:raise ValueError('Unknown booking lifecycle observation')
        states[bid]={k:copy.deepcopy(row[k])for k in BOOK_FIELDS}
    final={r['booking_id']:r for r in program['mission_bookings']}
    if len(final)!=len(program['mission_bookings'])or final!=states or active or conditional or any(r['state']!='arrived'for r in states.values()):
        raise ValueError('Complete program retains a changed or unfinished mission booking')
    if set(final)!=set(foreign_by_booking):
        raise ValueError('Every foreign issued mission needs exactly its own fenced booking')
    for mission in assignments.values():
        if mission['booking_id']is not None:
            booking=final[mission['booking_id']]
            if (booking['mission_id']!=mission['mission_id']or booking['vehicle_id']!=mission['vehicle_id']
                    or booking['from_level']!=mission['source_level']or booking['to_level']!=mission['goal']['level']
                    or _time(booking['created_s'],duration)>mission['assigned_s']):
                raise ValueError('A foreign mission needs its exact booking fenced before issuance')
            continue
        vehicle=mission['vehicle_id'];t=mission['assigned_s'];episode=by_vehicle[vehicle].episode(t)
        actual=episode['level_id']==mission['source_level']and not episode['attached_cabin']
        history={}
        for row in events:
            if row['time_s']>t:break
            if row['vehicle_id']==vehicle:history[row['booking_id']]=row
        incoming=any(row['state']in('active','boarded')and row['to_level']==mission['source_level']for row in history.values())
        if not(actual or incoming):raise ValueError('A local mission source needs the observed own floor or its fenced incoming destination')

    waiting=program['waiting_events']
    for row in waiting:
        booking=final.get(row.get('booking_id'));kind=row['event'];role=row['role']
        if booking is None or row.get('mission_id')!=booking['mission_id']or row['vehicle_id']!=booking['vehicle_id']:
            raise ValueError('Waiting event changed its own immutable mission booking')
        place={'level':row['level'],'slot':row['slot']};t=_time(row['time_s'],duration)
        if kind=='waiting_promoted':
            valid=role=='start'and place==booking['destination']and t==arrived[booking['booking_id']]
        elif kind=='waiting_role_activated':
            valid=role=='destination'and place==booking['destination']and booking['source_role']=='arrival'and t==booking['activated_s']
        elif kind in('waiting_granted','waiting_bound'):
            if role=='start':
                expected=booking['created_s']if booking['source_role']=='start'else booking['activated_s']
                valid=place==booking['start']and t==expected and(kind=='waiting_bound'or booking['source_role']=='start')
            else:
                valid=(kind=='waiting_granted'and place==booking['destination']and t==booking['created_s']and
                    role==('destination'if booking['source_role']=='start'else'lookahead_destination'))
        elif kind=='waiting_released':
            valid=role=='start'and((place==booking['start']and t==boarded[booking['booking_id']])or
                (place==booking['destination']and t>=arrived[booking['booking_id']]))
        else:raise ValueError('Unknown mission-bound waiting event')
        if not valid:raise ValueError('Waiting role/endpoint observation differs from its mission booking')
    for bid,booking in final.items():
        own=[r for r in waiting if r['booking_id']==bid]
        for kind,role,place,t in(
            ('waiting_granted','destination'if booking['source_role']=='start'else'lookahead_destination',booking['destination'],booking['created_s']),
            ('waiting_promoted','start',booking['destination'],arrived[bid])):
            if sum(r['event']==kind and r['role']==role and {'level':r['level'],'slot':r['slot']}==place and r['time_s']==t for r in own)!=1:
                raise ValueError('Mission booking lacks its unique fenced/observed waiting endpoint')
        if booking['source_role']=='arrival'and sum(r['event']=='waiting_role_activated'and r['time_s']==booking['activated_s']for r in own)!=1:
            raise ValueError('Conditional booking lacks its observed role activation')
    ports={p['id']:p['level_id']for p in navigation.mesh.manifest['elevator']['ports']if p['active']}
    requests={r['booking_id']:r for r in program['lift_requests']}
    if len(requests)!=len(program['lift_requests'])or set(requests)!=set(final):raise ValueError('Every booking needs exactly its actual lift request')
    for bid,booking in final.items():
        request=requests[bid]
        if (request['vehicle_id']!=booking['vehicle_id']or request['mission_id']!=booking['mission_id']
                or ports.get(request['start_port'])!=booking['from_level']or ports.get(request['destination_port'])!=booking['to_level']
                or not max(fenced[bid],receipts[booking['mission_id']],booking['activated_s'])<=request['requested_s']<=request['assigned_s']<=boarded[bid]<=arrived[bid]
                or request['exited_s']!=arrived[bid]):
            raise ValueError('Lift request does not match its immutable issued mission booking')
        for name,time in(('lift_boarded',boarded[bid]),('lift_exited',arrived[bid])):
            matches=[e for e in program['lift_events']if e['vehicle_id']==booking['vehicle_id']and e['event']==name and e['time_s']==time]
            if len(matches)!=1:raise ValueError('Booking transition lacks its actual lift observation')
        if completions[booking['mission_id']]['sent_s']<arrived[bid]:
            raise ValueError('A foreign mission cannot complete before observed lift arrival')
    return {'passed':True,'issued_missions':len(assignments),'foreign_bookings':len(final),
        'replayed_downlink_receipts':len(receipts),'received_own_acknowledgments':len(ack_messages),
        'identity_bound_completions':len(completions),'final_home_missions':dict(homes),
        'basis':'Original issued IDs, exact seeded downlink/world-tick replay, received own acknowledgments and observed mission-bound lift lifecycle; no runtime or dispatcher flags'}
