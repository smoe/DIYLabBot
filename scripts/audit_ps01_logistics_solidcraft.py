"""Native SolidCraft occurrence poses and BRep distances for PS01/TR01 paths."""
import argparse
import itertools
import math
from pathlib import Path
import time

import build_ps01_logistics as build
from ps01_logistics_validation import Program,certify,transformed,bbox_distance
from solidcraft_audit_session import Session

s=build.s


def certify_partitioned(program,records,provider,path):
    """Use a complete suggested partition, never another CAD's distances."""
    from report_ps01_logistics import coverage
    suggestion=s.read(path);coverage(suggestion,program)
    spans={str(i):(row['phase'],*row['interval']) for i,row in enumerate(suggestion['continuous_intervals'])}
    def mapped(key,a,b):
        phase,lo,hi=spans[key]
        return phase,lo+(hi-lo)*a,lo+(hi-lo)*b
    class Partition:
        definition=program.definition;links=program.links;curves=spans
        def collision_pairs(self,items):return program.collision_pairs(items)
        def delta(self,key,a,b,record):return program.delta(*mapped(key,a,b),record)
        def pair_bound(self,pair,key,a,b,frame):return program.pair_bound(pair,*mapped(key,a,b),frame)
    def frames(requests):
        converted=[]
        for key,mid,width in requests:
            phase,a,b=mapped(key,mid-width/2,mid+width/2)
            converted.append((phase,(a+b)/2,b-a))
        return provider(converted)
    result=certify(Partition(),records,frames)
    for row in result['continuous_intervals']:
        phase,a,b=mapped(row['phase'],*row['interval']);row.update(phase=phase,interval=[a,b])
    for row in result['failures']:
        key=row['phase'];row['phase']=spans[key][0]
        if 'interval' in row:row['interval']=list(mapped(key,*row['interval'])[1:])
        if 'u' in row:row['u']=mapped(key,row['u'],row['u'])[1]
    result['partition_suggestion']={'path':str(path.resolve()),'sha256':s.robot.digest(path),
        'initial_maximum_depth':suggestion['maximum_depth'],
        'scope':'Subdivision suggestions only; every accepted interval uses SolidCraft native geometry and the conservative bounds again'}
    result['maximum_depth_scope']='Additional subdivisions beyond the suggested intervals'
    return result


class Provider:
    def __init__(self,directory,cli):
        self.dest=Path(directory);self.scene=build.geometry.Scene()
        self.program=Program(s.read(self.dest/'program.json'),self.scene)
        self.report=s.read(self.dest/'solidcraft-local-report.json');self.bodies=self.report['records']
        self.records=build.grouped(self.bodies);self.lookup={r['id']:r for r in self.records}
        for record in self.records:
            record['names']=[n for body in self.bodies if body['id'] in record['members'] for n in body['names']]
        self.pairs,_=self.program.collision_pairs(self.records)
        self.session=Session(cli,s.ROOT,self.dest,self.dest/'Logistics-local.solidcraft')
        self.poses={r['occurrence']:s.robot.identity() for r in self.records if r.get('occurrence')}
        self.occurrence_corners={occurrence:[point for record in self.records if record.get('occurrence')==occurrence
            for point in itertools.product(*zip(record['local_bbox']['min'],record['local_bbox']['max']))]
            for occurrence in self.poses}
        self.distance_cache={};self.exact=0;self.frames=0;self.started=time.monotonic()

    def drive(self,phase,u):
        targets={r['occurrence']:self.program.matrix(r,phase,u) for r in self.records if r.get('occurrence')}
        commands=[];names=[]
        for occurrence,target in targets.items():
            current=self.poses[occurrence]
            if max(abs(a-b) for x,y in zip(current,target) for a,b in zip(x,y))<1e-12:continue
            commands.append({'command':'occurrence.move','params':{'occurrence':occurrence,'space':'world',
                'move_grounded':True,'matrix':s.robot.multiply(target,s.robot.inverse(current))}});names.append(occurrence)
        values=self.session.run(commands) if commands else []
        s.require(len(values)==len(names),'Incomplete native occurrence updates')
        error=0.
        for occurrence,result in zip(names,values):
            s.require(isinstance(result,dict) and 'transform' in result and not result.get('pending'),'Missing native solved occurrence')
            actual=[list(row) for row in zip(*result['transform'])]
            # Bound positional disagreement over the entire native body box.
            # Rotation matrix entries alone are dimensionless, not millimetres.
            error=max(error,max(math.dist(s.robot.transform(actual,point),s.robot.transform(targets[occurrence],point))
                                for point in self.occurrence_corners[occurrence]))
            self.poses[occurrence]=actual
        s.require(error<1e-7,'Native occurrence pose differs from compiled FK')
        matrices={r['id']:self.poses[r['occurrence']] if r.get('occurrence') else r['matrix'] for r in self.records}
        boxes={r['id']:transformed(r['local_bbox'],matrices[r['id']]) for r in self.records}
        return matrices,boxes,error

    def __call__(self,requests):
        prepared=[];guard=self.program.definition['continuous_audit']['numeric_guard_mm']
        for phase,u,width in requests:
            matrices,boxes,error=self.drive(phase,u);distances={};coarse=width>1/16
            radii={r['id']:self.program.delta(phase,u-width/2,u+width/2,r) for r in self.records} if not coarse else {}
            candidates=[]
            for pair in self.pairs:
                    a,b=pair['a'],pair['b'];lower=bbox_distance(boxes[a],boxes[b])
                    fixed=self.program.relative_fixed(pair,phase,u-width/2,u+width/2)
                    # Fixed seating/retention interfaces may certify at the
                    # coarsest interval, so check their native overlap now.
                    if coarse and pair['category']!='seating_contact':continue
                    excursion=0 if fixed else math.inf if coarse else radii[a]+radii[b]
                    if lower-excursion-guard>=pair['required_mm'] and lower>.01:continue
                    # A box is a conservative lower bound. Distant candidates
                    # can refine without expensive native BRep queries.
                    if lower>5:continue
                    relative=s.robot.multiply(s.robot.inverse(matrices[a]),matrices[b])
                    key=(a,b,tuple(round(v,8) for row in relative for v in row))
                    if key in self.distance_cache:distances[(a,b)]=self.distance_cache[key]
                    else:candidates.append((pair,key))
            commands=[];owners=[];body_lookup={r['id']:r for r in self.bodies}
            for pair,key in candidates:
                a,b=pair['a'],pair['b']
                for x,y in itertools.product(self.lookup[a]['members'],self.lookup[b]['members']):
                    bx,by=body_lookup[x],body_lookup[y]
                    if bbox_distance(transformed(bx['local_bbox'],matrices[a]),transformed(by['local_bbox'],matrices[b]))>5:continue
                    for nx,ny in itertools.product(bx['names'],by['names']):
                        commands.append({'command':'inspect.measure','params':{'items':[{'type':'body','name':nx},{'type':'body','name':ny}]}})
                        contact=pair['category']=='seating_contact'
                        if contact:commands.append({'command':'inspect.interference','params':{'bodies':[nx,ny]}})
                        owners.append((pair,key,nx,ny,contact))
            raw=iter(self.session.run(commands) if commands else []);measured={}
            for pair,key,nx,ny,contact in owners:
                value=next(raw);s.require({x['name'] for x in value['items']}=={nx,ny},'Foreign native distance')
                d=value['distance_mm'];s.require(math.isfinite(d) and d>=0,'Invalid native BRep distance')
                s.require(d+1e-7>=pair['required_mm'],'Native clearance failure: '+str((pair,d,phase,u)))
                if contact:
                    hit=next(raw);s.require(hit['checked']==2 and not any(hit[k] for k in ('unchecked','truncated','budget_exceeded','pairs_not_checked')),'Incomplete contact audit')
                    volume=sum(x['volume_mm3'] for x in hit['interferences'])
                    s.require(volume<=1e-4,'Positive native seating overlap: '+str((pair,volume)))
                measured[key]=min(measured.get(key,math.inf),d);self.exact+=1
            for pair,key in candidates:
                # Unqueried sub-body pairs were separated by at least 5 mm.
                value=min(measured.get(key,math.inf),5.)
                self.distance_cache[key]=value;distances[(pair['a'],pair['b'])]=value
            frame={'boxes':boxes,'fk_error_mm':error,'coarse_lower_bounds_only':True,
                'distance':lambda a,b,ds=distances,bs=boxes:ds.get((a,b),bbox_distance(bs[a],bs[b]))}
            prepared.append(frame);self.frames+=1
            if self.frames%32==0:
                print({'poses':self.frames,'native_distances':self.exact,'phase':phase,
                       'elapsed_s':round(time.monotonic()-self.started,1)},flush=True)
        print({'poses':self.frames,'native_distances':self.exact,'elapsed_s':round(time.monotonic()-self.started,1)},flush=True)
        return prepared


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--solidcraft-cli',required=True);parser.add_argument('--mode',choices=('continuous','discrete','pose'),default='continuous')
    parser.add_argument('--partition',type=Path,help='Optional complete interval partition; all native distances are independently rechecked')
    args=parser.parse_args();dest=args.directory
    execution_pins={**build.pins(),str(Path(__file__).resolve().relative_to(s.ROOT)):s.robot.digest(Path(__file__))}
    if args.partition:
        helper=s.ROOT/'scripts/report_ps01_logistics.py'
        execution_pins[str(helper.relative_to(s.ROOT))]=s.robot.digest(helper)
    program_hash=s.robot.digest(dest/'program.json')
    artifact_hash=s.robot.digest(dest/'Logistics-local.solidcraft')
    provider=Provider(dest,args.solidcraft_cli)
    result={'passed':False,'error':'Audit did not complete'}
    try:
        if args.mode=='continuous':
            _,_,error=provider.drive('load.approach',0)
            provider.session.tool('save',{'path':str((dest/'Logistics.solidcraft').resolve())})
            build.write(dest/'solidcraft-pose.json',{'passed':True,'maximum_native_pose_error_mm':error,
                'program_sha256':program_hash,'artifact_sha256':s.robot.digest(dest/'Logistics.solidcraft'),
                'scope':'Native initial occurrence poses; continuous collision audit follows separately'})
            result=(certify_partitioned(provider.program,provider.records,provider,args.partition) if args.partition else
                    certify(provider.program,provider.records,provider))
        elif args.mode=='discrete':
            failures=[]
            for phase in provider.program.curves:
                for u in (0,.25,.5,.75,1):
                    frame=provider([(phase,u,0)])[0]
                    for pair in provider.pairs:
                        distance=frame['distance'](pair['a'],pair['b'])
                        if distance+1e-7<pair['required_mm']:failures.append({**pair,'phase':phase,'u':u,'distance_mm':distance})
            result={'passed':not failures,'failures':failures,'scope':'Diagnostic discrete poses only'}
        else:
            provider.drive('load.approach',0);provider.session.tool('save',{'path':str((dest/'Logistics.solidcraft').resolve())})
            values=provider.session.run([{'command':'inspect.measure','params':{}}]);result={'passed':True,'measurement':values[0]}
    except (ValueError,RuntimeError) as error:
        result={'passed':False,'error':str(error)}
    finally:
        try:
            build.base.verify_pins(execution_pins)
            s.require(program_hash==s.robot.digest(dest/'program.json') and
                      artifact_hash==s.robot.digest(dest/'Logistics-local.solidcraft'),'Audit inputs changed during execution')
        except ValueError as error:
            result={'passed':False,'error':str(error)}
        result.update(backend='solidcraft',native_distances=provider.exact,elapsed_s=time.monotonic()-provider.started,
            artifact_sha256=artifact_hash,program_sha256=program_hash,source_files_sha256=execution_pins)
        build.write(dest/('solidcraft-'+args.mode+'.json'),result)
        print({'passed':result['passed']},flush=True)
        provider.session.close()


if __name__=='__main__':main()
