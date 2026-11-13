"""Room bindings, presentation transforms and the shared native furniture contract."""
import copy
import json
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_stack as stack
import building_furnishings as furniture


class FurnishingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = stack.load(); cls.p = stack.parameters(cls.spec)
        cls.data = stack.interfaces(cls.spec, cls.p)
        cls.result = furniture.compile(cls.spec['sources']['furnishings'], stack.templates(cls.spec)[0], cls.p, cls.data['levels'])

    def test_owner_room_assignments(self):
        self.assertEqual({r['room'] for r in self.result['rooms']}, {'1.008','1.002','2.002','3.002','3.009'})
        self.assertEqual({r['level'] for r in self.result['rooms'] if r['room']=='1.008'}, {'OG1'})
        self.assertEqual(self.result['omitted_walls'], ['OG1__Wall_W027'])

    def test_only_kitchen_partition_removed(self):
        expanded = stack.expanded(self.spec, self.p)
        ids = {b['id'] for b in expanded['bodies']}
        self.assertNotIn('OG1__Wall_W027',ids)
        self.assertTrue({'OG2__Wall_W027','OG3__Wall_W027'} <= ids)
        self.assertEqual(len(ids),len(expanded['bodies']))
        self.assertTrue({o['body'] for o in expanded['operations']} <= ids)

    def test_easter_egg_has_separate_occluding_door(self):
        kitchen = next(r for r in self.result['rooms'] if r['room']=='1.008')
        self.assertTrue(kitchen['easter_egg_body_ids'])
        self.assertEqual(len(kitchen['fridge_door_body_ids']),2)
        self.assertFalse(set(kitchen['fridge_door_body_ids']) & set(kitchen['easter_egg_body_ids']))
        self.assertTrue(any(o['body']=='Kitchen1008_Fridge_Shell' and o['action']=='cut' for o in self.result['operations']))

    def test_desk_and_chair_counts(self):
        ids = self.result['body_ids']
        for room in ['PhD1002','PhD2002','PhD3002']:
            self.assertEqual(sum(id.startswith(room+'_Desk') and id.endswith('_Top') for id in ids),4)
            self.assertEqual(sum(id.startswith(room+'_Chair') and id.endswith('_Seat') for id in ids),4)
        self.assertIn('Office3009_Desk_Top', ids)

    def test_separate_items_have_no_unintended_bbox_overlap(self):
        bounds={}
        for op in self.result['operations']:
            if op['action']!='create': continue
            shape=op['shape']
            if shape['kind']=='polygon_prism':
                lo=[min(v[i] for v in shape['points']) for i in (0,1)]+[shape['offset']]
                hi=[max(v[i] for v in shape['points']) for i in (0,1)]+[shape['offset']+shape['depth']]
            else:
                x,y,z=shape['origin'];r=shape['radius']
                lo=[x-r,y-r,z];hi=[x+r,y+r,z+shape['height']]
            bounds[op['body']]=(lo,hi)
        # These AABB overlaps are the intentionally cut basin and fridge cavities.
        cavity_pairs={frozenset(('LeftRun','Sink')),frozenset(('Fridge','Penguin')),frozenset(('Fridge','PenguinTea'))}
        names=list(bounds)
        for index,a in enumerate(names):
            for b in names[index+1:]:
                room,instance=a.split('_')[:2];other_room,other_instance=b.split('_')[:2]
                if (room,instance)==(other_room,other_instance): continue
                lo,hi=bounds[a];blo,bhi=bounds[b]
                if min(min(hi[k],bhi[k])-max(lo[k],blo[k]) for k in range(3))>1e-5:
                    self.assertEqual(room,other_room,(a,b))
                    self.assertIn(frozenset((instance,other_instance)),cavity_pairs,(a,b))

    def test_public_views_bind_current_sources_and_reviewed_images(self):
        proof=json.loads((stack.ROOT/'docs/media/building-furnishings.provenance.json').read_text())
        self.assertFalse(proof['original_photographs_included'])
        self.assertEqual({image['id'] for image in proof['images']},{'Kitchen1008','PhD1002','Kitchen1008_EasterEgg'})
        for name,digest in proof['source_files_sha256'].items():
            self.assertEqual(hashlib.sha256((stack.ROOT/name).read_bytes()).hexdigest(),digest,name)
        for image in proof['images']:
            data=(stack.ROOT/image['path']).read_bytes()
            self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(hashlib.sha256(data).hexdigest(),image['sha256'])
            self.assertTrue(image['visual_reviewed'])

    def test_sources_match_declared_schemas(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        for source, schema in [('furnishings/building-social.json', 'building-furnishings.schema.json'), ('furniture/social.catalog.json', 'social-furniture-catalog.schema.json')]:
            Draft202012Validator(json.loads((stack.ROOT/'model'/schema).read_text())).validate(json.loads((stack.ROOT/'model'/source).read_text()))

    def test_stale_pins_rejected(self):
        ref=copy.deepcopy(self.spec['sources']['furnishings']);ref['source_sha256']='0'*64
        with self.assertRaises(ValueError): furniture.read(ref)

    def test_vertical_placement_and_body_ownership(self):
        source=stack.expanded(self.spec,self.p)
        by_room={r['id']:r for r in self.result['rooms']}
        for body in self.result['bodies']:
            room=by_room[body['component'].removesuffix('_Furniture')]
            self.assertFalse(room['placement_qualified'])
            self.assertGreater(room['presentation_scale'],0)
            for op in [o for o in self.result['operations'] if o['body']==body['id']]:
                shape=op['shape']; z=shape.get('offset',shape.get('origin',[0,0,0])[2])
                self.assertGreaterEqual(z,room['origin_mm'][2]-1e-6)
        stack.solidcraft_commands(self.spec,self.p)


class KitchenSeatingTests(unittest.TestCase):
    def test_kitchen_chairs_are_evenly_distributed_along_both_long_sides(self):
        ref=json.loads(stack.SOURCE.read_text())['sources']['furnishings']
        source=furniture.read(ref);catalog=furniture.read(source['catalog'])
        kitchen=next(room for room in source['rooms'] if room['room']=='1.008')
        tables=[item for item in kitchen['instances'] if item['id'].startswith('Table')]
        top=next(part['shape'] for part in catalog['types']['desk'] if part['id']=='Top')
        self.assertTrue(all(item['yaw_deg']==90 for item in tables))
        xlo=min(t['xyz_mm'][0]-top['size'][1] for t in tables)
        xhi=max(t['xyz_mm'][0] for t in tables)
        ylo=min(t['xyz_mm'][1] for t in tables)
        yhi=max(t['xyz_mm'][1]+top['size'][0] for t in tables)
        chairs=[item for item in kitchen['instances'] if item['type'] in ('dining_chair','office_chair')]
        self.assertEqual(len(chairs),8)
        sides=[[c for c in chairs if c['xyz_mm'][0]<xlo],[c for c in chairs if c['xyz_mm'][0]>xhi]]
        self.assertEqual([len(side) for side in sides],[4,4])
        rows=[]
        for side,yaw in zip(sides,[90,-90]):
            ys=sorted(c['xyz_mm'][1] for c in side);pitch=(yhi-ylo)/len(side)
            self.assertTrue(all(ylo<y<yhi for y in ys))
            self.assertTrue(all(c['yaw_deg']==yaw for c in side))
            for index,y in enumerate(ys):self.assertAlmostEqual(y,ylo+(index+.5)*pitch)
            rows.append(ys)
        self.assertEqual(rows[0],rows[1])


if __name__=='__main__': unittest.main()
