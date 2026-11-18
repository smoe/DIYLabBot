"""Photograph-bound kitchen and corrected pass-through lift regression checks."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import building_stack as stack
import building_walkthrough as walkthrough
import building_kitchenette as kitchen
import building_furnishings as furniture
import kitchenette_model as recipe


class KitchenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=stack.load();cls.p=stack.parameters(cls.spec)
        cls.interface=stack.interfaces(cls.spec,cls.p);cls.expanded=stack.expanded(cls.spec,cls.p)
        cls.program=walkthrough.compile();cls.station=cls.interface['kitchenette']

    def test_first_room_uses_full_scale_furniture_and_existing_appliances(self):
        k=self.station
        self.assertEqual((k['level_id'],k['template_areas'],k['scale']),('OG3',['R3_008A'],1))
        self.assertGreaterEqual(k['room_wall_clearance_mm'],7)
        self.assertEqual({i['type'] for i in k['appliance_instances']},{'fridge','microwave','kettle'})
        catalog=furniture.read(furniture.read(k['equipment_source'])['catalog'])
        for item in k['appliance_instances']:
            expected={k['id']+'_'+item['id']+'_'+part['body'] for part in catalog['types'][item['type']] if part['action']=='create'}
            self.assertTrue(expected<=set(k['appliance_body_ids']))
        ids={b['id'] for b in self.expanded['bodies']}
        self.assertTrue(set(k['body_ids'])<=ids)
        self.assertIn('Kitchen3008_Cabinet_DrawerFront5',ids)
        self.assertIn('Kitchen3008_Cabinet_SinkBasin',ids)

    def test_both_room_doors_open_toward_window_and_clear_continuous_sweep(self):
        checks=self.station['door_sweep_checks']
        self.assertEqual({v['opening_id'] for v in checks},{'D3_008A','D3_008AB'})
        self.assertTrue(all(v['opening_axis']==[-1,0] and v['minimum_clearance_mm']>100 for v in checks))
        policy=json.loads((ROOT/'model/building-doors.shared.json').read_text())
        selected=[v for v in policy['opening_overrides'] if v['opening_id'] in {'D3_008A','D3_008AB'}]
        self.assertEqual({v['level_id'] for v in selected},{'OG3'})
        self.assertTrue(all(v['type']=='plain' for v in selected))
        # The open entrance leaf is parked beyond the entire refrigerator door sweep.
        hinge=next(v['hinge_mm'] for v in checks if v['opening_id']=='D3_008A')
        fridge=next(v for v in self.station['appliance_supports'] if v['slot']=='fridge')
        self.assertGreater(hinge[1],fridge['bounds_mm']['max'][1]+560)

    def test_room_view_and_appliance_articulations_share_native_parts(self):
        stop=next(v for v in self.program['stops'] if v['id']=='kitchen3008')
        self.assertEqual(stop['level_id'],'OG3')
        self.assertLess(stop['target_mm'][0],stop['eye_mm'][0])
        objects={v['id']:v for v in self.program['objects']}
        for name in ('Fridge','Microwave'):
            obj=objects['Kitchen3008.'+name+'.Door']
            self.assertTrue(set(obj['moving_body_ids'])<=set(self.station['appliance_body_ids']))
            self.assertEqual(obj['states'],{'closed':0,'open':90})
        self.assertIn('Kitchen1008.Fridge.Door',objects)
        self.assertEqual(self.program['microscopy']['area'],'R3_007')

    def test_oversized_kitchen_is_rejected_without_rescaling(self):
        original=furniture.read
        ref=self.spec['sources']['kitchenette'];equipment=original(ref);furnishing=original(equipment['furnishings']);catalog=original(furnishing['catalog'])
        catalog['parameters']['width']['value']=1800
        plans={v['id']:stack.level_plan(self.spec,v['id']) for v in self.interface['levels']}
        with patch.object(furniture,'read',side_effect=lambda r:catalog if r==furnishing['catalog'] else original(r)):
            with self.assertRaisesRegex(ValueError,'room interior'):
                kitchen.compile(ref,plans,self.p,self.interface['levels'],self.spec['exterior']['doors'])

    def test_invalid_recipe_dimension_and_all_source_schemas(self):
        source=json.loads((ROOT/'model/furniture/kitchenette.catalog.json').read_text())
        changed=copy.deepcopy(source);changed['parameters']['width']['value']=float('nan')
        with self.assertRaises(ValueError):recipe.parameters(changed)
        try:import jsonschema
        except ImportError:self.skipTest('jsonschema not installed')
        from referencing import Registry,Resource
        schemas=[]
        for name in ('assembly-reference.schema.json','kitchenette.schema.json'):
            path=ROOT/'model'/name;schema=json.loads(path.read_text());schema['$id']=path.as_uri()
            schemas.append((schema['$id'],Resource.from_contents(schema)))
        validator=jsonschema.Draft202012Validator(schema,registry=Registry().with_resources(schemas))
        for name in ('furniture/kitchenette.catalog.json','furnishings/kitchen-3008.json','equipment/kitchen-3008.json'):
            validator.validate(json.loads((ROOT/'model'/name).read_text()))

    def test_lift_has_opposite_ports_for_low_and_upper_floors_and_both_cabin_apertures(self):
        lift=self.program['elevator']
        self.assertEqual([(p['level_id'],p['side']) for p in lift['ports'] if p['active']],
            [('KG','inward'),('EG','inward'),('OG1','outward'),('OG2','outward'),('OG3','outward')])
        cuts={op['id'] for op in self.expanded['operations'] if op['body']=='BuildingLiftCabin' and op['action']=='cut'}
        self.assertTrue({'LiftPort_EG_outward_CabinCut','LiftPort_EG_inward_CabinCut'}<=cuts)
        cabin=next(v for v in self.program['objects'] if v['id']==lift['object_id'])
        rails=lift['fittings']['interior']['rail_body_ids']
        self.assertEqual(len(rails),4)
        self.assertTrue(set(rails+['LiftCabinFloorFinish','LiftControlPanel','LiftTelephone'])<=set(cabin['moving_body_ids']))
        self.assertFalse(lift['lift_operation_implemented'])


if __name__=='__main__':unittest.main()
