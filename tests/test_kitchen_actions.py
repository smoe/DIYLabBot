"""Kitchen panels own their hardware; pull-out contents follow their drawers."""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import building_walkthrough as walkthrough
import kitchenette_model as recipe
import building_stack as stack
import json


class KitchenActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program=walkthrough.compile()
        cls.objects={v['id']:v for v in cls.program['objects']}
        cls.source=json.loads((ROOT/'model/furniture/kitchenette.catalog.json').read_text())

    def test_every_drawer_and_compartment_is_independently_operable(self):
        expected={'Drawer'+str(n) for n in range(1,6)}|{'SinkDoor','UpperDoor1','UpperDoor2','UpperFlap'}
        objects=[o for o in self.objects.values() if o['id'].startswith('Kitchen3008.Cabinet.')]
        self.assertEqual({o['joint']['id'] for o in objects},expected)
        owners=set()
        for obj in objects:
            self.assertFalse(owners & set(obj['moving_body_ids']))
            owners.update(obj['moving_body_ids'])
            self.assertEqual(obj['reference_state'],'closed')
            self.assertFalse(any(obj['qualification'].values()))
        for n in range(1,6):
            obj=self.objects['Kitchen3008.Cabinet.Drawer'+str(n)]
            self.assertEqual(obj['joint']['type'],'prismatic')
            self.assertEqual(obj['joint']['axis'],[0,1,0])
            self.assertEqual(len(obj['moving_body_ids']),5)
            self.assertIn('Kitchen3008_Cabinet_DrawerBox'+str(n),obj['moving_body_ids'])
            self.assertGreater(obj['states']['open'],300)
            self.assertLess(obj['states']['open'],500)
            self.assertGreater(obj['viewpoint']['target_mm'][1],obj['joint']['origin_mm'][1]-20,
                               'Crosshair must aim at the front, not the rear box centre')

    def test_closed_drawer_boxes_fit_the_carcass_including_bottom_and_top(self):
        parts={p['id']:p for p in recipe.parts(self.source)}
        cavity=parts['DrawersHollow']['shape']
        for n in range(1,6):
            box=parts['DrawerBox'+str(n)]['shape']
            for axis in range(3):
                self.assertGreater(box['origin'][axis],cavity['origin'][axis])
                self.assertLess(box['origin'][axis]+box['size'][axis],
                                cavity['origin'][axis]+cavity['size'][axis])

    def test_drawer_stroke_tracks_recipe_depth(self):
        original=recipe.articulations(self.source)
        self.source['parameters']['depth']['value']=650
        try:changed=recipe.articulations(self.source)
        finally:self.source['parameters']['depth']['value']=620
        self.assertGreater(changed[0]['limits_mm'][1],original[0]['limits_mm'][1])
        self.assertEqual([j['moving_body_ids'] for j in changed],[j['moving_body_ids'] for j in original])

    def test_flap_and_double_doors_open_outward(self):
        self.assertEqual(self.objects['Kitchen3008.Cabinet.UpperFlap']['joint']['axis'],[1,0,0])
        self.assertEqual(self.objects['Kitchen3008.Cabinet.UpperDoor1']['joint']['axis'],[0,0,1])
        self.assertEqual(self.objects['Kitchen3008.Cabinet.UpperDoor2']['joint']['axis'],[0,0,-1])
        for n in (1,2):self.assertEqual(self.objects['Kitchen3008.Cabinet.UpperDoor'+str(n)]['states']['open'],85)

    def test_rear_room_reaches_a_real_facade_window_on_og3_only(self):
        building=stack.load();parameters=stack.parameters(building)
        interface=stack.interfaces(building,parameters)
        plan=stack.level_plan(building,'OG3')
        self.assertEqual(next(w for w in plan['walls'] if w['id']=='W017')['kind'],'open_boundary')
        self.assertNotIn('D3_009',{o['id'] for o in plan['openings']})
        self.assertIn('D3_009',{o['id'] for o in stack.level_plan(building,'OG2')['openings']})
        windows=interface['exterior']['side_window_groups']
        self.assertTrue(any(w['level_id']=='OG3' and w['wall']=='W005' for w in windows))
        self.assertTrue(any(p['target_body']=='OG3__Wall_W005' for p in interface['opening_probes']))
        rear=next(r for r in interface['furnishings']['rooms'] if r['id']=='Office3009')
        self.assertEqual(rear['room'],'3.008')

    def test_only_kettle_lids_move_in_both_kitchens(self):
        for room in ('Kitchen1008','Kitchen3008'):
            obj=self.objects[room+'.Kettle.Lid']
            self.assertEqual(obj['moving_body_ids'],[room+'_Kettle_Lid'])
            self.assertAlmostEqual(sum(v*v for v in obj['joint']['axis']),1)
            self.assertEqual(obj['joint']['axis'][2],0)
            self.assertEqual(obj['states'],{'closed':0,'open':90})
            r=[v-h for v,h in zip(obj['viewpoint']['target_mm'],obj['joint']['origin_mm'])]
            axis=obj['joint']['axis']
            raised_z=obj['joint']['origin_mm'][2]+axis[0]*r[1]-axis[1]*r[0]
            self.assertGreater(raised_z,obj['viewpoint']['target_mm'][2]+50,'The lid opens upward')


if __name__=='__main__':unittest.main()
