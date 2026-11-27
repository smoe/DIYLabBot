"""Build both stationary camera variants from a shared portable model."""

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

import build_extraction_kit_station as checks
import stationary_camera as model
import tool_paths
from tube_cam_model import pose_change_point


def source_pins():
    producers = (
        "stationary_camera.py",
        "build_stationary_cameras.py",
        "build_stationary_cameras_freecad.py",
        "build_extraction_kit_station.py",
        "extraction_kit_station.py",
        "build_tube_carrier_freecad.py",
        "tube_carrier_model.py",
        "tube_cam_model.py",
        "build_neutral_freecad.py",
        "freecad/solidcraftbot_freecad.py",
        "freecad/persist_station_view.py",
        "freecad/persist_view.py",
        "assembly_model.py",
        "robot_spec.py",
        "robot_cameras.py",
        "robot_components.py",
        "tool_paths.py",
    )
    paths = [model.SOURCE, model.SCHEMA, *(model.ROOT / "scripts" / name for name in producers)]
    return {checks.relative(path): checks.robot_spec.digest(path) for path in paths}


def new_directory(source_sha256):
    parent = model.ROOT / "exports/generated"
    parent.mkdir(parents=True, exist_ok=True)
    stem = "stationary-cameras-" + source_sha256[:12]
    index = 1
    while True:
        output = parent / (stem if index == 1 else f"{stem}-r{index}")
        try:
            output.mkdir()
            return output
        except FileExistsError:
            index += 1


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def pose_checks(source, p, baseline, baseline_values, samples, geometry):
    """Check measured rigid transforms using the shared component kinematics."""
    body_components = {body["id"]: body["component"] for body in source["bodies"]}
    neutral = {body["body"]: body for body in baseline}
    results = []
    for sample, measured in zip(samples, geometry, strict=True):
        values = sample["joint_values"]
        errors = []
        for body in measured:
            name = body["body"]
            reference = neutral[name]
            expected = pose_change_point(
                source, body_components[name], reference["world_center_of_mass_mm"], p,
                baseline_values, values,
            )
            errors.append(math.dist(expected, body["world_center_of_mass_mm"]))
        maximum = max(errors)
        results.append({"id": sample["id"], "joint_values_deg": values,
                        "maximum_center_error_mm": maximum, "passed": maximum < 0.01})
    return results


def solidcraft_geometry(args, spec, p, source, output):
    build_script = output / "build.commands.json"
    initial = output / "solidcraft-default.json"
    native = output / (spec["id"] + ".sc")
    checks.write(build_script, {"commands": model.solidcraft_commands(spec, p)})
    subprocess.run([args.solidcraft_cli, "run", str(build_script), "--save", str(native),
                    "--json-out", str(initial), "--quiet"], cwd=model.ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    baseline = checks.measurements(read(initial), source, backend="solidcraft")
    native_digest = checks.robot_spec.digest(native)
    measured = []
    for index, sample in enumerate(model.samples(spec, p)):
        values = sample["joint_values"]
        if values == model.pose(spec, p):
            measured.append(baseline)
            continue
        script = output / f"pose-{index:02d}.commands.json"
        result = output / f"solidcraft-pose-{index:02d}.json"
        commands = [{"command": "joint.drive", "params": {"joint": name, "value": value, "quiet": True}}
                    for name, value in values.items()]
        commands.append({"command": "joint.solve", "params": {}})
        checks.write(script, {"commands": commands})
        subprocess.run([args.solidcraft_cli, "eval", str(script), "--in", str(native),
                        "--json-out", str(result)], cwd=model.ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        measured.append(checks.measurements(read(result), source, backend="solidcraft"))
    if checks.robot_spec.digest(native) != native_digest:
        raise ValueError("SolidCraft pose checks modified the saved camera model")
    return native, baseline, measured


def freecad_geometry(args, variant, spec, source, output):
    native = output / (spec["id"] + ".FCStd")
    result = output / "freecad-measurements.json"
    subprocess.run([
        args.freecad_python, str(model.ROOT / "scripts/build_stationary_cameras_freecad.py"),
        variant, str(native), str(result),
    ], cwd=model.ROOT, env=checks.freecad_environment(args.freecad_python), check=True)
    result = read(result)
    initial = checks.measurements({"geometry": result["default_geometry"]}, source, backend="freecad")
    samples = [checks.measurements({"geometry": data}, source, backend="freecad")
               for data in result["sample_geometry"]]
    sys.path.insert(0, str(model.ROOT / "scripts/freecad"))
    from persist_station_view import persist
    styles = []
    for body in source["bodies"]:
        appearance = body["appearance"]
        color = "#" + "".join(f"{channel:02x}" for channel in appearance["color"])
        styles.append({**body, "appearance": {**appearance, "color": color}})
    presentation = persist(native, {"bodies": styles}, initial)
    return native, initial, samples, presentation


def build_variant(args, catalog, variant, pins, output):
    spec = model.materialize(catalog, variant)
    p = model.parameters(spec)
    source = model.expanded(spec, p)
    samples = model.samples(spec, p)
    baseline_values = model.pose(spec, p)
    output.mkdir()
    artifacts, backend_poses, geometry = {}, {}, {}
    presentation = None
    if args.backend in {"both", "solidcraft"}:
        native, baseline, geometry["solidcraft"] = solidcraft_geometry(args, spec, p, source, output)
        artifacts["solidcraft"] = native
        backend_poses["solidcraft"] = pose_checks(source, p, baseline, baseline_values, samples,
                                                  geometry["solidcraft"])
    if args.backend in {"both", "freecad"}:
        native, baseline, geometry["freecad"], presentation = freecad_geometry(args, variant, spec, source, output)
        artifacts["freecad"] = native
        backend_poses["freecad"] = pose_checks(source, p, baseline, baseline_values, samples, geometry["freecad"])
    comparisons = None
    if args.backend == "both":
        comparisons = [{"id": sample["id"], "bodies": checks.compare(sc, fc)}
                       for sample, sc, fc in zip(samples, geometry["solidcraft"], geometry["freecad"], strict=True)]
    passed = (all(row["passed"] for result in backend_poses.values() for row in result)
              and (comparisons is None or all(body["passed"] for row in comparisons for body in row["bodies"])))
    checks.verify_pins(pins)
    return {
        "variant": variant,
        "passed": passed,
        "body_count": len(source["bodies"]),
        "default_optical_frame": model.optical_frame(spec, p),
        "sample_optical_frames": [
            {"id": sample["id"], "frame": model.optical_frame(spec, p, sample["joint_values"])}
            for sample in samples
        ],
        "sample_pose_checks": backend_poses,
        "cross_cad_comparisons": comparisons,
        "freecad_presentation": presentation,
        "files": {name: checks.relative(path) for name, path in artifacts.items()},
        "artifact_sha256": {name: checks.robot_spec.digest(path) for name, path in artifacts.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("freecad", "solidcraft", "both"), default="both")
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args()
    tool_paths.resolve_tool_arguments(parser, args, required=checks.required_tools(args.backend))
    pins = source_pins()
    catalog = model.load()
    source_sha256 = pins[checks.relative(model.SOURCE)]
    output = new_directory(source_sha256)
    cases = []
    for variant in model.VARIANTS:
        print(f"Building stationary camera: {variant}", flush=True)
        cases.append(build_variant(args, catalog, variant, pins, output / variant))
    report = {
        "format": "solidcraftbot.stationary-camera-build/1",
        "source": checks.relative(model.SOURCE),
        "source_sha256": source_sha256,
        "source_files_sha256": pins,
        "backend": args.backend,
        "cross_cad_checked": args.backend == "both",
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
        "scope": "Native geometry and discrete pose comparison of illustrative stationary camera envelopes",
        "limits": {
            "continuous_clearance_checked": False,
            "manufacturing_released": False,
            "optical_calibration": False,
            "hardware_tested": False,
        },
    }
    checks.verify_pins(pins)
    path = output / "build-report.json"
    checks.write(path, report)
    if not report["passed"]:
        raise SystemExit(f"Stationary camera comparison failed: {checks.relative(path)}")
    print(f"Stationary camera models passed: {checks.relative(path)}", flush=True)


if __name__ == "__main__":
    main()
