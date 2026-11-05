"""Offline contract checks; no ROS installation required."""
from pathlib import Path
import copy
import json
import math
import struct
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"ros2_ws/src/solidcraftbot_ros"))
import robot_spec as model
from solidcraftbot_ros.protocol import scenario,duration_parts


def origin_matrix(origin):
    x,y,z=[float(v)*1000 for v in origin.get("xyz","0 0 0").split()]
    r,p,yaw=[float(v) for v in origin.get("rpy","0 0 0").split()]
    cr,sr,cp,sp,cy,sy=math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(yaw),math.sin(yaw)
    return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr,x],
            [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr,y],[-sp,cp*sr,cp*cr,z],[0.,0.,0.,1.]]


class ModelContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=model.load()
        if not (ROOT/"ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf").is_file(): return
        cls.urdf=ET.parse(ROOT/"ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf").getroot()
        cls.config=json.loads((ROOT/"ros2_ws/src/solidcraftbot_ros/config/scenarios.json").read_text())

    def test_forward_kinematics_against_numeric_a01_reference(self):
        source=json.loads((ROOT/"model/kinematic-reference.json").read_text(encoding="utf-8"))
        expected=model.forward(self.spec)
        for name,native in source["nominal_occurrences"].items():
            for i in range(4):
                for j in range(4): self.assertAlmostEqual(expected[name][i][j],native[j][i],places=8)

    @unittest.skipUnless((ROOT / 'exports/generated/build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_freecad_saved_visibility_and_letter_materials(self):
        build=json.loads((ROOT/"exports/generated/build-report.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(ROOT/build["artifacts"]["freecad"]) as archive:
            gui=ET.fromstring(archive.read("GuiDocument.xml"))
            doc=ET.fromstring(archive.read("Document.xml"))
            providers={p.get("name"):p for p in gui.findall("ViewProviderData/ViewProvider")}
            letters=[]
            for obj in doc.findall("ObjectData/Object"):
                body=obj.find("Properties/Property[@name='SourceBody']/String")
                if body is None: continue
                provider=providers[obj.get("name")]
                self.assertEqual(provider.find("Properties/Property[@name='Visibility']/Bool").get("value"),"true")
                if body.get("value").startswith("UMR_"):
                    letters.append(body.get("value"))
                    material=provider.find("Properties/Property[@name='ShapeAppearance']/MaterialList").get("file")
                    data=archive.read(material)
                    self.assertEqual(struct.unpack_from("<I",data,0)[0],1)
                    self.assertEqual(struct.unpack_from("<I",data,8)[0],0x0f2d4bff)
            self.assertEqual(set(letters),{"UMR_U_0","UMR_M_1","UMR_R_2"})
            for obj in doc.findall("Objects/Object"):
                if obj.get("type") in {"App::Origin","App::Line","App::Plane","App::Point"}:
                    provider=providers[obj.get("name")]
                    self.assertEqual(provider.find("Properties/Property[@name='Visibility']/Bool").get("value"),"false")

    def test_length_change_moves_joint_anchors(self):
        parameters=model.parameters(self.spec,{"upper_len":220})
        self.assertEqual(parameters["elbow_z"],370)
        self.assertEqual(parameters["wrist_z"],545)
        self.assertEqual(model.frame(self.spec["joints"][2],parameters)[2][3],370)
        self.assertEqual(model.frame(self.spec["joints"][4],parameters)[2][3],545)

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_urdf_joint_frames_and_metres_match_model(self):
        poses=[[0]*6,model.home(self.spec)]
        for axis in range(6):
            q=model.home(self.spec); q[axis]+=5; poses.append(q)
        parameters=model.parameters(self.spec)
        for q in poses:
            world={"base_link":model.identity()}; index=0
            expected=model.forward(self.spec,q)
            for joint in self.urdf.findall("joint"):
                relative=origin_matrix(joint.find("origin"))
                parent=joint.find("parent").get("link"); child=joint.find("child").get("link")
                turn=model.identity()
                if joint.get("type")=="revolute":
                    a=math.radians(q[index]); c,s=math.cos(a),math.sin(a)
                    turn[0][0],turn[0][1],turn[1][0],turn[1][1]=c,-s,s,c
                    target=model.multiply(expected[self.spec["joints"][index]["child"]],model.frame(self.spec["joints"][index],parameters))
                    index+=1
                else: target=None
                world[child]=model.multiply(model.multiply(world[parent],relative),turn)
                if target:
                    for i in range(4):
                        for j in range(4): self.assertAlmostEqual(world[child][i][j],target[i][j],places=6)
            expected_tool=model.transform(expected[self.spec["flange_reference"]["link"]],[model.evaluate(v,parameters) for v in self.spec["flange_reference"]["point"]])
            for actual,value in zip(model.transform(world["tool0"],[0,0,0]),expected_tool): self.assertAlmostEqual(actual,value,places=6)

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_ros_joint_order_limits_and_home(self):
        joints=self.urdf.findall("joint[@type='revolute']")
        self.assertEqual([j.get("name") for j in joints],self.config["joint_names"])
        self.assertEqual(len(joints),6)
        first=scenario(self.config,"base_sweep_return")["points"][0]["positions_rad"]
        for joint,description,value in zip(joints,self.spec["joints"],first):
            self.assertAlmostEqual(float(joint.find("limit").get("lower")),math.radians(description["limits_deg"][0]))
            self.assertAlmostEqual(value,math.radians(description["home_deg"]))

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_reject_out_of_range_and_excessive_speed(self):
        config=copy.deepcopy(self.config)
        config["scenarios"][0]["points"][1]["positions_rad"][0]=99
        with self.assertRaises(ValueError): scenario(config,"base_sweep_return")
        config=copy.deepcopy(self.config)
        config["velocity_limit_rad_s"]=0.001
        with self.assertRaises(ValueError): scenario(config,"base_sweep_return")

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_reject_time_errors_and_unknown_scenario(self):
        config=copy.deepcopy(self.config)
        config["scenarios"][0]["points"][1]["time_s"]=0
        with self.assertRaises(ValueError): scenario(config,"base_sweep_return")
        with self.assertRaises(ValueError): scenario(self.config,"undefined")
        self.assertEqual(duration_parts(1.9999999999),(2,0))

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_simulation_scope_and_mesh_assets(self):
        self.assertEqual(self.urdf.find("ros2_control/hardware/plugin").text,"mock_components/GenericSystem")
        self.assertFalse(self.urdf.findall("link/inertial"))
        self.assertTrue(self.urdf.findall("link/visual[@name='UMR_marking']"))
        for mesh in self.urdf.findall("link/visual/geometry/mesh"):
            relative=mesh.get("filename").split("package://solidcraftbot_ros/",1)[1]
            path=ROOT/"ros2_ws/src/solidcraftbot_ros"/relative
            self.assertTrue(path.is_file()); self.assertGreater(path.stat().st_size,84)
        self.assertEqual(self.config["spec_sha256"],model.digest(model.SPEC))

    @unittest.skipUnless((ROOT / 'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_mesh_coordinates_are_in_metres(self):
        for path in (ROOT/"ros2_ws/src/solidcraftbot_ros/meshes").glob("*.stl"):
            data=path.read_bytes(); count=struct.unpack_from("<I",data,80)[0]
            self.assertEqual(len(data),84+50*count)
            largest=0.
            for index in range(count):
                vertex_values=struct.unpack_from("<9f",data,84+index*50+12)
                largest=max(largest,max(abs(v) for v in vertex_values))
            self.assertGreater(largest,0.005)
            self.assertLess(largest,1.0)


if __name__=="__main__": unittest.main()
