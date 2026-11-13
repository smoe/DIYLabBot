"""Photo-informed facade, wood doors, open guards and grade remain one source."""
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import building_stack as model
import building_exterior as exterior

class ExteriorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=model.load();cls.p=model.parameters(cls.s);cls.d=model.interfaces(cls.s,cls.p);cls.e=model.expanded(cls.s,cls.p)

    def test_terrain_uses_eg_grade_and_spans_basement_not_an_extra_storey(self):
        ext=self.d['exterior'];self.assertEqual(ext['grade_z_mm'],0);self.assertEqual(ext['terrain_bottom_mm'],-4500)
        self.assertEqual(len(ext['terrain_body_ids']),4);self.assertEqual(len(self.d['levels']),5)
        for name in ext['terrain_body_ids']:
            shape=next(o['shape'] for o in self.e['operations'] if o['body']==name)
            self.assertEqual(shape['origin'][2]+shape['size'][2],0)
        self.assertFalse(ext['dimensions_measured']);self.assertFalse(ext['safety_qualified'])

    def test_front_replaces_only_scoped_placeholder_walls_and_is_not_an_opaque_screen(self):
        ext=self.d['exterior'];names={b['id'] for b in self.e['bodies']}
        self.assertNotIn('OG1__Wall_W108',names);self.assertNotIn('EG__Wall_EW074',names)
        self.assertIn('KG__Wall_W049',names)
        glass=[b for b in self.e['bodies'] if b['id'] in ext['glass_body_ids']]
        self.assertEqual(len(glass),24);self.assertTrue(all(b['appearance']['opacity']==.2 for b in glass))
        self.assertTrue(any(o['action']=='cut' and o['id'].endswith('_Entrance') for o in self.e['operations']))
        self.assertTrue(any(o['body']==ext['frame_body_id'] and o['action']=='join' for o in self.e['operations']))
        self.assertGreater(len(ext['frame_body_ids']),10)
        self.assertTrue(all(o['action']=='create' for o in self.e['operations'] if o['body'] in set(ext['frame_body_ids'])-{ext['frame_body_id']}))

    def test_door_leaves_share_one_colour_and_have_native_aperture_witnesses(self):
        ext=self.d['exterior'];doors=[b for b in self.e['bodies'] if b['id'] in ext['door_leaves'].values()]
        self.assertGreater(len(doors),100)
        self.assertEqual({b['appearance']['color'] for b in doors},{self.s['exterior']['door_color']})
        witnesses={p['target_body'] for p in self.d['opening_probes'] if p['id'].startswith('LeafClear_')}
        self.assertEqual(witnesses,set(ext['door_leaves'].values()))
        self.assertFalse(set(ext['omitted_body_ids']) & {p['target_body'] for p in self.d['opening_probes']})

    def test_open_guards_have_posts_hand_rail_and_four_separate_horizontal_bars(self):
        ext=self.d['exterior'];self.assertEqual(len(ext['guard_groups']),6)
        for group in ext['guard_groups']:
            operations=[o for o in self.e['operations'] if o['body'] in group['body_ids']]
            self.assertTrue(all(o['action']=='create' for o in operations))
            self.assertEqual(sum('_Bar' in o['body'] for o in operations),4)
            self.assertEqual(sum('_Handrail' in o['body'] for o in operations),1)
            self.assertTrue(all(o['shape']['depth']<=1100 for o in operations))
        self.assertNotIn('OG1__Wall_W106',{b['id'] for b in self.e['bodies']})

    def test_vertical_variant_recomputes_site_front_and_guards(self):
        p=model.parameters(self.s,{'clear_height_mm':3500,'slab_thickness_mm':200});d=model.interfaces(self.s,p)
        self.assertEqual(d['exterior']['terrain_bottom_mm'],-3900)
        self.assertEqual(d['exterior']['facade_top_mm'],14800)
        self.assertEqual(d['exterior']['grade_z_mm'],0)

    def test_invalid_or_invented_contract_values_are_rejected(self):
        for key,value in [('bay_count',True),('glass_opacity',1),('frame_mm',0),('guard_bar_fractions',[.5,.5]),('door_color','wood')]:
            s=copy.deepcopy(self.s['exterior']);s[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):exterior.validate(s)
        s=copy.deepcopy(self.s);s['exterior']['front_wall']='Invented'
        with self.assertRaises(ValueError):model.validate(s)

if __name__=='__main__':unittest.main()
