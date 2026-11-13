"""Source-referenced TR01 docks, workstation ownership and six-axis transfers."""
import copy,json,math
from pathlib import Path

import tr01_floor_motion as floor
import centrifuge_robot_pickup as pickup
import sample_motion
import cf01_unload_validation as validation

ROOT=floor.ROOT
SOURCE=ROOT/'model/tr01-l01-workcell.protocol.json'
F=floor.F


def load():
    s=json.loads(SOURCE.read_text())
    if s['format']!='solidcraftbot.tr01-workcell/1' or s['mode']!='synthetic_only':raise ValueError('Synthetic workcell source required')
    for key in ('layout','floor_motion','arm_source','tool_reference','limits_reference'):floor.assembly.validate_reference(s[key])
    if s['guards']['no_timeout_release'] is not True or s['guards']['no_audible_eviction'] is not True:raise ValueError('Explicit workstation priority required')
    return s


def actor_source(s,name):
    layout=floor.layout.load(validate_builds=False);context=floor.layout.parameters(layout);items={i['id']:i for i in layout['instances']}
    definition=s['actors'][name]
    original=items.get(definition['source_instance'])
    source=floor.layout.instance_source(layout,original) if original else floor.robot.load(floor.assembly.validate_reference(s['arm_source']))
    base=definition['xyz_mm'] or floor.layout.xyz(original['xyz'],context)
    yaw=definition['yaw_deg'] if definition['yaw_deg'] is not None else original['yaw_deg']
    scene=copy.deepcopy(pickup.load())
    scene['gripper'].update(s.get('gripper_overrides',{}))
    scene['arm_fixture'].update(position_mm=base,yaw_deg=yaw)
    kin=pickup.Kinematics(source,scene)
    return source,scene,kin


def grip(s,station):
    fs=floor.load();ls=floor.layout.load(validate_builds=False);spec,p,variant=floor.vehicle_source(fs,ls)
    def local(body,selected=variant):
        expanded=floor.vehicle.expanded(spec,p,selected)
        geometry=tube_geometry(expanded,body,s['cargo_grip_offset_from_top_mm']);point=geometry['grip_mm']
        return point,expanded
    car,_=local(s['cargo_slot_body']);item=s['stations'][station];x,y,a=item['dock_pose_mm_rad'];c,q=math.cos(a),math.sin(a)
    target=[x+c*car[0]-q*car[1],y+q*car[0]+c*car[1],car[2]]
    ref=next((r for r in s['additional_racks'] if r['id']==item['rack_instance']),None)
    if ref:base=ref['xyz_mm'];yaw=0.
    else:
        inst=next(i for i in ls['instances'] if i['id']==item['rack_instance']);base=floor.layout.xyz(inst['xyz'],floor.layout.parameters(ls));yaw=math.radians(inst['yaw_deg'])
    mixed=next(v for v in spec['variants'] if v['id']=='Floor_Mixed')
    local_point,expanded=local('B2_'+item['rack_place_body'],mixed)
    datum=next(frame['origin_mm'] for frame in expanded['interfaces'] if frame['id']=='B2_CassetteDatum')
    point=[a-b for a,b in zip(local_point,datum)];c,q=math.cos(yaw),math.sin(yaw)
    bench=[base[0]+c*point[0]-q*point[1],base[1]+q*point[0]+c*point[1],base[2]+point[2]]
    return bench,target


def tube_geometry(expanded,body,offset):
    """Include the joined cap as well as the tube shaft, from one recipe."""
    shapes=[o['shape'] for o in expanded['operations'] if o['body']==body and o['action'] in ('create','join')]
    if not shapes or any(s['kind']!='cylinder' or s['axis']!=[0,0,1] for s in shapes):raise ValueError('Coaxial closed tube cylinders required')
    centre=shapes[0]['origin'][:2]
    if any(s['origin'][:2]!=centre for s in shapes):raise ValueError('Coaxial tube and cap required')
    bottom=min(s['origin'][2] for s in shapes);top=max(s['origin'][2]+s['height'] for s in shapes);radius=max(s['radius'] for s in shapes)
    grip=[*centre,top+offset]
    return {'grip_mm':grip,'radius_mm':radius,'tool_axial_bounds_mm':[grip[2]-top,grip[2]-bottom]}


def compile_arm_curve(qs,kin,caps,limits,loaded):
    points=floor.motion.from_positions(list(range(len(qs))),[[math.radians(v) for v in q] for q in qs])
    # Damp a complete knot jet together so the upright-tool linear angle
    # identities survive bounded fitting. Transit knots retain nonzero motion.
    for iteration in range(40):
        bad=set()
        for index,(a,b) in enumerate(zip(points,points[1:])):
            bound=floor.motion.bounds([a,b])[F[0]]
            if any(math.degrees(lo)<limits_[0]-1e-7 or math.degrees(hi)>limits_[1]+1e-7
                   for lo,hi,limits_ in zip(bound['min'],bound['max'],kin.limits)):bad.update((index,index+1))
        if not bad:break
        for index in bad:
            for field in F[1:3]:points[index][field]=[v*.5 for v in points[index][field]]
    else:raise ValueError('Coupled bounded PVA fit failed')
    joint=floor.motion.bounds(points)
    for index,(lo,hi,declared) in enumerate(zip(joint[F[0]]['min'],joint[F[0]]['max'],kin.limits)):
        if math.degrees(lo)<declared[0]-1e-6 or math.degrees(hi)>declared[1]+1e-6:raise ValueError('Intermediate arm joint limit J'+str(index+1)+' '+str([math.degrees(lo),math.degrees(hi)])+' nodes='+str([q[index] for q in qs]))
    # Bound every material point of the source cylinder in the downward
    # tool frame. Derive height/radius and grip offset, never a copied tube.
    definition=load();fs=floor.load();ls=floor.layout.load(validate_builds=False)
    spec,p,variant=floor.vehicle_source(fs,ls)
    geometry=tube_geometry(floor.vehicle.expanded(spec,p,variant),definition['cargo_slot_body'],definition['cargo_grip_offset_from_top_mm'])
    radius=geometry['radius_mm']
    references=[[x,y,z] for x in (-radius,radius) for y in (-radius,radius)
                for z in geometry['tool_axial_bounds_mm']]
    fk=sample_motion.bounds(kin,points,points_mm=references,subdivisions=4)
    factor=max((max(joint[field]['max_abs'])/caps[key])**(1/order) for order,(field,key) in enumerate(zip(F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')),1))
    for order,field in enumerate(('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'),1):factor=max(factor,(fk[field]/limits['sample_translation'][field])**(1/order))
    for order,field in enumerate(sample_motion.ANGULAR,1):factor=max(factor,(fk[field]/math.radians(limits['sample_rotation'][('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3')[order-1]]))**(1/order))
    factor=math.ceil(factor*100*(1+1e-6))/100
    points=floor.motion.scale(points,factor)
    curve=floor.motion.Curve(points)
    proof=validation.no_stop(curve,0.,curve.times[-1],sample_motion.KinematicJets(kin),references,{'stop_joint_speed_rad_s':1e-6,'stop_speed_mm_s':.01})
    return {'points':points,'duration_s':curve.times[-1],'joint_bounds':floor.motion.bounds(curve),
            'fk_bounds':sample_motion.bounds(kin,curve,points_mm=references,subdivisions=4),'no_stop':proof,
            'timing':{'uniform_factor':factor,'resolution':.01,'global_time_optimality_proved':False},'loaded':loaded}


def compile_station(s,station):
    item=s['stations'][station]
    if item['actor']=='human':return {'station':station,'kind':'manual','bench_grip_mm':grip(s,station)[0],'car_grip_mm':grip(s,station)[1]}
    source,scene,kin=actor_source(s,item['actor']);roll=item['tool_roll_deg']
    limits=json.loads(floor.assembly.validate_reference(s['limits_reference']).read_text())['limits']
    seed=floor.robot.home(source)
    def ik(point):
        nonlocal seed
        target=pickup.tool_target(point,0.,roll)
        base=[kin.base[i][3] for i in range(3)];dx,dy=point[0]-base[0],point[1]-base[1]
        rho=math.hypot(dx,dy);p=kin.p
        lever=kin.flange[2]+kin.length-p['wrist_z']
        z=point[2]+lever-base[2]-p['shoulder_z'];l1=p['upper_len'];l2=p['fore_len']
        cosine=(rho*rho+z*z-l1*l1-l2*l2)/(2*l1*l2)
        candidates=[]
        yaw=math.degrees(math.atan2(kin.base[1][0],kin.base[0][0]))
        if -1<=cosine<=1:
            for sign in (-1,1):
                q3=sign*math.acos(cosine)
                q2=math.atan2(rho,z)-math.atan2(l2*math.sin(q3),l1+l2*math.cos(q3))
                q=[(math.degrees(math.atan2(dy,dx))-yaw+180)%360-180,math.degrees(q2),math.degrees(q3),0.,180-math.degrees(q2+q3),0.]
                rotation=floor.robot.multiply(floor.robot.inverse(kin.tool(q)),target)
                q[5]=math.degrees(math.atan2(rotation[1][0],rotation[0][0]))
                if all(lo-1e-7<=v<=hi+1e-7 for v,(lo,hi) in zip(q,kin.limits)) and max(abs(v) for v in kin.residual(q,target))<.01:candidates.append(q)
        if not candidates:raise ValueError('No upright analytic IK within source limits at '+str(point))
        seed=min(candidates,key=lambda q:sum((a-b)**2 for a,b in zip(q,seed)))
        return seed[:]
    park=ik(s['actors'][item['actor']]['park_tcp_mm']);bench,car=grip(s,station)
    via=item['clearance_tcp_mm']
    def path_joints(points):
        from cf01_unload_path import CornerPath
        pieces=[];cursor=points[0]
        def line(a,b):
            length=math.dist(a,b)
            if length>1e-8:pieces.append(([a,b],length))
        for index,corner in enumerate(points[1:-1],1):
            trim=min(s['arm_path']['corner_trim_mm'],math.dist(points[index-1],corner)*.25,math.dist(corner,points[index+1])*.25)
            blend=CornerPath(points[index-1],corner,points[index+1],0.,0.,trim)
            line(cursor,blend.controls[0]);pieces.append((blend.controls,7*trim/3));cursor=blend.controls[-1]
        line(cursor,points[-1]);total=sum(weight for _,weight in pieces)
        step=s['arm_path']['reference_step_mm'];count=math.ceil(total/step)
        # Equal spacing avoids a very short last interval with a full-speed
        # incoming jet, which otherwise dips below the seated endpoint.
        samples=[total*i/count for i in range(count+1)]
        result=[]
        for distance in samples:
            remaining=distance
            for controls,weight in pieces:
                if remaining<=weight+1e-8:break
                remaining-=weight
            result.append(ik(CornerPath._bezier(controls,max(0.,min(1.,remaining/weight)))))
        return result
    # Same source-defined geometric transit is evaluated in both directions.
    result={'station':station,'kind':'robot','actor':item['actor'],'park_joints_deg':park,'base_matrix':kin.base,
            'bench_grip_mm':bench,'car_grip_mm':car,'tool':scene['gripper'],'transfers':{}}
    for direction in ('load','unload'):
        path=[bench,*via,car] if direction=='load' else [car,*reversed(via),bench]
        loaded_q=path_joints(path)
        above_source=path[1];above_target=path[-2]
        bench_via=item.get('empty_bench_via_tcp_mm',[])
        empty_in=path_joints([s['actors'][item['actor']]['park_tcp_mm'],*(bench_via if direction=='load' else []),above_source,path[0]])
        empty_out=path_joints([path[-1],above_target,*(reversed(bench_via) if direction=='unload' else []),s['actors'][item['actor']]['park_tcp_mm']])
        result['transfers'][direction]={
            'empty_in':compile_arm_curve(empty_in,kin,limits['arm_empty'],limits,False),
            'loaded':compile_arm_curve(loaded_q,kin,limits['arm_loaded'],limits,True),
            'empty_out':compile_arm_curve(empty_out,kin,limits['arm_empty'],limits,False)}
    return result


def compile_program():
    s=load();result={'format':'solidcraftbot.tr01-workcell-program/1','definition':s,'stations':{}}
    for station in s['stations']:
        result['stations'][station]=compile_station(s,station)
        print(station,'compiled',flush=True)
    return result


def approach(s,station,radius):
    """Geometric chassis reference, independently oriented, not a drive model.

    Reorientation finishes on the centre line before the lateral approach.
    Departure reverses this exact rigid-pose curve, including its orientation.
    """
    fs=copy.deepcopy(floor.load());item=s['stations'][station]
    queue=fs['stations'][station]['park_xy_mm'];dock=item['dock_pose_mm_rad']
    fs['stations']={'queue':{'park_xy_mm':queue},'dock':{'park_xy_mm':dock[:2]}}
    fs['curve']['corner_trim_mm']=60
    route=floor.compile_route(fs,{'id':station+'.approach','from':'queue','to':'dock',
        'via_xy_mm':item['approach_via_xy_mm'],'reverse':False},radius)
    nodes=floor.canonical(route['points']);end=nodes[-1]['time_s']
    # A separate rest-to-rest orientation channel ends before leaving the
    # first straight centre-line leg. Conservative native interval checking
    # below tests the actual combined PVA curve, not the reference polyline.
    yaw0=math.pi/2 if station!='QC' else -math.pi/2
    yaw1=dock[2];yaw1=yaw0+(yaw1-yaw0+math.pi)%(2*math.pi)-math.pi
    first=item['approach_via_xy_mm'][0]
    turn_end=next((p['time_s'] for p in nodes[1:] if math.dist(p[F[0]][:2],queue)>math.dist(first,queue)*.55),end*.15)
    for node in nodes:
        u=min(1.,node['time_s']/turn_end);delta=yaw1-yaw0
        node[F[0]][2]=yaw0+delta*(10*u**3-15*u**4+6*u**5)
        node[F[1]][2]=delta*(30*u*u-60*u**3+30*u**4)/turn_end if u<1 else 0.
        node[F[2]][2]=delta*(60*u-180*u*u+120*u**3)/turn_end**2 if u<1 else 0.
    actual=floor.dynamics(floor.motion.Curve(nodes),radius)
    factor=max(1.,*( (actual[k][field]/fs['limits'][k][field])**(1/order)
        for k in ('linear','angular','carried_points') for order,field in enumerate(('velocity','acceleration','jerk'),1)))
    factor=math.ceil(factor*100*(1+1e-6))/100;nodes=floor.motion.scale(nodes,factor)
    curve=floor.motion.Curve(nodes)
    if not floor.no_stop(curve)['passed']:raise ValueError('Dock approach contains internal stop')
    return {'id':station+'.approach','from':station,'to':station,'duration_s':curve.times[-1],
        'points':floor.public(nodes),'dynamics':floor.dynamics(curve,radius),'no_stop':floor.no_stop(curve)}


def reverse_curve(route):
    points=floor.canonical(route['points']);end=points[-1]['time_s']
    reverse=[{'time_s':end-p['time_s'],F[0]:p[F[0]],F[1]:[-v for v in p[F[1]]],F[2]:p[F[2]]} for p in reversed(points)]
    return {**route,'id':route['id'].replace('approach','departure'),'points':floor.public(reverse)}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--station',choices=['DNA','CF01','QC','TS01']);parser.add_argument('--output',required=True)
    args=parser.parse_args();s=load()
    result=compile_station(s,args.station) if args.station else compile_program()
    result['workcell_sha256']=floor.robot.digest(SOURCE)
    Path(args.output).write_text(json.dumps(result,allow_nan=False)+'\n')
