"""Registration must align complete envelopes and retain vertical connections."""
import copy
import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import building_stack as stack
import building_alignment as alignment
import relative_floorplan as floor


def distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1];t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.dist(point,[a[0]+t*dx,a[1]+t*dy])


class AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=stack.load();cls.canonical=stack.templates(cls.spec)[0]
        cls.reference=alignment.contour(cls.canonical,[a for a in cls.canonical['areas'] if a['id'] in cls.spec['roof']['opaque_area_ids']])

    def assert_same_boundary(self,plan,edges,other,target):
        for source,chain,dest,boundary in [(plan,edges,other,target),(other,target,plan,edges)]:
            segments=[(dest['vertices'][e['start']],dest['vertices'][e['end']]) for e in boundary]
            for e in chain:
                a,b=(source['vertices'][e[k]] for k in ('start','end'))
                # Check both directions and edge interiors, including all corners.
                for t in (0,.25,.5,.75,1):
                    point=[a[j]+t*(b[j]-a[j]) for j in (0,1)]
                    self.assertLess(min(distance(point,c,d) for c,d in segments),1e-10)

    def test_all_five_complete_envelopes_match_not_just_bounding_boxes(self):
        for level in self.spec['levels']:
            with self.subTest(level=level['id']):
                plan=stack.level_plan(self.spec,level['id'])
                external='ExternalStairGround' if level['id']=='EG' else 'R3_017'
                edges=alignment.contour(plan,[a for a in plan['areas'] if a['kind']!='void' and a['id'] not in {external,'ExternalLink'}])
                self.assert_same_boundary(plan,edges,self.canonical,self.reference)

    def test_lift_and_internal_stair_geometry_stays_exactly_in_shared_frame(self):
        for level in self.spec['levels']:
            plan=stack.level_plan(self.spec,level['id'])
            for name in self.spec['alignment']['fixed_areas']:
                if name not in {a['id'] for a in plan['areas']}:continue
                a=floor.outline(plan,name);b=floor.outline(self.canonical,name)
                self.assertAlmostEqual(floor.signed_area(a),floor.signed_area(b),places=12)
                self.assertTrue(all(floor.point_membership(p,b)==0 for p in a))
                self.assertTrue(all(floor.point_membership(p,a)==0 for p in b))
            # Lift ports must stay on the same shared walls, not only the shaft centre.
            walls={w['id']:w for w in plan['walls']};canonical={w['id']:w for w in self.canonical['walls']}
            for side in self.spec['circulation']['elevator']['sides'].values():
                w=side['wall']
                self.assertEqual({tuple(plan['vertices'][walls[w][k]]) for k in ('start','end')},{tuple(self.canonical['vertices'][canonical[w][k]]) for k in ('start','end')})

    def test_source_traces_are_unchanged_and_registered_graphs_remain_valid(self):
        for level,key in [('KG','basement'),('EG','ground_floor')]:
            path=ROOT/self.spec['sources'][key]['source'];before=path.read_bytes()
            plan=stack.level_plan(self.spec,level);floor.validate(plan)
            self.assertEqual(path.read_bytes(),before)
            self.assertIsNone(plan['calibration'])
        # The EG extension closes the recess without moving the stair's outer wall.
        plan=stack.level_plan(self.spec,'EG')
        self.assertIn('EnvelopeFoyerApron',{a['id'] for a in plan['areas']})

    def test_height_variant_keeps_xy_registration_and_connects_all_storeys(self):
        p=stack.parameters(self.spec,{'clear_height_mm':3500,'slab_thickness_mm':200})
        data=stack.interfaces(self.spec,p)
        self.assertEqual([(c['from_level'],c['to_level']) for c in data['circulation']['stairs'][0]['connectors']],[('KG','EG'),('EG','OG1'),('OG1','OG2'),('OG2','OG3')])
        self.assertEqual([l['z_mm'] for l in data['levels']],[-3700,0,3700,7400,11100])
        bottom=next(c for c in data['circulation']['connection_witnesses'] if c['id']=='ExternalFireStair_EG_OG1_Bottom_Connection')
        self.assertIn('EG__Area_ExternalStairGround',bottom['target_bodies'])

    def test_invalid_landmarks_and_core_policy_are_rejected(self):
        source=copy.deepcopy(self.spec['alignment']);source['fixed_areas']=[]
        with self.assertRaisesRegex(ValueError,'cores'):alignment.validate(source)
        source=copy.deepcopy(self.spec['alignment']);source['landmarks']['KG'][0][0]='MissingVertex'
        with self.assertRaisesRegex(ValueError,'Landmarks'):alignment.register(stack.ground.load(ROOT/self.spec['sources']['basement']['source']),self.canonical,[a for a in self.canonical['areas'] if a['id'] in self.spec['roof']['opaque_area_ids']],source,'KG')

    def test_cache_does_not_share_mutable_geometry(self):
        plan=stack.level_plan(self.spec,'EG');plan['vertices']['E010'][0]+=10
        self.assertLess(stack.level_plan(self.spec,'EG')['vertices']['E010'][0],1)

if __name__=='__main__':unittest.main()
