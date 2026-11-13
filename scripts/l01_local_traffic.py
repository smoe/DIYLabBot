"""Local-only range-scan traffic fixture, separate from workflow execution.

World truth is confined to SensorWorld and the independent clearance auditor.
LocalController receives own state and delayed anonymous scans, never peers.
"""
import bisect,copy,hashlib,json,math,sys
from pathlib import Path
import tr01_floor_motion as floor
ROOT=floor.ROOT;SOURCE=ROOT/'model/l01-local-traffic.demo.json';F=floor.F

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load():
    s=json.loads(SOURCE.read_text());motion=floor.load();limits=motion['limits']['linear']
    if s['format']!='solidcraftbot.local-traffic-demo/1' or s['mode']!='synthetic_only':raise ValueError('Synthetic traffic contract required')
    if not 0<s['desired_speed_mm_s']<=limits['velocity']:raise ValueError('Traffic velocity exceeds source limit')
    if len(s['vehicles'])!=3 or len({v['id'] for v in s['vehicles']})!=3:raise ValueError('Three distinct instances required')
    sensor=s['sensor']
    if sensor['stale_after_s']<=sensor['period_s']+sensor['latency_s']:raise ValueError('Scan age must permit the declared delayed cycle')
    return s,motion

def point(t,p,v,a):return {'time_s':t,F[0]:[p],F[1]:[v],F[2]:[a]}

def braking(v,a,A,J):
    """Exact C2 jerk-limited stop from a viable positive-velocity state."""
    if v<1e-8 and abs(a)<1e-8:return None
    b=math.sqrt(max(0,J*v+a*a/2));peak=min(A,b);t1=max(0,(a+peak)/J)
    v1=v+a*t1-J*t1*t1/2;t2=max(0,(v1-peak*peak/(2*J))/peak) if peak else 0;t3=peak/J
    knots=[point(0,0,v,a)];t=p=0
    for duration,j in [(t1,-J),(t2,0),(t3,J)]:
        if duration<1e-10:continue
        p+=v*duration+a*duration**2/2+j*duration**3/6;v+=a*duration+j*duration**2/2;a+=j*duration;t+=duration
        knots.append(point(t,p,v,a))
    if abs(v)>1e-6 or abs(a)>1e-6:raise ValueError('Nonviable braking state')
    knots[-1][F[1]]=[0.];knots[-1][F[2]]=[0.]
    return floor.motion.Curve(knots)

def ray_disc(ox,oy,dx,dy,cx,cy,r):
    x,y=ox-cx,oy-cy;b=x*dx+y*dy;c=x*x+y*y-r*r;d=b*b-c
    if d<0:return math.inf
    t=-b-math.sqrt(d)
    return t if t>=0 else math.inf

def ray_box(ox,oy,dx,dy,box):
    lo,hi=0.,math.inf
    for origin,direction,minimum,maximum in zip((ox,oy),(dx,dy),box[:2],box[2:]):
        if abs(direction)<1e-12:
            if not minimum<=origin<=maximum:return math.inf
        else:
            a,b=sorted(((minimum-origin)/direction,(maximum-origin)/direction));lo=max(lo,a);hi=min(hi,b)
    return lo if hi>=lo else math.inf

class SensorWorld:
    def __init__(self,settings,lane,static_boxes):self.settings=settings;self.lane=lane;self.static=static_boxes
    def scan(self,own,discs,now):
        """First return only. Output has no object IDs or world positions."""
        settings=self.settings;returns=[]
        for degrees in range(0,360,settings['angular_step_deg']):
            angle=math.radians(degrees);dx,dy=math.sin(angle),math.cos(angle)
            distance=min([settings['range_mm'],*[ray_disc(self.lane,own,dx,dy,*disc) for disc in discs],*[ray_box(self.lane,own,dx,dy,b) for b in self.static]])
            if distance<settings['range_mm']:returns.append([dx*distance,dy*distance])
        return {'captured_s':now,'returns_local_mm':returns}

class LocalController:
    def __init__(self,start,goal,settings,limits,radius):
        self.y=start;self.goal=goal;self.v=self.a=0.;self.settings=settings;self.limits=limits;self.radius=radius
        self.plan=None;self.plan_start=0;self.plan_origin=start;self.mode='waiting';self.clear_since=None;self.stops=0;self.reason='initial';self.last_scan=None;self.history=[point(0,start,0,0)];self.minimum_scan_gap=math.inf
    def set_plan(self,curve,now,mode):
        self.plan=curve;self.plan_start=now;self.plan_origin=self.y;self.mode=mode
    def evaluate(self,now):
        if self.plan is None:return self.y,self.v,self.a
        jet=self.plan.evaluate(min(self.plan.times[-1],max(0,now-self.plan_start)))
        return self.plan_origin+jet[F[0]][0],jet[F[1]][0],jet[F[2]][0]
    def advance(self,start,end):
        if self.plan:
            for knot in self.plan.points:
                t=self.plan_start+knot['time_s']
                if start+1e-9<t<end-1e-9:self.history.append(point(t,self.plan_origin+knot[F[0]][0],knot[F[1]][0],knot[F[2]][0]))
        self.y,self.v,self.a=self.evaluate(end);self.history.append(point(end,self.y,self.v,self.a))
        if self.plan and end>=self.plan_start+self.plan.times[-1]-1e-9:
            self.plan=None;self.v=self.a=0.;self.mode='arrived' if self.goal-self.y<.01 else 'waiting'
    def decide(self,now,scan):
        if scan:self.last_scan=scan
        scan=self.last_scan;s=self.settings;A=self.limits['acceleration'];J=self.limits['jerk'];brake=braking(self.v,self.a,A,J)
        stop_time=brake.times[-1] if brake else 0.;stop_distance=brake.evaluate(stop_time)[F[0]][0] if brake else 0.
        age=now-scan['captured_s'] if scan else math.inf;stale=age>s['stale_after_s']
        # Inflate the swept disc for beam spacing, range error and scan age.
        inflation=s['range_error_mm']+s['range_mm']*math.sin(math.radians(s['angular_step_deg']))
        width=self.radius+self.settings['clearance_mm']+inflation
        gap=min((p[1]-self.radius-inflation for p in scan['returns_local_mm'] if abs(p[0])<=width and p[1]>0),default=math.inf) if scan else 0
        self.minimum_scan_gap=min(self.minimum_scan_gap,gap)
        reaction=s['period_s']+s['latency_s'];closing=s['maximum_obstacle_closing_speed_mm_s']
        required=self.settings['clearance_mm']+stop_distance+(self.v+closing)*reaction+closing*stop_time
        if self.mode=='waiting':
            launch=braking(self.settings['desired_speed_mm_s'],0,A,J);launch_time=launch.times[-1];launch_distance=launch.evaluate(launch_time)[F[0]][0]
            required=max(required,self.settings['clearance_mm']+launch_distance+(self.settings['desired_speed_mm_s']+closing)*reaction+closing*launch_time)
        obstructed=stale or gap<=required
        if obstructed:
            self.clear_since=None;self.reason='scan_missing_or_stale' if stale else 'local_obstacle'
            if brake and self.mode!='braking':self.set_plan(brake,now,'braking');self.stops+=1
        else:
            if self.clear_since is None:self.clear_since=now
            if self.mode=='waiting' and now-self.clear_since>=s['clear_observation_s'] and self.goal-self.y>.01:
                self.reason='clear_scan';curve=floor.motion.Curve(floor.motion.rest_to_rest(self.goal-self.y,self.settings['desired_speed_mm_s'],A,J));self.set_plan(curve,now,'driving')
        return {'mode':self.mode,'reason':self.reason,'scan_age_s':age if math.isfinite(age) else None,'observed_gap_mm':gap if math.isfinite(gap) else None,'required_gap_mm':required}

def person_position(s,lane,t):
    p=s['person'];arrival=p['arrives_at_lane_s'];leave=p['leaves_lane_s'];clear=p['fully_clear_s'];offset=p['lateral_offset_mm']
    x=lane+offset*(1-min(1,t/arrival)) if t<leave else lane+offset*min(1,(t-leave)/(clear-leave))
    return [x,p['y_mm'],p['radius_mm']]

def checked_straight_coverage(report,program,lane,start,end):
    """Reuse an existing native proof only for identical rigid-body poses."""
    floor.verify({name:sha for name,sha in report['source_files_sha256'].items() if name not in {'scripts/tr01_workcell_player.html','scripts/render_tr01_workcell.py'}})
    for key in ('program','floor_validation'):
        if digest(ROOT/report['files'][key])!=report['artifact_sha256'][key]:raise ValueError('Changed native proof artifact')
    proof=json.loads((ROOT/report['files']['floor_validation']).read_text())
    if not proof['passed']:raise ValueError('Native floor proof must pass')
    passed={r['id']:r for r in proof['routes'] if r['passed']};intervals=[]
    for route in program['floor_routes']:
        if route['id'] not in passed:continue
        for a,b in zip(route['points'],route['points'][1:]):
            pa,pb=a['pose_mm_rad'],b['pose_mm_rad']
            yaw=lambda y:abs((y-math.pi/2+math.pi)%(2*math.pi)-math.pi)<1e-8
            if abs(pa[0]-lane)>1e-8 or abs(pb[0]-lane)>1e-8 or abs(pa[2]-pb[2])>1e-8 or not yaw(pa[2]) or not yaw(pb[2]):continue
            if any(abs(p[field][axis])>1e-8 for p in (a,b) for field in ('velocity_mm_rad_s','acceleration_mm_rad_s2') for axis in (0,2)):continue
            intervals.append((min(pa[1],pb[1]),max(pa[1],pb[1]),route['id']))
    cursor=start;used=set()
    for a,b,name in sorted(intervals):
        if a<=cursor+1e-6 and b>cursor:cursor=b;used.add(name)
    if cursor<end-1e-6:raise ValueError('Traffic poses are not covered by existing checked straight segments')
    return {'passed':True,'y_interval_mm':[start,end],'lane_x_mm':lane,'yaw_rad':math.pi/2,'source_routes':sorted(used),
        'native_proof':report['files']['floor_validation'],'native_proof_sha256':report['artifact_sha256']['floor_validation'],
        'method':'identical constant-X constant-heading source PVA segments cover the full new Y interval; full vehicle, load and cover unchanged; arms parked'}

def simulate(dropout=None,settings=None):
    source,motion=load();s=copy.deepcopy(settings or source);lane=motion['traffic_policy']['resolved_lane_centres_mm'][s['lane']]
    report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text());program=json.loads((ROOT/report['files']['program']).read_text());radius=program['floor_routes'][0]['dynamics']['radius_mm']
    native_coverage=checked_straight_coverage(report,program,lane,min(v['start_y_mm'] for v in s['vehicles']),max(v['goal_y_mm'] for v in s['vehicles']))
    params=floor.layout.parameters(floor.layout.load(validate_builds=False));static=[[0,0,params['bench_depth'],params['left_depth']],[params['room_width']/2-params['island_half_width'],params['island_start_y'],params['room_width']/2+params['island_half_width'],params['island_start_y']+params['island_length']]]
    cfg={**s['sensor'],**s['controller'],'desired_speed_mm_s':s['desired_speed_mm_s']}
    effective={key:value*s['controller']['motion_limit_utilization'] for key,value in motion['limits']['linear'].items()}
    controllers=[LocalController(v['start_y_mm'],v['goal_y_mm'],cfg,effective,radius) for v in s['vehicles']]
    world=SensorWorld(s['sensor'],lane,static);pending=[[] for _ in controllers];step=s['controller']['integration_step_s'];frames=[];min_car=min_person=math.inf;max_steps=round(s['maximum_duration_s']/step)
    states=[{} for _ in controllers];scan_every=round(s['sensor']['period_s']/step)
    for tick in range(max_steps+1):
        now=tick*step;person=person_position(s,lane,now)
        # All sensors sample the same pre-step world; no sequential agent privilege.
        for i,c in enumerate(controllers):
            if tick%scan_every==0 and not(dropout and dropout[0]<=now<=dropout[1]):
                discs=[(lane,other.y,radius) for j,other in enumerate(controllers) if i!=j]+[person]
                pending[i].append((now+s['sensor']['latency_s'],world.scan(c.y,discs,now)))
        for i,c in enumerate(controllers):
            ready=None
            while pending[i] and pending[i][0][0]<=now+1e-9:ready=pending[i].pop(0)[1]
            states[i]=c.decide(now,ready)
        for i,c in enumerate(controllers):
            min_person=min(min_person,math.hypot(lane-person[0],c.y-person[1])-radius-person[2])
            for other in controllers[i+1:]:min_car=min(min_car,abs(c.y-other.y)-2*radius)
        finished=now>s['person']['fully_clear_s']+1 and all(c.mode=='arrived' for c in controllers)
        if tick%2==0 or finished:frames.append({'time_s':round(now,6),'vehicles':[{'id':v['id'],'y_mm':round(c.y,6),'velocity_mm_s':round(c.v,6),**states[i]} for i,(v,c) in enumerate(zip(s['vehicles'],controllers))],'person_mm':person[:2]})
        if finished:break
        for c in controllers:c.advance(now,now+step)
    # A motion-Lipschitz allowance turns sampled separation into a conservative interval bound.
    interval_allowance=step*(2*s['desired_speed_mm_s']+s['person']['lateral_offset_mm']/s['person']['arrives_at_lane_s'])
    bounds={'car_car_clearance_lower_mm':min_car-interval_allowance,'car_person_clearance_lower_mm':min_person-interval_allowance,'interval_motion_allowance_mm':interval_allowance}
    trajectories=[]
    for v,c in zip(s['vehicles'],controllers):
        curve=floor.motion.Curve(c.history);public=[]
        for p in c.history:public.append([p['time_s'],p[F[0]][0],p[F[1]][0],p[F[2]][0]])
        bounds_actual=floor.motion.bounds(curve)
        dynamic={name:bounds_actual[field]['max_abs'][0] for name,field in zip(('velocity','acceleration','jerk'),F[1:])}
        if any(dynamic[name]>motion['limits']['linear'][name] for name in dynamic):raise ValueError('Exported traffic curve exceeds source dynamics')
        trajectories.append({'dynamics':dynamic,'id':v['id'],'points':public,'stops_for_observation':c.stops,'arrived':c.mode=='arrived'})
    pins={str(SOURCE.relative_to(ROOT)):digest(SOURCE),str(Path(__file__).relative_to(ROOT)):digest(__file__),s['motion_source']:digest(ROOT/s['motion_source']),report['files']['program']:digest(ROOT/report['files']['program'])}
    return {'format':'solidcraftbot.local-traffic-result/1','lane_x_mm':lane,'radius_mm':radius,'duration_s':frames[-1]['time_s'],'frames':frames,'trajectories':trajectories,'clearance':bounds,'native_pose_coverage':native_coverage,'settings':s,'source_files_sha256':pins,'all_arrived':all(c.mode=='arrived' for c in controllers),'shared_positions':False}

def main():
    result=simulate();out=ROOT/'exports/tr01-workcell';out.mkdir(parents=True,exist_ok=True);(out/'local-traffic.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({k:result[k] for k in ['duration_s','clearance','all_arrived','shared_positions']}))
    if not result['all_arrived'] or min(result['clearance'][k] for k in ['car_car_clearance_lower_mm','car_person_clearance_lower_mm'])<0:raise SystemExit('Traffic fixture failed')
if __name__=='__main__':main()
