"""L01 shared equipment instances, primitive props, access corridors and IK screen."""
from pathlib import Path
import json
import math
import lab_room_model as room
import robot_spec as robot

ROOT=room.ROOT
SOURCE=ROOT/'model/lab-layout-l01.shared.json'
digest=robot.digest


def load(*, validate_builds=True):
    """Validate source bindings; native build evidence is optional for source-only tests."""
    s=json.loads(SOURCE.read_text(encoding='utf-8'))
    if s['format']!='solidcraftbot.lab-layout/1' or s['units']!={'length':'mm','angle':'deg'}: raise ValueError('Layout contract')
    for name,a in s['assets'].items():
        bindings=[('source','source_sha256')]
        if validate_builds: bindings.append(('native','native_sha256'))
        for key,hkey in bindings:
            if digest(ROOT/a[key])!=a[hkey]: raise ValueError('Pinned asset changed: '+name+' '+key)
        if not validate_builds: continue
        report=json.loads((ROOT/a['report']).read_text(encoding='utf-8'))
        if not report['passed']: raise ValueError('Upstream build not passed: '+name)
        if report.get('source_sha256',report.get('spec_sha256'))!=a['source_sha256']: raise ValueError('Upstream report/source mismatch: '+name)
    ids=[i['id'] for i in s['instances']]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate layout instance')
    if len([i for i in s['instances'] if i['asset']=='arm'])!=3: raise ValueError('Three arms required')
    return s


def parameters(s): return {**room.parameters(room.load()),**s['parameters']}
def xyz(values,p): return [robot.evaluate(v,p) for v in values]


def matrix(item,p):
    x,y,z=xyz(item['xyz'],p); a=math.radians(item['yaw_deg']); c=math.cos(a); q=math.sin(a)
    return [[c,-q,0,x],[q,c,0,y],[0,0,1,z],[0,0,0,1]]


def inverse_position_ik(s,instance,target):
    """Position-only planar 3-link screen of the actual arm flange reference."""
    p=parameters(s); arm=robot.load(ROOT/s['assets']['arm']['source']); ap=robot.parameters(arm)
    base=xyz(instance['xyz'],p); dx,dy,dz=[a-b for a,b in zip(target,base)]; rho=math.hypot(dx,dy)
    yaw=(math.degrees(math.atan2(dy,dx))-instance['yaw_deg']+180)%360-180
    l1=ap['upper_len']; l2=ap['fore_len']; l3=robot.evaluate(arm['flange_reference']['point'][2],ap)-ap['wrist_z']
    best=None
    for pitch in range(0,361,2):
        phi=math.radians(pitch); r=rho-l3*math.sin(phi); z=dz-ap['shoulder_z']-l3*math.cos(phi)
        cosine=(r*r+z*z-l1*l1-l2*l2)/(2*l1*l2)
        if not -1<=cosine<=1: continue
        for sign in [-1,1]:
            q3=sign*math.acos(cosine)
            q2=math.atan2(r,z)-math.atan2(l2*math.sin(q3),l1+l2*math.cos(q3))
            a2=math.degrees(q2); a3=math.degrees(q3); a5=pitch-a2-a3
            q=[yaw,a2,a3,0,a5,0]
            if any(not j['limits_deg'][0]<=v<=j['limits_deg'][1] for j,v in zip(arm['joints'],q)): continue
            local=robot.transform(robot.forward(arm,q)[arm['flange_reference']['link']],[robot.evaluate(v,ap) for v in arm['flange_reference']['point']])
            actual=robot.transform(matrix(instance,p),local); error=math.dist(actual,target)
            cost=error*1000+sum((a-b)**2 for a,b in zip(q,instance['joints_deg']))/10000
            if best is None or cost<best[0]: best=(cost,{'joint_angles_deg':q,'position_error_mm':error,'passed':error<0.01})
    return best[1] if best else {'passed':False,'reason':'No position-only solution within original joint limits'}


def reach_report(s):
    p=parameters(s); items={i['id']:i for i in s['instances']}; result=[]
    for target in s['reach_targets']:
        point=xyz(target['xyz'],p)
        for arm in target['arms']: result.append({'id':target['id'],'arm':arm,'target_mm':point,**inverse_position_ik(s,items[arm],point)})
    return result


def primitives(s):
    """New props reuse portable boxes/cuts; racks reuse the TR01 cassette."""
    p=parameters(s); groups=[]
    for arm in [i for i in s['instances'] if i['asset']=='arm']:
        x,y,z=xyz(arm['xyz'],p); h=robot.evaluate(arm.get('riser_height','arm_riser_h'),p)
        groups.append({'id':'Mount'+arm['id'],'host':arm['host'],'xyz':[x,y,z-h],'yaw_deg':arm['yaw_deg'],
            'color':{'ArmA':'#3e7897','ArmB':'#429780','ArmC':'#bd984b'}[arm['id']],
            'ops':[{'kind':'box','size':[180,160,h],'origin':[-90,-80,0],'action':'create'},
                   {'kind':'box','size':[180-2*p['riser_wall'],160-2*p['riser_wall'],h+2],'origin':[-90+p['riser_wall'],-80+p['riser_wall'],-1],'action':'cut'}]})
    return groups
