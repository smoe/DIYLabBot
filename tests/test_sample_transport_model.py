"""TR01 contracts: common interfaces, honest capacity, and parameter coupling."""
from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sample_transport_model as model


class SampleTransportTests(unittest.TestCase):
    def setUp(self): self.spec=model.load(); self.p=model.parameters(self.spec)

    def test_batch_coverage_requires_known_rotor_load(self):
        v=self.spec['variants'][1]
        self.assertEqual(model.capacity(v),{'plates':0,'tubes':48})
        self.assertEqual(model.batch_coverage(self.spec,v),{'plates':None,'tubes':None})
        spec=copy.deepcopy(self.spec); spec['requirements']['required_tubes_per_batch']=49
        self.assertFalse(model.batch_coverage(spec,v)['tubes'])
        spec['requirements']['required_tubes_per_batch']=24
        self.assertTrue(model.batch_coverage(spec,v)['tubes'])

    def test_same_physical_cassette_in_all_floor_configurations(self):
        variants=self.spec['variants']; sources=[model.expanded(self.spec,self.p,v) for v in variants]
        # Compare all cassette primitives after subtracting their local datum.
        def cassette(source,bay):
            origin=next(f['origin_mm'] for f in source['interfaces'] if f['id']==f'B{bay}_CassetteDatum')
            result=[]
            for op in source['operations']:
                if op['body']!=f'B{bay}_Cassette': continue
                shape=copy.deepcopy(op['shape']); shape['origin']=[x-y for x,y in zip(shape['origin'],origin)]
                result.append((op['action'],shape))
            return result
        self.assertEqual(cassette(sources[0],1),cassette(sources[1],2))
        self.assertEqual(cassette(sources[0],1),cassette(sources[2],1))

    def test_deck_geometry_and_load_frames_change_together(self):
        v=self.spec['variants'][0]; p=model.parameters(self.spec,{'floor_deck_z':950})
        a=model.expanded(self.spec,self.p,v); b=model.expanded(self.spec,p,v)
        self.assertEqual(b['frames'][0]['origin_mm'][2]-a['frames'][0]['origin_mm'][2],150)
        self.assertEqual(b['interfaces'][0]['origin_mm'][2]-a['interfaces'][0]['origin_mm'][2],150)
        for source in [a,b]:
            deck=next(o['shape'] for o in source['operations'] if o['id']=='TopDeck')
            self.assertEqual(deck['origin'][2]+deck['size'][2],source['frames'][0]['origin_mm'][2])
        p=model.parameters(self.spec,{'floor_deck_z':700}); floor=model.expanded(self.spec,p,self.spec['variants'][2])
        self.assertEqual(floor['interfaces'][0]['origin_mm'][2],702)
        self.assertEqual(floor['joints'],[])

    def test_floor_only_architecture_does_not_claim_universal_arm_reach(self):
        self.assertFalse(self.spec['requirements']['track_required'])
        for v in self.spec['variants']:
            self.assertEqual(v['family'],'floor')
            source=model.expanded(self.spec,self.p,v)
            self.assertEqual(source['joints'],[])
            self.assertNotIn('Track',[c['id'] for c in source['components']])
        handoff=self.spec['handoff_requirements']
        self.assertEqual(handoff['station_registry'],[])
        self.assertFalse(handoff['all_station_reaches_verified'])
        self.assertTrue(handoff['load_stays_on_vehicle'])

    def test_unknown_and_out_of_range_dimensions_rejected(self):
        for p in [{'floor_deck_z':0},{'floor_deck_z':float('nan')},{'bench_travel':600},{'unknown':1},{'plate_height':90}]:
            with self.assertRaises(ValueError): model.parameters(self.spec,p)


if __name__=='__main__': unittest.main()
