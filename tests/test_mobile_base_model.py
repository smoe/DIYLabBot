"""MB01 support transfer, source boundaries, relative frames and build evidence."""
from pathlib import Path
import copy
import json
import math
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import mobile_base_model as mobile
import robot_spec as robot
import station_model


class MobileBaseContracts(unittest.TestCase):
    def setUp(self):
        self.spec=mobile.load(); self.arm=robot.load(); self.p=mobile.parameters(self.spec)

    def test_external_base_preserves_six_axis_arm_contract(self):
        self.assertEqual(len(self.arm['links']),7); self.assertEqual(len(self.arm['joints']),6)
        self.assertEqual(self.arm['mobile_base']['source'],'model/mobile-base-mb01.shared.json')
        compiled=mobile.solidcraft_commands(self.spec,self.arm,self.p)
        names=[c['params']['name'] for c in compiled if c['command']=='joint.create']
        self.assertEqual(len(names),11)  # plus the as-built rigid mounting joint
        self.assertEqual(set(j['id'] for j in self.arm['joints']),{n for n in names if n.startswith('J')})

    def test_working_supports_touch_table_while_wheels_are_unloaded(self):
        for overrides in [{},{'mb_wheel_radius':24},{'mb_length':420},{'mb_foot_clearance':10}]:
            p=mobile.parameters(self.spec,overrides)
            for name in ['working','parking_supported','manual_reposition']:
                s=mobile.state(self.spec,self.arm,p,name)
                foot_bottom=p['mb_foot_clearance']-s['support_extension_mm']+s['chassis_lift_mm']
                if s['supports']=='deployed':
                    self.assertAlmostEqual(foot_bottom,0); self.assertGreater(s['chassis_lift_mm'],0)
                else:
                    self.assertAlmostEqual(s['chassis_lift_mm'],0); self.assertGreater(foot_bottom,0)

    def test_wheels_and_support_columns_have_separate_clearance_envelopes(self):
        for overrides in [{},{'mb_width':320},{'mb_wheel_radius':26,'mb_wheel_width':22,'mb_wheel_inset_y':75}]:
            p=mobile.parameters(self.spec,overrides); expanded=mobile.expanded(self.spec,p)
            for w in expanded['wheels']:
                wc=[robot.evaluate(v,p) for v in w['center']]
                for support in expanded['supports']:
                    foot=[robot.evaluate(v,p) for v in support['contact']]
                    # For the near front feet, Y separates the complete wheel
                    # fork envelope and the foot pad; rear feet are far away.
                    if abs(wc[0]-foot[0])<2*p['mb_wheel_radius']:
                        self.assertGreater(abs(wc[1]-foot[1]),p['mb_wheel_width']/2+6+p['mb_pad_radius'])

    def test_parameters_move_mount_and_named_support_frames_together(self):
        original=mobile.expanded(self.spec,self.p)
        changed=mobile.parameters(self.spec,{'mb_length':420,'mb_wheel_radius':24})
        variant=mobile.expanded(self.spec,changed)
        self.assertAlmostEqual(changed['mb_mount_z']-self.p['mb_mount_z'],4)
        self.assertAlmostEqual(robot.evaluate(variant['frames']['MB01.Support.A'][0],changed)-robot.evaluate(original['frames']['MB01.Support.A'][0],self.p),10)
        self.assertAlmostEqual(robot.evaluate(variant['frames']['MB01.Support.C'][0],changed)-robot.evaluate(original['frames']['MB01.Support.C'][0],self.p),-10)

    def test_oriented_servo_imports_receive_the_world_mounting_offset(self):
        # A local Z move of an import with a Y-axis motor moves it sideways.
        # Compare the actual import and joint frame translations to the design
        # world points, rather than accepting merely successful CAD commands.
        offset=[0,0,self.p['mb_mount_z']]
        commands=robot.solidcraft_commands(self.arm,root_offset=offset)
        imports={c['params']['name']:c['params']['matrix'] for c in commands if c['command']=='file.insert_step'}
        p=robot.parameters(self.arm)
        for link in robot.expanded(self.arm)['links']:
            for op in link['recipe']:
                if op['action']=='create' and op['primitive']['kind']=='vendor_step':
                    expected=[robot.evaluate(v,p)+delta for v,delta in zip(op['primitive']['origin'],offset)]
                    actual=imports[op['id']+'_import']
                    for i in range(3): self.assertAlmostEqual(actual[i][3],expected[i])
        joints={c['params']['name']:c['params'] for c in commands if c['command']=='joint.create'}
        for joint in self.arm['joints']:
            expected=[robot.evaluate(v,p)+delta for v,delta in zip(joint['frame']['origin'],offset)]
            self.assertEqual(joints[joint['id']]['a']['frame']['origin'],expected)

    def test_manual_motion_preserves_local_relative_geometry(self):
        a=[17,-23,81]; b=[-6,43,122]; pose=mobile.state(self.spec,self.arm,self.p,'parked_aside')
        t=mobile.frame_matrix(pose)
        self.assertAlmostEqual(math.dist(a,b),math.dist(robot.transform(t,a),robot.transform(t,b)),places=10)
        self.assertFalse(self.spec['vision']['precision_dock_required'])
        self.assertTrue(self.spec['vision']['localization_invalidated_by_manual_move'])

    def test_invalid_qualification_pose_and_visual_controller_claims_are_rejected(self):
        for change in ['release','camera','localization','pose','support','parameter']:
            with self.subTest(change=change):
                s=copy.deepcopy(self.spec)
                if change=='release': s['qualification']['manufacturing_released']=True
                elif change=='camera': s['vision']['visual_servo_implemented']=True
                elif change=='localization': s['vision']['localization_invalidated_by_manual_move']=False
                elif change=='pose': s['poses']['manual_reposition']['arm_deg'][2]=180
                elif change=='support': s['poses']['working']['supports']='retracted'
                else: s['parameters']['mb_width']['expression']=50
                with self.assertRaises(ValueError): mobile.validate(s)

    def test_fold_samples_respect_limits_and_keep_support_until_folded(self):
        samples=mobile.samples(self.spec,self.arm,self.p)
        previous=None
        for sample in samples:
            if sample['id'].startswith('MB01.Fold.'):
                q=sample['state']['arm_deg']
                self.assertEqual(sample['state']['supports'],'deployed')
                for j,v in zip(self.arm['joints'],q): self.assertLessEqual(j['limits_deg'][0],v); self.assertLessEqual(v,j['limits_deg'][1])
                if previous: self.assertLessEqual(max(abs(a-b) for a,b in zip(q,previous)),self.spec['checks']['fold_sample_step_deg']+1e-8)
                previous=q
        resume=self.spec['protocol']['steps'][-1]['requires']
        for guard in ['fresh_tip_and_tube_observation','depth_and_orientation_observable','operator_resume']: self.assertIn(guard,resume)


class MobileBaseBuildEvidence(unittest.TestCase):
    @unittest.skipUnless((ROOT / 'cad/mobile-base-mb01/shared-build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_native_freecad_files_persist_the_named_poses_and_source_ids(self):
        report=json.loads((ROOT/'cad/mobile-base-mb01/shared-build-report.json').read_text())
        spec=mobile.load(); arm=robot.load(); p=mobile.parameters(spec)
        for state in report['states']:
            with self.subTest(state=state['id']), zipfile.ZipFile(ROOT/state['freecad']) as archive:
                doc=ET.fromstring(archive.read('Document.xml'))
                controller=next(o for o in doc.findall('ObjectData/Object') if o.get('name')=='Controller')
                properties={v.get('name'):v[0].get('value') for v in controller.findall('Properties/Property') if len(v)}
                pose=mobile.state(spec,arm,p,state['id'])
                self.assertEqual(properties['MB01_Pose'],state['id'])
                self.assertEqual(properties['SpecSHA256'],robot.digest(robot.SPEC))
                self.assertEqual(properties['MB01_SourceSHA256'],mobile.digest(mobile.SOURCE))
                for i,angle in enumerate(pose['arm_deg'],1): self.assertAlmostEqual(float(properties['J'+str(i)]),angle)
                for key,value in zip(['MB01_BaseX','MB01_BaseY','MB01_BaseYaw'],pose['manual_xy_yaw']): self.assertAlmostEqual(float(properties[key]),value)
                self.assertAlmostEqual(float(properties['MB01_ChassisLift']),pose['chassis_lift_mm'])
                for tag in 'ABC': self.assertAlmostEqual(float(properties['MB01_Support'+tag]),pose['support_extension_mm'])
                self.assertIn('GuiDocument.xml',archive.namelist())

    @unittest.skipUnless((ROOT / 'cad/mobile-base-mb01/shared-build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_both_cads_all_states_and_dimension_variants_have_matching_sources(self):
        report=json.loads((ROOT/'cad/mobile-base-mb01/shared-build-report.json').read_text())
        self.assertTrue(report['passed']); self.assertEqual(report['source_sha256'],mobile.digest(mobile.SOURCE))
        self.assertEqual(report['arm_sha256'],robot.digest(robot.SPEC)); self.assertTrue(report['solidcraft_joints_resolve'])
        self.assertEqual(report['solidcraft_joint_count'],12)
        for state in report['states']:
            self.assertTrue(state['passed'])
            for backend in ['solidcraft','freecad']: self.assertEqual(robot.digest(ROOT/state[backend]),state['sha256'][backend])
        self.assertEqual(len(report['parameter_variants']),2)
        self.assertTrue(all(v['passed'] for v in report['parameter_variants']))
        validation=json.loads((ROOT/report['freecad_validation']).read_text())
        self.assertTrue(validation['reopened'])
        self.assertTrue(all(not sample['overlaps'] for sample in validation['samples']))
        self.assertLess(report['envelopes']['manual_reposition']['arm']['xy_area_mm2'],report['envelopes']['working']['arm']['xy_area_mm2']*0.85)
        self.assertFalse(report['ros_runtime_tested'])

    @unittest.skipUnless((ROOT / "ros2_ws/src/solidcraftbot_ros/urdf/robot_mb01_working.urdf").is_file(), "Requires local mobile-base ROS build")
    def test_ros_static_base_retains_six_arm_axes_and_explicit_si_units(self):
        p=mobile.parameters(mobile.load())
        for name in ['working','manual_reposition']:
            root=ET.parse(ROOT/'ros2_ws/src/solidcraftbot_ros/urdf'/('robot_mb01_'+name+'.urdf')).getroot()
            self.assertEqual(len(root.findall("joint[@type='revolute']")),6)
            mount=root.find("joint[@name='mb01_arm_mount']/origin")
            self.assertAlmostEqual(float(mount.get('xyz').split()[2]),p['mb_mount_z']/1000)
            base=root.find("joint[@name='mb01_manual_location']/origin")
            self.assertAlmostEqual(float(base.get('xyz').split()[2]),p['mb_wheel_lift']/1000 if name=='working' else 0)
            pose=mobile.state(mobile.load(),robot.load(),p,name)
            for joint,angle in zip(robot.load()['joints'],pose['arm_deg']):
                initial=root.find("ros2_control/joint[@name='%s']/state_interface[@name='position']/param[@name='initial_value']"%joint['id'].lower())
                self.assertAlmostEqual(float(initial.text),math.radians(angle))


if __name__=='__main__': unittest.main()
