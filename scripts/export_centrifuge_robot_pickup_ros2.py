"""Export the demonstrated arm channel for the existing ROS trajectory client.

No CAD or ROS installation is needed. This is a joint program, not a complete
CF01 cycle: gripper, station commands and sensor/interlock feedback are separate.
The running robot description must match the recorded variant, fixture and TCP;
the existing client does not check that geometric compatibility.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys

import centrifuge_robot_pickup as pickup

sys.path.insert(0,str(pickup.ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros.protocol import scenario

SCENARIO='cf01_robot_to_rack'
DEFAULT_OUTPUT=pickup.ROOT/'exports/generated/cf01-robot-pickup-ros2/scenarios.json'


def source_hashes(scene):
    workspace=pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))
    paths=[pickup.SOURCE,*[pickup.ROOT/path for path in scene['sources'].values()],
           *pickup.workspace.source_dependencies(workspace)]
    return {str(path.relative_to(pickup.ROOT)):pickup.robot.digest(path) for path in paths}


def robot_description_requirements(scene,arm=None,robot_sha256=None):
    """Share variant/fixture/TCP metadata without evaluating a motion program."""
    arm=arm or pickup.arm_source(scene)
    fixture=scene['arm_fixture'];kin=pickup.Kinematics(arm,scene)
    flange_link=arm['flange_reference']['link']
    flange_frame=pickup.robot.frame(next(joint for joint in arm['joints'] if joint['child']==flange_link),pickup.robot.parameters(arm))
    # URDF link origins are joint frames, not the source construction origin.
    tcp=pickup.robot.transform(pickup.robot.inverse(flange_frame),[kin.flange[0],kin.flange[1],kin.flange[2]+kin.length])
    return {'robot_source':scene['sources']['robot'],
            'robot_source_sha256':robot_sha256 or pickup.robot.digest(pickup.ROOT/scene['sources']['robot']),
            'parameter_overrides_mm':copy.deepcopy(scene.get('robot_parameter_overrides_mm',{})),
            'base_position_m':[value/1000 for value in fixture['position_mm']],
            'base_yaw_rad':math.radians(fixture['yaw_deg']),
            'tcp_parent_link':flange_link.lower(),'tcp_position_in_parent_m':[value/1000 for value in tcp],
            'compatibility_verified':False,
            'compatibility_check':'Required before execution; not performed by the trajectory client'}


def configuration():
    """Preserve every source sample; validate with the existing client contract."""
    scene_digest=pickup.robot.digest(pickup.SOURCE)
    scene=pickup.load();before=source_hashes(scene)
    if before[str(pickup.SOURCE.relative_to(pickup.ROOT))]!=scene_digest:
        raise ValueError('Pickup sources changed during ROS export; retry from a stable source revision')
    data=pickup.trajectory(scene);arm=pickup.arm_source(scene)
    points=[{'time_s':sample['time_s'],
             'positions_rad':[math.radians(value) for value in sample['joints_deg']]}
            for sample in data['samples']]
    config={'joint_names':[joint['id'].lower() for joint in arm['joints']],
            'limits_rad':[[math.radians(value) for value in joint['limits_deg']] for joint in arm['joints']],
            'scenarios':[{'id':SCENARIO,'points':points}],
            # Same simulation setting as build_ros2.generate, not a motor rating.
            'velocity_limit_rad_s':0.5,'mode':'mock',
            'limit_status':'Mock validation setting, not a qualified hardware limit',
            'source_files_sha256':before,
            'exporter_sha256':pickup.robot.digest(Path(__file__)),
            'included_channels':['six_arm_joints'],
            'excluded_channels':['gripper','CF01 station commands','live collision, sensor and quality feedback'],
            'robot_description_requirements':robot_description_requirements(scene,arm,data['robot_sha256']),
            'verification':{'ros_runtime':False,'hardware_execution':False,
                            'integrated_CF01_cycle':False}}
    if source_hashes(scene)!=before:raise ValueError('Pickup sources changed during ROS export; retry from a stable source revision')
    scenario(config,SCENARIO)
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args();config=configuration()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(config,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    points=config['scenarios'][0]['points']
    print(json.dumps({'output':str(args.output),'scenario':SCENARIO,'points':len(points),
                      'duration_s':points[-1]['time_s'],'robot_description_compatibility_verified':False,
                      'ros_runtime_verified':False,'hardware_verified':False},indent=2))


if __name__=='__main__':main()
