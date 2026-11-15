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
    if getattr(program,'native_batch_drive',False):
        from h02_native_pose_boxes import drive as pose_drive
        return pose_drive(program,phase,u)
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
    local_commands=local_builder.commands(spec,p,source)
    extra=[]
    if hasattr(program,'extra_parts'):
        from h02_transfer_adapters import transfer_sliders,solidcraft_extra
        local_commands=transfer_sliders(local_commands,program);extra_commands,extra=solidcraft_extra(program,variant);local_commands+=extra_commands
    commands=filtered+local_commands
    for joint in program.arm['joints']:commands.append({'command':'joint.drive','params':{'joint':joint['id'],'value':0,'quiet':True}})
    commands.append({'command':'joint.solve','params':{}})
    records=[]
    for link in arm['links']:
        for op in link['recipe']:
            if op['action']=='create' and op['body'] not in cones:
                records.append({'id':op['body'],'group':link['id'],'kind':'arm','role':op['role'],'names':aliases.get(op['body'],[op['body']])})
    hidden=[]
    for b in extra:
        records.append({'id':b['id'],'group':b['group'],'kind':b['kind'],'role':b['role'],'names':[b['id']]})
        if b['hidden']:hidden.append(b['id'])
    for b in source['bodies']:
        if b['component']=='Proof':hidden.append(b['id']);continue
        kind='sample' if b['component']=='Tube' else 'tool' if b['component'] in ('Tool','FingerLeft','FingerRight') else 'fixture'
        records.append({'id':b['id'],'group':b['component'],'kind':kind,'role':b['role'],'names':[b['id']]})
    for probe in model.probes(program):
        center=probe['point'] if probe.get('world_template') else [a+b for a,b in zip(probe['point'],program.definition['arm_fixture']['position_mm'])]
        commands.extend([{'command':'solid.sphere','params':{'center':center,'radius':.2,'body_name':probe['id']}},
                         {'command':'component.move_bodies','params':{'component':probe['group'],'bodies':[probe['id']]}}]);hidden.append(probe['id'])
    plane=program.definition['support_plane'];commands.extend([
        {'command':'solid.box','params':{'corner':plane['origin_mm'],'length':plane['size_mm'][0],'width':plane['size_mm'][1],'height':plane['size_mm'][2],'body_name':'SupportPlane'}},
        {'command':'appearance.assign','params':{'bodies':['SupportPlane'],'color':'#90999c','opacity':1}}])
    records.append({'id':'SupportPlane','group':'Ground','kind':'bench','role':'support_plane_witness','names':['SupportPlane']})
    mid=program.state('extraction',.5);point=mid.get('tool_position_mm',[0,0,mid['tool_z_mm']]);control_z=point[2]+program.kin.length-3
    commands.extend([{'command':'solid.box','params':{'corner':[point[0]-.5,point[1]-.5,control_z-.5],'length':1,'width':1,'height':1,'body_name':'ArmMidpathBlocker'}},
                     {'command':'component.move_bodies','params':{'component':'Proof','bodies':['ArmMidpathBlocker']}}]);hidden.append('ArmMidpathBlocker')
    if hasattr(program,'extra_parts'):
        from h02_native_pose_boxes import STUDY,keys
        commands.append({'command':'motion.study','params':{'name':STUDY,'steps':1,'keys':keys(program,'closure',1)}});program.native_batch_drive=True
    commands.extend(drive(program,'closure',1));commands.append({'command':'browser.visibility','params':{'items':hidden,'visible':False}})
    commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.h02-arm-pickup':{
        'source':common.relative(getattr(program,'source_path',model.SOURCE)),'source_sha256':model.robot.digest(getattr(program,'source_path',model.SOURCE)),'branch':program.definition['branch'],
        'status':program.definition['status']}}}})
    file=cad/(variant+'.sc');result=run(cli,commands,directory,'build',save=file);raw=measurements(result)
    engine=Session(cli,model.ROOT,directory,file)
    # --results does not append a measurement automatically.
    values=run(cli,[{'command':'inspect.measure','params':{}}],directory,'grasp',file,engine=engine);raw=measurements(values)[0]
    zero=[{'command':'joint.drive','params':{'joint':j['id'],'value':0,'quiet':True}} for j in program.arm['joints']]+[{'command':'joint.solve','params':{}},{'command':'inspect.measure','params':{}}]
    baseline=measurements(run(cli,zero,directory,'zero',file,engine=engine))[0];body={b['name']:b for b in baseline['bodies']}
    for record in records:
        b=aggregate(body,record['names'])['bbox']
        record['native_zero_bbox']=b
        record['local_bbox']={edge:[x-y for x,y in zip(b[edge],program.definition['arm_fixture']['position_mm'])] for edge in ['min','max']} if record['kind']=='arm' else b
    program.native_zero_measurement=baseline
    return file,records,raw,aliases,engine


class Provider:
    def __init__(self,cli,program,native,directory,records,expected_names,engine=None):
        self.cli,self.program,self.native,self.directory,self.records,self.expected_names=cli,program,native,directory,records,set(expected_names)
        self.pairs,_=getattr(program,'collision_pairs',lambda records:model.collision_pairs(program,records))(records);self.batch=0
        self.engine=engine or Session(cli,model.ROOT,directory,native)
        self.pose_cache=None
        if getattr(program,'native_batch_drive',False):
            zero=[{'command':'joint.drive','params':{'joint':j['id'],'value':0,'quiet':True}} for j in program.arm['joints']]
            zero.extend({'command':'joint.drive','params':{'joint':k,'value':0,'quiet':True}} for k in program.coordinate_names)
            zero.append({'command':'joint.solve','params':{}});self.engine.run(zero)
            self.pose_cache={name:model.robot.identity() for name in [*program.links,'Tool','Tube','FingerLeft','FingerRight']}
            self.zero={b['name']:b for b in program.native_zero_measurement['bodies']}
            if set(self.zero)!=self.expected_names:raise ValueError('Incomplete native zero-construction BReps')

    def __call__(self,requests):
        index=self.batch;self.batch+=1;commands=[]
        for phase,u,width in requests:
            commands+=drive(self.program,phase,u)
            if self.pose_cache is None:commands.append({'command':'inspect.measure','params':{'summary':True}})
        raw_frames=run(self.cli,commands,self.directory,'frames-'+str(index),self.native,engine=self.engine)
        if self.pose_cache is None:frames=measurements(raw_frames)
        else:
            from h02_native_pose_boxes import update,snapshot
            frames=[]
            for r in raw_frames:
                if update(self.pose_cache,[r]):
                    boxes,centers=snapshot(self.program,self.records,self.zero,self.pose_cache);frames.append({'pose_boxes':boxes,'pose_centers':centers})
        if len(frames)!=len(requests):raise ValueError('Incomplete SolidCraft native poses')
        prepared=[];distance_commands=[];owners=[]
        for number,((phase,u,width),frame) in enumerate(zip(requests,frames)):
            if self.pose_cache is None:
                by_name={v['name']:v for v in frame['bodies']}
                if set(by_name)!=self.expected_names:raise ValueError('Native body completeness changed')
                semantic={r['id']:aggregate(by_name,r['names']) for r in self.records};boxes={n:v['bbox'] for n,v in semantic.items()}
                centers={name:[(a+b)/2 for a,b in zip(by_name[name]['bbox']['min'],by_name[name]['bbox']['max'])]
                         for name in [p['id'] for p in model.probes(self.program)]+['ToolMount']}
            else:boxes=frame['pose_boxes'];centers=frame['pose_centers'];semantic={}
            distances={};candidates=[]
            fk_error=model.probe_error(self.program,self.program.state(phase,u),centers,self.records)
            # Use the very same conservative enclosure test as certify().
            # A native distance is needed only when boxes cannot discharge it.
            guard=self.program.definition['continuous_audit']['numeric_guard_mm']
            radii={r['id']:self.program.delta(phase,u-width/2,u+width/2,r) for r in self.records} if width<=1/16 else {}
            for pair in self.pairs:
                if width>1/16 or model.bbox_distance(boxes[pair['a']],boxes[pair['b']])>=max(5,max(self.program.definition['clearance_mm'].values())+1):continue
                excursion=radii[pair['a']]+radii[pair['b']]+guard+2*fk_error
                lower=max(0,model.bbox_distance(boxes[pair['a']],boxes[pair['b']])-guard)
                if lower-excursion<pair['required_mm']:
                    bound=getattr(self.program,'pair_bound',lambda *args:None)(pair,phase,u-width/2,u+width/2,{})
                    if bound is None:candidates.append(pair)
            if candidates:
                distance_commands+=drive(self.program,phase,u)
                lookup={r['id']:r['names'] for r in self.records}
                for pair in candidates:
                    for a,b in itertools.product(lookup[pair['a']],lookup[pair['b']]):
                        distance_commands.append({'command':'inspect.measure','params':{'items':[{'type':'body','name':a},{'type':'body','name':b}]}})
                        owners.append((number,pair['a'],pair['b'],a,b))
            prepared.append({'boxes':boxes,'coarse_lower_bounds_only':width>1/16,'fk_error_mm':fk_error,'distances':distances,'geometry':semantic})
        raw=run(self.cli,distance_commands,self.directory,'distances-'+str(index),self.native,engine=self.engine) if distance_commands else []
        if self.pose_cache is not None:
            from h02_native_pose_boxes import update
            update(self.pose_cache,raw)
        values=[v for v in raw if isinstance(v,dict) and 'distance_mm' in v]
        if len(values)!=len(owners):raise ValueError('Incomplete native distances')
        for (number,x,y,a,b),value in zip(owners,values):
            if {v['name'] for v in value['items']}!={a,b}:raise ValueError('Foreign native distance result')
            distances=prepared[number]['distances'];distances[(x,y)]=min(distances.get((x,y),math.inf),value['distance_mm'])
        for frame in prepared:
            frame['distance']=lambda a,b,values=frame['distances'],boxes=frame['boxes']:values.get((a,b),model.bbox_distance(boxes[a],boxes[b]))
        print('SolidCraft continuous batch '+str(index)+' poses '+str(len(requests))+' exact native distances '+str(len(values)),flush=True)
        return prepared
