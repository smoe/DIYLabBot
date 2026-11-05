"""Portable CF01 semantic recipe and its SolidCraft adapter. Units: mm, deg."""
import copy
import json
import math
from pathlib import Path
import robot_spec
import centrifuge_mechanisms as mechanisms

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/centrifuge-cf01.shared.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate

# Portable polygon glyphs, independent of an installed font. Outer loop then holes.
DIGITS = {
    '0': [[[0,0],[3,0],[3,5],[0,5]], [[1,1],[1,4],[2,4],[2,1]]],
    '1': [[[1,0],[2,0],[2,5],[1,5],[0,4],[0,3],[1,4]]],
    '2': [[[0,0],[3,0],[3,1],[1,1],[1,2],[3,2],[3,5],[0,5],[0,4],[2,4],[2,3],[0,3]]],
    '3': [[[0,0],[3,0],[3,5],[0,5],[0,4],[2,4],[2,3],[1,3],[1,2],[2,2],[2,1],[0,1]]],
    '4': [[[2,0],[3,0],[3,5],[2,5],[2,3],[1,3],[1,5],[0,5],[0,2],[2,2]]],
    '5': [[[0,0],[3,0],[3,3],[1,3],[1,4],[3,4],[3,5],[0,5],[0,2],[2,2],[2,1],[0,1]]],
    '6': [[[0,0],[3,0],[3,3],[1,3],[1,4],[3,4],[3,5],[0,5]], [[1,1],[1,2],[2,2],[2,1]]],
    '7': [[[2,0],[3,0],[3,5],[0,5],[0,4],[2,4]]],
    '8': [[[0,0],[3,0],[3,5],[0,5]], [[1,1],[1,2],[2,2],[2,1]], [[1,3],[1,4],[2,4],[2,3]]],
    '9': [[[0,0],[3,0],[3,5],[0,5],[0,2],[2,2],[2,1],[0,1]], [[1,3],[1,4],[2,4],[2,3]]]
}


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format'] != 'solidcraftbot.centrifuge/1': raise ValueError('CF01 format required')
    if spec['units'] != {'length':'mm','angle':'deg','time':'s','speed':'rpm','rcf':'x_g'}: raise ValueError('Explicit units required')
    if spec['rotor']['slots'] != 12: raise ValueError('Recipe v1 implements 12 pockets')
    if spec['rotor']['slot_1_angle_deg']!=-90 or spec['handling']['pickup_angle_deg']!=-90:
        raise ValueError('Recipe v1 places the pickup and slot 01 on station -Y')
    if not 20 <= spec['rotor']['tilt_from_vertical_deg'] <= 40: raise ValueError('Tilt outside concept range')
    if spec['handling']['strategy'] != 'index_closed_stop_open_then_axial_lift': raise ValueError('Unsupported handling strategy')
    if not 0 < spec['handling']['index_limit_rpm'] <= 2: raise ValueError('Slow indexing only')
    if spec['structure']['material']!='steel' or spec['structure']['containment_qualified'] is not False:
        raise ValueError('Owner-selected steel family, unqualified containment required')
    view=spec['presentation']
    if (type(view['opacity']) not in (int,float) or not 0<view['opacity']<=1 or
        not set(view['translucent_roles'])<={'steel_housing','steel_chamber_wall','steel_chamber_floor','steel_lid'}):
        raise ValueError('Supported enclosure roles and opacity in (0,1] required')
    if spec['mechanisms']['format']!='solidcraftbot.centrifuge-mechanisms/1': raise ValueError('Mechanism contract required')
    encoder=spec['services']['rotation']
    if spec['services']['format']!='solidcraftbot.centrifuge-services/1': raise ValueError('Unsupported services contract')
    if encoder['counts_per_revolution']!=encoder['lines_per_revolution']*encoder['quadrature_multiplier'] or encoder['quadrature_multiplier']!=4:
        raise ValueError('Consistent ABZ quadrature counts required')
    if spec['services']['power']['protective_earth_required'] is not True: raise ValueError('Steel chassis requires planned PE bonding')
    if not encoder_requirements(spec,parameters(spec))['bandwidth_requirement_sufficient']:
        raise ValueError('Counter bandwidth below encoder speed requirement and margin')
    return spec


def parameters(spec, overrides=None):
    p = robot_spec.parameters(spec, overrides)
    for key, value in p.items():
        if not spec['parameters'][key]['range'][0] <= value <= spec['parameters'][key]['range'][1]:
            raise ValueError('Outside exploration range: ' + key)
    if p['rotor_radius'] >= p['chamber_inner_radius'] or p['lid_z'] < p['chamber_top']+4: raise ValueError('Chamber/lid clearance')
    if 2*(p['chamber_inner_radius']+p['chamber_wall']+4)>min(p['base_width'],p['base_depth']): raise ValueError('Chamber outside base')
    if p['chamber_floor_z']+p['chamber_floor']>=p['rotor_bottom']: raise ValueError('Floor/rotor clearance')
    if not mechanisms.requirements(spec,p)['gravity_target_covers_case']: raise ValueError('Lid torque target below provisional gravity margin')
    return p


def rpm_for_rcf(rcf, radius_mm):
    if not all(type(v) in (int,float) and math.isfinite(v) and v > 0 for v in (rcf,radius_mm)):
        raise ValueError('Finite positive RCF and radius required')
    return math.sqrt(rcf / (1.118e-5 * radius_mm / 10))


def pocket(spec, p, slot):
    if type(slot) is not int or not 1 <= slot <= spec['rotor']['slots']: raise ValueError('Slot must be 1..12')
    theta = math.radians(spec['rotor']['slot_1_angle_deg'] + (slot-1)*360/spec['rotor']['slots'])
    tilt = math.radians(spec['rotor']['tilt_from_vertical_deg'])
    axis = [-math.cos(theta)*math.sin(tilt), -math.sin(theta)*math.sin(tilt), math.cos(tilt)]
    bottom = [p['bottom_radius']*math.cos(theta), p['bottom_radius']*math.sin(theta), p['mouth_z']-p['tube_length']*axis[2]]
    return bottom, axis


def plus(o, axis, distance): return [a+b*distance for a,b in zip(o,axis)]


def service_frames(spec,p):
    power=[evaluate(v,p) for v in spec['services']['power']['inlet_frame_mm']]
    return {'power_inlet':power,'encoder_ring':[0,0,p['encoder_z']],
            'encoder_readhead':[p['encoder_radius']+p['encoder_gap'],0,p['encoder_z']+3],
            'hinge':[0,p['chamber_inner_radius']+p['chamber_wall']+2,p['lid_z']+p['hinge_lift']]}


def encoder_requirements(spec,p):
    e=spec['services']['rotation']; rpm=rpm_for_rcf(spec['rotor']['target_rcf_x_g'],p['bottom_radius'])
    edge=e['required_speed_rating_rpm']*e['counts_per_revolution']/60
    return {'id':e['id'],'target_rpm':rpm,'resolution_deg':360/e['counts_per_revolution'],
            'target_channel_cycles_hz':rpm*e['lines_per_revolution']/60,'target_counter_edges_hz':rpm*e['counts_per_revolution']/60,
            'rating_counter_edges_hz':edge,'minimum_counter_hz_with_margin':edge*e['bandwidth_margin_factor'],
            'bandwidth_requirement_sufficient':e['counter_input_requirement_hz']>=edge*e['bandwidth_margin_factor'],
            'accuracy_verified':False,'hardware_selected':False}


def encoder_measurement(delta_count,interval_s,counts_per_rev=4096):
    if type(delta_count) is not int or abs(delta_count)>2**63-1 or type(counts_per_rev) is not int or counts_per_rev<=0:
        raise ValueError('Signed counter delta and positive integer counts/revolution required')
    if type(interval_s) not in (int,float) or not math.isfinite(interval_s) or interval_s<=0: raise ValueError('Positive finite interval in seconds required')
    return {'speed_rpm':delta_count*60/counts_per_rev/interval_s,'delta_angle_deg':delta_count*360/counts_per_rev,
            'standstill_confirmed':False}


def power_cord(spec,p):
    x,y,z=service_frames(spec,p)['power_inlet']; start=x+34; arc_start=start+14; r=p['power_cable_bend']; end_z=6
    theta=math.acos(1-(z-end_z)/(2*r)); dx=r*math.sin(theta); drop=r*(1-math.cos(theta))
    a=[arc_start,z]; b=[arc_start+dx,z-drop]; c=[arc_start+2*dx,end_z]
    mid1=[arc_start+r*math.sin(theta/2),z-r*(1-math.cos(theta/2))]
    mid2=[c[0]-r*math.sin(theta/2),end_z+r*(1-math.cos(theta/2))]
    return {'kind':'round_cable','origin':[start,y,z],'plane_origin':[0,y,0],'u_axis':[1,0,0],'v_axis':[0,0,1],
            'radius':p['power_cable_radius'],'centerline_bend_radius_mm':r,'start_tangent':[1,0,0],
            'centerline_length_mm':14+2*r*theta+48,
            'curves':[{'kind':'line','start':[start,z],'end':a},{'kind':'arc','start':a,'through':mid1,'end':b},
                      {'kind':'arc','start':b,'through':mid2,'end':c},{'kind':'line','start':c,'end':[c[0]+48,end_z]}]}


def expanded(spec, p):
    result = {'components': [{'id':'Frame','grounded':True}, {'id':'RotorGroup','grounded':False},
              {'id':'LidGroup','grounded':False}, {'id':'EjectorGroup','grounded':False}, {'id':'PresentedTube','grounded':False},
              *[{'id':g,'grounded':False} for g in ['BrakePadUpperGroup','BrakePadLowerGroup','LatchLeftGroup','LatchRightGroup']]],
              'bodies': [], 'operations': [], 'joints': []}
    def body(name, group, color, role='concept_geometry', opacity=1):
        if role in spec['presentation']['translucent_roles']: opacity=spec['presentation']['opacity']
        result['bodies'].append({'id':name,'component':group,'role':role,'material_family':'steel' if role.startswith('steel_') else None,'appearance':{'color':color,'opacity':opacity}})
        return name
    def op(name, target, kind, origin, action='create', **shape):
        result['operations'].append({'id':name,'body':target,'action':action,'shape':{'kind':kind,'origin':origin,**shape}})
    def cyl(name,target,r,h,o,action='create',axis=None): op(name,target,'cylinder',o,action,radius=r,height=h,axis=axis or [0,0,1])
    def box(name,target,size,o,action='create'): op(name,target,'box',o,action,size=size)
    w,d=p['base_width'],p['base_depth']; wall=p['base_wall']; r=p['chamber_inner_radius']+p['chamber_wall']; frames=service_frames(spec,p)
    base=body('BaseHousing','Frame','#c1c8ce','steel_housing')
    box('Housing',base,[w,d,p['base_height']],[-w/2,-d/2,0])
    box('ElectricalBay',base,[w-2*wall,d-2*wall,p['base_height']-wall-p['base_floor']],[-w/2+wall,-d/2+wall,p['base_floor']],'cut')
    cyl('ShaftThroughRoof',base,22,wall+2,[0,0,p['base_height']-wall-1],'cut')
    for index,(x,y) in enumerate([(-90,-90),(-90,90),(90,-90),(90,90)]):
        cyl('PostRoofClearance'+str(index),base,p['floor_support_radius']+0.5,wall+2,[x,y,p['base_height']-wall-1],'cut')
    px,py,pz=frames['power_inlet']; box('PowerEntryCutout',base,[wall+2,26,26],[px-wall-1,py-13,pz-13],'cut')
    chamber=body('ContainmentEnvelope','Frame','#87939e','steel_chamber_wall')
    floor_top=p['chamber_floor_z']+p['chamber_floor']
    cyl('ChamberOuter',chamber,r,p['chamber_top']-floor_top,[0,0,floor_top])
    cyl('ChamberInside',chamber,p['chamber_inner_radius'],p['chamber_top']-floor_top+2,[0,0,floor_top-1],'cut')
    floor=body('ChamberFloor','Frame','#87939e','steel_chamber_floor')
    cyl('FloorPlate',floor,r,p['chamber_floor'],[0,0,p['chamber_floor_z']]); cyl('ShaftThroughFloor',floor,10,p['chamber_floor']+2,[0,0,p['chamber_floor_z']-1],'cut')
    for index,(x,y) in enumerate([(-90,-90),(-90,90),(90,-90),(90,90)]):
        post=body('FloorSupport'+str(index),'Frame','#87939e','steel_floor_support')
        cyl('SupportPost'+str(index),post,p['floor_support_radius'],p['chamber_floor_z']-p['base_floor'],[x,y,p['base_floor']])
    # Power entry and a true round sweep, before the costly rotor booleans.
    inlet=body('PowerEntryModule','Frame','#26323d','power_entry_envelope')
    box('PowerModule',inlet,[15,24,24],[px-15,py-12,pz-12]); box('PowerFlange',inlet,[4,34,34],[px,py-17,pz-17],'join')
    rocker=body('PowerRocker','Frame','#b72d36','switch_envelope'); box('Rocker',rocker,[1.5,6,15],[px+4,py-14,pz-7.5])
    fuse=body('FuseDrawer','Frame','#62717b','fuse_envelope'); box('Fuse',fuse,[1.5,6,15],[px+4,py+8,pz-7.5])
    plug=body('CordCoupler','Frame','#202a33','cord_connector_envelope'); box('CordCouplerBody',plug,[20,18,20],[px+6,py-9,pz-10])
    relief=body('CordStrainRelief','Frame','#202a33','strain_relief_envelope'); cyl('Relief',relief,5,8,[px+26,py,pz],axis=[1,0,0])
    cord=body('PowerCord','Frame','#202a33','power_cable_envelope'); shape=power_cord(spec,p)
    result['operations'].append({'id':'PowerCordSweep','body':cord,'action':'create','shape':shape})
    earth=body('ProtectiveEarthStud','Frame','#c8aa49','earth_bond_envelope'); cyl('EarthStud',earth,3,8,[px-30,py,p['base_floor']])
    lead=body('ProtectiveEarthLead','Frame','#79b83b','earth_lead_envelope')
    a=[px-12,py,pz-10]; b=[px-30,py,p['base_floor']+8]; length=math.dist(a,b)
    cyl('EarthLead',lead,1.2,length,a,axis=[(v-u)/length for u,v in zip(a,b)])
    electronics=body('ControlElectronicsEnvelope','Frame','#326f65','isolated_control_and_drive_envelope')
    box('ControllerBay',electronics,[42,62,34],[72,-45,p['base_floor']+5])
    mechanisms.drive(spec,p,body,cyl,box)
    ring=body('EncoderTargetRing','RotorGroup','#b69855','balanced_encoder_target_envelope')
    cyl('EncoderRing',ring,p['encoder_radius'],6,frames['encoder_ring']); cyl('EncoderRingBore',ring,8,8,[0,0,p['encoder_z']-1],'cut')
    sensor=body('RotationSensor','Frame','#478fa0','encoder_readhead_envelope'); sx,sy,sz=frames['encoder_readhead']
    box('EncoderReadhead',sensor,[12,12,10],[sx,sy-6,sz-5])
    bracket=body('EncoderBracket','Frame','#87939e','steel_sensor_support')
    box('SensorPost',bracket,[4,16,sz-5-p['base_floor']],[sx+14,-8,p['base_floor']])
    box('SensorShelf',bracket,[18,16,3],[sx,-8,sz-8],'join')
    wire=body('EncoderSignalCable','Frame','#8462b0','sensor_signal_cable_envelope')
    a=[sx+12,0,sz]; b=[90,-45,36]; length=math.dist(a,b)
    cyl('SignalLead',wire,1.5,length,a,axis=[(v-u)/length for u,v in zip(a,b)])
    hub=body('DriveHub','RotorGroup','#748fa5'); cyl('Hub',hub,18,3,[0,0,p['rotor_bottom']-3])
    rotor=body('Rotor','RotorGroup','#244a66','unqualified_rotor')
    cyl('RotorBlank',rotor,p['rotor_radius'],p['rotor_top']-p['rotor_bottom'],[0,0,p['rotor_bottom']])
    for slot in range(1,spec['rotor']['slots']+1):
        tag=f'{slot:02d}'; bottom,axis=pocket(spec,p,slot)
        # Seat and ejector passage are deliberately separate semantic features.
        cyl('TubeBore'+tag,rotor,p['tube_radius']+0.3,p['tube_length']+12,plus(bottom,axis,-0.3),'cut',axis)
        cyl('EjectorPassage'+tag,rotor,1.8,31,plus(bottom,axis,-30),'cut',axis)
        group='PresentedTube' if slot==1 else 'RotorGroup'
        tube=body('Tube'+tag,group,'#a4dce0','illustrative_tube')
        op('TubeCone'+tag,tube,'cone',bottom,radius=1,top_radius=p['tube_radius'],height=12,axis=axis)
        cyl('TubeWall'+tag,tube,p['tube_radius'],p['tube_length']-12,plus(bottom,axis,12),'join',axis)
        cyl('TubeCollar'+tag,tube,7,2,plus(bottom,axis,p['tube_length']),'join',axis)
        cap=body('ClosedCap'+tag,group,'#59b5bf','closed_cap_envelope')
        cyl('Cap'+tag,cap,7,1.5,plus(bottom,axis,p['tube_length']+2.1),axis=axis)
        # Globally upright numbers: each stays readable in the reference top view.
        a=math.radians(-90+(slot-1)*30); center=[92*math.cos(a),92*math.sin(a),p['rotor_top']+0.15]
        for index,char in enumerate(tag):
            name=body('Number'+tag+'_'+str(index),'RotorGroup','#ffffff','surface_marking_visual_only')
            loops=[[[x*2,y*2] for x,y in loop] for loop in DIGITS[char]]
            op(name,name,'profile',[center[0]-7+index*8,center[1]-5,center[2]],loops=loops,u_axis=[1,0,0],v_axis=[0,1,0],depth=0.2)
    mark=body('HomeTriangle','RotorGroup','#ffd047','surface_marking_visual_only')
    op(mark,mark,'profile',[-10,-22,p['rotor_top']+0.15],loops=[[[0,12],[20,12],[10,-8]]],u_axis=[1,0,0],v_axis=[0,1,0],depth=0.2)
    mark=body('SecondarySquare','RotorGroup','#39d7e2','surface_marking_visual_only')
    box('Square',mark,[10,10,0.2],[21,-5,p['rotor_top']+0.15])
    lid=body('CommandLid','LidGroup','#aeb7c0','steel_lid')
    cyl('LidDisc',lid,r+4,p['lid_thickness'],[0,0,p['lid_z']])
    mechanisms.lid(spec,p,frames['hinge'],body,cyl,box)
    actuator=body('LiftActuatorEnvelope','Frame','#e9b047','actuator_envelope'); box('LiftDrive',actuator,[18,22,22],[-9,-108,floor_top+2])
    bottom,axis=pocket(spec,p,1)
    pin=body('RetractablePusher','EjectorGroup','#e9b047','ejector_contact_concept')
    cyl('Pusher',pin,1.2,16,plus(bottom,axis,-p['park_gap']-16),axis=axis)
    datum=body('StationDatumL','Frame','#202f40','custom_station_landmark')
    box('DatumLong',datum,[25,4,1],[-112,-125,p['base_height']]); box('DatumShort',datum,[4,20,1],[-112,-125,p['base_height']],'join')
    for i in range(3):
        dot=body('StationDot'+str(i),'Frame','#202f40','custom_station_landmark'); cyl('Dot'+str(i),dot,2,1,[-78+i*9,-123,p['base_height']])
    for i,char in enumerate('UMR'):
        name=body('UMR_'+char,'Frame','#0f2d4b','marking')
        op(name,name,'profile',[-29+i*22,-d/2-0.2,30],loops=[[[x*2.5,y*2.5] for x,y in loop] for loop in robot_spec.GLYPHS[char]],u_axis=[1,0,0],v_axis=[0,0,1],depth=0.8)
    result['joints']=[
        {'id':'Lid','type':'revolute','parent':'Frame','child':'LidGroup','origin':frames['hinge'],'axis':[-1,0,0],'reference_x':[0,1,0],'limits':[0,105],'unit':'deg'},
        {'id':'Rotor','type':'revolute','parent':'Frame','child':'RotorGroup','origin':[0,0,p['rotor_bottom']],'axis':[0,0,1],'reference_x':[1,0,0],'limits':[-360,360],'unit':'deg'},
        {'id':'Lift','type':'slider','parent':'Frame','child':'EjectorGroup','origin':bottom,'axis':axis,'reference_x':[1,0,0],'limits':[0,p['park_gap']+p['lift_travel']],'unit':'mm'},
        {'id':'TubeLift','type':'slider','parent':'RotorGroup','child':'PresentedTube','origin':bottom,'axis':axis,'reference_x':[1,0,0],'limits':[0,p['lift_travel']],'unit':'mm'},*mechanisms.joints(p)]
    return result


def pose(spec,p,name=None): return {k:evaluate(v,p) for k,v in spec['poses'][name or spec['display_pose']].items()}


def validate_pose(source,values):
    if set(values)!={j['id'] for j in source['joints']}: raise ValueError('Every mechanism coordinate required')
    for j in source['joints']:
        v=values[j['id']]
        if not math.isfinite(v) or not j['limits'][0]<=v<=j['limits'][1]: raise ValueError('Joint limit: '+j['id'])
    if abs(values['BrakeUpper']-values['BrakeLower'])>1e-9: raise ValueError('Paired brake pads must move together')
    if values['Lid']>0:
        travel=next(j['limits'][1] for j in source['joints'] if j['id']=='LatchLeft')
        if values['BrakeUpper']!=0 or values['LatchLeft']!=travel or values['LatchRight']!=travel:
            raise ValueError('Lid opening requires parked rotor brake and retracted locking pins')


def transform(source,component,point,values):
    joint=next((j for j in source['joints'] if j['child']==component),None)
    if joint is None: return point[:]
    axis=joint['axis']; value=values[joint['id']]
    if joint['type']=='slider': moved=plus(point,axis,value)
    else:
        v=[a-b for a,b in zip(point,joint['origin'])]; c=math.cos(math.radians(value)); s=math.sin(math.radians(value))
        cross=[axis[1]*v[2]-axis[2]*v[1],axis[2]*v[0]-axis[0]*v[2],axis[0]*v[1]-axis[1]*v[0]]; dot=sum(a*b for a,b in zip(axis,v))
        moved=[joint['origin'][i]+v[i]*c+cross[i]*s+axis[i]*dot*(1-c) for i in range(3)]
    return transform(source,joint['parent'],moved,values)


def samples(spec,p):
    result=[{'id':name,'values':pose(spec,p,name)} for name in spec['poses']]
    for angle in range(0,106,15): result.append({'id':'CF01.access.'+str(angle),'values':{**pose(spec,p,'lid_unlocked'),'Lid':angle}})
    for slot in range(1,13): result.append({'id':f'CF01.index.{slot:02d}','values':{**pose(spec,p,'ready_to_spin'),'Rotor':-(slot-1)*30}})
    for step in range(8):
        stroke=(p['park_gap']+p['lift_travel'])*step/7
        result.append({'id':'CF01.present.'+str(step),'values':{**pose(spec,p,'open'),'Lift':stroke,'TubeLift':max(0,stroke-p['park_gap'])}})
    for step in range(5):
        result.append({'id':'CF01.brake.'+str(step),'values':{**pose(spec,p,'closed'),'BrakeUpper':p['brake_clearance']*step/4,'BrakeLower':p['brake_clearance']*step/4}})
    for step in range(6):
        result.append({'id':'CF01.lid_lock.'+str(step),'values':{**pose(spec,p,'closed'),'LatchLeft':p['latch_travel']*step/5,'LatchRight':p['latch_travel']*step/5}})
    return result


def solidcraft_commands(spec,p):
    source=expanded(spec,p); commands=[]
    def add(command,**params): commands.append({'command':command,'params':params})
    add('document.metadata.set',values={'org.solidcraftbot.centrifuge':{'source':str(SOURCE.relative_to(ROOT)),'sha256':digest(SOURCE),'status':spec['status']}})
    for op in source['operations']:
        s=op['shape']; kind=s['kind']; args={'name':op['id'],'operation':'new' if op['action']=='create' else op['action']}
        if op['action']=='create': args['body_name']=op['body']
        else: args['targets']=[op['body']]
        if kind=='round_cable':
            path_name=op['id']+'_Path'; profile_name=op['id']+'_Section'; ids=[]; counts={'line':0,'arc':0}
            add('sketch.create',name=path_name,plane={'origin':s['plane_origin'],'x_dir':s['u_axis'],'y_dir':s['v_axis']})
            for curve in s['curves']:
                counts[curve['kind']]+=1; ids.append(('l' if curve['kind']=='line' else 'a')+str(counts[curve['kind']]))
                if curve['kind']=='line': add('sketch.line',points=[curve['start'],curve['end']],infer=False)
                else: add('sketch.arc.three_point',start=curve['start'],through=curve['through'],end=curve['end'])
            add('sketch.finish')
            add('sketch.create',name=profile_name,plane={'origin':s['origin'],'x_dir':[0,1,0],'y_dir':[0,0,1]})
            add('sketch.circle.center',center=[0,0],radius=s['radius']); add('sketch.finish')
            add('solid.sweep',sketch=profile_name,path_sketch=path_name,path=ids,orientation='perpendicular',**args)
        elif kind=='profile':
            add('sketch.create',name=op['id']+'_Profile',plane={'origin':s['origin'],'x_dir':s['u_axis'],'y_dir':s['v_axis']})
            for loop in s['loops']: add('sketch.line',points=loop,closed=True,infer=False)
            add('sketch.finish'); add('solid.extrude',distance=s['depth'],**args)
        elif kind=='box': add('solid.box',corner=s['origin'],**dict(zip(['length','width','height'],s['size'])),**args)
        else:
            params={'base':s['origin'],'axis':s['axis'],'radius':s['radius'],'height':s['height']}
            if kind=='cone': params['top_radius']=s['top_radius']
            add('solid.'+kind,**params,**args)
    for group in source['components']:
        add('component.create',name=group['id'],parent='root',activate=False,grounded=group['grounded'])
        add('component.move_bodies',component=group['id'],bodies=[b['id'] for b in source['bodies'] if b['component']==group['id']])
    steel=[b['id'] for b in source['bodies'] if b['material_family']=='steel']
    add('material.assign',bodies=steel,material='Steel')
    for b in source['bodies']: add('appearance.assign',bodies=[b['id']],**b['appearance'])
    for j in source['joints']:
        frame={'origin':j['origin'],'z':j['axis'],'x':j['reference_x']}
        add('joint.create',name=j['id'],type=j['type'],a={'occurrence':j['parent'],'frame':frame},b={'occurrence':j['child'],'frame':frame},flip=True,values=[0],limits=[j['limits']],quiet=True)
    for k,v in pose(spec,p).items(): add('joint.drive',joint=k,value=v,quiet=True)
    add('joint.solve'); add('browser.visibility',folder='joints',visible=False)
    return commands


def prepare():
    spec=load(); p=parameters(spec); stem='centrifuge-cf01-'+digest(SOURCE)[:12]; rev=stem; n=1
    while (ROOT/'cad/generated'/rev).exists(): n+=1; rev=stem+'-r'+str(n)
    cad=ROOT/'cad/generated'/rev; out=ROOT/'exports/generated'/rev
    cad.mkdir(parents=True); out.mkdir(parents=True)
    write(out/'commands.json',{'commands':solidcraft_commands(spec,p)})
    context={'revision':rev,'cad':str(cad),'out':str(out),'source_sha256':digest(SOURCE)}
    write(ROOT/'tmp/cf01-context.json',context)
    return context


def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__': print(json.dumps(prepare()))
