"""Check functional locating geometry and explicit, measured fastener stacks."""
from pathlib import Path
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from x6_mounting_design import analyse
import robot_spec as model

class X6AssemblyDesign(unittest.TestCase):
    def setUp(self):
        self.source=json.loads((ROOT/'model/x6-mounting-interface.json').read_text())

    def test_nominal_stacks_and_worst_case_margins(self):
        r=analyse(self.source)
        for section,overlap,limits,margin,floor in [('housing',4.6,[4.3,4.9],.9,2.3),('output',4.1,[3.9,4.3],.5,1.8)]:
            x=r['fasteners'][section]
            self.assertAlmostEqual(x['nominal_axial_thread_overlap_mm'],overlap)
            for a,b in zip(x['axial_thread_overlap_range_mm'],limits):self.assertAlmostEqual(a,b)
            self.assertAlmostEqual(x['minimum_tip_margin_mm'],margin)
            self.assertAlmostEqual(x['minimum_plate_floor_mm'],floor)
            self.assertIsNone(x['torque_nm'])
            self.assertFalse(x['full_thread_engagement_verified'])
        self.assertAlmostEqual(r['fasteners']['housing']['minimum_measured_face_to_usable_thread_end_mm'],8.3)
        self.assertFalse(self.source['assembly_design']['housing_thread_depth_reference_verified'])
        self.assertFalse(r['manufacturing_released'])

    def test_locating_clearance_and_radial_relief_budget(self):
        x=analyse(self.source)['locating']
        self.assertEqual(x['pin_diameter_limits_mm'],[4.98,5])
        self.assertAlmostEqual(x['diametral_clearance_range_mm'][0],0)
        self.assertAlmostEqual(x['diametral_clearance_range_mm'][1],.032)
        self.assertAlmostEqual(x['minimum_radial_slot_allowance_mm'],.1)
        self.assertAlmostEqual(x['assumed_radial_error_budget_mm'],.0719)
        self.assertLess(x['assembly_angular_free_play_half_range_deg'],.026)

    def test_short_long_and_unmeasured_screws_are_rejected(self):
        for length in [4,8]:
            s=copy.deepcopy(self.source);s['output']['fastener_design']['length_mm']=length
            with self.assertRaisesRegex(ValueError,'too short or bottoming'):analyse(s)
        s=copy.deepcopy(self.source);s['output']['fastener_design']['accepted_length_tolerance_mm']=.3
        with self.assertRaisesRegex(ValueError,'bottoming'):analyse(s)

    def test_added_washer_or_thickness_requires_reselection(self):
        s=copy.deepcopy(self.source);s['output']['fastener_design']['washer_stack_mm']=.8
        with self.assertRaises(ValueError):analyse(s)
        with self.assertRaisesRegex(ValueError,'thickness changed'):analyse(self.source,7)
        spec=model.load();spec['parameters']['x6_plate_t']['expression']='7'
        with self.assertRaisesRegex(ValueError,'thickness changed'):model.expanded(spec)

    def test_insufficient_slot_relief_is_rejected(self):
        s=copy.deepcopy(self.source);s['housing']['locating_pins']['plate_fit']['slot_length_limits_mm']=[5.1,5.15]
        with self.assertRaisesRegex(ValueError,'pitch/thermal'):analyse(s)

    def test_slot_is_a_cut_in_both_adapter_inputs(self):
        commands=model.solidcraft_commands(model.load())
        cut=next(c for c in commands if c['params'].get('name')=='A2_housing_plate_locating_1_middle' and c['command']=='solid.extrude')
        self.assertEqual(cut['params']['operation'],'cut')
        self.assertEqual(cut['params']['targets'],['A2_housing_plate'])
        self.assertEqual(cut['params']['distance'],'x6_plate_t')

if __name__=='__main__':unittest.main()
