"""Fresh native static-route and interval dynamic proof for independent handoffs."""
import bisect,json,math,sys
from pathlib import Path
import FreeCAD as App
import Part
import l01_independent_fleet as fleet
import check_tr01_floor_motion as check
ROOT=fleet.ROOT;OUT=fleet.OUT;F=fleet.F;floor=fleet.floor
sys.path.insert(0,str(ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo

def main():
    path=OUT/'independent-fleet.json';program=json.loads(path.read_text());checksum=program.pop('program_sha256')
    if fleet.serial.canonical_sha(program)!=checksum:raise ValueError('Independent program bytes changed')
    program['program_sha256']=checksum;floor.verify(program['source_files_sha256'])
    config,base,workcell,workspace=fleet.read_inputs();report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text());curves=[floor.motion.Curve([fleet.as_point(*p) for p in v['points']]) for v in program['traffic']['trajectories']];duration=program['duration_s'];radius=workspace['radius_mm'];margin=config['minimum_added_clearance_mm'];source=program['traffic']['settings'];dynamic_margin=source['controller']['clearance_mm'];jobs=program['jobs'];failures=[];leaves=[]
    def fail(message):raise ValueError(message)
    post_export={}
    for track,curve in zip(program['tracks'],curves):
        actual=floor.dynamics(curve,radius)
        for kind in ('linear','angular','carried_points'):
            for metric,limit in floor.load()['limits'][kind].items():
                if actual[kind][metric]>limit:fail('Post-export vehicle motion limit exceeded: '+track['id']+' '+kind+' '+metric)
        run=[];episodes=[];holds=0
        traffic_phase=next(p for p in track['phases'] if p['kind']=='traffic');start=traffic_phase['start_s'];end=start+traffic_phase['duration_s']
        def finish_episode():
            if len(run)<2:return
            proof=floor.no_stop(floor.motion.Curve(run))
            if not proof['passed']:fail('Post-export internal transport rest or unresolved speed: '+track['id']+' '+json.dumps(proof['failures'][:3]))
            episodes.append({'start_s':run[0]['time_s'],'end_s':run[-1]['time_s'],'passed':True})
        for index,(a,b) in enumerate(zip(curve.points,curve.points[1:])):
            if b['time_s']<=start or a['time_s']>=end:continue
            moving=max(abs(v) for axis in curve.segments[index] for v in axis[1:])>=1e-12
            if moving:
                if not run:run.append(a)
                run.append(b)
            else:finish_episode();run=[];holds+=1
        finish_episode();post_export[track['id']]={'dynamics':actual,'moving_episodes':episodes,'controller_observation_or_arrival_hold_intervals':holds,'passed':True}
    print('Post-export PVA limits and no-stop moving episodes passed',flush=True)
    for job in jobs:
        key=job['station']+':'+job['direction'];bound=workspace['jobs'][key]
        if any(job[k]!=bound[k] for k in ('actor','area','box')):fail('Station reservation differs from native workspace')
        observation=[e for e in program['workplace_observations'] if e['station']==job['station'] and e['time_s']<=job['start_s']]
        if not observation or max(observation,key=lambda e:e['time_s'])['status']!='person_clear':fail('Station admitted without named positive observation')
        if any(e['station']==job['station'] and job['start_s']<e['time_s']<job['end_s'] and e['status']!='person_clear' for e in program['workplace_observations']):fail('New occupation invalidated a running station lease')
        track=next(t for t in program['tracks'] if t['id']==job['vehicle']);parts=[p for p in track['phases'] if p.get('stage')==job['direction'] and p['kind'] not in ('resource_wait','traffic')]
        for phase in parts:
            if phase['kind'] in ('arm','dock'):
                lease=phase['state']['benches'][job['area']]
                if not lease['person_clear'] or lease['vehicle']!=job['vehicle']:fail('Moving phase has no exclusive current work-area lease')
            if phase['kind']=='arm':
                ref=workcell['stations'][job['station']]['transfers'][phase['direction']][phase['part']]
                if phase['actor']!=job['actor'] or abs(ref['duration_s']-phase['duration_s'])>1e-9:fail('Arm reference or clock changed')
        index=next(i for i,t in enumerate(program['tracks']) if t['id']==job['vehicle']);bounds=floor.extrema(curves[index],job['start_s'],job['end_s'])
        if any(bounds['min'][k]-radius<bound['vehicle']['min'][k]-1e-5 or bounds['max'][k]+radius>bound['vehicle']['max'][k]+1e-5 for k in range(2)):fail('Actual vehicle leaves its reserved native docking envelope')
    for i,a in enumerate(jobs):
        for b in jobs[i+1:]:
            if min(a['end_s'],b['end_s'])<=max(a['start_s'],b['start_s']):continue
            if a['area']==b['area'] or a['actor']==b['actor']:fail('Simultaneous exclusive station or arm owners')
            distance=check.box_distance(a['box'],b['box'])
            if distance<margin:fail('Overlapping simultaneous swept workspaces')
            leaves.append({'kind':'job_job','vehicles':[a['vehicle'],b['vehicle']],'clearance_lower_mm':distance})
    for job in jobs:
        lower=check.box_distance(job['box'],program['traffic']['person_full_envelope'])
        if lower<margin:fail('Person envelope intersects an active handoff workspace')
        leaves.append({'kind':'job_person','vehicle':job['vehicle'],'clearance_lower_mm':lower})
    person_epoch=program['traffic']['person_epoch_s'];person_source={'person':source['person']};lane=program['traffic']['person_full_envelope']['min'][0]+source['person']['radius_mm']
    def person(t):return fleet.local.person_position(person_source,lane,max(0,t-person_epoch))
    person_knots=[person_epoch+source['person'][k] for k in ('arrives_at_lane_s','leaves_lane_s','fully_clear_s')]+[person_epoch]
    def centre_bound(i,a,b):
        mid=(a+b)/2;p=curves[i].evaluate(mid)[F[0]];bounds=floor.extrema(curves[i],a,b);delta=math.hypot(*[max(abs(bounds['min'][k]-p[k]),abs(bounds['max'][k]-p[k])) for k in (0,1)]);return p,delta
    def certify(a,b,kind,indices,job=None,depth=0):
        mid=(a+b)/2;p,delta=centre_bound(indices[0],a,b);required=dynamic_margin if kind in ('car_car','car_person') else margin
        if kind=='car_car':q,other=centre_bound(indices[1],a,b);lower=math.dist(p[:2],q[:2])-2*radius-delta-other
        elif kind=='car_person':
            q=person(mid);samples=[person(t) for t in [a,b,*[t for t in person_knots if a<t<b]]];other=max(math.dist(s[:2],q[:2]) for s in samples);lower=math.dist(p[:2],q[:2])-radius-q[2]-delta-other
        else:
            box=job['box'];distance=math.hypot(*[max(0.,box['min'][k]-p[k],p[k]-box['max'][k]) for k in (0,1)]);lower=distance-radius-delta
        if lower>=required:
            leaves.append({'kind':kind,'start_s':a,'end_s':b,'vehicles':indices,'job_vehicle':job['vehicle'] if job else None,'clearance_lower_mm':lower,'required_mm':required});return
        if depth>=18 or b-a<1e-5:
            failures.append({'kind':kind,'start_s':a,'end_s':b,'lower_mm':lower,'required_mm':required});return
        certify(a,mid,kind,indices,job,depth+1);certify(mid,b,kind,indices,job,depth+1)
    # Windows cover every original time, including long waits and all overlaps;
    # extrema are evaluated on ORIGINAL exported PVA polynomials, never frames.
    boundaries=sorted({0.,duration,*[min(duration,5.*i) for i in range(math.ceil(duration/5)+1)],*[j[k] for j in jobs for k in ('start_s','end_s')],*[t for t in person_knots if 0<t<duration]})
    for a,b in zip(boundaries,boundaries[1:]):
        for i in range(3):
            certify(a,b,'car_person',[i])
            for j in range(i+1,3):certify(a,b,'car_car',[i,j])
            for job in jobs:
                if job['vehicle']!=program['missions'][i]['id'] and job['start_s']<=a+1e-8 and job['end_s']>=b-1e-8:certify(a,b,'car_job',[i],job)
        if failures:break
    for i,track in enumerate(program['tracks']):
        for phase in track['phases']:
            if phase['kind']!='traffic':continue
            a=phase['start_s'];end=a+phase['duration_s']
            for area,definition in workcell['definition']['work_areas'].items():
                x0,x1,y0,y1=definition['bounds_xy_mm'];bench={'vehicle':'bench:'+area,'box':{'min':[x0,y0,0],'max':[x1,y1,10000]}}
                t=a
                while t<end-1e-9:
                    b=min(end,t+5);certify(t,b,'car_bench',[i],bench);t=b
    if failures:fail('Unresolved or failed coupled interval: '+json.dumps(failures[:5]))
    print('Coupled interval bounds passed',len(leaves),flush=True)
    car=App.openDocument(str(ROOT/report['files']['vehicle']));vehicle=Part.makeCompound([geo.world_shape(o) for o in geo.features(car)]);scene=App.openDocument(str(ROOT/report['files']['freecad']));obstacles=[(o.Label,geo.world_shape(o),check.box(geo.world_shape(o))) for o in scene.Objects if hasattr(o,'Shape') and not o.Shape.isNull() and '_view_CONE' not in o.Label]
    routes=[{'id':v['id'],'duration_s':duration,'points':floor.public(c.points)} for v,c in zip(program['traffic']['trajectories'],curves)]
    native=check.validate({'definition':floor.load(),'routes':routes},vehicle,obstacles,radius,App)
    summary={'added_obstacle_checks':len(leaves),'minimum_added_obstacle_clearance_mm':min(v['clearance_lower_mm'] for v in leaves),'required_mm':margin,'native_routes_passed':native['passed'],'maximum_parallel_arms':program['statistics']['maximum_parallel_arms'],'driving_during_arm_handoff':program['statistics']['driving_during_arm_handoff'],'original_static_arm_proof':'Original source-bound discrete native checks, unchanged; concurrent moving obstacles additionally enclosed continuously','added_obstacle_proof':'Full new native vehicle PVA routes plus analytic interval car/car, car/person, car/workspace, disjoint parallel native swept workspaces'}
    result={'passed':native['passed'] and not failures,'program_sha256':checksum,'checker_sha256':fleet.local.digest(__file__),'native_inputs_sha256':{**{report['files'][k]:report['artifact_sha256'][k] for k in ('vehicle','freecad','program','arm_validation','floor_validation')},'exports/tr01-workcell/independent-workspaces.json':fleet.local.digest(OUT/'independent-workspaces.json')},'summary':summary,'method':summary['added_obstacle_proof'],'post_export_motion':post_export,'intervals':leaves,'native':native}
    (OUT/'independent-fleet-clearance.json').write_text(json.dumps(result,separators=(',',':'))+'\n');print(json.dumps(summary),flush=True)
    if not result['passed']:fail('Fresh native independent-fleet route proof failed')
if __name__=='__main__':
    import check_l01_independent_fleet_freecad as adapter
    adapter.main()
