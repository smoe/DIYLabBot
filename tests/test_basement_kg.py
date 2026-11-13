"""Basement integration: shared cores, real level policy and variant geometry."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import building_stack as stack
import ground_floor_model as registered
import relative_floorplan as floor

class BasementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=stack.load();cls.p=stack.parameters(cls.spec)
        cls.data=stack.interfaces(cls.spec,cls.p)

    def test_distinct_registered_plan_with_single_definition_boundaries(self):
        plan=stack.level_plan(self.spec,'KG');canonical=stack.templates(self.spec)[0]
        self.assertEqual(plan['id'],'Basement_KG')
        self.assertEqual(len(plan['areas']),28)
        labels={a['label'] for a in plan['areas']}
        for label in ('0.007 Flüssigstickstoff','0.008 RLT-Zentrale','0.011 Kühlraum','0.015 Technik / Druckluft'):
            self.assertIn(label,labels)
        for name in ('LiftCore','R3_028'):
            self.assertAlmostEqual(floor.signed_area(floor.outline(plan,name)),floor.signed_area(floor.outline(canonical,name)))
            self.assertTrue(all(floor.point_membership(p,floor.outline(canonical,name)) == 0 for p in floor.outline(plan,name)))
        raw=registered.raw_source(plan)
        self.assertTrue(any(isinstance(v,dict) for v in raw['vertices'].values()))
        self.assertIsNone(plan['calibration'])
        self.assertFalse(any(a['kind']=='void' for a in plan['areas']))

    def test_basement_has_floor_but_no_inherited_atrium_or_external_stair(self):
        d=self.data;levels={v['id']:v for v in d['levels']}
        self.assertEqual(levels['KG']['z_mm'],-4250)
        self.assertEqual(levels['EG']['z_mm'],0)
        self.assertTrue(levels['KG']['floor_bodies'])
        self.assertEqual([v['id'] for v in d['atrium_prisms']],['OG1_AtriumVoid','OG2_AtriumVoid','OG3_AtriumVoid'])
        self.assertEqual(d['circulation']['elevator']['doors_by_level']['KG'],['inward'])
        self.assertEqual(d['circulation']['elevator']['deferred_stops'],[])
        stairs=d['circulation']['stairs'][0]
        self.assertEqual(stairs['connectors'][0]['from_level'],'KG')
        self.assertEqual(stairs['connectors'][0]['to_level'],'EG')
        self.assertEqual(stairs['planned_connectors'],[])
        ext=d['circulation']['external_stairs'][0]
        self.assertEqual(ext['connectors'][0]['from_level'],'EG')
        self.assertNotIn('KG',{c['from_level'] for c in ext['connectors']})
        self.assertFalse(d['metric_scale_known'])

    def test_height_variant_updates_basement_shaft_and_connector_together(self):
        p=stack.parameters(self.spec,{'clear_height_mm':3500,'slab_thickness_mm':200})
        d=stack.interfaces(self.spec,p);e=stack.expanded(self.spec,p)
        self.assertEqual(d['levels'][0]['z_mm'],-3700)
        c=d['circulation']['stairs'][0]['connectors'][0]
        self.assertEqual((c['z0_mm'],c['z1_mm']),(-3700,0))
        post=next(o for o in e['operations'] if o['id']=='LiftPost_SW_Box')
        self.assertEqual(post['shape']['origin'][2],-3700)
        self.assertEqual(post['shape']['origin'][2]+post['shape']['size'][2],d['levels'][-1]['clear_top_mm'])

    def test_shifted_core_is_rejected_even_with_matching_reference_metadata(self):
        plan=stack.level_plan(self.spec,'KG');raw=registered.raw_source(plan)
        changed=copy.deepcopy(plan)
        wall=next(w for w in changed['walls'] if w['id']=='W062')
        changed['vertices'][wall['start']][0] += .01
        with mock.patch.object(stack.ground,'load',return_value=changed), mock.patch.object(stack.ground,'raw_source',return_value=raw):
            with self.assertRaisesRegex(ValueError,'KG core differs'):
                stack.level_plan(self.spec,'KG')

    def test_basement_pin_prevents_silent_source_replacement(self):
        s=copy.deepcopy(self.spec);s['sources']['basement']['source_sha256']='0'*64
        with self.assertRaises(ValueError):stack.level_plan(s,'KG')

if __name__=='__main__':unittest.main()
