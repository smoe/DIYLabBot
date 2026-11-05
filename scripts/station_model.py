"""CAD-independent station source, primitive arithmetic and SolidCraft adapter."""
from pathlib import Path
import ast
import copy
import hashlib
import json
import math
import robot_spec

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'model/tube-station-c01.shared.json'


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path=SOURCE):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format']!='solidcraftbot.station/1': raise ValueError('Not a station source')
    if spec['units']['length']!='mm' or spec['units']['angle']!='deg': raise ValueError('Explicit mm/deg required')
    p=parameters(spec)
    for label in spec.get('markings',[]):
        scale=evaluate(label['height'],p)/10
        tracking=label.get('tracking',2)*scale
        width=len(label['text'])*6*scale+max(0,len(label['text'])-1)*tracking
        for i,char in enumerate(label['text']):
            if char not in robot_spec.GLYPHS: raise ValueError('Unsupported marking glyph: '+char)
            offset=i*(6*scale+tracking)-width/2
            location=['(%s) + (%s)'%(value,offset*axis) for value,axis in zip(label['origin'],label['u_axis'])]
            spec['bodies'].append({'id':label['id']+'_'+char+'_'+str(i),'component':label['component'],'role':'marking','appearance':label['appearance'],
                'geometry':{'type':'polygon_prism','origin':location,'u_axis':label['u_axis'],'v_axis':label['v_axis'],
                            'loops':[[[x*scale,y*scale] for x,y in loop] for loop in robot_spec.GLYPHS[char]],'depth':label['depth']}})
    groups={c['id'] for c in spec['components']}
    if len(groups)!=len(spec['components']) or sum(c['grounded'] for c in spec['components'])!=1: raise ValueError('Invalid component roots')
    names=[b['id'] for b in spec['bodies']]
    if len(set(names))!=len(names): raise ValueError('Duplicate bodies')
    if any(b['component'] not in groups for b in spec['bodies']): raise ValueError('Unknown component')
    if any(c['target'] not in names for c in spec['cuts']): raise ValueError('Unknown cut target')
    if len({c['target'] for c in spec['cuts']})!=len(spec['cuts']): raise ValueError('Analytic reference currently supports one cut per body')
    for j in spec['joints']:
        if j['parent']!='Frame' or j['child'] not in groups or j['type']!='revolute': raise ValueError('Version 1 uses independent rotations about Frame')
    for b in spec['bodies']+spec['cuts']: primitive(b['geometry'],p)
    for pose in spec['poses_deg'].values(): validate_pose(spec,pose)
    return spec


def parameters(spec,overrides=None):
    for name in overrides or {}:
        if name in spec['parameters'] and any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(spec['parameters'][name]['expression']),mode='eval'))):
            raise ValueError('Override the driving parameter instead of derived '+name)
    values=robot_spec.parameters(spec,overrides)
    for name,value in values.items():
        definition=spec['parameters'][name]
        lo,hi=definition['range']
        if definition['unit']!='mm' or not lo<=value<=hi: raise ValueError('Parameter outside declared range: '+name)
    return values


def evaluate(value,p): return robot_spec.evaluate(value,p)


def primitive(shape,p):
    s=copy.deepcopy(shape)
    s['origin']=[evaluate(v,p) for v in s['origin']]
    if s['type']=='box':
        s['size']=[evaluate(v,p) for v in s['size']]
        if min(s['size'])<=0: raise ValueError('Nonpositive box')
    elif s['type']=='cylinder':
        s['radius']=evaluate(s['radius'],p); s['height']=evaluate(s['height'],p)
        if s['radius']<=0 or s['height']<=0 or s['axis'] not in ([1,0,0],[0,1,0],[0,0,1]): raise ValueError('Unsupported cylinder')
    elif s['type']=='polygon_prism':
        s['depth']=evaluate(s['depth'],p)
        if s['depth']<=0 or not s['loops'] or any(len(loop)<3 for loop in s['loops']): raise ValueError('Invalid polygon prism')
        u,v=s['u_axis'],s['v_axis']
        if abs(sum(a*b for a,b in zip(u,v)))>1e-9 or any(abs(sum(a*a for a in axis)-1)>1e-9 for axis in [u,v]): raise ValueError('Orthonormal prism basis required')
    else: raise ValueError('Unsupported primitive')
    return s


def stats(s):
    o=s['origin']
    if s['type']=='box':
        return math.prod(s['size']),[a+b/2 for a,b in zip(o,s['size'])],{'min':o[:],'max':[a+b for a,b in zip(o,s['size'])]}
    if s['type']=='polygon_prism':
        area=0; moment=[0,0]
        for index,loop in enumerate(s['loops']):
            edges=list(zip(loop,loop[1:]+loop[:1]))
            cross=[a[0]*b[1]-b[0]*a[1] for a,b in edges]
            signed=sum(cross)/2
            centroid=[sum((a[i]+b[i])*c for (a,b),c in zip(edges,cross))/(6*signed) for i in range(2)]
            weight=abs(signed)*(1 if index==0 else -1)
            area+=weight
            moment=[m+weight*c for m,c in zip(moment,centroid)]
        if area<=0: raise ValueError('Nonpositive polygon area')
        u,v=s['u_axis'],s['v_axis']; n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        centroid=[o[i]+u[i]*moment[0]/area+v[i]*moment[1]/area+n[i]*s['depth']/2 for i in range(3)]
        points=[[o[i]+u[i]*x+v[i]*y+n[i]*depth for i in range(3)] for x,y in s['loops'][0] for depth in [0,s['depth']]]
        return area*s['depth'],centroid,{'min':[min(q[i] for q in points) for i in range(3)],'max':[max(q[i] for q in points) for i in range(3)]}
    axis=s['axis'].index(1); center=o[:]; center[axis]+=s['height']/2
    lo=[c-s['radius'] for c in o]; hi=[c+s['radius'] for c in o]
    lo[axis]=o[axis]; hi[axis]=o[axis]+s['height']
    return math.pi*s['radius']**2*s['height'],center,{'min':lo,'max':hi}


def removed_stats(target,tool):
    _,_,a=stats(target); _,_,b=stats(tool)
    lo=[max(x,y) for x,y in zip(a['min'],b['min'])]
    hi=[min(x,y) for x,y in zip(a['max'],b['max'])]
    if any(y<=x for x,y in zip(lo,hi)): return 0,[0,0,0]
    if target['type']==tool['type']=='box': return math.prod(y-x for x,y in zip(lo,hi)),[(x+y)/2 for x,y in zip(lo,hi)]
    if tool['type']!='cylinder': raise ValueError('Unsupported analytic cut')
    axis=tool['axis'].index(1); center=tool['origin'][:]; center[axis]=(lo[axis]+hi[axis])/2
    if target['type']=='box':
        if any(b['min'][i]<a['min'][i] or b['max'][i]>a['max'][i] for i in range(3) if i!=axis): raise ValueError('Partial radial cut unsupported')
    elif target['axis']!=tool['axis'] or any(abs(target['origin'][i]-tool['origin'][i])>1e-9 for i in range(3) if i!=axis) or tool['radius']>=target['radius']:
        raise ValueError('Only smaller coaxial cylindrical cuts supported')
    return math.pi*tool['radius']**2*(hi[axis]-lo[axis]),center


def references(spec,p):
    result=[]
    for body in spec['bodies']:
        s=primitive(body['geometry'],p); volume,center,bounds=stats(s)
        for cut in (c for c in spec['cuts'] if c['target']==body['id']):
            removed,com=removed_stats(s,primitive(cut['geometry'],p))
            center=[(volume*a-removed*b)/(volume-removed) for a,b in zip(center,com)]
            volume-=removed
        result.append({'body':body['id'],'component':body['component'],'volume_mm3':volume,'center_of_mass_mm':center,'bbox':bounds})
    return result


def validate_pose(spec,pose):
    if set(pose)!={j['id'] for j in spec['joints']}: raise ValueError('Pose must specify every joint')
    if any(not math.isfinite(pose[j['id']]) or not j['limits_deg'][0]<=pose[j['id']]<=j['limits_deg'][1] for j in spec['joints']): raise ValueError('Joint limit')


def transform(spec,component,point,p,pose):
    joint=next((j for j in spec['joints'] if j['child']==component),None)
    if joint is None: return point[:]
    origin=[evaluate(x,p) for x in joint['origin']]
    axis=joint['axis']; theta=math.radians(pose[joint['id']]); c,s=math.cos(theta),math.sin(theta)
    v=[x-y for x,y in zip(point,origin)]; dot=sum(x*y for x,y in zip(axis,v))
    cross=[axis[1]*v[2]-axis[2]*v[1],axis[2]*v[0]-axis[0]*v[2],axis[0]*v[1]-axis[1]*v[0]]
    return [origin[i]+v[i]*c+cross[i]*s+axis[i]*dot*(1-c) for i in range(3)]


def pose_samples(spec):
    result=[{'id':name,'angles_deg':pose} for name,pose in spec['poses_deg'].items()]
    for joint in spec['joints']:
        for angle in joint['limits_deg']:
            pose=dict(spec['poses_deg']['pipetting']); pose[joint['id']]=angle
            result.append({'id':joint['id']+'_'+str(angle),'angles_deg':pose})
    return result


def solidcraft_commands(spec,p,pose=None):
    commands=[]
    def add(command,**params): commands.append({'command':command,'params':params})
    def shape_args(shape):
        s=primitive(shape,p)
        if s['type']=='box': return {'corner':s['origin'],**dict(zip(['length','width','height'],s['size']))}
        return {'radius':s['radius'],'height':s['height'],'base':s['origin'],'axis':s['axis']}
    for body in spec['bodies']:
        if body['geometry']['type']=='polygon_prism':
            s=primitive(body['geometry'],p)
            add('sketch.create',name=body['id']+'_profile',plane={'origin':s['origin'],'x_dir':s['u_axis'],'y_dir':s['v_axis']})
            count=0
            for loop in s['loops']:
                add('sketch.line',points=loop,closed=True)
                count+=len(loop)
            add('sketch.constraint.fix',entities=['l'+str(i) for i in range(1,count+1)],fixed=True)
            add('sketch.finish')
            add('solid.extrude',distance=s['depth'],operation='new',name=body['id'],body_name=body['id'])
        else:
            add('solid.'+body['geometry']['type'],name=body['id'],body_name=body['id'],operation='new',**shape_args(body['geometry']))
        for cut in (c for c in spec['cuts'] if c['target']==body['id']):
            add('solid.'+cut['geometry']['type'],name=cut['id'],operation='cut',targets=[body['id']],**shape_args(cut['geometry']))
    for group in spec['components']:
        add('component.create',name=group['id'],parent='root',activate=False,grounded=group['grounded'])
        add('component.move_bodies',component=group['id'],bodies=[b['id'] for b in spec['bodies'] if b['component']==group['id']])
    for body in spec['bodies']: add('appearance.assign',bodies=[body['id']],**body['appearance'])
    for j in spec['joints']:
        frame={'origin':[evaluate(x,p) for x in j['origin']],'z':j['axis'],'x':j['reference_x']}
        add('joint.create',name=j['id'],type='revolute',a={'occurrence':j['parent'],'frame':frame},b={'occurrence':j['child'],'frame':frame},flip=True,values=[0],limits=[j['limits_deg']],quiet=True)
    for joint,value in (pose or spec['poses_deg']['pipetting']).items(): add('joint.drive',joint=joint,value=value,quiet=True)
    add('joint.solve'); add('browser.visibility',folder='joints',visible=False)
    return commands
