"""Independent native SolidCraft arm construction and batched distance provider."""
import copy
import itertools
import json
import math
import subprocess
import h02_arm_pickup as model
import h02_direct_pickup as local
import build_h02_direct_pickup as local_builder
import solidcraft_vendor as vendor
import build_extraction_kit_station as common
from solidcraft_audit_session import Session


def drive(program,phase,u):
    state=program.state(phase,u)
    result=[{'command':'joint.drive','params':{'joint':joint['id'],'value':value,'quiet':True}}
            for joint,value in zip(program.arm['joints'],state['joints_deg'])]
    result.extend({'command':'joint.drive','params':{'joint':name,'value':value,'quiet':True}} for name,value in state['coordinates'].items())
    result.append({'command':'joint.solve','params':{}})
    return result


def run(cli,commands,directory,name,native=None,save=None,engine=None):
    script=directory/(name+'.commands.json');output=directory/(name+'.json');common.write(script,{'commands':commands})
    if engine is not None:
        result=engine.run(commands);common.write(output,result);return result
    cmd=[cli,'run',str(script),'--quiet','--results','--json-out',str(output)]
    if native:cmd+=['--in',str(native)]
    if save:cmd+=['--save',str(save)]
    with (directory/(name+'.log')).open('w') as log:subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT)
    return json.loads(output.read_text())


def measurements(results):
    return [v for v in results if isinstance(v,dict) and isinstance(v.get('bodies'),list) and v['bodies'] and
            isinstance(v['bodies'][0],dict) and 'bbox' in v['bodies'][0]]


def aggregate(raw,names):
    chosen=[raw[n] for n in names];volume=sum(v['volume_mm3'] for v in chosen)
    if volume<=0 or any(not v['closed'] for v in chosen):raise ValueError('Invalid native body')
    return {'name':names[0],'volume_mm3':volume,'center_of_mass':[sum(v['center_of_mass'][i]*v['volume_mm3'] for v in chosen)/volume for i in range(3)] if 'center_of_mass' in chosen[0] else None,
        'bbox':{edge:[fn(v['bbox'][edge][i] for v in chosen) for i in range(3)] for edge,fn in [('min',min),('max',max)]}}


def construct(cli,program,variant,directory,cad,sections):
    spec=local.context(program.local_scene,variant);p=local.parameters(spec);source,_,_=local.proof(spec,p)
    commands,aliases=vendor.replace_imports(model.robot.solidcraft_commands(program.arm,root_offset=program.definition['arm_fixture']['position_mm']),sections)
    arm=model.robot.expanded(program.arm);cones={op['body'] for link in arm['links'] for op in link['recipe'] if op['action']=='create' and op.get('role')=='viewing_cone'}
    filtered=[]
    for cmd in commands:
        c=copy.deepcopy(cmd);args=c['params']
        if args.get('body_name') in cones or args.get('body') in cones:continue
        for field in ['bodies','targets']:
            if field in args:
                args[field]=[n for n in args[field] if n not in cones]
                if not args[field]:break
        else:filtered.append(c)
    commands=filtered+local_builder.commands(spec,p,source)
    for joint in program.arm['joints']:commands.append({'command':'joint.drive','params':{'joint':joint['id'],'value':0,'quiet':True}})
    commands.append({'command':'joint.solve','params':{}})
    records=[]
    for link in arm['links']:
        for op in link['recipe']:
            if op['action']=='create' and op['body'] not in cones:
                records.append({'id':op['body'],'group':link['id'],'kind':'arm','role':op['role'],'names':aliases.get(op['body'],[op['body']])})
    hidden=[]
    for b in source['bodies']:
        if b['component']=='Proof':hidden.append(b['id']);continue
        kind='sample' if b['component']=='Tube' else 'tool' if b['component'] in ('Tool','FingerLeft','FingerRight') else 'fixture'
        records.append({'id':b['id'],'group':b['component'],'kind':kind,'role':b['role'],'names':[b['id']]})
    for probe in model.probes(program):
        center=[a+b for a,b in zip(probe['point'],program.definition['arm_fixture']['position_mm'])]
        commands.extend([{'command':'solid.sphere','params':{'center':center,'radius':.2,'body_name':probe['id']}},
                         {'command':'component.move_bodies','params':{'component':probe['group'],'bodies':[probe['id']]}}]);hidden.append(probe['id'])
    plane=program.definition['support_plane'];commands.extend([
        {'command':'solid.box','params':{'corner':plane['origin_mm'],'length':plane['size_mm'][0],'width':plane['size_mm'][1],'height':plane['size_mm'][2],'body_name':'SupportPlane'}},
        {'command':'appearance.assign','params':{'bodies':['SupportPlane'],'color':'#90999c','opacity':1}}])
    records.append({'id':'SupportPlane','group':'Ground','kind':'bench','role':'support_plane_witness','names':['SupportPlane']})
    control_z=program.z0+program.kin.length-3+program.travel/2
    commands.extend([{'command':'solid.box','params':{'corner':[-.5,-.5,control_z-.5],'length':1,'width':1,'height':1,'body_name':'ArmMidpathBlocker'}},
                     {'command':'component.move_bodies','params':{'component':'Proof','bodies':['ArmMidpathBlocker']}}]);hidden.append('ArmMidpathBlocker')
    commands.extend(drive(program,'closure',1));commands.append({'command':'browser.visibility','params':{'items':hidden,'visible':False}})
    commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.h02-arm-pickup':{
        'source':common.relative(model.SOURCE),'source_sha256':model.robot.digest(model.SOURCE),'branch':program.definition['branch'],
        'status':program.definition['status']}}}})
    file=cad/(variant+'.sc');result=run(cli,commands,directory,'build',save=file);raw=measurements(result)
    engine=Session(cli,model.ROOT,directory,file)
    # --results does not append a measurement automatically.
    values=run(cli,[{'command':'inspect.measure','params':{}}],directory,'grasp',file,engine=engine);raw=measurements(values)[0]
    zero=[{'command':'joint.drive','params':{'joint':j['id'],'value':0,'quiet':True}} for j in program.arm['joints']]+[{'command':'joint.solve','params':{}},{'command':'inspect.measure','params':{}}]
    baseline=measurements(run(cli,zero,directory,'zero',file,engine=engine))[0];body={b['name']:b for b in baseline['bodies']}
    for record in records:
        b=aggregate(body,record['names'])['bbox']
        record['local_bbox']={edge:[x-y for x,y in zip(b[edge],program.definition['arm_fixture']['position_mm'])] for edge in ['min','max']} if record['kind']=='arm' else b
    return file,records,raw,aliases,engine


class Provider:
    def __init__(self,cli,program,native,directory,records,expected_names,engine=None):
        self.cli,self.program,self.native,self.directory,self.records,self.expected_names=cli,program,native,directory,records,set(expected_names)
        self.pairs,_=model.collision_pairs(program,records);self.batch=0
        self.engine=engine or Session(cli,model.ROOT,directory,native)

    def __call__(self,requests):
        index=self.batch;self.batch+=1;commands=[]
        for phase,u,width in requests:commands+=drive(self.program,phase,u)+[{'command':'inspect.measure','params':{'summary':True}}]
        frames=measurements(run(self.cli,commands,self.directory,'frames-'+str(index),self.native,engine=self.engine))
        if len(frames)!=len(requests):raise ValueError('Incomplete SolidCraft native poses')
        prepared=[];distance_commands=[];owners=[]
        for number,((phase,u,width),frame) in enumerate(zip(requests,frames)):
            by_name={v['name']:v for v in frame['bodies']}
            if set(by_name)!=self.expected_names:raise ValueError('Native body completeness changed')
            semantic={r['id']:aggregate(by_name,r['names']) for r in self.records};boxes={n:v['bbox'] for n,v in semantic.items()}
            centers={name:[(a+b)/2 for a,b in zip(by_name[name]['bbox']['min'],by_name[name]['bbox']['max'])]
                     for name in [p['id'] for p in model.probes(self.program)]+['ToolMount']}
            distances={};candidates=[]
            for pair in self.pairs:
                if width<=1/16 and model.bbox_distance(boxes[pair['a']],boxes[pair['b']])<max(5,max(self.program.definition['clearance_mm'].values())+1):
                    candidates.append(pair)
            if candidates:
                distance_commands+=drive(self.program,phase,u)
                lookup={r['id']:r['names'] for r in self.records}
                for pair in candidates:
                    for a,b in itertools.product(lookup[pair['a']],lookup[pair['b']]):
                        distance_commands.append({'command':'inspect.measure','params':{'items':[{'type':'body','name':a},{'type':'body','name':b}]}})
                        owners.append((number,pair['a'],pair['b'],a,b))
            prepared.append({'boxes':boxes,'coarse_lower_bounds_only':width>1/16,'fk_error_mm':model.probe_error(self.program,self.program.state(phase,u),centers,self.records),'distances':distances,'geometry':semantic})
        raw=run(self.cli,distance_commands,self.directory,'distances-'+str(index),self.native,engine=self.engine) if distance_commands else []
        values=[v for v in raw if isinstance(v,dict) and 'distance_mm' in v]
        if len(values)!=len(owners):raise ValueError('Incomplete native distances')
        for (number,x,y,a,b),value in zip(owners,values):
            if {v['name'] for v in value['items']}!={a,b}:raise ValueError('Foreign native distance result')
            distances=prepared[number]['distances'];distances[(x,y)]=min(distances.get((x,y),math.inf),value['distance_mm'])
        for frame in prepared:
            frame['distance']=lambda a,b,values=frame['distances'],boxes=frame['boxes']:values.get((a,b),model.bbox_distance(boxes[a],boxes[b]))
        print('SolidCraft continuous batch '+str(index)+' poses '+str(len(requests))+' exact native distances '+str(len(values)),flush=True)
        return prepared
