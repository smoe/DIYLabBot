"""Office equipment stays on referenced tops; existing furniture remains leading."""
import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import building_stack as stack
import building_furnishings as furniture
import relative_floorplan as floor

class OfficeComputerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=stack.load();cls.p=stack.parameters(cls.spec);cls.data=stack.interfaces(cls.spec,cls.p)
        cls.plans={v['id']:stack.level_plan(cls.spec,v['id']) for v in cls.data['levels'] if v['id'].startswith('OG')}
        cls.source=furniture.read(cls.spec['sources']['furnishings'])
        cls.result=furniture.compile(cls.spec['sources']['furnishings'],stack.templates(cls.spec)[0],cls.p,cls.data['levels'],cls.plans)
    def test_thirteen_screen_and_mini_pc_sets(self):
        rooms=self.result['rooms'];self.assertEqual([(r['room'],len(r.get('worktop_equipment',[]))) for r in rooms],[('1.008',0),('1.002',4),('2.002',4),('3.002',4),('3.009',1)])
        for suffix in ('MonitorScreen','MiniPC'):
            self.assertEqual(sum(b['id'].endswith('_'+suffix) for b in self.result['bodies']),13)
    def test_all_equipment_is_inside_support_footprint_and_above_top(self):
        operations={o['body']:o['shape'] for o in self.result['operations'] if o['action']=='create'}
        for room in self.result['rooms']:
            for binding in room.get('worktop_equipment',[]):
                top=operations[binding['support_body']];height=top['offset']+top['depth']
                self.assertAlmostEqual(binding['origin_mm'][2],height)
                for body in binding['body_ids']:
                    shape=operations[body];self.assertGreaterEqual(shape['offset'],height-1e-6)
                    self.assertTrue(all(floor.point_membership(q,top['points'])>=0 for q in shape['points']))
    def test_short_glass_door_side_top_is_not_a_workstation(self):
        room=next(r for r in self.result['rooms'] if r['room']=='3.002')
        supports=[v['support_instance'] for v in room['worktop_equipment']]
        self.assertEqual(supports.count('Desk0'),2);self.assertNotIn('Desk2',supports)
    def test_existing_geometry_is_unchanged_when_equipment_is_removed(self):
        source=copy.deepcopy(self.source)
        for room in source['rooms']:room['instances']=[v for v in room['instances'] if 'worktop_anchor' not in v]
        original=furniture.read
        def read(ref):return source if ref['source'].endswith('building-social.json') else original(ref)
        with patch.object(furniture,'read',side_effect=read):before=furniture.compile(self.spec['sources']['furnishings'],stack.templates(self.spec)[0],self.p,self.data['levels'],self.plans)
        ids={b['id'] for b in before['bodies']}
        self.assertEqual(before['bodies'],[b for b in self.result['bodies'] if b['id'] in ids])
        self.assertEqual(before['operations'],[o for o in self.result['operations'] if o['body'] in ids])
    def test_unknown_or_overhanging_anchor_is_rejected(self):
        original=furniture.read
        for mutation in ('unknown','edge'):
            source=copy.deepcopy(self.source);room=next(r for r in source['rooms'] if r['room']=='1.002');item=next(v for v in room['instances'] if 'worktop_anchor' in v)
            if mutation=='unknown':item['worktop_anchor']['instance']='Missing'
            else:item['worktop_anchor']['uv']=[0,0]
            def read(ref):return source if ref['source'].endswith('building-social.json') else original(ref)
            with self.subTest(mutation=mutation),patch.object(furniture,'read',side_effect=read),self.assertRaises(ValueError):
                furniture.compile(self.spec['sources']['furnishings'],stack.templates(self.spec)[0],self.p,self.data['levels'],self.plans)
if __name__=='__main__':unittest.main()
