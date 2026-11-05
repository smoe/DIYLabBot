"""Portable provisional camera envelopes, mounts, optical frames and visual cones.

Frames use the model's zero-configuration coordinates, not a measured camera
calibration. Optical +Z is forward, +X right, +Y down. No CAD/ROS dependencies.
"""
import copy
import math


def cameras(spec):
    return [(link["id"], op) for link in spec["links"]
            for op in link["recipe"] if op["action"] == "camera"]


def offset(frame, point):
    from robot_components import axes
    x, y, z = axes(frame)
    return ["(%s) + (%s)" % (origin, " + ".join(
        "(%s) * (%s)" % (coefficient, value)
        for coefficient, value in zip((x[i], y[i], z[i]), point)
        if abs(coefficient) > 1e-12) or "0")
        for i, origin in enumerate(frame["origin"])]


def audit(spec):
    from robot_spec import evaluate, parameters
    from robot_components import axes
    p = parameters(spec)
    chain = [spec["links"][0]["id"]] + [j["child"] for j in spec["joints"]]
    found = cameras(spec)
    if found and (len(found) != 2 or {c["purpose"] for _, c in found} != {"tip", "awareness"}):
        raise ValueError("Arm requires a tip camera and an awareness camera")
    ids = set()
    result = []
    for link, camera in found:
        name = camera["id"]
        if name in ids:
            raise ValueError("Duplicate camera ID")
        ids.add(name)
        if camera["status"] != "provisional" or camera["manufacturing_released"] is not False or camera["part"] is not None:
            raise ValueError(name + ": camera and mounts must remain unselected and provisional")
        axes(camera["frame"])
        if len(camera["frame"]["origin"]) != 3:
            raise ValueError(name + ": optical origin needs three coordinates")
        for v in camera["frame"]["origin"]:
            evaluate(v, p)
        dimensions = camera["body_size_mm"] + [camera["lens"]["radius_mm"], camera["lens"]["length_mm"],
            camera["view"]["range_mm"], camera["view"]["far_radius_mm"]]
        if len(camera["body_size_mm"]) != 3 or any(evaluate(v, p) <= 0 for v in dimensions):
            raise ValueError(name + ": camera dimensions must be positive")
        if not camera["mount_boxes"]:
            raise ValueError(name + ": provisional attachment envelope required")
        for box in camera["mount_boxes"]:
            if len(box["origin"]) != 3 or len(box["size"]) != 3 or any(evaluate(v, p) <= 0 for v in box["size"]):
                raise ValueError(name + ": invalid mount box")
            for v in box["origin"]:
                evaluate(v, p)
        view = camera["view"]
        if view["kind"] != "illustrative_circular_cone" or view["occlusion_checked"] is not False or not 0 < view["opacity"] < 1:
            raise ValueError(name + ": cone must be translucent and unverified")
        if len(camera["color"]) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in camera["color"]):
            raise ValueError(name + ": invalid RGB color")
        route = chain[:chain.index(link) + 1]
        connection = camera["connection"]
        if connection["controller"] != spec["services"]["controller"]["id"] or connection["route_links"] != route:
            raise ValueError(name + ": camera cable route skips a moving boundary")
        if any(connection[k] is not None for k in ("interface", "cable", "strain_relief", "max_frame_age_ms")):
            raise ValueError(name + ": physical camera wiring and timing are not selected")
        result.append({"id": name, "purpose": camera["purpose"], "mounted_link": link,
            "status": camera["status"], "manufacturing_released": False, "part": None,
            "optical_frame": {"origin_mm": [evaluate(v, p) for v in camera["frame"]["origin"]],
                              "axis": camera["frame"]["axis"], "x": camera["frame"]["x"]},
            "cone_range_mm": evaluate(view["range_mm"], p), "cone_far_radius_mm": evaluate(view["far_radius_mm"], p),
            "full_cone_angle_deg": math.degrees(2 * math.atan(evaluate(view["far_radius_mm"], p) / evaluate(view["range_mm"], p))),
            "cone_is_collision_geometry": False, "occlusion_checked": False,
            "route_links": route, "required_joint_passages": [j["id"] for j in spec["joints"] if j["child"] in route[1:]],
            "physical_wiring_verified": False, "calibration_verified": False})
    return {"passed": True, "cameras": result, "stationary_cameras_modeled": False,
            "qualification": "Illustrative envelopes; no optics, visibility, calibration, mass or manufacturing qualification"}


def lower(spec):
    """Lower one camera description into the same five bodies for both CADs."""
    audit(spec)
    result = copy.deepcopy(spec)
    for link in result["links"]:
        operations = []
        for camera in link["recipe"]:
            if camera["action"] != "camera":
                operations.append(camera)
                continue
            name, f = camera["id"], camera["frame"]
            w, h, d = camera["body_size_mm"]
            lens = camera["lens"]
            def create(suffix, role, primitive, color=None, opacity=1):
                body = name + suffix
                operations.append({"id": body, "action": "create", "body": body,
                    "role": role, "primitive": primitive})
                result["body_appearances"][body] = {"color": color or camera["color"], "opacity": opacity}
            create("_body_ENVELOPE", "camera_envelope", {"kind": "box", "size": [w, h, d],
                "origin": offset(f, ["-(%s)/2" % w, "-(%s)/2" % h, "-(%s)-(%s)" % (d, lens["length_mm"])]),
                "axis": f["axis"], "x": f["x"]})
            create("_lens_ENVELOPE", "camera_envelope", {"kind": "cylinder", "radius": lens["radius_mm"],
                "length": lens["length_mm"], "origin": offset(f, [0, 0, "-(%s)" % lens["length_mm"]]),
                "axis": f["axis"]}, [35, 42, 52])
            for index, box in enumerate(camera["mount_boxes"]):
                create("_mount_%d_PROVISIONAL" % index, "camera_mount", {"kind": "box", **box}, [160, 175, 188])
            # SolidCraft requires a nonzero base circle. Construct from the far
            # circle back to the optical apex; FreeCAD uses the identical frame.
            view = camera["view"]
            create("_view_CONE", "viewing_cone", {"kind": "cone", "radius": view["far_radius_mm"],
                "top_radius": 0, "length": view["range_mm"], "origin": offset(f, [0, 0, view["range_mm"]]),
                "axis": [-v for v in f["axis"]]}, opacity=view["opacity"])
        link["recipe"] = operations
    return result


def axis_angle(frame):
    """Rigid rotation for SolidCraft's move command, in explicit degrees."""
    from robot_components import axes
    x, y, z = axes(frame)
    # Unit quaternion from a rotation matrix, including 180-degree rotations.
    r = [[x[i], y[i], z[i]] for i in range(3)]
    trace = sum(r[i][i] for i in range(3))
    if trace > 0:
        s = 2 * math.sqrt(trace + 1)
        q = [s / 4, (r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s]
    else:
        i = max(range(3), key=lambda k: r[k][k]); j, k = (i + 1) % 3, (i + 2) % 3
        s = 2 * math.sqrt(1 + r[i][i] - r[j][j] - r[k][k])
        q = [0., 0., 0., 0.]; q[0] = (r[k][j] - r[j][k]) / s
        q[i + 1] = s / 4; q[j + 1] = (r[j][i] + r[i][j]) / s; q[k + 1] = (r[k][i] + r[i][k]) / s
    length = math.sqrt(sum(v * v for v in q[1:]))
    return ([1, 0, 0], 0) if length < 1e-12 else ([v / length for v in q[1:]], math.degrees(2 * math.atan2(length, q[0])))
