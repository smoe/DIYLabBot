"""Non-rendered servo requirements and harness topology; no cable physics."""
import json
import math
from pathlib import Path


FEEDBACK = {"measured_position", "sample_time", "fault_status"}
SIGNALS = {"power", "command", "position_feedback", "fault_status"}


def _positive_or_unknown(values, label):
    for key, value in values.items():
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError(label + ": " + key + " must be positive or unknown (null)")


def _ids(items, label):
    result = {item["id"]: item for item in items}
    if len(result) != len(items):
        raise ValueError("Duplicate " + label + " ID")
    return result


def route_to_link(spec, target):
    """Ordered rigid links from the controller's grounded link to a motor."""
    links = [spec["links"][0]["id"]] + [j["child"] for j in spec["joints"]]
    if target not in links:
        raise ValueError("Unknown motor mounting link: " + target)
    return links[:links.index(target) + 1]


def audit(spec):
    """Reject broken topology; explicitly leave all physical checks unresolved.

    A logical circuit can share a cable/bus with others. Link paths describe
    required moving boundaries, not a geometrically feasible cable centreline.
    """
    services = spec["services"]
    if services["format"] != "solidcraftbot.services/1":
        raise ValueError("Unsupported services format")
    if services["status"] != "requirements_and_concept_topology":
        raise ValueError("Service layer is not a verified wiring design")
    controller = services["controller"]
    if controller["mounted_link"] != spec["links"][0]["id"]:
        raise ValueError("This harness audit expects a controller at the grounded base")
    joints = {j["id"]: j for j in spec["joints"]}
    from robot_spec import expanded
    bodies = {op["body"]: link["id"] for link in expanded(spec)["links"]
              for op in link["recipe"] if op["action"] == "create"}
    actuators = _ids(services["actuators"], "actuator")
    if len(actuators) != 6 or {a["joint"] for a in actuators.values()} != set(joints):
        raise ValueError("Exactly one servo requirement is needed for each of the six joints")
    if controller["id"] in actuators:
        raise ValueError("Controller and actuator IDs must differ")
    unresolved, actuator_report = [], []
    for actuator in actuators.values():
        name = actuator["id"]
        if actuator["kind"] != "servo" or actuator["command_interfaces"] != ["position"]:
            raise ValueError(name + ": position-controlled servo required")
        if set(actuator["required_feedback"]) != FEEDBACK:
            raise ValueError(name + ": readable measured position, timestamp and fault status required")
        if bodies.get(actuator["envelope_body"]) != actuator["mounted_link"]:
            raise ValueError(name + ": motor mounting link disagrees with the CAD envelope")
        feedback = actuator["feedback"]
        if feedback["measurement_location"] not in (None, "motor_shaft", "servo_output", "joint_output"):
            raise ValueError(name + ": unknown encoder location")
        _positive_or_unknown({k: feedback[k] for k in ("period_ms", "max_sample_age_ms", "latency_ms")}, name)
        transmission = actuator["transmission"]
        _positive_or_unknown({"motor_revolutions_per_joint_revolution": transmission["motor_revolutions_per_joint_revolution"]}, name)
        direction = transmission["direction"]
        if direction is not None and (type(direction) is not int or direction not in (-1, 1)):
            raise ValueError(name + ": transmission direction must be -1, +1 or unknown")
        offset = transmission["joint_zero_offset_deg"]
        if offset is not None and (type(offset) not in (int, float) or not math.isfinite(offset)):
            raise ValueError(name + ": invalid joint zero offset")
        missing = (["part"] if actuator["part"] is None else [])
        missing += ["feedback." + k for k, v in feedback.items() if v is None]
        missing += ["transmission." + k for k, v in transmission.items() if v is None]
        unresolved.append({"id": name, "fields": missing})
        actuator_report.append({"id": name, "joint": actuator["joint"], "ros_joint": actuator["joint"].lower(),
                               "mounted_link": actuator["mounted_link"], "feedback_source": "measured_hardware_required; current_ROS_backend_is_mock"})

    harness = services["harness"]
    if harness["topology"] != "logical_connections_physical_topology_unselected":
        raise ValueError("Physical power/bus topology is not selected")
    if harness["render_in_motion"] is not False or harness["flexible_dynamics"] is not False:
        raise ValueError("Cable rendering and flexible dynamics are not implemented")
    circuits = _ids(harness["circuits"], "circuit")
    if len(circuits) != 6 or {c["target"] for c in circuits.values()} != set(actuators):
        raise ValueError("Power, command and feedback circuit required for every servo")
    crossings, circuit_report = set(), []
    for circuit in circuits.values():
        name = circuit["id"]
        if circuit["source"] != controller["id"] or set(circuit["signals"]) != SIGNALS:
            raise ValueError(name + ": missing controller, power, command or return feedback path")
        route = route_to_link(spec, actuators[circuit["target"]]["mounted_link"])
        if circuit["route_links"] != route:
            raise ValueError(name + ": route must follow the link chain to the motor mounting link")
        crossed = [j["id"] for j in spec["joints"] if j["child"] in route[1:]]
        crossings.update(crossed)
        _positive_or_unknown({k: v for k, v in circuit["cable"].items() if k != "part"}, name)
        _positive_or_unknown({k: circuit["electrical"][k] for k in ("voltage_v", "peak_current_a")}, name)
        # A future routing backend will validate curves/clamps. Do not silently
        # accept coordinates now and imply they have passed physical checks.
        if any(v is not None for v in circuit["routing"].values()):
            raise ValueError(name + ": geometric cable routing is not implemented yet")
        missing = [section + "." + k for section in ("cable", "routing", "electrical")
                   for k, v in circuit[section].items() if v is None]
        unresolved.append({"id": name, "fields": missing})
        circuit_report.append({"id": name, "target": circuit["target"], "crossed_joints": crossed,
                               "route_links": route, "physical_route_verified": False})
    passages = harness["joint_passages"]
    if len(passages) != len(crossings) or {p["joint"] for p in passages} != crossings:
        raise ValueError("Every crossed moving boundary needs exactly one cable passage requirement")
    for passage in passages:
        joint = joints[passage["joint"]]
        limits, neutral = passage["allowed_limits_deg"], passage["neutral_deg"]
        if passage["scheme"] not in (None, "service_loop", "torsion_route", "slip_ring"):
            raise ValueError("Unknown cable passage scheme")
        if neutral is not None and (type(neutral) not in (int, float) or not math.isfinite(neutral)):
            raise ValueError("Invalid cable neutral angle")
        if limits is not None:
            if len(limits) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in limits):
                raise ValueError("Invalid cable passage angular limits")
            if limits[0] > joint["limits_deg"][0] or limits[1] < joint["limits_deg"][1]:
                raise ValueError(joint["id"] + ": cable allowance does not cover declared joint limits")
            if neutral is not None and not limits[0] <= neutral <= limits[1]:
                raise ValueError("Cable neutral outside cable allowance")
        unresolved.append({"id": "passage:" + joint["id"], "fields": [k for k, v in passage.items() if v is None]})
    return {"logical_topology_passed": True, "actuators": actuator_report, "circuits": circuit_report,
            "unresolved": unresolved,
            "physical_validation": {"status": "not_performed", "routing_and_slack": False, "bend_radius": False,
                                    "torsion": False, "collision_and_snagging": False, "voltage_drop_and_thermal": False,
                                    "feedback_timing_and_calibration": False, "flexible_dynamics": False},
            "notes": ["Logical circuits may share a physical bus/cable; no bus or wiring topology selected.",
                      "Null means unknown, never zero, unlimited or passed.",
                      "Only motor supplies are covered; no tool wiring beyond the generic flange."]}


def write_report(spec, destination, spec_sha256):
    result = {"spec_sha256": spec_sha256, "services": spec["services"], **audit(spec)}
    Path(destination).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import robot_spec as model
    destination = model.ROOT / "exports/generated/services-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_report(model.load(), destination, model.digest(model.SPEC))
    print("Six servo connections checked; physical routing and feedback hardware remain unresolved.")
