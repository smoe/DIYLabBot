"""Selected hardware must remain in generated CAD and RViz link assemblies."""
from pathlib import Path
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import robot_spec as model
from robot_components import library
from check_servo_mountings import assembly_bindings,native_part_metadata
from solidcraft_vendor import semantic_bodies

@unittest.skipUnless((ROOT / "exports/generated/build-report.json").is_file() and (ROOT / "ros2_ws/src/solidcraftbot_ros/config/geometry.json").is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
class RobotPartsIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=model.load();cls.lib=library(cls.spec)
        build=json.loads((ROOT/'exports/generated/build-report.json').read_text())
        cls.native=native_part_metadata(ROOT/build['artifacts']['freecad'])
        cls.measurements=json.loads((ROOT/build['artifacts']['solidcraft_measurements']).read_text())['bodies']
        cls.aliases=build.get('solidcraft_body_aliases',{})
        cls.sc=set(semantic_bodies(cls.measurements,cls.native,cls.aliases))
        cls.ros=json.loads((ROOT/'ros2_ws/src/solidcraftbot_ros/config/geometry.json').read_text())

    def test_actual_robot_uses_selected_joint_parts_and_hardware(self):
        result=assembly_bindings(self.spec,self.lib,self.native,self.sc,self.ros)
        self.assertEqual([j['servo'] for j in result['joints']],['RMD-X4-P36-36-E-L','RMD-X6-P20-60-E','RMD-X4-P36-36-E-L']+['RMD-X2-P28-7-E']*3)
        self.assertEqual(result['counts'],{'servos':6,'motor_plates':12,'own_locating_pins':20,'specified_screws':70})

    def test_missing_rviz_pin_or_plate_cannot_pass(self):
        for body in ['A1_housing_plate','A1_housing_plate_pin_round']:
            ros=copy.deepcopy(self.ros);ros['links']['L0_Base']['mesh_bodies'].remove(body)
            with self.assertRaisesRegex(ValueError,'RViz missing'):assembly_bindings(self.spec,self.lib,self.native,self.sc,ros)

    def test_old_vendor_part_or_missing_cad_body_cannot_pass(self):
        native=copy.deepcopy(self.native);native['A1_housing']['VendorPart']='obsolete_motor_placeholder'
        with self.assertRaisesRegex(ValueError,'vendor part/revision'):assembly_bindings(self.spec,self.lib,native,self.sc,self.ros)
        bodies=self.sc-{'A1_output_plate'}
        with self.assertRaisesRegex(ValueError,'missing from CAD'):assembly_bindings(self.spec,self.lib,self.native,bodies,self.ros)

    def test_missing_split_housing_piece_cannot_pass(self):
        if not self.aliases:self.skipTest('Requires a build with split vendor housings')
        part=self.aliases['A1_housing'][0]
        bodies=[b for b in self.measurements if b['name']!=part]
        with self.assertRaisesRegex(ValueError,'identities/count mismatch'):
            semantic_bodies(bodies,self.native,self.aliases)

if __name__=='__main__':unittest.main()
