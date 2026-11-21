"""Independent physical identities and proposal/report contract checks."""

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import joint_bearings_holding as calculation
import robot_spec


def vector_cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def vector_norm(values):
    return math.sqrt(sum(value * value for value in values))


class JointBearingsHoldingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = calculation.load_source()
        cls.model = calculation.Model(cls.source)
        cls.cases = cls.model.mass_sets()
        cls.simple_pose = [0.0, 90.0, 0.0, 0.0, 0.0, 0.0]

    def unit_flange_mass(self, mass=1.0):
        return self.model.point("independent_flange_test", self.model.links[-1],
                                self.model.flange, mass, "test_fixture")

    def load_mutated_source(self, mutation):
        source = copy.deepcopy(self.source)
        mutation(source)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "concept.json"
            path.write_text(json.dumps(source, allow_nan=True), encoding="utf-8")
            return calculation.load_source(path)

    def test_source_contract_and_all_local_pins(self):
        self.assertEqual(self.source["format"], "solidcraftbot.joint-bearings-holding/1")
        self.assertEqual(self.source["status"], "proposal_pending_owner_decision")
        self.assertEqual(self.source["phase"], 1)
        self.assertFalse(self.source["recommendation"]["brake_in_first_prototype"])
        self.assertFalse(self.source["physical_qualification"])
        self.assertEqual(self.source["source_refs"]["robot"]["path"], "model/robot.json")
        self.assertEqual(self.source["source_refs"]["actuators"]["path"], "model/actuator-selection.json")
        references = list(self.source["source_refs"].values())
        references += [item for item in self.source["vendor_evidence"]["sources"].values()
                       if "path" in item]
        for reference in references:
            with self.subTest(path=reference["path"]):
                path = ROOT / reference["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), reference["sha256"])
        with self.assertRaisesRegex(ValueError, "source pin"):
            self.load_mutated_source(lambda s: s["source_refs"]["robot"].update(sha256="0" * 64))

    def test_fixture_one_kg_horizontal_flange_has_hand_calculated_torques(self):
        rows = self.model.loads([self.unit_flange_mass()], self.simple_pose)
        # Hand calculation in metres: mg * (0.491, 0.291, 0.116).
        for index, expected in ((1, 4.81506515), (2, 2.85373515), (4, 1.1375714)):
            with self.subTest(joint=index + 1):
                self.assertAlmostEqual(rows[index]["gravity_torque_nm"], expected, places=10)
        transforms = robot_spec.forward(self.model.robot, self.simple_pose)
        flange = robot_spec.transform(transforms[self.model.links[-1]], self.model.flange)
        for actual, expected in zip(flange, [491.0, 0.0, 150.0]):
            self.assertAlmostEqual(actual, expected, places=10)
        # The actuator output face and kinematic anchor differ along the axis.
        self.assertEqual(rows[1]["joint_origin_mm"], [0.0, 52.0, 150.0])
        self.assertEqual(rows[1]["output_face_origin_mm"], [0.0, -52.0, 150.0])
        self.assertIsNone(rows[1]["true_internal_bearing_tilting_moment_nm"])

    def test_servo_parent_ownership_and_independent_servo_only_fixture(self):
        servos = self.cases["servo_only"]
        self.assertEqual([point["link"] for point in servos], self.model.links[:-1])
        rows = self.model.loads(servos, self.simple_pose)
        # Own servo mass is at its housing parent's output-face surrogate.
        # J2: g*(.36*.2 + .26*(.284+.375+.475)).
        # J3: g*.26*(.084+.175+.275); J5: g*.26*.1.
        for index, expected in ((1, 3.597471486), (2, 1.361555286), (4, 0.2549729)):
            self.assertAlmostEqual(rows[index]["gravity_torque_nm"], expected, places=10)
        own_servo = self.model.loads([servos[2]], self.simple_pose)
        self.assertAlmostEqual(own_servo[1]["gravity_torque_nm"], 0.7060788, places=10)
        self.assertEqual(own_servo[2]["gravity_torque_nm"], 0.0)

    def test_radial_radius_bound_covers_independent_pose_samples(self):
        points = self.cases["planning_loaded"]
        for sample in range(12):
            pose = [low + (high - low) * (((sample + 1) * (axis + 3) * 0.173) % 1.0)
                    for axis, (low, high) in enumerate(self.model.contexts["robot_limits"])]
            transforms = robot_spec.forward(self.model.robot, pose)
            for point in points:
                owner = self.model.links.index(point["link"])
                world = robot_spec.transform(transforms[point["link"]], point["point_mm"])
                for index in range(owner):
                    parent = transforms[self.model.joints[index]["parent"]]
                    origin = robot_spec.transform(parent, self.model.origins[index])
                    axis = [sum(parent[row][column] * self.model.axes[index][column]
                                for column in range(3)) for row in range(3)]
                    radial = vector_norm(vector_cross(axis, [(x - y) / 1000.0
                                                            for x, y in zip(world, origin)]))
                    with self.subTest(sample=sample, point=point["id"], joint=index):
                        self.assertLessEqual(radial, self.model.radius_bound(point, index) + 1e-12)

    def test_gravity_reduction_preserves_yaw_and_coaxial_last_roll(self):
        reference = [20.0, 35.0, 65.0, 21.0, 80.0, 15.0]
        expected = self.model.loads(self.cases["planning_loaded"], reference)
        for yaw, roll in ((-160.0, -170.0), (160.0, 170.0), (0.0, -30.0)):
            pose = list(reference)
            pose[0], pose[5] = yaw, roll
            rows = self.model.loads(self.cases["planning_loaded"], pose)
            for index in (1, 2, 3, 4):
                self.assertAlmostEqual(rows[index]["gravity_torque_nm"],
                                       expected[index]["gravity_torque_nm"], places=10)
            self.assertAlmostEqual(rows[0]["gravity_torque_nm"], 0.0, places=12)
            self.assertAlmostEqual(rows[5]["gravity_torque_nm"], 0.0, places=12)

    def test_unit_mass_sensitivity_is_linear_and_respects_known_coefficient(self):
        rows = self.model.loads([self.unit_flange_mass(0.3)], self.simple_pose)
        increased = self.model.loads([self.unit_flange_mass(0.5)], self.simple_pose)
        for index, coefficient in ((1, 4.81506515), (2, 2.85373515), (4, 1.1375714)):
            measured_coefficient = ((increased[index]["gravity_torque_nm"] - rows[index]["gravity_torque_nm"])
                                    / 0.2)
            self.assertAlmostEqual(measured_coefficient, coefficient, places=10)

    def test_counterbearing_reactions_balance_force_and_bending_not_drive_torque(self):
        for pose in (self.simple_pose, robot_spec.home(self.model.robot)):
            rows = self.model.loads([self.unit_flange_mass()], pose)
            for index in (0, 1, 2, 3, 4, 5):
                row = rows[index]
                result = calculation.support_example(self.model, row)
                axis = row["output_face_axis"]
                first, second = result["servo_reaction_n"], result["counterbearing_reaction_n"]
                for a, b, force in zip(first, second, row["force_external_n"]):
                    self.assertAlmostEqual(a + b + force, 0.0, places=10)
                span = result["analytical_example_span_mm"] / 1000.0
                support_moment = vector_cross([component * span for component in axis], second)
                total_moment = [a + b for a, b in zip(row["output_face_moment_nm"], support_moment)]
                torsion = sum(a * b for a, b in zip(total_moment, axis))
                for component, direction in zip(total_moment, axis):
                    self.assertAlmostEqual(component - torsion * direction, 0.0, places=10)
                self.assertAlmostEqual(sum(a * b for a, b in zip(second, axis)), 0.0, places=10)
                self.assertEqual(result["drive_torque_unchanged_nm"], row["gravity_torque_nm"])
                self.assertIsNone(result["actual_bearing_center_separation_mm"])
                self.assertIsNone(result["physical_internal_bearing_reactions_n"])

    def test_dynamic_bound_contains_tangential_and_centripetal_terms(self):
        # One 1kg point 0.1m from the vertical J1 axis, owned only by L1.
        point = self.model.point("yaw_test", self.model.links[1], [100.0, 0.0, 60.0], 1.0, "test")
        profile = {"velocity_rad_s": 1.0, "acceleration_rad_s2": 2.0, "jerk_rad_s3": 20.0}
        result = calculation.dynamic_bound(self.model, [point], profile)
        self.assertAlmostEqual(result["point_mass_coupled_acceleration_bounds"][0]
                               ["linear_acceleration_bound_m_s2"], 0.3)
        self.assertAlmostEqual(result["joint_torque_addition_upper_nm"][self.model.ids[0]], 0.03)
        # Actual simultaneous perpendicular accelerations have norm sqrt(.2²+.1²).
        self.assertGreaterEqual(result["force_addition_norm_upper_n"][self.model.ids[0]],
                                math.hypot(0.2, 0.1))
        self.assertFalse(result["qualified"])
        self.assertIn("intrinsic_link_rotor_inertia", result["omissions"])

    def test_power_loss_is_a_conditional_single_axis_model_not_actual_contact(self):
        result = calculation.power_loss(self.model, [self.unit_flange_mass()], self.simple_pose, 1,
                                        self.model.contexts["robot_limits"])
        self.assertEqual(result["hypothetical_endpoint_reason"], "software_range_boundary_not_a_physical_hardstop")
        self.assertAlmostEqual(result["hypothetical_single_joint_endpoint_deg"][1], 100.0)
        # Vertical drop from 90 to 100deg is 491mm*sin(10deg).
        self.assertAlmostEqual(result["hypothetical_tcp_fall_mm"], 85.2612552344628, places=8)
        self.assertAlmostEqual(result["point_mass_inertia_kg_m2"], 0.241081, places=10)
        self.assertAlmostEqual(result["initial_acceleration_rad_s2_without_intrinsic_inertia"],
                               13.33603705808421, places=8)
        for key in ("physical_hardstop_pose_deg", "first_contact_pose_deg", "actual_tcp_fall_mm",
                    "guaranteed_unpowered_holding", "driver_braking_evidence"):
            self.assertIsNone(result[key])
        self.assertEqual(result["driver_braking_credit_nm"], 0)
        self.assertFalse(result["power_loss_safety_verified"])
        self.assertIn("other_joints_artificially_fixed", result["conditions"])

    def test_zero_mass_stays_zero_without_inventing_inertia_or_acceleration(self):
        zero = [self.unit_flange_mass(0)]
        rows = self.model.loads(zero, self.simple_pose)
        self.assertTrue(all(row["gravity_torque_nm"] == 0 for row in rows))
        result = calculation.power_loss(self.model, zero, self.simple_pose, 1,
                                        self.model.contexts["robot_limits"])
        self.assertEqual(result["point_mass_inertia_kg_m2"], 0)
        self.assertIsNone(result["initial_acceleration_rad_s2_without_intrinsic_inertia"])
        self.assertIsNone(result["rough_energy_based_angular_speed_rad_s"])
        self.assertIsNone(result["actual_tcp_fall_mm"])

    def test_zero_planning_mass_source_reduces_to_servo_contribution(self):
        def remove_allowances(source):
            assumptions = source["assumptions"]
            for item in assumptions["planning_link_masses_kg"].values():
                item["value"] = 0.0
            assumptions["planning_tool_mass_kg"]["value"] = 0.0
            assumptions["planning_sample_mass_kg"]["value"] = 0.0
        source = self.load_mutated_source(remove_allowances)
        model = calculation.Model(source)
        cases = model.mass_sets()
        reference = model.loads(cases["servo_only"], self.simple_pose)
        for name in ("planning_loaded", "planning_empty"):
            rows = model.loads(cases[name], self.simple_pose)
            for actual, expected in zip(rows, reference):
                self.assertAlmostEqual(actual["gravity_torque_nm"], expected["gravity_torque_nm"])
                self.assertEqual(actual["force_external_n"], expected["force_external_n"])

    def test_backlash_uses_radians_and_local_chain_sum_and_preserves_unknowns(self):
        self.assertAlmostEqual(calculation.backlash_shift_mm(15, 500), 2.181661564992912, places=12)
        result = calculation.backlash_at_pose(self.model, self.simple_pose)
        for index, expected in ((0, 2.1423916568230394), (1, 2.1423916568230394),
                                (2, 1.2697270308258746), (4, 0.5061454830783556)):
            row = result["joints"][index]
            self.assertAlmostEqual(row["load_reversal_arc_bound_mm"], expected, places=10)
            self.assertTrue(row["compensation_required_if_motor_side_gear_term_exceeds_proposal"])
            self.assertFalse(row["compensation_implemented"])
            self.assertIsNone(row["actual_output_brake_tcp_shift_mm"])
            self.assertIsNone(row["elastic_compliance_mm_per_nm"])
        self.assertAlmostEqual(result["local_linearized_chain_sum_mm"], 6.060655827550309, places=10)
        for index in (3, 5):
            self.assertFalse(result["joints"][index]["compensation_required_if_motor_side_gear_term_exceeds_proposal"])
        self.assertFalse(result["positions_neutral_verified"])
        self.assertIsNone(result["application_chain_shift_mm"])

    def test_counterweight_J3_mass_is_included_in_J2_balance(self):
        # Isolate the balance construction from the independently tested optimizer.
        with patch.object(self.model, "extrema", return_value={"lower_bound": 0.0, "upper_bound": 0.0}):
            result = calculation.counterweight_analysis(self.model, self.cases)
        original = self.model.loads(self.cases["planning_loaded"], self.simple_pose)
        first, second = result["construction"]
        expected_elbow_mass = original[2]["gravity_torque_nm"] / (9.80665 * 0.175)
        self.assertAlmostEqual(first["derived_counterweight_mass_kg"], expected_elbow_mass)
        # The reflected elbow weight is at z=175mm, 25mm distal to J2 at z=150mm.
        expected_shoulder_target = original[1]["gravity_torque_nm"] + expected_elbow_mass * 9.80665 * 0.025
        self.assertAlmostEqual(second["reference_target_torque_nm"], expected_shoulder_target)
        self.assertAlmostEqual(second["derived_counterweight_mass_kg"],
                               expected_shoulder_target / (9.80665 * 0.2))
        self.assertAlmostEqual(result["reference_residual_all_joints_nm"][self.model.ids[1]], 0.0, places=10)
        self.assertAlmostEqual(result["reference_residual_all_joints_nm"][self.model.ids[2]], 0.0, places=10)
        self.assertFalse(result["power_loss_holding_verified"])

    def test_budget_known_sum_overrun_and_unknown_are_distinct(self):
        complete = calculation.budget_totals([
            {"id": "rings", "quantity": 3, "unit_gross_eur": 12.5},
            {"id": "structure", "quantity": 1, "unit_gross_eur": 100}], 700)
        self.assertEqual(complete["total_gross_eur"], 137.5)
        self.assertTrue(complete["fits_budget"])
        conditional = calculation.budget_totals([
            {"id": "rings", "quantity": 3, "unit_gross_eur": 12.5},
            {"id": "structure", "quantity": 1, "unit_gross_eur": None}], 700)
        self.assertEqual(conditional["known_subtotal_gross_eur"], 37.5)
        self.assertIsNone(conditional["total_gross_eur"])
        self.assertIsNone(conditional["fits_budget"])
        self.assertEqual(conditional["remaining_for_unknowns_eur"], 662.5)
        overrun = calculation.budget_totals([
            {"id": "structure", "quantity": 8, "unit_gross_eur": 100},
            {"id": "unknown", "quantity": 1, "unit_gross_eur": None}], 700)
        self.assertEqual(overrun["known_overrun_eur"], 100)
        self.assertFalse(overrun["fits_budget"])
        self.assertIsNone(overrun["total_gross_eur"])
        with self.assertRaises(ValueError):
            calculation.budget_totals([{"id": "bad", "quantity": -1, "unit_gross_eur": None}], 700)

    def test_assumption_units_nulls_and_numerical_domains_are_validated(self):
        for key, invalid in (("gravity_m_s2", "kg"), ("planning_tool_mass_kg", "mm"),
                             ("planning_sample_mass_kg", "s"), ("torque_safety_factor", "Nm")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load_mutated_source(lambda s, k=key, v=invalid: s["assumptions"][k].update(unit=v))
        for key in ("gravity_m_s2", "torque_safety_factor", "backdrive_safety_factor", "counterweight_arm_scale"):
            with self.subTest(zero=key), self.assertRaises(ValueError):
                self.load_mutated_source(lambda s, k=key: s["assumptions"][k].update(value=0))
        for invalid in (None, -1, True, float("nan"), float("inf")):
            with self.subTest(mass=invalid), self.assertRaises(ValueError):
                self.load_mutated_source(lambda s, v=invalid: s["assumptions"]["planning_tool_mass_kg"].update(value=v))
        self.load_mutated_source(lambda s: s["assumptions"]["planning_tool_mass_kg"].update(value=0))
        for key in ("hold_duration_s", "physical_stop_angles_deg", "first_contact_pose_deg",
                    "support_centres_measured_mm"):
            with self.subTest(unknown=key), self.assertRaises(ValueError):
                self.load_mutated_source(lambda s, k=key: s["assumptions"].update({k: 0}))

    def test_extrema_enclose_independently_known_wrist_maximum(self):
        result = self.model.extrema([self.unit_flange_mass()], 4,
                                    self.model.contexts["robot_limits"], self.simple_pose)
        # Wrist-flange distance perpendicular to J5 is always 0.116m; gravity
        # is perpendicular to that radius at the horizontal fixture pose.
        expected = 1.1375714
        self.assertLessEqual(result["lower_bound"], expected + 1e-10)
        self.assertGreaterEqual(result["upper_bound"], expected - 1e-10)
        self.assertIsNone(result["maximum_exact_nm"])
        self.assertFalse(result["pose_collision_checked"])

    def test_tracked_derived_report_and_cli_check_are_reproducible(self):
        # Missing required artifacts fail this test; they are never skipped.
        report_path = ROOT / "docs/joint-bearings-holding.report.json"
        self.assertTrue(report_path.is_file(), "Generate the required derived report before running the suite")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["derived"])
        self.assertEqual(report["source_sha256"], hashlib.sha256(calculation.SOURCE.read_bytes()).hexdigest())
        self.assertIn("not_a_proven_lower_bound", report["servo_case_interpretation"])
        self.assertFalse(report["brake_in_first_prototype"])
        self.assertFalse(report["owner_decision_gates"]["tool_fitted_park_inside_SP02_window"])
        self.assertFalse(report["qualification"]["safety"])
        self.assertTrue(all(value is None for value in report["open_measurements"].values()))
        for case in ("servo_only", "planning_loaded", "planning_empty"):
            for context in ("robot_limits", "sp02_window"):
                with self.subTest(case=case, context=context):
                    power_rows = report["power_loss"][case][context]
                    thermal_rows = report["thermal_holding"][case][context]
                    self.assertEqual({row["joint"] for row in power_rows}, set(self.model.ids))
                    self.assertEqual({row["joint"] for row in thermal_rows}, set(self.model.ids))
                    self.assertTrue(all(row["actual_tcp_fall_mm"] is None for row in power_rows))
                    self.assertTrue(all(row["thermal_acceptance"] is None for row in thermal_rows))
        for path, expected in report["source_files_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), expected)
        process = subprocess.run([sys.executable, str(ROOT / "scripts/joint_bearings_holding.py"), "--check"],
                                 cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("report is reproducible", process.stdout)


if __name__ == "__main__":
    unittest.main()
