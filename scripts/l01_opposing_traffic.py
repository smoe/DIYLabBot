"""Three station missions with local-only head-on resolution on aisle centres."""
import bisect,copy,json,math
from pathlib import Path
import l01_local_traffic as local
from cf01_unload_path import CornerPath
floor=local.floor;ROOT=local.ROOT;F=local.F;SOURCE=ROOT/'model/l01-opposing-traffic.demo.json'

def load():
    s=json.loads(SOURCE.read_text());floor.assembly.validate_reference(s['base_profile']);base,motion=local.load()
    if s['format']!='solidcraftbot.opposing-traffic-demo/1':raise ValueError('Opposing traffic contract required')
    if s['encounter_rule']['preferred_circulation']!='left_north_rear_east_right_south_front_west' or s['encounter_rule']['yield_direction']!=-1:raise ValueError('Unsupported local encounter rule')
    if any(m['from'] not in motion['stations'] or m['to'] not in motion['stations'] or m['from']==m['to'] or m['initial_direction'] not in (-1,1) for m in s['missions']):raise ValueError('Distinct known station endpoints and signed travel directions required')
    if len({m['id'] for m in s['missions']})!=3:raise ValueError('Distinct vehicle IDs required')
    if len(s['missions'])!=3 or {v['initial_direction'] for v in s['missions']}!={-1,1}:raise ValueError('Three missions including opposing travel required')
    if len({v['to'] for v in s['missions']})!=3:raise ValueError('Distinct station targets required')
    return s,base,motion

class RingPath:
    """One portable C2/C3-ended CornerPath recipe; no bench-side lanes."""
    def __init__(self,motion,step=40):
        c=motion['traffic_policy']['resolved_lane_centres_mm'];trim=motion['curve']['corner_trim_mm'];self.lanes=c
        corners=[[c['left'],c['rear'],0],[c['right'],c['rear'],0],[c['right'],c['front'],0],[c['left'],c['front'],0]]
        blends=[CornerPath(corners[(i-1)%4],p,corners[(i+1)%4],0,0,trim).controls for i,p in enumerate(corners)]
        self.pieces=[];self.ends=[];self.length=0;self.step=step
        # Begin immediately after the front-left corner and travel north.
        cursor=blends[-1][-1]
        for i,controls in enumerate(blends):
            self.add([cursor,controls[0]],math.dist(cursor,controls[0]),math.pi/2-i*math.pi/2)
            self.add(controls,7*trim/3,math.pi/4-i*math.pi/2);cursor=controls[-1]
        self.samples=[];self.cells={}
        for index,piece in enumerate(self.pieces):
            start=0 if index==0 else self.ends[index-1];count=1 if len(piece['controls'])==2 else math.ceil(piece['weight']/step)
            for i in range(count):
                a=start+piece['weight']*i/count;b=start+piece['weight']*(i+1)/count;pa=self.evaluate(a)[0];pb=self.evaluate(b)[0];n=len(self.samples);self.samples.append((a,b,pa,pb))
                for x in range(math.floor(min(pa[0],pb[0])/500)-1,math.floor(max(pa[0],pb[0])/500)+2):
                    for y in range(math.floor(min(pa[1],pb[1])/500)-1,math.floor(max(pa[1],pb[1])/500)+2):self.cells.setdefault((x,y),[]).append(n)
    def add(self,controls,weight,yaw):
        derivatives=[];d=controls
        for order in range(1,4):
            degree=len(d)-1;d=[[degree*(b-a) for a,b in zip(x,y)] for x,y in zip(d,d[1:])] if degree else [[0,0,0]]
            derivatives.append([[v/weight**order for v in p] for p in d])
        self.pieces.append({'controls':controls,'weight':weight,'derivatives':derivatives,'yaw':yaw});self.length+=weight;self.ends.append(self.length)
    def evaluate(self,s):
        lap=math.floor(s/self.length);s=s-lap*self.length;index=min(len(self.pieces)-1,bisect.bisect_right(self.ends,s));piece=self.pieces[index];start=0 if index==0 else self.ends[index-1];u=(s-start)/piece['weight']
        p=CornerPath._bezier(piece['controls'],u);d1,d2,d3=[CornerPath._bezier(d,u) for d in piece['derivatives']];n2=d1[0]**2+d1[1]**2;cross=d1[0]*d2[1]-d1[1]*d2[0]
        yaw=math.atan2(d1[1],d1[0]);yaw+=2*math.pi*round((piece['yaw']-yaw)/(2*math.pi));yaw-=lap*2*math.pi
        yaw1=cross/n2;yaw2=(d1[0]*d3[1]-d1[1]*d3[0])/n2-2*cross*(d1[0]*d2[0]+d1[1]*d2[1])/n2**2
        return [p[0],p[1],yaw],[d1[0],d1[1],yaw1],[d2[0],d2[1],yaw2]
    def project(self,p):
        candidates=self.cells.get((math.floor(p[0]/500),math.floor(p[1]/500)),[]);best=(math.inf,0)
        for i in candidates:
            a,b,pa,pb=self.samples[i];d=[pb[k]-pa[k] for k in range(2)];norm=sum(v*v for v in d)
            u=max(0,min(1,sum((p[k]-pa[k])*d[k] for k in range(2))/norm));distance=math.hypot(*(p[k]-pa[k]-u*d[k] for k in range(2)))
            if distance<best[0]:best=distance,a+u*(b-a)
        return best
    def station(self,motion,name):
        xy=motion['stations'][name]['park_xy_mm'];distance,s=self.project(xy)
        if distance>.01:raise ValueError('Station waiting position must lie on the aisle ring')
        return s

class RangeWorld:
    def __init__(self,settings,boxes):self.settings=settings;self.boxes=boxes
    def scan(self,pose,discs,now):
        out=[];s=self.settings
        for degrees in range(0,360,s['angular_step_deg']):
            angle=math.radians(degrees);yaw=pose[2]+angle;dx,dy=math.cos(yaw),math.sin(yaw)
            distance=min([s['range_mm'],*[local.ray_disc(*pose[:2],dx,dy,*d) for d in discs],*[local.ray_box(*pose[:2],dx,dy,b) for b in self.boxes]])
            if distance<s['range_mm']:out.append([math.sin(angle)*distance,math.cos(angle)*distance])
        return {'captured_s':now,'returns_local_mm':out}

class MissionController:
    def __init__(self,mission,path,motion,cfg,limits,radius,rule):
        self.mission=mission;self.path=path;self.cfg=cfg;self.limits=limits;self.radius=radius;self.rule=rule;self.direction=mission['initial_direction'];self.goal=path.station(motion,mission['to']);start=path.station(motion,mission['from']);self.driver=self.new_driver(start);self.history=[];self.record(0,start,0,0);self.blocked_since=None;self.rerouted=False;self.events=[];self.retreat_end=None;self.last_scan=None
    @property
    def progress(self):return self.driver.y*self.direction
    def new_driver(self,start):
        distance=(self.goal-start)*self.direction%self.path.length
        return local.LocalController(start*self.direction,start*self.direction+distance,self.cfg,self.limits,self.radius)
    def pose(self):return self.path.evaluate(self.progress)[0]
    def observe(self,raw,own_progress):
        # Only own localization at capture converts the anonymous local returns.
        pose=self.path.evaluate(own_progress)[0];left=[-math.sin(pose[2]),math.cos(pose[2])];forward=[math.cos(pose[2]),math.sin(pose[2])];points=[]
        for x,y in raw['returns_local_mm']:
            p=[pose[k]+left[k]*x+forward[k]*y for k in range(2)];lateral,s=self.path.project(p);points.append((p,lateral,s))
        return {'captured_s':raw['captured_s'],'points_from_own_localization':points}
    def decide(self,now,scan):
        if scan:self.last_scan=scan
        age=now-self.last_scan['captured_s'] if self.last_scan else math.inf;points=[];own=self.pose();width=self.radius+self.cfg['clearance_mm']+self.cfg['range_error_mm']+self.cfg['range_mm']*math.sin(math.radians(self.cfg['angular_step_deg']))
        if self.last_scan:
            for p,lateral,s in self.last_scan['points_from_own_localization']:
                ahead=(s-self.progress)*self.direction%self.path.length
                if lateral<=width+self.path.step/10 and 1e-4<ahead<self.cfg['range_mm']*1.6:
                    distance=math.dist(own[:2],p);points.append([0,distance])
        derived={'captured_s':self.last_scan['captured_s'],'returns_local_mm':points} if self.last_scan else None
        state=self.driver.decide(now,derived)
        # Time is only a persistence condition for a fresh, still-blocked observation.
        # It never asserts that the rear route has become free.
        blocked=self.driver.mode=='waiting' and state['reason']=='local_obstacle' and age<=self.cfg['stale_after_s']
        if blocked:
            if self.blocked_since is None:self.blocked_since=now
            if self.direction==self.rule['yield_direction'] and now-self.blocked_since>=self.rule['blocked_fresh_observation_s']:
                start=self.progress;self.direction=1;self.driver=self.new_driver(start);self.driver.history=[local.point(now,self.driver.y,0,0)];self.rerouted=True;self.blocked_since=None;self.last_scan=None
                self.retreat_end=self.path.ends[1];self.events.append({'time_s':now,'vehicle':self.mission['id'],'event':'local_yield_and_reroute','own_progress_mm':start,'peer_data_used':False});state={'mode':'waiting','reason':'rear_scan_required','scan_age_s':None,'observed_gap_mm':None,'required_gap_mm':None}
        else:self.blocked_since=None
        if state['mode']=='driving' and self.rerouted:state['mode']='retreating' if self.progress<self.retreat_end else 'rerouted'
        return state
    def record(self,t,s,v,a):
        p,d1,d2=self.path.evaluate(s);self.history.append({'time_s':t,F[0]:p,F[1]:[d*v for d in d1],F[2]:[dd*v*v+d*a for d,dd in zip(d1,d2)]})
    def advance(self,start,end):
        previous=len(self.driver.history);self.driver.advance(start,end)
        for p in self.driver.history[previous:]:self.record(p['time_s'],p[F[0]][0]*self.direction,p[F[1]][0]*self.direction,p[F[2]][0]*self.direction)


def simulate(dropout=None,progress=False):
    s,base,motion=load();path=RingPath(motion,s['path_projection_step_mm']);report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text())
    floor.verify({name:sha for name,sha in report['source_files_sha256'].items() if name not in {'scripts/tr01_workcell_player.html','scripts/render_tr01_workcell.py'}})
    for key in ('program','vehicle','freecad'):
        if local.digest(ROOT/report['files'][key])!=report['artifact_sha256'][key]:raise ValueError('Native input changed')
    program=json.loads((ROOT/report['files']['program']).read_text());radius=program['floor_routes'][0]['dynamics']['radius_mm'];cfg={**base['sensor'],**base['controller'],'desired_speed_mm_s':base['desired_speed_mm_s']};limits={k:v*base['controller']['motion_limit_utilization'] for k,v in motion['limits']['linear'].items()}
    controllers=[MissionController(v,path,motion,cfg,limits,radius,s['encounter_rule']) for v in s['missions']]
    p=floor.layout.parameters(floor.layout.load(validate_builds=False));boxes=[[0,0,p['bench_depth'],p['left_depth']],[p['room_width']-p['bench_depth'],0,p['room_width'],p['right_depth']],[p['room_width']/2-p['island_half_width'],p['island_start_y'],p['room_width']/2+p['island_half_width'],p['island_start_y']+p['island_length']]]
    world=RangeWorld(base['sensor'],boxes);pending=[[] for c in controllers];dt=base['controller']['integration_step_s'];scan_steps=round(base['sensor']['period_s']/dt);frames=[];minimum={'car_car':math.inf,'car_person':math.inf,'bench':math.inf};person_source=copy.deepcopy(base);person_source['person'].update({'y_mm':s['person']['y_mm']});bench=program['definition']['work_areas']
    for tick in range(round(s['maximum_duration_s']/dt)+1):
        now=tick*dt;person=local.person_position(person_source,path.lanes[s['person']['lane']],now);poses=[c.pose() for c in controllers]
        if tick%scan_steps==0 and not(dropout and dropout[0]<=now<=dropout[1]):
            for i,c in enumerate(controllers):
                raw=world.scan(poses[i],[(*p[:2],radius) for j,p in enumerate(poses) if i!=j]+[person],now);pending[i].append((now+base['sensor']['latency_s'],c.observe(raw,c.progress)))
        states=[]
        for c,queue in zip(controllers,pending):
            scan=None
            while queue and queue[0][0]<=now+1e-9:scan=queue.pop(0)[1]
            states.append(c.decide(now,scan))
        for i,pose in enumerate(poses):
            minimum['car_person']=min(minimum['car_person'],math.dist(pose[:2],person[:2])-radius-person[2])
            for other in poses[i+1:]:minimum['car_car']=min(minimum['car_car'],math.dist(pose[:2],other[:2])-2*radius)
            for area in bench.values():
                x0,x1,y0,y1=area['bounds_xy_mm'];distance=math.hypot(max(x0-pose[0],pose[0]-x1,0),max(y0-pose[1],pose[1]-y1,0))-radius;minimum['bench']=min(minimum['bench'],distance)
        if progress and tick%400==0:print('traffic',round(now,1),[(c.mission['id'],c.driver.mode,round(c.progress),state.get('observed_gap_mm'),state.get('required_gap_mm')) for c,state in zip(controllers,states)],flush=True)
        finished=all(c.driver.mode=='arrived' for c in controllers)
        if tick%round(s['output_step_s']/dt)==0 or finished:frames.append({'time_s':now,'vehicles':[{'id':m['id'],'station':m['to'],'pose_mm_rad':pose,'velocity_mm_s':c.driver.v,**state} for m,c,pose,state in zip(s['missions'],controllers,poses,states)],'person_mm':person[:2]})
        if finished:break
        for c in controllers:c.advance(now,now+dt)
    trajectories=[];scale=1.
    for m,c in zip(s['missions'],controllers):
        curve=floor.motion.Curve(c.history);dynamic=floor.dynamics(curve,radius)
        scale=max(scale,*[(dynamic[k][name]/motion['limits'][k][name])**(1/order) for k in ('linear','angular','carried_points') for order,name in enumerate(('velocity','acceleration','jerk'),1)])
        trajectories.append({'id':m['id'],'from':m['from'],'station':m['to'],'points':[[p['time_s'],p[F[0]],p[F[1]],p[F[2]]] for p in c.history],'arrived':c.driver.mode=='arrived','stops_for_observation':c.driver.stops,'events':c.events})
    scale=math.ceil(scale*1000)/1000*1.002
    for t in trajectories:
        for p in t['points']:p[0]*=scale;p[2]=[v/scale for v in p[2]];p[3]=[v/scale**2 for v in p[3]]
        curve=floor.motion.Curve([{'time_s':p[0],F[0]:p[1],F[1]:p[2],F[2]:p[3]} for p in t['points']]);t['dynamics']=floor.dynamics(curve,radius)
        if any(t['dynamics'][k][n]>motion['limits'][k][n] for k in ('linear','angular','carried_points') for n in ('velocity','acceleration','jerk')):raise ValueError('Exported mission dynamics exceed source limits')
        for event in t['events']:event['time_s']*=scale
    for frame in frames:
        frame['time_s']*=scale
        for v in frame['vehicles']:
            v['velocity_mm_s']/=scale
            if v['scan_age_s'] is not None:v['scan_age_s']*=scale
    allowance=dt*(2*base['desired_speed_mm_s']+base['person']['lateral_offset_mm']/base['person']['arrives_at_lane_s']);clearance={'car_car_clearance_lower_mm':minimum['car_car']-allowance,'car_person_clearance_lower_mm':minimum['car_person']-allowance,'bench_clearance_lower_mm':minimum['bench']-dt*base['desired_speed_mm_s'],'interval_motion_allowance_mm':allowance}
    dependencies={str(SOURCE.relative_to(ROOT)):local.digest(SOURCE),str(Path(__file__).relative_to(ROOT)):local.digest(__file__),s['base_profile']['source']:s['base_profile']['source_sha256'],'scripts/l01_local_traffic.py':local.digest(local.__file__),**{name:sha for name,sha in report['source_files_sha256'].items() if name not in {'scripts/tr01_workcell_player.html','scripts/render_tr01_workcell.py'}}}
    return {'format':'solidcraftbot.opposing-traffic-result/1','duration_s':frames[-1]['time_s'],'frames':frames,'trajectories':trajectories,'radius_mm':radius,'clearance':clearance,'settings':{**base,**s,'person':{**base['person'],**s['person']}},'source_files_sha256':dependencies,'all_arrived':all(t['arrived'] for t in trajectories),'shared_positions':False,'uniform_clock_scale':scale,'effective_sensor_period_s':base['sensor']['period_s']*scale,'effective_sensor_latency_s':base['sensor']['latency_s']*scale,'effective_obstacle_closing_speed_mm_s':base['sensor']['maximum_obstacle_closing_speed_mm_s']/scale,'native_context':report,'native_pose_coverage':{'passed':False,'method':'new curved poses require a new native proof'},'geometry_path':{'pieces':path.pieces,'length':path.length}}

def reduced_native_reference(points,radius,stride=20):
    """Coarser native query curve plus a bound to every original polynomial.

    Only the certificate uses the reference. Playback and dynamics keep all
    original knots. The native required clearance includes the full error.
    """
    original=floor.motion.Curve(points);indices=sorted(set(range(0,len(points),stride))|{len(points)-1});reduced=[points[i] for i in indices];reference=floor.motion.Curve(reduced);maximum=0.
    for i,coefficients in enumerate(original.segments):
        start,end=original.times[i:i+2];j=min(len(reference.segments)-1,bisect.bisect_right(reference.times,start)-1);a,b=reference.times[j:j+2];alpha=(start-a)/(b-a);beta=(end-start)/(b-a);upper=[]
        for c,r in zip(coefficients,reference.segments[j]):
            composed=[sum(r[n]*math.comb(n,k)*alpha**(n-k)*beta**k for n in range(k,len(r))) for k in range(6)]
            delta=[x-y for x,y in zip(c,composed)];candidates=[0.,1.,*floor.motion.real_roots(floor.motion.derivative(delta))];upper.append(max(abs(floor.motion.polynomial(delta,u)) for u in candidates))
        maximum=max(maximum,math.hypot(*upper[:2])+radius*min(2.,upper[2]))
    return reduced,math.nextafter(maximum+1e-6+radius*1e-10,math.inf)

def validated_result():
    path=ROOT/'exports/tr01-workcell/opposing-traffic.json';proof_path=ROOT/'exports/tr01-workcell/opposing-native-clearance.json';result=json.loads(path.read_text());proof=json.loads(proof_path.read_text())
    floor.verify(result['source_files_sha256'])
    if proof['program_sha256']!=local.digest(path) or proof['checker_sha256']!=local.digest(ROOT/'scripts/check_l01_opposing_traffic_freecad.py') or not proof['passed']:raise ValueError('Current complete native traffic proof required')
    floor.verify(proof['native_inputs_sha256'])
    if not result['all_arrived'] or result['clearance']['bench_clearance_lower_mm']<=0 or min(result['clearance'][k] for k in ('car_car_clearance_lower_mm','car_person_clearance_lower_mm'))<result['settings']['controller']['clearance_mm']:raise ValueError('Incomplete or unsafe opposing traffic result')
    result['native_pose_coverage']={'passed':True,'method':proof['method'],'proof':str(proof_path.relative_to(ROOT)),'proof_sha256':local.digest(proof_path),'program_sha256':local.digest(path)}
    result['source_files_sha256'].update({str(path.relative_to(ROOT)):local.digest(path),str(proof_path.relative_to(ROOT)):local.digest(proof_path),'scripts/check_l01_opposing_traffic_freecad.py':local.digest(ROOT/'scripts/check_l01_opposing_traffic_freecad.py')})
    result.pop('native_context',None);result.pop('geometry_path',None)
    return result

def main():
    result=simulate(progress=True);out=ROOT/'exports/tr01-workcell/opposing-traffic.json';out.write_text(json.dumps(result,separators=(',',':'))+'\n');print(json.dumps({k:result[k] for k in ('duration_s','all_arrived','clearance','uniform_clock_scale')}));print([(t['id'],t['events']) for t in result['trajectories']])
if __name__=='__main__':main()
