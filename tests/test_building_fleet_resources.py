"""Static conflict closure must precede independent own vehicle grants."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_resources import ResourceCatalog,_positive_overlap


def navigation(rooms=()):
    return SimpleNamespace(radius=50,reserve=10,
        config={'missions':{'targets':[{'level':'EG','area':a}for a in rooms]},'depot':{'level':'EG','areas':[]}},
        polygons={'EG':{a:[[i*1000,0],[(i+1)*1000,0],[(i+1)*1000,1000],[i*1000,1000]]for i,a in enumerate(rooms)}},
        topological={'EG':{'connections':[{'areas':list(rooms[:2]),'wall':'W1','opening':'D1'}]if len(rooms)>=2 else[]}})


def route(identifier,x,level='EG'):
    return {'level':level,'points_mm':[[x-1000,0],[x+1000,0]],
            'resources':[{'id':identifier,'kind':'passage','start_index':0,'end_index':1,'crossing_mm':[x,0]}]}


class StaticResourcesTests(unittest.TestCase):
    def test_different_names_and_opposite_routes_share_overlapping_token(self):
        a=route('EG.merge.A',1000);b=route('EG.merge.B',1050)
        b['points_mm'].reverse()
        c=ResourceCatalog(navigation(),[a,b])
        self.assertEqual(c.canonical['EG.merge.A'],c.canonical['EG.merge.B'])
        self.assertEqual(len(c.resources),1)
        self.assertTrue(c.normalize(a)['resource_spans'])
        self.assertEqual(c.normalize(a)['resource_spans'][0]['resource'],c.normalize(b)['resource_spans'][0]['resource'])

    def test_separated_regions_and_other_floors_are_not_global_mutex(self):
        c=ResourceCatalog(navigation(),[route('EG.A',0),route('EG.B',3000),route('OG1.A',0,'OG1')])
        self.assertEqual(len(c.resources),3)
        self.assertFalse(c.report()['whole_floor_mutex_added'])

    def test_connected_selected_rooms_share_room_and_door_resource(self):
        nav=navigation(('R1','R2'))
        row={'level':'EG','points_mm':[[-500,500],[2500,500]],'resources':[
            {'id':'EG.D1','kind':'room','start_index':0,'end_index':1,'crossing_mm':[1000,500],'areas':['R1','R2']}]}
        c=ResourceCatalog(nav,[row])
        self.assertEqual(c.canonical['EG.room.R1'],c.canonical['EG.room.R2'])
        self.assertEqual(c.canonical['EG.D1'],c.canonical['EG.room.R1'])
        self.assertEqual(len(c.resources),1)

    def test_shared_boundary_is_not_positive_region_overlap(self):
        first=[[0,0],[1,0],[1,1],[0,1]]
        self.assertFalse(_positive_overlap(first,[[1,0],[2,0],[2,1],[1,1]]))
        self.assertTrue(_positive_overlap(first,[[.9,0],[2,0],[2,1],[.9,1]]))


if __name__=='__main__':unittest.main()
