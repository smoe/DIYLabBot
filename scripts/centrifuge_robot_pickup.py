"""Shared CF01/6R pickup scene, constrained IK and rigid tube handoff. No I/O."""
import json
import math
from pathlib import Path
import robot_spec as robot
import assembly_model as assembly
import synthetic_workspace as workspace
import rack_slots
import centrifuge_model as cf
import centrifuge_protocol as protocol

ROOT=cf.ROOT
SOURCE=ROOT/'model/centrifuge-cf01.robot-pickup.shared.json'


def validate(s):
    if s['format']!='solidcraftbot.centrifuge-robot-pickup/1':raise ValueError('Pickup scene contract required')
    assembly.validate_reference({'source':s['sources']['robot']})
    if s['sources']['centrifuge']!=str(cf.SOURCE.relative_to(ROOT)) or s['sources']['protocol']!=str(protocol.SOURCE.relative_to(ROOT)):
        raise ValueError('This pickup backend supports the shared CF01 station and protocol only')
    if s['gripper']['operation']!='parallel_tube_gripper_envelope':raise ValueError('Supported gripper operation required')
    times=[k['time_s'] for k in s['timeline']]
    if times[0]!=0 or any(a>=b for a,b in zip(times,times[1:])):raise ValueError('Strictly ordered pickup timeline required')
    spec=cf.load();p=cf.parameters(spec);checks=s['checks'];attach=next(k for k in s['timeline'] if k['tube_owner']=='gripper')
    if attach['time_s']!=checks['attachment_time_s'] or attach['jaw']!='closed' or attach['robot_pose']!='grasp':raise ValueError('Handoff requires closed gripper at the grasp pose')
    if not checks['attachment_time_s']<checks['extraction_time_s']<checks['robot_clear_confirmed_s']<=checks['closing_starts_s']:raise ValueError('Grasp, extraction, withdrawal and closure must stay ordered')
    carried=False;seated=False
    for a,b in zip(s['timeline'],s['timeline'][1:]):
        if a['tube_owner']=='gripper':carried=True
        if b['tube_owner']=='rack':
            if not carried or b['robot_pose']!='rack_seated' and not seated or not b.get('rack_seated'):raise ValueError('Rack handoff requires supported tube at seated pose')
            if not seated and (b['time_s']!=checks['rack_handoff_time_s'] or b['jaw']!='closed'):raise ValueError('Confirm rack support before releasing fingers')
            seated=True
        elif seated:raise ValueError('Tube stays supported in rack after release')
        elif carried and b['tube_owner']!='gripper':raise ValueError('Unsupported tube ownership change')
        before=cf.pose(spec,p,a['station_pose']);after=cf.pose(spec,p,b['station_pose'])
        if after['Lid']<before['Lid']:
            if a['time_s']<checks['robot_clear_confirmed_s'] or not a.get('workspace_clear') or not b.get('workspace_clear') or a['robot_pose']!='withdrawn' or b['robot_pose']!='withdrawn':raise ValueError('Lid closure requires confirmed withdrawn robot and tube')
        if a['robot_pose']!=b['robot_pose'] and a['time_s']<checks['robot_clear_confirmed_s'] and (before['Lid']!=105 or after['Lid']!=105):raise ValueError('Robot access requires fully open lid')
        if a['jaw']=='closed' and b['jaw']=='open' and (not a.get('rack_seated') or a['tube_owner']!='rack'):raise ValueError('Rack support must be confirmed before opening jaws')
    g=s['gripper']
    if s['arm_fixture']['position_mm'][2]!=0 or s['arm_fixture']['mounting']!='direct_to_bench':raise ValueError('Direct bench mounting required; no riser')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in [g['flange_to_grip_mm'],g['open_gap_mm'],*g['body_size_mm'],*g['finger_stem_size_mm'],*g['finger_pad_size_mm']]):raise ValueError('Positive finite gripper dimensions required')
    rack_geometry(s,p)  # Validate the semantic rack operation and its interfaces.
    if not checks['rack_handoff_time_s']<checks['release_complete_time_s']<=times[-1]:raise ValueError('Rack confirmation must precede release')
    return s


def load():return validate(workspace.materialize_scene(json.loads(SOURCE.read_text(encoding='utf-8'))))


def arm_source(scene):return robot.load(ROOT/scene['sources']['robot'],scene.get('robot_parameter_overrides_mm'))


def rack_geometry(scene,p):
    """Lower a bottom-supported rack with generous guide bores and conical entries."""
    r=scene['rack'];sx,sy=r['size_mm'];base=r['base_thickness_mm'];low=r['guide_bottom_mm'];thick=r['guide_thickness_mm'];rail=r['rail_width_mm']
    if r['operation']!='guided_tube_rack':raise ValueError('Unsupported rack operation')
    if any(type(r[n]) is not int or r[n]<1 for n in ['rows','columns','selected_slot']):raise ValueError('Positive rack counts/slot required')
    if r['selected_slot']>r['rows']*r['columns']:raise ValueError('Rack slot outside capacity')
    dims=[sx,sy,base,low,thick,rail,r['pitch_mm'],r['bore_radius_mm'],r['entry_radius_mm'],r['entry_depth_mm']]
    if any(not math.isfinite(v) or v<=0 for v in dims):raise ValueError('Positive finite rack dimensions required')
    if not base<low or r['entry_depth_mm']>thick or r['bore_radius_mm']<p['tube_radius']+scene['transport_requirement']['position_target_mm']+.2:raise ValueError('Rack support/entry/transport clearance invalid')
    if r['entry_radius_mm']<r['bore_radius_mm'] or min(sx-(r['columns']-1)*r['pitch_mm'],sy-(r['rows']-1)*r['pitch_mm'])/2<=r['entry_radius_mm']+rail:raise ValueError('Rack edge or rail clearance invalid')
    parts=[]
    def body(name,shape,role='rack_structure',cuts=None):parts.append({'id':'Rack.'+name,'group':'Rack','shape':shape,'cuts':cuts or [],'role':role})
    body('Base',{'kind':'box','origin':[-sx/2,-sy/2,0],'size':[sx,sy,base]})
    for sign,tag in [(-1,'Left'),(1,'Right')]:body(tag+'Rail',{'kind':'box','origin':[sign*(sx/2-rail/2)-rail/2,-sy/2,base],'size':[rail,sy,low-base]})
    slots=[];cuts=[];places=rack_slots.places(r)
    for row in range(r['rows']):
        for col in range(r['columns']):
            x=(col-(r['columns']-1)/2)*r['pitch_mm'];y=(row-(r['rows']-1)/2)*r['pitch_mm'];slot=row*r['columns']+col+1
            slots.append({**places[slot-1],'tube_bottom_mm':[x,y,base],'grip_mm':[x,y,base+p['tube_length']-8]})
            cuts.extend([{'kind':'cylinder','radius':r['bore_radius_mm'],'height':thick+2,'origin':[x,y,low-1]},
                {'kind':'cone','radius':r['bore_radius_mm'],'top_radius':r['entry_radius_mm'],'height':r['entry_depth_mm']+.01,'origin':[x,y,low+thick-r['entry_depth_mm']]}])
    body('Guide',{'kind':'box','origin':[-sx/2,-sy/2,low],'size':[sx,sy,thick]},cuts=cuts)
    body('OrientationKey',{'kind':'cylinder','radius':3,'height':2,'origin':[-sx/2+5,-sy/2+5,low+thick]},'rack_orientation_marker')
    return {'parts':parts,'slots':slots,'frame':placement(r['position_mm'],r['yaw_deg']),'capacity':len(slots)}


def tube_owner(scene,t):
    return 'station' if t<scene['checks']['attachment_time_s'] else 'gripper' if t<scene['checks']['rack_handoff_time_s'] else 'rack'


def placement(position,yaw):
    t=robot.identity();c=math.cos(math.radians(yaw));s=math.sin(math.radians(yaw))
    t[0][:2]=[c,-s];t[1][:2]=[s,c]
    for i in range(3):t[i][3]=position[i]
    return t


def solve_linear(a,b):
    a=[list(row)+[v] for row,v in zip(a,b)];n=len(b)
    for k in range(n):
        pivot=max(range(k,n),key=lambda i:abs(a[i][k]));a[k],a[pivot]=a[pivot],a[k]
        if abs(a[k][k])<1e-14:raise ValueError('Singular IK step')
        d=a[k][k];a[k]=[v/d for v in a[k]]
        for i in range(n):
            if i==k:continue
            d=a[i][k];a[i]=[v-d*w for v,w in zip(a[i],a[k])]
    return [row[-1] for row in a]


class Kinematics:
    def __init__(self,source,scene):
        self.arm=source;self.p=robot.parameters(source);self.base=placement(scene['arm_fixture']['position_mm'],scene['arm_fixture']['yaw_deg'])
        self.frames=[robot.frame(j,self.p) for j in source['joints']]
        self.limits=[j['limits_deg'] for j in source['joints']]
        self.flange=[robot.evaluate(v,self.p) for v in source['flange_reference']['point']]
        self.length=scene['gripper']['flange_to_grip_mm']
    def forward(self,q):
        return {link:robot.multiply(self.base,frame) for link,frame in robot.forward(self.arm,q).items()}
    def tool(self,q):
        t=[row[:] for row in self.forward(q)[self.arm['flange_reference']['link']]]
        tip=robot.transform(t,[self.flange[0],self.flange[1],self.flange[2]+self.length])
        for i in range(3):t[i][3]=tip[i]
        return t
    def residual(self,q,target):
        current=self.tool(q);r=robot.multiply(target,robot.inverse(current))
        # Robust SO(3) logarithm, including large initial orientation errors.
        trace=sum(r[i][i] for i in range(3));angle=math.acos(max(-1,min(1,(trace-1)/2)))
        axis=[r[2][1]-r[1][2],r[0][2]-r[2][0],r[1][0]-r[0][1]];length=math.sqrt(sum(v*v for v in axis))
        if length<1e-8 and angle>1:
            axis=[math.sqrt(max(0,(r[i][i]+1)/2)) for i in range(3)];length=math.sqrt(sum(v*v for v in axis))
        rot=[v*angle/max(length,1e-12) for v in axis]
        return [target[i][3]-current[i][3] for i in range(3)]+[v*100 for v in rot]
    def inverse(self,target,seed):
        best=None
        seeds=[seed,[40,60,90,0,70,0],[0,70,-90,0,90,0],[-80,50,100,0,60,90],[80,50,100,0,80,-90]]
        for start in seeds:
            q=[max(lo,min(hi,v)) for v,(lo,hi) in zip(start,self.limits)]
            for iteration in range(120):
                e=self.residual(q,target);norm=math.sqrt(sum(v*v for v in e))
                if best is None or norm<best[0]:best=(norm,q[:])
                if norm<0.001:return q
                cols=[]
                for i in range(6):
                    qq=q[:];qq[i]+=.02;ee=self.residual(qq,target);cols.append([(a-b)/.02 for a,b in zip(ee,e)])
                a=[[sum(v*w for v,w in zip(cols[i],cols[j]))+(0.08 if i==j else 0) for j in range(6)] for i in range(6)]
                delta=solve_linear(a,[-sum(v*w for v,w in zip(col,e)) for col in cols])
                factor=min(1,7/max(max(abs(v) for v in delta),1e-9));accepted=False
                for gain in [factor,factor*.5,factor*.2,factor*.05]:
                    candidate=[max(lo,min(hi,v+gain*d)) for v,d,(lo,hi) in zip(q,delta,self.limits)]
                    if sum(v*v for v in self.residual(candidate,target))<norm*norm:q=candidate;accepted=True;break
                if not accepted:break
        if best[0]>0.04:raise ValueError('No accurate constrained IK solution; residual='+str(best[0])+' q='+str(best[1]))
        return best[1]


def targets(scene,spec,p):
    bottom,axis=cf.pocket(spec,p,1);point=cf.plus(bottom,axis,p['tube_length']-8+p['lift_travel'])
    result={};rack=rack_geometry(scene,p)
    for name,definition in scene['poses'].items():
        if 'rack_slot' in definition:
            pos=robot.transform(rack['frame'],rack['slots'][definition['rack_slot']-1]['grip_mm']);pos[2]+=definition['above_seat_mm']
        elif 'position_mm' in definition:pos=definition['position_mm']
        else:pos=cf.plus(point,axis,definition['offset_along_tube_mm']) if 'offset_along_tube_mm' in definition else [a+b for a,b in zip(point,definition['offset_from_presented_grip_mm'])]
        result[name]=tool_target(pos,definition.get('tool_tilt_from_vertical_deg',spec['rotor']['tilt_from_vertical_deg']),scene['gripper'].get('roll_about_tube_deg',0))
    return result


def tool_target(position,tilt_deg,roll_deg=0):
    a=math.radians(tilt_deg);c=math.cos(a);s=math.sin(a)
    return robot.multiply([[1,0,0,position[0]],[0,-c,-s,position[1]],[0,s,-c,position[2]],[0,0,0,1]],placement([0,0,0],roll_deg))


def target_at(scene,spec,p,t,goals=None):
    goals=goals or targets(scene,spec,p);a,b,u=segment(scene['timeline'],t)
    ta,tb=goals[a['robot_pose']],goals[b['robot_pose']]
    aa=scene['poses'][a['robot_pose']].get('tool_tilt_from_vertical_deg',spec['rotor']['tilt_from_vertical_deg']);ab=scene['poses'][b['robot_pose']].get('tool_tilt_from_vertical_deg',spec['rotor']['tilt_from_vertical_deg'])
    return tool_target([ta[i][3]+u*(tb[i][3]-ta[i][3]) for i in range(3)],aa+u*(ab-aa),scene['gripper'].get('roll_about_tube_deg',0))


def segment(keys,t):
    index=next((k for k in range(1,len(keys)) if t<=keys[k]['time_s']),len(keys)-1)
    a,b=keys[index-1:index+1];return a,b,(t-a['time_s'])/(b['time_s']-a['time_s'])


def station_frames(scene,spec,p):
    keys=[]
    for k in scene['timeline']:
        values={**cf.pose(spec,p,k['station_pose']),**{n:cf.evaluate(v,p) for n,v in k.get('coordinates',{}).items()}}
        keys.append({'time_s':k['time_s'],'phase':k['phase'],'values':values})
    return keys


def gripper_parts(scene,p):
    """Portable box/cylinder intent, in the grip-center frame (+Z points at tube)."""
    g=scene['gripper'];l=g['flange_to_grip_mm'];bx,by,bz=g['body_size_mm'];sx,sy,sz=g['finger_stem_size_mm'];px,py,pz=g['finger_pad_size_mm'];offset=g.get('finger_stem_radial_offset_mm',px)
    return [
        {'id':'ToolMount','group':'Tool','shape':{'kind':'cylinder','radius':15,'height':6,'origin':[0,0,-l]},'role':'illustrative_gripper_mount'},
        {'id':'GripperBody','group':'Tool','shape':{'kind':'box','size':[bx,by,bz],'origin':[-bx/2,-by/2,-l+6]},'role':'illustrative_gripper_body'},
        {'id':'LeftFingerStem','group':'FingerLeft','shape':{'kind':'box','size':[sx,sy,sz],'origin':[-offset,-sy/2,g['finger_stem_start_mm']]},'role':'illustrative_gripper_finger'},
        {'id':'LeftFingerPad','group':'FingerLeft','shape':{'kind':'box','size':[px,py,pz],'origin':[-px,-py/2,g['finger_pad_start_mm']]},'role':'illustrative_gripper_pad'},
        {'id':'RightFingerStem','group':'FingerRight','shape':{'kind':'box','size':[sx,sy,sz],'origin':[offset-sx,-sy/2,g['finger_stem_start_mm']]},'role':'illustrative_gripper_finger'},
        {'id':'RightFingerPad','group':'FingerRight','shape':{'kind':'box','size':[px,py,pz],'origin':[0,-py/2,g['finger_pad_start_mm']]},'role':'illustrative_gripper_pad'}]


def trajectory(scene=None):
    scene=scene or load();spec=cf.load();p=cf.parameters(spec);arm=arm_source(scene)
    kin=Kinematics(arm,scene);goals=targets(scene,spec,p);keys=station_frames(scene,spec,p)
    duration=scene['timeline'][-1]['time_s'];dt=scene['checks']['sample_period_s'];count=round(duration/dt)
    seed=kin.inverse(goals['grasp'],scene['ik_seed_deg']);seed=kin.inverse(goals['withdrawn'],seed)
    result=[];max_error=0
    for i in range(count+1):
        t=i*dt;a,b,u=segment(scene['timeline'],t);target=target_at(scene,spec,p,t,goals)
        seed=kin.inverse(target,seed);error=kin.residual(seed,target);max_error=max(max_error,max(abs(v) for v in error[:3]))
        cf_values=protocol.at_time(keys,t)['values'];cf.validate_pose(cf.expanded(spec,p),cf_values)
        ga=scene['gripper']['open_gap_mm'] if a['jaw']=='open' else 2*p['tube_radius']
        gb=scene['gripper']['open_gap_mm'] if b['jaw']=='open' else 2*p['tube_radius']
        result.append({'time_s':t,'phase':a['phase'] if t==0 else b['phase'],'joints_deg':seed[:],
            'station':cf_values,'jaw_gap_mm':ga+u*(gb-ga),'tube_owner':tube_owner(scene,t),
            'workspace_clear':t>=scene['checks']['robot_clear_confirmed_s']})
    if any(max(abs(x-y) for x,y in zip(a['joints_deg'],b['joints_deg']))>10 for a,b in zip(result,result[1:])):raise ValueError('Discontinuous IK branch; revise grasp roll, path or seed before playback')
    return {'scene_sha256':robot.digest(SOURCE),'robot_sha256':robot.digest(ROOT/scene['sources']['robot']),
        'geometry_sha256':robot.digest(cf.SOURCE),'protocol_sha256':robot.digest(protocol.SOURCE),'samples':result,
        'robot_parameter_overrides_mm':scene.get('robot_parameter_overrides_mm',{}),
        'maximum_tip_position_error_mm':max_error,'duration_s':duration,'sample_period_s':dt,'limits_deg':kin.limits}


def interpolate(samples,t):
    t=max(0,min(samples[-1]['time_s'],t))
    for a,b in zip(samples,samples[1:]):
        if t<=b['time_s']:
            u=(t-a['time_s'])/(b['time_s']-a['time_s'])
            return {'time_s':t,'phase':b['phase'],'joints_deg':[x+(y-x)*u for x,y in zip(a['joints_deg'],b['joints_deg'])],
                'station':{k:a['station'][k]+(b['station'][k]-a['station'][k])*u for k in a['station']},
                'jaw_gap_mm':a['jaw_gap_mm']+(b['jaw_gap_mm']-a['jaw_gap_mm'])*u}
    return samples[-1]


def interpolation_audit(scene,data,step_s=1/32):
    """Numerical deviation of joint-interpolated playback from Cartesian intent."""
    spec=cf.load();p=cf.parameters(spec);goals=targets(scene,spec,p);kin=Kinematics(arm_source(scene),scene)
    position=0;orientation=0;worst_time=0;count=round(data['duration_s']/step_s)
    for i in range(count+1):
        t=data['duration_s']*i/count;sample=interpolate(data['samples'],t);e=kin.residual(sample['joints_deg'],target_at(scene,spec,p,t,goals))
        deviation=math.sqrt(sum(v*v for v in e[:3]));angle=math.degrees(math.sqrt(sum(v*v for v in e[3:]))/100)
        if deviation>position:position=deviation;worst_time=t
        orientation=max(orientation,angle)
    return {'passed':position<scene['transport_requirement']['position_target_mm'],'samples':count+1,'sample_period_s':data['duration_s']/count,
        'maximum_position_deviation_mm':position,'worst_position_time_s':worst_time,'maximum_orientation_deviation_deg':orientation,
        'scope':'Numerical interpolation of the conceptual path; excludes physical accuracy, sensing, compliance and dynamics'}


def rigid_from_cf(source,group,values):
    origin=cf.transform(source,group,[0,0,0],values);points=[cf.transform(source,group,p,values) for p in [[1,0,0],[0,1,0],[0,0,1]]]
    return [[points[j][i]-origin[i] for j in range(3)]+[origin[i]] for i in range(3)]+[[0,0,0,1]]


class SceneEvaluator:
    """Cache immutable source expansion; used identically by all playback/checks."""
    def __init__(self,scene,data):
        self.scene=scene;spec=cf.load();p=cf.parameters(spec);self.kin=Kinematics(arm_source(scene),scene)
        self.source=cf.expanded(spec,p);self.rack=rack_geometry(scene,p)['frame']
        attachment=interpolate(data['samples'],scene['checks']['attachment_time_s'])
        self.attachment=robot.multiply(robot.inverse(self.kin.tool(attachment['joints_deg'])),rigid_from_cf(self.source,'PresentedTube',attachment['station']))
        seated=interpolate(data['samples'],scene['checks']['rack_handoff_time_s'])
        self.seated_tube=robot.multiply(self.kin.tool(seated['joints_deg']),self.attachment)
    def __call__(self,sample):
        result={c['id']:rigid_from_cf(self.source,c['id'],sample['station']) for c in self.source['components']}
        result.update({'Arm.'+name:t for name,t in self.kin.forward(sample['joints_deg']).items()})
        tool=self.kin.tool(sample['joints_deg']);result['Tool']=tool
        result['FingerLeft']=robot.multiply(tool,placement([-sample['jaw_gap_mm']/2,0,0],0))
        result['FingerRight']=robot.multiply(tool,placement([sample['jaw_gap_mm']/2,0,0],0))
        owner=tube_owner(self.scene,sample['time_s'])
        if owner=='gripper':result['PresentedTube']=robot.multiply(tool,self.attachment)
        elif owner=='rack':result['PresentedTube']=self.seated_tube
        result['Rack']=self.rack;result['Scene']=robot.identity();return result


def matrices(scene,data,sample):return SceneEvaluator(scene,data)(sample)


def mock_transfer_trace():
    """Endpoint handshake audit, separate from illustrative continuous motion timing."""
    from centrifuge_control import Simulator,ControlError
    clock=[0.];sim=Simulator(clock=lambda:clock[0]);bridge=protocol.MockProtocol(sim);token=bridge.invoke('acquire',client_id='robot-pickup-preview')['token'];trace=[]
    def advance(t):
        while clock[0]+2<t:clock[0]+=2;bridge.invoke('heartbeat',token)
        clock[0]=t;bridge.invoke('heartbeat',token)
    def step(command,**args):
        motion=next(c for c in bridge.contract['commands'] if c['id']==command)['observable']
        result=bridge.begin(command,token,**args) if motion else bridge.invoke(command,token,**args)
        trace.append({'time_s':clock[0],'command':command,'status':protocol.state_si(sim.status())});return result
    step('index',slot=1);advance(11.5);step('open_lid');advance(14.5);step('present_tube');sim.robot_clear=False
    advance(21.5)
    try:step('confirm_removed',grasp_confirmed=True,tube_absent=False)
    except ControlError as error:trace.append({'time_s':clock[0],'blocked':'premature transfer','error':error.code})
    else:raise AssertionError('Tube absence must be confirmed')
    advance(24.5);step('confirm_removed',grasp_confirmed=True,tube_absent=True)
    for command in ('retract_lift','close_lid'):
        try:step(command)
        except ControlError as error:trace.append({'time_s':clock[0],'blocked':command,'error':error.code})
        else:raise AssertionError('Robot must withdraw first')
    advance(29.5);sim.robot_clear=True;advance(30.5);step('retract_lift');advance(41);step('close_lid');advance(42);step('release')
    return {'passed':True,'mode':'simulation_only','scope':'Discrete protocol endpoint confirmations, not physical sensor or continuous timing validation','trace':trace}

