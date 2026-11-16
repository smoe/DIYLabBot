"""Water-only L01 motion composition; no runtime effects or E4 decisions."""
import copy
import hashlib
import json
import math
from pathlib import Path

import analytics_concept as tools
import centrifuge_robot_pickup as pickup
import robot_spec as robot
import sample_motion
import cf01_unload_validation as validation
from cf01_unload_path import CornerPath
from solidcraftbot_ros import motion

ROOT = robot.ROOT
SOURCE = ROOT/'model/water-practice-l01.motion.json'
OUT = ROOT/'exports/water-practice/l01'
F = motion.FIELDS


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def load():
    s = read(SOURCE)
    if s['format'] != 'solidcraftbot.water-practice-l01-motion/1' or s['mode'] != 'synthetic_display_fixture':
        raise ValueError('Water-only display composition required')
    for ref in s['sources'].values():
        if digest(ROOT/ref['source']) != ref['source_sha256']:
            raise ValueError('Changed water motion input: '+ref['source'])
    return s


def kinematics(s, actor, actor_data):
    # Reuse the current arm, unchanged L01 base and semantic pipette TCP.
    arm = robot.load()
    kit = read(ROOT/'model/analytics-tools.shared.json')
    scene = read(ROOT/'model/centrifuge-cf01.robot-pickup.shared.json')
    base = actor_data[actor]['base']
    scene['arm_fixture'] = {'position_mm':[r[3] for r in base[:3]],
                            'yaw_deg':math.degrees(math.atan2(base[1][0],base[0][0]))}
    scene['gripper']['flange_to_grip_mm'] = kit['cases'][s['pipette_case']]['tcp_length_mm']
    return pickup.Kinematics(arm, scene)


def upright_ik(kin, point, roll, seed):
    target = pickup.tool_target(point, 0, roll)
    base = [kin.base[i][3] for i in range(3)]
    dx,dy = point[0]-base[0],point[1]-base[1]
    rho = math.hypot(dx,dy)
    p = kin.p
    z = point[2]+kin.flange[2]+kin.length-p['wrist_z']-base[2]-p['shoulder_z']
    l1,l2 = p['upper_len'],p['fore_len']
    cosine = (rho*rho+z*z-l1*l1-l2*l2)/(2*l1*l2)
    candidates = []
    if -1 <= cosine <= 1:
        for sign in (-1,1):
            q3 = sign*math.acos(cosine)
            q2 = math.atan2(rho,z)-math.atan2(l2*math.sin(q3),l1+l2*math.cos(q3))
            yaw = math.degrees(math.atan2(kin.base[1][0],kin.base[0][0]))
            q = [(math.degrees(math.atan2(dy,dx))-yaw+180)%360-180,
                 math.degrees(q2),math.degrees(q3),0,180-math.degrees(q2+q3),0]
            r = robot.multiply(robot.inverse(kin.tool(q)),target)
            q[5] = math.degrees(math.atan2(r[1][0],r[0][0]))
            if all(lo <= v <= hi for v,(lo,hi) in zip(q,kin.limits)) and max(map(abs,kin.residual(q,target))) < .001:
                candidates.append(q)
    if not candidates:
        raise ValueError('No upright pipette IK: '+str(point))
    return min(candidates,key=lambda q:sum((a-b)**2 for a,b in zip(q,seed)))


def fit(qs, kin, limits, loaded, empty_limits, subdivisions):
    points = motion.from_positions(list(range(len(qs))),[[math.radians(v) for v in q] for q in qs])
    joint = motion.bounds(points)
    for lo,hi,declared in zip(joint[F[0]]['min'],joint[F[0]]['max'],kin.limits):
        if math.degrees(lo)<declared[0]-1e-6 or math.degrees(hi)>declared[1]+1e-6:
            raise ValueError('Intermediate joint limit')
    # Include a conservative cube around the water carried inside the tip,
    # and the entire pipettor, all expressed relative to its TCP.
    references = [[x,y,z] for x in (-40,40) for y in (-24,24) for z in (-kin.length,0)]
    fk = sample_motion.bounds(kin,points,points_mm=references,subdivisions=subdivisions)
    caps = limits['arm_loaded' if loaded else 'arm_empty']
    factor = max((max(joint[field]['max_abs'])/caps[key])**(1/order)
                 for order,(field,key) in enumerate(zip(F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')),1))
    linear = limits['sample_translation'] if loaded else empty_limits
    for order,field in enumerate(('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'),1):
        factor = max(factor,(fk[field]/linear[field])**(1/order))
    for order,field in enumerate(sample_motion.ANGULAR,1):
        cap = math.radians(limits['sample_rotation'][('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3')[order-1]])
        factor = max(factor,(fk[field]/cap)**(1/order))
    factor = math.ceil(factor*100*(1+1e-6))/100
    points = motion.scale(points,factor)
    curve = motion.Curve(points)
    no_stop = validation.no_stop(curve,0,curve.times[-1],sample_motion.KinematicJets(kin),[[0,0,0]],
                                 {'stop_joint_speed_rad_s':1e-6,'stop_speed_mm_s':.01})
    if not no_stop['passed']:
        raise ValueError('Unnecessary internal stop')
    return {'duration_s':curve.times[-1],'points':points,'loaded':loaded,
            'joint_bounds':motion.bounds(curve),
            'fk_bounds':sample_motion.bounds(kin,curve,points_mm=references,subdivisions=subdivisions),
            'no_stop':no_stop,'timing':{'uniform_factor':factor,'global_time_optimality_proved':False},
            'material_point_box_tcp_mm':{'min':[-40,-24,-kin.length],'max':[40,24,0]}}


def compile_program(actor_data, report):
    s = load()
    if report['mode']!='test_fixture' or not report['practice_completed'] or report['medium']!='water':
        raise ValueError('Completed water fixture report required')
    for name,sha in report['source_files_sha256'].items():
        if digest(ROOT/name)!=sha:
            raise ValueError('Changed water report input: '+name)
    evidence = report['demo_evidence']
    if evidence['simulated_transfers']!=['A1','B1','C1','A2'] or evidence['additional_transfer_during_reconciliation']:
        raise ValueError('Unexpected fixture transfer history')
    kit = read(ROOT/'model/analytics-tools.shared.json')
    case = kit['cases'][s['fixture_case']]
    rim = case['plate_height_mm']/8+case['tube_height_mm']
    limits = read(ROOT/'model/cf01-unload-demo.motion.json')['limits']
    program = {'format':'solidcraftbot.water-practice-l01-program/1','paths':{},'actors':actor_data,
               'definition':s,'kit':kit,'steps':['A1','B1','C1','A2'],'e4_decisions_changed':False,
               'additional_transfer_during_reconciliation':False,'fixture_report_sha256':None}
    workcell = read(ROOT/'model/tr01-l01-workcell.protocol.json')
    for name,path in s['paths'].items():
        actor = path['actor'];kin = kinematics(s,actor,actor_data)
        roll = workcell['stations'][path['station']]['tool_roll_deg']
        source = [*path['source_mm'][:2],path['source_mm'][2]+rim-s['insertion_below_rim_mm']]
        target = [*path['target_mm'][:2],path['target_mm'][2]+rim-s['insertion_below_rim_mm']]
        high = max(source[2],target[2])+s['insertion_below_rim_mm']+s['transit_above_rim_mm']
        # Withdraw vertically until the full immersed tip clears the rim,
        # then blend the two elevated corners without a transport stop.
        route=[source,[source[0],source[1],high],[target[0],target[1],high],target]
        pieces=[];cursor=source
        for i,corner in enumerate(route[1:-1],1):
            trim=min(10,math.dist(route[i-1],corner)/4,math.dist(corner,route[i+1])/4)
            blend=CornerPath(route[i-1],corner,route[i+1],0,0,trim)
            pieces.append(([cursor,blend.controls[0]],math.dist(cursor,blend.controls[0])))
            pieces.append((blend.controls,7*trim/3));cursor=blend.controls[-1]
        pieces.append(([cursor,target],math.dist(cursor,target)))
        total=sum(weight for _,weight in pieces);points=[]
        for i in range(s['path_samples']):
            distance=total*i/(s['path_samples']-1)
            for controls,weight in pieces:
                if distance<=weight+1e-8:break
                distance-=weight
            points.append(CornerPath._bezier(controls,max(0,min(1,distance/weight))))
        qs=[];seed=actor_data[actor]['park']
        for point in points:
            seed=upright_ik(kin,point,roll,seed);qs.append(seed)
        # Pipetting starts parked above the source with an upright tool. No
        # automatic tool change or movement from the legacy gripper park.
        park_point=[source[0],source[1],high]
        park=upright_ik(kin,park_point,roll,qs[0])
        approach_q=[upright_ik(kin,[source[0],source[1],high+(source[2]-high)*i/8],roll,park) for i in range(9)]
        # Retreat lifts vertically first before returning over the source.
        retreat_points=[[target[0],target[1],target[2]+(high-target[2])*i/8] for i in range(9)]
        retreat_points += [[target[0]+(source[0]-target[0])*i/8,target[1]+(source[1]-target[1])*i/8,high] for i in range(1,9)]
        retreat_q=[upright_ik(kin,p,roll,qs[-1]) for p in retreat_points]
        curves={'approach':fit(approach_q,kin,limits,False,s['empty_tcp_limits'],s['bound_subdivisions']),
                'loaded':fit(qs,kin,limits,True,s['empty_tcp_limits'],s['bound_subdivisions']),
                'retreat':fit(retreat_q,kin,limits,False,s['empty_tcp_limits'],s['bound_subdivisions'])}
        program['paths'][name]={**path,'park':park,'tcp_source':source,'tcp_target':target,'curves':curves}
    program['source_files_sha256']={str(SOURCE.relative_to(ROOT)):digest(SOURCE),
        **{r['source']:r['source_sha256'] for r in s['sources'].values()},
        **{str(Path(m.__file__).relative_to(ROOT)):digest(m.__file__) for m in (robot,pickup,sample_motion,validation,tools)},
        'scripts/cf01_unload_path.py':digest(ROOT/'scripts/cf01_unload_path.py'),
        str(Path(__file__).relative_to(ROOT)):digest(__file__),
        'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py':digest(motion.__file__)}
    return program
