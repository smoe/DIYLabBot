"""Exercise the shared stationary camera variants without native CAD."""

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stationary_camera as camera
from tube_carrier_model import numeric_shape


class StationaryCameraTests(unittest.TestCase):
    def setUp(self):
        self.catalog = camera.load()
        self.fixed = camera.materialize(self.catalog, "fixed")
        self.steerable = camera.materialize(self.catalog, "pan_tilt")

    def test_both_mounts_reuse_the_same_camera_and_plate_geometry(self):
        edited = {"head_depth": 56}
        dimensions = []
        for spec in (self.fixed, self.steerable):
            parameters = camera.parameters(spec, edited)
            source = camera.expanded(spec, parameters)
            geometry = {
                operation["body"]: numeric_shape(operation["shape"], parameters)
                for operation in source["operations"]
            }
            dimensions.append({key: geometry[key] for key in ("MountingPlate", "CameraHousing", "Lens")})
            self.assertEqual(geometry["CameraHousing"]["size"][0], edited["head_depth"])
            self.assertEqual(geometry["Lens"]["origin"][0], edited["head_depth"] / 2)
        self.assertEqual(*dimensions)
        self.assertNotEqual(camera.parameters(self.fixed)["head_depth"], edited["head_depth"])

    def test_mount_stays_grounded_and_only_the_steerable_head_has_joints(self):
        for spec in (self.fixed, self.steerable):
            geometry = camera.expanded(spec, camera.parameters(spec))
            self.assertEqual([part["id"] for part in geometry["components"] if part["grounded"]], ["Mount"])
            owners = {body["id"]: body["component"] for body in geometry["bodies"]}
            self.assertEqual(owners["MountingPlate"], "Mount")
            if spec is self.fixed:
                self.assertEqual(geometry["joints"], [])
                self.assertEqual(owners["CameraHousing"], "Mount")
                with self.assertRaises(ValueError):
                    camera.validate_pose(geometry, {"Tilt": 10})
            else:
                self.assertEqual(
                    [(joint["id"], joint["parent"], joint["child"], joint["type"]) for joint in geometry["joints"]],
                    [("Pan", "Mount", "Turret", "revolute"), ("Tilt", "Turret", "Head", "revolute")],
                )
                self.assertEqual(owners["CameraHousing"], "Head")

    def test_optical_frame_tracks_pan_and_downward_tilt(self):
        parameters = camera.parameters(self.steerable)
        self.assertEqual(
            camera.optical_frame(self.steerable, parameters),
            camera.optical_frame(self.fixed, camera.parameters(self.fixed)),
        )
        frame = camera.optical_frame(self.steerable, parameters, {"Pan": 90, "Tilt": 30})
        extension = parameters["head_depth"] / 2 + parameters["lens_depth"]
        expected = {
            "origin_mm": (0, math.sqrt(3) / 2 * extension, parameters["pivot_z"] - extension / 2),
            "axis": (0, math.sqrt(3) / 2, -0.5),
            "x": (1, 0, 0),
        }
        for key, vector in expected.items():
            for actual, reference in zip(frame[key], vector, strict=True):
                self.assertAlmostEqual(actual, reference, places=9)

    def test_pose_samples_respect_limits_and_invalid_inputs_fail(self):
        parameters = camera.parameters(self.steerable)
        geometry = camera.expanded(self.steerable, parameters)
        for sample in camera.samples(self.steerable, parameters):
            camera.validate_pose(geometry, sample["joint_values"])
        for values in (
            {"Pan": -1, "Tilt": 0},
            {"Pan": 0, "Tilt": parameters["tilt_travel"] + 1},
            {"Pan": math.nan, "Tilt": 0},
            {"Pan": 0},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                camera.validate_pose(geometry, values)
        with self.assertRaises(ValueError):
            camera.materialize(self.catalog, "unknown")
        with self.assertRaises(ValueError):
            camera.parameters(self.steerable, {"head_width": 500})

    def test_solidcraft_commands_use_the_same_head_joints(self):
        for spec in (self.fixed, self.steerable):
            commands = camera.solidcraft_commands(spec, camera.parameters(spec))
            metadata = next(row["params"]["values"] for row in commands if row["command"] == "document.metadata.set")
            self.assertEqual(metadata["org.solidcraftbot.stationary-camera"]["variant"], spec["variant"])
            joints = [row["params"] for row in commands if row["command"] == "joint.create"]
            if spec is self.fixed:
                self.assertEqual(joints, [])
                self.assertFalse(any(row["command"] == "joint.drive" for row in commands))
            else:
                self.assertEqual([(joint["name"], joint["type"]) for joint in joints],
                                 [("Pan", "revolute"), ("Tilt", "revolute")])
                self.assertEqual([joint["a"]["frame"]["z"] for joint in joints], [[0, 0, 1], [0, 1, 0]])

    def test_catalog_rejects_incorrect_units(self):
        self.catalog["parameters"]["tilt_travel"]["unit"] = "mm"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-camera.json"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            with self.assertRaises(ValueError):
                camera.load(path)


if __name__ == "__main__":
    unittest.main()
