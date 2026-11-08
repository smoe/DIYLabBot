"""Native SolidCraft scene recipes and frozen poses from the shared sources."""
import copy
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import robot_spec as robot
from solidcraft_vendor import replace_imports


def construction(scene,vendor_sections):
    station=cf.load();p=cf.parameters(station);source=cf.expanded(station,p)
    arm=pickup.arm_source(scene);expanded=robot.expanded(arm)
    arm_bodies=[{'id':op['body'],'group':link['id'],'role':op.get('role','concept_geometry')}
                for link in expanded['links'] for op in link['recipe'] if op['action']=='create']
    excluded={b['id'] for b in arm_bodies if b['role']=='viewing_cone'}
    arm_commands,aliases=replace_imports(robot.solidcraft_commands(arm),vendor_sections)
    commands=[]
    # The existing generators own all geometry. These review snapshots have
    # frozen source transforms, not a second set of native joint constraints.
    for original in cf.solidcraft_commands(station,p)+arm_commands:
        command=copy.deepcopy(original);name=command['command'];args=command['params']
        if name.startswith('joint.') or (name=='browser.visibility' and args.get('folder')=='joints'):continue
        if args.get('body_name') in excluded or args.get('body') in excluded:continue
        for field in ['bodies','targets']:
            if field in args:
                args[field]=[n for n in args[field] if n not in excluded]
                if not args[field]:break
        else:commands.append(command)
    def add(command,**params):commands.append({'command':command,'params':params})
    manifest=[{'id':b['id'],'group':b['component'],'names':[b['id']],'asset':'station'} for b in source['bodies']]
    for body in arm_bodies:
        if body['id'] in excluded:continue
        names=aliases.get(body['id'],[body['id']])
        for name in names:add('body.rename',body=name,name='Arm_'+name)
        manifest.append({'id':'Arm.'+body['id'],'group':'Arm.'+body['group'],
                         'names':['Arm_'+n for n in names],'asset':'arm','role':body['role']})
    parts=pickup.gripper_parts(scene,p)+pickup.rack_geometry(scene,p)['parts']
    parts.append({'id':'BenchSurface','group':'Scene','shape':{'kind':'box',
                  'origin':scene['bench_surface']['origin_mm'],'size':scene['bench_surface']['size_mm']}})
    for body in parts:
        name=body['id'].replace('.','_')
        for i,shape in enumerate([body['shape'],*body.get('cuts',[])]):
            args={'name':name+'_'+str(i),'operation':'cut' if i else 'new'}
            args.update({'targets':[name]} if i else {'body_name':name})
            if shape['kind']=='box':args.update(corner=shape['origin'],**dict(zip(['length','width','height'],shape['size'])))
            else:
                args.update(base=shape['origin'],axis=[0,0,1],radius=shape['radius'],height=shape['height'])
                if shape['kind']=='cone':args['top_radius']=shape['top_radius']
            add('solid.'+shape['kind'],**args)
        appearance=pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))['bench']['bodies'][0]['appearance'] if body['group']=='Scene' else {'color':'#61b99a' if body['group']=='Rack' else '#d5a03a','opacity':1}
        add('appearance.assign',bodies=[name],**appearance)
        manifest.append({'id':body['id'],'group':body['group'],'names':[name],'asset':'scene'})
    for group in sorted({b['group'] for b in parts}):
        add('component.create',name=group,parent='root',activate=False,grounded=True)
        add('component.move_bodies',component=group,bodies=[b['id'].replace('.','_') for b in parts if b['group']==group])
    names=[n for body in manifest for n in body['names']]
    if len(set(names))!=len(names):raise ValueError('Native scene body identity collision')
    return commands,manifest


def placements(scene,data,time_s):
    sample=pickup.interpolate(data['samples'],time_s)
    matrices=pickup.matrices(scene,data,sample)
    commands=[{'command':'occurrence.move','params':{'occurrence':group.removeprefix('Arm.')+':1',
                'space':'world','matrix':matrix,'move_grounded':True}} for group,matrix in matrices.items()]
    return commands,matrices
