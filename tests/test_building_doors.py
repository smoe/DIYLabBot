"""Shared door types, owner exceptions, basement material and window geometry."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import building_doors as doors
import building_stack as building
import relative_floorplan as floor


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
        self.assertEqual(set(self.catalog['materials']),{'wood','steel','glass','blue_black_steel'})
        self.assertEqual(self.catalog['materials']['wood']['thickness_source'],'exterior.door_leaf_mm')
        self.assertTrue(all(v['mass_kg'] is None for v in self.bindings.values()))

    def test_doctoral_writing_rooms_keep_windows_except_the_explicit_glass_connection(self):
        for level in ['OG1','OG2','OG3']:
            self.assertTrue(all(v['type']=='round_window' for v in self.bindings_for(level,'R3_002') if v['material']!='glass'))
        glass=self.bindings['OG3__D3_002_001']
        self.assertEqual((glass['type'],glass['material']),('plain','glass'))
        self.assertTrue(glass['full_leaf_glazing'])

    def test_kitchen_and_owner_office_remain_plain(self):
        for level,area in [('OG1','R3_008A'),('OG3','R3_008A')]:
            self.assertTrue(all(v['type']=='plain' for v in self.bindings_for(level,area)))

    def test_larger_upper_and_lower_band_rooms_use_round_windows(self):
        for level in ['OG1','OG2','OG3']:
            for area in ['R3_001','R3_003','R3_015','R3_016']:
                self.assertTrue(all(v['type']=='round_window' for v in self.bindings_for(level,area) if v['material']!='glass'))
        # A small side room is not silently classified as a laboratory.
        self.assertTrue(all(v['type']=='plain' for v in self.bindings_for('OG3','R3_007')))

    def test_all_basement_leaves_use_the_heavy_steel_profile(self):
        basement=[v for v in self.bindings.values() if v['level_id']=='KG']
        self.assertTrue(basement)
        self.assertTrue(all(v['material']=='steel' and v['leaf_thickness_mm']==self.catalog['materials']['steel']['thickness_mm'] for v in basement))
        self.assertTrue(all(v['mass_kg'] is None for v in basement))

    def test_internal_stairwell_has_open_passages_on_all_levels(self):
        expected={'KG':'DK013','EG':'D0_020','OG1':'D3_028','OG2':'D3_028','OG3':'D3_028'}
        exterior=self.data['exterior']
        passages=exterior['open_passages']
        self.assertEqual(len(passages),len(expected))
        self.assertEqual({p['level_id']:p['opening_id'] for p in passages},expected)
        probes={probe['id']:probe for probe in self.data['opening_probes']}
        for passage in passages:
            key=passage['level_id']+'__'+passage['opening_id']
            self.assertEqual(probes[key]['target_body'],passage['wall_body_id'])
            self.assertEqual(passage['height_mm'],self.p['door_height_mm'])
            self.assertGreater(passage['width_mm'],0)
            self.assertNotIn(key,exterior['door_leaves'])
            self.assertNotIn(key,exterior['door_bindings'])
            leaf=passage['level_id']+'__DoorLeaf_'+passage['opening_id']
            self.assertFalse(any(body==leaf or body.startswith(leaf+'_') for body in exterior['body_ids']))
        for level in ('OG1','OG2','OG3'):
            self.assertIn(level+'__D3_017',exterior['door_leaves'])

    def test_open_passage_rejects_conflicting_or_missing_opening(self):
        policy=copy.deepcopy(self.policy)
        override=policy['opening_overrides'][0]
        policy['open_passages'].append({'opening_id':override['opening_id'],'levels':[override['level_id']]})
        with self.assertRaisesRegex(ValueError,'conflicts'):
            doors.validate(policy,self.catalog)
        plan={'openings':[],'walls':[]}
        with self.assertRaisesRegex(ValueError,'requires a door-sized aperture'):
            doors.bind_open_passages({'open_passages':[{'opening_id':'Missing','levels':['EG']}]},{'EG':plan})

    def test_demolished_kitchen_partition_does_not_leave_a_floating_door(self):
        self.assertNotIn('OG1__D3_008AB',self.bindings)
        self.assertNotIn('OG1__D3_008AB',self.data['exterior']['door_leaves'])
        self.assertIn('OG2__D3_008AB',self.bindings)
        self.assertIn('OG3__D3_008AB',self.bindings)
        self.assertNotIn('OG3__D3_009',self.bindings)
        self.assertIn('OG2__D3_009',self.bindings)

    def test_explicit_exclusions_win_at_shared_doorways(self):
        policy=copy.deepcopy(self.policy);policy['opening_overrides']=[];policy['include_areas']={'OG3':['Lab']};policy['exclude_areas']={'OG3':['Office']};policy['default_type']='round_window'
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
        self.assertEqual(len(result['bodies']),6)
        opening=next(o for o in result['operations'] if o['id'].endswith('_ViewingOpening'))
        self.assertEqual(opening['action'],'cut');self.assertEqual(opening['body'],'WindowDoor')
        self.assertEqual(opening['shape']['axis'],u+[0])
        self.assertGreater(opening['shape']['height'],selection['leaf_thickness_mm'])
        self.assertEqual(selection['window']['diameter_mm'],self.catalog['window']['diameter_mm'])
        for i in (0,1):self.assertAlmostEqual(selection['window']['center_mm'][i],hinge[i]+normal[i]*450)
        self.assertEqual(selection['window']['center_mm'][2],4250+self.catalog['window']['center_height_mm'])

    def test_plain_door_has_no_window_bodies_or_cut(self):
        result=doors.geometry(self.catalog,{'type':'plain','material':'steel'},'SteelDoor',[0,0],[1,0],[0,1],900,2150,0,self.spec['exterior'])
        self.assertEqual([b['role'] for b in result['bodies']],
                         ['concept_open_steel_room_door', 'concept_room_door_handle', 'concept_room_door_handle'])
        self.assertTrue(all(op['action']=='create' for op in result['operations']))

    def test_handles_are_on_the_latch_edge_of_both_faces_in_mirrored_frames(self):
        u=[math.cos(.37),math.sin(.37)]
        hinge=[1410,733]
        width,height,base=900,2150,4250
        handle=self.catalog['handle']
        for sign in (-1,1):
            normal=[-sign*u[1],sign*u[0]]
            for material in ('wood','steel','glass'):
                with self.subTest(sign=sign,material=material):
                    selection={'type':'plain','material':material}
                    result=doors.geometry(self.catalog,selection,'Door',hinge,u,normal,width,height,base,self.spec['exterior'])
                    shapes={op['body']:op['shape'] for op in result['operations']}
                    self.assertEqual(selection['detail_body_ids'],['Door_HandleFront','Door_HandleBack'])
                    thickness=selection['leaf_thickness_mm']
                    projection=handle['projection_mm']
                    for suffix,expected in [('Front',(0,projection)),('Back',(-thickness-projection,-thickness))]:
                        shape=shapes['Door_Handle'+suffix]
                        relative=[[point[i]-hinge[i] for i in (0,1)] for point in shape['points']]
                        along=[sum(x*y for x,y in zip(point,u)) for point in relative]
                        across=[sum(x*y for x,y in zip(point,normal)) for point in relative]
                        self.assertAlmostEqual(min(along),expected[0])
                        self.assertAlmostEqual(max(along),expected[1])
                        mount=width-handle['latch_inset_mm']
                        self.assertAlmostEqual(max(across),mount+handle['section_mm']/2)
                        self.assertAlmostEqual(min(across),mount-handle['lever_length_mm'])
                        self.assertAlmostEqual(shape['offset']+shape['depth']/2,base+handle['center_height_mm'])

    def test_invalid_dimensions_and_unsupported_variants_fail_closed(self):
        for key,value in [('diameter_mm',-1),('glass_opacity',True),('center_height_mm',float('nan'))]:
            catalog=copy.deepcopy(self.catalog);catalog['window'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):doors.validate(self.policy,catalog)
        with self.assertRaises(ValueError):doors.geometry(self.catalog,{'type':'round_window','material':'wood'},'TooNarrow',[0,0],[1,0],[0,1],400,2150,0,self.spec['exterior'])
        with self.assertRaises(ValueError):doors.geometry(self.catalog,{'type':'unimplemented','material':'wood'},'Unknown',[0,0],[1,0],[0,1],900,2150,0,self.spec['exterior'])

    def test_stale_catalog_binding_is_rejected(self):
        ref=copy.deepcopy(self.spec['exterior']['doors']);ref['source_sha256']='0'*64
        with self.assertRaises(ValueError):doors.load(ref)


    def test_logistics_room_and_right_handed_steel_doors(self):
        plan=building.level_plan(self.spec,'EG')
        self.assertEqual(next(a['label'] for a in plan['areas'] if a['id']=='R0_013'),'13 Logistik (Post / Abfall)')
        bodies={b['id']:b for b in building.expanded(self.spec,self.p)['bodies']}
        for opening,region in [('D0_013_Exterior','exterior'),('D0_013','R0_013')]:
            selected=self.bindings['EG__'+opening];placement=selected['placement']
            self.assertEqual((selected['material'],selected['type']),('blue_black_steel','plain'))
            self.assertEqual(placement['approach_from'],region)
            self.assertEqual(placement['opens_into'],region)
            self.assertEqual(placement['hinge_side'],'right')
            self.assertAlmostEqual(sum(a*b for a,b in zip(placement['opening_axis'],placement['approach_normal'])),1)
            door=next(o for o in plan['openings'] if o['id']==opening);wall=next(w for w in plan['walls'] if w['id']==door['wall'])
            a,b=[plan['vertices'][wall[k]] for k in ('start','end')]
            endpoints=[[(a[i]+f*(b[i]-a[i]))*self.p['display_scale'] for i in (0,1)] for f in door['interval']]
            center=[sum(a[i]+f*(b[i]-a[i]) for f in door['interval'])/2 for i in (0,1)]
            sample=[center[i]+placement['opening_axis'][i]*1e-4 for i in (0,1)]
            membership=floor.point_membership(sample,floor.outline(plan,'R0_013'))
            self.assertEqual(membership,-1 if region=='exterior' else 1)
            right=placement['right_vector'];projection=lambda q:sum(x*y for x,y in zip(q,right))
            self.assertAlmostEqual(projection(placement['hinge_mm']),max(map(projection,endpoints)))
            self.assertEqual(bodies[selected['leaf_body_id']]['appearance']['color'],'#172530')
            self.assertEqual(selected['leaf_thickness_mm'],self.catalog['materials']['steel']['thickness_mm'])

    def test_handing_is_independent_of_wall_vertex_order(self):
        plan=building.level_plan(self.spec,'EG');door=next(o for o in plan['openings'] if o['id']=='D0_013_Exterior')
        pose={'approach_from':'exterior','hinge_side':'right','opens_into':'exterior'};expected=doors.handed_frame(plan,door,pose,self.p['display_scale'])
        reverse=copy.deepcopy(plan);other=next(o for o in reverse['openings'] if o['id']==door['id']);wall=next(w for w in reverse['walls'] if w['id']==door['wall']);wall['start'],wall['end']=wall['end'],wall['start'];other['interval']=[1-other['interval'][1],1-other['interval'][0]]
        for area in reverse['areas']:
            for edge in area['boundary']:
                if edge['wall']==door['wall']:edge['direction']*=-1
        actual=doors.handed_frame(reverse,other,pose,self.p['display_scale'])
        for key in ('hinge_mm','opening_axis'):
            for a,b in zip(actual[key],expected[key]):self.assertAlmostEqual(a,b)
        with self.assertRaises(ValueError):doors.handed_frame(plan,door,{**pose,'opens_into':'R0_001'},1)

class GlassOverrideTests(unittest.TestCase):
    """Component checks do not depend on an already regenerated building cache."""
    @classmethod
    def setUpClass(cls):
        source=ROOT/'model/building-doors.shared.json'
        cls.policy,cls.catalog=doors.load({'source':str(source.relative_to(ROOT)),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
        cls.policy=copy.deepcopy(cls.policy);cls.policy['opening_overrides']=[o for o in cls.policy['opening_overrides'] if o['level_id']=='OG3']
        cls.plan=floor.load(ROOT/'model/floor-f03.shared.json')
        cls.door=next(item for item in cls.plan['openings'] if item['id']=='D3_002_001')
        cls.legacy={'door_leaf_mm':40,'door_color':'#C99448'}

    def test_glass_connection_is_explicitly_bound_only_on_og3(self):
        doors.validate_overrides(self.policy,{'OG3':self.plan})
        chosen=doors.select(self.policy,self.plan,self.plan,'OG3',self.door)
        self.assertEqual((chosen['type'],chosen['material'],chosen['reason']),
                         ('plain','glass','owner_opening_override'))
        self.assertEqual(chosen['area_ids'],['R3_001','R3_002'])
        self.assertIn('laboratory 3.001',chosen['override_basis'])
        for level in ('OG1','OG2'):
            chosen=doors.select(self.policy,self.plan,self.plan,level,self.door)
            self.assertEqual((chosen['type'],chosen['material']),('round_window','wood'))

    def test_full_glass_leaf_has_transparent_material_and_no_round_cut(self):
        chosen=doors.select(self.policy,self.plan,self.plan,'OG3',self.door)
        result=doors.geometry(self.catalog,chosen,'GlassDoor',[100,200],[1,0],[0,1],1010,2150,12750,self.legacy)
        self.assertEqual(len(result['bodies']),3)
        self.assertEqual(len(result['operations']),3)
        body=result['bodies'][0]
        self.assertEqual(body['role'],'concept_open_glass_room_door')
        self.assertEqual(body['appearance'],{'color':self.catalog['materials']['glass']['color'],
                                             'opacity':self.catalog['materials']['glass']['opacity']})
        self.assertEqual(chosen['leaf_thickness_mm'],12)
        self.assertTrue(chosen['full_leaf_glazing'])
        self.assertFalse(chosen['dimensions_measured'])
        self.assertEqual(chosen['detail_body_ids'],['GlassDoor_HandleFront','GlassDoor_HandleBack'])
        self.assertTrue(all(operation['action']=='create' for operation in result['operations']))

    def test_legacy_profiles_and_untargeted_levels_generate_identical_geometry(self):
        legacy_policy=copy.deepcopy(self.policy);legacy_policy.pop('opening_overrides')
        legacy_catalog=copy.deepcopy(self.catalog);legacy_catalog['materials'].pop('glass')
        doors.validate(legacy_policy,legacy_catalog)
        for level in ('KG','OG1','OG2'):
            old=doors.select(legacy_policy,self.plan,self.plan,level,self.door)
            new=doors.select(self.policy,self.plan,self.plan,level,self.door)
            self.assertEqual(old,new)
            a=doors.geometry(legacy_catalog,old,'Door',[100,200],[1,0],[0,1],1010,2150,4250,self.legacy)
            b=doors.geometry(self.catalog,new,'Door',[100,200],[1,0],[0,1],1010,2150,4250,self.legacy)
            self.assertEqual(a,b)

    def test_other_og3_openings_keep_their_existing_selection(self):
        legacy=copy.deepcopy(self.policy)
        # Remove only the glass connection under test. Kitchen 3.008 already
        # has separate owner-confirmed poses that must remain in the baseline.
        legacy['opening_overrides']=[o for o in legacy['opening_overrides'] if o['opening_id']!=self.door['id']]
        for door in self.plan['openings']:
            if door['kind']!='door' or door['id']==self.door['id']:continue
            with self.subTest(opening=door['id']):
                self.assertEqual(doors.select(legacy,self.plan,self.plan,'OG3',door),
                                 doors.select(self.policy,self.plan,self.plan,'OG3',door))

    def test_unknown_override_ids_and_non_door_openings_fail_closed(self):
        not_a_door=next(item['id'] for item in self.plan['openings'] if item['kind']!='door')
        for identity in ('DoesNotExist',not_a_door):
            policy=copy.deepcopy(self.policy);policy['opening_overrides'][0]['opening_id']=identity
            with self.subTest(opening=identity):
                with self.assertRaisesRegex(ValueError,'Unknown or non-door override opening'):
                    doors.validate_overrides(policy,{'OG3':self.plan})
                with self.assertRaisesRegex(ValueError,'Unknown or non-door override opening'):
                    doors.select(policy,self.plan,self.plan,'OG3',self.door)

    def test_invalid_override_levels_types_materials_and_duplicates_fail_closed(self):
        for key,value in [('level_id','ROOF'),('type','unimplemented'),('material','paper'),('basis','')]:
            policy=copy.deepcopy(self.policy);policy['opening_overrides'][0][key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):doors.validate(policy,self.catalog)
        policy=copy.deepcopy(self.policy);policy['opening_overrides'].append(copy.deepcopy(policy['opening_overrides'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate per-opening'):
            doors.validate(policy,self.catalog)
        with self.assertRaisesRegex(ValueError,'Override level has no actual plan'):
            doors.validate_overrides(self.policy,{'OG2':self.plan})

    def test_glass_profile_dimensions_and_opacity_are_not_guessed(self):
        for key,value in [('thickness_mm',0),('thickness_mm',float('nan')),('opacity',True),('opacity',1),('mass_kg',10),('color',None)]:
            catalog=copy.deepcopy(self.catalog);catalog['materials']['glass'][key]=value
            with self.subTest(field=key,value=value),self.assertRaises(ValueError):doors.validate(self.policy,catalog)
        with self.assertRaisesRegex(ValueError,'full-glass leaf uses the plain'):
            doors.geometry(self.catalog,{'type':'round_window','material':'glass'},'BadGlass',
                           [0,0],[1,0],[0,1],1010,2150,0,self.legacy)

    def test_current_policy_and_catalog_match_their_schemas(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        for source,schema in [('model/building-doors.shared.json','model/building-doors.schema.json'),
                              ('model/doors/room-doors.catalog.json','model/room-door-catalog.schema.json')]:
            Draft202012Validator(json.loads((ROOT/schema).read_text())).validate(json.loads((ROOT/source).read_text()))


if __name__=='__main__':unittest.main()
