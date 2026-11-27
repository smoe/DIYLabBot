"""Shared stationary camera geometry and optical frames for two mount variants."""

import copy
import json
import math

import assembly_model
import robot_spec as robot
import tube_carrier_model as portable
from tube_cam_model import matrix


ROOT = robot.ROOT
SOURCE = ROOT / "model/stationary-camera.catalog.json"
SCHEMA = ROOT / "model/stationary-camera.schema.json"
VARIANTS = ("fixed", "pan_tilt")
LENGTHS = {
    "base_depth", "base_width", "base_height", "head_depth", "head_width",
    "head_height", "lens_radius", "lens_depth", "pivot_z", "turret_radius",
    "turret_height", "yoke_thickness", "yoke_clearance", "yoke_depth", "pin_radius",
}
ANGLES = {"pan_travel", "tilt_travel"}
digest = robot.digest
evaluate = robot.evaluate


def load(path=SOURCE):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if (
        set(catalog) != {"format", "status", "units", "variants", "parameters", "limitations"}
        or catalog["format"] != "solidcraftbot.stationary-camera/1"
        or catalog["status"] != "concept_not_for_manufacture"
        or catalog["units"] != {"length": "mm", "angle": "deg"}
        or catalog["variants"] != list(VARIANTS)
    ):
        raise ValueError("Invalid stationary camera catalog")
    if set(catalog["parameters"]) != LENGTHS | ANGLES:
        raise ValueError("Incomplete stationary camera parameters")
    for name, row in catalog["parameters"].items():
        if (
            set(row) != {"expression", "unit", "range", "description"}
            or row["unit"] != ("mm" if name in LENGTHS else "deg")
            or not isinstance(row["description"], str)
            or not row["description"]
            or not isinstance(row["range"], list)
            or len(row["range"]) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in [row["expression"], *row["range"]])
            or not 0 < row["range"][0] <= row["expression"] <= row["range"][1]
        ):
            raise ValueError("Invalid camera parameter: " + name)
    if not isinstance(catalog["limitations"], list) or not catalog["limitations"] or not all(
        isinstance(item, str) and item for item in catalog["limitations"]
    ):
        raise ValueError("Camera model limitations are required")
    for variant in VARIANTS:
        parameters(materialize(catalog, variant))
    return catalog


def materialize(catalog, variant):
    if variant not in VARIANTS:
        raise ValueError("Unknown stationary camera variant: " + str(variant))
    return {
        "id": "StationaryCameraFixed" if variant == "fixed" else "StationaryCameraPanTilt",
        "variant": variant,
        "status": catalog["status"],
        "parameters": copy.deepcopy(catalog["parameters"]),
    }


def parameters(spec, overrides=None):
    p = robot.parameters(assembly_model.parameter_variant(spec, overrides))
    if 2 * p["lens_radius"] > min(p["head_width"], p["head_height"]):
        raise ValueError("Lens does not fit the camera face")
    if p["pivot_z"] - p["head_height"] / 2 <= p["base_height"]:
        raise ValueError("Fixed post must have positive height")
    if spec["variant"] == "pan_tilt":
        yoke_floor = p["base_height"] + p["turret_height"] + p["yoke_thickness"]
        swing_radius = math.hypot(p["head_depth"] / 2 + p["lens_depth"], p["head_height"] / 2)
        if p["pivot_z"] - swing_radius <= yoke_floor:
            raise ValueError("Head envelope can reach the yoke bridge")
        if 2 * p["turret_radius"] > min(p["base_depth"], p["base_width"]):
            raise ValueError("Turntable does not fit the mounting plate")
        if p["pan_travel"] > 180 or p["tilt_travel"] >= 90:
            raise ValueError("Unsupported stationary camera articulation")
    return p


def expanded(spec, p):
    """Lower the family to the existing portable body and joint contract."""
    steerable = spec["variant"] == "pan_tilt"
    head = "Head" if steerable else "Mount"
    result = {
        "bodies": [],
        "operations": [],
        "components": [{"id": "Mount", "grounded": True}],
        "joints": [],
    }
    if steerable:
        result["components"] += [{"id": name, "grounded": False} for name in ("Turret", "Head")]
        for name, parent, child, axis, x, origin in (
            ("Pan", "Mount", "Turret", [0, 0, 1], [1, 0, 0], [0, 0, "base_height"]),
            ("Tilt", "Turret", "Head", [0, 1, 0], [1, 0, 0], [0, 0, "pivot_z"]),
        ):
            travel = name.lower() + "_travel"
            result["joints"].append({
                "id": name, "type": "revolute", "parent": parent, "child": child,
                "axis": axis, "reference_x": x, "origin": origin,
                "limit_parameter": travel, "limits_deg": [0, p[travel]],
            })

    def create(name, owner, role, shape, color):
        result["bodies"].append({
            "id": name, "component": owner, "role": role,
            "appearance": {"color": color, "opacity": 1},
        })
        result["operations"].append({"id": name, "body": name, "action": "create", "shape": shape})

    metal, housing, glass = [124, 145, 161], [218, 231, 234], [39, 64, 83]

    def box(name, owner, role, origin, size, color=metal):
        create(name, owner, role, {"kind": "box", "origin": origin, "size": size}, color)

    def cylinder(name, owner, role, origin, radius, height, axis, color=metal):
        create(name, owner, role, {"kind": "cylinder", "origin": origin, "radius": radius,
                                   "height": height, "axis": axis}, color)

    box("MountingPlate", "Mount", "camera_mount", ["-base_depth/2", "-base_width/2", 0],
        ["base_depth", "base_width", "base_height"])
    if steerable:
        cylinder("PanTurntable", "Turret", "concept_camera_turntable", [0, 0, "base_height"],
                 "turret_radius", "turret_height", [0, 0, 1])
        offset = "head_width/2+yoke_clearance+yoke_thickness"
        box("YokeBridge", "Turret", "concept_camera_yoke",
            ["-yoke_depth/2", f"-({offset})", "base_height+turret_height"],
            ["yoke_depth", f"2*({offset})", "yoke_thickness"])
        for suffix, sign, origin_y in (
            ("Left", 1, "head_width/2+yoke_clearance"),
            ("Right", -1, f"-({offset})"),
        ):
            box("Yoke" + suffix, "Turret", "concept_camera_yoke",
                ["-yoke_depth/2", origin_y, "base_height+turret_height+yoke_thickness"],
                ["yoke_depth", "yoke_thickness", "pivot_z+pin_radius-base_height-turret_height-yoke_thickness"])
            cylinder("TiltPivot" + suffix, head, "concept_camera_pivot",
                     [0, f"{sign}*head_width/2", "pivot_z"],
                     "pin_radius", "yoke_clearance+yoke_thickness", [0, sign, 0])
    else:
        box("FixedPost", "Mount", "camera_mount",
            ["-yoke_depth/2", "-head_width/4", "base_height"],
            ["yoke_depth", "head_width/2", "pivot_z-head_height/2-base_height"])

    box("CameraHousing", head, "camera_envelope",
        ["-head_depth/2", "-head_width/2", "pivot_z-head_height/2"],
        ["head_depth", "head_width", "head_height"], housing)
    cylinder("Lens", head, "camera_envelope", ["head_depth/2", 0, "pivot_z"],
             "lens_radius", "lens_depth", [1, 0, 0], glass)
    return result


def pose(spec, p, name=None):
    name = name or "forward"
    if name not in {"forward", "aimed", "limit"}:
        raise ValueError("Unknown stationary camera pose: " + name)
    if spec["variant"] == "fixed":
        if name != "forward":
            raise ValueError("Fixed camera has no articulation")
        return {}
    factor = {"forward": 0, "aimed": 0.5, "limit": 1}[name]
    return {joint: p[joint.lower() + "_travel"] * factor for joint in ("Pan", "Tilt")}


def validate_pose(source, values):
    if not isinstance(values, dict) or set(values) != {row["id"] for row in source["joints"]}:
        raise ValueError("Camera pose must specify exactly its joints")
    for joint in source["joints"]:
        value = values[joint["id"]]
        low, high = joint["limits_deg"]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("Camera angle outside concept limits: " + joint["id"])


def samples(spec, p):
    names = ("forward",) if spec["variant"] == "fixed" else ("forward", "aimed", "limit")
    return [{"id": name, "joint_values": pose(spec, p, name)} for name in names]


def optical_frame(spec, p, values=None):
    values = pose(spec, p) if values is None else values
    source = expanded(spec, p)
    validate_pose(source, values)
    head = "Head" if source["joints"] else "Mount"
    transform = matrix(source, head, p, values)
    return {
        "origin_mm": robot.transform(transform, [p["head_depth"] / 2 + p["lens_depth"], 0, p["pivot_z"]]),
        "axis": [row[0] for row in transform[:3]],
        "x": [-row[1] for row in transform[:3]],
    }


def solidcraft_commands(spec, p):
    import sys
    commands = portable.solidcraft_commands(spec, p, sys.modules[__name__])
    metadata = next(command for command in commands if command["command"] == "document.metadata.set")
    metadata["params"] = {"values": {"org.solidcraftbot.stationary-camera": {
        "source": str(SOURCE.relative_to(ROOT)), "source_sha256": digest(SOURCE),
        "variant": spec["variant"], "status": spec["status"],
    }}}
    return commands
