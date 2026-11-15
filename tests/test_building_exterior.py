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
        cls.s=model.load()
        # Exercise the exterior recipe independently of optional room demolition.
        cls.s['sources'].pop('furnishings',None)
        cls.p=model.parameters(cls.s);cls.d=model.interfaces(cls.s,cls.p);cls.e=model.expanded(cls.s,cls.p)

    def test_lawn_is_a_thin_green_surface_at_eg_grade(self):
        ext=self.d['exterior'];self.assertEqual(ext['grade_z_mm'],0);self.assertEqual(ext['terrain_bottom_mm'],-20)
        self.assertEqual(len(ext['terrain_body_ids']),1);self.assertEqual(len(self.d['levels']),5)
        for name in ext['terrain_body_ids']:
            body=next(b for b in self.e['bodies'] if b['id']==name)
            self.assertEqual(body['appearance']['color'],'#559447')
            shape=next(o['shape'] for o in self.e['operations'] if o['body']==name and o['action']=='create')
            self.assertEqual(shape['size'][2],20)
            self.assertEqual(shape['origin'][2]+shape['size'][2],0)
        self.assertFalse(ext['dimensions_measured']);self.assertFalse(ext['safety_qualified'])

    def test_front_replaces_only_scoped_placeholder_walls_and_is_not_an_opaque_screen(self):
        ext=self.d['exterior'];names={b['id'] for b in self.e['bodies']}
        self.assertNotIn('OG1__Wall_W108',names);self.assertNotIn('EG__Wall_EW074',names)
        self.assertIn('KG__Wall_W049',names)
        glass=[b for b in self.e['bodies'] if b['id'] in ext['glass_body_ids']]
        self.assertGreater(len(glass),24);self.assertTrue(all(b['appearance']['opacity']==.2 for b in glass))
        self.assertTrue(any(o['action']=='cut' and o['id'].endswith('_Entrance') for o in self.e['operations']))
        self.assertTrue(any(o['body']==ext['frame_body_id'] and o['action']=='join' for o in self.e['operations']))
        self.assertGreater(len(ext['frame_body_ids']),10)
        self.assertTrue(all(o['action']=='create' for o in self.e['operations'] if o['body'] in {n for n in ext['frame_body_ids'] if n.startswith('Foyer')}-{ext['frame_body_id']}))

    def test_door_materials_and_native_aperture_witnesses(self):
        ext=self.d['exterior'];doors=[b for b in self.e['bodies'] if b['id'] in ext['door_leaves'].values()]
        self.assertGreater(len(doors),100)
        for body in doors:
            if body['id'].startswith('KG__'):
                self.assertEqual(body['role'],'concept_open_steel_room_door')
            elif body['id']=='OG3__DoorLeaf_D3_002_001':
                self.assertEqual(body['role'],'concept_open_glass_room_door')
                self.assertEqual(body['appearance'],{'color':'#A7CDD8','opacity':.3})
            else:
                self.assertEqual(body['appearance']['color'],self.s['exterior']['door_color'])
        witnesses={p['target_body'] for p in self.d['opening_probes'] if p['id'].startswith('LeafClear_')}
        self.assertEqual(witnesses,set(ext['door_leaves'].values()))
        self.assertFalse(set(ext['omitted_body_ids']) & {p['target_body'] for p in self.d['opening_probes']})

    def test_open_guards_have_posts_hand_rail_and_four_separate_horizontal_bars(self):
        ext=self.d['exterior']
        self.assertEqual({(group['level_id'],group['boundary']) for group in ext['guard_groups']},
                         {(level,wall) for level in ['OG1','OG2','OG3'] for wall in ['W068','W106','W065']})
        for group in ext['guard_groups']:
            operations=[o for o in self.e['operations'] if o['body'] in group['body_ids']]
            self.assertTrue(all(o['action']=='create' for o in operations))
            self.assertEqual(sum('_Bar' in o['body'] for o in operations),4)
            self.assertEqual(sum('_Handrail' in o['body'] for o in operations),1)
            self.assertTrue(all(o['shape']['depth']<=1100 for o in operations))
        self.assertNotIn('OG1__Wall_W106',{b['id'] for b in self.e['bodies']})

    def test_vertical_variant_recomputes_site_front_and_guards(self):
        p=model.parameters(self.s,{'clear_height_mm':3500,'slab_thickness_mm':200});d=model.interfaces(self.s,p)
        self.assertEqual(d['exterior']['terrain_bottom_mm'],-20)
        self.assertEqual(d['exterior']['facade_top_mm'],14800)
        self.assertEqual(d['exterior']['grade_z_mm'],0)

    def test_kitchen_window_addition_is_bound_to_og1_only(self):
        selected=copy.deepcopy(self.s)
        selected['exterior']['side_window_walls_by_level']={'OG1':['W005']}
        added=model.interfaces(selected,self.p)['exterior']
        groups=[group for group in added['side_window_groups'] if group['wall']=='W005']
        self.assertEqual([(group['level_id'],group['target_body']) for group in groups],
                         [('OG1','OG1__Wall_W005')])
        self.assertTrue(any(probe['target_body']=='OG1__Wall_W005' for probe in added['window_probes']))
        baseline=copy.deepcopy(selected)
        baseline['exterior'].pop('side_window_walls_by_level')
        before=model.interfaces(baseline,self.p)['exterior']
        self.assertEqual([group for group in added['side_window_groups'] if group['level_id']!='OG1'],
                         [group for group in before['side_window_groups'] if group['level_id']!='OG1'])

    def test_invalid_level_window_additions_are_rejected(self):
        for additions in ({'KG':['W005']},{'OG1':[]},{'OG1':['W005','W005']},
                          {'OG1':[self.s['exterior']['side_window_walls'][0]]},False):
            selected=copy.deepcopy(self.s['exterior'])
            selected['side_window_walls_by_level']=additions
            with self.subTest(additions=additions),self.assertRaises(ValueError):
                exterior.validate(selected)
        selected=copy.deepcopy(self.s)
        selected['exterior']['side_window_walls_by_level']={'OG1':['W070']}
        with self.assertRaisesRegex(ValueError,'actual outer facade'):
            model.interfaces(selected,self.p)

    def test_entrance_flanks_are_opaque_and_side_bands_have_closed_gaps(self):
        ext=self.d['exterior'];bodies={b['id']:b for b in self.e['bodies']}
        for name in ['OG3__Wall_W102']:
            self.assertEqual(bodies[name]['appearance'],{'color':self.s['exterior']['concrete_color'],'opacity':1})
        self.assertTrue(ext['side_window_groups'])
        self.assertEqual({v['level_id'] for v in ext['side_window_groups']},{'EG','OG1','OG2','OG3'})
        self.assertTrue(all('W114' not in v['wall'] and 'W118' not in v['wall'] for v in ext['side_window_groups']))
        for group in ext['side_window_groups']:
            level=next(v for v in self.d['levels'] if v['id']==group['level_id'])
            self.assertGreater(group['z_bounds_mm'][0],level['z_mm'])
            self.assertLess(group['z_bounds_mm'][1],level['clear_top_mm'])
            self.assertIn(group['target_body'],ext['surface_overrides'])
        self.assertEqual(len(ext['window_probes']),len(ext['side_window_groups']))

    def test_only_entrance_flanks_above_grade_are_painted_red(self):
        bodies={b['id']:b for b in self.e['bodies']}
        for level in ['OG1','OG2','OG3']:
            for wall in ['W114','W118']:
                self.assertEqual(bodies[level+'__Wall_'+wall]['appearance'],{'color':self.s['exterior']['entrance_flank_color'],'opacity':1})
        self.assertEqual(self.s['exterior']['entrance_flank_color'],'#B65E52')
        self.assertTrue(any(v['color']==self.s['exterior']['entrance_flank_color'] for k,v in self.d['exterior']['surface_overrides'].items() if k.startswith('EG__')))
        self.assertFalse(any(v['color']==self.s['exterior']['entrance_flank_color'] for k,v in self.d['exterior']['surface_overrides'].items() if k.startswith('KG__')))
        for group in self.d['exterior']['side_window_groups']:
            self.assertEqual(bodies[group['target_body']]['appearance']['color'],self.s['exterior']['side_cladding_color'])

    def test_access_surfaces_are_thin_and_separate_from_lawn(self):
        ext=self.d['exterior']
        self.assertEqual({v['material'] for v in ext['site_regions']},{'sidewalk','driveway','entrance_apron','left_hardstanding'})
        self.assertEqual(len(ext['site_body_ids']),5)
        for region in ext['site_regions']:
            self.assertEqual(region['origin_mm'][2],-20)
            self.assertEqual(region['size_mm'][2],20)
        sidewalk=next(v for v in ext['site_regions'] if v['material']=='entrance_apron')
        driveway=next(v for v in ext['site_regions'] if v['material']=='driveway')
        self.assertAlmostEqual(sidewalk['origin_mm'][0]+sidewalk['size_mm'][0],driveway['origin_mm'][0])

    def test_paving_reaches_glass_and_left_side_entrance_with_road_beyond(self):
        ext=self.d['exterior'];regions={r['material']:r for r in ext['site_regions']}
        front=regions['entrance_apron'];road=regions['driveway'];side=regions['sidewalk']
        self.assertAlmostEqual(front['origin_mm'][0],ext['facade_plane_x_mm'])
        self.assertEqual(front['origin_mm'][1],road['origin_mm'][1])
        self.assertEqual(front['size_mm'][1],road['size_mm'][1])
        self.assertEqual(road['size_mm'][0],self.s['exterior']['road_width_mm'])
        self.assertEqual(side['entry_opening'],'D0_013_Exterior')
        self.assertTrue(side['points_mm'])
        self.assertEqual(side['facade_walls'][0],'W090')
        self.assertIn('W037',side['facade_walls'])
        self.assertEqual(side['facade_walls'][-1],'W102')

    def test_left_context_is_hardstanding_without_a_lawn_buffer(self):
        regions={r['material']:r for r in self.d['exterior']['site_regions']};court=regions['left_hardstanding']
        self.assertLess(court['origin_mm'][1],min(r['origin_mm'][1] for k,r in regions.items() if k!='left_hardstanding'))
        self.assertFalse(court['boundary_measured'])
        self.assertEqual(next(b for b in self.e['bodies'] if b['id']==court['body'])['appearance']['color'],self.s['exterior']['road_color'])
        self.assertTrue(any(o['body']=='Terrain_Lawn' and o['id']=='Site_LeftHardstanding_LawnCut' for o in self.e['operations']))

    def test_invalid_or_invented_contract_values_are_rejected(self):
        for key,value in [('bay_count',True),('glass_opacity',1),('frame_mm',0),('guard_bar_fractions',[.5,.5]),('door_color','wood'),('left_hardstanding_end_fraction',True)]:
            s=copy.deepcopy(self.s['exterior']);s[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):exterior.validate(s)
        s=copy.deepcopy(self.s);s['exterior']['front_wall']='Invented'
        with self.assertRaises(ValueError):model.validate(s)

if __name__=='__main__':unittest.main()
