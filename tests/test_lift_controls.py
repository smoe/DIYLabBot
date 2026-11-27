"""Shared cabin/landing controls and physical sill continuity."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import lift_fittings as lift


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.source=json.loads((ROOT/'model/building-stack.shared.json').read_text())['circulation']['elevator']['fittings']
        self.rectangle=[10107.810810810812,15102.405405405405,12605.702702702703,17303.]
        self.opening=[15608.10810823892,16529.729729741622]
        self.levels=[{'id':name,'z_mm':(n-1)*4250} for n,name in enumerate(('KG','EG','OG1','OG2','OG3'))]
        sides={'KG':['inward'],'EG':['outward','inward'],'OG1':['outward'],'OG2':['outward'],'OG3':['outward']}
        self.ports=[{'id':'Port_'+l['id']+'_'+side,'level_id':l['id'],'side':side,
                     'active':True,'z_mm':l['z_mm'],'plane_x_mm':12902.702702702703 if side=='inward' else 9810.810810810812,
                     'wall_thickness_mm':180,'height_mm':2150}for l in self.levels for side in sides[l['id']]]
        self.model=lift.compile(self.source,self.rectangle,90,self.opening,self.ports,0,self.levels)
        self.shapes={o['body']:o['shape']for o in self.model['operations']}

    def test_five_cabin_buttons_and_seven_displays_share_floor_codes(self):
        c=self.model['placements']['controls'];attached=set(self.model['attached_body_ids'])
        self.assertEqual([b['label']for b in c['floor_buttons']],['K','E','1','2','3'])
        self.assertEqual(len(c['landing_panels']),6);self.assertEqual(len(c['displays']),7)
        self.assertTrue({'Port_EG_inward','Port_EG_outward'}<={p['port_id']for p in c['landing_panels']})
        for button in c['floor_buttons']:
            self.assertTrue(set(button['body_ids'])<=attached)
        for display in c['displays']:
            self.assertEqual(len(display['cells']),15)
            for cell in display['cells']:
                self.assertEqual(cell['body_id']in attached,display['port_id']is None)
            for level,letter in c['floor_labels'].items():
                actual=[''.join('1'if level in cell['levels']else'0'for cell in display['cells'][i:i+3])for i in range(0,15,3)]
                self.assertEqual(actual,lift.GLYPHS[letter])
        for panel in c['landing_panels']:
            self.assertFalse(set(panel['button_body_ids'])&attached)

    def test_all_sills_have_the_declared_clear_gap_and_match_floor_height(self):
        self.assertEqual({t['port_id']for t in self.model['placements']['thresholds']},
                         {p['id']for p in self.ports})
        for threshold in self.model['placements']['thresholds']:
            port=next(p for p in self.ports if p['id']==threshold['port_id']);shape=self.shapes[threshold['body_id']]
            self.assertEqual(threshold['gap_mm'],8)
            self.assertAlmostEqual(abs(threshold['landing_edge_x_mm']-threshold['cabin_edge_x_mm']),8)
            self.assertEqual(shape['origin'][1],self.opening[0]);self.assertAlmostEqual(shape['size'][1],self.opening[1]-self.opening[0])
            self.assertAlmostEqual(shape['origin'][2]+shape['size'][2],port['z_mm']+3)
            self.assertNotIn(threshold['body_id'],self.model['attached_body_ids'])
        self.assertTrue({'LiftCabinSill_outward','LiftCabinSill_inward'}<=set(self.model['attached_body_ids']))

    def test_cabin_controls_face_the_right_side_of_the_upper_floor_entrance(self):
        panel=self.shapes['LiftControlPanel'];placement=self.model['placements']['panel']
        x0,y0,x1,y1=self.rectangle
        # Upper-floor entry faces +X: its right side is the south (-Y) wall.
        self.assertEqual(placement['entry_side'],'outward')
        self.assertEqual(placement['face_normal'],[0,1,0])
        self.assertAlmostEqual(panel['origin'][1],y0+90)
        self.assertLess(panel['origin'][0]+panel['size'][0],(x0+x1)/2)
        self.assertEqual(panel['size'][1],self.source['panel']['depth_mm'])
        for button in self.model['placements']['controls']['floor_buttons']:
            shape=self.shapes['LiftFloorButton_'+button['level_id']]
            self.assertEqual(shape['axis'],[0,1,0])
            self.assertGreater(shape['origin'][1],panel['origin'][1]+panel['size'][1])
        display=self.shapes['LiftFloorDisplay']
        self.assertGreaterEqual(display['origin'][1],panel['origin'][1]+panel['size'][1])
        left=self.shapes['LiftFloorDisplay_LED_0_0']['origin']
        right=self.shapes['LiftFloorDisplay_LED_0_2']['origin']
        self.assertGreater(left[0],right[0],'Glyph columns read left to right from inside the cabin')

    def test_upper_handrail_stops_before_the_panel_and_lower_rail_continues(self):
        panel=self.shapes['LiftControlPanel'];end=panel['origin'][0]+panel['size'][0]
        upper=self.shapes['LiftHandrail_South_1'];lower=self.shapes['LiftHandrail_South_0']
        self.assertAlmostEqual(upper['origin'][0]-end,self.source['panel']['handrail_clearance_mm'])
        self.assertGreater(upper['origin'][0],lower['origin'][0])
        self.assertAlmostEqual(upper['origin'][0]+upper['height'],lower['origin'][0]+lower['height'])
        for n in range(3):
            bracket=self.shapes['LiftHandrail_South_1_Bracket'+str(n)]
            self.assertGreater(bracket['origin'][0]-bracket['radius'],end)
        self.assertEqual(self.shapes['LiftHandrail_North_1']['height'],lower['height'])

    def test_invalid_gap_and_label_fail_before_geometry(self):
        for gap in (0,21,float('nan'),True):
            s=copy.deepcopy(self.source);s['threshold']['landing_gap_mm']=gap
            with self.assertRaises(ValueError):lift.validate(s)
        s=copy.deepcopy(self.source);s['controls']['floor_labels']['KG']='B'
        with self.assertRaises(ValueError):lift.validate(s)


if __name__=='__main__':unittest.main()
