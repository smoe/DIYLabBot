"""Export the compiled synthetic unload arm channel with quintic P/V/A knots.

The controller must use spline interpolation. Live controller configuration,
robot-description compatibility, gripper/station integration and hardware remain
unverified. This export is not a biological sample-tolerance qualification.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

import export_centrifuge_robot_pickup_ros2 as previous

ROOT=previous.pickup.ROOT
sys.path.insert(0,str(ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion
from solidcraftbot_ros.protocol import derivative_mode,finite_vector,scenario

SCENARIO='cf01_unload_three_samples'
DEFAULT_OUTPUT=ROOT/'exports/generated/cf01-unload-ros2/scenarios.json'
FIELDS=('positions_rad','velocities_rad_s','accelerations_rad_s2')
ERROR_TOLERANCES={'positions_rad':1e-7,'velocities_rad_s':1e-6,'accelerations_rad_s2':1e-5}


def pinned_sources(program):
    sources=program.get('source_files_sha256')
    if not isinstance(sources,dict) or not sources:raise ValueError('Compiled program source bindings required')
    for name,digest in sources.items():
        if not isinstance(name,str):raise ValueError('Project-relative compiled source path required')
        path=(ROOT/name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Compiled source must stay in the project: '+name)
        if previous.pickup.robot.digest(path)!=digest:raise ValueError('Compiled program source changed: '+name)
    return copy.deepcopy(sources)


def quantize(points):
    if len(points)<2 or not derivative_mode(points):raise ValueError('At least two complete PVA points required')
    result=[];last=-1
    for point in points:
        time=point.get('time_s')
        if type(time) not in (int,float) or not math.isfinite(time) or time<0 or not math.isfinite(time*1e9):
            raise ValueError('Finite nonnegative knot times required')
        ns=round(time*1e9)
        if ns<=last:raise ValueError('Nanosecond quantization collapses or reorders knot times')
        last=ns
        for field in FIELDS:finite_vector(point[field],field)
        result.append({'time_s':ns/1e9,**{field:list(point[field]) for field in FIELDS}})
    if points[0]['time_s']!=0:raise ValueError('The compiled arm program must start at zero')
    for point in (points[0],points[-1]):
        if any(value!=0 for field in FIELDS[1:] for value in point[field]):
            raise ValueError('Explicit rest velocity and acceleration required at arm program endpoints')
    curve=motion.Curve(points)
    # Keeping the old jet at a shifted timestamp changes short-interval quintics
    # unnecessarily. Sample the reference curve at the actual ROS knot time.
    # Preserve both exact rest endpoints when their time rounds in either direction.
    for index in range(1,len(result)-1):
        state=motion.evaluate(curve,result[index]['time_s'])
        for field in FIELDS:result[index][field]=list(state[field])
    return result


def quantization_audit(reference,wire):
    """Conservative same-time P/V/A errors, not merely sampled agreement.

    Bound the normalized quintic difference at corresponding progress, then add
    the maximum knot shift times the global next-derivative bound. P/V/A are
    continuous across reference knots; rest endpoints permit constant extension.
    Actual wire jerk/position/derivative extrema are checked separately.
    """
    if len(reference)!=len(wire) or len(reference)<2:raise ValueError('Matching reference and wire PVA knots required')
    bounds=motion.bounds(reference)
    shift=max(abs(a['time_s']-b['time_s']) for a,b in zip(reference,wire))
    errors={field:0.0 for field in FIELDS}
    for a,b,wa,wb in zip(reference,reference[1:],wire,wire[1:]):
        dt=b['time_s']-a['time_s'];wdt=wb['time_s']-wa['time_s']
        original=motion.coefficients(a,b);rounded=motion.coefficients(wa,wb)
        for order,field in enumerate(FIELDS):
            following=('velocities_rad_s','accelerations_rad_s2','jerks_rad_s3')[order]
            for joint,(left,right) in enumerate(zip(original,rounded)):
                delta=[math.factorial(i)/math.factorial(i-order)*(left[i]/dt**order-right[i]/wdt**order)
                       for i in range(order,6)]
                candidates=[0.,1.,*motion.real_roots(motion.derivative(delta))]
                maximum=max(abs(motion.polynomial(delta,u)) for u in candidates)
                error=math.nextafter(maximum+shift*bounds[following]['max_abs'][joint],math.inf)
                if not math.isfinite(error):raise ValueError('Nonfinite ROS quantization error bound')
                errors[field]=max(errors[field],error)
    if any(errors[field]>ERROR_TOLERANCES[field] for field in FIELDS):
        raise ValueError('Nanosecond ROS polynomial differs from compiled reference beyond tolerance: '+repr(errors))
    return {'passed':True,'maximum_knot_shift_s':shift,'maximum_error_bounds':errors,
            'tolerances':ERROR_TOLERANCES.copy(),
            'knot_values':'Interior P/V/A evaluated at rounded reference times; exact rest endpoint jets retained',
            'method':'Numerical polynomial extrema of normalized quintic differences plus knot-shift/global derivative bounds; actual wire extrema checked independently'}


def configuration(program=None):
    if program is None:
        import cf01_unload_motion as compiler
        program=compiler.compile()
    if program.get('format')!='solidcraftbot.cf01-unload-program/1':raise ValueError('Compiled CF01 unload program required')
    before=pinned_sources(program)
    scene=previous.pickup.load()
    if program.get('scene')!=scene:raise ValueError('Compiled scene differs from current source-derived pickup scene')
    arm=previous.pickup.arm_source(scene)
    header=previous.robot_description_requirements(scene,arm)
    if program.get('robot_description_requirements')!=header:
        raise ValueError('Compiled robot variant, fixture or TCP metadata mismatch')
    limits=program.get('limits',{})
    if limits.get('qualified') is not False:raise ValueError('Explicit unqualified mock limits required')
    try:
        maximum={field:max(limits[kind][field] for kind in ('arm_loaded','arm_empty'))
                 for field in ('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')}
    except (KeyError,TypeError) as error:raise ValueError('Loaded and empty arm derivative limits required') from error
    points=program['arm']['points'];wire=quantize(points)
    expected_limits=[[math.radians(value) for value in joint['limits_deg']] for joint in arm['joints']]
    if program['arm']['limits_rad']!=expected_limits:raise ValueError('Compiled joint bounds differ from robot source')
    config={'joint_names':[joint['id'].lower() for joint in arm['joints']], 'limits_rad':expected_limits,
            'scenarios':[{'id':SCENARIO,'points':wire}], 'mode':'mock',
            'velocity_limit_rad_s':maximum['velocity_rad_s'],
            'motion_limits':{'qualified':False,**maximum},
            'interpolation':{'method':'quintic','controller_interpolation':'splines',
                             'live_configuration_verified':False,
                             'requirement':'The running joint_trajectory_controller must use spline interpolation for P/V/A knots; not inspected by this client'},
            'phase_limits':copy.deepcopy(limits),
            'phase_limit_check':'Separate compiled-program sample/phase audit required; global ROS arm bounds do not prove per-phase or biological limits',
            'source_files_sha256':before,
            'compiled_program_sha256':hashlib.sha256(json.dumps(program,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
            'runtime_source_files_sha256':{str(path.relative_to(ROOT)):previous.pickup.robot.digest(path) for path in
                [Path(__file__),Path(previous.__file__),Path(motion.__file__),
                 ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/protocol.py',
                 ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/demo.py']},
            'robot_description_requirements':header,
            'included_channels':['six_arm_joints'],
            'excluded_channels':['gripper','CF01 station commands','live collision, sensor and quality feedback'],
            'verification':{'ros_runtime':False,'hardware_execution':False,'integrated_CF01_cycle':False,
                            'biological_tolerance':False}}
    scenario(config,SCENARIO)
    config['nanosecond_quantization']=quantization_audit(points,wire)
    if pinned_sources(program)!=before:raise ValueError('Compiled sources changed during ROS export')
    return config


def reject_constant(value):raise ValueError('Nonfinite JSON value is forbidden: '+value)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--program',type=Path,help='Existing compiled source-bound unload program; otherwise compile the shared motion source')
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    program=json.loads(args.program.read_text(encoding='utf-8'),parse_constant=reject_constant) if args.program else None
    config=configuration(program)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(config,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'scenario':SCENARIO,'points':len(config['scenarios'][0]['points']),
                      'duration_s':config['scenarios'][0]['points'][-1]['time_s'],
                      'nanosecond_quantization':config['nanosecond_quantization'],
                      'required_controller_interpolation':'splines','live_configuration_verified':False,
                      'ros_runtime_verified':False,'hardware_verified':False},indent=2))


if __name__=='__main__':main()
