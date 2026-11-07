"""Shared L01 sample ownership, oriented IK and sampled transfer trajectory."""
from pathlib import Path
import json
import math
import lab_layout_model as layout
import robot_spec as robot
import centrifuge_model as cf
import sample_transport_model as tr

SOURCE=layout.ROOT/'model/lab-transfer-l01.protocol.json'


def load():
    s=json.loads(SOURCE.read_text(encoding='utf-8'))
    if s['format']!='solidcraftbot.lab-transfer/1' or s['units']!={'length':'mm','angle':'deg','time':'s'}: raise ValueError('Transfer contract/units')
    if s['sequence'][0]['duration_s']!=0 or any(x['duration_s']<=0 for x in s['sequence'][1:]): raise ValueError('Timeline duration')
    if s['sequence'][0]['sample_owner']!='TR01' or s['sequence'][-1]['sample_owner']!='TR01': raise ValueError('Roundtrip required')
    return s


def unit(v):
    n=math.sqrt(sum(x*x for x in v))
    return [x/n for x in v]


def direction(m,v): return [sum(m[i][j]*v[j] for j in range(3)) for i in range(3)]
def add(a,b,k=1): return [x+k*y for x,y in zip(a,b)]


def obb(matrix,minimum,maximum):
    center=robot.transform(matrix,[(a+b)/2 for a,b in zip(minimum,maximum)])
    half=[(b-a)/2 for a,b in zip(minimum,maximum)]
    axes=[[matrix[i][j] for i in range(3)] for j in range(3)]
    extent=[sum(abs(axes[j][i])*half[j] for j in range(3)) for i in range(3)]
    return {'center':center,'half':half,'axes':axes,'min':[c-e for c,e in zip(center,extent)],'max':[c+e for c,e in zip(center,extent)]}


def boxes_overlap(a,b):
    """Conservative separating-axis broad phase; no tessellation approximation."""
    if any(a['min'][i]>b['max'][i]+1e-8 or b['min'][i]>a['max'][i]+1e-8 for i in range(3)):return False
    dot=lambda x,y:sum(i*j for i,j in zip(x,y))
    delta=[x-y for x,y in zip(b['center'],a['center'])]
    r=[[dot(x,y) for y in b['axes']] for x in a['axes']];ar=[[abs(v)+1e-9 for v in row] for row in r]
    t=[dot(delta,x) for x in a['axes']];ah=a['half'];bh=b['half']
    for i in range(3):
        if abs(t[i])>ah[i]+sum(bh[j]*ar[i][j] for j in range(3)):return False
    for j in range(3):
        if abs(sum(t[i]*r[i][j] for i in range(3)))>bh[j]+sum(ah[i]*ar[i][j] for i in range(3)):return False
    for i in range(3):
        i1,i2=(i+1)%3,(i+2)%3
        for j in range(3):
            j1,j2=(j+1)%3,(j+2)%3
            if abs(t[i2]*r[i1][j]-t[i1]*r[i2][j])>ah[i1]*ar[i2][j]+ah[i2]*ar[i1][j]+bh[j1]*ar[i][j2]+bh[j2]*ar[i][j1]:return False
    return True


def data(s,ls):
    p=layout.parameters(ls); items={i['id']:i for i in ls['instances']}; arm=layout.instance_source(ls,items[s['arm']]); ap=robot.parameters(arm)
    cs=layout.instance_source(ls,items['CF01']);cp=cf.parameters(cs); ce=cf.expanded(cs,cp)
    base=layout.matrix(items[s['arm']],p); station=layout.matrix(items['CF01'],p)
    ts=layout.instance_source(ls,items['TR01']);tp=tr.parameters(ts);te=tr.expanded(ts,tp,layout.instance_variant(ts,items['TR01']))
    op=next(o for o in te['operations'] if o['body']==s['sample']['transporter_body'] and o['action']=='create')
    vehicle_bottom=robot.transform(layout.matrix(items['TR01'],p),op['shape']['origin'])
    bottom,axis=cf.pocket(cs,cp,s['sample']['centrifuge_slot']); cf_bottom=robot.transform(station,bottom); cf_axis=direction(station,axis)
    grip_height=cp['tube_length']+3.6+s['sample']['cap_grip_clearance_mm']
    targets={'vehicle_grip':(add(vehicle_bottom,[0,0,1],grip_height),[0,0,1]),
             'vehicle_clear':(add(vehicle_bottom,[0,0,1],grip_height+s['path']['vehicle_lift_mm']),[0,0,1]),
             'cf_seat':(add(cf_bottom,cf_axis,grip_height),cf_axis),
             'cf_pickup':(add(cf_bottom,cf_axis,grip_height+cp['lift_travel']),cf_axis),
             'cf_clear':(add(cf_bottom,cf_axis,grip_height+s['path']['cf_clearance_mm']),cf_axis),
             'transit':(s['path']['transit_tcp_mm'],[0,0,1]),
             'cf_pre':(s['path']['cf_pre_tcp_mm'],cf_axis),
             'cf_side':(s['path']['cf_side_tcp_mm'],cf_axis)}
    targets['cf_raised']=(add(targets['cf_clear'][0],[0,0,1],s['path']['cf_vertical_clearance_mm']),cf_axis)
    return dict(p=p,items=items,arm=arm,ap=ap,cs=cs,cp=cp,ce=ce,base=base,station=station,
                vehicle_bottom=vehicle_bottom,cf_bottom=cf_bottom,cf_axis=cf_axis,grip_height=grip_height,targets=targets)


def tcp(d,q,s):
    m=robot.multiply(d['base'],robot.forward(d['arm'],q)[d['arm']['flange_reference']['link']])
    pt=layout.xyz(d['arm']['flange_reference']['point'],d['ap']);pt[2]+=s['tool']['flange_standoff_mm']
    return robot.transform(m,pt),[-x for x in direction(m,[0,0,1])]


def oriented_solutions(d,s,point,tube_axis):
    """Analytic spherical-wrist IK; axial sample roll is intentionally free."""
    a=d['ap']; inv=robot.inverse(d['base']); target=robot.transform(inv,point)
    z=direction(inv,[-v for v in tube_axis]); flange_z=robot.evaluate(d['arm']['flange_reference']['point'][2],a)
    wrist=add(target,z,-(flange_z-a['wrist_z']+s['tool']['flange_standoff_mm']))
    rho=math.hypot(wrist[0],wrist[1]); height=wrist[2]-a['shoulder_z']; L=a['upper_len'];F=a['fore_len']
    cosine=(rho*rho+height*height-L*L-F*F)/(2*L*F)
    if not -1<=cosine<=1:return []
    result=[]
    for radius,az in [(rho,math.atan2(wrist[1],wrist[0])),(-rho,math.atan2(wrist[1],wrist[0])+math.pi)]:
        for sign in [1,-1]:
            elbow=sign*math.acos(cosine); shoulder=math.atan2(radius,height)-math.atan2(F*math.sin(elbow),L+F*math.cos(elbow))
            q0=[(math.degrees(az)+180)%360-180,math.degrees(shoulder),math.degrees(elbow),0,0,15]
            pre=robot.forward(d['arm'],q0)[d['arm']['joints'][2]['child']]
            local=direction(robot.inverse(pre),z); tilt=math.acos(max(-1,min(1,local[2])))
            for flip in [False,True]:
                roll=math.atan2(local[1],local[0])+(math.pi if flip else 0)
                q=q0[:3]+[(math.degrees(roll)+180)%360-180,math.degrees(tilt)*(-1 if flip else 1),15]
                if any(not j['limits_deg'][0]-1e-8<=v<=j['limits_deg'][1]+1e-8 for j,v in zip(d['arm']['joints'],q)):continue
                actual,axis=tcp(d,q,s);error=math.dist(actual,point);ae=math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(axis,tube_axis))))))
                if error<s['checks']['tcp_error_mm'] and ae<s['checks']['axis_error_deg']:
                    result.append({'q':q,'position_error_mm':error,'axis_error_deg':ae})
    return result


def sample_pose(d,s,owner,q,cfvalues):
    if owner=='arm':
        point,axis=tcp(d,q,s); return add(point,axis,-d['grip_height']),axis
    if owner=='TR01':return d['vehicle_bottom'][:],[0,0,1]
    return add(d['cf_bottom'],d['cf_axis'],cfvalues['TubeLift']),d['cf_axis'][:]


def compile(s,ls,choices=None):
    d=data(s,ls);poses={'park':d['items'][s['arm']]['joints_deg']}; errors={};previous=poses['park']
    for name in ['vehicle_clear','vehicle_grip','transit','cf_pre','cf_side','cf_raised','cf_clear','cf_seat','cf_pickup']:
        point,axis=d['targets'][name];candidates=oriented_solutions(d,s,point,axis)
        preference=s.get('ik_preference',{}).get(name,{})
        candidates=[c for c in candidates if all(c['q'][index]*preference[key]>=0 for key,index in [('wrist_pitch_sign',4),('elbow_sign',2)] if key in preference)]
        if not candidates:raise ValueError('No oriented solution: '+name+' '+str(point))
        candidates.sort(key=lambda c:sum((a-b)**2 for a,b in zip(c['q'],previous)))
        selected=candidates[(choices or {}).get(name,0)];poses[name]=selected['q'];errors[name]={k:v for k,v in selected.items() if k!='q'};previous=selected['q']
    keys=[];time=0;last=None
    for stage in s['sequence']:
        values=cf.pose(d['cs'],d['cp'],stage['station_pose'])
        cartesian=last and last['arm_pose']!=stage['arm_pose'] and any(
            {last['arm_pose'],stage['arm_pose']} <= group for group in
            [{'vehicle_clear','vehicle_grip'},{'cf_pre','cf_side','cf_raised','cf_clear','cf_seat','cf_pickup'}])
        count=math.ceil(math.dist(d['targets'][last['arm_pose']][0],d['targets'][stage['arm_pose']][0])/2) if cartesian else 1
        prior=last['q'] if last else poses['park']
        for index in range(1,count+1):
            u=index/count
            if cartesian:
                start,axis=d['targets'][last['arm_pose']];end=d['targets'][stage['arm_pose']][0]
                point=[a+(b-a)*u for a,b in zip(start,end)]
                candidates=oriented_solutions(d,s,point,axis)
                if not candidates:raise ValueError('Cartesian insertion not reachable: '+stage['id'])
                q=min(candidates,key=lambda c:sum((a-b)**2 for a,b in zip(prior,c['q'])))['q']
            else:q=poses[stage['arm_pose']]
            entry={**stage,'time_s':time+stage['duration_s']*u,'q':q,'cf':values}
            keys.append(entry);prior=q
        time+=stage['duration_s'];last=keys[-1]
    return {'format':'solidcraftbot.lab-transfer-timeline/1','duration_s':time,'poses':poses,'ik_errors':errors,'keyframes':keys,
            'layout_sha256':robot.digest(layout.SOURCE),'protocol_sha256':robot.digest(SOURCE),'units':s['units']}


def at_time(timeline,time,s,ls,d=None):
    keys=timeline['keyframes']; b=keys[-1];a=b;u=1
    for before,after in zip(keys,keys[1:]):
        if time<=after['time_s']:
            a,b=before,after;u=max(0,(time-a['time_s'])/(b['time_s']-a['time_s']));break
    q=[x+(y-x)*u for x,y in zip(a['q'],b['q'])];values={k:a['cf'][k]+(b['cf'][k]-a['cf'][k])*u for k in a['cf']}
    # The destination action describes who supports the sample during this leg.
    owner=b['sample_owner'];d=d or data(s,ls);bottom,axis=sample_pose(d,s,owner,q,values)
    return {'time_s':time,'phase':b['id'],'q':q,'cf':values,'sample_owner':owner,'sample_bottom':bottom,'sample_axis':axis}


def samples(timeline,s,ls):
    result=[];d=data(s,ls)
    for a,b in zip(timeline['keyframes'],timeline['keyframes'][1:]):
        n=max(1,math.ceil(max(abs(x-y) for x,y in zip(a['q'],b['q']))/s['checks']['max_joint_step_deg']),math.ceil(abs(b['cf']['Lid']-a['cf']['Lid'])/s['checks']['max_lid_step_deg']))
        while True:
            frames=[at_time(timeline,a['time_s']+(b['time_s']-a['time_s'])*i/n,s,ls,d) for i in range(n+1)]
            if max(math.dist(tcp(d,x['q'],s)[0],tcp(d,y['q'],s)[0]) for x,y in zip(frames,frames[1:]))<=s['checks']['max_tcp_step_mm']+1e-8:break
            n*=2
        result.extend(frames if not result else frames[1:])
    return result


if __name__=='__main__':
    s=load();ls=layout.load();t=compile(s,ls); print(json.dumps({'poses':t['poses'],'errors':t['ik_errors'],'samples':len(samples(t,s,ls))},indent=2))
