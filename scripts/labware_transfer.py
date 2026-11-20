"""Referenced labware-handling arm, supported carriers and planning-only transfers."""
import copy
import math

import pipetting_station as s
from centrifuge_robot_pickup import Kinematics, tool_target, rack_geometry

SOURCE = s.ROOT/'model/labware-transfer.shared.json'
PROTOCOL = s.ROOT/'model/pipetting-transfer-ps01.protocol.json'


def load(reference):
    layout = s.bound(reference)
    s.exact(layout, 'format id source arm_instance ports carriers park limitations', 'transfer layout')
    s.require(layout['format']=='solidcraftbot.pipetting-transfer-setup/1', 'Transfer setup contract required')
    spec = s.bound(layout['source'])
    s.exact(spec, 'format id units status recipe parameters sources jaws payloads qualification limitations', 'handling definition')
    s.require(spec['format']=='solidcraftbot.labware-transfer/1' and spec['units']=={'length':'mm','angle':'deg'}
              and spec['recipe']=='supported_carrier_and_parallel_jaw_gripper/1', 'Supported carrier/gripper definition required')
    s.require(spec['qualification']=={'physical_grasp_verified':False,'payload_retention_verified':False,
              'load_capacity_kg':None,'hardware_implemented':False,'motion_implemented':False}, 'Unqualified handling concept required')
    s.require(spec['jaws']=={'joint_type':'symmetric_prismatic','axis':[1,0,0],
              'closed_gap_parameter':'carrier_d','open_gap_parameter':'open_gap'}, 'Symmetric jaw contract required')
    expected={'plate96':{'operation':'referenced_plate','source':'plate'},
              'tip_box':{'operation':'unmeasured_tip_box_envelope','source':'tips','basis':'synthetic_design_envelope_not_article_dimensions'},
              'tube_rack':{'operation':'referenced_guided_rack','source':'rack'}}
    s.require(spec['payloads']==expected, 'Supported payload recipes required')
    s.exact(spec['sources'],'plate tips rack','handling source references')
    for ref in spec['sources'].values():s.bound(ref)
    parameters(spec)
    return layout, spec


def parameters(spec):
    names='carrier_w carrier_d foot_h base_t foot_size locator_t locator_h locator_clearance flange_to_grip mount_radius mount_t body_h body_d open_gap finger_t finger_d lip_depth lip_t approach_clearance dock_t dock_w dock_d box_w box_d box_h'.split()
    s.require(set(spec['parameters'])==set(names), 'Supported handling parameters required')
    p=s.robot.parameters(spec)
    for name,definition in spec['parameters'].items():
        s.exact(definition,'expression unit range','handling parameter')
        s.require(definition['unit']=='mm' and len(definition['range'])==2, 'Explicit mm parameter range required')
        s.number(p[name],positive=True)
        s.require(definition['range'][0]<=p[name]<=definition['range'][1], 'Handling parameter out of range')
    s.require(p['open_gap']-2*p['lip_depth']>p['carrier_d']+4, 'Open fingers must clear carrier support lips')
    s.require(p['lip_t']<p['foot_h'] and p['foot_size']*4<p['carrier_d'], 'Undergrip clearance required')
    s.require(p['flange_to_grip']-p['mount_t']-p['body_h']>p['base_t']+p['box_h']+10,
              'Gripper body must clear the box planning envelope')
    s.require(p['carrier_w']<=p['dock_w'] and p['carrier_d']<=p['dock_d'], 'Carrier must fit dock')
    return p


def seat_height(spec):
    p=parameters(spec)
    return p['foot_h']+p['base_t']


def bindings(layout):
    bound={}
    for item in layout['carriers']:
        s.exact(item,'id host payload','carrier instance')
        payload=item['payload']
        if payload.get('kind') in {'existing_labware','existing_tip_stock'}:
            s.exact(payload,'kind instance','existing payload reference')
            s.require(payload['instance'] not in bound, 'Payload cannot have two carriers')
            bound[payload['instance']]=item
    return bound


def carrier_parts(spec, size):
    p=parameters(spec);sx,sy=size[:2];w,d,h,t=p['carrier_w'],p['carrier_d'],p['foot_h'],p['base_t']
    gap,stop=p['locator_clearance'],p['locator_t']
    s.require(sx+2*(gap+stop)<w and sy+2*(gap+stop)<d, 'Payload does not fit carrier locators')
    parts=[s.part('Base',s.box([-w/2,-d/2,h],[w,d,t]),'#728b95')]
    f=p['foot_size']
    for i,(a,b) in enumerate([(-1,-1),(-1,1),(1,-1),(1,1)]):
        parts.append(s.part('Foot'+str(i),s.box([a*w*.36-f/2,b*d*.28-f/2,0],[f,f,h]),'#354955'))
        # Corner stops leave the middle of both long edges free for undergrip.
        x=a*(sx/2+gap+stop/2);y=b*(sy/2+gap+stop/2)
        parts.append(s.part('Locator'+str(i),s.box([x-stop/2,y-stop/2,h+t],[stop,stop,p['locator_h']]),'#d59c44'))
    return parts


def gripper_parts(spec, gap):
    p=parameters(spec)
    s.require(p['carrier_d']<=gap<=p['open_gap'], 'Jaw gap outside supported interval')
    length=p['flange_to_grip'];start=-length+p['mount_t']+p['body_h'];width=p['open_gap']+2*p['finger_t']+4
    parts=[s.part('Mount',s.cylinder([0,0,-length],p['mount_radius'],p['mount_t']),'#d8a041'),
           s.part('ActuatorEnvelope',s.box([-width/2,-p['body_d']/2,-length+p['mount_t']],
                                          [width,p['body_d'],p['body_h']]),'#446c81')]
    for sign,name in [(-1,'Left'),(1,'Right')]:
        x=sign*gap/2-(p['finger_t'] if sign<0 else 0)
        parts.append(s.part(name+'Finger',s.box([x,-p['finger_d']/2,start],
                    [p['finger_t'],p['finger_d'],-start+p['lip_t']]),'#a6b7c0'))
        lip_x=x if sign<0 else x-p['lip_depth']
        parts.append(s.part(name+'SupportLip',s.box([lip_x,-p['finger_d']/2,0],
                    [p['finger_t']+p['lip_depth'],p['finger_d'],p['lip_t']]),'#537b8c'))
    return parts


def grip_interface_report(spec):
    p=parameters(spec)
    return {'passed':True,'open_lip_clearance_per_side_mm':(p['open_gap']-2*p['lip_depth']-p['carrier_d'])/2,
            'support_overlap_per_side_mm':p['lip_depth'],'lip_to_dock_clearance_mm':p['foot_h']-p['lip_t'],
            'physical_grasp_verified':False,'scope':'Nominal carrier/gripper interface dimensions; no contact force or retention qualification.'}


def state(arm, item, q=None):
    links={name:s.robot.multiply(item['matrix'],frame) for name,frame in s.robot.forward(arm,q).items()}
    flange=s.robot.multiply(links[arm['flange_reference']['link']],s.workspace.pose(
        [s.robot.evaluate(v,s.robot.parameters(arm)) for v in arm['flange_reference']['point']],0))
    return {'world_links':links,'flange_matrix':flange}


def kinematics(context):
    handle=context['handling'];item=context['spatial']['devices'][handle['layout']['arm_instance']]
    base=item['matrix'];yaw=math.degrees(math.atan2(base[1][0],base[0][0]))
    return Kinematics(context['arms'][item['id']]['arm'],{'arm_fixture':{
        'position_mm':[base[i][3] for i in range(3)],'yaw_deg':yaw},
        'gripper':{'flange_to_grip_mm':parameters(handle['source'])['flange_to_grip']}})


def extend(context, layout, spec):
    p=parameters(spec);frames=copy.deepcopy(context['frames']);occupied={};carriers={}
    pad=s.parameters(context['station'])
    s.require(p['carrier_w']<=pad['bay_w'] and p['carrier_d']<=pad['bay_d'], 'Carrier exceeds deck pad')
    s.require(s.bound(spec['sources']['tips'])==context['tip_source'], 'One shared tip library required')
    original_tip_stocks={r['id']:r for r in context['tip_racks']}
    bench=s.numeric_shape(context['spatial']['bench']['operations'][0]['shape'],{})
    for port in layout['ports']:
        s.exact(port,'id host xyz yaw_deg','handling port')
        s.require(port['id'] not in frames and port['host']=='PS01.Worktop' and port['yaw_deg']==0, 'Unique unrotated worktop port required')
        s.require(len(port['xyz'])==3 and all(type(v) in (int,float) and math.isfinite(v) for v in port['xyz'])
                  and port['xyz'][2]==0, 'Finite worktop port position required')
        base=s.robot.multiply(context['spatial']['frames'][port['host']],s.workspace.pose(port['xyz'],port['yaw_deg']))
        for x in [-p['dock_w']/2,p['dock_w']/2]:
            for y in [-p['dock_d']/2,p['dock_d']/2]:
                corner=s.robot.transform(base,[x,y,0])
                s.require(all(bench['origin'][i]<=corner[i]<=bench['origin'][i]+bench['size'][i] for i in (0,1))
                          and abs(corner[2]-bench['origin'][2]-bench['size'][2])<1e-6, 'Handling dock must sit on reference bench')
        frames[port['id']]=s.robot.multiply(base,s.workspace.pose([0,0,p['dock_t']],0))
        context['groups'].append({'id':port['id'],'parts':[s.part('Dock',s.box([-p['dock_w']/2,-p['dock_d']/2,0],
                                    [p['dock_w'],p['dock_d'],p['dock_t']]),'#89a6b0')],'matrix':base})
    for item in layout['carriers']:
        s.exact(item,'id host payload','carrier instance')
        identity,host,payload=item['id'],item['host'],item['payload'];kind=payload.get('kind')
        s.require(identity not in carriers and host in frames and host not in occupied, 'Unique carrier and free known host required')
        extra=[];content={};size=None
        if kind=='existing_labware':
            definition=context['labware'].get(payload['instance']);s.require(definition is not None,'Unknown carried labware')
            s.require(context['setup']['assets'][definition['instance']['asset']]==spec['sources']['plate'], 'Carried plate must use the declared labware reference')
            s.require(definition['instance']['host']==host,'Carrier and labware host differ')
            size=definition['size_mm'];content={'labware_id':payload['instance'],'wells':list(definition['wells'])}
        elif kind in {'existing_tip_stock','tip_reserve'}:
            if kind=='existing_tip_stock':
                stock=original_tip_stocks.get(payload['instance']);s.require(stock is not None and stock['host']==host,'Unknown tip stock or carrier host mismatch')
                variant=stock['variant'];content={'tip_rack_id':stock['id'],'tip_ids':[v['tip_id'] for v in stock['slots'] if v['occupied']]}
            else:
                s.exact(payload,'kind variant occupancy','reserve tip box')
                s.require(payload['occupancy']=='full_synthetic_fixture','Explicit synthetic reserve occupancy required')
                variant=payload['variant'];content={'tip_rack_id':identity,'tip_ids':[identity+'.'+v for v in s.tips.slot_ids(context['tip_source'],variant)],'admitted_to_pipetting_stock':False}
            s.tips.parameters(context['tip_source'],variant)
            size=[p['box_w'],p['box_d'],p['box_h']]
            color={'tip_10_ul':'#e3b542','tip_200_ul':'#58a48e','tip_1000_ul':'#5b8fc8'}[variant]
            box=s.part('TipBoxPlanningEnvelope',s.box([-size[0]/2,-size[1]/2,seat_height(spec)],size),color,
                       role='unmeasured_box_envelope_not_manufacturer_geometry')
            box['appearance']['opacity']=.38;extra.append(box)
            content.update(variant=variant,geometry_qualified=False)
        elif kind=='guided_rack':
            s.exact(payload,'kind occupancy','empty rack')
            s.require(payload['occupancy']=='empty_synthetic_fixture','Only empty rack fixture supported')
            rack=s.bound(spec['sources']['rack']);size=[*rack['size_mm'],rack['guide_bottom_mm']+rack['guide_thickness_mm']]
            # Reuse the existing rack construction. No tubes are instantiated;
            # zero tube envelopes are used only for this empty-rack adapter.
            geometry=rack_geometry({'rack':{**rack,'selected_slot':1,'position_mm':[0,0,0],'yaw_deg':0},
                'transport_requirement':{'position_target_mm':0}}, {'tube_radius':0,'tube_length':0})
            for part in geometry['parts']:
                result=copy.deepcopy(part)
                for shape in [result['shape'],*result.get('cuts',[])]:shape['origin'][2]+=seat_height(spec)
                result['appearance']={'color':'#6c9ba9','opacity':1};extra.append(result)
            content={'rack_id':identity,'slots':[v['place_id'] for v in geometry['slots']],'occupancy':'empty_synthetic_fixture'}
        else:raise ValueError('Unsupported carrier payload')
        parts=carrier_parts(spec,size)+extra
        context['groups'].append({'id':identity,'parts':parts,'matrix':frames[host]})
        carriers[identity]={'id':identity,'host':host,'payload':payload,'content':content,'size_mm':size}
        occupied[host]=identity
    # Reservoirs and any other uncarried labware still occupy their deck slots.
    for definition in context['labware'].values():
        host=definition['instance']['host']
        if host not in occupied:occupied[host]='fixed:'+definition['instance']['id']
    arm_id=layout['arm_instance'];item=context['spatial']['devices'][arm_id]
    arm=s.assembly.load_instance(s.robot,item['source'],item.get('overrides'))
    context['arms'][arm_id]={'arm':arm}
    context['handling']={'source':spec,'layout':layout,'frames':frames,'carriers':carriers,'occupied':occupied}
    park=layout['park'];s.exact(park,'tcp_world_mm roll_deg jaw ik_seed_deg','handling park pose')
    s.require(park['jaw']=='open' and park['roll_deg']==90,'Open gripper and fixed carrier orientation required')
    kin=kinematics(context);target=tool_target(park['tcp_world_mm'],0,park['roll_deg'])
    q=kin.inverse(target,park['ik_seed_deg']);arm_state=state(arm,item,q)
    context['arms'][arm_id].update(state=arm_state,joints_deg=q)
    context['groups'].append({'id':'LabwareGripper','parts':gripper_parts(spec,p['open_gap']),'matrix':kin.tool(q)})
    context['handling']['park_residual']=kin.residual(q,target)
    return context


def endpoint_report(context):
    h=context['handling'];p=parameters(h['source']);kin=kinematics(context);park=h['layout']['park']
    seed=context['arms'][h['layout']['arm_instance']]['joints_deg'];checks=[]
    for identity,frame in h['frames'].items():
        for tag,height in [('grasp',0),('above',p['approach_clearance'])]:
            point=s.robot.transform(frame,[0,0,p['foot_h']+height]);target=tool_target(point,0,park['roll_deg'])
            q=kin.inverse(target,seed);residual=kin.residual(q,target);seed=q
            checks.append({'host':identity,'pose':tag,'tcp_world_mm':point,'joints_deg':q,
                           'position_error_mm':math.sqrt(sum(v*v for v in residual[:3])),
                           'rotation_error_rad':math.sqrt(sum(v*v for v in residual[3:]))/100})
    return {'passed':all(v['position_error_mm']<.04 and v['rotation_error_rad']<.0004 for v in checks),
            'checks':checks,'scope':'Constrained IK at discrete grasp/above endpoints only; not a connected, collision-free or timed trajectory.'}


def plan(context, path=PROTOCOL):
    protocol=s.read(path)
    s.exact(protocol,'format id mode setup coordination steps limitations','handling protocol')
    s.require(protocol['format']=='solidcraftbot.pipetting-transfer-protocol/1' and protocol['mode']=='planning_only','Planning-only handling contract required')
    s.require(s.bound(protocol['setup'])==context['setup'],'Handling protocol setup mismatch')
    coordination=protocol['coordination']
    s.exact(coordination,'shared_zone transport_requires pipetting_requires release_requires','arm coordination')
    s.require(coordination=={'shared_zone':'PS01.Deck',
        'transport_requires':['pipetting_arm_parked_and_clear_confirmed','no_active_liquid_transfer_confirmed','shared_zone_exclusive_claim_confirmed'],
        'pipetting_requires':['transfer_arm_parked_and_clear_confirmed','all_labware_seated_and_identified_confirmed'],
        'release_requires':['payload_seated_confirmed','gripper_empty_confirmed','transfer_arm_parked_and_clear_confirmed']},'Explicit mutual-exclusion feedback contract required')
    h=context['handling'];occupied=copy.deepcopy(h['occupied']);locations={k:v['host'] for k,v in h['carriers'].items()}
    steps=[];seen=set()
    s.require(isinstance(protocol['steps'],list) and protocol['steps'],'Transfer steps required')
    for step in protocol['steps']:
        s.exact(step,'id carrier destination','handling step')
        identity,target=step['carrier'],step['destination']
        s.require(step['id'] not in seen and identity in locations and target in h['frames'],'Unique transfer and known carrier/destination required')
        seen.add(step['id']);source=locations[identity]
        s.require(target not in occupied and occupied.get(source)==identity,'Transfer needs matching source and empty destination')
        phases=[{'operation':name,'required_feedback':feedback} for name,feedback in [
            ('claim_shared_zone',coordination['transport_requires']),
            ('identify_source_and_destination',['source_payload_identity_and_occupancy_confirmed','destination_empty_confirmed']),
            ('grasp',['carrier_supported_grasp_confirmed']),
            ('transfer',['destination_pose_reached_with_payload_retained_confirmed']),
            ('seat_and_release',['payload_identity_and_seating_confirmed','gripper_empty_confirmed']),
            ('park_and_release_zone',coordination['release_requires'])]]
        steps.append({**step,'source':source,'content':copy.deepcopy(h['carriers'][identity]['content']),'phases':phases})
        del occupied[source];occupied[target]=identity;locations[identity]=target
    return {'format':'solidcraftbot.pipetting-transfer-plan/1','passed':True,'mode':'planning_only',
        'steps':steps,'projected_locations':locations,'coordination':coordination,'feedback_observed':False,
        'hardware_ready':False,'motion':None,'duration_s':None,'material_or_tip_stock_bookings':False,
        'scope':'Projected carrier placement with unchanged content identities; no effects, feedback, stock admission or motion execution.'}
