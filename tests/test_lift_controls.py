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
        self.ports=[{'id':'Port_'+l['id'],'level_id':l['id'],'side':'inward' if i<2 else 'outward',
                     'active':True,'z_mm':l['z_mm'],'plane_x_mm':12902.702702702703 if i<2 else 9810.810810810812,
                     'wall_thickness_mm':180,'height_mm':2150}for i,l in enumerate(self.levels)]
        self.model=lift.compile(self.source,self.rectangle,90,self.opening,self.ports,0,self.levels)
        self.shapes={o['body']:o['shape']for o in self.model['operations']}

    def test_five_buttons_and_six_displays_share_floor_codes(self):
        c=self.model['placements']['controls'];attached=set(self.model['attached_body_ids'])
        self.assertEqual([b['label']for b in c['floor_buttons']],['K','E','1','2','3'])
        self.assertEqual(len(c['landing_panels']),5);self.assertEqual(len(c['displays']),6)
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
        for threshold in self.model['placements']['thresholds']:
            port=next(p for p in self.ports if p['id']==threshold['port_id']);shape=self.shapes[threshold['body_id']]
            self.assertEqual(threshold['gap_mm'],8)
            self.assertAlmostEqual(abs(threshold['landing_edge_x_mm']-threshold['cabin_edge_x_mm']),8)
            self.assertEqual(shape['origin'][1],self.opening[0]);self.assertAlmostEqual(shape['size'][1],self.opening[1]-self.opening[0])
            self.assertAlmostEqual(shape['origin'][2]+shape['size'][2],port['z_mm']+3)
            self.assertNotIn(threshold['body_id'],self.model['attached_body_ids'])
        self.assertTrue({'LiftCabinSill_outward','LiftCabinSill_inward'}<=set(self.model['attached_body_ids']))

    def test_invalid_gap_and_label_fail_before_geometry(self):
        for gap in (0,21,float('nan'),True):
            s=copy.deepcopy(self.source);s['threshold']['landing_gap_mm']=gap
            with self.assertRaises(ValueError):lift.validate(s)
        s=copy.deepcopy(self.source);s['controls']['floor_labels']['KG']='B'
        with self.assertRaises(ValueError):lift.validate(s)


if __name__=='__main__':unittest.main()
