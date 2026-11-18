"""MI01 source, placement and building integration contracts."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import building_stack as stack
import building_microscopy as placement
import building_furnishings as furniture
import microscope_model as model
import building_walkthrough as walkthrough


class MicroscopeTests(unittest.TestCase):
    def test_optical_parts_and_four_supports_survive_parameter_variants(self):
        spec=model.load()
        for overrides in ({},{k:v['range'][0] for k,v in spec['parameters'].items()},
                          {k:v['range'][1] for k,v in spec['parameters'].items()}):
            p=model.parameters(spec,overrides);source=model.expanded(spec,p)
            bodies={b['id']:b for b in source['bodies']}
            self.assertEqual(len(bodies),len(source['bodies']))
            self.assertEqual(len([b for b in bodies.values() if b['role']=='microscope_objective']),6)
            self.assertEqual(len([b for b in bodies.values() if b['role']=='microscope_support_foot']),4)
            self.assertIn('ScientificCamera',bodies);self.assertIn('GlassSlide',bodies)
            for op in source['operations']:
                self.assertIn(op['body'],bodies)
                box=model.shape_bounds(op['shape'])
                self.assertTrue(all(box['max'][i]>box['min'][i] for i in range(3)))
            for obj in spec['objectives']:
                lens=next(op['shape'] for op in source['operations'] if op['body']=='Objective_'+obj['id']+'_Lens')
                self.assertGreaterEqual(lens['origin'][2]-(p['stage_z']+3),1)

    def test_invalid_parameter_or_objective_is_rejected(self):
        spec=model.load()
        for value in [float('nan'),-1,9999]:
            with self.assertRaises(ValueError):model.parameters(spec,{'base_width':value})
        changed=copy.deepcopy(spec);changed['objectives'][0]['length_mm']=150
        with self.assertRaises(ValueError):model.parameters(changed)

    def test_half_turn_preserves_every_primitive_extent(self):
        spec=model.load();source=model.expanded(spec,model.parameters(spec));origin=[30,50,780]
        turned,_=placement.translate_instrument(source,'Test',origin,180)
        for before,after in zip(source['operations'],turned['operations']):
            a,b=model.shape_bounds(before['shape']),model.shape_bounds(after['shape'])
            for i in range(3):
                expected=origin[i]+(a['min'][i] if i==2 else -a['max'][i])
                self.assertAlmostEqual(b['min'][i],expected)
                self.assertAlmostEqual(b['max'][i]-b['min'][i],a['max'][i]-a['min'][i])


class PlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=stack.load();cls.p=stack.parameters(cls.spec)
        cls.levels=stack.interfaces(cls.spec,cls.p)['levels']
        cls.plans={v['id']:stack.level_plan(cls.spec,v['id']) for v in cls.levels}
        cls.ref=cls.spec['sources']['microscopy']

    def test_room_support_and_door_clearance(self):
        result=placement.compile(self.ref,self.plans,self.p,self.levels);v=result['interface']
        self.assertEqual((v['level_id'],v['area'],v['scale']),('OG3','R3_007',1))
        self.assertGreaterEqual(v['room_wall_clearance_mm'],99.99)
        self.assertGreater(v['support_edge_margin_mm'],150)
        self.assertTrue(all(c['minimum_sweep_margin_mm']>400 for c in v['door_sweep_checks']))
        self.assertTrue(all(b['level_id']=='OG3' and b['room_id']=='R3_007' for b in result['bodies']))
        self.assertEqual(len(v['instrument_body_ids']),148)

    def test_unsupported_instrument_placement_fails(self):
        original=furniture.read;equipment=original(self.ref)
        for change in [{'support':'MissingBench'},{'uv':[0,0]},{'yaw_deg':90}]:
            altered=copy.deepcopy(equipment);altered['placement'].update(change)
            with patch.object(furniture,'read',side_effect=lambda ref:altered if ref==self.ref else original(ref)):
                with self.assertRaises(ValueError):placement.compile(self.ref,self.plans,self.p,self.levels)

    def test_building_and_viewpoint_reference_the_same_instrument(self):
        program=walkthrough.compile();station=program['microscopy']
        view=next(s for s in program['stops'] if s['id']=='microscopy')
        self.assertEqual(view['level_id'],station['level_id'])
        self.assertEqual(view['anchor']['station'],station['id'])
        self.assertIn('model/microscope-mi01.shared.json',program['source_files_sha256'])
        scene=stack.expanded(self.spec,self.p);ids={b['id'] for b in scene['bodies']}
        self.assertTrue(set(station['body_ids'])<=ids)

    def test_sources_match_their_schemas(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema is not installed')
        for filename,schema in [('microscope-mi01.shared.json','microscope-mi01.schema.json'),
                                ('equipment/microscopy-3007.json','building-microscopy.schema.json'),
                                ('furnishings/microscopy-3007.json','building-microscopy.schema.json')]:
            jsonschema.Draft202012Validator(json.loads((ROOT/'model'/schema).read_text())).validate(json.loads((ROOT/'model'/filename).read_text()))


if __name__=='__main__':unittest.main()
