"""Camera frame attachment, visual-only cones and provisional wiring contracts."""
from pathlib import Path
import copy
import json
import math
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import robot_spec as model
import robot_cameras as cameras
from test_model_interfaces import origin_matrix


class CameraContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = model.load()
        cls.package = ROOT / "ros2_ws/src/solidcraftbot_ros"
        if not (cls.package / "urdf/robot.urdf").is_file(): return
        cls.urdf = ET.parse(cls.package / "urdf/robot.urdf").getroot()
        cls.geometry = json.loads((cls.package / "config/geometry.json").read_text())

    def test_tip_route_includes_the_final_wrist_joint(self):
        report = cameras.audit(self.spec)
        by_id = {c["id"]: c for c in report["cameras"]}
        self.assertEqual(by_id["C_tip"]["required_joint_passages"], [j["id"] for j in self.spec["joints"]])
        self.assertEqual(by_id["C_scene"]["required_joint_passages"], ["J1_BaseYaw"])
        for camera in by_id.values():
            self.assertFalse(camera["manufacturing_released"])
            self.assertIsNone(camera["part"])
            self.assertFalse(camera["occlusion_checked"])
            self.assertFalse(camera["cone_is_collision_geometry"])

    def test_invalid_camera_frame_and_false_qualification_are_rejected(self):
        for mutation in ("release", "occlusion", "frame", "route", "range"):
            with self.subTest(mutation=mutation):
                spec = copy.deepcopy(self.spec)
                tip = next(c for _, c in cameras.cameras(spec) if c["purpose"] == "tip")
                if mutation == "release": tip["manufacturing_released"] = True
                elif mutation == "occlusion": tip["view"]["occlusion_checked"] = True
                elif mutation == "frame": tip["frame"]["x"] = tip["frame"]["axis"]
                elif mutation == "route": tip["connection"]["route_links"].pop()
                else: spec["parameters"]["cam_tip_range"]["expression"] = "-1"
                with self.assertRaises(ValueError): model.expanded(spec)

    def test_cone_apex_and_tip_target_share_the_declared_optical_axis(self):
        spec = copy.deepcopy(self.spec)
        spec["parameters"]["upper_len"]["expression"] = "220"
        spec["parameters"]["cam_tip_range"]["expression"] = "170"
        p = model.parameters(spec)
        expanded = model.expanded(spec)
        for link, camera in cameras.cameras(spec):
            cone = next(o["primitive"] for l in expanded["links"] for o in l["recipe"] if o["id"] == camera["id"] + "_view_CONE")
            apex = [model.evaluate(v, p) + z * model.evaluate(cone["length"], p) for v, z in zip(cone["origin"], cone["axis"])]
            for actual, value in zip(apex, camera["frame"]["origin"]):
                self.assertAlmostEqual(actual, model.evaluate(value, p), places=8)
            self.assertEqual(cone["top_radius"], 0)
        tip = next(c for _, c in cameras.cameras(spec) if c["purpose"] == "tip")
        origin = [model.evaluate(v, p) for v in tip["frame"]["origin"]]
        distance = origin[0] / -tip["frame"]["axis"][0]
        target = [a + distance * z for a, z in zip(origin, tip["frame"]["axis"])]
        self.assertAlmostEqual(target[0], 0)
        self.assertAlmostEqual(target[2] - model.evaluate(spec["flange_reference"]["point"][2], p), 128)

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_urdf_optical_frames_follow_their_links_in_multiple_poses(self):
        poses = [model.home(self.spec), [0] * 6, [35, 40, 55, 20, 70, -45]]
        p = model.parameters(self.spec)
        for q in poses:
            frames = {"base_link": model.identity()}
            index = 0
            for joint in self.urdf.findall("joint"):
                relative = origin_matrix(joint.find("origin"))
                turn = model.identity()
                if joint.get("type") == "revolute":
                    a = math.radians(q[index]); index += 1
                    turn[0][0], turn[0][1], turn[1][0], turn[1][1] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
                frames[joint.find("child").get("link")] = model.multiply(model.multiply(frames[joint.find("parent").get("link")], relative), turn)
            expected = model.forward(self.spec, q)
            for link, camera in cameras.cameras(self.spec):
                target = model.multiply(expected[link], model.frame({"frame": camera["frame"]}, p))
                actual = frames[camera["id"].lower() + "_optical"]
                for i in range(4):
                    for j in range(4): self.assertAlmostEqual(actual[i][j], target[i][j], places=6)
        self.assertEqual(len(self.urdf.findall("joint[@type='revolute']")), 6)

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_cones_are_translucent_visuals_and_never_collision_bodies(self):
        collision_names = {c.get("name") for c in self.urdf.findall("link/collision")}
        mesh_bodies = {name for link in self.geometry["links"].values() for name in link["mesh_bodies"]}
        for link, camera in cameras.cameras(self.spec):
            name = camera["id"] + "_view_CONE"
            visual = self.urdf.find("link/visual[@name='%s']" % name)
            self.assertIsNotNone(visual)
            self.assertAlmostEqual(float(visual.find("material/color").get("rgba").split()[3]), camera["view"]["opacity"])
            self.assertNotIn(name + "_conservative_box", collision_names)
            self.assertIn(camera["id"] + "_body_ENVELOPE_conservative_box", collision_names)
            self.assertNotIn(name, mesh_bodies)
        config = json.loads((self.package / "config/cameras.json").read_text())
        self.assertFalse(config["image_topics_implemented"])
        self.assertEqual(config["spec_sha256"], model.digest(model.SPEC))

    @unittest.skipUnless((ROOT / 'exports/generated/build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_freecad_native_cones_frames_and_saved_transparency(self):
        build = json.loads((ROOT / "exports/generated/build-report.json").read_text())
        validation = json.loads((ROOT / build["artifacts"]["freecad_report"]).read_text())
        self.assertEqual(validation["excluded_collision_roles"], ["viewing_cone"])
        self.assertTrue(validation["passed"])
        for case in validation["camera_parameter_changes"]:
            self.assertLess(case["max_camera_and_link_probe_error_mm"], 1e-6)
        with zipfile.ZipFile(ROOT / build["artifacts"]["freecad"]) as archive:
            doc = ET.fromstring(archive.read("Document.xml"))
            gui = ET.fromstring(archive.read("GuiDocument.xml"))
            for _, camera in cameras.cameras(self.spec):
                cone = camera["id"] + "_view_CONE"
                self.assertEqual(doc.find("Objects/Object[@name='%s']" % cone).get("type"), "Part::Cone")
                self.assertIsNotNone(doc.find("Objects/Object[@name='%s_optical']" % camera["id"]))
                props = gui.find("ViewProviderData/ViewProvider[@name='%s']/Properties" % cone)
                self.assertEqual(props.find("Property[@name='Visibility']/Bool").get("value"), "true")
                self.assertEqual(int(props.find("Property[@name='Transparency']/Integer").get("value")), round(100 * (1 - camera["view"]["opacity"])))


if __name__ == "__main__": unittest.main()
