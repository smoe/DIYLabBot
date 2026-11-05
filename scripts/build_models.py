"""One reproducible command: compile spec, build both CADs, run scenario, compare.

Run with normal Python: python scripts/build_models.py
The FreeCAD backend runs in FreeCAD's bundled Python. SolidCraft CLI uses a
separate headless process and never replaces a design open in the desktop app.
"""
from pathlib import Path
import argparse
import json
import math
import shutil
import subprocess
import sys
import time

import robot_spec as model
import robot_services
import robot_cameras


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freecad-python",default=str(Path.home()/"AppData/Local/Programs/FreeCAD 27.1/bin/python.exe"))
    parser.add_argument("--solidcraft-cli",default=shutil.which("solidcraft-cli") or "solidcraft-cli")
    parser.add_argument("--ros2",action="store_true",help="Also generate ROS 2 meshes, description and protocol configuration")
    args=parser.parse_args()
    started=time.monotonic(); spec=model.load(); digest=model.digest(model.SPEC)
    revision=digest[:12]; counter=1
    while (model.ROOT/"cad/generated"/revision).exists():
        counter+=1; revision=digest[:12]+"-r"+str(counter)
    artifact_dir=model.ROOT/"cad/generated"/revision
    artifact_dir.mkdir(parents=True,exist_ok=True)
    export_dir=model.ROOT/"exports/generated"/revision
    export_dir.mkdir(parents=True,exist_ok=True)
    (export_dir/"model-source.json").write_text(json.dumps(spec,indent=2)+"\n",encoding="utf-8")
    camera_report=export_dir/"cameras-report.json"
    camera_report.write_text(json.dumps({"spec_sha256":digest,**robot_cameras.audit(spec)},indent=2)+"\n",encoding="utf-8")
    services_report=export_dir/"services-report.json"
    robot_services.write_report(spec,services_report,digest)
    component_report=export_dir/"components-report.json"
    if "vendor_library" in spec:
        from robot_components import audit
        component_report.write_text(json.dumps({"spec_sha256":digest,"library":spec["vendor_library"],**audit(spec)},indent=2)+"\n",encoding="utf-8")
    commands=export_dir/"solidcraft.commands.json"
    commands.write_text(json.dumps({"spec_sha256":digest,"commands":model.solidcraft_commands(spec)},indent=2)+"\n",encoding="utf-8")
    trace={s["id"]:model.sample_scenario(spec,s["id"]) for s in spec["scenarios"]}
    (export_dir/"scenario-traces.json").write_text(json.dumps({"spec_sha256":digest,"scenarios":trace},indent=2)+"\n",encoding="utf-8")
    solidcraft=artifact_dir/(spec["id"]+".solidcraft"); freecad=artifact_dir/(spec["id"]+".FCStd")
    solid_measurements=export_dir/"solidcraft-measurements.json"; free_report=export_dir/"freecad-validation.json"
    print("Building SolidCraft from neutral specification...",flush=True)
    subprocess.run([args.solidcraft_cli,"run",str(commands),"--save",str(solidcraft),"--out",str(export_dir/(spec["id"]+".step")),"--json-out",str(solid_measurements)],check=True,cwd=model.ROOT)
    print("Checking six SolidCraft joint movements...",flush=True)
    from check_solidcraft_joints import check
    joint_report=check(spec,solidcraft,export_dir,args.solidcraft_cli)
    print("Building and checking FreeCAD and protocol samples...",flush=True)
    subprocess.run([args.freecad_python,str(model.ROOT/"scripts/build_neutral_freecad.py"),str(freecad),str(free_report)],check=True,cwd=model.ROOT)
    view_report=export_dir/"freecad-presentation.json"
    print("Saving FreeCAD colours and UMR visibility...",flush=True)
    subprocess.run([sys.executable,str(model.ROOT/"scripts/freecad/persist_view.py"),str(freecad),str(view_report)],check=True,cwd=model.ROOT,timeout=30)
    sc=json.loads(solid_measurements.read_text(encoding="utf-8")); fc=json.loads(free_report.read_text(encoding="utf-8"))
    fc["model_sha256"]=model.digest(freecad)
    free_report.write_text(json.dumps(fc,indent=2)+"\n",encoding="utf-8")
    sc_bodies={b["name"]:b for b in sc["bodies"]}; comparisons=[]
    for body in fc["geometry"]:
        other=sc_bodies[body["body"]]
        error=math.sqrt(sum((a-b)**2 for a,b in zip(body["world_center_of_mass_mm"],other["center_of_mass"])))
        volume_error=abs(body["volume_mm3"]-other["volume_mm3"])/body["volume_mm3"]
        comparisons.append({"body":body["body"],"com_error_mm":error,"relative_volume_error":volume_error,"passed":error<0.01 and volume_error<0.001})
    report={"spec_sha256":digest,"spec":"model/robot.json","passed":bool(fc["passed"] and len(sc_bodies)==len(comparisons) and all(c["passed"] for c in comparisons)),
            "artifacts":{name:str(path.relative_to(model.ROOT)).replace("\\","/") for name,path in {"solidcraft":solidcraft,"freecad":freecad,"freecad_report":free_report,"freecad_presentation":view_report,"solidcraft_measurements":solid_measurements}.items()},
            "artifact_sha256":{name:model.digest(path) for name,path in {"solidcraft":solidcraft,"freecad":freecad}.items()},
            "body_comparisons":comparisons,"elapsed_s":time.monotonic()-started,
            "collision_check":"FreeCAD BRep at protocol samples, not continuous collision checking",
            "services_report":str(services_report.relative_to(model.ROOT)).replace("\\","/"),
            "cameras_report":str(camera_report.relative_to(model.ROOT)).replace("\\","/"),
            "components_report":str(component_report.relative_to(model.ROOT)).replace("\\","/") if component_report.exists() else None,
            "solidcraft_joint_report":str(joint_report.relative_to(model.ROOT)).replace("\\","/"),
            "generator_sha256":{str(path.relative_to(model.ROOT)).replace("\\","/"):model.digest(path) for path in [Path(__file__),model.ROOT/"scripts/robot_spec.py",model.ROOT/"scripts/robot_components.py",model.ROOT/"scripts/servo_mounting_design.py",model.ROOT/"scripts/x6_mounting_design.py",model.ROOT/"scripts/prepare_servo_components.py",model.ROOT/"scripts/robot_cameras.py",model.ROOT/"scripts/build_neutral_freecad.py",model.ROOT/"scripts/build_ros2.py",model.ROOT/"scripts/check_solidcraft_joints.py",model.ROOT/"scripts/freecad/persist_view.py",model.ROOT/"scripts/freecad/solidcraftbot_freecad.py"]},
            "limitations":["Selected vendor exterior geometry; X2/X4/X6 nominal locating fits and screw stacks calculated under explicit assumptions; pin retention, physical fits, loads and X6 housing thread-depth reference remain unverified", "No dynamics, tooth contact, fluid simulation or hardware protocol execution", "Cable topology audited; physical routing, bend, torsion and feedback hardware not verified", "No manufacturing, load, stiffness or precision qualification"]}
    destination=model.ROOT/"exports/generated/build-report.json"
    destination.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if not report["passed"]: raise SystemExit("Cross-CAD validation failed; see "+str(destination))
    print("Both CADs and sampled protocol checks passed in %.2f s"%report["elapsed_s"],flush=True)
    print("Model revision:",revision,flush=True)
    if args.ros2:
        subprocess.run([sys.executable,str(model.ROOT/"scripts/build_ros2.py"),"--freecad-python",args.freecad_python],check=True,cwd=model.ROOT)
        report["ros2_generated"]=True
        report["ros2_runtime_tested"]=False
        destination.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if spec.get("mobile_base"):
        mobile_command=[sys.executable,str(model.ROOT/"scripts/build_mobile_base.py"),"--freecad-python",args.freecad_python,"--solidcraft-cli",args.solidcraft_cli]
        if args.ros2: mobile_command.append("--ros2")
        subprocess.run(mobile_command,check=True,cwd=model.ROOT)
        report["mobile_base_report"]="cad/mobile-base-mb01/shared-build-report.json"
        destination.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__": main()
