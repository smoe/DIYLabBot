"""Nominal X6 locating and fastener stack calculations; no CAD dependency.

Results are design checks under explicit assumptions, not thread-stripping,
preload, fatigue, accuracy or physical-sample qualification.
"""
import math

def analyse(source, plate_thickness_mm=None):
    from servo_mounting_design import fastener_stacks
    result=fastener_stacks(source,plate_thickness_mm)
    pins=source["housing"]["locating_pins"]; fit=pins["plate_fit"]
    pin_min=pins["outside_diameter_mm"]+min(pins["outside_diameter_tolerance_mm"])
    pin_max=pins["outside_diameter_mm"]+max(pins["outside_diameter_tolerance_mm"])
    hole_min,hole_max=fit["round_bore_limits_mm"]
    width_min,width_max=fit["slot_width_limits_mm"]
    if min(hole_min-pin_max,width_min-pin_max)<-1e-9:raise ValueError("Interference with X6 locating sleeves")
    span=source["housing"]["bolt_circle_mm"]
    radial=(fit["slot_length_limits_mm"][0]-pin_max)/2
    thermal=span*abs(fit["assumed_plate_alpha_per_k"]-fit["assumed_motor_pitch_alpha_per_k"])*fit["assumed_temperature_change_k"]
    budget=fit["assumed_vendor_pitch_error_mm"]+fit["machined_pitch_error_allowance_mm"]+thermal
    if radial<budget:raise ValueError("X6 radial slot cannot accommodate the stated pitch/thermal budget")
    angle=math.degrees(math.asin(((hole_max-pin_min)+(width_max-pin_min))/2/span))
    result["locating"]={"pin_diameter_limits_mm":[pin_min,pin_max],"round_bore_limits_mm":[hole_min,hole_max],
        "diametral_clearance_range_mm":[hole_min-pin_max,hole_max-pin_min],
        "minimum_radial_slot_allowance_mm":radial,"assumed_radial_error_budget_mm":budget,
        "assumed_differential_thermal_growth_mm":thermal,"assembly_angular_free_play_half_range_deg":angle,
        "illustrative_400mm_lever_error_mm":400*math.sin(math.radians(angle)),
        "notes":"Free-play calculation excludes position, coaxiality and load errors. Clamping/calibration still required; zero minimum clearance needs a hand-fit check."}
    return result


if __name__=="__main__":
    import argparse,hashlib,json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",type=Path,help="Save calculation and current source/build provenance as JSON")
    args=parser.parse_args()
    source=root/"model/x6-mounting-interface.json"
    result=analyse(json.loads(source.read_text(encoding="utf-8")))
    paths=[source,Path(__file__),root/"model/robot.json",root/"model/robot.schema.json",
           root/"scripts/prepare_servo_components.py",root/"scripts/robot_components.py",
           root/"scripts/robot_spec.py",root/"scripts/build_neutral_freecad.py",
           root/"scripts/build_models.py",root/"scripts/build_ros2.py",
           root/"cad/vendor/myactuator/component-library.json"]
    result["source_files_sha256"]={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    build=json.loads((root/"exports/generated/build-report.json").read_text())
    if not build["passed"] or build["spec_sha256"]!=result["source_files_sha256"]["model/robot.json"]:
        raise ValueError("Build does not match the current arm source")
    result["artifacts"]=build["artifacts"];result["artifact_sha256"]=build["artifact_sha256"]
    native=json.loads((root/build["artifacts"]["freecad_report"]).read_text())
    result["screw_head_clearance"]=native["x6_screw_head_clearance"]
    result["cross_cad_body_count"]=len(build["body_comparisons"])
    result["passed"]=build["passed"] and result["screw_head_clearance"]["passed"]
    rendered=json.dumps(result,indent=2)+"\n"
    if args.report:
        target=args.report.resolve()
        if not target.is_relative_to(root):raise ValueError("Keep report inside project")
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(rendered,encoding="utf-8")
        print("X6 nominal design checks:",result["passed"],str(target))
    else:print(rendered,end="")
