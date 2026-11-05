"""H03: one robot-turned camshaft, two roller cams, wedge collar and bayonet latch."""
from pathlib import Path
import ast
import copy
import json
import math
import sys
import robot_spec
import tube_carrier_model as portable
import tube_frame_model as frame

ROOT=frame.ROOT
SOURCE=ROOT/'model/tube-cam-h03.shared.json'
digest=robot_spec.digest
evaluate=robot_spec.evaluate


def load(path=SOURCE):
    own=json.loads(Path(path).read_text(encoding='utf-8'))
    if own['format']!='solidcraftbot.tube-cam/1': raise ValueError('Unsupported H03 format')
    base=ROOT/own['base_source']
    if digest(base)!=own['base_sha256']: raise ValueError('H02 base changed; review the H03 interface')
    spec=json.loads(base.read_text(encoding='utf-8'))
    spec['parameters'].update(own.pop('parameter_updates'))
    spec.update(own)
    p=parameters(spec)
    for s in samples(spec,p): protocol_check(spec,p,s['joint_values'])
    return spec


def parameters(spec,overrides=None):
    for name in overrides or {}:
        if name in spec['parameters'] and any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(spec['parameters'][name]['expression']),mode='eval'))):
            raise ValueError('Override the driving parameter instead of '+name)
    p=robot_spec.parameters(spec,overrides)
    for n,d in spec['parameters'].items():
        if d['unit'] not in ['mm','deg',''] or not d['range'][0]<=p[n]<=d['range'][1]: raise ValueError('Parameter range/unit: '+n)
    return p


def smooth(t): return t*t*t*(10-15*t+6*t*t)


def law(spec,p,track,angle,derivative=0):
    for a,b,x,y in spec['cam_tracks'][track]['segments']:
        if angle<=b+1e-9:
            x,y=evaluate(x,p),evaluate(y,p); t=max(0,min(1,(angle-a)/(b-a)))
            if derivative==1:return (y-x)*30*t*t*(1-t)*(1-t)/(b-a)*180/math.pi
            if derivative==2:return (y-x)*(60*t-180*t*t+120*t*t*t)/(b-a)**2*(180/math.pi)**2
            return x+(y-x)*smooth(t)
    return evaluate(spec['cam_tracks'][track]['segments'][-1][3],p) if not derivative else 0


def outline(spec,p,track):
    base=evaluate(spec['cam_tracks'][track]['base_radius'],p); r=p['roller_radius']; result=[]
    for angle in range(0,360,spec['cam_profile_step_deg']):
        t=math.radians(angle); R=base+r+law(spec,p,track,angle); d=law(spec,p,track,angle,1)
        x,z=-R*math.sin(t),R*math.cos(t)
        dx,dz=-d*math.sin(t)-R*math.cos(t),d*math.cos(t)-R*math.sin(t)
        norm=math.hypot(dx,dz); offset=r+p['profile_allowance']
        result.append([x-offset*dz/norm,z+offset*dx/norm])
    return result


def bolt_base(spec,p,angle):
    collar=min(p['collar_travel'],max(0,law(spec,p,'Closing',angle)-p['closing_take_up']))
    if angle<200:return max(1.2,min(4.2,25.2-2*collar))
    return 1.2*(1-smooth(max(0,min(1,(angle-200)/10))))


def values_at(spec,p,angle,carry=0,release=0,turn=0):
    result={}; returning=turn>=89.999
    for v in spec['variants']:
        tag=v['id']; push=law(spec,p,'Pusher',angle); close=law(spec,p,'Closing',angle)
        close_rise=p['closing_stroke']*smooth(max(0,min(1,(angle-130)/70)))
        collar=max(0,(close if returning else close_rise)-p['closing_take_up'])
        tube=max(0,push-p['contact_gap']) if returning else p['eject_travel']*smooth(max(0,min(1,(angle-30)/100)))
        for key,value in {'CamAngle':angle,'Pusher':push,'ClosingFollower':close,'Collar':collar,
                          'TubeLift':tube+carry,'ReceiverLift':carry,'JawL':p['jaw_open']*(1-collar/p['collar_travel']),
                          'JawR':p['jaw_open']*(1-collar/p['collar_travel']),
                          'LatchRetract':max(bolt_base(spec,p,angle),release),'BoltTurn':turn}.items():result[key+tag]=value
    return result


def pose(spec,p,name=None):
    name=name or spec['display_pose']
    states={'ready':(0,0,0,0),'contact':(30,0,0,0),'lifted':(130,0,0,0),
            'latched':(220,0,0,0),'supported':(360,0,0,0),'carried':(360,p['receiver_travel'],0,0),
            'release_pull':(210,0,4.5,0),'release_twist':(210,0,4.5,90),
            'return_open':(130,0,4.5,90),'returned':(0,0,4.5,90)}
    return values_at(spec,p,*states[name])


def protocol_check(spec,p,values):
    checks=[]
    for v in spec['variants']:
        tag=v['id']; q=lambda key:values[key+tag]
        supported=abs(q('TubeLift'))<1e-7 or abs(q('Pusher')-q('TubeLift')-p['contact_gap'])<1e-7 or (
            abs(q('JawL'))+abs(q('JawR'))<1e-7 and abs(q('TubeLift')-p['eject_travel']-q('ReceiverLift'))<1e-7)
        if not supported:raise ValueError('Unsupported tube: '+tag)
        if q('ReceiverLift')>1e-7 and (q('CamAngle')<320 or q('Pusher')>1e-7 or q('LatchRetract')>1e-7):
            raise ValueError('Receiver departure before completed capture/return: '+tag)
        if q('BoltTurn')>1e-7 and q('LatchRetract')<4.4:raise ValueError('Pull latch before twisting: '+tag)
        if q('CamAngle')>220 and q('BoltTurn')<89.999 and q('LatchRetract')>1e-7:
            raise ValueError('Latch required before cam return: '+tag)
        checks.append({'variant':tag,'supported':True,'latch_engaged':q('LatchRetract')<1e-7,'passed':True})
    return checks


def authorize_turn(spec,previous,next_angle,capture_confirmed):
    checkpoint=spec['phase_edges_deg']['capture_check']
    if previous<=checkpoint<next_angle and not capture_confirmed:raise ValueError('Verify tube capture and bolt engagement before cam return')
    return True


def samples(spec,p):
    angles=sorted(set(list(range(0,361,15))+[30,130,190,200,205,210,220,290,320]))
    result=[{'id':'transfer_'+str(a),'joint_values':values_at(spec,p,a)} for a in angles]
    result += [{'id':'carry_'+str(i),'joint_values':values_at(spec,p,360,p['receiver_travel']*i/4)} for i in range(1,5)]
    result += [{'id':'release_pull_'+str(i),'joint_values':values_at(spec,p,210,0,4.5*i/4)} for i in range(1,5)]
    result += [{'id':'release_twist_'+str(i),'joint_values':values_at(spec,p,210,0,4.5,90*i/4)} for i in range(1,5)]
    result += [{'id':'return_'+str(a),'joint_values':values_at(spec,p,a,0,4.5,90)} for a in [210,200,180,160,130,90,60,30,0]]
    for s in result:s['units']={k:('deg' if k.startswith(('CamAngle','BoltTurn')) else 'mm') for k in s['joint_values']}
    return result


def build_samples(spec,p):
    # Native cam links are probed separately with joint-value readback; avoid
    # replaying the complete protocol before the first inspectable file exists.
    return [{'id':'ready','joint_values':pose(spec,p,'ready')}]


def expanded(spec,p):
    out=frame.expanded(spec,p)
    removed={b['id'] for b in out['bodies'] if b['id'].endswith('PusherDriveEnvelope')}
    out['bodies']=[b for b in out['bodies'] if b['id'] not in removed]
    out['operations']=[o for o in out['operations'] if o['body'] not in removed]
    for v in spec['variants']:
        tag,cx=v['id'],v['center_x']; shaft='Camshaft'+tag; closer='ClosingFollower'+tag
        collar='ClosingCollar'+tag; latch='LatchSlide'+tag; bolt='LatchBolt'+tag; recv='Receiver'+tag
        out['components'] += [{'id':shaft,'grounded':False},{'id':closer,'grounded':False},
            {'id':collar,'grounded':False,'parent':recv},{'id':latch,'grounded':False,'parent':recv},
            {'id':bolt,'grounded':False,'parent':latch}]
        def body(name,component,color,role='structure',opacity=1):
            ident=tag+'_'+name;out['bodies'].append({'id':ident,'component':component,'role':role,'appearance':{'color':color,'opacity':opacity}});return ident
        def op(name,target,shape,action='create'):out['operations'].append({'id':tag+'_'+name,'body':target,'action':action,'shape':shape})
        def box(name,target,size,base,action='create'):
            op(name,target,{'kind':'box','size':size,'origin':[f'({cx})+({base[0]})',base[1],base[2]]},action)
        def cyl(name,target,radius,height,base,axis=[0,0,1],action='create',top=None):
            s={'kind':'cone' if top is not None else 'cylinder','radius':radius,'height':height,'origin':[f'({cx})+({base[0]})',base[1],base[2]],'axis':axis}
            if top is not None:s['top_radius']=top
            op(name,target,s,action)
        def prism(name,target,points,y,depth,action='create'):
            op(name,target,{'kind':'polygon_prism','plane':'XZ','offset':y,'points':[[f'({cx})+({x})',z] for x,z in points],'depth':depth,'fixed':True},action)
        def sector(name,target,start,end,x):
            # The far chord lies outside the sleeve: two radial planes remove
            # the exact angular window without faceting a circular cutter.
            radius=16
            points=[[21, 'receiver_guide_z+2.5']]+[[21+radius*math.cos(math.radians(a)),f'receiver_guide_z+2.5+({radius*math.sin(math.radians(a))})'] for a in [start,end]]
            op(name,target,{'kind':'polygon_prism','plane':'YZ','offset':f'({cx})+({x})','points':points,'depth':1.5,'fixed':True},'cut')
        # Replace the motor envelope by a shaft, cams and guided mechanical followers.
        for operation in out['operations']:
            if operation['id']==tag+'_Base':operation['shape'].update(size=[150,76,6],origin=[f'({cx})-75',-22,0])
            if operation['id']==tag+'_ReceiverRail':operation['shape']['size'][1]=3
            if operation['id']==tag+'_Pushrod':
                operation['shape'].update(height='tube_bottom_z-contact_gap-1-(cam_center_z+cam_base_radius+roller_radius)',
                    origin=[cx,0,'cam_center_z+cam_base_radius+roller_radius'])
        base=tag+'_DockBase'
        cyl('ClosingRodBaseBore',base,2.2,8,[0,27,-1],action='cut')
        for y in [0,38]:
            bearing=body('Bearing'+str(y),'DockFrame','#8194a5','camshaft_support')
            box('BearingBlock'+str(y),bearing,[16,8,16],[-8,y-4,'cam_center_z-8'])
            for sign in [-1,1]:box('BearingLeg'+str(y)+str(sign),bearing,[4,8,'-cam_center_z+8'],[-12 if sign<0 else 8,y-4,'cam_center_z-8'],'join')
            cyl('BearingBore'+str(y),bearing,4.1,10,[0,y-5,'cam_center_z'],[0,1,0],'cut')
        axle=body('Camshaft',shaft,'#b5bdc6','robot_turn_shaft')
        cyl('Axle',axle,3.5,66,[0,-22,'cam_center_z'],[0,1,0])
        coupling=body('RobotTurnLug',shaft,'#cf5c45','robot_turn_interface')
        box('TurnLug',coupling,[24,6,8],[-12,-28,'cam_center_z-4'])
        for x in [-7,7]:cyl('TurnLugHole'+str(x),coupling,1.6,8,[x,-29,'cam_center_z'],[0,1,0],'cut')
        for track,color in [('Pusher','#d59142'),('Closing','#5c9eaf')]:
            cam=body(track+'Cam',shaft,color,'cam_profile')
            points=[[x,f'cam_center_z+({z})'] for x,z in outline(spec,p,track)]
            prism(track+'CamProfile',cam,points,spec['cam_tracks'][track]['y'],6)
            comp='Ejector'+tag if track=='Pusher' else closer
            roller=body(track+'Roller',comp,'#e5ce5f','cam_roller')
            height='cam_center_z+'+spec['cam_tracks'][track]['base_radius']+'+roller_radius'
            y=15 if track=='Pusher' else 27
            cyl(track+'FollowerRoller',roller,'roller_radius',8,[0,y-4,height],[0,1,0])
            follower=body(track+'FollowerCarrier',comp,'#9fae93','cam_follower')
            if track=='Pusher':
                box('PusherOffset',follower,[4,19,4],[-2,-1,f'({height})-2'])
                cyl('PusherRollerPin',follower,1.2,8,[0,11,height],[0,1,0],'join')
            else:
                cyl('ClosingPushrod',follower,1.5,'receiver_guide_z+6-closing_take_up-('+height+')',[0,27,height])
                pinbody=body('ClosingFollowerRollerPin',comp,'#9fae93','cam_follower_pin')
                cyl('ClosingRollerPin',pinbody,1.2,8,[0,23,height],[0,1,0])
        # Closing collar: two inclined faces squeeze jaw rollers, with a rear latch stem.
        wedge=body('WedgeCollar',collar,'#73a67b','closing_wedge_collar')
        correction=2.5*math.sqrt(1+(p['jaw_open']/p['collar_travel'])**2)
        k=p['jaw_open']/p['collar_travel']; center=12+p['jaw_open']+correction
        box('WedgeTop',wedge,[74,6,4],[-37,15,'receiver_guide_z+4.8'])
        for sign in [-1,1]:
            low=center-16*k;high=center+4*k
            points=[[(low)*sign,'receiver_guide_z-14'],[(low+4)*sign,'receiver_guide_z-14'],
                    [(high+4)*sign,'receiver_guide_z+6'],[high*sign,'receiver_guide_z+6']]
            prism('WedgeArm'+str(sign),wedge,points,15,6,'join')
        box('WedgeInputPad',wedge,[6,15,4],[-3,18,'receiver_guide_z+6'],'join')
        box('LatchStem',wedge,[6,6,28],[33,18,'receiver_guide_z-14'],'join')
        box('LatchWindow',wedge,[6,8,7],[34.5,17,'receiver_guide_z-15'],'cut')
        for sign,comp in [(-1,'JawL'+tag),(1,'JawR'+tag)]:
            target=tag+'_ReceiverJaw'+('L' if sign<0 else 'R')
            box('JawRollerTab'+str(sign),target,[5,4,3],[-14 if sign<0 else 9,5,'receiver_guide_z+1'],'join')
            pin=body('WedgeRollerPin'+str(sign),comp,'#adb8c4','wedge_roller_pin')
            cyl('WedgePin'+str(sign),pin,0.8,16,[sign*12,7,'receiver_guide_z+2'],[0,1,0])
            roller=body('WedgeRoller'+str(sign),comp,'#e5ce5f','wedge_roller')
            cyl('WedgeFollower'+str(sign),roller,2.5,6,[sign*12,15,'receiver_guide_z+2'],[0,1,0])
        # Spring-bolt housing and positive pull/quarter-turn hold-open bayonet slots.
        housing=body('LatchHousing',recv,'#8093a4','latch_housing')
        cyl('LatchSleeve',housing,4.5,9,[47,21,'receiver_guide_z+2.5'],[1,0,0])
        cyl('LatchSpringBarrel',housing,6,18,[56,21,'receiver_guide_z+2.5'],[1,0,0],'join')
        cyl('LatchShaftBore',housing,1.8,29,[46,21,'receiver_guide_z+2.5'],[1,0,0],'cut')
        cyl('LatchSpringCavity',housing,4.5,15,[57,21,'receiver_guide_z+2.5'],[1,0,0],'cut')
        box('BayonetStraightSlots',housing,[6.3,12,1.8],[48.1,15,'receiver_guide_z+1.6'],'cut')
        for i,(a,b) in enumerate(spec['latch']['bayonet_sector_angles_deg']):sector('BayonetQuarterSlot'+str(i),housing,a,b,52.8)
        # A bracket is ahead of the moving collar plane, preserving its travel.
        bracket=body('LatchBracket',recv,'#8093a4','latch_support')
        box('LatchBracketArm',bracket,[31,3,5],[20,10,'receiver_guide_z+3'])
        box('LatchBracketEnd',bracket,[4,10,7],[47,12,'receiver_guide_z-1'],'join')
        cyl('LatchBracketClearance',bracket,4.7,6,[46,21,'receiver_guide_z+2.5'],[1,0,0],'cut')
        box('LatchBracketPinSlot',bracket,[6.3,12,1.8],[48.1,15,'receiver_guide_z+1.6'],'cut')
        latchbody=body('LatchBolt',bolt,'#cb667e','spring_bayonet_bolt')
        profile=spec['latch']['bolt_profile']
        op('LatchBoltProfile',latchbody,{'kind':'axis_revolved_profile','axis':profile['axis'],
            'axis_origin':[cx,spec['latch']['center_y_mm'],spec['latch']['center_z']],
            'points_ar':profile['points_ar_mm']})
        crosspin=body('LatchCrossPin',bolt,'#cb667e','bayonet_cross_pin')
        cyl('BayonetCrossPin',crosspin,0.6,10,[49,16,'receiver_guide_z+2.5'],[0,1,0])
        handle=body('LatchRobotHandle',bolt,'#cb667e','robot_release_handle')
        box('LatchRobotHandle',handle,[2,10,2],[78,16,'receiver_guide_z+1.5'])
        # New joints retain the H02 receiver and jaw hierarchy.
        for j in out['joints']:
            if j['id']=='Pusher'+tag:j['origin']=[cx,15,'cam_center_z+cam_base_radius+roller_radius']
        for name,child,parent,typ,axis,xref,origin,limit in [
            ('CamAngle',shaft,'DockFrame','revolute',[0,1,0],[1,0,0],[cx,15,'cam_center_z'],'cam_turn_limit'),
            ('ClosingFollower',closer,'DockFrame','slider',[0,0,1],[1,0,0],[cx,27,'cam_center_z+closing_base_radius+roller_radius'],'closing_stroke'),
            ('Collar',collar,recv,'slider',[0,0,1],[1,0,0],[cx,21,'receiver_guide_z'],'collar_travel'),
            ('LatchRetract',latch,recv,'slider',[1,0,0],[0,1,0],[f'({cx})+49',21,'receiver_guide_z+2.5'],'bolt_travel'),
            ('BoltTurn',bolt,latch,'revolute',[1,0,0],[0,1,0],[f'({cx})+49',21,'receiver_guide_z+2.5'],'release_turn_limit')]:
            out['joints'].append({'id':name+tag,'child':child,'parent':parent,'type':typ,'axis':axis,'reference_x':xref,
                'origin':origin,'limit_parameter':limit,('limits_deg' if typ=='revolute' else 'limits_mm'):[0,p[limit]]})
    out['model_spec']=spec;out['parameter_values']=p
    return out


def numeric_shape(shape,p):
    if shape['kind']=='axis_revolved_profile':
        s=copy.deepcopy(shape);s['axis_origin']=[evaluate(v,p) for v in s['axis_origin']]
        s['points_ar']=[[evaluate(v,p) for v in point] for point in s['points_ar']];return s
    if shape['kind']!='polygon_prism':return portable.numeric_shape(shape,p)
    s=copy.deepcopy(shape);s['offset']=evaluate(s['offset'],p);s['depth']=evaluate(s['depth'],p)
    s['points']=[[evaluate(v,p) for v in point] for point in s['points']];return s


def validate_pose(source,values):
    if set(values)!={j['id'] for j in source['joints']}:raise ValueError('Every joint required')
    for j in source['joints']:
        lo,hi=j.get('limits_mm',j.get('limits_deg'))
        if not lo-1e-7<=values[j['id']]<=hi+1e-7:raise ValueError('Joint limit '+j['id'])


def matrix(source,component,p,values):
    j=next((j for j in source['joints'] if j['child']==component),None)
    if not j:return robot_spec.identity()
    local=robot_spec.identity()
    if j['type']=='slider':
        for i,a in enumerate(j['axis']):local[i][3]=a*values[j['id']]
    else:
        angle=math.radians(values[j['id']]);c,s=math.cos(angle),math.sin(angle);a=j['axis'];o=[evaluate(x,p) for x in j['origin']]
        for i in range(3):
            for k in range(3):
                cross=((0,-a[2],a[1]),(a[2],0,-a[0]),(-a[1],a[0],0))[i][k]
                local[i][k]=(c if i==k else 0)+(1-c)*a[i]*a[k]+s*cross
            local[i][3]=o[i]-sum(local[i][k]*o[k] for k in range(3))
    return robot_spec.multiply(matrix(source,j['parent'],p,values),local)


def pose_change_point(source,component,point,p,before,after):
    ref=robot_spec.transform(robot_spec.inverse(matrix(source,component,p,before)),point)
    return robot_spec.transform(matrix(source,component,p,after),ref)


def skip_interference_pair(a,b):
    return any(set([a,b])==set([tag+'_'+track+'Cam',tag+'_'+track+suffix]) for tag in ['V15','V20'] for track in ['Pusher','Closing'] for suffix in ['Roller','FollowerCarrier','FollowerRollerPin'])


def check_interface_geometry(spec,p,geometry):return frame.check_interface_geometry(spec,p,geometry)
def optical_rays(spec,p):return frame.optical_rays(spec,p)
def analytic_checks(actual,spec,p):return []
def source_dependencies(spec):return [ROOT/spec['base_source'],Path(frame.__file__),ROOT/'scripts/build_tube_cam.py']


def binding_fields(spec,p,tag,style):
    """One expression graph, emitted as SolidCraft parameters or FreeCAD fields."""
    fc=style=='freecad';ref=lambda n:('Controller.' if fc else '')+n+tag
    fields=[]
    def add(name,unit,expression=None,value=0):fields.append({'name':name+tag,'unit':unit,'expression':expression,'value':value})
    cam=ref('CamAngle') if fc else ref('CamInput')
    carry=ref('ReceiverLift') if fc else ref('CarryInput')
    release=ref('ReleaseStroke') if fc else ref('ReleaseInput')
    turn=ref('BoltTurn') if fc else ref('BayonetInput')
    if fc:add('ReleaseStroke','mm',value=0)
    else:
        for name,unit in [('CamInput','deg'),('CarryInput','mm'),('ReleaseInput','mm'),('BayonetInput','deg')]:add(name,unit)
    for name,a,b in [('Contact',0,30),('Lift',30,130),('Close',130,200),('Snap',200,210),('PushBack',220,320),('CloseBack',220,290)]:
        q=ref('Q'+name)
        add('Q'+name,'',f'max(0{"," if not fc else ";"}min(1{"," if not fc else ";"}({cam}/(1 deg)-{a})/{b-a}))')
        add('S'+name,'',f'{q}*{q}*{q}*(10-15*{q}+6*{q}*{q})')
    sep=';' if fc else ','
    add('ReturnMode','',f'floor({turn}/(90 deg))')
    mode=ref('ReturnMode'); par=lambda n:('ModelParameters.'+n if fc else n)
    add('PushLaw','mm',f'{par("contact_gap")}*{ref("SContact")}+{par("eject_travel")}*{ref("SLift")}-{par("pusher_limit")}*{ref("SPushBack")}')
    add('CloseLaw','mm',f'{par("closing_stroke")}*({ref("SClose")}-{ref("SCloseBack")})')
    add('CollarLaw','mm',f'max(0 mm{sep}(1-{mode})*{par("closing_stroke")}*{ref("SClose")}+{mode}*{ref("CloseLaw")}-{par("closing_take_up")})')
    add('LatchRamp','mm',f'max(0 mm{sep}{ref("CloseLaw")}-{par("closing_take_up")})')
    add('TubeLaw','mm',f'(1-{mode})*{par("eject_travel")}*{ref("SLift")}+{mode}*max(0 mm{sep}{ref("PushLaw")}-{par("contact_gap")})+{carry}')
    # A third phase switch selects the pre-snap expression without an if().
    add('AfterClose','',f'floor(min(1{sep}{cam}/(200 deg)))')
    after=ref('AfterClose')
    add('BoltLaw','mm',f'max({release}{sep}(1-{after})*max(1.2 mm{sep}min(4.2 mm{sep}25.2 mm-2*{ref("LatchRamp")}))+{after}*1.2 mm*(1-{ref("SSnap")}))')
    if fc:
        for name,target in [('Pusher','PushLaw'),('ClosingFollower','CloseLaw'),('Collar','CollarLaw'),('TubeLift','TubeLaw'),('LatchRetract','BoltLaw')]:add(name,'mm',ref(target))
        for name in ['JawL','JawR']:add(name,'mm',f'{par("jaw_open")}*(1-{ref("CollarLaw")}/{par("collar_travel")})')
    return fields


def native_controller_fields(spec,p):return [f for v in spec['variants'] for f in binding_fields(spec,p,v['id'],'freecad')]


def control_inputs_from_pose(spec,p,values):
    result={}
    for v in spec['variants']:
        tag=v['id'];a=values['CamAngle'+tag]
        for key in ['CamAngle','ReceiverLift','BoltTurn']:result[key+tag]=values[key+tag]
        q=values['LatchRetract'+tag]
        result['ReleaseStroke'+tag]=q if q>bolt_base(spec,p,a)+1e-7 else 0
    return result


def native_parameters(spec,p):return [f for v in spec['variants'] for f in binding_fields(spec,p,v['id'],'solidcraft')]


def joint_expression(spec,p,joint):
    name=joint['id'];tag=name[-3:]
    for prefix,target in [('CamAngle','CamInput'),('TubeLift','TubeLaw'),('ReceiverLift','CarryInput'),('Collar','CollarLaw'),('LatchRetract','BoltLaw'),('BoltTurn','BayonetInput')]:
        if name==prefix+tag:return target+tag
    return None


def coupling_commands(spec,p):
    result=[]
    for v in spec['variants']:
        tag=v['id']
        result.append({'command':'component.move_sketches','params':{'sketches':[tag+'_'+track+'CamProfile_Sketch' for track in ['Pusher','Closing']],'component':'Camshaft'+tag}})
        for track,follower in [('Pusher','Pusher'),('Closing','ClosingFollower')]:
            result.append({'command':'joint.cam','params':{'a':'CamAngle'+tag,'b':follower+tag,
                'profile':{'sketch':tag+'_'+track+'CamProfile_Sketch'},'follower':'roller','radius':'roller_radius'}})
        for jaw in ['JawL','JawR']:
            result.append({'command':'joint.motion_link','params':{'a':'Collar'+tag,'b':jaw+tag,
                'ratio':-p['jaw_open']/p['collar_travel'],'offset':p['jaw_open']}})
    return result


def drive_commands(spec,p,values):
    changes={}
    inputs=control_inputs_from_pose(spec,p,values)
    for v in spec['variants']:
        tag=v['id']
        for param,field,unit in [('CamInput','CamAngle','deg'),('CarryInput','ReceiverLift','mm'),('ReleaseInput','ReleaseStroke','mm'),('BayonetInput','BoltTurn','deg')]:
            changes[param+tag]=str(inputs[field+tag])+' '+unit
    return [{'command':'parameters.change','params':{'changes':changes}}]


def solidcraft_commands(spec,p):return portable.solidcraft_commands(spec,p,provider=sys.modules[__name__])


def segment_distance(point,a,b):
    dx,dz=b[0]-a[0],b[1]-a[1];t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dz)/(dx*dx+dz*dz)))
    return math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dz)


def polygon_rectangle_clear(poly,rectangle):
    xmin,xmax,zmin,zmax=rectangle
    if any(xmin<x<xmax and zmin<z<zmax for x,z in poly):return False
    def inside(point):
        x,z=point;flag=False
        for a,b in zip(poly,poly[1:]+poly[:1]):
            if (a[1]>z)!=(b[1]>z) and x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0]:flag=not flag
        return flag
    corners=[[xmin,zmin],[xmax,zmin],[xmax,zmax],[xmin,zmax]]
    if any(inside(c) for c in corners):return False
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    for a,b in zip(poly,poly[1:]+poly[:1]):
        for c,d in zip(corners,corners[1:]+corners[:1]):
            if cross(a,b,c)*cross(a,b,d)<-1e-12 and cross(c,d,a)*cross(c,d,b)<-1e-12:return False
    return True


def geometry_checks(spec,p):
    result=[]
    for track in spec['cam_tracks']:
        contour=outline(spec,p,track);base=evaluate(spec['cam_tracks'][track]['base_radius'],p);clear=[];pressure=[];curvature=[];carrier_clear=[]
        for angle in range(361):
            t=math.radians(angle);R=base+p['roller_radius']+law(spec,p,track,angle);d=law(spec,p,track,angle,1);dd=law(spec,p,track,angle,2)
            point=[-R*math.sin(t),R*math.cos(t)]
            clear.append(min(segment_distance(point,a,b) for a,b in zip(contour,contour[1:]+contour[:1]))-p['roller_radius'])
            rotated=[[math.cos(t)*x+math.sin(t)*z,-math.sin(t)*x+math.cos(t)*z] for x,z in contour]
            bounds=(-2,2,R-2,R+2) if track=='Pusher' else (-1.5,1.5,R,500)
            carrier_clear.append(polygon_rectangle_clear(rotated,bounds))
            pressure.append(math.degrees(math.atan(abs(d)/R)))
            denominator=R*R+2*d*d-R*dd
            if denominator>0:curvature.append((R*R+d*d)**1.5/denominator)
        result.append({'track':track,'samples':361,'minimum_roller_gap_mm':min(clear),'maximum_roller_gap_mm':max(clear),
            'maximum_pressure_angle_deg':max(pressure),'minimum_positive_pitch_curvature_radius_mm':min(curvature),
            'follower_carrier_clear':all(carrier_clear),
            'passed':min(clear)>-1e-6 and max(clear)<0.09 and min(curvature)>p['roller_radius']+p['profile_allowance'] and all(carrier_clear)})
    return result


def render_plan(spec,p):
    cx=p['module_pitch']/2
    return [
        {'id':'mechanism','path':'cam-mechanism.png','pose':'latched','variant':'V20','width':1250,'height':1100,'hide_roles':['clearance_envelope'],
         'camera':{'target':[cx+10,10,2],'yaw':-0.7,'pitch':0.22,'distance':245,'fov':0}},
        {'id':'cams','path':'cam-profiles.png','pose':'ready','variant':'V20','width':1100,'height':900,
         'hide_roles':['clearance_envelope','open_optical_frame','lower_exterior_seat','tube_shape_reference','illustrative_fluid','receiver_carriage_envelope','split_receiver_seat_and_guide','closing_wedge_collar','latch_housing','latch_support','spring_bayonet_bolt','wedge_roller','wedge_roller_pin'],
         'camera':{'target':[cx,13,p['cam_center_z']+9],'yaw':-0.45,'pitch':0.12,'distance':155,'fov':0}},
        {'id':'latch','path':'cam-latch.png','pose':'latched','variant':'V20','width':1200,'height':800,
         'hide_roles':['clearance_envelope','cam_profile','camshaft_support','robot_turn_shaft','robot_turn_interface','cam_roller','cam_follower','external_bottom_pusher','open_optical_frame','lower_exterior_seat','structure'],
         'camera':{'target':[cx+28,17,p['receiver_guide_z']+8],'yaw':-0.9,'pitch':0.3,'distance':125,'fov':0}}
    ]
