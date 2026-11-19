"""Continuous, source-limited full-arm carrier transfers and TR01 travel."""
import copy
import itertools
import math

import ps01_logistics_geometry as geometry
import pipetting_station as s
import labware_transfer as handling
import sample_motion
import cf01_unload_validation as validation
from cf01_unload_path import CornerPath
from centrifuge_robot_pickup import tool_target,solve_linear
from tr01_floor_motion import motion, F

SOURCE = s.ROOT / 'model/ps01-logistics.motion.json'


def compiler_pins():
    paths={SOURCE,geometry.SOURCE}
    paths.update(s.ROOT/'scripts'/name for name in ('ps01_logistics_motion.py','ps01_logistics_geometry.py',
        'sample_motion.py','cf01_unload_validation.py','cf01_unload_path.py','centrifuge_robot_pickup.py','robot_spec.py'))
    paths.add(s.ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py')
    return {str(path.relative_to(s.ROOT)):s.robot.digest(path) for path in sorted(paths)}


def load():
    spec = s.read(SOURCE)
    s.exact(spec, 'format mode logistics arm_limits sample_limits vehicle_limits path demonstration limitations', 'logistics motion')
    s.require(spec['format'] == 'solidcraftbot.ps01-logistics-motion/1' and spec['mode'] == 'synthetic_geometry_only', 'Synthetic geometry profile required')
    for name in ('logistics', 'arm_limits', 'sample_limits', 'vehicle_limits'):
        s.bound(spec[name])
    for key in ('clearance_above_worktop_mm', 'corner_trim_mm', 'reference_step_mm', 'time_quantum_s', 'collision_sample_step_s', 'minimum_clearance_mm'):
        s.number(spec['path'][key], positive=True)
    return spec


class SpatialPath(list):
    """C2 weighted line/Bezier route, sampled only to fit the joint PVA."""
    def __init__(self,pieces,step):
        self.pieces=pieces;self.length=sum(weight for _,weight in pieces)
        count=max(4,math.ceil(self.length/step))
        self.progress=[self.length*i/count for i in range(count+1)]
        super().__init__(self.at(distance) for distance in self.progress)

    def at(self,distance):
        remaining=max(0.,min(self.length,distance))
        for controls,weight in self.pieces:
            if remaining<=weight+1e-9:break
            remaining-=weight
        return CornerPath._bezier(controls,max(0.,min(1.,remaining/weight)))


def rounded_points(points, step, trim):
    unique = [points[0]]
    for point in points[1:]:
        if math.dist(point, unique[-1]) > 1e-6:
            unique.append(point)
    s.require(len(unique) >= 2, 'A nonzero transport path is required')
    pieces = []; cursor = unique[0]
    def line(a, b):
        length = math.dist(a, b)
        if length > 1e-8:
            pieces.append(([a,b],length))
    for index, corner in enumerate(unique[1:-1], 1):
        radius = min(trim, math.dist(unique[index-1],corner)*.25, math.dist(corner,unique[index+1])*.25)
        blend = CornerPath(unique[index-1],corner,unique[index+1],0,0,radius)
        line(cursor,blend.controls[0]); pieces.append((blend.controls,7*radius/3)); cursor=blend.controls[-1]
    line(cursor,unique[-1])
    return SpatialPath(pieces,step)


def upright_ik(kin, point, seed):
    target=tool_target(point,0,90)
    q=kin.inverse(target,seed)
    # Canonicalize the exact upright wrist relation before polynomial fitting.
    # Linear PVA interpolation then preserves these identities between knots.
    s.require(abs(q[3])<.01, 'Upright zero-roll IK branch required')
    q[3]=0.; q[4]=180-q[1]-q[2]; q[5]=0.
    correction=s.robot.multiply(s.robot.inverse(kin.tool(q)),target)
    q[5]=math.degrees(math.atan2(correction[1][0],correction[0][0]))
    wrist_offset=q[5]-q[0]
    def canonical(values):
        return [values[0],values[1],values[2],0.,180-values[1]-values[2],values[0]+wrist_offset]
    # The shared numerical solver accepts sub-millimetre endpoint residuals.
    # Supported seating needs tighter translation while retaining the exact
    # linear wrist relations, otherwise jaw closure can microscopically enter
    # the carrier floor. Refine the three independent angles with its solver.
    for _ in range(8):
        actual=kin.tool(q);error=[point[i]-actual[i][3] for i in range(3)]
        if max(abs(v) for v in error)<1e-9:break
        columns=[]
        for j in range(3):
            candidate=q[:];candidate[j]+=1e-4;pose=kin.tool(canonical(candidate))
            columns.append([(pose[i][3]-actual[i][3])/1e-4 for i in range(3)])
        step=solve_linear(list(zip(*columns)),error)
        q=canonical([q[i]+step[i] for i in range(3)])
    s.require(all(lo-1e-6<=v<=hi+1e-6 for v,(lo,hi) in zip(q,kin.limits))
              and max(abs(kin.tool(q)[i][3]-point[i]) for i in range(3))<1e-7, 'Canonical upright IK failed')
    return q


def path(scene, station_id, start, end, *, empty_start=False, empty_end=False, spec=None):
    spec=spec or load(); base=scene.stations[station_id]['worktop_xyz_mm']
    clearance=base[2]+spec['path']['clearance_above_worktop_mm']
    up_start=[start[0],start[1],clearance]; up_end=[end[0],end[1],clearance]
    points=[start,up_start]
    # Going from a front dock to a rear port passes left of the arm base.
    # These are through-points, not stop conditions.
    arm_base=scene.kin(station_id).base
    bx,by=arm_base[0][3],arm_base[1][3]
    if (start[1]-by)*(end[1]-by)<0 and max(start[0],end[0])>bx-180:
        for y in ([by-100,by+150] if start[1]<end[1] else [by+150,by-100]):
            points.append([bx-280,y,clearance])
    points.extend([up_end,end])
    # Empty park is a real endpoint; still blend the complete approach/withdrawal.
    if empty_start:
        points=points[0:1]+points[2:]
    if empty_end:
        points=points[:-2]+points[-1:]
    return rounded_points(points,spec['path']['reference_step_mm'],spec['path']['corner_trim_mm'])


def curve(scene, station_id, points, references, loaded, spec):
    kin=scene.kin(station_id)
    seed=scene.arms[station_id+'.PS01TransferArm']['joints_deg']; qs=[]
    for point in points:
        seed=upright_ik(kin,point,seed); qs.append([math.radians(v) for v in seed])
    limits=s.bound(spec['arm_limits'])['limits']; caps=limits['arm_loaded' if loaded else 'arm_empty']
    # Parameterize the whole spatial path by one S-curve. Giving equally spaced
    # path knots equal times and then forcing endpoint rest makes the tiny first
    # interval limit every transit interval, producing artificially slow travel.
    distances=points.progress
    radius=kin.p['upper_len']+kin.p['fore_len']+kin.length
    scalar_caps=(s.bound(spec['sample_limits'])['sample_caps'] if loaded else {
        'velocity_mm_s':radius*caps['velocity_rad_s'],
        'acceleration_mm_s2':radius*caps['acceleration_rad_s2'],
        'jerk_mm_s3':radius*caps['jerk_rad_s3']})
    scalar=motion.Curve(motion.rest_to_rest(distances[-1],*(scalar_caps[key] for key in
        ('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'))))
    times=[0.]
    for distance in distances[1:-1]:
        low,high=0.,scalar.times[-1]
        for _ in range(48):
            mid=(low+high)/2
            if scalar.evaluate(mid)[F[0]][0]<distance:low=mid
            else:high=mid
        times.append((low+high)/2)
    times.append(scalar.times[-1])
    # Differentiate the continuous reference route, not a local polynomial
    # through unequally timed distant IK knots. The latter can turn withdrawal
    # sideways before the fingers clear the payload. The executed quintics are
    # still bounded and checked independently after this numerical fitting.
    nodes=[]
    for index,(time,q) in enumerate(zip(times,qs)):
        velocity=[0.]*6;acceleration=[0.]*6
        if index not in (0,len(qs)-1):
            progress=distances[index];h=min(.1,progress/4,(distances[-1]-progress)/4)
            samples={j:[math.radians(v) for v in upright_ik(kin,points.at(progress+j*h),[math.degrees(v) for v in q])]
                     for j in (-2,-1,1,2)}
            clock=scalar.evaluate(time);speed=clock[F[1]][0];accel=clock[F[2]][0]
            for j in range(6):
                first=(samples[-2][j]-8*samples[-1][j]+8*samples[1][j]-samples[2][j])/(12*h)
                second=(-samples[-2][j]+16*samples[-1][j]-30*q[j]+16*samples[1][j]-samples[2][j])/(12*h*h)
                velocity[j]=first*speed;acceleration[j]=second*speed*speed+first*accel
        nodes.append({'time_s':time,F[0]:q,F[1]:velocity,F[2]:acceleration})
    bounds=motion.bounds(nodes)
    for lo,hi,limit in zip(bounds[F[0]]['min'],bounds[F[0]]['max'],kin.limits):
        s.require(math.degrees(lo)>=limit[0]-1e-6 and math.degrees(hi)<=limit[1]+1e-6, 'Intermediate joint position limit exceeded')
    sample=s.bound(spec['sample_limits'])['sample_caps']
    fk_limits={'sample_translation':sample,'sample_rotation':limits['sample_rotation']}
    fk=sample_motion.adaptive_bounds(kin,nodes,points_mm=references,
        subdivisions=spec['path']['fk_subdivisions'],
        max_subdivisions=spec['path']['fk_max_subdivisions'],limits=fk_limits) if loaded else None
    factor=max((max(bounds[field]['max_abs'])/caps[key])**(1/order)
               for order,(field,key) in enumerate(zip(F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')),1))
    if loaded:
        for order,key in enumerate(('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'),1):
            factor=max(factor,(fk[key]/sample[key])**(1/order))
        for order,key in enumerate(sample_motion.ANGULAR,1):
            cap=math.radians(limits['sample_rotation'][('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3')[order-1]])
            factor=max(factor,(fk[key]/cap)**(1/order))
    quantum=spec['path']['time_quantum_s']
    factor=math.ceil(factor*(1+1e-7)*times[-1]/quantum)*quantum/times[-1]
    nodes=motion.scale(nodes,factor); result=motion.Curve(nodes)
    proof=validation.no_stop(result,0,result.times[-1],sample_motion.KinematicJets(kin),references,
                             {'stop_joint_speed_rad_s':1e-6,'stop_speed_mm_s':.01})
    residual=max(max(abs(v) for v in kin.residual([math.degrees(x) for x in node[F[0]]],tool_target(point,0,90))) for node,point in zip(nodes,points))
    # Derivatives scale exactly by factor**order; retain the actual interval
    # proof and refinement metadata instead of falling back to a coarse bound.
    scaled_fk=copy.deepcopy(fk)
    if scaled_fk:
        for order,key in enumerate(sample_motion.LINEAR[1:],1):
            scaled_fk[key]/=factor**order
            scaled_fk['tool'][key]/=factor**order
            for point in scaled_fk['points']:point[key]/=factor**order
        for order,key in enumerate(sample_motion.ANGULAR,1):scaled_fk[key]/=factor**order
        scaled_fk['proof_time_scale']=factor
    return {'points':nodes,'duration_s':result.times[-1],'loaded':loaded,
            'joint_bounds':motion.bounds(nodes),'fk_bounds':scaled_fk,
            'no_stop':proof,'maximum_knot_fk_residual':residual,'time_scale':factor,
            'timing':'Smallest millisecond uniform time scale meeting the conservative bounds for this fixed PVA path; not global time optimality.'}


def transfer(scene, station_id, source_frame, target_frame, carrier_id, spec=None):
    spec=spec or load(); hp=scene.hp
    start=s.robot.transform(source_frame,[0,0,hp['foot_h']]); end=s.robot.transform(target_frame,[0,0,hp['foot_h']])
    relation=s.robot.multiply(s.robot.inverse(tool_target(start,0,90)),source_frame)
    corners=[]
    for part in scene.payloads[carrier_id]:
        box=geometry.part_bounds(part)
        corners.extend(s.robot.transform(relation,p) for p in itertools.product(*zip(box['min'],box['max'])))
    # Use one conservative envelope of every carried solid, not only a TCP.
    low=[min(p[i] for p in corners) for i in range(3)]; high=[max(p[i] for p in corners) for i in range(3)]
    refs=list(itertools.product(*zip(low,high)))
    park=scene.park(station_id)
    result={'station':station_id,'carrier_id':carrier_id,'source_frame':source_frame,'target_frame':target_frame,
            'attachment':relation,'references_tool_mm':refs,'phases':{}}
    for name,a,b,loaded in [('approach',park,start,False),('carried',start,end,True),('withdraw',end,park,False)]:
        points=path(scene,station_id,a,b,empty_start=name=='approach',empty_end=name=='withdraw',spec=spec)
        result['phases'][name]=curve(scene,station_id,points,refs if loaded else [],loaded,spec)
    # Jaw actuation is its own required grasp/release motion. Bounds are inherited
    # from the existing station-linear concept, not stretched presentation pauses.
    caps=s.bound(spec['arm_limits'])['limits']['station_linear']
    jaw=motion.rest_to_rest(hp['open_gap']-hp['carrier_d'],caps['velocity_mm_s'],caps['acceleration_mm_s2'],caps['jerk_mm_s3'])
    result['jaw_motion']={'points':jaw,'duration_s':jaw[-1]['time_s'],'bounds':motion.bounds(jaw),
                          'confirmation':'Explicit supported/grasp/release test-fixture observation; real wait duration unknown'}
    return result


def travel(scene, source_station, target_station, loaded, spec=None):
    spec=spec or load(); a=scene.stations[source_station]['dock_xy_mm']; b=scene.stations[target_station]['dock_xy_mm']
    caps=s.bound(spec['vehicle_limits'])['limits']['linear']
    points=motion.rest_to_rest(math.dist(a,b),caps['velocity'],caps['acceleration'],caps['jerk'])
    bound=motion.bounds(points)
    return {'points':points,'duration_s':points[-1]['time_s'],'from_xy_mm':a,'to_xy_mm':b,'yaw_deg':0,
            'loaded':loaded,'bounds':bound,'limits':caps,'scope':'Straight rigid vehicle pose; no wheel/steering controller or physical braking qualification.'}


def compile_demo(scene=None):
    captured=compiler_pins()
    scene=scene or geometry.Scene(); spec=load(); demo=spec['demonstration']
    a=demo['source'].split('.')[0]; b=demo['target'].split('.')[0]; cid=demo['carrier_id']
    load_move=transfer(scene,a,scene.frames[demo['source']],scene.load_frame(a),cid,spec)
    unload_move=transfer(scene,b,scene.load_frame(b),scene.frames[demo['target']],cid,spec)
    drive=travel(scene,a,b,True,spec)
    s.require(captured==compiler_pins(),'Motion sources changed during compilation')
    return {'format':'solidcraftbot.ps01-logistics-motion-program/1','definition':spec,'compiler_sources_sha256':captured,
            'load':load_move,'travel':drive,'unload':unload_move,
            'motion_duration_s':sum(p['duration_s'] for move in (load_move,unload_move) for p in move['phases'].values())
                                +4*load_move['jaw_motion']['duration_s']+drive['duration_s'],
            'playback_factor':demo['playback_factor'],'human_reference_s':demo['human_reference_s'],
            'human_speed_acceptance_proven':False,'hardware_executed':False,
            'feedback_wait_duration_s':None}
