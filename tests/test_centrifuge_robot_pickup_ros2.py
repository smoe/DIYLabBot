"""The ROS arm program is the sampled demonstration, not a new motion source."""
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import export_centrifuge_robot_pickup_ros2 as export
import build_ros2


def urdf_origin(joint):
    origin=joint.find('origin')
    x,y,z=[float(value) for value in origin.get('xyz','0 0 0').split()]
    roll,pitch,yaw=[float(value) for value in origin.get('rpy','0 0 0').split()]
    cr,sr,cp,sp,cy,sy=math.cos(roll),math.sin(roll),math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw)
    return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr,x],
            [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr,y],
            [-sp,cp*sr,cp*cr,z],[0.,0.,0.,1.]]


class PickupROS2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene=export.pickup.load();cls.data=export.pickup.trajectory(cls.scene)
        with patch.object(export.pickup,'trajectory',return_value=cls.data):
            cls.config=export.configuration()

    def test_every_arm_sample_and_time_is_preserved_in_radians(self):
        points=self.config['scenarios'][0]['points']
        self.assertEqual(len(points),len(self.data['samples']))
        self.assertEqual([point['time_s'] for point in points],[sample['time_s'] for sample in self.data['samples']])
        for point,sample in zip(points,self.data['samples']):
            for actual,expected in zip(point['positions_rad'],sample['joints_deg']):
                self.assertAlmostEqual(math.degrees(actual),expected,places=12)
        self.assertEqual(self.config['joint_names'],[joint['id'].lower() for joint in export.pickup.arm_source(self.scene)['joints']])

    def test_variant_fixture_tcp_and_sources_remain_explicit_requirements(self):
        requirements=self.config['robot_description_requirements']
        self.assertEqual(requirements['parameter_overrides_mm'],{'upper_len':280,'fore_len':250})
        for actual,expected in zip(requirements['base_position_m'],self.scene['arm_fixture']['position_mm']):
            self.assertAlmostEqual(actual*1000,expected)
        self.assertAlmostEqual(math.degrees(requirements['base_yaw_rad']),self.scene['arm_fixture']['yaw_deg'])
        self.assertFalse(requirements['compatibility_verified'])
        for source,digest in self.config['source_files_sha256'].items():
            self.assertEqual(export.pickup.robot.digest(ROOT/source),digest)
        self.assertIn('model/centrifuge-cf01.robot-pickup.shared.json',self.config['source_files_sha256'])
        self.assertIn('model/synthetic-cf01-workspace.shared.json',self.config['source_files_sha256'])
        self.assertEqual(self.config['included_channels'],['six_arm_joints'])
        self.assertFalse(any(self.config['verification'].values()))

    def test_tcp_matches_actual_generated_urdf_forward_kinematics(self):
        arm=export.pickup.arm_source(self.scene);requirements=self.config['robot_description_requirements']
        # Only link/joint frames matter here; no CAD mesh is built or inspected.
        geometry={'links':{link['id']:{'mesh':'unused.stl','collision_boxes':[]} for link in arm['links']}}
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory)
            for name in ['config','urdf']: (package/name).mkdir()
            with patch.object(build_ros2,'PACKAGE',package):build_ros2.generate(arm,geometry)
            urdf=ET.parse(package/'urdf/robot.urdf').getroot()
        kin=export.pickup.Kinematics(arm,self.scene)
        for index in [0,len(self.data['samples'])//2,len(self.data['samples'])-1]:
            sample=self.data['samples'][index]
            q=dict(zip(self.config['joint_names'],self.config['scenarios'][0]['points'][index]['positions_rad']))
            world={'base_link':export.pickup.placement(requirements['base_position_m'],math.degrees(requirements['base_yaw_rad']))}
            for joint in urdf.findall('joint'):
                turn=export.pickup.robot.identity()
                if joint.get('type')=='revolute':
                    angle=q[joint.get('name')];c,s=math.cos(angle),math.sin(angle)
                    turn[0][0],turn[0][1],turn[1][0],turn[1][1]=c,-s,s,c
                parent=world[joint.find('parent').get('link')]
                world[joint.find('child').get('link')]=export.pickup.robot.multiply(export.pickup.robot.multiply(parent,urdf_origin(joint)),turn)
            actual=export.pickup.robot.transform(world[requirements['tcp_parent_link']],requirements['tcp_position_in_parent_m'])
            expected=export.pickup.robot.transform(kin.tool(sample['joints_deg']),[0,0,0])
            self.assertLess(math.dist(actual,[value/1000 for value in expected]),1e-9)

    def test_joint_limits_and_mock_velocity_are_checked_before_export(self):
        for failure in ['limit','speed']:
            with self.subTest(failure=failure):
                data=copy.deepcopy(self.data)
                lower,upper=self.config['limits_rad'][0]
                if failure=='limit':data['samples'][1]['joints_deg'][0]=math.degrees(upper)+1
                else:
                    first=self.config['scenarios'][0]['points'][0]['positions_rad'][0]
                    data['samples'][1]['joints_deg'][0]=math.degrees(max([lower,upper],key=lambda value:abs(value-first)))
                with patch.object(export.pickup,'trajectory',return_value=data):
                    with self.assertRaisesRegex(ValueError,'outside limits|mock velocity limit'):
                        export.configuration()

    def test_source_change_during_export_is_rejected(self):
        sources=self.config['source_files_sha256'];changed={**sources,'model/robot.json':'changed'}
        with patch.object(export,'source_hashes',side_effect=[sources,changed]),patch.object(export.pickup,'trajectory',return_value=self.data):
            with self.assertRaisesRegex(ValueError,'sources changed during ROS export'):
                export.configuration()

    def test_existing_client_dry_run_accepts_the_complete_export_without_ros(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scenarios.json'
            path.write_text(json.dumps(self.config),encoding='utf-8')
            environment={**os.environ,'PYTHONPATH':str(ROOT/'ros2_ws/src/solidcraftbot_ros')}
            result=subprocess.run([sys.executable,'-B','-m','solidcraftbot_ros.demo','--dry-run',
                                   '--config',str(path),'--scenario',export.SCENARIO],
                                  cwd=ROOT,env=environment,capture_output=True,text=True,check=True,timeout=15)
            self.assertEqual(json.loads(result.stdout),{'joint_names':self.config['joint_names'],'scenario':self.config['scenarios'][0]})


if __name__=='__main__':unittest.main()
