"""Independent station jobs and unchanged local-only opposing-traffic drivers."""
import bisect, copy, json, math
from pathlib import Path
import l01_fleet_handoffs as serial
import check_tr01_floor_motion as geometry
traffic=serial.traffic;local=traffic.local;floor=local.floor
ROOT=serial.ROOT;SOURCE=ROOT/'model/l01-independent-fleet.demo.json';OUT=ROOT/'exports/tr01-workcell';F=serial.F

def validate_config(config):
    if config.get('format')!='solidcraftbot.independent-fleet-demo/1' or config.get('mode')!='synthetic_display_only':raise ValueError('Independent synthetic fleet source required')
    required={'exclusive_station_and_arm','anonymous_station_clearance_observation','local_range_scans_only_for_drivers','fresh_person_clear_before_docking','no_timeout_release'}
    if set(config.get('guards',{}))!=required or any(v is not True for v in config['guards'].values()):raise ValueError('Independent fleet guards required')
    values=[config['workspace_interval_step_s'],config['minimum_added_clearance_mm'],*config['controller'].values()]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values):raise ValueError('Finite positive scheduling parameters required')
    if config['controller']['initial_vehicle_clock_scale']<1 or config['minimum_added_clearance_mm']<15:raise ValueError('Existing motion and clearance limits may not be weakened')
    concurrency=config.get('concurrency_contract',{})
    if concurrency.get('replaces_entry_condition')!='all_stationary_arms_parked' or concurrency.get('additional_entry_conditions')!=['exclusive_station_and_arm','disjoint_native_swept_workspaces','anonymous_stopping_envelopes_clear','current_coupled_interval_certificate']:raise ValueError('Explicit certified concurrency replacement required')
    seen=set()
    for event in config['workplace_observations']:
        key=(event['station'],event['time_s'])
        if (event['station'] not in ('DNA','CF01','QC') or event['status'] not in ('occupied','person_clear','unknown')
                or event['evidence']!='synthetic_demo_fixture' or isinstance(event['time_s'],bool) or not isinstance(event['time_s'],(int,float)) or not math.isfinite(event['time_s']) or event['time_s']<0 or key in seen):raise ValueError('Explicit unambiguous synthetic workplace observations required')
        seen.add(key)
    return config

def person_clear_observed(observations,station,now):
    events=[e for e in observations if e['station']==station and e['time_s']<=now]
    return bool(events) and max(events,key=lambda e:e['time_s'])['status']=='person_clear'

def read_inputs():
    config=validate_config(json.loads(SOURCE.read_text()))
    floor.assembly.validate_reference(config['serial_source'])
    base=serial.validated();report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text());program=json.loads((ROOT/report['files']['program']).read_text())
    contract=config['concurrency_contract'];original=program['definition']['guards']['entry_requires']
    if contract['replaces_entry_condition'] not in original or contract['retained_entry_conditions']!=[v for v in original if v!=contract['replaces_entry_condition']]:raise ValueError('Upstream entry conditions changed; reconcile the concurrency contract')
    workspace=json.loads((OUT/'independent-workspaces.json').read_text());floor.verify(workspace['source_files_sha256'])
    if not workspace['passed']:raise ValueError('Native workspace bounds required')
    return config,base,program,workspace

def as_point(t,p,v=None,a=None):return {'time_s':t,F[0]:list(p),F[1]:list(v or [0,0,0]),F[2]:list(a or [0,0,0])}
def append_point(points,p):
    # Equivalent resting frames from independent solvers can differ by a few
    # floating-point ULPs. Do not create a microscopic move between two rests.
    if points and all(v==0 for point in (points[-1],p) for field in F[1:3] for v in point[field]):
        if all(abs(a-b)<=64*math.ulp(max(1.,abs(a),abs(b))) for a,b in zip(points[-1][F[0]],p[F[0]])):p[F[0]]=list(points[-1][F[0]])
    if points and abs(points[-1]['time_s']-p['time_s'])<1e-8:
        if max(abs(a-b) for k in F[:3] for a,b in zip(points[-1][k],p[k]))>1e-5:raise ValueError('Discontinuous vehicle phase boundary')
        points[-1]=p;return
    if points and p['time_s']<points[-1]['time_s']:raise ValueError('Vehicle clock rollback')
    if len(points)>1 and all(max(abs(v) for v in q[k])<1e-10 for q in (points[-2],points[-1],p) for k in F[1:3]) and points[-2][F[0]]==points[-1][F[0]]==p[F[0]]:points[-1]=p
    else:points.append(p)

def car_box(bounds,p,inflate=0.):
    b=geometry_box(bounds,serial.placement([*p[:2],0],p[2]));return {'min':[v-inflate for v in b['min']],'max':[v+inflate for v in b['max']]}
def geometry_box(b,m):
    pts=[floor.robot.transform(m,[x,y,z]) for x in (b['min'][0],b['max'][0]) for y in (b['min'][1],b['max'][1]) for z in (b['min'][2],b['max'][2])]
    return {'min':[min(p[k] for p in pts) for k in range(3)],'max':[max(p[k] for p in pts) for k in range(3)]}

def path_speed_gain(path):
    # A Bezier derivative stays in the convex hull of its derivative controls.
    # Ring progress is not assumed to equal exact Cartesian arc length.
    return max(math.hypot(*p) for piece in path.pieces for p in piece['derivatives'][0])

def compile_program(observations=None,progress=False,clock_scale=None):
    config,base,program,workspace=read_inputs();settings,profile,motion=traffic.load();path=traffic.RingPath(motion,settings['path_projection_step_mm']);gain=path_speed_gain(path);missions=base['missions'];n=len(missions);radius=workspace['radius_mm'];margin=config['minimum_added_clearance_mm'];dt=config['controller']['integration_step_s'];factor=clock_scale or config['controller']['initial_vehicle_clock_scale']
    if any(not math.isclose(period/dt,round(period/dt),abs_tol=1e-8) or period<dt for period in (profile['sensor']['period_s'],config['controller']['output_step_s'])):raise ValueError('Controller and output clocks must divide the source sensor period exactly')
    cfg={**profile['sensor'],**profile['controller'],'desired_speed_mm_s':profile['desired_speed_mm_s']/factor}
    # Avoid depending on JSON member order for dimensional time scaling.
    limits={k:motion['limits']['linear'][k]*profile['controller']['motion_limit_utilization']/factor**order for order,k in enumerate(('velocity','acceleration','jerk'),1)}
    controllers=[traffic.MissionController(m,path,motion,cfg,limits,radius,settings['encounter_rule']) for m in missions];pending=[[] for _ in missions]
    poses=[c.pose() for c in controllers];initial=copy.deepcopy(base['phases'][0]['state']);tracks=[{'id':m['id'],'phases':[],'points':[as_point(0,poses[i])],'mode':'waiting_load','job':None,'waiting_since':0.,'load_complete':None,'arrival_s':None} for i,m in enumerate(missions)]
    templates={(p['station'],p['stage']):[] for p in base['phases'] if p.get('stage') in ('load','unload')}
    for p in base['phases']:
        if p.get('stage') in ('load','unload'):templates[p['station'],p['stage']].append(p)
    approaches={s:floor.motion.Curve(floor.canonical(a['points'])) for s,a in program['approaches'].items()};active={};jobs=[];events=[];frames=[];first_departure=None;vacated=set();admission=[]
    p=floor.layout.parameters(floor.layout.load(validate_builds=False));static=[[0,0,p['bench_depth'],p['left_depth']],[p['room_width']-p['bench_depth'],0,p['room_width'],p['right_depth']],[p['room_width']/2-p['island_half_width'],p['island_start_y'],p['room_width']/2+p['island_half_width'],p['island_start_y']+p['island_length']]]
    person_source=copy.deepcopy(profile);person_source['person'].update(y_mm=settings['person']['y_mm']);lane=path.lanes[settings['person']['lane']];person_radius=profile['person']['radius_mm'];person_box={'min':[lane-person_radius,settings['person']['y_mm']-person_radius,0],'max':[lane+profile['person']['lateral_offset_mm']+person_radius,settings['person']['y_mm']+person_radius,1800]}
    minimum={'car_car':math.inf,'car_person':math.inf,'bench':math.inf};max_simultaneous_arms=0;drive_with_arm=False
    def pose_at(i,t):
        tr=tracks[i]
        if tr['job'] is not None:
            job=tr['job'];parts=tr['phases'][job['first_phase']:];phase=next((p for p in reversed(parts) if p['start_s']<=t),parts[0]);state=phase['state']['cars'][i]
            if phase['kind']=='dock':
                curve=approaches[phase['station']];u=max(0,min(phase['duration_s'],t-phase['start_s']));q=curve.evaluate(curve.times[-1]-u if phase['reverse'] else u)[F[0]];return [q[0],q[1],q[2]+phase['yaw_offset']]
            return state
        return controllers[i].pose() if tr['mode']=='traffic' else tr['points'][-1][F[0]]
    def stopping_observation(i):
        tr=tracks[i];c=controllers[i]
        if tr['mode']!='traffic':return car_box(workspace['car_bounds'],poses[i])
        reaction=cfg['period_s']+cfg['latency_s'];A=limits['acceleration'];J=limits['jerk'];v=c.driver.v+A*reaction;brake=local.braking(v,A,A,J);d=c.driver.v*reaction+.5*A*reaction**2+(brake.evaluate(brake.times[-1])[F[0]][0] if brake else 0)
        d*=gain
        return {'min':[poses[i][0]-radius-d,poses[i][1]-radius-d,workspace['car_bounds']['min'][2]],'max':[poses[i][0]+radius+d,poses[i][1]+radius+d,workspace['car_bounds']['max'][2]]}
    def admit(i,station,direction,t):
        # Station occupancy observations are anonymous physical envelopes, not
        # peer state or intentions sent to any transporter controller.
        key=station+':'+direction;hull=workspace['jobs'][key];observed=[stopping_observation(j) for j in range(n) if j!=i]+[person_box]
        if not person_clear_observed(observations if observations is not None else config['workplace_observations'],station,t):return False
        if direction=='unload' and station not in vacated:return False
        if any(hull['area']==v['area'] or hull['actor']==v['actor'] or geometry.box_distance(hull['box'],v['box'])<margin for v in active.values()):return False
        if any(geometry.box_distance(hull['box'],ob)<margin for ob in observed):return False
        job={'vehicle':missions[i]['id'],'station':station,'direction':direction,'start_s':t,'actor':hull['actor'],'area':hull['area'],'box':hull['box'],'first_phase':len(tracks[i]['phases'])};parts=templates[station,direction];origin=parts[0]['start_s'];current_yaw=poses[i][2];template_yaw=parts[0]['state']['cars'][i][2];yaw_delta=2*math.pi*round((current_yaw-template_yaw)/(2*math.pi))
        if math.dist(poses[i][:2],parts[0]['state']['cars'][i][:2])>1e-5:raise ValueError('Station job requested away from its own waiting position')
        tr=tracks[i]
        if t>tr['waiting_since']+1e-8:
            tr['phases'].append({'kind':'resource_wait','start_s':tr['waiting_since'],'duration_s':t-tr['waiting_since'],'vehicle':tr['id'],'station':station,'stage':direction,'state':copy.deepcopy(parts[0]['state'])});job['first_phase']+=1
        for part in parts:
            phase=copy.deepcopy(part);phase['start_s']=t+part['start_s']-origin;phase['state']['cars'][i][2]+=yaw_delta
            if phase['kind']=='dock':phase['yaw_offset']+=yaw_delta
            tr['phases'].append(phase)
            append_point(tr['points'],as_point(phase['start_s'],phase['state']['cars'][i]))
            if phase['kind']=='dock':
                curve=approaches[station];points=curve.points if not phase['reverse'] else list(reversed(curve.points));D=curve.times[-1]
                for point in points:
                    u=D-point['time_s'] if phase['reverse'] else point['time_s'];q=list(point[F[0]]);q[2]+=phase['yaw_offset'];sgn=-1 if phase['reverse'] else 1
                    append_point(tr['points'],as_point(phase['start_s']+u,q,[sgn*v for v in point[F[1]]],point[F[2]]))
            else:append_point(tr['points'],as_point(phase['start_s']+phase['duration_s'],phase['state']['cars'][i]))
            if phase['kind']=='event':events.append({'time_s':phase['start_s']+phase['duration_s'],'event':phase['event'],'vehicle':tr['id'],'station':station,'work_area':hull['area'],'evidence':'synthetic_demo_fixture'})
        job['end_s']=tr['phases'][-1]['start_s']+tr['phases'][-1]['duration_s'];jobs.append(job);active[i]=job;tr['job']=job;tr['mode']='job';admission.append({'time_s':t,'vehicle':tr['id'],'station':station,'minimum_observed_stopping_envelope_clearance_mm':min(geometry.box_distance(hull['box'],o) for o in observed),'peer_state_transmitted':False});return True
    scan_steps=round(profile['sensor']['period_s']/dt);output_steps=round(config['controller']['output_step_s']/dt)
    for tick in range(round(config['controller']['maximum_duration_s']/dt)+1):
        now=tick*dt
        for i,tr in enumerate(tracks):
            if tr['job'] and now<tr['job']['end_s'] and not person_clear_observed(observations if observations is not None else config['workplace_observations'],tr['job']['station'],now):raise ValueError('New occupation invalidates an active station job; a newly verified stop/resume program is required')
            if tr['job'] and now>=tr['job']['end_s']-1e-9:
                job=tr['job'];active.pop(i);tr['job']=None;tr['waiting_since']=now
                if job['direction']=='load':
                    tr['mode']='traffic';tr['load_complete']=now;vacated.add(job['station']);controllers[i].history=[];controllers[i].record(now,controllers[i].progress,0,0);pending[i]=[]
                    if first_departure is None:first_departure=now
                else:tr['mode']='done'
            if tr['mode']=='traffic' and controllers[i].driver.mode=='arrived':
                tr['mode']='waiting_unload';tr['arrival_s']=now;tr['waiting_since']=now;start=tr['load_complete'];tr['phases'].append({'kind':'traffic','start_s':start,'duration_s':now-start,'vehicle':tr['id'],'station':missions[i]['to'],'stage':'traffic'})
        poses=[pose_at(i,now) for i in range(n)]
        for i,tr in enumerate(tracks):
            if tr['mode']=='waiting_load':admit(i,missions[i]['from'],'load',now)
            elif tr['mode']=='waiting_unload':admit(i,missions[i]['to'],'unload',now)
        person=local.person_position(person_source,lane,max(0,now-first_departure) if first_departure is not None else 0)
        proxy=[*[j['box']['min'][:2]+j['box']['max'][:2] for j in active.values()]];world=traffic.RangeWorld(profile['sensor'],static+proxy)
        if tick%scan_steps==0:
            for i,tr in enumerate(tracks):
                if tr['mode']!='traffic':continue
                raw=world.scan(poses[i],[(*p[:2],radius) for j,p in enumerate(poses) if i!=j]+[person],now);pending[i].append((now+profile['sensor']['latency_s'],controllers[i].observe(raw,controllers[i].progress)))
        states=[]
        for i,tr in enumerate(tracks):
            state={'mode':tr['mode'],'scan_age_s':None,'observed_gap_mm':None,'required_gap_mm':None}
            if tr['mode']=='traffic':
                scan=None
                while pending[i] and pending[i][0][0]<=now+1e-9:scan=pending[i].pop(0)[1]
                state=controllers[i].decide(now,scan)
            states.append(state)
        for i,pose in enumerate(poses):
            minimum['car_person']=min(minimum['car_person'],math.dist(pose[:2],person[:2])-radius-person_radius)
            for other in poses[i+1:]:minimum['car_car']=min(minimum['car_car'],math.dist(pose[:2],other[:2])-2*radius)
            if tracks[i]['mode']=='traffic':
                for area in program['definition']['work_areas'].values():
                    x0,x1,y0,y1=area['bounds_xy_mm'];minimum['bench']=min(minimum['bench'],math.hypot(max(x0-pose[0],pose[0]-x1,0),max(y0-pose[1],pose[1]-y1,0))-radius)
        arms=sum(1 for i,j in active.items() if any(p['kind']=='arm' and p['start_s']<=now<p['start_s']+p['duration_s'] for p in tracks[i]['phases'][j['first_phase']:]))
        max_simultaneous_arms=max(max_simultaneous_arms,arms);drive_with_arm|=bool(arms and any(t['mode']=='traffic' and c.driver.v>1e-5 for t,c in zip(tracks,controllers)))
        finished=all(t['mode']=='done' for t in tracks)
        if tick%output_steps==0 or finished:frames.append({'time_s':now,'vehicles':[{'id':m['id'],'station':m['to'],'pose_mm_rad':pose,'velocity_mm_s':controllers[i].driver.v if tracks[i]['mode']=='traffic' else 0.,**state} for i,(m,pose,state) in enumerate(zip(missions,poses,states))],'person_mm':person[:2]})
        if progress and tick%2000==0:print('independent',round(now,2),[(t['id'],t['mode'],round(controllers[i].driver.v,2)) for i,t in enumerate(tracks)],flush=True)
        if finished:break
        for i,tr in enumerate(tracks):
            if tr['mode']=='traffic':
                c=controllers[i];previous=len(c.history);c.advance(now,now+dt)
                for point in c.history[previous:]:append_point(tr['points'],point)
    if not finished:raise ValueError('Independent station/traffic scenario did not complete: '+str([(t['id'],t['mode']) for t in tracks]))
    trajectories=[];required_scale=1.
    for tr,c in zip(tracks,controllers):
        append_point(tr['points'],as_point(now,tr['points'][-1][F[0]]));curve=floor.motion.Curve(tr['points']);dynamics=floor.dynamics(curve,radius)
        required_scale=max(required_scale,*[(dynamics[k][name]/motion['limits'][k][name])**(1/order) for k in ('linear','angular','carried_points') for order,name in enumerate(('velocity','acceleration','jerk'),1)])
        trajectories.append({'id':tr['id'],'points':[[p['time_s'],p[F[0]],p[F[1]],p[F[2]]] for p in tr['points']],'dynamics':dynamics,'events':c.events,'arrived':True})
        tr.pop('points');tr.pop('job');tr['complete_s']=max(p['start_s']+p['duration_s'] for p in tr['phases'])
    if required_scale>1.00001:raise ValueError('Vehicle dynamics need a slower simulation clock: '+str(required_scale))
    allowance=dt*(2*profile['desired_speed_mm_s']+profile['person']['lateral_offset_mm']/profile['person']['arrives_at_lane_s']);clearance={'car_car_clearance_lower_mm':minimum['car_car']-allowance,'car_person_clearance_lower_mm':minimum['car_person']-allowance,'bench_clearance_lower_mm':minimum['bench']-dt*profile['desired_speed_mm_s']}
    if min(clearance[k] for k in ('car_car_clearance_lower_mm','car_person_clearance_lower_mm'))<profile['controller']['clearance_mm'] or clearance['bench_clearance_lower_mm']<=0:raise ValueError('Independent full-scene clearances failed: '+str(clearance))
    source_pins={**base['source_files_sha256'],**workspace['source_files_sha256'],str(SOURCE.relative_to(ROOT)):local.digest(SOURCE),'scripts/l01_independent_fleet.py':local.digest(__file__),'exports/tr01-workcell/independent-workspaces.json':local.digest(OUT/'independent-workspaces.json')}
    result={'format':'solidcraftbot.fleet-handoffs-program/2','source_files_sha256':source_pins,'missions':missions,'cargo_ids':base['cargo_ids'],'initial_state':initial,'tracks':tracks,'phases':sorted([p for t in tracks for p in t['phases']],key=lambda p:p['start_s']),'jobs':jobs,'events':sorted(events,key=lambda e:e['time_s']),'duration_s':now,'traffic_start_s':first_departure,'traffic_end_s':max(t['arrival_s'] for t in tracks),'station_admissions':admission,'workspace_jobs':workspace['jobs'],'statistics':{'maximum_parallel_arms':max_simultaneous_arms,'driving_during_arm_handoff':drive_with_arm,'serial_duration_s':base['duration_s']},'limitations':config['limitations'],'entry_contract':config['concurrency_contract'],'path_speed_gain_upper':gain,'vehicle_clock_scale':factor,'workplace_observations':observations if observations is not None else config['workplace_observations']}
    result['traffic']={'format':'solidcraftbot.independent-traffic-result/1','duration_s':now,'frames':frames,'trajectories':trajectories,'radius_mm':radius,'clearance':clearance,'settings':{**profile,**settings,'person':{**profile['person'],**settings['person']},'limitations':config['limitations']},'all_arrived':True,'shared_positions':False,'native_pose_coverage':{'passed':False},'source_files_sha256':source_pins,'person_epoch_s':first_departure,'person_full_envelope':person_box}
    result['program_sha256']=serial.canonical_sha(result);return result

def validated():
    path=OUT/'independent-fleet.json';result=json.loads(path.read_text());floor.verify(result['source_files_sha256'])
    checksum=result.pop('program_sha256')
    if serial.canonical_sha(result)!=checksum:raise ValueError('Independent fleet program changed')
    result['program_sha256']=checksum;proof_path=OUT/'independent-fleet-clearance.json';proof=json.loads(proof_path.read_text())
    if not proof['passed'] or proof['program_sha256']!=checksum or proof['checker_sha256']!=local.digest(ROOT/'scripts/check_l01_independent_fleet_freecad.py'):raise ValueError('Current complete independent-fleet proof required')
    floor.verify(proof['native_inputs_sha256']);result['source_files_sha256'].update({'exports/tr01-workcell/independent-fleet.json':local.digest(path),'exports/tr01-workcell/independent-fleet-clearance.json':local.digest(proof_path),'scripts/check_l01_independent_fleet_freecad.py':local.digest(ROOT/'scripts/check_l01_independent_fleet_freecad.py')})
    result['clearance_summary']=proof['summary'];result['traffic']['native_pose_coverage']={'passed':True,'method':proof['method']};return result

def main():
    result=compile_program(progress=True);(OUT/'independent-fleet.json').write_text(json.dumps(result,separators=(',',':'))+'\n');print(json.dumps({'duration_s':result['duration_s'],'statistics':result['statistics'],'program_sha256':result['program_sha256']}))
if __name__=='__main__':main()
