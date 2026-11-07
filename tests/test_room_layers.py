"""Independent room geometry, reusable furniture and preservation of L01 placement."""
from pathlib import Path
import copy
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import lab_room_model as room
import room_geometry_model as geometry
import furniture_model as furniture
import lab_layout_model as layout
import lab_transfer_model as transfer

BASELINE=room.ROOT/'tests/fixtures/l01-before-layer-split.json'


class RoomLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=json.loads(BASELINE.read_text());cls.spec=room.load()

    def assertNestedClose(self,actual,expected):
        if isinstance(expected,dict):
            self.assertEqual(set(actual),set(expected))
            for k in expected:self.assertNestedClose(actual[k],expected[k])
        elif isinstance(expected,list):
            self.assertEqual(len(actual),len(expected))
            for a,b in zip(actual,expected):self.assertNestedClose(a,b)
        elif isinstance(expected,(float,int)):
            self.assertAlmostEqual(actual,expected,delta=1e-8)
        else:self.assertEqual(actual,expected)

    def test_every_primitive_boolean_sequence_style_and_frame_matches_pre_split_variants(self):
        for case in self.before['cases']:
            with self.subTest(case=case['id']):
                p=room.parameters(self.spec,case['overrides']);actual=room.expanded(self.spec,p)
                for key in ['bodies','operations','frames','components']:
                    by_id={x['id']:copy.deepcopy(x) for x in actual[key]}
                    for obj in by_id.values():
                        if key=='operations':obj['shape']=room.numeric_shape(obj['shape'],p)
                        if key=='frames':obj['origin']=[room.evaluate(v,p) for v in obj['origin']]
                    self.assertNestedClose(by_id,{x['id']:x for x in case['expanded'][key]})
                # CSG order is part of geometry, even when independent bodies are reordered.
                for body in actual['bodies']:
                    self.assertEqual([o['id'] for o in actual['operations'] if o['body']==body['id']],
                                     [o['id'] for o in case['expanded']['operations'] if o['body']==body['id']])
                self.assertNestedClose(room.circulation(p),case['circulation'])

    def test_equipment_poses_and_transfer_targets_are_preserved(self):
        spec=layout.load(validate_builds=False);p=layout.parameters(spec)
        self.assertNestedClose({i['id']:layout.matrix(i,p) for i in spec['instances']},self.before['equipment_matrices'])
        targets=transfer.data(transfer.load(),spec)['targets']
        self.assertNestedClose(json.loads(json.dumps(targets)),self.before['transfer_targets'])

    def test_geometry_can_be_loaded_without_furniture_parameters_or_bodies(self):
        spec=geometry.load();p=geometry.parameters(spec);expanded=geometry.expanded(spec,p)
        self.assertNotIn('bench_height',p);self.assertNotIn('island_length',p)
        self.assertEqual({c['id'] for c in expanded['components']},{'RoomShell'})
        self.assertEqual(len(expanded['bodies']),9)
        self.assertNotIn('work_surface',{b['role'] for b in expanded['bodies']})
        self.assertEqual(set(geometry.interfaces(spec)),{'floor_outline'})

    def test_parameter_ownership_is_disjoint_and_catalog_has_no_room_instances(self):
        self.assertFalse(set(self.spec['_geometry']['parameters'])&set(self.spec['_furnishings']['parameters']))
        catalog=self.spec['_catalog'];text=json.dumps(catalog)
        self.assertNotIn('L01',text);self.assertNotIn('bench_height',text);self.assertNotIn('xyz',text)
        benches=[i for i in self.spec['_furnishings']['instances'] if i['type']=='storage_bench']
        self.assertEqual(len(benches),4)

    def test_catalog_type_can_be_reused_and_rotated_without_changing_the_room(self):
        p=room.parameters(self.spec);before=geometry.expanded(self.spec['_geometry'],p)
        item={'id':'IndependentBench','type':'storage_bench','component':'Furniture','bindings':{'width':400,'length':800,'height':900,'top_t':40,'plinth_h':100},'xyz':[100,200,0],'yaw_deg':90,'frames':{'Worktop':'IndependentBench.Top'}}
        result=furniture.instantiate(self.spec['_catalog'],item,p)
        self.assertEqual(len(result['bodies']),3)
        self.assertEqual(result['operations'][0]['shape']['kind'],'polygon_prism')
        frame=result['frames'][0]
        self.assertNestedClose([room.evaluate(x,p) for x in frame['origin']],[-300,400,900])
        self.assertNestedClose(frame['x_axis'],[0,1,0])
        self.assertEqual(geometry.expanded(self.spec['_geometry'],p),before)

    def test_moving_one_furniture_instance_moves_its_frame_only(self):
        changed=copy.deepcopy(self.spec);item=next(i for i in changed['_furnishings']['instances'] if i['id']=='IslandLeft')
        item['xyz'][0]='room_width/2-island_half_width+25'
        p=room.parameters(changed)
        frames=lambda spec:{f['id']:[room.evaluate(v,p) for v in f['origin']] for f in room.expanded(spec,p)['frames']}
        a,b=frames(self.spec),frames(changed)
        self.assertEqual(b['L01.IslandLeft.Worktop'][0]-a['L01.IslandLeft.Worktop'][0],25)
        for name in a:
            if name!='L01.IslandLeft.Worktop':self.assertEqual(a[name],b[name])

    def test_invalid_type_bindings_cycles_or_duplicate_ids_are_rejected(self):
        for defect in ['type','binding','cycle','duplicate','frame']:
            spec=copy.deepcopy(self.spec);f=spec['_furnishings']
            if defect=='type':f['instances'][0]['type']='missing'
            elif defect=='binding':f['instances'][0]['bindings']['height']='unknown_dimension'
            elif defect=='cycle':f['expressions'].update(a='b',b='a')
            elif defect=='duplicate':f['instances'].append(copy.deepcopy(f['instances'][0]))
            else:f['instances'][0]['frames']['missing']='Bad.Frame'
            with self.subTest(defect=defect),self.assertRaises(ValueError):room.expanded(spec,room.parameters(spec))


if __name__=='__main__':unittest.main()
