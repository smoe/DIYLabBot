"""Independent BF01 exported-byte checks, separate from compilation claims.

Only standard-library/shared polynomial and geometry primitives are used.
A canonical full-episode geometry callback is mandatory for support/static
collision qualification; native BReps and actual WebGL remain separate gates.
"""
import bisect
import collections
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace

import building_fleet_comm as comm
import building_fleet_model as model
import building_fleet_motion as motion
import building_fleet_depot as depot
from building_fleet_navigation import point_in_polygon
from building_fleet_resources import _point_distance
from check_building_fleet_freecad import Trajectory, timeline_from_manifest, curve_extrema

F=motion.F
FORMAT='solidcraftbot.building-fleet-export-check/2'
CHECKS=('coverage','homes','dynamics','no_stop','support','collision','resources','lift','perception','telemetry')
ALLOWED_HOLDS=frozenset({'protective_stop','resource_wait','lift_wait','lift_parked',
                         'lift_travel','lift_door_sequence','home'})
GENERATORS=('building_fleet_checks.py','building_fleet_support.py','building_fleet_floor.py',
    'building_fleet_motion.py','building_fleet_clearance.py','building_fleet_navigation.py',
    'building_fleet_control.py','building_fleet_services.py','building_fleet_sim.py',
    'building_fleet_lift_checks.py','building_fleet_lift_geometry.py','building_fleet_runner.py',
    'building_fleet_missions.py','building_fleet_resources.py','building_fleet_comm.py',
    'building_fleet_dispatch.py','building_fleet_depot.py','building_fleet_routes.py',
    'building_fleet_geometry.py','building_fleet_geometry_checks.py','building_fleet_zones.py','tr01_camera_model.py')


def finite(value,minimum=-math.inf):
    if type(value)not in(int,float)or not math.isfinite(value)or value<minimum:
        raise ValueError('Finite bounded numeric check input required')
    return value


def source_pins(source):
    return {**model.source_pins(source),**model.protected_pins(),
            **{'scripts/'+name:model.digest(model.ROOT/'scripts'/name)for name in GENERATORS}}


def verify_pins(pins):
    if not isinstance(pins,dict)or not pins:raise ValueError('Nonempty current source/artifact pins required')
    for name,digest in pins.items():model.resolve_pin({'path':name,'sha256':digest})


def _same_pose(actual,expected,tolerance=1e-6):
    return (len(actual)==len(expected)and all(abs(finite(a)-finite(b))<=tolerance for a,b in zip(actual,expected)))


def _cut_intervals(trajectory,start,end,extra=()):
    cuts={start,end,*[t for t in trajectory.starts if start<t<end],
          *[t for e in trajectory.episodes for t in(e['end_s'],)if start<t<end],
          *[t for t in extra if start<t<end]}
    return zip(sorted(cuts),sorted(cuts)[1:])

def check_resource_history(events,duration,vehicle_ids):
    """Replay grants/releases independently, preserving simultaneous ordering."""
    held={};owners={};windows={};starts={};previous=-math.inf
    for row in events:
        t=row['time_s'];vehicle=row['vehicle_id'];resource=row['resource'];event=row['event']
        if type(t)not in(int,float)or not math.isfinite(t)or not 0<=t<=duration+1e-7 or t<previous or abs(t*1000-round(t*1000))>1e-5:raise ValueError('Chronological bounded resource events required')
        previous=t
        if vehicle not in vehicle_ids or not isinstance(resource,str)or not resource:raise ValueError('Known own vehicle and static resource required')
        if event=='passage_granted':
            if vehicle in held or resource in owners:raise ValueError('Overlapping resource ownership or multiple narrow tokens')
            held[vehicle]=resource;owners[resource]=vehicle;starts[vehicle]=t
        elif event=='passage_released':
            if held.get(vehicle)!=resource or owners.get(resource)!=vehicle:raise ValueError('Resource release without matching own grant')
            windows.setdefault((vehicle,resource),[]).append((starts.pop(vehicle),t));del held[vehicle];del owners[resource]
        else:raise ValueError('Only actual grants and releases belong in resource history')
    if held:raise ValueError('Terminal program still holds narrow resources')
    return windows

def _covered(windows,vehicle,resource,a,b):
    return any(left<=a+1e-7 and right>=b-1e-7 for left,right in windows.get((vehicle,resource),()))

def check_resource_occupancy(trajectories,catalog,windows,homes=None):
    """Interval-enclose actual XY against immutable guarded conflict regions.

    Parked depot homes are obstacles, not moving claimants. Every driving
    interval potentially entering a region needs its vehicle's actual grant.
    Ambiguous boundary cases are refined; they never silently pass.
    """
    regions={}
    for row in catalog['regions']:
        regions.setdefault(row['level'],[]).append(row)
    checks=0
    for trajectory in trajectories:
        for episode in trajectory.episodes:
            if episode['attached_cabin']or episode.get('lift_phase')in('boarding','alighting'):continue
            if homes is not None and episode['mode']=='hold':
                p=episode['points'][0]
                state={'level':episode['level_id'],'aboard':False,'pose_mm':p['pose_mm_rad'],
                       'velocity_mm_rad_s':p['velocity_mm_rad_s'],'acceleration_mm_rad_s2':p['acceleration_mm_rad_s2']}
                if depot.exact_home_rest(trajectory.identity,state,homes):continue
            curve=episode['curve'];level=episode['level_id'];selected=list(regions.get(level,[]))
            # A room claim concerns a route entering that room. Portal guards
            # cover the doorway independently of this interior predicate.
            def may_enter(polygon,a,b,depth=0):
                middle=(a+b)/2;xy=curve.evaluate(middle)[F[0]][:2]
                if point_in_polygon(xy,polygon):return True
                bounds=curve_extrema(curve,a,b)
                delta=math.hypot(*(max(abs(bounds[k][i]-xy[i])for k in('min','max'))for i in range(2)))
                if _point_distance(xy,polygon)>delta+1e-8:return False
                if depth>=20 or b-a<=.0005:return True  # Ambiguous boundary needs the claim.
                return may_enter(polygon,a,middle,depth+1)or may_enter(polygon,middle,b,depth+1)
            for row in catalog.get('room_polygons',[]):
                if row['level']!=level:continue
                if any(may_enter(row['polygon'],a,b)for a,b in zip(curve.times,curve.times[1:])):
                    selected.append({'level':level,'resource':row['resource'],'polygon':row['polygon'],
                                     'padding':catalog['room_guard_mm']})
            if not selected:continue
            def interval(a,b,depth=0):
                nonlocal checks
                checks+=1;mid=(a+b)/2;pose=curve.evaluate(mid)[F[0]][:2]
                raw=curve_extrema(curve,a,b)
                delta=math.hypot(*(max(abs(raw[k][i]-pose[i])for k in('min','max'))for i in range(2)))
                pending=[]
                for row in selected:
                    if _covered(windows,trajectory.identity,row['resource'],a,b):continue
                    if _point_distance(pose,row['polygon'])<=delta+row.get('padding',0)+1e-7:pending.append(row)
                if not pending:return
                if b-a<=.0005 or depth>=24:raise ValueError('Driving curve lacks its own exclusive resource: '+str((trajectory.identity,level,a,b,[r['resource']for r in pending])))
                interval(a,mid,depth+1);interval(mid,b,depth+1)
            cuts=sorted({*curve.times,*[t for (vehicle,_),rows in windows.items()if vehicle==trajectory.identity for pair in rows for t in pair if episode['start_s']<t<episode['end_s']]})
            for a,b in zip(cuts,cuts[1:]):interval(a,b)
    return {'passed':True,'intervals':checks,'method':'actual exported XY polynomial enclosures against immutable guarded regions and own grant intervals'}

def check_coverage(program,trajectories,navigation,source):
    target={(r['level'],r['area']):r for r in source['missions']['targets']}
    counts={k:0 for k in target};by_id={t.identity:t for t in trajectories};seen=set()
    reported={}
    for message in program['received_messages']:
        comm.validate(message)
        if message['kind']=='event'and message['payload']['event']=='inspection_completed':
            d=message['payload']['details'];key=(message['vehicle_id'],d['level'],d['area'],message['sent_s'])
            reported[key]=True
    for row in program['inspection_witnesses']:
        identity=row['vehicle_id'];key=(row['level'],row['area']);t=row['time_s'];mission=row['mission_id']
        if identity not in by_id or key not in target or mission in seen:raise ValueError('Unique actual own inspection witness required')
        seen.add(mission);episode=by_id[identity].episode(t)
        state=episode['curve'].evaluate(t)
        if episode['mode']!='driving'or episode['level_id']!=key[0]or math.hypot(*state[F[1]][:2])<=1e-5:raise ValueError('Inspection is a moving actual pass, never a planned or stationary visit')
        if not point_in_polygon(state[F[0]][:2],navigation.polygons[key[0]][key[1]]):raise ValueError('Inspection witness lies outside its source-bound room')
        if not any(v==identity and lev==key[0]and area==key[1]and abs(sent-t)<1e-6 for v,lev,area,sent in reported):raise ValueError('Actual inspection lacks its received completion event')
        counts[key]+=1
    if any(counts[k]<r['minimum_visits']for k,r in target.items()):raise ValueError('Actual received coverage is incomplete')
    return [{'level':k[0],'area':k[1],'visits':counts[k],'basis':r['basis']}for k,r in target.items()]

def check_pair_clearance(trajectories,navigation,duration):
    """Independent interval replay of all exported oriented vehicle envelopes."""
    from building_fleet_sim import IntervalAuditor,footprint,polygon_distance
    length,width=navigation.envelope['length_mm'],navigation.envelope['width_mm']
    height=navigation.envelope['height_mm'];reserve=navigation.reserve;minimum=math.inf;checks=0;refined=0
    def box_gap(a,b):
        return math.sqrt(sum(max(0.,a['min'][k]-b['max'][k],b['min'][k]-a['max'][k])**2 for k in range(3)))
    def envelope(trajectory,a,b):
        episode=trajectory.episode((a+b)/2);curve=episode['curve'];raw=curve_extrema(curve,a,b)
        hx=IntervalAuditor._extent(length,width,raw['min'][2],raw['max'][2])
        hy=IntervalAuditor._extent(width,length,raw['min'][2],raw['max'][2])
        zs=[trajectory.pose(a)[2],trajectory.pose(b)[2],trajectory.pose((a+b)/2)[2]]
        return {'min':[raw['min'][0]-hx,raw['min'][1]-hy,min(zs)],
                'max':[raw['max'][0]+hx,raw['max'][1]+hy,max(zs)+height]}
    def pair(first,second,a,b,boxes=None,depth=0):
        nonlocal minimum,checks,refined
        checks+=1
        boxes=boxes or(envelope(first,a,b),envelope(second,a,b));lower=box_gap(*boxes)
        if lower>=reserve:
            minimum=min(minimum,lower);return
        mid=(a+b)/2;p,q=first.pose(mid),second.pose(mid)
        horizontal=polygon_distance(footprint({'pose_mm':[p[0],p[1],p[3]],'footprint_mm':[length,width]}),
                                    footprint({'pose_mm':[q[0],q[1],q[3]],'footprint_mm':[length,width]}))
        vertical=max(0.,p[2]-q[2]-height,q[2]-p[2]-height)
        actual=math.hypot(horizontal,vertical)
        if actual<reserve-1e-6:raise ValueError('Actual exported vehicle envelopes collide: '+str((first.identity,second.identity,mid,actual)))
        lower=actual-first.inflation(a,b,navigation.radius)-second.inflation(a,b,navigation.radius)
        if lower>=reserve:
            minimum=min(minimum,lower);return
        if depth>=24 or b-a<=1e-7:raise ValueError('Actual exported pair interval cannot be certified at unchanged reserve')
        refined+=1;pair(first,second,a,mid,depth=depth+1);pair(first,second,mid,b,depth=depth+1)
    cuts={0.,duration}
    for trajectory in trajectories:
        cuts.update(trajectory.starts);cuts.update(e['end_s']for e in trajectory.episodes)
        for row in trajectory.lift.schedule:cuts.update(t for t in(row['start_s'],row['end_s'])if 0<t<duration)
    ordered=sorted(cuts)
    for a,b in zip(ordered,ordered[1:]):
        # Broad boxes are themselves whole-interval proofs, so empty stretches
        # need no uniform temporal sampling. Refinement occurs only as needed.
        boxes=[envelope(t,a,b)for t in trajectories]
        for i,first in enumerate(trajectories):
            for j in range(i+1,len(trajectories)):pair(first,trajectories[j],a,b,(boxes[i],boxes[j]))
    return {'passed':True,'reserve_mm':reserve,'minimum_interval_lower_mm':minimum,
            'pair_intervals':checks,'refinements':refined,
            'scope':'Independent actual exported XY/yaw polynomial boxes, absolute cabin z and conservative oriented vehicle prisms; no controller or perception claims consumed'}

def check_lift_schedule(schedule,manifest,lift):
    """Recheck source timing, active landings and closed-door travel."""
    elevator=manifest['elevator'];ports=[p for p in elevator['ports']if p['active']]
    z_by_level={p['level_id']:p['z_mm']for p in ports};trips=0
    doors={o['id']:o for o in manifest['objects']if o.get('mechanism')=='lift_door'}
    for row in schedule:
        start,end=row['start_s'],row['end_s']
        if row['kind']=='travel':
            expected=1.875*abs(row['to_z_mm']-row['from_z_mm'])/elevator['speed_mm_s']
            if abs(end-start-expected)>1e-6 or expected<=0:raise ValueError('Lift duration differs from source quintic speed')
            if row['to_level']not in z_by_level or abs(z_by_level[row['to_level']]-row['to_z_mm'])>1e-7:raise ValueError('Lift destination is not an active source landing')
            prior=lift.values(max(0,start-1e-8))
            if abs(prior[elevator['object_id']]-row['from_z_mm'])>1e-5:raise ValueError('Lift schedule has a height discontinuity')
            if any(abs(prior[name]-obj['states']['closed'])>1e-6 for name,obj in doors.items()):raise ValueError('Lift travels with an open door')
            trips+=1
        else:
            if row['level']not in z_by_level or abs(lift.z(start)-z_by_level[row['level']])>1e-6:raise ValueError('Door sequence is not at its active floor')
            if not doors or any(abs(end-start-obj['duration_s'])>1e-6 for obj in doors.values()):raise ValueError('Door duration differs from source')
    return {'passed':True,'trips':trips,'basis':'source speed/duration/active ports; independent numeric schedule replay'}


def check_homes(trajectories,navigation,program):
    """Bind all start/end states to the independently prepared depot layout."""
    if program['homes']!=navigation.homes:raise ValueError('Program homes differ from the current source-derived depot layout')
    for trajectory in trajectories:
        home=navigation.homes[trajectory.identity]
        for at in(0.,program['duration_s']):
            e=trajectory.episode(at);jet=e['curve'].evaluate(at)
            state={'level':e['level_id'],'aboard':e['attached_cabin'],'pose_mm':jet[F[0]],
                   'velocity_mm_rad_s':jet[F[1]],'acceleration_mm_rad_s2':jet[F[2]]}
            if not depot.exact_home_rest(trajectory.identity,state,navigation.homes):
                raise ValueError('Every vehicle must begin/end at exact own home and zero PVA')
        if trajectory.episodes[-1]['mode']!='hold'or trajectory.episodes[-1].get('hold_reason')!='home':
            raise ValueError('Actual final home hold required')
    return {'passed':True,'vehicles':len(trajectories),'start_and_end_states':2*len(trajectories),
            'basis':'independently prepared home slots, exact source level and shared exact_home_rest predicate'}


def check_exported_motion(trajectories,source,radius):
    """Re-evaluate every exported and re-quantized polynomial, between nodes."""
    caps=source['motion']['empty_linear_limits']
    linear=dict(zip(('velocity','acceleration','jerk'),(caps['velocity_mm_s'],caps['acceleration_mm_s2'],caps['jerk_mm_s3'])))
    angular=model.reference(source,'angular_profile')['limits']['angular']
    maxima={kind:{k:0. for k in linear}for kind in('linear','angular')}
    counts=collections.Counter();rests=[]
    for trajectory in trajectories:
        before_drives=counts['driving_episodes']
        for index,e in enumerate(trajectory.episodes):
            points=e['points']
            if any(abs(finite(p['time_s'])*1000-round(p['time_s']*1000))>1e-5 for p in points):
                raise ValueError('Every exported PVA time must use the source1ms grid')
            quantized=[{**p,'time_s':round(p['time_s']*1000)/1000}for p in points]
            curves=(e['curve'],motion.floor.motion.Curve(motion.floor.canonical(quantized)))
            for curve in curves:
                bounds=motion.episode_dynamics(curve,radius)
                for kind,limits in(('linear',linear),('angular',angular)):
                    for key,cap in limits.items():
                        maxima[kind][key]=max(maxima[kind][key],bounds[kind][key])
                        if bounds[kind][key]>cap*(1+1e-6):
                            raise ValueError('Actual exported/quantized '+kind+' '+key+' exceeds its unchanged source limit')
                counts['polynomial_intervals']+=len(curve.segments)
            if e['mode']=='driving':
                counts['driving_episodes']+=1
                if any(not motion.floor.no_stop(c)['passed']for c in curves):raise ValueError('Unjustified interior rest in actual driving curve')
                if index and trajectory.episodes[index-1]['mode']=='driving'and math.hypot(*points[0]['velocity_mm_rad_s'][:2])<1e-5:
                    raise ValueError('Adjacent driving episodes conceal a waypoint stop')
            else:
                reason=e.get('hold_reason');condition=e.get('hold_condition')
                if reason not in ALLOWED_HOLDS or not isinstance(condition,str)or not condition.strip():
                    raise ValueError('A functional hold needs an allowed reason and concrete observation/completion condition')
                if reason=='home'and any(later['mode']=='driving'for later in trajectory.episodes[index+1:]):
                    raise ValueError('A home endhold cannot hide an intermediate demonstration pause')
                if e['mode']=='lift'and not e['attached_cabin']:raise ValueError('Lift travel must remain absolutely cabin-attached')
                rests.append({'vehicle_id':trajectory.identity,'episode':index,'reason':reason,'condition':condition})
        if counts['driving_episodes']==before_drives:raise ValueError('Every fleet vehicle must execute an actual drive')
    if not counts['driving_episodes']:raise ValueError('A parked fleet is not a complete program')
    return ({'passed':True,'maxima':maxima,'limits':{'linear':linear,'angular':angular},**counts,
             'basis':'shared analytic polynomial extrema on actual exported curves and a fresh1ms quantization'},
            {'passed':True,'driving_episodes':counts['driving_episodes'],'functional_holds':rests,
             'basis':'shared interior speed-root test, adjacent episode continuity and explicit functional hold conditions'})


def check_depot(trajectories,navigation,catalog,windows):
    """Check fixed-home assumptions continuously, independently of trace flags."""
    from building_fleet_sim import footprint,polygon_distance
    aliases={};rooms={};source=navigation.config
    for area in source['depot']['areas']:
        level=source['depot']['level'];key=(level,area);alias=level+'.room.'+area
        if alias not in catalog['aliases']:raise ValueError('Source depot room lacks canonical resource')
        aliases[key]=catalog['aliases'][alias];rooms[key]=navigation.polygons[level][area]
    cuts=[t for rows in windows.values()for pair in rows for t in pair]
    checked=refined=0;home_proofs=[];size=[navigation.envelope['length_mm'],navigation.envelope['width_mm']]
    def visit(trajectory,episode,room,resource,a,b,depth=0):
        nonlocal checked,refined
        checked+=1
        if _covered(windows,trajectory.identity,resource,a,b):return
        curve=episode['curve'];left,right=[curve.evaluate(t)for t in(a,b)]
        def state(raw):return {'level':episode['level_id'],'aboard':episode['attached_cabin'],'pose_mm':raw[F[0]],
                               'velocity_mm_rad_s':raw[F[1]],'acceleration_mm_rad_s2':raw[F[2]]}
        if all(depot.exact_home_rest(trajectory.identity,state(raw),navigation.homes)for raw in(left,right)):
            bounds=curve_extrema(curve,a,b,1)
            if max(abs(v)for key in('min','max')for v in bounds[key])<1e-9:return
        velocity=curve_extrema(curve,a,b,1)
        movement=(math.hypot(*(max(abs(velocity[k][i])for k in('min','max'))for i in range(2)))+
                  navigation.radius*max(abs(velocity[k][2])for k in('min','max')))*(b-a)/2
        gap=min(polygon_distance(footprint({'pose_mm':raw[F[0]],'footprint_mm':size}),room)for raw in(left,right))
        if gap-movement>=navigation.reserve-1e-7:return
        if depth>=24 or b-a<=1e-7:raise ValueError('Nonowner occupies a depot room away from exact fixed home/rest')
        refined+=1;mid=(a+b)/2;visit(trajectory,episode,room,resource,a,mid,depth+1);visit(trajectory,episode,room,resource,mid,b,depth+1)
    for trajectory in trajectories:
        for e in trajectory.episodes:
            if e['attached_cabin']or e['level_id']!=source['depot']['level']:continue
            if e['mode']=='driving':
                home_proofs.append(depot.fixed_home_curve_proof(e['curve'],trajectory.identity,navigation.homes,navigation.envelope,navigation.reserve,e['level_id']))
            for key,room in rooms.items():
                for a,b in _cut_intervals(trajectory,e['start_s'],e['end_s'],[*e['curve'].times,*cuts]):
                    visit(trajectory,e,room,aliases[key],a,b)
    return {'passed':True,'invariant_intervals':checked,'refinements':refined,'fixed_home_curve_checks':len(home_proofs),
            'minimum_fixed_home_lower_mm':min((p['minimum_distance_lower_bound_mm']for p in home_proofs if p['minimum_distance_lower_bound_mm']is not None),default=None),
            'room_resources':[{'level':key[0],'area':key[1],'resource':resource}for key,resource in aliases.items()],
            'basis':'actual polynomial intervals versus depot rooms/own exclusive grants; all other source homes retained as physical envelopes'}


def check_waiting_history(events,duration,navigation,vehicle_ids):
    """Recheck source and destination bay exclusivity through promotion."""
    owners={};held={};windows={};starts={};previous=-math.inf
    for row in events:
        t=finite(row['time_s'],0);vehicle=row['vehicle_id'];key=(row['level'],row['slot']);event=row['event'];role=row['role']
        if t<previous or t>duration or vehicle not in vehicle_ids or role not in('start','destination'):raise ValueError('Chronological own waiting-place history required')
        previous=t
        if key[0]not in navigation.waits or type(key[1])is not int or not 0<=key[1]<len(navigation.waits[key[0]]):raise ValueError('Waiting bay differs from prepared source layout')
        own=(vehicle,role)
        if event=='waiting_granted':
            if key in owners or own in held:raise ValueError('Waiting-place grant overlaps another owner')
            owners[key]=own;held[own]=key;starts[own]=t
        elif event=='waiting_released':
            if held.get(own)!=key or owners.get(key)!=own:raise ValueError('Waiting-place release lacks its exact own grant')
            windows.setdefault((vehicle,key),[]).append((starts.pop(own),t));del held[own];del owners[key]
        elif event=='waiting_promoted':
            old=(vehicle,'destination')
            if role!='start'or own in held or held.get(old)!=key or owners.get(key)!=old:raise ValueError('Destination promotion lacks source release and exact destination grant')
            held[own]=held.pop(old);owners[key]=own;starts[own]=starts.pop(old)
        else:raise ValueError('Unknown waiting-place observation')
    if held:raise ValueError('Terminal program retains waiting-place reservations')
    return {'passed':True,'events':len(events),'grant_windows':sum(map(len,windows.values())),'basis':'source bay identities, dual-end admission exclusivity and explicit promotion/release replay'}


def check_telemetry(program,trajectories,source,navigation):
    """Rebuild only received states; independently verify capture and radio time."""
    duration=program['duration_s'];by_id={t.identity:t for t in trajectories};messages=program['received_messages']
    room=comm.ReceivedControlRoom();sequence={};previous=(-math.inf,'',0);owners={};counts=collections.Counter();outages={};active={}
    for m in messages:
        comm.validate(m);key=(m['received_s'],m['vehicle_id'],m['seq'])
        if key<previous or m['received_s']>duration+1e-7:raise ValueError('Only chronological messages received by model end may enter the control room')
        previous=key;vehicle=m['vehicle_id']
        if vehicle not in by_id or m['seq']!=sequence.get(vehicle,0)+1:raise ValueError('Complete delivered sender sequence required; duplicates/gaps cannot fabricate completion')
        sequence[vehicle]=m['seq'];counts[m['kind']]+=1;room.receive(m)
        t=by_id[vehicle];payload=m['payload']
        if m['kind']=='heartbeat':
            pose=t.pose(m['sent_s']);e=t.episode(m['sent_s'])
            if not _same_pose(payload['pose_mm'],[pose[0],pose[1],pose[3]])or payload['level']!=e['level_id']:raise ValueError('Heartbeat is not bound to its own actual capture-time state')
            if payload['speed_mm_s']>source['motion']['empty_linear_limits']['velocity_mm_s']*(1+1e-6):raise ValueError('Reported own speed exceeds source profile')
            if payload['area']in navigation.polygons[e['level_id']]and not point_in_polygon(pose[:2],navigation.polygons[e['level_id']][payload['area']]):raise ValueError('Heartbeat area differs from source geometry')
        elif m['kind']=='perception':
            ref=payload['camera_ref'];capture=program['camera_captures'].get(ref)
            if not capture or ref in owners and owners[ref]!=vehicle:raise ValueError('A camera reference must have one own sender and an original capture')
            owners[ref]=vehicle;at=payload['captured_s'];pose=t.pose(at);e=t.episode(at)
            if capture['captured_s']!=at or capture['level_id']!=payload['level']or payload['level']!=e['level_id']:
                raise ValueError('Delivered camera time/level is not the own source capture')
            if not _same_pose(capture['pose_xyz_mm'],pose[:3])or abs(finite(capture['yaw_rad'])-pose[3])>1e-6 or not _same_pose(payload['pose_mm'],[pose[0],pose[1],pose[3]]):
                raise ValueError('Camera and reported scan pose must use original own localization')
        elif payload['event']in('comm_lost','comm_restored'):
            if payload['event']=='comm_lost':
                if vehicle in active:raise ValueError('Nested radio blackout')
                active[vehicle]=m['sent_s']
            else:
                if vehicle not in active:raise ValueError('Radio restoration has no own preceding blackout')
                began=active.pop(vehicle);outages.setdefault(vehicle,[]).append((began,m['sent_s']))
    if active or set(sequence)!=set(by_id):raise ValueError('Every vehicle must finish its received radio state')
    # The channel hash is pure source math; replay delivery release and ordering
    # from the received original sender timestamps, including in-flight buffering.
    channel=comm.Channel(source['communication']['latency_s'],source['missions']['seed'],max(source['communication']['latency_s']))
    for vehicle in by_id:
        rows=sorted((m for m in messages if m['vehicle_id']==vehicle),key=lambda m:m['seq']);due=-math.inf
        for m in rows:
            release=m['sent_s'];latency=channel._latency(vehicle,m['seq'])
            for begin,end in outages.get(vehicle,[]):
                if begin<=release<end:release=end
            expected=max(release+latency,due)
            for begin,end in outages.get(vehicle,[]):
                if begin<=expected<end:expected=max(end+latency,due)
            if abs(expected-m['received_s'])>1e-7:raise ValueError('Received time differs from source deterministic radio/buffer replay')
            due=expected
            if m['delivered_late']!=(m['received_s']-m['sent_s']>max(source['communication']['latency_s'])):raise ValueError('Late marker differs from original sender age')
        for kind,period in(('heartbeat',1.),('perception',.5)):
            times=[m['sent_s']for m in rows if m['kind']==kind]
            if not times or any(abs(t/period-round(t/period))>1e-7 for t in times)or any(b-a>period+1e-7 for a,b in zip(times,times[1:])):
                raise ValueError('Complete periodic own telemetry required')
    if set(owners)!=set(program['camera_captures']):raise ValueError('Unreceived/unowned camera captures cannot enter the completed export')
    snapshot=room.snapshot(duration)
    if any(not row['connected']for row in snapshot['vehicles'].values()):raise ValueError('Final received connection state remains in blackout')
    return {'passed':True,'messages':len(messages),'kinds':dict(counts),'camera_captures':len(owners),
            'late_messages':sum(m['delivered_late']for m in messages),'received_coverage':snapshot['coverage'],
            'basis':'strict telemetry schema, contiguous received sequences, own capture-time PVA binding and source hash-jitter/buffer replay; reducer receives no world object'}


def operating_cabin_lanes(navigation,source):
    """Re-derive the source operating lanes without reading runtime reports."""
    from building_fleet_services import cabin_lanes
    sensor=model.resolved_sensor(source)
    perception_gap=(sensor['clearance_mm']+sensor['range_error_mm']+
        sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))+
        source['geometry']['localization_tolerance_mm'])
    gap=max(navigation.reserve,perception_gap)+navigation.navigation_margin_mm
    lanes=cabin_lanes(navigation.cabin_interior_mm,
        [navigation.envelope['length_mm'],navigation.envelope['width_mm']],gap,
        maximum=source['lift']['maximum_capacity'])
    return lanes,gap


def check_lift_program(program,trajectories,navigation,source,lift):
    """Inspect allocated slots, source FK gates and the complete door curtain."""
    from building_fleet_services import cabin_lanes
    from building_fleet_lift_checks import gate_at
    from building_fleet_sim import footprint,polygon_distance
    manifest=navigation.mesh.manifest;config=manifest['elevator'];duration=program['duration_s']
    result=check_lift_schedule(program['lift_schedule'],manifest,lift)
    if not result['trips']:raise ValueError('A complete building fleet program must actually use the lift')
    lanes,passing_gap=operating_cabin_lanes(navigation,source)
    ports={p['id']:p for p in config['ports']if p['active']};by_id={t.identity:t for t in trajectories}
    requests=program['lift_requests'];events=program['lift_events'];windows=[]
    for row in requests:
        vehicle=row['vehicle_id'];start=ports.get(row['start_port']);end=ports.get(row['destination_port']);slot=row['slot']
        a=finite(row['requested_s'],0);b=finite(row['assigned_s'],a);exit_time=finite(row['exited_s'],b)
        if vehicle not in by_id or start is None or end is None or start['level_id']==end['level_id']or type(slot)is not int or not 0<=slot<len(lanes)or exit_time>duration:
            raise ValueError('Completed source-active allocated lift request required')
        if any(v==vehicle and not(exit_time<=x or y<=a)for v,x,y,_,_ in windows):raise ValueError('Own lift requests overlap')
        boarded=[e for e in events if e['event']=='lift_boarded'and e['vehicle_id']==vehicle and b-1e-7<=e['time_s']<=exit_time+1e-7]
        exited=[e for e in events if e['event']=='lift_exited'and e['vehicle_id']==vehicle and abs(e['time_s']-exit_time)<1e-7]
        assigned=[e for e in events if e['event']=='lift_slot_assigned'and e['vehicle_id']==vehicle and abs(e['time_s']-b)<1e-7 and e['slot']==slot]
        if len(boarded)!=1 or len(exited)!=1 or len(assigned)!=1:raise ValueError('Lift request needs unique actual assigned/boarded/exited observations')
        board=boarded[0]['time_s'];trajectory=by_id[vehicle];gate_at(navigation.mesh,start['id'],lift,board);gate_at(navigation.mesh,end['id'],lift,exit_time)
        pose=trajectory.pose(board)
        if not _same_pose(pose[:2],lanes[slot]['pose_mm'][:2]):raise ValueError('Boarded acknowledgement is away from its allocated native cabin lane')
        expected='reverse'if start['side']==end['side']else'forward'
        if exited[0]['direction']!=expected:raise ValueError('Lift exit direction differs from source active-port sides')
        windows.append((vehicle,a,exit_time,slot,board))
    if not windows:raise ValueError('A lift schedule alone does not prove actual fleet rides')
    gates=attached=0
    for trajectory in trajectories:
        for e in trajectory.episodes:
            a,b=e['start_s'],e['end_s'];phase=e.get('lift_phase');mid=(a+b)/2
            own=[r for r in windows if r[0]==trajectory.identity and r[1]<=a+1e-7 and r[2]>=a-1e-7]
            if e['attached_cabin']:
                attached+=1
                if len(own)!=1 or own[0][4]>a+1e-7:raise ValueError('Cabin attachment lacks its own actual parked/boarded observation')
                lane=lanes[own[0][3]]['pose_mm']
                if not _same_pose(e['points'][0]['pose_mm_rad'][:2],lane[:2]):raise ValueError('Cabin-attached XY differs from its allocated lane')
            if phase in('boarding','alighting'):
                if len(own)!=1:raise ValueError('Crossing lacks an own active lift request')
                port=e.get('port_id')
                if port not in ports:raise ValueError('Crossing lacks a source-active own port')
                end_gate=b if phase=='boarding'else min(b,own[0][2])
                cuts={a,end_gate,*[t for row in program['lift_schedule']for t in(row['start_s'],row['end_s'])if a<t<end_gate]}
                for t in sorted(cuts):gate_at(navigation.mesh,port,lift,t);gates+=1
                if phase=='alighting':
                    request=next(r for r in requests if r['vehicle_id']==trajectory.identity and r['requested_s']==own[0][1])
                    reverse=ports[request['start_port']]['side']==ports[request['destination_port']]['side']
                    if bool(e.get('reverse'))!=reverse:raise ValueError('Actual exit curve has the wrong direction')
    # Slot occupancy and door-line freedom are verified from exported poses,
    # independently of the service's accepted observation flags.
    for a,b in zip(sorted({t for w in windows for t in(w[4],w[2])}),sorted({t for w in windows for t in(w[4],w[2])})[1:]):
        active=[w for w in windows if w[4]<b-1e-8 and w[2]>a+1e-8]
        if len(active)>len(lanes)or len({w[3]for w in active})!=len(active):raise ValueError('Allocated cabin occupancy exceeds distinct native slots')
    curtain_intervals=0
    margin=navigation.navigation_margin_mm;bounds=config['cabin_bounds_mm'];size=[navigation.envelope['length_mm'],navigation.envelope['width_mm']]
    for row in program['lift_schedule']:
        if row['kind']!='doors'or row['target']!='closed':continue
        a,b=row['start_s'],row['end_s']
        if b>duration+1e-7:raise ValueError('Lift door sequence exceeds model duration')
        for port in ports.values():
            if port['level_id']!=row['level']:continue
            plane=port['plane_x_mm'];curtain=[[plane-margin,bounds['min'][1]-margin],[plane+margin,bounds['min'][1]-margin],
                [plane+margin,bounds['max'][1]+margin],[plane-margin,bounds['max'][1]+margin]]
            def visit(trajectory,start,end,depth=0):
                nonlocal curtain_intervals
                curtain_intervals+=1;e=trajectory.episode((start+end)/2)
                if not e['attached_cabin']and abs(trajectory.levels[e['level_id']]['z_mm']-port['z_mm'])>1e-7:return
                raw=curve_extrema(e['curve'],start,end,1)
                movement=(math.hypot(*(max(abs(raw[k][i])for k in('min','max'))for i in range(2)))+
                    navigation.radius*max(abs(raw[k][2])for k in('min','max')))*(end-start)/2
                gap=min(polygon_distance(footprint({'pose_mm':e['curve'].evaluate(t)[F[0]],'footprint_mm':size}),curtain)for t in(start,end))
                if gap-movement>1e-7:return
                if depth>=24 or end-start<=1e-7:raise ValueError('Actual vehicle occupies the closing lift doorway')
                mid=(start+end)/2;visit(trajectory,start,mid,depth+1);visit(trajectory,mid,end,depth+1)
            for trajectory in trajectories:
                for start,end in _cut_intervals(trajectory,a,b):visit(trajectory,start,end)
        observed=sorted(e['time_s']for e in events if e['event']=='door_line_clear'and e.get('clear')is True and e.get('level')==row['level']and a-1e-8<=e['time_s']<=b+1e-8)
        if not observed or observed[0]>a+.05000001 or b-observed[-1]>.05000001 or any(y-x>.05000001 for x,y in zip(observed,observed[1:])):
            raise ValueError('Door closure lacks the required continuous synthetic observation sequence')
    return {**result,'requests':len(windows),'capacity':len(lanes),'source_passing_gap_mm':passing_gap,'attached_episodes':attached,
            'fully_open_FK_gates':gates,'curtain_intervals':curtain_intervals,
            'basis':'actual source-timed schedule, native cabin lane assignment, own lifecycle events, numeric FK/open-door gates and continuous exported door-curtain exclusion'}


def check_perception(program,trajectories,source,navigation,catalog,windows):
    """Audit original anonymous inputs and actual selected stop curves.

    The trace is evidence, never a pass flag. Every scan pose and decision PVA
    binds to the independent exported trajectory. Native static map matching
    and the source-gated fixed-home contract are rebuilt before gap replay.
    """
    from building_fleet_control import Controller,qualified_perception_limit,_qualified_scalar_stop
    from building_fleet_runner import native_scan_geometry
    from building_fleet_sim import SegmentIndex
    evidence=program.get('own_input_evidence')
    if not isinstance(evidence,dict)or evidence.get('format')!='solidcraftbot.building-fleet-own-input-evidence/1':
        raise ValueError('Original own-input trace required; perception compiler flags are insufficient')
    path=model.resolve_pin({'path':evidence['path'],'sha256':evidence['sha256']})
    cfg=model.resolved_sensor(source);linear=source['motion']['empty_linear_limits']
    limits=dict(zip(('velocity','acceleration','jerk'),(linear['velocity_mm_s'],linear['acceleration_mm_s2'],linear['jerk_mm_s3'])))
    angular=model.reference(source,'angular_profile')['limits']['angular'];radius=navigation.radius
    limit=qualified_perception_limit(tuple(sorted(cfg.items())),tuple(sorted(limits.items())),radius,source['geometry']['localization_tolerance_mm'])
    settings={**cfg,'desired_speed_mm_s':limit['applied_velocity_mm_s']}
    uncertainty=cfg['range_error_mm']+source['geometry']['localization_tolerance_mm']+cfg['range_mm']*math.sin(math.radians(cfg['angular_step_deg']))
    visible=cfg['range_mm']-radius-uncertainty;reaction=cfg['period_s']+cfg['latency_s']+cfg['stale_after_s']
    static,cabins,landings=native_scan_geometry(navigation)
    statics={k:SegmentIndex(v)for k,v in static.items()};cabins={k:SegmentIndex(v)for k,v in cabins.items()};landings={k:SegmentIndex(v)for k,v in landings.items()}
    aliases={(source['depot']['level'],area):catalog['aliases'][source['depot']['level']+'.room.'+area]for area in source['depot']['areas']}
    maps={t.identity:depot.FixedHomeMap(t.identity,navigation.homes,navigation.envelope,aliases,
        cfg['range_error_mm']+source['geometry']['localization_tolerance_mm'])for t in trajectories}
    by_id={t.identity:t for t in trajectories};ports={p['id']:p for p in navigation.mesh.manifest['elevator']['ports']if p['active']}
    paths={};clocks={};scan_history={t.identity:collections.deque(maxlen=8)for t in trajectories};decisions={t.identity:set()for t in trajectories}
    counts=collections.Counter();groups={};minimum=math.inf;checked_stops=0;scan_previous={};global_time=-math.inf
    perceptions=collections.defaultdict(list)
    for m in program['received_messages']:
        if m['kind']=='perception':perceptions[(m['vehicle_id'],m['payload']['captured_s'])].append(m['payload']['scan'])
    with gzip.open(path,'rt',encoding='utf-8')as stream:
        for line in stream:
            if len(line)>16*1024*1024:raise ValueError('Unbounded own-input evidence row')
            row=json.loads(line,parse_constant=lambda _:(_ for _ in()).throw(ValueError('Nonfinite trace JSON')));kind=row.get('kind');counts[kind]+=1
            if kind=='own_path':
                fields={'points_mm','corner_trim_mm','zone_caps','reverse'}
                if set(row)!={'kind','id',*fields}:raise ValueError('Own path bank contains unexpected controller knowledge')
                data={k:row[k]for k in fields};digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
                if digest!=row['id']or digest in paths:raise ValueError('Changed/duplicate own path bank identity')
                path_curve=motion.Path(row['points_mm'],row['corner_trim_mm']);caps=row['zone_caps']
                if type(row['reverse'])is not bool or any(len(v)!=2 or not 0<=finite(v[0])<=path_curve.length or not 0<finite(v[1])<=limits['velocity']for v in caps)or caps!=sorted(caps)or len({v[0]for v in caps})!=len(caps):
                    raise ValueError('Source-bounded ordered own zone caps required')
                paths[digest]={'path':path_curve,'caps':caps,'reverse':row['reverse'],'geometry':{}}
            elif kind=='stop_clock':
                if set(row)!={'kind','id','points'}:raise ValueError('Stop bank contains unexpected fields')
                digest=hashlib.sha256(json.dumps(row['points'],separators=(',',':'),allow_nan=False).encode()).hexdigest()
                if digest!=row['id']or digest in clocks:raise ValueError('Changed/duplicate scalar stop identity')
                clock=motion.floor.motion.Curve(row['points'])
                if any(len(p[f])!=1 for p in clock.points for f in F[:3])or any(abs(t*1000-round(t*1000))>1e-5 for t in clock.times)or clock.times[0]!=0 or clock.points[0][F[0]][0]!=0:
                    raise ValueError('Selected stop must be an original zero-origin scalar clock')
                bounds=motion.floor.motion.bounds(clock)
                if bounds[F[1]]['min'][0]<-1e-8 or any(abs(clock.points[-1][f][0])>1e-8 for f in F[1:3])or bounds[F[2]]['max_abs'][0]>limits['acceleration']*(1+1e-6)or bounds[F[3]]['max_abs'][0]>limits['jerk']*(1+1e-6):
                    raise ValueError('Selected scalar stop violates monotonicity/rest/source bounds')
                clocks[digest]=clock
            elif kind=='scan':
                if set(row)!={'kind','vehicle_id','captured_s','pose_mm_rad','level','z_mm','returns_local_mm'}:raise ValueError('Only anonymous local vectors and own localization may enter scan evidence')
                identity=row['vehicle_id'];at=finite(row['captured_s'],0)
                if identity not in by_id or at<scan_previous.get(identity,-math.inf)or abs(at/cfg['period_s']-round(at/cfg['period_s']))>1e-7:raise ValueError('Chronological source-periodic own scans required')
                if identity in scan_previous and at-scan_previous[identity]>cfg['period_s']+1e-7:raise ValueError('Original scan stream has a missing capture')
                scan_previous[identity]=at;trajectory=by_id[identity];pose=trajectory.pose(at);e=trajectory.episode(at)
                if not _same_pose(row['pose_mm_rad'],[pose[0],pose[1],pose[3]])or abs(finite(row['z_mm'])-pose[2])>1e-6 or row['level']!=e['level_id']:raise ValueError('Scan input contains a non-own capture localization')
                if not isinstance(row['returns_local_mm'],list)or len(row['returns_local_mm'])>360//cfg['angular_step_deg']:raise ValueError('Original full-circle anonymous scan vectors required')
                for vector in row['returns_local_mm']:
                    if len(vector)!=2 or math.hypot(*[finite(v)for v in vector])>cfg['range_mm']+cfg['range_error_mm']:raise ValueError('Anonymous scan exceeds the source beam/range envelope')
                vectors=row['returns_local_mm'];near=min(vectors,key=lambda p:math.hypot(*p),default=None)
                summary={'return_count':len(vectors),'nearest_mm':math.hypot(*near)if near is not None else None,'bearing_rad':math.atan2(near[0],near[1])if near is not None else None}
                for reported in perceptions.pop((identity,at),[]):
                    if summary!=reported:raise ValueError('Received perception summary is not the original anonymous scan')
                scan_history[identity].append(row)
            elif kind=='decision':
                fields={'kind','vehicle_id','time_s','path_id','progress_mm','velocity_mm_s','acceleration_mm_s2','zone_cap_mm_s','captured_s','own_grant_permits','selected_stop_clock','own_conditional_home_map_grant','decision','mode','observation_range_margin_mm'}
                if set(row)!=fields:raise ValueError('Only declared own state, anonymous scan and own grants may enter decision evidence')
                identity=row['vehicle_id'];at=finite(row['time_s'],0)
                if identity not in by_id or at<global_time-1e-8 or abs(at/.05-round(at/.05))>1e-7 or at in decisions[identity]:raise ValueError('Unique chronological actual0.05s decision states required')
                global_time=at;decisions[identity].add(at);trajectory=by_id[identity];e=trajectory.episode(at);jet=e['curve'].evaluate(at)
                bank=paths.get(row['path_id'])
                if bank is None:raise ValueError('Decision does not reference its original own route bank')
                y=finite(row['progress_mm'],0);v=finite(row['velocity_mm_s'],0);a=finite(row['acceleration_mm_s2'])
                if y>bank['path'].length+1e-5:raise ValueError('Own progress left its original path')
                pose,V,A=bank['path'].pva(y,v,a);offset=math.pi if bank['reverse']else 0.
                pose[2]+=offset;pose[2]=jet[F[0]][2]+math.remainder(pose[2]-jet[F[0]][2],2*math.pi)
                if any(not _same_pose(x,z,1e-5)for x,z in zip((pose,V,A),(jet[F[0]],jet[F[1]],jet[F[2]]))):raise ValueError('Decision own PVA differs from actual exported trajectory')
                key=(identity,e.get('leg_id'),row['path_id']);group=groups.setdefault(key,{'first':at,'clear_since':None,'previous':'waiting'})
                car=Controller.__new__(Controller);car.path=bank['path'];car.source=source;car.radius=radius;car.half_length=max(abs(navigation.envelope['min'][0]),abs(navigation.envelope['max'][0]));car.half_width=max(abs(navigation.envelope['min'][1]),abs(navigation.envelope['max'][1]));car.settings=settings;car.limits=limits;car.angular=angular;car.y=y;car.v=v;car.a=a;car.goal=bank['path'].length;car.zone_caps=bank['caps'];car.zone_velocity_cap=max([settings['desired_speed_mm_s'],*[min(settings['desired_speed_mm_s'],cap)for _,cap in bank['caps']]]);car.heading_offset=pose[2]-bank['path'].evaluate(y)[0][2];car.recorded=[{'pose_mm_rad':jet[F[0]]}];car.record_times=[group['first']];car._geometry_cache=bank['geometry'];car.own_pose_at=lambda captured,t=trajectory:[*t.pose(captured)[:2],t.pose(captured)[3]]
                expected_cap=car._zone_cap_at(y)
                if abs(finite(row['zone_cap_mm_s'])-expected_cap)>1e-6:raise ValueError('Decision cap differs from the original source-bound own path cap')
                grant=row['own_conditional_home_map_grant']
                if type(grant)is not dict or set(grant)-{'status','resource'}:raise ValueError('A conditional home map accepts only its own resource grant')
                if grant.get('status')=='granted'and not _covered(windows,identity,grant.get('resource'),at,at):raise ValueError('Conditional home matching lacks its actual own depot-room grant')
                maps[identity].set_own_grant(grant);known=[];port=ports.get(e.get('port_id'))
                if port is not None and e.get('lift_phase')in('boarding','alighting'):
                    sides=(port['side'],)
                    if sides in cabins:known.append(cabins[sides])
                    if(e['level_id'],sides)in landings:known.append(landings[e['level_id'],sides])
                def match(own,local,index=statics[e['level_id']],known=known,mapped=maps[identity]):
                    x,y,yaw=own;side,forward=local;point=(x+math.cos(yaw)*forward-math.sin(yaw)*side,y+math.sin(yaw)*forward+math.cos(yaw)*side)
                    tolerance=cfg['range_error_mm']+source['geometry']['localization_tolerance_mm']
                    return index.matches(point,tolerance)or any(k.matches(point,tolerance)for k in known)or mapped.matches(own,local)
                car.static_return=match;capture=row['captured_s'];available=[s for s in scan_history[identity]if s['captured_s']+cfg['latency_s']<=at+1e-8]
                latest=available[-1]if available else None
                if (latest['captured_s']if latest else None)!=capture:raise ValueError('Decision scan is not the latest delayed own observation')
                scan=None if latest is None else {'captured_s':latest['captured_s'],'returns_local_mm':latest['returns_local_mm']}
                gap,_=car._observed_gap(scan,at);stop=clocks.get(row['selected_stop_clock'])if row['selected_stop_clock']is not None else None
                if (v>1e-8 or abs(a)>1e-8)and stop is None:raise ValueError('Moving decision lacks its actual selected bounded stop clock')
                distance=duration=0.
                if stop is not None:
                    if abs(stop.points[0][F[1]][0]-v)>1e-6 or abs(stop.points[0][F[2]][0]-a)>1e-6:raise ValueError('Selected stop does not begin at its actual own velocity/acceleration')
                    distance=stop.points[-1][F[0]][0];duration=stop.times[-1]
                    if y+distance>car.goal+1e-5 or not car._admissible(stop,y)[0]:raise ValueError('Selected actual Cartesian stop fails source/angular/zone/no-stop bounds')
                    checked_stops+=1
                closing=max(expected_cap,cfg['maximum_obstacle_closing_speed_mm_s']);required=cfg['clearance_mm']+distance+(expected_cap+closing)*reaction+closing*duration
                if row['observation_range_margin_mm']is not None:finite(row['observation_range_margin_mm'])
                decision=row['decision'];mode=row['mode']
                if mode in('waiting','braking')or group['previous']in('waiting','braking'):
                    launch=_qualified_scalar_stop(expected_cap,0.,limits['acceleration'],limits['jerk'],closing)
                    if launch is None:raise ValueError('Source launch cap has no independently bounded stopping family')
                    required=max(required,cfg['clearance_mm']+launch['distance_mm']+(expected_cap+closing)*reaction+closing*launch['duration_s'])
                minimum=min(minimum,visible-required)
                if visible<required-1e-6:raise ValueError('Actual selected stop/reaction/closing envelope exceeds finite sensor range')
                if decision['mode']!=mode or type(row['own_grant_permits'])is not bool:raise ValueError('Decision mode and explicit own grant differ')
                if mode!='arrived':
                    if abs(finite(decision['observed_gap_mm'])-gap)>1e-5 or abs(finite(decision['required_gap_mm'])-required)>1e-5:raise ValueError('Decision gap/range claim differs from independent anonymous-input replay')
                    clear=row['own_grant_permits']and gap>required
                    if clear:
                        if group['clear_since']is None:group['clear_since']=at
                    else:
                        group['clear_since']=None
                        if v>1e-8 and mode!='braking':raise ValueError('Observed obstruction did not produce bounded braking')
                    if group['previous']=='waiting'and mode=='driving'and(group['clear_since']is None or at-group['clear_since']<cfg['clear_observation_s']-1e-8):raise ValueError('Restart lacks its source fresh-clear observation interval')
                group['previous']=mode
            else:raise ValueError('Unknown own-input evidence row')
    if dict(counts)!=evidence['counts']or not counts['scan']or not counts['decision']or not counts['own_path']or perceptions:
        raise ValueError('Original own-input evidence counts/received scan coverage are incomplete')
    expected=0
    for trajectory in trajectories:
        for e in trajectory.episodes:
            if e['mode']!='driving':continue
            for tick in range(math.ceil(e['start_s']/.05-1e-7),math.ceil(e['end_s']/.05-1e-7)):
                at=round(tick*.05,3);expected+=1
                if at not in decisions[trajectory.identity]:raise ValueError('Exported driving interval lacks its actual controller-input observation')
    return {'passed':True,'trace':{'path':evidence['path'],'sha256':evidence['sha256']},'rows':dict(counts),
            'driving_decision_coverage':expected,'checked_selected_stops':checked_stops,'minimum_range_margin_mm':minimum,
            'derived_limit':limit,'basis':'raw own anonymous scan/capture/decision replay, source static matching and exclusive fixed-home invariant, actual selected stop polynomials, full reaction/staleness/closing envelope and fresh-clear restart; no perception pass flags consumed'}


def check_waiting_occupancy(trajectories,navigation,events,duration):
    """Every unowned bay remains excluded between actual grant boundaries."""
    from building_fleet_sim import footprint,polygon_distance
    replay=check_waiting_history(events,duration,navigation,{t.identity for t in trajectories})
    windows={};held={};starts={}
    for row in events:
        own=(row['vehicle_id'],row['role']);key=(row['level'],row['slot']);event=row['event'];at=row['time_s']
        if event=='waiting_granted':held[own]=key;starts[own]=at
        elif event=='waiting_promoted':
            old=(row['vehicle_id'],'destination');held[own]=held.pop(old);starts[own]=starts.pop(old)
        else:
            windows.setdefault((own[0],key),[]).append((starts.pop(own),at));del held[own]
    cuts=[t for rows in windows.values()for pair in rows for t in pair];intervals=refinements=0
    size=[navigation.envelope['length_mm'],navigation.envelope['width_mm']]
    def visit(trajectory,e,key,polygon,a,b,depth=0):
        nonlocal intervals,refinements
        intervals+=1
        if any(x<=a+1e-7 and y>=b-1e-7 for x,y in windows.get((trajectory.identity,key),[])):return
        raw=curve_extrema(e['curve'],a,b,1)
        movement=(math.hypot(*(max(abs(raw[k][i])for k in('min','max'))for i in range(2)))+
                  navigation.radius*max(abs(raw[k][2])for k in('min','max')))*(b-a)/2
        distance=min(polygon_distance(footprint({'pose_mm':e['curve'].evaluate(t)[F[0]],'footprint_mm':size}),polygon)for t in(a,b))
        if distance-movement>=navigation.reserve-1e-7:return
        if depth>=24 or b-a<=1e-7:raise ValueError('Actual body occupies or re-enters a lift waiting bay without its own live grant')
        refinements+=1;mid=(a+b)/2;visit(trajectory,e,key,polygon,a,mid,depth+1);visit(trajectory,e,key,polygon,mid,b,depth+1)
    for trajectory in trajectories:
        for e in trajectory.episodes:
            if e['attached_cabin']:continue
            level=e['level_id']
            for slot,polygon in enumerate(navigation.waiting_bay_polygons.get(level,[])):
                for a,b in _cut_intervals(trajectory,e['start_s'],e['end_s'],[*e['curve'].times,*cuts]):visit(trajectory,e,(level,slot),polygon,a,b)
    return {**replay,'occupancy_intervals':intervals,'refinements':refinements,
            'occupancy_basis':'oriented actual bodies, polynomial interval displacement, every live grant/release boundary and recursive conservative exclusion; ungranted re-entry forbidden'}


def _context(program,source,navigation):
    if navigation is None or getattr(navigation,'config',None)!=source:raise ValueError('Current independently prepared source-matched navigation required')
    verify_pins(program['source_files_sha256'])
    required={**model.source_pins(source),**model.protected_pins()}
    required.update({k:v for k,v in source_pins(source).items()if k!='scripts/building_fleet_checks.py'})
    if any(program['source_files_sha256'].get(k)!=v for k,v in required.items()):raise ValueError('Program omits current source/runtime/support/protected pins')
    expected={f'BF{i:02d}'for i in range(1,21)}
    if program.get('format')!='solidcraftbot.building-fleet-program/1'or program.get('complete')is not True:raise ValueError('Actual complete20-vehicle exported program required')
    if program.get('seed')!=source['missions']['seed']or program.get('targets')!=source['missions']['targets']:raise ValueError('Exported mission seed/targets differ from the exact current source')
    duration=finite(program['duration_s'],0)
    if not source['missions']['minimum_duration_s']<=duration<=source['missions']['maximum_duration_s']:raise ValueError('Actual model duration exceeds source mission contract')
    if program.get('qualification')!=source['qualification']:raise ValueError('Export must preserve every synthetic/open qualification flag')
    rows=program['trajectories']
    if len(rows)!=20 or {r['vehicle_id']for r in rows}!=expected:raise ValueError('Exactly BF01..20 exported trajectories required')
    manifest=navigation.mesh.manifest
    if program['levels']!=manifest['levels']:raise ValueError('Program floor heights differ from the source-pinned native scene')
    lift=timeline_from_manifest(manifest,program['lift_schedule']);levels={r['id']:r for r in manifest['levels']}
    trajectories=[Trajectory(row,levels,lift)for row in rows]
    for trajectory in trajectories:
        if trajectory.starts[0]!=0 or abs(trajectory.episodes[-1]['end_s']-duration)>1e-8:raise ValueError('All20 vehicles must cover the identical complete model interval')
    return trajectories,lift


def _geometry_result(callback,program,source,navigation,trajectories,lift):
    if not callable(callback):raise ValueError('Canonical independent full-episode geometry callback required; embedded geometry flags cannot qualify an export')
    result=callback(program,source,navigation,trajectories,lift)
    if not isinstance(result,dict):raise ValueError('Explicit independent geometry evidence required')
    expected={(t.identity,index)for t in trajectories for index,_ in enumerate(t.episodes)}
    lift_expected={(t.identity,index)for t in trajectories for index,e in enumerate(t.episodes)
                   if e['attached_cabin']or e.get('lift_phase')in('boarding','alighting')}
    for name in('support','collision','lift'):
        row=result.get(name)
        if not isinstance(row,dict)or row.get('passed')is not True or len(row)<2:raise ValueError('Independent '+name+' geometry evidence failed or missing')
        coverage={(r['vehicle_id'],r['episode'])for r in row.get('covered_episodes',[])}
        if coverage!=(lift_expected if name=='lift'else expected):raise ValueError('Independent '+name+' geometry does not cover every actual exported episode')
    return result


def check_program(program_path,source=None,navigation=None,*,resource_catalog=None,geometry_check=None,output=None):
    """Produce the external /2 report bound to the exact program bytes.

    Failed checks remain explicit rows. Missing authoritative context cannot
    turn into a compiler flag or a successful report. Reports are never added
    back into the program, avoiding a program/report digest cycle.
    """
    started=time.monotonic();source=model.load()if source is None else model.validate(copy.deepcopy(source))
    path=Path(program_path).resolve()
    if not path.is_relative_to(model.ROOT.resolve()):raise ValueError('Project-local exact program bytes required')
    original_digest=model.digest(path);program=model.read_json(path);pins=source_pins(source)
    trajectories,lift=_context(program,source,navigation)
    if resource_catalog is None:raise ValueError('Independently rebuilt canonical resource catalog required')
    catalog=resource_catalog.report()if hasattr(resource_catalog,'report')else copy.deepcopy(resource_catalog)
    if catalog!=program['resource_catalog']:raise ValueError('Exported resource catalog differs from independently rebuilt source geometry')
    checks={};cache={}
    def run(name,operation):
        try:
            row=operation()
            if not isinstance(row,dict)or row.get('passed')is not True or len(row)<2:raise ValueError('Explicit positive metrics/evidence required')
            checks[name]=row
        except (ValueError,RuntimeError,KeyError,TypeError,ArithmeticError,IndexError)as exc:
            checks[name]={'passed':False,'error':type(exc).__name__+': '+str(exc)}
    def coverage():
        rows=check_coverage(program,trajectories,navigation,source)
        return {'passed':True,'targets':rows,'source_target_count':len(source['missions']['targets']),
                'basis':'unique moving actual polynomial room witnesses and received completion events; authoritative source polygons'}
    run('coverage',coverage);run('homes',lambda:check_homes(trajectories,navigation,program))
    try:
        checks['dynamics'],checks['no_stop']=check_exported_motion(trajectories,source,navigation.radius)
    except (ValueError,RuntimeError,KeyError,TypeError,ArithmeticError,IndexError)as exc:
        for name in('dynamics','no_stop'):checks[name]={'passed':False,'error':type(exc).__name__+': '+str(exc)}
    if checks['dynamics']['passed']:
        try:checks['dynamics']['source_zones']=check_source_zones(program,trajectories,navigation,source)
        except (ValueError,RuntimeError,KeyError,TypeError,ArithmeticError,IndexError)as exc:
            checks['dynamics']={'passed':False,'error':type(exc).__name__+': '+str(exc)}
    def resources():
        windows=check_resource_history(program['resource_events'],program['duration_s'],{t.identity for t in trajectories});cache['windows']=windows
        if any(resource not in catalog['resources']for _,resource in windows):raise ValueError('A grant uses a resource outside the canonical source catalog')
        return {'passed':True,'occupancy':check_resource_occupancy(trajectories,catalog,windows,navigation.homes),
                'waiting':check_waiting_occupancy(trajectories,navigation,program['waiting_events'],program['duration_s']),
                'conditional_depot':check_depot(trajectories,navigation,catalog,windows)}
    run('resources',resources)
    run('telemetry',lambda:check_telemetry(program,trajectories,source,navigation))
    run('lift',lambda:check_lift_program(program,trajectories,navigation,source,lift))
    if checks['resources']['passed']:
        run('perception',lambda:check_perception(program,trajectories,source,navigation,catalog,cache['windows']))
    else:checks['perception']={'passed':False,'error':'Actual resource/depot invariant failed; conditional map matching cannot be authorized'}
    try:
        geometry=_geometry_result(geometry_check,program,source,navigation,trajectories,lift)
        checks['support']=geometry['support']
        run('collision',lambda:{'passed':True,'static_geometry':geometry['collision'],
            'pairs':check_pair_clearance(trajectories,navigation,program['duration_s'])})
        if checks['lift']['passed']:checks['lift']['geometry']=geometry['lift']
    except (ValueError,RuntimeError,KeyError,TypeError,ArithmeticError,IndexError)as exc:
        for name in('support','collision'):checks[name]={'passed':False,'error':type(exc).__name__+': '+str(exc)}
        checks['lift']['passed']=False;checks['lift']['geometry_error']=str(exc)
    if original_digest!=model.digest(path)or pins!=source_pins(source):raise ValueError('Program/source bytes changed during independent verification')
    result={'format':FORMAT,'passed':all(checks[name]['passed']is True for name in CHECKS),
        'program':{'path':str(path.relative_to(model.ROOT.resolve())),'sha256':original_digest},
        'source_files_sha256':pins,'checks':checks,'duration_s':program['duration_s'],'seed':source['missions']['seed'],
        'elapsed_wall_s':time.monotonic()-started,'qualification':copy.deepcopy(source['qualification']),
        'scope':'Independent exported-byte source/home/room/PVA/quantized/no-stop/resource/lift/anonymous-input/received-radio checks plus canonical full-episode geometry callbacks. Native full-program BRep and actual browser execution are separate mandatory reports.'}
    if output is not None:
        destination=Path(output).resolve()
        if not destination.is_relative_to((model.ROOT/'exports').resolve()):raise ValueError('Independent report belongs in ignored project exports')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('x',encoding='utf-8',newline='\n')as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    return result


def check_source_zones(program,trajectories,navigation,source):
    """Apply the source room/lift/door cap to actual exported polynomials."""
    from building_fleet_clearance import PolygonIndex
    from building_fleet_zones import source_regions,point_distance
    guard=navigation.radius+navigation.reserve+navigation.navigation_margin_mm
    cap=source['motion']['zone_velocity_mm_s'];used_doors=set();room_intervals=door_crossings=lift_crossings=0
    zones={level:[r['polygon_mm']for r in source_regions(navigation,level)]for level in navigation.topological}
    zone_indexes={level:PolygonIndex(polygons)for level,polygons in zones.items()}
    objects=navigation.mesh.manifest['objects'];doors={o['id']:o for o in objects if o.get('mechanism')=='room_door'}
    supplied=program['room_route_object_ids']
    if not isinstance(supplied,list)or len(set(supplied))!=len(supplied)or any(name not in doors or doors[name].get('initial_state',doors[name]['reference_state'])!='open'for name in supplied):
        raise ValueError('Only current source-open room doors may be fleet route doors')
    def visit(curve,polygon,a,b,depth=0):
        nonlocal room_intervals
        room_intervals+=1;velocity=curve_extrema(curve,a,b,1)
        upper=math.hypot(*(max(abs(velocity[k][i])for k in('min','max'))for i in range(2)))
        if upper<=cap*(1+1e-6):return
        mid=(a+b)/2;jet=curve.evaluate(mid);position=jet[F[0]][:2];raw=curve_extrema(curve,a,b)
        delta=math.hypot(*(max(abs(raw[k][i]-position[i])for k in('min','max'))for i in range(2)))
        if point_distance(position,polygon)>guard+delta+1e-7:return
        if point_distance(position,polygon)<=guard and math.hypot(*jet[F[1]][:2])>cap*(1+1e-6):raise ValueError('Actual exported room/lift velocity exceeds the source zone cap')
        if depth>=24 or b-a<=1e-7:raise ValueError('Actual source-zone interval cannot be certified below its velocity cap')
        visit(curve,polygon,a,mid,depth+1);visit(curve,polygon,mid,b,depth+1)
    for trajectory in trajectories:
        for e in trajectory.episodes:
            if e['mode']!='driving':continue
            curve=e['curve'];level=e['level_id']
            position_bounds=[]
            for a,b in zip(curve.times,curve.times[1:]):
                raw=curve_extrema(curve,a,b);position_bounds.append(raw)
                for polygon in zone_indexes[level].query([v-guard for v in raw['min'][:2]],[v+guard for v in raw['max'][:2]]):
                    if any(max(p[k]for p in polygon)+guard<raw['min'][k]or min(p[k]for p in polygon)-guard>raw['max'][k]for k in range(2)):continue
                    visit(curve,polygon,a,b)
            crossings=[]
            for portal in navigation.portals[level]:
                if not portal.get('opening'):continue
                candidates=[o for o in doors.values()if o.get('level_id')==level and o.get('opening_id')==portal['opening']]
                if len(candidates)!=1:raise ValueError('Current source portal must have one native room door')
                crossings.append((portal['centre_mm'],portal['normal'],portal['tangent'],portal['opening_width_mm']/2,candidates[0]['id']))
            for port in navigation.mesh.manifest['elevator']['ports']:
                if not port['active']or port['level_id']!=level:continue
                centre_y=(navigation.cabin_interior_mm['min'][1]+navigation.cabin_interior_mm['max'][1])/2
                crossings.append(([port['plane_x_mm'],centre_y],[1,0],[0,1],
                    (navigation.cabin_interior_mm['max'][1]-navigation.cabin_interior_mm['min'][1])/2,None))
            for index,coeffs in enumerate(curve.segments):
                start,end=curve.times[index:index+2]
                raw=position_bounds[index]
                for centre,normal,tangent,width,door in crossings:
                    def projected(axis):
                        return (sum(axis[k]*(raw['min'][k]if axis[k]>=0 else raw['max'][k])-centre[k]*axis[k]for k in range(2)),
                                sum(axis[k]*(raw['max'][k]if axis[k]>=0 else raw['min'][k])-centre[k]*axis[k]for k in range(2)))
                    low,high=projected(normal)
                    if low>1e-6 or high< -1e-6:continue
                    low,high=projected(tangent)
                    if low>width+1e-6 or high< -width-1e-6:continue
                    signed=[normal[0]*x+normal[1]*y for x,y in zip(coeffs[0],coeffs[1])];signed[0]-=sum(centre[k]*normal[k]for k in range(2))
                    if max(map(abs,signed))<1e-9:continue
                    roots=motion.floor.motion.real_roots(signed)
                    roots.extend(u for u in(0.,1.)if abs(motion.floor.motion.polynomial(signed,u))<1e-6)
                    for u in roots:
                        at=start+(end-start)*u;jet=curve.evaluate(at)
                        if abs(sum((jet[F[0]][k]-centre[k])*tangent[k]for k in range(2)))>width+1e-6:continue
                        if math.hypot(*jet[F[1]][:2])>cap*(1+1e-6):raise ValueError('Actual exported door/port crossing exceeds the source zone cap')
                        if door is None:lift_crossings+=1
                        else:used_doors.add(door);door_crossings+=1
    if not used_doors<=set(supplied):raise ValueError('An actually crossed room door is missing from the shared freeze set')
    return {'passed':True,'cap_mm_s':cap,'room_intervals':room_intervals,'door_crossings':door_crossings,
            'lift_port_crossings':lift_crossings,'actual_route_door_ids':sorted(used_doors),
            'full_body_guard_mm':guard,'basis':'immutable source_regions, whole-body circumscribed guard and polynomial interval speed bounds, plus actual door/port-plane roots; no generated progress-window/pathcap flags consumed'}
