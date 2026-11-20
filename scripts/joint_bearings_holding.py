"""Reproducible Phase-1 joint-load proposal; no CAD or robot execution.

All positions come from robot_spec and pinned sources. Point masses and their
centres are deliberately incomplete planning models, not physical mass data.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import robot_spec
from joint_load_math import build_trig_model, maximize_absolute

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "model/joint-bearings-holding.json"
REPORT = ROOT / "docs/joint-bearings-holding.report.json"
ACTIVE = (1, 2, 3, 4)


def add(a, b): return [x + y for x, y in zip(a, b)]
def sub(a, b): return [x - y for x, y in zip(a, b)]
def scale(a, k): return [x * k for x in a]
def dot(a, b): return math.fsum(x * y for x, y in zip(a, b))
def norm(a): return math.sqrt(max(0.0, dot(a, a)))
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def rotate(t, v): return [dot(row[:3], v) for row in t[:3]]
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(label + " must be finite and at least " + str(minimum))
    return float(value)


def reference_path(reference):
    path = (ROOT / reference["path"]).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file() or sha(path) != reference["sha256"]:
        raise ValueError("Missing or changed source pin: " + reference["path"])
    return path


def load_source(path=SOURCE):
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    if source["format"] != "solidcraftbot.joint-bearings-holding/1" or source["status"] != "proposal_pending_owner_decision":
        raise ValueError("Only the Phase-1 proposal format is supported")
    if source["phase"] != 1 or source["recommendation"]["brake_in_first_prototype"] is not False:
        raise ValueError("Phase 1 must not approve a brake-equipped prototype")
    if source["recommendation"]["prototype_released"] is not False or any("brake" in item for item in source["recommendation"]["prototype_holding"]):
        raise ValueError("Prototype release and brake selection require a separate owner decision")
    for ref in source["source_refs"].values(): reference_path(ref)
    for ref in source["vendor_evidence"]["sources"].values():
        if "path" in ref: reference_path(ref)
    assumptions = source["assumptions"]
    rules = {"servo_com_rule": "entire_module_at_output_face_owned_by_housing_parent_assumed",
             "link_com_rule": "midpoint_adjacent_joint_origins_last_to_flange",
             "tool_com_rule": "flange_reference_surrogate",
             "counterbearing_span_rule": "vendor_module_depth_plus_two_source_plate_thicknesses",
             "axial_load_share": "servo_locating_counterbearing_axially_floating_assumption"}
    if any(assumptions[key] != rule for key, rule in rules.items()):
        raise ValueError("Unsupported mass, support or axial-allocation model rule")
    units = {"gravity_m_s2": "m/s2", "torque_safety_factor": "1", "backdrive_safety_factor": "1",
             "planning_tool_mass_kg": "kg", "planning_sample_mass_kg": "kg", "counterweight_arm_scale": "1"}
    for key, unit in units.items():
        number(assumptions[key]["value"], key)
        if assumptions[key].get("unit") != unit or not assumptions[key].get("reason"):
            raise ValueError("Assumptions need units and reasons")
    if any(assumptions[key]["value"] < 1 for key in ("torque_safety_factor", "backdrive_safety_factor")):
        raise ValueError("Safety factors must be at least one")
    if any(assumptions[key]["value"] <= 0 for key in ("gravity_m_s2", "counterweight_arm_scale")):
        raise ValueError("Gravity and counterweight arm scale must be positive")
    for item in assumptions["planning_link_masses_kg"].values():
        number(item["value"], "planning link mass")
        if item["unit"] != "kg" or not item["reason"]: raise ValueError("Invalid mass assumption")
    for key in ("hold_duration_s", "physical_stop_angles_deg", "first_contact_pose_deg", "support_centres_measured_mm"):
        if assumptions[key] is not None:
            raise ValueError("Physical evidence is not implemented in this proposal: " + key)
    if source["later_brake_tcp_tolerance"]["status"] != "proposed":
        raise ValueError("Owner tolerance is a proposal, not an accepted limit")
    if source["later_brake_tcp_tolerance"]["unit"] != "mm":
        raise ValueError("The proposed tolerance must be in mm")
    number(source["later_brake_tcp_tolerance"]["value"], "proposed tolerance")
    return source


class Model:
    def __init__(self, source):
        self.source = source
        self.robot = robot_spec.load(reference_path(source["source_refs"]["robot"]))
        self.parameters = robot_spec.parameters(self.robot)
        self.selection = json.loads(reference_path(source["source_refs"]["actuators"]).read_text())
        self.parts = {p["id"]: p for p in self.selection["parts"]}
        self.library = json.loads(reference_path(source["source_refs"]["component_library"]).read_text())
        self.geometry = json.loads(reference_path(source["source_refs"]["geometry_report"]).read_text())
        self.sp02 = json.loads(reference_path(source["source_refs"]["sp02"]).read_text())
        self.motion = json.loads(reference_path(source["source_refs"]["motion"]).read_text())
        self.mobile = json.loads(reference_path(source["source_refs"]["mobile_base"]).read_text())
        self.joints = self.robot["joints"]
        self.ids = [j["id"] for j in self.joints]
        self.links = [l["id"] for l in self.robot["links"]]
        if set(source["assumptions"]["planning_link_masses_kg"]) != set(self.links[1:]):
            raise ValueError("Exactly the six moving links need planning mass assumptions")
        self.owners = {link: i for i, link in enumerate(self.links)}
        self.origins = [[robot_spec.evaluate(x, self.parameters) for x in j["frame"]["origin"]] for j in self.joints]
        self.axes = [j["frame"]["axis"] for j in self.joints]
        self.flange = [robot_spec.evaluate(x, self.parameters) for x in self.robot["flange_reference"]["point"]]
        self.g = source["assumptions"]["gravity_m_s2"]["value"]
        self.outputs, self.housings, self.plates = {}, {}, {}
        for link in self.robot["links"]:
            for op in link["recipe"]:
                if op["action"] == "vendor_component":
                    index = int(op["actuator"][1:]) - 1
                    target = self.outputs if op["section"] == "output" else self.housings
                    target[index] = {**op, "owner": link["id"]}
                if op["action"] == "mount_plate": self.plates[op["body"]] = op
        if set(self.outputs) != set(range(6)) or set(self.housings) != set(range(6)):
            raise ValueError("All six source output/housing frames are required")
        if norm(cross(self.axes[0], [0, 0, 1])) > 1e-12:
            raise ValueError("Yaw independence requires the source base axis parallel to gravity")
        if any(self.joints[i]["parent"] != self.links[i] or self.joints[i]["child"] != self.links[i+1] for i in range(6)):
            raise ValueError("A serial source chain is required")
        self.contexts = {
            "robot_limits": [j["limits_deg"] for j in self.joints],
            "sp02_window": [self.sp02["operating_window_deg"][j]["range"] for j in self.ids],
        }
        self._pose_cache = {}

    def point(self, point_id, link, xyz, mass, status):
        return {"id": point_id, "link": link, "point_mm": list(xyz), "mass_kg": float(mass), "status": status}

    def mass_sets(self):
        servo = []
        for i in range(6):
            housing, output = self.housings[i], self.outputs[i]
            position = [robot_spec.evaluate(x, self.parameters) for x in output["frame"]["origin"]]
            servo.append(self.point("servo_"+str(i+1), housing["owner"], position,
                                    self.parts[output["part"]]["vendor_mass_kg"],
                                    "vendor_mass_at_assumed_output_face_COM_parent_owned_split_unknown"))
        structure = []
        for i, link in enumerate(self.links[1:], 1):
            end = self.origins[i] if i < 6 else self.flange
            center = scale(add(self.origins[i-1], end), .5)
            mass = self.source["assumptions"]["planning_link_masses_kg"][link]["value"]
            structure.append(self.point("structure_"+link, link, center, mass, "unmeasured_planning_allowance"))
        tool = self.point("tool", self.links[-1], self.flange,
                          self.source["assumptions"]["planning_tool_mass_kg"]["value"],
                          "unmeasured_flange_surrogate_not_actual_SP02_mass_distribution")
        sample = self.point("sample", self.links[-1], self.flange,
                            self.source["assumptions"]["planning_sample_mass_kg"]["value"],
                            "synthetic_tube_and_sample_allowance_not_observation")
        result = {"servo_only": servo, "planning_empty": servo + structure + [tool],
                  "planning_loaded": servo + structure + [tool, sample]}
        # Every chosen L6 point is on J6: roll cannot move these point masses.
        # This is a contract of this surrogate, not of real eccentric tools.
        for points in result.values():
            for point in points:
                if self.owners[point["link"]] == 6 and norm(cross(sub(point["point_mm"], self.origins[5]), self.axes[5])) > 1e-8:
                    raise ValueError("Noncoaxial distal masses require six-coordinate analysis")
        return result

    def pose(self, q):
        key = tuple(q)
        if key not in self._pose_cache:
            transforms = robot_spec.forward(self.robot, q)
            origins = [robot_spec.transform(transforms[j["parent"]], o) for j, o in zip(self.joints, self.origins)]
            axes = [rotate(transforms[j["parent"]], a) for j, a in zip(self.joints, self.axes)]
            output_origins, output_axes = [], []
            for i in range(6):
                op = self.outputs[i]
                t = transforms[self.joints[i]["parent"]]
                output_origins.append(robot_spec.transform(t, [robot_spec.evaluate(x, self.parameters) for x in op["frame"]["origin"]]))
                output_axes.append(rotate(t, op["frame"]["axis"]))
            self._pose_cache[key] = (transforms, origins, axes, output_origins, output_axes)
        return self._pose_cache[key]

    def loads(self, points, q):
        transforms, origins, axes, faces, face_axes = self.pose(q)
        forces = [[0., 0., 0.] for _ in range(6)]
        moments = [[0., 0., 0.] for _ in range(6)]
        face_moments = [[0., 0., 0.] for _ in range(6)]
        for point in points:
            owner = self.owners[point["link"]]
            position = robot_spec.transform(transforms[point["link"]], point["point_mm"])
            force = [0., 0., -self.g * point["mass_kg"]]
            for i in range(owner):
                forces[i] = add(forces[i], force)
                moments[i] = add(moments[i], cross(scale(sub(position, origins[i]), .001), force))
                face_moments[i] = add(face_moments[i], cross(scale(sub(position, faces[i]), .001), force))
        result = []
        for i in range(6):
            axial = dot(forces[i], face_axes[i])
            perpendicular = sub(forces[i], scale(face_axes[i], axial))
            face_torsion = dot(face_moments[i], face_axes[i])
            tilting_vector = sub(face_moments[i], scale(face_axes[i], face_torsion))
            result.append({"joint": self.ids[i], "joint_origin_mm": origins[i], "axis": axes[i],
                           "output_face_origin_mm": faces[i], "output_face_axis": face_axes[i],
                           "gravity_torque_nm": dot(moments[i], axes[i]), "force_external_n": forces[i],
                           "axial_force_signed_n": axial, "axial_force_n": abs(axial), "radial_force_n": norm(perpendicular),
                           "output_face_moment_nm": face_moments[i], "output_face_tilting_vector_nm": tilting_vector,
                           "output_face_tilting_moment_nm": norm(tilting_vector),
                           "internal_bearing_center_offset_mm": None, "true_internal_bearing_tilting_moment_nm": None})
        return result

    def radius_bound(self, point, i, face=False):
        if face:
            return self.distance_bound(point, i, face=True)
        owner = self.owners[point["link"]]
        if owner <= i: return 0.
        # A point on the last revolute axis is unaffected by that rotation.
        while owner > i+1 and norm(cross(sub(point["point_mm"], self.origins[owner-1]), self.axes[owner-1])) < 1e-9:
            owner -= 1
        if owner == i+1:
            vector = sub(point["point_mm"], self.origins[i])
            radius = norm(cross(self.axes[i], vector))
        else:
            first = sub(self.origins[i+1], self.origins[i])
            radius = norm(cross(self.axes[i], first))
            radius += sum(norm(sub(self.origins[k+1], self.origins[k])) for k in range(i+1, owner-1))
            radius += norm(sub(point["point_mm"], self.origins[owner-1]))
        return radius * .001

    def distance_bound(self, point, i, face=False):
        """Full distance bound, including axial offsets needed for bending."""
        owner = self.owners[point["link"]]
        if owner <= i: return 0.
        distance = sum(norm(sub(self.origins[k+1], self.origins[k])) for k in range(i, owner-1))
        distance += norm(sub(point["point_mm"], self.origins[owner-1]))
        if face:
            output = [robot_spec.evaluate(x, self.parameters) for x in self.outputs[i]["frame"]["origin"]]
            distance += norm(sub(output, self.origins[i]))
        return distance*.001

    def extrema(self, points, joint_index, bounds, seed):
        def objective(q4):
            q = [0., *q4, 0.]
            return self.loads(points, q)[joint_index]["gravity_torque_nm"]
        model = build_trig_model(objective, 4)
        seeds = [[min(pair[1], max(pair[0], seed[k])) for k, pair in zip(ACTIVE, [bounds[k] for k in ACTIVE])]]
        result = maximize_absolute(model, [bounds[k] for k in ACTIVE], seeds_deg=seeds,
                                   tolerance=self.source["numerical"]["torque_tolerance_nm"],
                                   max_cells=self.source["numerical"]["max_cells"])
        geometry_bound = self.g * math.fsum(p["mass_kg"] * self.radius_bound(p, joint_index) for p in points)
        result["unconstrained_geometric_upper_nm"] = geometry_bound
        result["upper_bound"] = min(result["upper_bound"], geometry_bound + model["model_error_bound"])
        result["gap"] = max(0., result["upper_bound"] - result["lower_bound"])
        result["converged"] = result["gap"] <= self.source["numerical"]["torque_tolerance_nm"]
        if result["converged"] and result["stopping_reason"] != "tolerance":
            result["stopping_reason"] = "geometric_bound_tolerance"
        result["method"] += "_min_source_geometric_lever_bound"
        result["witness_pose_deg"] = [0., *result.pop("witness_deg"), 0.]
        result["maximum_exact_nm"] = None
        result["pose_occurs_in_workflow"] = None
        result["pose_collision_checked"] = False
        result["coordinate_reduction"] = "vertical_J1_gravity_yaw_invariance_and_axial_L6_point_mass_J6_invariance_only"
        return result


def backlash_shift_mm(backlash_arcmin, lever_mm):
    return number(backlash_arcmin, "backlash") * math.pi / (180. * 60.) * number(lever_mm, "lever")


def budget_totals(rows, allowance):
    allowance = number(allowance, "allowance")
    known = 0.
    unknown = []
    for row in rows:
        quantity = number(row["quantity"], "quantity")
        if row["unit_gross_eur"] is None:
            unknown.append(row["id"])
        else:
            known += number(row["unit_gross_eur"], row["id"]) * quantity
    known = round(known, 2)
    return {"allowance_eur": allowance, "known_subtotal_gross_eur": known, "unknown_rows": unknown,
            "total_gross_eur": None if unknown else known,
            "known_overrun_eur": round(max(0., known-allowance), 2),
            "remaining_for_unknowns_eur": round(allowance-known, 2),
            "fits_budget": False if known > allowance else (None if unknown else True),
            "budget_status": "known_overrun" if known > allowance else ("conditional_incomplete" if unknown else "complete")}


def dynamic_bound(model, points, profile, qualified=False):
    velocity = number(profile["velocity_rad_s"], "joint velocity")
    acceleration = number(profile["acceleration_rad_s2"], "joint acceleration")
    torques, forces, face_moments = [0.]*6, [0.]*6, [0.]*6
    point_rows = []
    for point in points:
        owner = model.owners[point["link"]]
        if not owner: continue
        segments = [norm(sub(model.origins[k+1], model.origins[k]))*.001 for k in range(owner-1)]
        segments.append(norm(sub(point["point_mm"], model.origins[owner-1]))*.001)
        terms = []
        for k, length in enumerate(segments, 1):
            angular_sum = k * velocity
            angular_acceleration_sum = k * acceleration
            changing_axis_term = k*(k-1)/2 * velocity**2
            terms.append(length * (angular_acceleration_sum + changing_axis_term + angular_sum**2))
        linear = math.fsum(terms)
        point_rows.append({"point": point["id"], "linear_acceleration_bound_m_s2": linear})
        for i in range(owner):
            force = point["mass_kg"] * linear
            forces[i] += force
            torques[i] += force * model.radius_bound(point, i)
            face_moments[i] += force * model.distance_bound(point, i, face=True)
    return {"point_mass_coupled_acceleration_bounds": point_rows,
            "joint_torque_addition_upper_nm": dict(zip(model.ids, torques)),
            "force_addition_norm_upper_n": dict(zip(model.ids, forces)),
            "output_face_moment_addition_norm_upper_nm": dict(zip(model.ids, face_moments)),
            "jerk_limit_rad_s3": profile["jerk_rad_s3"],
            "jerk_interpretation": "limits_change_rate_not_an_extra_instantaneous_torque_factor",
            "source_profile_qualified": qualified, "qualified": False,
            "omissions": ["intrinsic_link_rotor_inertia", "gear_friction", "elasticity", "actual_trajectory", "moving_base"],
            "method": "triangle_bound_for_all_coupled_axes_tangential_changing_axis_and_centripetal_point_acceleration"}


def support_example(model, row):
    i = model.ids.index(row["joint"])
    op = model.outputs[i]
    library = model.library["parts"][op["part"]]
    plate = model.plates[op["body"]+"_plate"]
    thickness = robot_spec.evaluate(plate["thickness_mm"], model.parameters)
    span_mm = library["depth_mm"] + 2*thickness
    axis, force = row["output_face_axis"], row["force_external_n"]
    counter = scale(cross(axis, row["output_face_tilting_vector_nm"]), 1000./span_mm)
    servo = sub(scale(force, -1.), counter)
    return {"actual_bearing_center_separation_mm": None, "analytical_example_span_mm": span_mm,
            "span_rule": model.source["assumptions"]["counterbearing_span_rule"],
            "span_is_available_fork_spacing": False,
            "assumed_effective_first_support": "output_face_surrogate_internal_center_unknown",
            "counterbearing_reaction_n": counter, "servo_reaction_n": servo,
            "counterbearing_radial_reaction_n": norm(counter),
            "servo_radial_reaction_n": norm(sub(servo, scale(axis, dot(axis, servo)))),
            "axial_allocation": "servo_locating_counterbearing_axially_floating_assumption",
            "drive_torque_unchanged_nm": row["gravity_torque_nm"],
            "physical_internal_bearing_reactions_n": None,
            "formulas": {"B": "(axis cross M_perp)/s", "A": "-F-B", "moment_shift": "M_internal=M_face-delta*(axis cross F), delta unknown"}}


def pose_within(q, bounds): return all(low <= x <= high for x, (low, high) in zip(q, bounds))


def power_loss(model, points, q, joint_index, bounds):
    i = joint_index
    evidence = model.source["vendor_evidence"]["actuators"][model.outputs[i]["part"]]
    friction = evidence["backdrive_torque_nm"]
    safety = model.source["assumptions"]["backdrive_safety_factor"]["value"]
    start = model.loads(points, q)[i]["gravity_torque_nm"]
    transforms, origins, axes, _, _ = model.pose(q)
    point_inertia = 0.
    for point in points:
        if model.owners[point["link"]] <= i: continue
        p = robot_spec.transform(transforms[point["link"]], point["point_mm"])
        r = norm(cross(axes[i], scale(sub(p, origins[i]), .001)))
        point_inertia += point["mass_kg"] * r*r
    def torque(angle):
        probe = list(q); probe[i] = angle
        return model.loads(points, probe)[i]["gravity_torque_nm"]
    endpoint = list(q)
    reason = "typical_friction_model_no_start_not_guaranteed_holding"
    if abs(start) > friction:
        direction = 1. if start > 0 else -1.
        boundary = bounds[i][1] if direction > 0 else bounds[i][0]
        # This is a hypothetical slow Coulomb descent, all other joints held.
        # It is not an impact/contact or simultaneous multi-joint simulation.
        f0, f90, f180 = torque(0.), torque(90.), torque(180.)
        constant = (f0+f180)/2
        cosine, sine = (f0-f180)/2, f90-constant
        amplitude = math.hypot(cosine, sine)
        roots = []
        ratio = (direction*friction-constant)/amplitude if amplitude else math.inf
        if -1 <= ratio <= 1:
            phase = math.atan2(sine, cosine)
            angle = math.acos(ratio)
            low, high = sorted((q[i], boundary))
            for base in (phase-angle, phase+angle):
                for turn in range(math.ceil((math.radians(low)-base)/(2*math.pi)),
                                  math.floor((math.radians(high)-base)/(2*math.pi))+1):
                    root = math.degrees(base+turn*2*math.pi)
                    if direction*(root-q[i]) > 1e-9:
                        roots.append(root)
        if roots:
            endpoint[i] = min(roots, key=lambda angle: abs(angle-q[i]))
            reason = "hypothetical_quasistatic_typical_friction_equilibrium_not_physical_rest"
        else:
            endpoint[i] = boundary
            reason = "software_range_boundary_not_a_physical_hardstop"
    initial_tcp = robot_spec.transform(transforms[model.links[-1]], model.flange)
    end_transforms = model.pose(endpoint)[0]
    end_tcp = robot_spec.transform(end_transforms[model.links[-1]], model.flange)
    def potential(ts):
        return model.g*.001*math.fsum(p["mass_kg"]*robot_spec.transform(ts[p["link"]], p["point_mm"])[2] for p in points)
    energy = potential(transforms) - potential(end_transforms)
    friction_work = friction*abs(math.radians(endpoint[i]-q[i]))
    angular_speed = math.sqrt(2*max(0., energy-friction_work)/point_inertia) if point_inertia else None
    return {"joint": model.ids[i], "initial_pose_deg": q,
            "initial_gravity_torque_nm": start, "typical_backdrive_torque_nm": friction,
            "conservative_comparison_torque_nm": friction/safety,
            "gravity_exceeds_typical_with_margin": abs(start) > safety*friction,
            "gravity_driven_start_in_typical_friction_model": abs(start) > friction,
            "guaranteed_unpowered_holding": None, "power_loss_safety_verified": False,
            "hypothetical_single_joint_endpoint_deg": endpoint, "hypothetical_endpoint_reason": reason,
            "hypothetical_tcp_fall_mm": max(0., initial_tcp[2]-end_tcp[2]),
            "hypothetical_tcp_displacement_mm": norm(sub(initial_tcp, end_tcp)),
            "point_mass_inertia_kg_m2": point_inertia,
            "initial_acceleration_rad_s2_without_intrinsic_inertia": max(0., abs(start)-friction)/point_inertia if point_inertia else None,
            "hypothetical_energy_release_j": energy,
            "rough_energy_based_angular_speed_rad_s": angular_speed,
            "physical_hardstop_pose_deg": None, "first_contact_pose_deg": None, "actual_tcp_fall_mm": None,
            "driver_braking_credit_nm": 0., "driver_braking_evidence": None,
            "conditions": ["other_joints_artificially_fixed", "constant_typical_Coulomb_friction", "no_contact_geometry",
                           "no_stop_impact_or_overshoot", "joint_limits_are_not_physical_stops", "not_a_commanded_trajectory"],
            "hazards": ["sample_loss_or_disturbance", "pinch_and_crush_points", "contact_with_neighbour_equipment"]}


def backlash_at_pose(model, q):
    transforms, origins, axes, _, _ = model.pose(q)
    tcp = robot_spec.transform(transforms[model.links[-1]], model.flange)
    rows = []
    for i in range(6):
        evidence = model.source["vendor_evidence"]["actuators"][model.outputs[i]["part"]]
        lever = norm(cross(axes[i], sub(tcp, origins[i])))
        shift = backlash_shift_mm(evidence["backlash_arcmin"], lever)
        bits = model.parts[model.outputs[i]["part"]]["vendor_encoder_bits_input_output"][1]
        rows.append({"joint": model.ids[i], "lever_mm": lever, "backlash_arcmin": evidence["backlash_arcmin"],
                     "load_reversal_arc_bound_mm": shift,
                     "one_output_encoder_count_mm": lever*2*math.pi/(2**bits),
                     "encoder_is_not_structural_deformation_measurement": True,
                     "motor_side_brake_local_gear_backlash_mm": shift,
                     "ideal_output_side_brake_bypassed_local_gear_term_mm": 0.,
                     "output_brake_application_shift_mm": None, "elastic_compliance_mm_per_nm": None,
                     "actual_output_brake_tcp_shift_mm": None,
                     "compensation_required_if_motor_side_gear_term_exceeds_proposal": shift > model.source["later_brake_tcp_tolerance"]["value"],
                     "compensation_implemented": False,
                     "force_chain_after_motor_side_brake": ["gear", "output_bearing", "output_plate", model.joints[i]["child"], "downstream_joints_and_flange"],
                     "force_chain_after_proposed_output_brake": ["output_bearing_and_coupling_if_downstream_of_brake", "output_plate", model.joints[i]["child"], "downstream_joints_and_flange"]})
    return {"pose_deg": q, "joints": rows,
            "local_linearized_chain_sum_mm": math.fsum(r["load_reversal_arc_bound_mm"] for r in rows),
            "scope": "arc_bound_per_independent_joint_at_this_pose_sum_is_local_linearized_not_total_real_error",
            "elastic_chain_shift_mm": None, "application_chain_shift_mm": None,
            "positions_neutral_verified": False, "prototype_status": "measurement_goal_not_concept_acceptance_gate",
            "later_brake_status": "proposed_owner_tolerance_physical_shift_at_contact_not_controller_residual"}


def bearing_alternatives(model, poses):
    products = {p["id"]: p for p in model.source["research"]["products"]}
    concepts = model.source["research"]["bearing_concepts"]
    shifts = {name: backlash_at_pose(model, q) for name, q in poses.items()}
    rows = []
    for concept in concepts:
        for short in concept["joints"]:
            i = int(short[1:])-1
            op = model.outputs[i]
            part = model.library["parts"][op["part"]]
            plate = model.plates[op["body"]+"_plate"]
            housing_plate = model.plates[model.housings[i]["body"]+"_plate"]
            quantities = concept.get("additional_product_quantities_per_joint", concept.get("additional_product_quantities", {}))
            ring_mass = sum(products[key]["engineering_mass_kg"]*qty for key, qty in quantities.items())
            ring_width = sum(products[key]["dimensions_mm"]["width"]*qty for key, qty in quantities.items())
            prices = [products[key]["price"]["gross"]*qty for key, qty in quantities.items()]
            largest_od = max((products[key]["dimensions_mm"]["outside"] for key in quantities), default=0.)
            thickness = robot_spec.evaluate(plate["thickness_mm"], model.parameters)
            axial_source = {"module_depth_mm": part["depth_mm"], "output_plate_thickness_mm": thickness,
                            "housing_plate_thickness_mm": robot_spec.evaluate(housing_plate["thickness_mm"], model.parameters),
                            "output_plate_inner_diameter_mm": 2*plate["clearance_radius_mm"],
                            "output_plate_outer_diameter_mm": 2*plate["outer_radius_mm"],
                            "registered_section_bounds": {name: value["bbox_mm"] for name, value in part["sections"].items()},
                            "free_axial_space_mm": None, "free_radial_space_mm": None,
                            "available_fork_spacing_mm": None,
                            "interpretation": "existing_envelopes_and_annuli_are_not_free_space_or_bearing_seats"}
            examples = []
            for name, q in poses.items():
                load = model.loads(model.mass_sets()["planning_loaded"], q)[i]
                examples.append({"pose": name, "cantilever_face_wrench": load, "counter_support_example": support_example(model, load)})
            rows.append({"concept": concept["id"], "joint": model.ids[i], "products": quantities,
                         "ring_mass_only_kg": ring_mass, "complete_distal_added_mass_kg": 0. if not quantities else None,
                         "priced_rings_only_gross_eur": sum(prices), "complete_added_price_gross_eur": 0. if not quantities else None,
                         "bearing_widths_without_spacers_mm": ring_width, "largest_bearing_od_mm": largest_od,
                         "source_envelope": axial_source,
                         "new_plate_revision_required": concept["new_plate_revision_required"],
                         "affected_source_plate_ids": [housing_plate["body"], plate["body"]] if quantities else [],
                         "width_exceeds_source_plate_thickness": ring_width > thickness,
                         "bearing_OD_exceeds_output_plate_OD": largest_od > 2*plate["outer_radius_mm"],
                         "shaft_tolerances": None, "seat_tolerances": None,
                         "resulting_fork_or_plate_spacing_mm": None,
                         "SP02_clip_and_loop_clearance_verified": False,
                         "capacity_and_fit_accepted": None, "native_geometry_changed": False,
                         "gear_play_arc_bound_mm_by_pose": {name: value["joints"][i]["load_reversal_arc_bound_mm"] for name, value in shifts.items()},
                         "compensation_required_for_later_motor_side_brake_proposal": any(value["joints"][i]["compensation_required_if_motor_side_gear_term_exceeds_proposal"] for value in shifts.values()),
                         "elastic_shift_mm_for_this_bearing_arrangement": None,
                         "additional_bearing_does_not_remove_gear_backlash": True,
                         "force_comparisons": examples,
                         "overturning_allowable_nm": None,
                         "rated_forces_are_not_installed_combined_load_acceptance": True})
    return rows


def counterweight_analysis(model, cases):
    q = [0., 90., 0., 0., 0., 0.]
    extra = []
    construction = []
    factor = model.source["assumptions"]["counterweight_arm_scale"]["value"]
    for i, next_pitch in ((2, 4), (1, 2)):
        arm = scale(sub(model.origins[next_pitch], model.origins[i]), factor)
        point = model.point("counterweight_J"+str(i+1), model.joints[i]["child"],
                            sub(model.origins[i], arm), 1., "analytical_mirrored_pitch_arm_not_installed")
        target = model.loads(cases["planning_loaded"]+extra, q)[i]["gravity_torque_nm"]
        unit = model.loads([point], q)[i]["gravity_torque_nm"]
        mass = -target/unit if abs(unit) > 1e-12 else None
        if mass is None or mass < 0: raise ValueError("Counterweight geometry cannot oppose the reference load")
        point["mass_kg"] = mass
        extra.append(point)
        construction.append({"joint": model.ids[i], "reference_pose_deg": q, "reference_pose_in_SP02_window": pose_within(q, model.contexts["sp02_window"]),
                             "mirrored_arm_reference_mm": arm, "derived_counterweight_mass_kg": mass,
                             "reference_target_torque_nm": target, "counterweight_mass_is_procured": False})
    residuals = {}
    for name in ("planning_loaded", "planning_empty"):
        residuals[name] = {}
        points = cases[name]+extra
        for context, bounds in model.contexts.items():
            residuals[name][context] = {}
            for i in (1, 2):
                result = model.extrema(points, i, bounds, robot_spec.home(model.robot))
                friction = model.source["vendor_evidence"]["actuators"][model.outputs[i]["part"]]["backdrive_torque_nm"]
                result["typical_friction_with_margin_nm"] = friction/model.source["assumptions"]["backdrive_safety_factor"]["value"]
                result["whole_window_non_sinking_proven"] = False
                result["residual_exceeds_typical_margin_at_witness"] = result["lower_bound"] > result["typical_friction_with_margin_nm"]
                residuals[name][context][model.ids[i]] = result
    return {"construction": construction, "added_moving_mass_kg": sum(p["mass_kg"] for p in extra),
            "reference_residual_all_joints_nm": {model.ids[i]: row["gravity_torque_nm"] for i, row in enumerate(model.loads(cases["planning_loaded"]+extra, q))},
            "residual_extrema": residuals,
            "added_point_mass_inertia_upper_kg_m2": {model.ids[i]: sum(p["mass_kg"]*model.radius_bound(p, i)**2 for p in extra) for i in range(6)},
            "same_motion_profile_retained": True, "moving_mass_and_inertia_penalty": True,
            "spring_residual_torque_nm": None, "spring_mount_geometry_mm": None,
            "power_loss_holding_verified": False, "SP02_clearance_verified": False,
            "interpretation": "balance_at_one_analytical_pose_does_not_cancel_articulated_loads_or_sample_changes_in_entire_window"}


def holding_alternatives(model, extrema):
    """Compare reference components without approving a physical installation."""
    required = {j: r["upper_bound"]*model.source["assumptions"]["torque_safety_factor"]["value"] for j, r in extrema.items()}
    rows = []
    complexity = {"counterweight": 2, "gas_spring_reference": 3, "active_hold_then_park": 0,
                  "park_indexing_pin_reference": 1, "permanent_magnet_brake_followup": 5, "harmonic_escape": 6}
    for option in model.source["research"]["holding_concepts"]:
        torque = option.get("torque_nm")
        row = {"id": option["id"], "stage": option["stage"],
               "complexity_rank_proposed": complexity[option["id"]],
               "required_safety_factored_torque_nm": required,
               "reference_component_torque_nm": torque,
               "reference_torque_ratio_to_required": {j: torque/t if torque is not None and t > .01 else None for j, t in required.items()},
               "installed_holding_torque_nm": None, "system_fail_safe_qualified": False,
               "manual_release_and_foldability_verified": False, "qualified": False,
               "prototype_brake": False, "thermal_acceptance": None,
               "price_and_envelope_source": "model/joint-bearings-holding.json#research.holding_concepts."+option["id"]}
        if option["id"] == "active_hold_then_park":
            row["admissibility"] = "excluded_from_unconditional_acceptance_until_static_thermal_duration_and_owner_power_loss_decision"
            row["folding"] = "manufacturer_manual_backdrive_and_regeneration_rules_unknown"
        elif option["id"] == "park_indexing_pin_reference":
            row["admissibility"] = "only_after_confirmed_standstill_and_a_separately_supported_validated_park_pose"
            row["pin_force_required_at_actual_mount_n"] = None
            row["pin_force_formula"] = "F_required=required_torque/mount_radius; actual_radius_and_guide_gap_unknown"
            row["manual_release_concept"] = True
        elif option["id"] == "permanent_magnet_brake_followup":
            row["admissibility"] = "future_only_generic_shaft_brake_not_MYACTUATOR_approved_output_mount"
            row["additional_mass_requires_recalculation"] = True
            row["published_currentless_braking"] = option["currentless_braking"]
            row["nominal_release_current_a"] = option["nominal_power_w"]/option["nominal_voltage_v"]
            row["sequencing_requirement_not_implemented"] = ["servo_holds_position_then_apply_brake_then_reduce_servo_torque",
                                                              "rebuild_holding_torque_before_release", "no_position_following_against_applied_output_brake"]
        elif option["id"] == "counterweight":
            row["admissibility"] = "whole_window_residual_and_inertia_penalty_in_passive_counterbalance_report"
        elif option["id"] == "gas_spring_reference":
            row["admissibility"] = "force_and_stroke_do_not_define_joint_torque_without_anchors_and_force_curve"
            row["spring_moment_formula"] = "tau(q)=force(stroke(q),temperature)*perpendicular_moment_arm(q)"
        else:
            row["admissibility"] = "unselected_quote_dependent_replacement_no_price_or_fit_invented"
        rows.append(row)
    return rows


def bearing_load_envelopes(model, cases):
    rows = {}
    for name, points in cases.items():
        profile = "arm_empty" if name == "planning_empty" else "arm_loaded"
        dynamics = dynamic_bound(model, points, model.motion["limits"][profile], model.motion["limits"]["qualified"])
        rows[name] = []
        for i, joint in enumerate(model.ids):
            weight = model.g*sum(p["mass_kg"] for p in points if model.owners[p["link"]] > i)
            face_moment = model.g*sum(p["mass_kg"]*model.distance_bound(p, i, face=True) for p in points)
            force_bound = weight+dynamics["force_addition_norm_upper_n"][joint]
            moment_bound = face_moment+dynamics["output_face_moment_addition_norm_upper_nm"][joint]
            vendor = model.source["vendor_evidence"]["actuators"][model.outputs[i]["part"]]
            axial = {key: vendor[key]*1000 if vendor[key] is not None else None
                     for key in ("axial_tensile_published_kn", "axial_compressive_published_kn", "axial_unspecified_direction_published_kn")}
            radial = vendor["radial_published_kn"]*1000
            rows[name].append({"joint": joint, "static_external_force_norm_n": weight,
                               "static_output_face_moment_norm_upper_nm": face_moment,
                               "radial_force_upper_including_coupled_dynamics_n": force_bound,
                               "axial_force_magnitude_upper_including_coupled_dynamics_n": force_bound,
                               "force_component_bounds_are_separate_not_simultaneously_applied": True,
                               "output_face_moment_norm_upper_including_coupled_dynamics_nm": moment_bound,
                               "vendor_radial_published_n": radial, "vendor_axial_published_n": axial,
                               "ratio_to_published_radial_value_not_acceptance": force_bound/radial,
                               "vendor_output_bearing_allowable_tilting_moment_nm": None,
                               "true_internal_bearing_moment_nm": None,
                               "combined_loading_and_life_accepted": None,
                               "reference_scope": "whole_angle_box_triangle_bounds_for_assumed_point_masses_at_output_face_not_verified_internal_bearing"})
    return rows


def combined_load_demands(model, cases, extrema):
    result = {}
    factor = model.source["assumptions"]["torque_safety_factor"]["value"]
    for name, profile in (("planning_loaded", "arm_loaded"), ("planning_empty", "arm_empty")):
        dynamic = dynamic_bound(model, cases[name], model.motion["limits"][profile], model.motion["limits"]["qualified"])
        result[name] = {}
        for context, joints in extrema[name].items():
            result[name][context] = []
            for i, joint in enumerate(model.ids):
                gravity = joints[joint]["upper_bound"]
                addition = dynamic["joint_torque_addition_upper_nm"][joint]
                part = model.parts[model.outputs[i]["part"]]
                vendor = model.source["vendor_evidence"]["actuators"][part["id"]]
                result[name][context].append({"joint": joint, "gravity_upper_nm": gravity,
                                               "dynamic_addition_upper_nm": addition,
                                               "combined_triangle_upper_nm": gravity+addition,
                                               "safety_factored_combined_upper_nm": factor*(gravity+addition),
                                               "vendor_rated_reference_nm": part["vendor_rated_output_torque_nm"],
                                               "vendor_peak_reference_nm": vendor["peak_torque_nm"],
                                               "upper_exceeds_rated_reference": factor*(gravity+addition) > part["vendor_rated_output_torque_nm"],
                                               "physical_demand_or_infeasibility_proven": False,
                                               "scope": "conservative_coupled_point_mass_bounds_not_simultaneous_trajectory_extrema_intrinsic_inertias_unknown"})
    return result


def report_document(source_path=SOURCE):
    source = load_source(source_path)
    model = Model(source)
    cases = model.mass_sets()
    home = robot_spec.home(model.robot)
    named = {"home": home, **{name: pose["arm_deg"] for name, pose in model.mobile["poses"].items()}}
    maxima = {}
    pose_reports = {}
    for case_name, points in cases.items():
        maxima[case_name] = {}
        for context, bounds in model.contexts.items():
            maxima[case_name][context] = {model.ids[i]: model.extrema(points, i, bounds, home) for i in range(6)}
        pose_reports[case_name] = {name: {"pose_deg": q, "inside_sp02_window": pose_within(q, model.contexts["sp02_window"]),
                                         "loads": model.loads(points, q), "collision_checked": False} for name, q in named.items()}
    sensitive = []
    for p in cases["planning_loaded"]:
        if p["id"].startswith("servo_"): continue
        unit = {**p, "mass_kg": 1.}
        sensitive.append({"id": p["id"], "mass_actual_kg": None, "COM_reference_mm": p["point_mm"], "owner": p["link"],
                          "function": "tau_j(q)=servo_tau_j(q)+sum(m_i*unit_tau_ji(q))",
                          "absolute_global_coefficient_upper_nm_per_kg": {model.ids[i]: model.g*model.radius_bound(unit, i) for i in range(6)},
                          "home_coefficients_nm_per_kg": {model.ids[i]: row["gravity_torque_nm"] for i, row in enumerate(model.loads([unit], home))}})
    power = {}
    thermal = {}
    for case_name in ("servo_only", "planning_loaded", "planning_empty"):
        points = cases[case_name]
        power[case_name] = {}
        thermal[case_name] = {}
        for context, bounds in model.contexts.items():
            power[case_name][context] = []
            thermal[case_name][context] = []
            for i in range(6):
                extremum = maxima[case_name][context][model.ids[i]]
                q = extremum["witness_pose_deg"]
                power[case_name][context].append(power_loss(model, points, q, i, bounds))
                part = model.parts[model.outputs[i]["part"]]
                rated = part["vendor_rated_output_torque_nm"]
                demand = extremum["upper_bound"]*source["assumptions"]["torque_safety_factor"]["value"]
                required = extremum["upper_bound"] > source["numerical"]["torque_tolerance_nm"]
                thermal[case_name][context].append({"joint": model.ids[i], "hold_gravity_upper_nm": extremum["upper_bound"],
                                                    "safety_factored_hold_upper_nm": demand, "vendor_rated_reference_nm": rated,
                                                    "ratio_to_rated_reference": demand/rated,
                                                    "exceeds_rated_reference": demand > rated, "hold_duration_s": None,
                                                    "installed_static_continuous_hold_nm": None,
                                                    "gravity_hold_required_in_surrogate": required,
                                                    "thermal_acceptance": None, "procedure_b_unconditional_acceptance_excluded": required,
                                                    "exclusion_reason": "hold_duration_and_installed_static_thermal_evidence_unknown_not_proved_by_rated_or_peak_torque"})
        power[case_name]["named_pose_single_joint_cases"] = [power_loss(model, points, q, i, model.contexts["robot_limits"])
                                                              for name, q in named.items() if name in ("home", "parking_supported") for i in range(6)]
    rows = []
    products = {p["id"]: p for p in source["research"]["products"]}
    pitch = next(c for c in source["research"]["bearing_concepts"] if c["id"] == source["recommendation"]["bearing_pitch"])
    for key, quantity in pitch["additional_product_quantities_per_joint"].items():
        rows.append({"id": key, "quantity": quantity*len(pitch["joints"]), "unit_gross_eur": products[key]["price"]["gross"],
                     "price_reference": products[key]["price"]})
    rows.extend({"id": key, "quantity": 1, "unit_gross_eur": None} for key in source["budget"]["unknown_rows"])
    budget = budget_totals(rows, source["budget"]["mechanical_allowance_eur"])
    budget.update({"rows": rows, "cheapest_fully_qualified_under_budget_configuration": None,
                   "difference_to_recommendation_eur": None, "electrical_brake_controls_eur": None,
                   "electrical_budget_separate": True, "no_mechanical_allowance_increase": True})
    specimen = cases["planning_loaded"]
    selected_poses = {"home": home, "park_existing": named["parking_supported"]}
    for joint, result in maxima["planning_loaded"]["robot_limits"].items(): selected_poses["maximum_"+joint] = result["witness_pose_deg"]
    sources = {ref["path"]: ref["sha256"] for ref in source["source_refs"].values()}
    sources.update({ref["path"]: ref["sha256"] for ref in source["vendor_evidence"]["sources"].values() if "path" in ref})
    for name in ("scripts/joint_bearings_holding.py", "scripts/joint_load_math.py", "scripts/robot_spec.py"):
        sources[name] = sha(ROOT/name)
    return {"format": "solidcraftbot.joint-bearings-holding-report/1", "derived": True,
            "status": "proposal_pending_owner_decision", "phase": 1, "source_sha256": sha(source_path),
            "source_files_sha256": sources, "units": {"length": "mm", "force": "N", "torque": "Nm", "mass": "kg"},
            "qualification": {"physical": False, "safety": False, "manufacturing": False, "capacity": False,
                              "native_collision": False, "new_motion_program": False, "geometry_changed": False},
            "mass_models": cases, "servo_case_interpretation": "vendor_mass_only_lower_information_not_a_proven_lower_bound_on_real_torque",
            "sensitivity": sensitive, "gravity_extrema": maxima, "named_poses": pose_reports,
            "dynamics": {name: dynamic_bound(model, cases[name], model.motion["limits"][profile], qualified=model.motion["limits"]["qualified"])
                         for name, profile in (("planning_loaded", "arm_loaded"), ("planning_empty", "arm_empty"))},
            "bearing_alternatives": bearing_alternatives(model, selected_poses),
            "bearing_load_envelopes": bearing_load_envelopes(model, cases),
            "combined_load_demands": combined_load_demands(model, cases, maxima),
            "power_loss": power, "thermal_holding": thermal,
            "backlash_and_position_shift": {name: backlash_at_pose(model, q) for name, q in selected_poses.items()},
            "passive_counterbalance": counterweight_analysis(model, cases), "budget": budget,
            "holding_alternatives": holding_alternatives(model, maxima["planning_loaded"]["robot_limits"]),
            "recommendation": source["recommendation"], "brake_in_first_prototype": False,
            "later_brake_tcp_tolerance": source["later_brake_tcp_tolerance"],
            "open_measurements": source["open_measurements"],
            "owner_decision_gates": {"prototype_released": False, "tool_fitted_park_inside_SP02_window": pose_within(named["parking_supported"], model.contexts["sp02_window"]),
                                     "physical_power_loss_end_pose_and_drop_known": False, "thermal_holding_qualified": False,
                                     "no_revision_fit_and_load_capacity_proven": False,
                                     "no_revision_fit_impossibility_proven": False,
                                     "phase2_geometry_requires_owner_decision": True},
            "limitations": ["analytical_float_enclosures_not_formal_interval_certification", "unresolved_maximization_gaps_are_reported",
                            "unknown_mass_COM_and_rotor_inertia", "force_ratings_are_not_combined_load_or_tilting_acceptance",
                            "software_limits_are_not_physical_hardstops", "actual_first_contact_and_fall_remain_unknown",
                            "existing_MB01_park_outside_SP02_window", "no_indefinite_static_holding_rating", "no_brake_control_or_compensation_implemented"]}


def encoded_report(source_path=SOURCE):
    return json.dumps(report_document(source_path), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Recompute and compare the tracked derived report")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    content = encoded_report(args.source)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            print("Derived joint-bearing/holding report missing or stale: " + str(args.output))
            return 1
        print("Joint-bearing/holding report is reproducible; no geometry or hardware qualification.")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
