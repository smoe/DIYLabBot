"""Own-only, source-fenced route work for isolated BF01 planning workers.

Requests are computations for an already received immutable action. They never
allocate missions/resources, advance the world, or contain another car's pose.
"""
import copy
import math
import re
from bisect import bisect_right
from time import perf_counter
from types import SimpleNamespace
from building_fleet_control import Controller,PreparedNominal,preparation_digest,source_perception_limit,F
from building_fleet_model import control_step_s
from building_fleet_motion import Path,compile_motion
from building_fleet_depot import fixed_home_curve_proof
from building_fleet_zones import progress_windows
from building_fleet_starter import RollingController
import l01_local_traffic as local
import tr01_floor_motion as floor

FORMAT='solidcraftbot.building-fleet-own-preparation/1'
RESULT='solidcraftbot.building-fleet-own-preparation-result/1'


def _caps(source,nav,path,action,regions):
    from building_fleet_runner import zone_caps
    windows=progress_windows(path,regions[action['level']],
        nav.radius+nav.reserve+nav.navigation_margin_mm,source['motion']['zone_velocity_mm_s'])
    return zone_caps(source,path,action['points_mm'],action['zone_segments'],action['corner_trim_mm'],windows)


def _absolute_curve(driver,clock,origin,time_s):
    curve=driver._cartesian_curve(clock,origin)
    return floor.motion.Curve([{**p,'time_s':round(p['time_s']+time_s,3)}for p in curve.points])


def _check_absolute(context,request,absolute,phase,mark,*,grants=None):
    source,nav=context['source'],context['nav']
    observed=copy.deepcopy(request['observed']);observed['phase']=phase
    if grants is not None:
        observed['own_grants_at_start']=observed['own_grants']=copy.deepcopy(grants)
    home=None
    if request['action']['level']==source['depot']['level']:
        home=fixed_home_curve_proof(absolute,request['vehicle_id'],nav.homes,nav.envelope,nav.reserve,request['action']['level'])
        if mark:mark('fixed_home')
    proof=context['geometry_checks'](copy.deepcopy(request['action']),absolute,observed)
    if mark:mark('native_geometry')
    if not isinstance(proof,dict)or proof.get('passed')is not True:
        reason=proof.get('reason','missing proof') if isinstance(proof,dict) else 'missing proof'
        raise RuntimeError('Background native curve support/clearance rejected: '+str(reason))
    return {'geometry':proof,'fixed_home':home}


def _geometry(context,request,driver,clock,origin,phase,mark=None):
    absolute=_absolute_curve(driver,clock,origin,request['observed']['time_s'])
    if mark:mark('cartesian_curve')
    if request['kind']=='full_route' or 'rolling_horizon_mm' in request:
        return _check_route_geometry(context,request,absolute,clock.points,origin,phase,mark)
    return _check_absolute(context,request,absolute,phase,mark)


def _owned_departure_bend(path,catalog,level,held):
    """Take one existing bend and its braking straight inside the owned resource."""
    if (held is None or len(path.pieces)<=3 or len(path.pieces[0]['controls'])!=2
            or len(path.pieces[1]['controls'])==2 or len(path.pieces[2]['controls'])!=2):
        return None
    # Cutting the shared Bezier pieces at their boundary keeps the same trim,
    # progress coordinate, sample cells and heading throughout the prefix.
    short=copy.copy(path)
    short.pieces=path.pieces[:3]
    short.ends=path.ends[:3]
    short.length=short.ends[-1]
    short.samples=[sample for sample in path.samples if sample[0]<short.length]
    spans=catalog.spans(level,short)
    if (len(spans)!=1 or spans[0]['resource']!=held or spans[0]['start_progress_mm']!=0
            or spans[0]['end_progress_mm']<short.length):
        return None
    return short,spans


def _checked_result(request,**values):
    result={'format':RESULT,'request_id':request['request_id'],'kind':request['kind'],
        'source_binding':request['source_binding'],'fence':copy.deepcopy(request['fence']),**values}
    result['result_sha256']=preparation_digest(result)
    return result


def _passed_receipt(receipt,field):
    proof=receipt.get(field) if isinstance(receipt,dict) else None
    return isinstance(proof,dict) and proof.get('passed') is True


def _return_release(action, grants):
    """Derive the sole allowed grant change from this source-bound return action."""
    if action.get('lift_phase') or not isinstance(grants,dict):
        return None
    grant=grants.get('waiting_place',{})
    if grant.get('status')!='granted' or grant.get('role')!='start' or grant.get('level')!=action['level']:
        return None
    markers=[m for m in action.get('markers',()) if m['event']=='waiting_place_released']
    if len(markers)!=1:
        return None
    marker=markers[0]
    if (marker['details']!={'level':grant['level'],'slot':grant['slot']}
            or not math.isfinite(marker['progress_mm']) or marker['progress_mm']<=0):
        return None
    return {'marker_mm':marker['progress_mm'],'own_grants':{**grants,'waiting_place':{'status':'none'}}}


def _post_release_scope(request, start_mm, leg_id):
    if request['kind'] not in ('route_interval','continuation'):
        return None
    release=_return_release(request['action'],request['observed'].get('own_grants_at_start'))
    if release is None or start_mm<release['marker_mm']-1e-7:
        return None
    if type(leg_id) is not int or leg_id<=0:
        raise ValueError('Post-release geometry requires the installed own leg')
    return {**release,'leg_id':leg_id}


def _check_route_geometry(context,request,absolute,scalar_points,origin,phase,mark):
    """Check the released bay as an obstacle for every post-marker curve portion."""
    release=_return_release(request['action'],request['observed'].get('own_grants_at_start'))
    scope=request.get('post_release')
    if scope is not None and not isinstance(scope,dict):
        raise ValueError('Post-release geometry requires a bound own scope')
    start=origin+scalar_points[0][F[0]][0]
    expected=_post_release_scope(request,start,(scope or {}).get('leg_id'))
    if scope!=expected:
        raise ValueError('Route geometry has the wrong post-release scope')
    if scope is not None:
        return {**_check_absolute(context,request,absolute,phase,mark,grants=scope['own_grants']),
                'post_release':copy.deepcopy(scope)}
    receipt=_check_absolute(context,request,absolute,phase,mark)
    if release is None or origin+scalar_points[-1][F[0]][0]<=release['marker_mm']-1e-7:
        return receipt
    # The retained scalar clock and Cartesian curve share their PVA knot times.
    # Include the runner's release tolerance at the start of the restricted tail.
    scalar=floor.motion.Curve([{**p,'time_s':t} for p,t in zip(scalar_points,absolute.times)])
    lo,hi=absolute.times[0],absolute.times[-1]
    for _ in range(48):
        at=(lo+hi)/2
        if origin+scalar.evaluate(at)[F[0]][0]<release['marker_mm']-1e-7:
            lo=at
        else:
            hi=at
    index=bisect_right(absolute.times,lo)
    if absolute.times[index]-lo<1e-6:
        # Keep the complete original interval when the remainder would be too short
        # to reconstruct from floating-point PVA without numerical cancellation.
        points=absolute.points[index-1:]
    else:
        cut=absolute.evaluate(lo)
        points=[{'time_s':lo,**{key:cut[key] for key in F[:3]}},*absolute.points[index:]]
    tail=floor.motion.Curve(points)
    receipt['released_bay_tail']={
        **_check_absolute(context,request,tail,phase,mark,grants=release['own_grants']),
        'own_grants':copy.deepcopy(release['own_grants'])}
    return receipt


def _release_receipt_matches(request,receipt,start_mm,end_mm):
    scope=request.get('post_release')
    if receipt.get('post_release')!=scope:
        return False
    if scope is not None:
        return receipt['geometry'].get('own_waiting_slot',False) is None
    release=_return_release(request['action'],request['observed'].get('own_grants_at_start'))
    if release is None or end_mm<=release['marker_mm']-1e-7:
        return True
    tail=receipt.get('released_bay_tail')
    return (start_mm<release['marker_mm']-1e-7 and _passed_receipt(tail,'geometry')
            and tail['geometry'].get('own_waiting_slot',False) is None
            and tail.get('own_grants')==release['own_grants'])


def _interval_binding(request,interval=None):
    # Static geometry uses this action's original waiting-bay/lift context.
    # Current passage ownership is checked independently on every live step.
    fence=request['fence'];level=request['action']['level']
    if fence.get('level')!=level or type(fence.get('generation')) is not int:
        raise ValueError('Missing interval action level or generation')
    grants=request['observed'].get('own_grants_at_start')
    if not isinstance(grants,dict):raise ValueError('Missing original action grants')
    fields=[request['source_binding'],request['vehicle_id'],fence['action_sha256'],
        fence['generation'],level,grants]
    if interval is not None:
        fields.append(interval)
        if 'post_release' in request:fields.append(request['post_release'])
    return preparation_digest(fields)


def _prove_interval(context,request,asset,start,end,mark):
    # Slice the single world-coordinate curve at its original PVA knots, with
    # the original absolute clock and unwrapped yaw at both shared endpoints.
    curve=floor.motion.Curve(asset['points'][start:end+1])
    receipt=_check_route_geometry(context,request,curve,asset['scalar_points'][start:end+1],
                                  0.,'background_nominal_interval',mark)
    if (request['action']['level']==context['source']['depot']['level']
            and (receipt.get('fixed_home') or {}).get('passed') is not True):
        raise ValueError('Original fixed-home proof missing for depot interval')
    interval={'start_knot':start,'end_knot':end,'start_mm':asset['positions'][start],
        'end_mm':asset['positions'][end],'program_sha256':asset['program_sha256']}
    receipt['interval_sha256']=_interval_binding(request,interval)
    asset['end_knot']=end
    return {'interval':interval,'receipt':receipt}


def _next_interval(request,context,mark):
    asset=context.get('rolling_nominals',{}).get(request['vehicle_id'])
    start=request.get('start_knot')
    try:
        if (asset is None or asset['binding']!=_interval_binding(request)
                or request.get('program_sha256')!=asset['program_sha256'] or request['action'].get('lift_phase')
                or type(start)is not int or start!=asset['end_knot'] or start>=len(asset['points'])-1):
            raise ValueError('Interval does not continue its exact source-bound program')
        if asset.get('rejected'):raise ValueError(asset['rejected'])
        end=min(start+32,len(asset['points'])-1)
        mark('restore_interval')
        try:
            values=_prove_interval(context,request,asset,start,end,mark)
        except (RuntimeError,ValueError) as error:
            asset['rejected']=str(error)
            raise
        return _checked_result(request,**values)
    except (RuntimeError,ValueError) as error:
        return _checked_result(request,status='interval_rejected',reason=str(error))


def prepare_route(request,context,*,phase_complete=None):
    """Compute a full route or short C2 connector, without constructing a world.

    The caller must supply its independently restored source binding. Native
    geometry and fixed-home proofs run here; actual scan/brake decisions remain
    in the simulation worker after the observed-state commit fence.
    """
    previous=perf_counter()
    def mark(name):
        nonlocal previous
        if phase_complete is not None:
            phase_complete(name,perf_counter()-previous)
            previous=perf_counter()

    if (type(request)is not dict or request.get('format')!=FORMAT or
            request.get('kind')not in('full_route','continuation','route_interval')or
            request.get('source_binding')!=context.get('source_binding')):
        raise ValueError('The planning worker needs its exact boot source binding')
    if request['fence']['action_sha256']!=preparation_digest(request['action']):raise ValueError('Immutable own action differs from its request fence')
    source,nav=context['source'],context['nav'];action=request['action']
    if request['kind']=='route_interval':return _next_interval(request,context,mark)
    path=Path(action['points_mm'],action['corner_trim_mm'],corner_trim_caps=action.get('corner_trim_caps'))
    caps=copy.deepcopy(request['zone_caps'])
    mark('path_setup')
    if request['kind']=='full_route':
        partial='rolling_horizon_mm' in request
        if partial:
            horizon=request['rolling_horizon_mm']
            if (action.get('lift_phase') or request['vehicle_id'] not in nav.homes or
                    type(horizon) not in(int,float) or not 0<horizon<=path.length):
                return _checked_result(request,status='interval_rejected',reason='Invalid initial rolling horizon')
            try:binding=_interval_binding(request)
            except ValueError as error:return _checked_result(request,status='interval_rejected',reason=str(error))
            assets=context.setdefault('rolling_nominals',{})
            previous_asset=assets.get(request['vehicle_id'])
            if previous_asset and previous_asset['request']['fence']['generation']>=request['fence']['generation']:
                return _checked_result(request,status='interval_rejected',reason='Existing or newer prepared generation')
        velocity=source_perception_limit(source,nav.radius)['applied_velocity_mm_s']
        mark('perception_limit')
        program=compile_motion(path,source,velocity,reverse=action['reverse'],zone_caps=caps,
            variable_corner_speed=context.get('variable_corner_speed', False) and
            (not action.get('lift_phase') or action.get('variable_corner_speed') is True))
        mark('compile_motion')
        driver=Controller(path,source,caps,own_start_s=request['observed']['time_s'],radius_mm=nav.radius,motion_program=program)
        driver.align_initial_heading(request['own_pose_mm_rad'][2])
        mark('nominal_retiming')
        # Preserve the actual checked quantized clock, rather than asking the
        # simulation worker to repeat its full nominal retiming/proof search.
        program['scalar_clock']=copy.deepcopy(driver.nominal_clock.points)
        program_sha=preparation_digest(program)
        if partial:
            points=driver.nominal_clock.points
            absolute=_absolute_curve(driver,driver.nominal_clock,0.,request['observed']['time_s'])
            mark('cartesian_curve')
            asset={'request':copy.deepcopy(request),'binding':binding,'program_sha256':program_sha,
                'points':absolute.points,'scalar_points':points,
                'positions':tuple(p[F[0]][0] for p in points),'end_knot':0}
            assets[request['vehicle_id']]=asset
            # Cover a moving rejoin beyond the starter when available. Later
            # quanta contain at most 32 original intervals.
            first_join=next((i for i,p in enumerate(points) if p[F[0]][0]>horizon+5
                and p[F[1]][0]>1e-6 and abs(p[F[2]][0])<1e-8),None)
            first_past=next((i for i,p in enumerate(points) if p[F[0]][0]>=horizon),len(points)-1)
            end=min(len(points)-1,max(32,first_past,(first_join+1) if first_join is not None else first_past))
            try:values=_prove_interval(context,request,asset,0,end,mark)
            except (RuntimeError,ValueError) as error:
                asset['rejected']=str(error)
                return _checked_result(request,status='interval_rejected',reason=str(error))
        else:
            values={'receipt':_geometry(context,request,driver,driver.nominal_clock,0.,'background_nominal',mark)}
        from building_fleet_runner import WorldRunner
        door_context=SimpleNamespace(nav=nav,route_door_ids=set())
        doors=WorldRunner.door_markers(door_context,action['level'],path)
        spans=context['catalog'].spans(action['level'],path)
        mark('spans_and_door_markers')
        return _checked_result(request,program=program,nominal_proof=driver.nominal_clock_proof,
            **values,program_sha256=program_sha,resource_spans=spans,
            door_markers=doors,room_route_object_ids=sorted(door_context.route_door_ids))
    program=request['program']
    if request.get('program_sha256')!=preparation_digest(program):raise ValueError('Continuation nominal program changed')
    initial_yaw=request['own_pose_mm_rad'][2]
    horizon=request.get('horizon_mm',path.length)
    if type(horizon) not in (int,float) or not 0<horizon<=path.length:
        return _checked_result(request,status='no_checked_connector',anchor=request['anchor'])
    if 'horizon_mm' in request:
        asset=context.get('rolling_nominals',{}).get(request['vehicle_id'])
        if (action.get('lift_phase') or asset is None or asset['binding']!=_interval_binding(request)
                or asset['program_sha256']!=request['program_sha256']
                or horizon>asset['positions'][asset['end_knot']]+1e-8):
            return _checked_result(request,status='no_checked_connector',anchor=request['anchor'],
                reason='Requested join exceeds the source-bound checked nominal')
        # A later horizon can be reached around a corner. Calibrate the
        # path's heading offset using the actual pose at its original start.
        initial_yaw=asset['request']['own_pose_mm_rad'][2]
    prepared=PreparedNominal(source,path,caps,program,request['nominal_proof'],path.length)
    driver=Controller(path,source,caps,radius_mm=nav.radius,motion_program=program,prepared_nominal=prepared)
    driver.align_initial_heading(initial_yaw)
    mark('restore_nominal')
    anchor=request['anchor'];origin=anchor['progress_mm'];v=anchor['velocity_mm_s'];a=anchor['acceleration_mm_s2']
    driver.y=origin;driver.v=v;driver.a=a;driver.now=anchor['time_s']
    # At a confirmed stop the live rolling plan can rejoin an earlier
    # accelerating or braking knot. The connector must match its entire
    # endpoint PVA and pass the same bounds and geometry checks.
    earlier_rest_join = ('horizon_mm' in request and control_step_s(source) > .05
                         and abs(v) < 1e-8 and abs(a) < 1e-8)
    candidates=[p for p in driver.nominal_clock.points if origin+5<p[F[0]][0]<=horizon and p[F[1]][0]>1e-6
                and (earlier_rest_join or abs(p[F[2]][0])<1e-8)]
    # A terminal rest anchor is also valid when no moving nominal node remains.
    if horizon==path.length:candidates.append(driver.nominal_clock.points[-1])
    for target in candidates:
        distance=target[F[0]][0]-origin
        if distance<=0:continue
        duration=max(.02,distance/max(driver._zone_cap_at(origin),1e-9))
        for _ in range(18):
            duration=math.ceil(duration*1000)/1000
            raw=floor.motion.Curve([local.point(0,0,v,a),local.point(duration,distance,target[F[1]][0],target[F[2]][0])])
            scalar=floor.motion.bounds(raw)
            if scalar[F[1]]['min'][0]>=-1e-8 and all(scalar[f]['max_abs'][0]<=driver.limits[k]*(1+1e-6)for f,k in zip(F[1:],('velocity','acceleration','jerk'))):
                connector=driver._quantized_clock(raw,origin)
                valid,bounds=driver._admissible(connector,origin)
                if 'horizon_mm' in request:
                    extent=floor.motion.bounds(connector)[F[0]]
                    valid=valid and origin+extent['min'][0]>=-1e-8 and origin+extent['max'][0]<=horizon+1e-8
                if valid:
                    mark('connector_search')
                    try:receipt=_geometry(context,request,driver,connector,origin,'background_C2_connector',mark)
                    except (ValueError,RuntimeError) as error:
                        if 'horizon_mm' not in request:raise
                        return _checked_result(request,status='no_checked_connector',anchor=anchor,reason=str(error))
                    points=copy.deepcopy(connector.points);join=points[-1]['time_s']
                    for node in driver.nominal_clock.points:
                        if node['time_s']>target['time_s']+1e-9:
                            points.append(local.point(round(join+node['time_s']-target['time_s'],3),node[F[0]][0]-origin,node[F[1]][0],node[F[2]][0]))
                    # C2 at the join follows from exactly shared PVA, and all
                    # suffix intervals retain their original checked PVA bytes.
                    proof={'passed':True,'connector_dynamics':bounds,'join_progress_mm':target[F[0]][0],
                        'suffix_program_sha256':request['program_sha256'],'receipt':receipt,
                        'anchor':copy.deepcopy(anchor),'time_quantum_s':.001,'PVA_continuity':'C2'}
                    mark('join_suffix')
                    return _checked_result(request,clock=points,anchor=anchor,proof=proof)
            duration*=1.2
    mark('connector_search')
    return _checked_result(request,status='no_checked_connector',anchor=anchor)


class BackgroundPreparation:
    """One route computation per immutable active own action and generation."""
    def __init__(self,engine,source_binding):
        if type(source_binding)is not str or not re.fullmatch('[0-9a-f]{64}',source_binding):raise ValueError('Complete SHA-256 worker source binding required')
        self.engine=engine;self.binding=source_binding;self.serial=0;self.queue=[];self.jobs={};self.pending_by_vehicle={}
        self.full={};self.continuations={};self.attempted_anchors={};self.statistics={'submitted':0,'accepted':0,'stale':0,'starters':0,'continuations':0,'rejected':0}
        self.intervals={};self.failures={}

    def pending(self,identity):
        row=self.engine.vehicles[identity]
        if row['action']is None:self.pending_by_vehicle.pop(identity,None)
        return identity in self.pending_by_vehicle and row['driver']is None

    def drain(self):
        result=[];waiting=[]
        departures=getattr(self.engine,'departures',None)
        for job in self.queue:
            if departures is not None and departures.staged(job['vehicle_id']):
                waiting.append(job)
            else:
                result.append(job)
        self.queue=waiting
        return copy.deepcopy(result)

    def snapshot(self):
        return {**self.statistics,'pending':len(self.jobs),'failures':dict(self.failures),
            'checked_intervals':copy.deepcopy(self.intervals),
            'requests':[{'request_id':r['request_id'],'kind':r['kind'],'vehicle_id':r['vehicle_id']}for r in self.jobs.values()]}

    def _fence(self,identity,action):
        e=self.engine
        return {'action_sha256':preparation_digest(action),'level':e.vehicles[identity]['level'],
            'generation':e.vehicles[identity].get('preparation_generation',0),
            'own_grants':copy.deepcopy(e.own_grants(identity)),
            'own_narrow_grant':copy.deepcopy(e.resources.own_grants(identity))}

    def _request(self,identity,action,caps,kind,**values):
        self.serial+=1;e=self.engine
        request={'format':FORMAT,'kind':kind,'request_id':str(self.serial),'source_binding':self.binding,
            'vehicle_id':identity,'action':copy.deepcopy(action),'zone_caps':copy.deepcopy(caps),
            'fence':self._fence(identity,action),'own_pose_mm_rad':e.vehicles[identity]['pose_mm_rad'][:],
            'observed':e.geometry_context(identity,'background_request'),**copy.deepcopy(values)}
        self.jobs[request['request_id']]=request;self.queue.append(request);self.statistics['submitted']+=1
        return request

    def start_drive(self,identity,action):
        e=self.engine;row=e.vehicles[identity]
        if action['level']!=row['level']or row['driver']is not None:raise RuntimeError('Own drive must begin at its observed same-floor rest')
        path=Path(action['points_mm'],action['corner_trim_mm'],corner_trim_caps=action.get('corner_trim_caps'))
        if math.dist(path.evaluate(0)[0][:2],row['pose_mm_rad'][:2])>1e-6:raise RuntimeError('Own route does not begin at observed localization')
        caps=_caps(e.source,e.nav,path,action,e.zone_regions)
        row['preparation_generation']=row.get('preparation_generation',0)+1
        row.pop('waiting_bay_release',None)
        self.failures.pop(identity,None)
        self.intervals.pop(identity,None)
        self.attempted_anchors.pop(identity,None)
        row['action_context']=copy.deepcopy(e.own_grants(identity));row['action']=copy.deepcopy(action)
        request=self._request(identity,action,caps,'full_route');self.pending_by_vehicle[identity]=request['request_id']
        row['phase']='preparing';row['hold_reason']='await_checked_route';row['hold_condition']='same_source_action_and_own_grants'
        if e.progress is not None:e.progress({'phase':'background_route_submitted','vehicle_id':identity,'request_id':request['request_id'],'model_time_s':e.now})
        began=perf_counter()
        self._starter(identity,action,path,caps,request)
        if isinstance(row['driver'],RollingController):
            request['rolling_horizon_mm']=row['driver'].certified_horizon_mm
        elif getattr(e,'departures',None) is not None and e.departures.staged(identity):
            raise RuntimeError('Private departure needs its own checked rolling starter')
        if e.progress is not None:
            e.progress({'phase':'starter_timing','request_id':request['request_id'],'vehicle_id':identity,
                'model_time_s':e.now,'wall_s':perf_counter()-began,'installed':row['driver'] is not None})

    def _starter(self,identity,action,path,caps,request):
        e=self.engine;row=e.vehicles[identity]
        if action.get('lift_phase')or not path.pieces or len(path.pieces[0]['controls'])!=2:return
        held=e.resources.holds.get(identity)
        horizon=path.ends[0];start=path.evaluate(0)[0];end=path.evaluate(horizon)[0]
        release=_return_release(action,request['observed'].get('own_grants_at_start'))
        departures=getattr(e,'departures',None)
        if departures is not None and departures.staged(identity):
            ticket=departures.ticket_for(identity)
            if preparation_digest(action)!=ticket['action_sha256']:
                raise RuntimeError('Private departure action changed before its starter proof')
            held=ticket['resource']
            horizon=min(horizon,ticket['horizon_mm'])
            end=path.evaluate(horizon)[0]
        if release is not None and horizon>=release['marker_mm']-1e-7:
            # The initial full-route result still requires the original grant.
            # No private starter may reach the physical release before it arrives.
            horizon=release['marker_mm']-1e-4
            if horizon<=1e-5:return
            end=path.evaluate(horizon)[0]
        proposed_horizon=horizon
        short=Path([start[:2],end[:2]],action['corner_trim_mm'])
        spans=e.catalog.spans(row['level'],short)
        own=[s for s in spans if s['resource']==held and s['start_progress_mm']<=1e-6 and s['end_progress_mm']>0]
        if not own:return
        horizon=min(horizon,own[0]['end_progress_mm'])
        if horizon<=1e-5:return
        if horizon!=proposed_horizon:
            start=path.evaluate(0)[0];end=path.evaluate(horizon)[0]
            short=Path([start[:2],end[:2]],action['corner_trim_mm'])
            spans=e.catalog.spans(row['level'],short)
        phase='rolling_straight_starter'
        home=e.nav.homes.get(identity)
        if (release is None and home and home['level']==row['level'] and not action['reverse']
                and path.position(0)[:2]==home['pose_mm_rad'][:2]
                and not (departures and departures.staged(identity))):
            extension=_owned_departure_bend(path,e.catalog,row['level'],held)
            if extension is not None:
                short,spans=extension
                horizon=short.length
                phase='rolling_depot_bend_starter'
        cap=source_perception_limit(e.source,e.nav.radius)['applied_velocity_mm_s']
        short_caps=[(at,value)for at,value in caps if at<short.length]
        program=compile_motion(short,e.source,cap,reverse=action['reverse'],zone_caps=short_caps,
            variable_corner_speed=phase=='rolling_depot_bend_starter' and e.variable_corner_speed)
        driver=RollingController(path,e.source,caps,own_start_s=e.now,radius_mm=e.nav.radius,
            static_return=e.static_return(row['level'],None,identity),motion_program=program,certified_horizon_mm=horizon,
            prior_localization=e.prior_localization(identity))
        driver.align_initial_heading(row['pose_mm_rad'][2])
        context={'source':e.source,'nav':e.nav,'geometry_checks':e.geometry_checker}
        receipt=_geometry(context,request,driver,driver.nominal_clock,0.,phase)
        self._install(identity,action,driver,caps,receipt,phase,prepared_spans=spans,
            door_markers=e.door_markers(row['level'],short))
        self.statistics['starters']+=1

    def _install(self,identity,action,driver,caps,receipt,phase,*,prepared_spans=None,door_markers=None):
        from building_fleet_runner import ResourceGate
        e=self.engine;row=e.vehicles[identity]
        markers=copy.deepcopy(action['markers'])+(e.door_markers(row['level'],driver.path)if door_markers is None else copy.deepcopy(door_markers))
        markers.sort(key=lambda m:m['progress_mm'])
        if any(type(m.get('progress_mm'))not in(int,float)or not 0<=m['progress_mm']<=driver.path.length for m in markers):raise ValueError('Actual own marker progress required')
        e.leg_counter+=1
        row.update(driver=driver,gate=ResourceGate(e,identity,driver,row['level'],prepared_spans=prepared_spans),action=copy.deepcopy(action),
            markers=markers,phase='driving',event_cursor=0,leg_id=e.leg_counter)
        row['drives']+=1
        e.geometry_checks.append({'vehicle_id':identity,'leg_id':row['leg_id'],'phase':phase,'proof':copy.deepcopy(receipt['geometry'])})
        if receipt.get('fixed_home')is not None:e.depot_checks.append({'vehicle_id':identity,'leg_id':row['leg_id'],'phase':phase,'proof':copy.deepcopy(receipt['fixed_home'])})
        if e.evidence is not None:row['evidence_path_id']=e.evidence.route(action,caps)
        e.event(identity,'leg_started',{'leg_id':row['leg_id'],'level':row['level'],'terminal':action['terminal']['kind'],'preparation':phase},e.now)
        if not row['mission_pending']:
            state=e.planner.states[identity];queue=[m for m in state['queue']if m['mission_id']not in state['completed']]
            if not any(m['goal']['kind']=='home'for m in queue):e.request_mission(identity,action['prefetch_level'],e.now)

    def _current(self,request):
        e=self.engine;identity=request['vehicle_id'];row=e.vehicles[identity]
        # The action and existing booking are immutable. A source-bound starter
        # may have moved; no peer position is part of this admission fence.
        fence=request['fence']
        same_action=(row['action']is not None and preparation_digest(row['action'])==fence['action_sha256']and
            row.get('preparation_generation',0)==request['fence']['generation']and
            row['level']==fence['level']and not row['done'])
        if not same_action:return False
        grants=e.own_grants(identity)
        if 'rolling_horizon_mm' in request:
            if (row['action'].get('lift_phase') or row['action_context']!=request['observed']['own_grants_at_start']
                    or row['action_context']!=fence['own_grants']):
                return False
            scope=request.get('post_release')
            if scope is not None and scope['leg_id']!=row['leg_id']:
                return False
            release=row.get('waiting_bay_release')
            if (release is not None and release['leg_id']==row['leg_id']
                    and release['generation']==fence['generation']):
                expected=_return_release(row['action'],row['action_context'])
                return (request['kind'] in ('route_interval','continuation')
                        and expected is not None and scope=={**expected,'leg_id':row['leg_id']}
                        and release['grant']==fence['own_grants']['waiting_place']
                        and release['marker_mm']==scope['marker_mm']
                        and release['progress_mm']>=scope['marker_mm']-1e-7
                        and release['time_s']<=e.now and grants==scope['own_grants'])
            # Passage ownership is checked separately by ResourceGate on each step.
            return grants==fence['own_grants']
        return grants==fence['own_grants'] and e.resources.own_grants(identity)==fence['own_narrow_grant']

    def _reject(self,request,reason):
        identity=request['vehicle_id']
        self.jobs.pop(request['request_id'],None)
        self.statistics['rejected']+=1
        if ('rolling_horizon_mm' in request and
                self.engine.vehicles[identity].get('preparation_generation')==request['fence']['generation']):
            self.failures[identity]=reason
            self.continuations.pop(identity,None)
        return {'accepted':False,'status':reason,'request_id':request['request_id']}

    def _accept_interval(self,request,result,nominal):
        identity=request['vehicle_id']
        driver=self.engine.vehicles[identity]['driver']
        interval=result.get('interval');receipt=result.get('receipt')
        if not isinstance(driver,RollingController) or not isinstance(interval,dict) or not isinstance(receipt,dict):
            return False
        first,last=interval.get('start_knot'),interval.get('end_knot')
        nodes=nominal['program']['scalar_clock']
        previous=self.intervals.get(identity)
        expected=previous['end_knot'] if previous else 0
        if (type(first)is not int or type(last)is not int or first!=expected or not first<last<len(nodes)
                or first!=request.get('start_knot',0)
                or interval.get('program_sha256')!=nominal['program_sha256']
                or interval.get('start_mm')!=nodes[first][F[0]][0]
                or interval.get('end_mm')!=nodes[last][F[0]][0]
                or not 0<=interval['start_mm']<interval['end_mm']<=driver.goal+1e-5
                or (last==len(nodes)-1 and abs(interval['end_mm']-driver.goal)>1e-5)
                or receipt.get('interval_sha256')!=_interval_binding(request,interval)
                or not _passed_receipt(receipt,'geometry')
                or not _release_receipt_matches(request,receipt,interval['start_mm'],interval['end_mm'])
                or (request['action']['level']==self.engine.source['depot']['level']
                    and not _passed_receipt(receipt,'fixed_home'))):
            return False
        horizon=driver.goal if last==len(nodes)-1 else interval['end_mm']
        if driver.joined_nominal and not driver.extend_horizon(horizon):
            return False
        self.intervals[identity]={'end_knot':last,'horizon_mm':horizon}
        leg=self.engine.vehicles[identity]['leg_id']
        for field,log in [('geometry',self.engine.geometry_checks),('fixed_home',self.engine.depot_checks)]:
            if receipt.get(field) is not None:
                log.append({'vehicle_id':identity,'leg_id':leg,'phase':'nominal_interval',
                    'interval':dict(interval),'proof':copy.deepcopy(receipt[field])})
        return True

    def accept(self,result):
        if type(result)is not dict:raise ValueError('Own route worker result required')
        request=self.jobs.get(result.get('request_id'))
        departures=getattr(self.engine,'departures',None)
        if request is not None and departures is not None and departures.staged(request['vehicle_id']):
            return {'accepted':False,'status':'await_corridor_handover','request_id':request['request_id']}
        unsigned={k:v for k,v in result.items()if k!='result_sha256'}
        if (request is None or result.get('format')!=RESULT or result.get('source_binding')!=self.binding or
                result.get('kind')!=request['kind']or result.get('fence')!=request['fence']or
                result.get('result_sha256')!=preparation_digest(unsigned)):
            if request is not None and 'rolling_horizon_mm' in request:
                return self._reject(request,'invalid_receipt')
            self.statistics['rejected']+=1;return {'accepted':False,'status':'invalid_receipt','request_id':result.get('request_id')}
        del self.jobs[request['request_id']]
        identity=request['vehicle_id'];row=self.engine.vehicles[identity]
        if 'rolling_horizon_mm' in request and identity in self.failures:
            return self._reject(request,self.failures[identity])
        if not self._current(request):
            self.statistics['stale']+=1
            if 'rolling_horizon_mm' in request:
                return self._reject(request,'stale_geometry_context')
            if request['kind']=='continuation':self.continuations.pop(identity,None)
            elif (row.get('action')==request['action']and
                  row.get('preparation_generation',0)==request['fence']['generation']):
                renewed=self._request(identity,request['action'],request['zone_caps'],'full_route')
                self.pending_by_vehicle[identity]=renewed['request_id']
            return {'accepted':False,'status':'stale_own_fence','request_id':request['request_id']}
        if result.get('status')=='interval_rejected':
            return self._reject(request,str(result.get('reason') or 'interval_rejected'))
        if request['kind']=='route_interval':
            active=self.full.get(identity)
            if active is None or not self._accept_interval(request,result,active[1]):
                return self._reject(request,'invalid_interval_proof')
            self.statistics['accepted']+=1
        elif request['kind']=='full_route':
            if (not isinstance(result.get('program'),dict) or not result['program'].get('scalar_clock') or
                    not isinstance(result.get('nominal_proof'),dict) or result['nominal_proof'].get('time_quantum_s')!=.001 or
                    result.get('program_sha256')!=preparation_digest(result['program'])or
                    not _passed_receipt(result.get('receipt'),'geometry') or
                    type(result.get('resource_spans'))is not list or type(result.get('door_markers'))is not list or
                    type(result.get('room_route_object_ids'))is not list):
                return self._reject(request,'invalid_proof')
            if 'rolling_horizon_mm' in request and not self._accept_interval(request,result,result):
                return self._reject(request,'invalid_interval_proof')
            if 'rolling_horizon_mm' not in request and not _release_receipt_matches(request,result['receipt'],
                    0.,result['program']['scalar_clock'][-1][F[0]][0]):
                return self._reject(request,'invalid_proof')
            self.full[identity]=(request,copy.deepcopy(result));self.statistics['accepted']+=1
            if row['driver']is None:
                if row['pose_mm_rad']!=request['own_pose_mm_rad']:return {'accepted':False,'status':'stale_localization','request_id':request['request_id']}
                path=Path(request['action']['points_mm'],request['action']['corner_trim_mm'],corner_trim_caps=request['action'].get('corner_trim_caps'))
                token=PreparedNominal(self.engine.source,path,request['zone_caps'],result['program'],result['nominal_proof'],path.length)
                driver=Controller(path,self.engine.source,request['zone_caps'],own_start_s=self.engine.now,radius_mm=self.engine.nav.radius,
                    static_return=self.engine.static_return(row['level'],request['action'].get('lift_phase'),identity),
                    motion_program=result['program'],prepared_nominal=token,prior_localization=self.engine.prior_localization(identity))
                driver.align_initial_heading(row['pose_mm_rad'][2])
                self.engine.route_door_ids.update(result.get('room_route_object_ids',[]))
                self._install(identity,request['action'],driver,request['zone_caps'],result['receipt'],'background_nominal',
                    prepared_spans=result.get('resource_spans'),door_markers=result.get('door_markers'))
                self.pending_by_vehicle.pop(identity,None);self.full.pop(identity,None)
            else:
                from building_fleet_runner import ResourceGate
                e=self.engine;e.route_door_ids.update(result.get('room_route_object_ids',[]))
                row['gate']=ResourceGate(e,identity,row['driver'],row['level'],prepared_spans=result.get('resource_spans'))
                extra=[m for m in result.get('door_markers',[])if m['progress_mm']>row['driver'].y+1e-5]
                prior=[m for m in row['markers']if m['event']!='door_passed']
                row['markers']=sorted(prior+copy.deepcopy(extra),key=lambda m:m['progress_mm'])
        else:
            self.continuations.pop(identity,None)
            if result.get('status')=='no_checked_connector':
                # More certified knots or a newly observed anchor can admit another join.
                if result.get('reason'):
                    return self._reject(request,result['reason'])
                self.statistics['rejected']+=1
                return {'accepted':False,'status':'no_checked_connector','request_id':request['request_id']}
            anchor=result.get('anchor')
            proof=result.get('proof',{})
            if (anchor!=request['anchor'] or not isinstance(proof,dict) or proof.get('passed')is not True
                    or ('horizon_mm' in request and (type(proof.get('join_progress_mm')) not in (int,float)
                        or not anchor['progress_mm']<proof['join_progress_mm']<=request['horizon_mm']+1e-5))
                    or proof.get('suffix_program_sha256')!=request['program_sha256']
                    or proof.get('anchor')!=anchor or not _passed_receipt(proof.get('receipt'),'geometry')
                    or ('rolling_horizon_mm' in request and not _release_receipt_matches(request,
                        proof['receipt'],anchor['progress_mm'],proof['join_progress_mm']))
                    or ('rolling_horizon_mm' in request and request['action']['level']==self.engine.source['depot']['level']
                        and not _passed_receipt(proof.get('receipt'),'fixed_home'))):
                return self._reject(request,'invalid_connector')
            self.continuations[identity]=copy.deepcopy(result)
        return {'accepted':True,'status':'ready','request_id':request['request_id']}

    def before_tick(self):
        e=self.engine
        for identity,(original,result)in list(self.full.items()):
            row=e.vehicles[identity];driver=row['driver']
            if not isinstance(driver,RollingController)or not driver.awaiting_continuation:
                self.full.pop(identity,None);self.pending_by_vehicle.pop(identity,None);continue
            if identity in self.failures:continue
            rolling='rolling_horizon_mm' in original
            interval=self.intervals.get(identity)
            horizon=interval['horizon_mm'] if interval else driver.goal
            pending=self.continuations.get(identity)
            if pending is not None and pending['request_id'] in self.jobs:continue
            if pending is not None and e.now>=pending['anchor']['time_s']-1e-8:
                anchor=pending['anchor']
                # The connector was checked inside its requested horizon. Only
                # adjoining intervals on that same nominal enlarge the usable suffix.
                current_request={**original,'fence':pending['fence'],'kind':'continuation',
                    'post_release':pending['proof']['receipt'].get('post_release')}
                if self._current(current_request)and driver.commit_continuation(pending['clock'],result['program']['scalar_clock'],anchor,pending['proof'],
                        horizon_mm=horizon if rolling else None,
                        allow_static_rest_rebase=not bool(original['action'].get('lift_phase'))):
                    self.statistics['continuations']+=1
                else:self.statistics['stale']+=1
                self.continuations.pop(identity,None)
                if not driver.awaiting_continuation:
                    self.full.pop(identity,None);self.pending_by_vehicle.pop(identity,None);continue
            if any(job['vehicle_id']==identity for job in self.jobs.values()):continue
            anchor=None if identity in self.continuations else driver.continuation_anchor()
            if anchor is not None and horizon>=driver.certified_horizon_mm and anchor['progress_mm']<horizon-1e-5:
                signature=(horizon,anchor['progress_mm'],anchor['velocity_mm_s'],anchor['acceleration_mm_s2'])
                if self.attempted_anchors.get(identity)!=signature:
                    self.attempted_anchors[identity]=signature
                    values={'anchor':anchor,'program':result['program'],'program_sha256':result['program_sha256'],
                            'nominal_proof':result['nominal_proof']}
                    if rolling:values['horizon_mm']=horizon
                    request=self._followup(original,'continuation',**values)
                    request['observed']['time_s']=anchor['time_s']
                    self.continuations[identity]={'request_id':request['request_id']}
                    continue
            if interval and interval['end_knot']<len(result['program']['scalar_clock'])-1:
                # Only a scheduling priority. The vehicle's actual step and stop are proved separately.
                fallback=driver._fallback
                stopping_end=driver.y if fallback is None else fallback['origin_mm']+fallback['clock'].points[-1][F[0]][0]
                self._followup(original,'route_interval',start_knot=interval['end_knot'],
                    program_sha256=result['program_sha256'],brake_headroom_mm=max(0.,horizon-stopping_end))

    def _followup(self,original,kind,**values):
        request=self._request(original['vehicle_id'],original['action'],original['zone_caps'],kind,**values)
        if 'rolling_horizon_mm' in original:
            request['rolling_horizon_mm']=original['rolling_horizon_mm']
            for key in ('fence','observed','own_pose_mm_rad'):
                request[key]=copy.deepcopy(original[key])
            row=self.engine.vehicles[original['vehicle_id']]
            if kind=='route_interval':
                nominal=self.full[original['vehicle_id']][1]
                start=nominal['program']['scalar_clock'][values['start_knot']][F[0]][0]
            else:
                start=values['anchor']['progress_mm']
            scope=_post_release_scope(request,start,row.get('leg_id'))
            if scope is not None:request['post_release']=scope
        return request
