"""Own-only, source-fenced route work for isolated BF01 planning workers.

Requests are computations for an already received immutable action. They never
allocate missions/resources, advance the world, or contain another car's pose.
"""
import copy
import math
import re
from time import perf_counter
from types import SimpleNamespace
from building_fleet_control import Controller,PreparedNominal,preparation_digest,source_perception_limit,F
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


def _geometry(context,request,driver,clock,origin,phase,mark=None):
    source,nav=context['source'],context['nav']
    observed=copy.deepcopy(request['observed']);observed['phase']=phase
    absolute=driver._cartesian_curve(clock,origin)
    absolute=floor.motion.Curve([{**p,'time_s':round(p['time_s']+observed['time_s'],3)}for p in absolute.points])
    if mark:mark('cartesian_curve')
    home=None
    if request['action']['level']==source['depot']['level']:
        home=fixed_home_curve_proof(absolute,request['vehicle_id'],nav.homes,nav.envelope,nav.reserve,request['action']['level'])
        if mark:mark('fixed_home')
    proof=context['geometry_checks'](copy.deepcopy(request['action']),absolute,observed)
    if mark:mark('native_geometry')
    if not isinstance(proof,dict)or proof.get('passed')is not True:raise RuntimeError('Background native curve support/clearance rejected')
    return {'geometry':proof,'fixed_home':home}


def _checked_result(request,**values):
    result={'format':RESULT,'request_id':request['request_id'],'kind':request['kind'],
        'source_binding':request['source_binding'],'fence':copy.deepcopy(request['fence']),**values}
    result['result_sha256']=preparation_digest(result)
    return result


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
            request.get('kind')not in('full_route','continuation')or
            request.get('source_binding')!=context.get('source_binding')):
        raise ValueError('The planning worker needs its exact boot source binding')
    if request['fence']['action_sha256']!=preparation_digest(request['action']):raise ValueError('Immutable own action differs from its request fence')
    source,nav=context['source'],context['nav'];action=request['action']
    path=Path(action['points_mm'],action['corner_trim_mm'],corner_trim_caps=action.get('corner_trim_caps'))
    caps=copy.deepcopy(request['zone_caps'])
    mark('path_setup')
    if request['kind']=='full_route':
        velocity=source_perception_limit(source,nav.radius)['applied_velocity_mm_s']
        mark('perception_limit')
        program=compile_motion(path,source,velocity,reverse=action['reverse'],zone_caps=caps)
        mark('compile_motion')
        driver=Controller(path,source,caps,own_start_s=request['observed']['time_s'],radius_mm=nav.radius,motion_program=program)
        driver.align_initial_heading(request['own_pose_mm_rad'][2])
        mark('nominal_retiming')
        receipt=_geometry(context,request,driver,driver.nominal_clock,0.,'background_nominal',mark)
        # Preserve the actual checked quantized clock, rather than asking the
        # simulation worker to repeat its full nominal retiming/proof search.
        program['scalar_clock']=copy.deepcopy(driver.nominal_clock.points)
        from building_fleet_runner import WorldRunner
        door_context=SimpleNamespace(nav=nav,route_door_ids=set())
        doors=WorldRunner.door_markers(door_context,action['level'],path)
        spans=context['catalog'].spans(action['level'],path)
        mark('spans_and_door_markers')
        return _checked_result(request,program=program,nominal_proof=driver.nominal_clock_proof,
            receipt=receipt,program_sha256=preparation_digest(program),resource_spans=spans,
            door_markers=doors,room_route_object_ids=sorted(door_context.route_door_ids))
    program=request['program']
    if request.get('program_sha256')!=preparation_digest(program):raise ValueError('Continuation nominal program changed')
    prepared=PreparedNominal(source,path,caps,program,request['nominal_proof'],path.length)
    driver=Controller(path,source,caps,radius_mm=nav.radius,motion_program=program,prepared_nominal=prepared)
    driver.align_initial_heading(request['own_pose_mm_rad'][2])
    mark('restore_nominal')
    anchor=request['anchor'];origin=anchor['progress_mm'];v=anchor['velocity_mm_s'];a=anchor['acceleration_mm_s2']
    driver.y=origin;driver.v=v;driver.a=a;driver.now=anchor['time_s']
    candidates=[p for p in driver.nominal_clock.points if p[F[0]][0]>origin+5 and p[F[1]][0]>1e-6 and abs(p[F[2]][0])<1e-8]
    # A terminal rest anchor is also valid when no moving nominal node remains.
    candidates.append(driver.nominal_clock.points[-1])
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
                if valid:
                    mark('connector_search')
                    receipt=_geometry(context,request,driver,connector,origin,'background_C2_connector',mark)
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

    def pending(self,identity):
        row=self.engine.vehicles[identity]
        if row['action']is None:self.pending_by_vehicle.pop(identity,None)
        return identity in self.pending_by_vehicle and row['driver']is None

    def drain(self):
        result=self.queue;self.queue=[];return copy.deepcopy(result)

    def snapshot(self):
        return {**self.statistics,'pending':len(self.jobs),'requests':[{'request_id':r['request_id'],'kind':r['kind'],'vehicle_id':r['vehicle_id']}for r in self.jobs.values()]}

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
        row['action_context']=copy.deepcopy(e.own_grants(identity));row['action']=copy.deepcopy(action)
        request=self._request(identity,action,caps,'full_route');self.pending_by_vehicle[identity]=request['request_id']
        row['phase']='preparing';row['hold_reason']='await_checked_route';row['hold_condition']='same_source_action_and_own_grants'
        if e.progress is not None:e.progress({'phase':'background_route_submitted','vehicle_id':identity,'request_id':request['request_id'],'model_time_s':e.now})
        began=perf_counter()
        self._starter(identity,action,path,caps,request)
        if e.progress is not None:
            e.progress({'phase':'starter_timing','request_id':request['request_id'],'vehicle_id':identity,
                'model_time_s':e.now,'wall_s':perf_counter()-began,'installed':row['driver'] is not None})

    def _starter(self,identity,action,path,caps,request):
        e=self.engine;row=e.vehicles[identity]
        if action.get('lift_phase')or not path.pieces or len(path.pieces[0]['controls'])!=2:return
        held=e.resources.holds.get(identity)
        horizon=path.ends[0];start=path.evaluate(0)[0];end=path.evaluate(horizon)[0]
        short=Path([start[:2],end[:2]],action['corner_trim_mm'])
        spans=e.catalog.spans(row['level'],short)
        own=[s for s in spans if s['resource']==held and s['start_progress_mm']<=1e-6 and s['end_progress_mm']>0]
        if not own:return
        horizon=min(horizon,own[0]['end_progress_mm'])
        if horizon<=1e-5:return
        if horizon!=path.ends[0]:
            start=path.evaluate(0)[0];end=path.evaluate(horizon)[0]
            short=Path([start[:2],end[:2]],action['corner_trim_mm'])
            spans=e.catalog.spans(row['level'],short)
        cap=source_perception_limit(e.source,e.nav.radius)['applied_velocity_mm_s']
        short_caps=[(at,value)for at,value in caps if at<short.length]
        program=compile_motion(short,e.source,cap,reverse=action['reverse'],zone_caps=short_caps)
        driver=RollingController(path,e.source,caps,own_start_s=e.now,radius_mm=e.nav.radius,
            static_return=e.static_return(row['level'],None,identity),motion_program=program,certified_horizon_mm=horizon,
            prior_localization=e.prior_localization(identity))
        driver.align_initial_heading(row['pose_mm_rad'][2])
        context={'source':e.source,'nav':e.nav,'geometry_checks':e.geometry_checker}
        receipt=_geometry(context,request,driver,driver.nominal_clock,0.,'rolling_straight_starter')
        self._install(identity,action,driver,caps,receipt,'rolling_straight_starter',prepared_spans=spans,
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
        return(row['action']is not None and preparation_digest(row['action'])==request['fence']['action_sha256']and
            row.get('preparation_generation',0)==request['fence']['generation']and
            row['level']==request['fence']['level']and not row['done']and
            e.own_grants(identity)==request['fence']['own_grants']and
            e.resources.own_grants(identity)==request['fence']['own_narrow_grant'])

    def accept(self,result):
        if type(result)is not dict:raise ValueError('Own route worker result required')
        request=self.jobs.get(result.get('request_id'))
        unsigned={k:v for k,v in result.items()if k!='result_sha256'}
        if (request is None or result.get('format')!=RESULT or result.get('source_binding')!=self.binding or
                result.get('kind')!=request['kind']or result.get('fence')!=request['fence']or
                result.get('result_sha256')!=preparation_digest(unsigned)):
            self.statistics['rejected']+=1;return {'accepted':False,'status':'invalid_receipt','request_id':result.get('request_id')}
        del self.jobs[request['request_id']]
        identity=request['vehicle_id'];row=self.engine.vehicles[identity]
        if not self._current(request):
            self.statistics['stale']+=1
            if request['kind']=='continuation':self.continuations.pop(identity,None)
            elif (row.get('action')==request['action']and
                  row.get('preparation_generation',0)==request['fence']['generation']):
                renewed=self._request(identity,request['action'],request['zone_caps'],'full_route')
                self.pending_by_vehicle[identity]=renewed['request_id']
            return {'accepted':False,'status':'stale_own_fence','request_id':request['request_id']}
        if request['kind']=='full_route':
            if (result.get('program_sha256')!=preparation_digest(result.get('program'))or
                    result.get('receipt',{}).get('geometry',{}).get('passed')is not True or
                    type(result.get('resource_spans'))is not list or type(result.get('door_markers'))is not list or
                    type(result.get('room_route_object_ids'))is not list):
                self.statistics['rejected']+=1;return {'accepted':False,'status':'invalid_proof','request_id':request['request_id']}
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
                self.statistics['rejected']+=1;return {'accepted':False,'status':'no_checked_connector','request_id':request['request_id']}
            anchor=result.get('anchor')
            if anchor!=request['anchor']or result.get('proof',{}).get('passed')is not True:
                self.statistics['rejected']+=1;return {'accepted':False,'status':'invalid_connector','request_id':request['request_id']}
            self.continuations[identity]=copy.deepcopy(result)
        return {'accepted':True,'status':'ready','request_id':request['request_id']}

    def before_tick(self):
        e=self.engine
        for identity,(original,result)in list(self.full.items()):
            row=e.vehicles[identity];driver=row['driver']
            if not isinstance(driver,RollingController)or not driver.awaiting_continuation:
                self.full.pop(identity,None);continue
            pending=self.continuations.get(identity)
            if pending is not None:
                if pending.get('request_id')in self.jobs:continue
                anchor=pending['anchor']
                if e.now<anchor['time_s']-1e-8:continue
                current_request={**original,'fence':pending['fence']}
                if self._current(current_request)and driver.commit_continuation(pending['clock'],result['program']['scalar_clock'],anchor,pending['proof'],
                        allow_static_rest_rebase=not bool(original['action'].get('lift_phase'))):
                    self.statistics['continuations']+=1;self.full.pop(identity,None);self.pending_by_vehicle.pop(identity,None)
                    self.continuations.pop(identity,None);continue
                self.statistics['stale']+=1;self.continuations.pop(identity,None)
            if identity in self.continuations:continue
            anchor=driver.continuation_anchor()
            if anchor is None:continue
            signature=tuple(anchor[k]for k in('progress_mm','velocity_mm_s','acceleration_mm_s2'))
            if self.attempted_anchors.get(identity)==signature:continue
            self.attempted_anchors[identity]=signature
            request=self._request(identity,original['action'],original['zone_caps'],'continuation',anchor=anchor,
                program=result['program'],program_sha256=result['program_sha256'],nominal_proof=result['nominal_proof'])
            request['observed']['time_s']=anchor['time_s']
            self.continuations[identity]={'request_id':request['request_id']}
