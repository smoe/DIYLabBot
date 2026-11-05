"""Hidden electromechanical requirements must retain connectivity and limits."""
from pathlib import Path
import copy
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import robot_spec as model
import robot_services as services


class ServiceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = model.load()

    def test_routes_follow_physical_motor_mounts(self):
        report = services.audit(self.spec)
        self.assertTrue(report["logical_topology_passed"])
        crossings = {c["target"]: c["crossed_joints"] for c in report["circuits"]}
        self.assertEqual(crossings["A1"], [])
        self.assertEqual(crossings["A3"], ["J1_BaseYaw", "J2_Shoulder"])
        self.assertEqual(crossings["A6"], [j["id"] for j in self.spec["joints"][:5]])
        self.assertEqual(report["physical_validation"]["status"], "not_performed")
        self.assertTrue(all(not value for key, value in report["physical_validation"].items() if key != "status"))

    def test_missing_motor_feedback_or_supply_is_rejected(self):
        for mutation in ("feedback", "supply", "motor"):
            with self.subTest(mutation=mutation):
                spec = copy.deepcopy(self.spec)
                if mutation == "feedback":
                    spec["services"]["actuators"][0]["required_feedback"].remove("measured_position")
                elif mutation == "supply":
                    spec["services"]["harness"]["circuits"].pop()
                else:
                    spec["services"]["actuators"][2]["mounted_link"] = "L3_Elbow"
                with self.assertRaises(ValueError):
                    services.audit(spec)

    def test_cannot_skip_a_moving_boundary_or_passage(self):
        for mutation in ("route", "passage"):
            with self.subTest(mutation=mutation):
                spec = copy.deepcopy(self.spec)
                harness = spec["services"]["harness"]
                if mutation == "route":
                    harness["circuits"][-1]["route_links"].remove("L2_UpperArm")
                else:
                    harness["joint_passages"].pop()
                with self.assertRaises(ValueError):
                    services.audit(spec)

    def test_cable_allowance_cannot_hide_joint_limit_mismatch(self):
        spec = copy.deepcopy(self.spec)
        passage = spec["services"]["harness"]["joint_passages"][0]
        passage.update(scheme="service_loop", neutral_deg=20, allowed_limits_deg=[-90, 90])
        with self.assertRaisesRegex(ValueError, "does not cover"):
            services.audit(spec)
        passage["allowed_limits_deg"] = [-160, 160]
        # An adequate angular declaration is still not a verified physical route.
        self.assertFalse(services.audit(spec)["physical_validation"]["torsion"])

    def test_hidden_requirements_preserve_rigid_model_commands(self):
        # A service-only edit cannot change the geometry or its commands.
        changed=copy.deepcopy(self.spec)
        changed["services"]["actuators"][0]["feedback"]["latency_ms"]=5
        self.assertEqual(model.solidcraft_commands(self.spec),model.solidcraft_commands(changed))


if __name__ == "__main__":
    unittest.main()
