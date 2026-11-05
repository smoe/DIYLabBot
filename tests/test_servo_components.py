"""Guard mechanical link assignment, provenance and lightweight ROS output."""
from pathlib import Path
import copy
import json
import math
import hashlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import robot_spec as model
import robot_components as components

class ServoComponents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=model.load()
        cls.library=components.library(cls.spec)

    def test_six_housings_and_outputs_follow_different_links(self):
        report=components.audit(self.spec)
        self.assertEqual(len(report["actuators"]),6)
        for result,joint in zip(report["actuators"],self.spec["joints"]):
            self.assertEqual(result["housing_link"],joint["parent"])
            self.assertEqual(result["output_link"],joint["child"])
        bad=copy.deepcopy(self.spec)
        op=next(o for o in bad["links"][0]["recipe"] if o["action"]=="vendor_component")
        op["section"]="output"
        with self.assertRaises(ValueError):components.audit(bad)

    def test_changed_library_cannot_silently_change_robot(self):
        spec=copy.deepcopy(self.spec);spec["vendor_library"]["sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"revision changed"):model.expanded(spec)

    def test_plates_lower_to_drawing_registered_bolt_patterns(self):
        expanded=model.expanded(self.spec)
        all_ops=[o for l in expanded["links"] for o in l["recipe"]]
        for link in self.spec["links"]:
            for op in link["recipe"]:
                if op["action"]!="mount_plate":continue
                interface=self.library["parts"][op["part"]]["interfaces"][op["section"]]
                holes=[o for o in all_ops if o["id"].startswith(op["id"]+"_bolt_")]
                self.assertEqual(len(holes),len(interface["hole_centres_mm"]))
                self.assertFalse(op["manufacturing_released"])
        self.assertTrue(self.library["parts"]["RMD-X6-P20-60-E"]["interfaces"]["housing"]["drawing_pattern_resolved"])

    def test_x6_housing_and_output_callouts_are_not_interchanged(self):
        part=self.library["parts"]["RMD-X6-P20-60-E"]
        for section,count,pcd,thread,clearance,core in [("housing",10,72.5,"M3",3.4,2.5),("output",12,44,"M4",4.5,3.3)]:
            interface=part["interfaces"][section]
            self.assertEqual(len(interface["hole_centres_mm"]),count)
            self.assertEqual(interface["bolt_circle_mm"],pcd)
            self.assertEqual(interface["vendor_thread"],thread)
            self.assertEqual(interface["plate_clearance_diameter_mm"],clearance)
            self.assertEqual(interface["cad_thread_core_diameter_mm"],core)
        evidence=ROOT/part["interface_check"]["path"]
        self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(),part["interface_check"]["sha256"])
        review=json.loads(evidence.read_text())
        self.assertTrue(review["passed"])
        self.assertEqual(review["interfaces"]["housing"]["matched_thread_core_count"],10)
        self.assertEqual(review["interfaces"]["output"]["matched_thread_core_count"],12)

    def test_x6_locating_sleeves_and_plate_bores_are_separate_from_fasteners(self):
        part=self.library["parts"]["RMD-X6-P20-60-E"]; interface=part["interfaces"]["housing"]
        locating=interface["locating_hole_centres_mm"]
        self.assertEqual(len(locating),2)
        self.assertFalse(set(map(tuple,locating)).intersection(map(tuple,interface["hole_centres_mm"])))
        self.assertEqual(interface["plate_locating_bore_diameter_mm"],5)
        self.assertAlmostEqual(part["sections"]["housing"]["bbox_mm"]["max"][2]-interface["z_mm"],2,places=5)
        evidence=json.loads((ROOT/part["interface_check"]["path"]).read_text())
        for pin in evidence["locating_pins"]:
            # Hollow 5/3-mm locating sleeve, length 8 mm, from the vendor STEP.
            self.assertAlmostEqual(pin["volume_mm3"],math.pi*(2.5**2-1.5**2)*8,places=4)
        expanded=model.expanded(self.spec)
        bores=[o for l in expanded["links"] for o in l["recipe"] if o["id"].startswith("A2_housing_plate_locating_")]
        self.assertEqual(len(bores),4) # round bore, two capsule ends and connecting prism
        cylinders=[o for o in bores if o["primitive"]["kind"]=="cylinder"]
        self.assertEqual(len(cylinders),3)
        self.assertTrue(all(o["primitive"]["radius"]==2.5 for o in cylinders))
        ends=[o for o in cylinders if "_end" in o["id"]]
        points=[[model.evaluate(v,model.parameters(self.spec)) for v in o["primitive"]["origin"]] for o in ends]
        self.assertAlmostEqual(math.dist(*points),.2,places=8)
        # Slot follows the radial line through the two locating centres.
        direction=[b-a for a,b in zip(*points)]
        self.assertAlmostEqual(abs(direction[0]),.2*abs(locating[1][1]-locating[0][1])/math.dist(*locating),places=8)

    @unittest.skipUnless((ROOT / 'exports/generated/build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_x6_native_plate_volumes_match_corrected_nominal_holes(self):
        build=json.loads((ROOT/"exports/generated/build-report.json").read_text())
        report=json.loads((ROOT/build["artifacts"]["freecad_report"]).read_text())
        bodies={b["body"]:b for b in report["geometry"]}
        source={o["body"]:o for l in self.spec["links"] for o in l["recipe"] if o["action"]=="mount_plate"}
        for body,count,diameter,locator_count in [("A2_housing_plate",10,3.4,2),("A2_output_plate",12,4.5,0)]:
            plate=source[body]
            thickness=model.evaluate(plate["thickness_mm"],model.parameters(self.spec))
            interface=self.library["parts"][plate["part"]]["interfaces"][plate["section"]]
            recess=interface["plate_head_recess"]
            expected=math.pi*thickness*(plate["outer_radius_mm"]**2-plate["clearance_radius_mm"]**2-count*(diameter/2)**2-locator_count*2.5**2)
            expected-=count*math.pi*((recess["diameter_mm"]/2)**2-(diameter/2)**2)*recess["depth_mm"]
            if locator_count:expected-=5*.2*thickness # extra rectangular area of radial capsule
            self.assertAlmostEqual(bodies[body]["volume_mm3"],expected,places=5)

    @unittest.skipUnless((ROOT / 'exports/generated/build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_x6_head_envelopes_clear_plates_and_adjacent_structure(self):
        build=json.loads((ROOT/"exports/generated/build-report.json").read_text())
        report=json.loads((ROOT/build["artifacts"]["freecad_report"]).read_text())
        check=report["x6_screw_head_clearance"]
        self.assertTrue(check["passed"])
        self.assertEqual(len(check["checks"]),22)
        self.assertTrue(all(not c["overlaps"] for c in check["checks"]))

    def test_vendor_components_and_plates_follow_length_changes(self):
        op=next(o for l in self.spec["links"] for o in l["recipe"] if o["id"]=="A3_housing")
        base=model.parameters(self.spec); changed=model.parameters(self.spec,{"upper_len":base["upper_len"]+20})
        self.assertAlmostEqual(model.evaluate(op["frame"]["origin"][2],changed)-model.evaluate(op["frame"]["origin"][2],base),20)

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_rviz_has_one_box_per_servo_and_no_vendor_detail_in_meshes(self):
        package=ROOT/"ros2_ws/src/solidcraftbot_ros"
        geometry=json.loads((package/"config/geometry.json").read_text())
        urdf=ET.parse(package/"urdf/robot.urdf").getroot()
        visuals=[v for v in urdf.findall("link/visual") if v.get("name","").endswith("_servo_box")]
        self.assertEqual(len(visuals),6)
        bodies={v.get("name").removesuffix("_servo_box") for v in visuals}
        self.assertEqual(bodies,{"A%d_housing"%i for i in range(1,7)})
        for visual in visuals:
            dimensions=[float(v) for v in visual.find("geometry/box").get("size").split()]
            self.assertTrue(all(.01<v<.1 for v in dimensions))
        for name,link in geometry["links"].items():
            expected=[o["body"] for l in self.spec["links"] if l["id"]==name for o in l["recipe"] if o["action"]=="vendor_component"]
            self.assertFalse(set(expected).intersection(link["mesh_bodies"]))
            for body in expected:self.assertIn(body,{b["body"] for b in link["collision_boxes"]})
        self.assertEqual(geometry["spec_sha256"],model.digest(model.SPEC))

if __name__=="__main__":unittest.main()
