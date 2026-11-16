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
import water_practice_upright_bounds as upright
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
    if s['bound_method']!='upright_chain_with_actual_polynomial_residuals' or s['progress_law']!='quintic_rest_to_rest':
        raise ValueError('Supported water-path bound and progress methods required')
    settings=s['retiming']
    if (settings['method']!='smooth_density_coordinate_descent' or settings['centres']<3 or settings['passes']<1
            or not 0<settings['width']<=1 or any(not math.isfinite(v) or v<=0 for v in settings['steps'])):
        raise ValueError('Finite positive smooth retiming settings required')
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


def density_retime(points,caps,settings):
    """Optimize a smooth time density; final interval certification is separate."""
    positions=[p[F[0]] for p in points];n=len(positions)-1
    centres=[i/(settings['centres']-1) for i in range(settings['centres'])]
    basis=[[math.exp(-(((i+.5)/n-c)/settings['width'])**2) for c in centres] for i in range(n)]
    evaluations=0
    def candidate(weights):
        nonlocal evaluations
        evaluations+=1
        intervals=[math.exp(sum(w*b for w,b in zip(weights,row))) for row in basis]
        scale=n/sum(intervals);times=[0.]
        for interval in intervals:times.append(times[-1]+interval*scale)
        result=motion.from_positions(times,positions);bound=motion.bounds(result)
        factor=max((max(bound[field]['max_abs'])/caps[key])**(1/order)
            for order,(field,key) in enumerate(zip(F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')),1))
        return factor*n,result
    weights=[0.]*len(centres);best,result=candidate(weights);initial=best
    for step in settings['steps']:
        for _ in range(settings['passes']):
            for i in range(len(weights)):
                options=[]
                for sign in (-1,1):
                    trial=weights[:];trial[i]=max(-4.,min(4.,trial[i]+sign*step))
                    cost,curve=candidate(trial);options.append((cost,trial,curve))
                cost,trial,curve=min(options,key=lambda v:v[0])
                if cost<best*(1-1e-8):best,weights,result=cost,trial,curve
    return result,{'method':'smooth_density_coordinate_descent','evaluations':evaluations,
                   'initial_joint_limited_duration_s':initial,'joint_limited_duration_s':best,
                   'density_weights':weights,'global_time_optimality_proved':False}


def fit(qs, kin, limits, loaded, empty_limits, subdivisions, retiming):
    points = motion.from_positions(list(range(len(qs))),[[math.radians(v) for v in q] for q in qs])
    joint = motion.bounds(points)
    for lo,hi,declared in zip(joint[F[0]]['min'],joint[F[0]]['max'],kin.limits):
        if math.degrees(lo)<declared[0]-1e-6 or math.degrees(hi)>declared[1]+1e-6:
            raise ValueError('Intermediate joint limit')
    # Include a conservative cube around the water carried inside the tip,
    # and the entire pipettor, all expressed relative to its TCP.
    references = [[x,y,z] for x in (-40,40) for y in (-24,24) for z in (-kin.length,0)]
    caps = limits['arm_loaded' if loaded else 'arm_empty']
    linear = limits['sample_translation'] if loaded else empty_limits
    def factor_for(points):
        joint=motion.bounds(points)
        fk=upright.bounds(kin,points,points_mm=references,subdivisions=subdivisions)
        factor=max((max(joint[field]['max_abs'])/caps[key])**(1/order)
            for order,(field,key) in enumerate(zip(F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')),1))
        for order,field in enumerate(('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'),1):factor=max(factor,(fk[field]/linear[field])**(1/order))
        for order,field in enumerate(sample_motion.ANGULAR,1):
            cap=math.radians(limits['sample_rotation'][('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3')[order-1]])
            factor=max(factor,(fk[field]/cap)**(1/order))
        return math.ceil(factor*10000*(1+1e-6))/10000
    candidates=[]
    factor=factor_for(points);candidates.append((points,factor,'uniform'))
    optimization=None
    if points[-1]['time_s']*factor>2:
        weighted,optimization=density_retime(points,caps,retiming)
        bounds=motion.bounds(weighted)
        if all(math.degrees(lo)>=lim[0]-1e-6 and math.degrees(hi)<=lim[1]+1e-6
               for lo,hi,lim in zip(bounds[F[0]]['min'],bounds[F[0]]['max'],kin.limits)):
            candidates.append((weighted,factor_for(weighted),'smooth_density_joint_extrema'))
    points,factor,method=min(candidates,key=lambda c:c[0][-1]['time_s']*c[1])
    points=motion.scale(points,factor)
    curve=motion.Curve(points)
    no_stop = validation.no_stop(curve,0,curve.times[-1],sample_motion.KinematicJets(kin),[[0,0,0]],
                                 {'stop_joint_speed_rad_s':1e-6,'stop_speed_mm_s':.01})
    if not no_stop['passed']:
        raise ValueError('Unnecessary internal stop')
    return {'duration_s':curve.times[-1],'points':points,'loaded':loaded,
            'joint_bounds':motion.bounds(curve),
            'fk_bounds':upright.bounds(kin,curve,points_mm=references,subdivisions=subdivisions),
            'no_stop':no_stop,'timing':{'uniform_factor':factor,'scale_factor_resolution':.0001,'progress_law':'quintic_rest_to_rest','retiming':method,'optimization':optimization,'global_time_optimality_proved':False},
            'material_point_box_tcp_mm':{'min':[-40,-24,-kin.length],'max':[40,24,0]}}


def progress(u):
    return 10*u**3-15*u**4+6*u**5


def rounded_points(route,count):
    pieces=[];cursor=route[0]
    for i,corner in enumerate(route[1:-1],1):
        trim=min(10,math.dist(route[i-1],corner)/4,math.dist(corner,route[i+1])/4)
        blend=CornerPath(route[i-1],corner,route[i+1],0,0,trim)
        pieces.append(([cursor,blend.controls[0]],math.dist(cursor,blend.controls[0])))
        pieces.append((blend.controls,7*trim/3));cursor=blend.controls[-1]
    pieces.append(([cursor,route[-1]],math.dist(cursor,route[-1])))
    total=sum(weight for _,weight in pieces);points=[]
    for i in range(count):
        distance=total*progress(i/(count-1))
        for controls,weight in pieces:
            if distance<=weight+1e-8:break
            distance-=weight
        points.append(CornerPath._bezier(controls,max(0,min(1,distance/weight))))
    return points


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
        points=rounded_points([source,[source[0],source[1],high],[target[0],target[1],high],target],s['path_samples'])
        qs=[];seed=actor_data[actor]['park']
        for point in points:
            seed=upright_ik(kin,point,roll,seed);qs.append(seed)
        # Pipetting starts parked above the source with an upright tool. No
        # automatic tool change or movement from the legacy gripper park.
        park_point=[source[0],source[1],high]
        park=upright_ik(kin,park_point,roll,qs[0])
        approach_q=[upright_ik(kin,[source[0],source[1],high+(source[2]-high)*progress(i/(s['approach_samples']-1))],roll,park) for i in range(s['approach_samples'])]
        # Retreat lifts vertically first before returning over the source.
        retreat_points=rounded_points([target,[target[0],target[1],high],park_point],s['retreat_samples'])
        retreat_q=[upright_ik(kin,p,roll,qs[-1]) for p in retreat_points]
        curves={'approach':fit(approach_q,kin,limits,False,s['empty_tcp_limits'],s['bound_subdivisions'],s['retiming']),
                'loaded':fit(qs,kin,limits,True,s['empty_tcp_limits'],s['bound_subdivisions'],s['retiming']),
                'retreat':fit(retreat_q,kin,limits,False,s['empty_tcp_limits'],s['bound_subdivisions'],s['retiming'])}
        program['paths'][name]={**path,'park':park,'tcp_source':source,'tcp_target':target,'curves':curves}
    program['source_files_sha256']={str(SOURCE.relative_to(ROOT)):digest(SOURCE),
        **{r['source']:r['source_sha256'] for r in s['sources'].values()},
        **{str(Path(m.__file__).relative_to(ROOT)):digest(m.__file__) for m in (robot,pickup,sample_motion,validation,tools,upright)},
        'scripts/cf01_unload_path.py':digest(ROOT/'scripts/cf01_unload_path.py'),
        str(Path(__file__).relative_to(ROOT)):digest(__file__),
        'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py':digest(motion.__file__)}
    return program
