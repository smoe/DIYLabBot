"""Generate ROS 2 assets from the same neutral model and current CAD build."""
from pathlib import Path
import argparse
import tool_paths
import json
import math
import subprocess
import xml.etree.ElementTree as ET

import robot_spec as model
import robot_services
import robot_cameras

PACKAGE=model.ROOT/"ros2_ws/src/solidcraftbot_ros"


def rpy(matrix):
    pitch=math.asin(max(-1.,min(1.,-matrix[2][0])))
    if abs(math.cos(pitch))>1e-9:
        return [math.atan2(matrix[2][1],matrix[2][2]),pitch,math.atan2(matrix[1][0],matrix[0][0])]
    return [0.,pitch,math.atan2(-matrix[0][1],matrix[1][1])]


def numbers(values): return " ".join("%.12g"%v for v in values)
def ros_name(link): return "base_link" if link=="L0_Base" else link.lower()


def generate(spec,geometry,velocity=0.5,effort=1.0):
    p=model.parameters(spec); frames={spec["links"][0]["id"]:model.identity()}
    frames.update({j["child"]:model.frame(j,p) for j in spec["joints"]})
    robot=ET.Element("robot",name="solidcraftbot_umr")
    for link in spec["links"]:
        node=ET.SubElement(robot,"link",name=ros_name(link["id"]))
        visual=ET.SubElement(node,"visual")
        shape=ET.SubElement(visual,"geometry")
        ET.SubElement(shape,"mesh",filename="package://solidcraftbot_ros/meshes/"+geometry["links"][link["id"]]["mesh"])
        material=ET.SubElement(visual,"material",name=link["id"]+"_concept")
        ET.SubElement(material,"color",rgba=numbers([v/255 for v in link["appearance"]["color"]]+[1]))
        for box in geometry["links"][link["id"]].get("servo_visual_boxes",[]):
            visual=ET.SubElement(node,"visual",name=box["body"]+"_servo_box")
            ET.SubElement(visual,"origin",xyz=numbers(box["xyz_m"]),rpy=numbers(rpy(box["rotation_matrix"])))
            shape=ET.SubElement(visual,"geometry"); ET.SubElement(shape,"box",size=numbers(box["size_m"]))
            material=ET.SubElement(visual,"material",name=box["body"]+"_servo")
            ET.SubElement(material,"color",rgba=numbers([v/255 for v in box["color"]]+[1]))
        marking=geometry["links"][link["id"]].get("marking")
        for camera_visual in geometry["links"][link["id"]].get("camera_visuals",[]):
            visual=ET.SubElement(node,"visual",name=camera_visual["body"])
            shape=ET.SubElement(visual,"geometry")
            ET.SubElement(shape,"mesh",filename="package://solidcraftbot_ros/meshes/"+camera_visual["mesh"])
            material=ET.SubElement(visual,"material",name=camera_visual["body"]+"_concept")
            ET.SubElement(material,"color",rgba=numbers([v/255 for v in camera_visual["color"]]+[camera_visual["opacity"]]))
        if marking:
            visual=ET.SubElement(node,"visual",name="UMR_marking")
            shape=ET.SubElement(visual,"geometry")
            ET.SubElement(shape,"mesh",filename="package://solidcraftbot_ros/meshes/"+marking["mesh"])
            material=ET.SubElement(visual,"material",name="UMR_ink")
            ET.SubElement(material,"color",rgba=numbers([v/255 for v in marking["color"]]+[1]))
        for index,box in enumerate(geometry["links"][link["id"]]["collision_boxes"]):
            collision=ET.SubElement(node,"collision",name=box["body"]+"_conservative_box")
            ET.SubElement(collision,"origin",xyz=numbers(box["xyz_m"]),rpy=numbers(rpy(box["rotation_matrix"])))
            shape=ET.SubElement(collision,"geometry"); ET.SubElement(shape,"box",size=numbers(box["size_m"]))
    for joint in spec["joints"]:
        name=joint["id"].lower()
        node=ET.SubElement(robot,"joint",name=name,type="revolute")
        ET.SubElement(node,"parent",link=ros_name(joint["parent"]))
        ET.SubElement(node,"child",link=ros_name(joint["child"]))
        relative=model.multiply(model.inverse(frames[joint["parent"]]),frames[joint["child"]])
        ET.SubElement(node,"origin",xyz=numbers([relative[i][3]/1000 for i in range(3)]),rpy=numbers(rpy(relative)))
        ET.SubElement(node,"axis",xyz="0 0 1")
        ET.SubElement(node,"limit",lower=str(math.radians(joint["limits_deg"][0])),upper=str(math.radians(joint["limits_deg"][1])),velocity=str(velocity),effort=str(effort))
    ET.SubElement(robot,"link",name="tool0")
    tool_joint=ET.SubElement(robot,"joint",name="flange_reference",type="fixed")
    ET.SubElement(tool_joint,"parent",link=ros_name(spec["flange_reference"]["link"]))
    ET.SubElement(tool_joint,"child",link="tool0")
    point=model.transform(model.inverse(frames[spec["flange_reference"]["link"]]),[model.evaluate(v,p) for v in spec["flange_reference"]["point"]])
    ET.SubElement(tool_joint,"origin",xyz=numbers([v/1000 for v in point]),rpy="0 0 0")
    for link,camera in robot_cameras.cameras(spec):
        name=camera["id"].lower()+"_optical"
        ET.SubElement(robot,"link",name=name)
        joint=ET.SubElement(robot,"joint",name=name+"_provisional",type="fixed")
        ET.SubElement(joint,"parent",link=ros_name(link))
        ET.SubElement(joint,"child",link=name)
        relative=model.multiply(model.inverse(frames[link]),model.frame({"frame":camera["frame"]},p))
        ET.SubElement(joint,"origin",xyz=numbers([relative[i][3]/1000 for i in range(3)]),rpy=numbers(rpy(relative)))
    control=ET.SubElement(robot,"ros2_control",name="UMRMockSystem",type="system")
    hardware=ET.SubElement(control,"hardware")
    ET.SubElement(hardware,"plugin").text="mock_components/GenericSystem"
    ET.SubElement(hardware,"param",name="calculate_dynamics").text="false"
    for joint in spec["joints"]:
        node=ET.SubElement(control,"joint",name=joint["id"].lower())
        command=ET.SubElement(node,"command_interface",name="position")
        ET.SubElement(command,"param",name="min").text=str(math.radians(joint["limits_deg"][0]))
        ET.SubElement(command,"param",name="max").text=str(math.radians(joint["limits_deg"][1]))
        state=ET.SubElement(node,"state_interface",name="position")
        ET.SubElement(state,"param",name="initial_value").text=str(math.radians(joint["home_deg"]))
    ET.indent(robot)
    (PACKAGE/"urdf/robot.urdf").write_text(ET.tostring(robot,encoding="unicode")+"\n",encoding="utf-8")
    names=[j["id"].lower() for j in spec["joints"]]
    controllers={"/**/controller_manager":{"ros__parameters":{"update_rate":100,"enforce_command_limits":True,
                    "joint_state_broadcaster":{"type":"joint_state_broadcaster/JointStateBroadcaster"},
                    "arm_controller":{"type":"joint_trajectory_controller/JointTrajectoryController"}}},
                 "/**/arm_controller":{"ros__parameters":{"joints":names,"command_interfaces":["position"],"state_interfaces":["position"],
                    "allow_partial_joints_goal":False,"constraints":{"goal_time":2.0,"stopped_velocity_tolerance":0.01}}}}
    # JSON is a YAML 1.2 subset and is parsed by ROS's YAML parameter reader.
    (PACKAGE/"config/controllers.yaml").write_text(json.dumps(controllers,indent=2)+"\n",encoding="utf-8")
    scenarios=[]
    for scenario in spec["scenarios"]:
        cumulative=0.; points=[]
        for step in scenario["steps"]:
            cumulative+=step["duration_s"]
            points.append({"step":step["id"],"time_s":cumulative,"positions_rad":[math.radians(step["joints_deg"][j["id"]]) for j in spec["joints"]]})
        scenarios.append({"id":scenario["id"],"points":points})
    protocol={"spec_sha256":model.digest(model.SPEC),"joint_names":names,
              "limits_rad":[[math.radians(v) for v in j["limits_deg"]] for j in spec["joints"]],
              "scenarios":scenarios,"mode":"mock","velocity_limit_rad_s":velocity,
              "effort_limit_nm":effort,"limit_status":"Simulation settings, not selected motor ratings"}
    (PACKAGE/"config/scenarios.json").write_text(json.dumps(protocol,indent=2)+"\n",encoding="utf-8")
    robot_services.write_report(spec,PACKAGE/"config/services.json",model.digest(model.SPEC))
    (PACKAGE/"config/cameras.json").write_text(json.dumps({"spec_sha256":model.digest(model.SPEC),
        "optical_frame_convention":"+Z forward, +X right, +Y down; uncalibrated",
        "image_topics_implemented":False,**robot_cameras.audit(spec)},indent=2)+"\n",encoding="utf-8")
    return robot,protocol


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=False)
    args=parser.parse_args(); tool_paths.resolve_tool_arguments(parser, args); spec=model.load()
    build=json.loads((model.ROOT/"exports/generated/build-report.json").read_text(encoding="utf-8"))
    if build["spec_sha256"]!=model.digest(model.SPEC) or not build["passed"]: raise ValueError("Run scripts/build_models.py first")
    for folder in ["config","urdf","meshes"]: (PACKAGE/folder).mkdir(parents=True,exist_ok=True)
    command="import sys; sys.path.insert(0,sys.argv[1]); import build_neutral_freecad as b; b.export_ros_geometry(b.model.load(),sys.argv[2],sys.argv[3])"
    subprocess.run([args.freecad_python,"-c",command,str(model.ROOT/"scripts"),str(model.ROOT/build["artifacts"]["freecad"]),str(PACKAGE)],check=True,cwd=model.ROOT)
    geometry=json.loads((PACKAGE/"config/geometry.json").read_text(encoding="utf-8"))
    generate(spec,geometry)
    print("ROS 2 package assets generated from",model.digest(model.SPEC)[:12],flush=True)


if __name__=="__main__": main()
