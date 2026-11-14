"""Shared door types, owner exceptions, basement material and window geometry."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import building_doors as doors
import building_stack as building


class DoorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=building.load();cls.p=building.parameters(cls.spec)
        cls.policy,cls.catalog=doors.load(cls.spec['exterior']['doors'])
        cls.data=building.interfaces(cls.spec,cls.p)
        cls.bindings=cls.data['exterior']['door_bindings']

    def bindings_for(self,level,area):
        found=[v for v in self.bindings.values() if v['level_id']==level and area in v['area_ids']]
        self.assertTrue(found,(level,area));return found

    def test_two_glazing_types_and_independent_material_profiles(self):
        self.assertEqual(set(self.catalog['types']),{'plain','round_window'})
        self.assertEqual(set(self.catalog['materials']),{'wood','steel'})
        self.assertEqual(self.catalog['materials']['wood']['thickness_source'],'exterior.door_leaf_mm')
        self.assertTrue(all(v['mass_kg'] is None for v in self.bindings.values()))

    def test_doctoral_writing_rooms_have_viewing_windows_on_every_storey(self):
        for level in ['OG1','OG2','OG3']:
            self.assertTrue(all(v['type']=='round_window' for v in self.bindings_for(level,'R3_002')))

    def test_kitchen_and_owner_office_remain_plain(self):
        for level,area in [('OG1','R3_008A'),('OG1','R3_008B'),('OG3','R3_009')]:
            self.assertTrue(all(v['type']=='plain' for v in self.bindings_for(level,area)))

    def test_larger_upper_and_lower_band_rooms_use_round_windows(self):
        for level in ['OG1','OG2','OG3']:
            for area in ['R3_001','R3_003','R3_015','R3_016']:
                self.assertTrue(all(v['type']=='round_window' for v in self.bindings_for(level,area)))
        # A small side room is not silently classified as a laboratory.
        self.assertTrue(all(v['type']=='plain' for v in self.bindings_for('OG3','R3_007')))

    def test_all_basement_leaves_use_the_heavy_steel_profile(self):
        basement=[v for v in self.bindings.values() if v['level_id']=='KG']
        self.assertTrue(basement)
        self.assertTrue(all(v['material']=='steel' and v['leaf_thickness_mm']==self.catalog['materials']['steel']['thickness_mm'] for v in basement))
        self.assertTrue(all(v['mass_kg'] is None for v in basement))

    def test_demolished_kitchen_partition_does_not_leave_a_floating_door(self):
        self.assertNotIn('OG1__D3_008AB',self.bindings)
        self.assertNotIn('OG1__D3_008AB',self.data['exterior']['door_leaves'])
        self.assertIn('OG2__D3_008AB',self.bindings)
        self.assertIn('OG3__D3_008AB',self.bindings)

    def test_explicit_exclusions_win_at_shared_doorways(self):
        policy=copy.deepcopy(self.policy);policy['include_areas']={'OG3':['Lab']};policy['exclude_areas']={'OG3':['Office']};policy['default_type']='round_window'
        plan={'areas':[{'id':id,'label':id,'boundary':[{'wall':'Shared'}]} for id in ['Lab','Office']]}
        selection=doors.select(policy,plan,None,'OG3',{'wall':'Shared'})
        self.assertEqual(selection['type'],'plain');self.assertEqual(selection['reason'],'explicit_room_or_label_exclusion')
        policy['exclude_areas']={};plan['areas'][1]['label']='Sekretariat'
        self.assertEqual(doors.select(policy,plan,None,'OG3',{'wall':'Shared'})['type'],'plain')

    def test_round_window_is_cut_through_the_leaf_and_has_separate_pane_and_rims(self):
        angle=.37;u=[math.cos(angle),math.sin(angle)];normal=[-u[1],u[0]];hinge=[100,200];selection={'type':'round_window','material':'wood'}
        original=copy.deepcopy(self.catalog)
        result=doors.geometry(self.catalog,selection,'WindowDoor',hinge,u,normal,900,2150,4250,self.spec['exterior'])
        self.assertEqual(self.catalog,original)
        self.assertEqual(len(result['bodies']),4)
        opening=next(o for o in result['operations'] if o['id'].endswith('_ViewingOpening'))
        self.assertEqual(opening['action'],'cut');self.assertEqual(opening['body'],'WindowDoor')
        self.assertEqual(opening['shape']['axis'],u+[0])
        self.assertGreater(opening['shape']['height'],selection['leaf_thickness_mm'])
        self.assertEqual(selection['window']['diameter_mm'],self.catalog['window']['diameter_mm'])
        for i in (0,1):self.assertAlmostEqual(selection['window']['center_mm'][i],hinge[i]+normal[i]*450)
        self.assertEqual(selection['window']['center_mm'][2],4250+self.catalog['window']['center_height_mm'])

    def test_plain_door_has_no_window_bodies_or_cut(self):
        result=doors.geometry(self.catalog,{'type':'plain','material':'steel'},'SteelDoor',[0,0],[1,0],[0,1],900,2150,0,self.spec['exterior'])
        self.assertEqual(len(result['bodies']),1);self.assertEqual(len(result['operations']),1)
        self.assertEqual(result['bodies'][0]['role'],'concept_open_steel_room_door')

    def test_invalid_dimensions_and_unsupported_variants_fail_closed(self):
        for key,value in [('diameter_mm',-1),('glass_opacity',True),('center_height_mm',float('nan'))]:
            catalog=copy.deepcopy(self.catalog);catalog['window'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):doors.validate(self.policy,catalog)
        with self.assertRaises(ValueError):doors.geometry(self.catalog,{'type':'round_window','material':'wood'},'TooNarrow',[0,0],[1,0],[0,1],400,2150,0,self.spec['exterior'])
        with self.assertRaises(ValueError):doors.geometry(self.catalog,{'type':'unimplemented','material':'wood'},'Unknown',[0,0],[1,0],[0,1],900,2150,0,self.spec['exterior'])

    def test_stale_catalog_binding_is_rejected(self):
        ref=copy.deepcopy(self.spec['exterior']['doors']);ref['source_sha256']='0'*64
        with self.assertRaises(ValueError):doors.load(ref)


if __name__=='__main__':unittest.main()
