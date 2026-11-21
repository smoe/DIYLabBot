"""Exact cached/full-route resource closure equivalence, without CAD claims.

The reference below preserves the former uncached/full-route sample algorithm.
Fixtures are bounded static maps and are never exported as fleet programmes.
"""
import collections
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_resources as resources
from building_fleet_resources import ResourceCatalog,_point_distance
from building_fleet_motion import Path as MotionPath
from building_fleet_runner import local_shortcut_neighbourhood


class NoDedup:
    def __contains__(self,key):return False
    def add(self,key):pass


class FullRouteReference(ResourceCatalog):
    """Former exact full-path behavior, deliberately without performance caches."""
    def _route(self,route,portals):
        self._region_keys=NoDedup()
        return super()._route(route,portals)

    def _spans(self,level,path,canonical=True):
        marked=collections.defaultdict(list);visited=[]
        for lev,alias,polygon in self.room_polygons:
            if lev==level and any(_point_distance(path.evaluate((a+b)/2)[0][:2],polygon)<=(b-a)/2+1e-6 for a,b,_,_ in path.samples):
                visited.append((alias,polygon))
        for a,b,_,_ in path.samples:
            centre=path.evaluate((a+b)/2)[0][:2];movement=(b-a)/2+1e-6;candidates=set()
            for key in self._cells(level,([v-movement for v in centre],[v+movement for v in centre]),padding=20):
                candidates.update(self._index.get(key,()))
            aliases=set()
            for index in candidates:
                row=self.regions[index]
                if _point_distance(centre,row['polygon'])<=movement:aliases.add(row['alias'])
            for alias,polygon in visited:
                if _point_distance(centre,polygon)<=self.guard+movement:aliases.add(alias)
            for alias in aliases:marked[self.canonical[alias]if canonical else self._find(alias)].append((a,b))
        spans=[]
        for resource,intervals in marked.items():
            intervals.sort();start,end=intervals[0]
            for a,b in intervals[1:]:
                if a<=end+1e-6:end=max(end,b)
                else:spans.append({'resource':resource,'start_progress_mm':start,'end_progress_mm':end});start,end=a,b
            spans.append({'resource':resource,'start_progress_mm':start,'end_progress_mm':end})
        return sorted(spans,key=lambda row:(row['start_progress_mm'],row['end_progress_mm'],row['resource']))


def navigation(room_polygon=None):
    rooms=[]if room_polygon is None else[{'level':'EG','area':'R'}]
    return NS(radius=100,reserve=10,
        config={'missions':{'targets':rooms},'depot':{'level':'EG','areas':[]}},
        topological={level:{'connections':[],'excluded_areas':[],'plan':{'areas':[{'id':'R','kind':'room'}]if level=='EG'and room_polygon is not None else[]}}for level in('EG','OG1')},
        polygons={'EG':{}if room_polygon is None else{'R':room_polygon},'OG1':{}})


def route(points,identifier=None,indices=None,level='EG'):
    claims=[]
    if identifier is not None:
        a,b=(0,len(points)-1)if indices is None else indices
        claims=[{'id':identifier,'kind':'passage','start_index':a,'end_index':b}]
    return {'level':level,'points_mm':points,'resources':claims,'corner_trim_mm':1}


def observed_spans(catalog,level,path):
    try:return ('ok',catalog.spans(level,path))
    except ValueError as error:return ('rejected',str(error))


class ResourceOptimizationReview(unittest.TestCase):
    def assert_equivalent(self,nav,bank,queries):
        original=copy.deepcopy(bank);reference=FullRouteReference(nav,bank);cached=ResourceCatalog(nav,bank)
        self.assertEqual(bank,original)
        self.assertEqual(cached.canonical,reference.canonical);self.assertEqual(cached.resources,reference.resources)
        self.assertEqual(len(cached.paths),len(reference.paths),'Every complete static path must remain present')
        for level,points in queries:
            for geometry in(points,list(reversed(points))):
                path=MotionPath(geometry,1)
                self.assertEqual(observed_spans(cached,level,path),observed_spans(reference,level,path))
        return reference,cached

    def test_full_route_closure_and_future_spans_match_without_duplicate_guards(self):
        bank=[route([[-500,0],[500,0]],'EG.A'),route([[-500,10],[500,10]],'EG.B'),
              route([[2500,0],[3500,0]],'EG.C'),route([[-500,0],[500,0]],'OG1.A',level='OG1')]
        bank.extend(copy.deepcopy(bank[:2])*4)
        reference,cached=self.assert_equivalent(navigation(),bank,
            [('EG',[[-600,0],[700,0]]),('EG',[[-600,300],[3600,300]]),('OG1',[[-600,0],[700,0]])])
        self.assertLess(len(cached.regions),len(reference.regions))
        unique={(row['level'],row['alias'],tuple(tuple(p)for p in row['polygon']))for row in reference.regions}
        self.assertEqual(len(cached.regions),len(unique))

    def test_whole_route_visited_room_semantics_are_retained(self):
        room=[[-1000,480],[-5,480],[-5,0],[5,0],[5,500],[-1000,500]]
        nav=navigation(room)
        A=route([[-990,490],[-1100,490],[-1100,-60],[-400,-60],[0,-174],[0,-300]],'EG.room.R',(0,0))
        A['resources'][0].update(kind='room',areas=['R'])
        B=route([[400,-60],[0,-174],[0,-300]])
        full=route([[-990,490],[-1100,490],[-1100,-60],[-400,-60],[400,-60]],'EG.splice.X',(3,4))
        local=route([[-1100,-60],[-400,-60],[400,-60]],'EG.splice.X',(1,2))
        self.assertTrue(local_shortcut_neighbourhood([-400,-60],[0,-174],[400,-60],110))
        reference,cached=self.assert_equivalent(nav,[A,B,full,copy.deepcopy(full)],
            [('EG',full['points_mm']),('EG',local['points_mm'])])
        self.assertEqual(cached.canonical['EG.room.R'],cached.canonical['EG.splice.X'])
        # This demonstrates why shortening catalog inputs is unsafe: the local
        # context never visits R, but its full route activates R's guard here.
        shortened=ResourceCatalog(nav,[A,B,local])
        self.assertNotEqual(shortened.canonical['EG.room.R'],shortened.canonical['EG.splice.X'])

    def test_static_raw_windows_are_reused_and_remapped_to_current_roots(self):
        bank=[route([[-500,0],[500,0]],'EG.A'),route([[-500,10],[500,10]],'EG.B')]
        cached=ResourceCatalog(navigation(),bank);level,path=cached.paths[0]
        with patch.object(resources,'_point_distance',wraps=resources._point_distance)as calculation:
            first=cached._spans(level,path,canonical=False);second=cached._spans(level,path,canonical=False)
        self.assertEqual(first,second);self.assertEqual(calculation.call_count,0)
        for row in cached._raw_alias_windows.values():self.assertTrue(all(alias in cached.parent for alias in row))
        self.assertEqual(cached.canonical['EG.A'],cached.canonical['EG.B'])

    def test_runtime_paths_are_not_retained_and_cache_keys_include_floor(self):
        bank=[route([[-500,0],[500,0]],'EG.A'),route([[-500,0],[500,0]],'OG1.A',level='OG1')]
        nav=navigation();reference,cached=self.assert_equivalent(nav,bank,[])
        static_keys=set(cached._raw_alias_windows)
        for i in range(50):
            path=MotionPath([[-500,i],[500,i]],1)
            for level in('EG','OG1'):
                self.assertEqual(observed_spans(cached,level,path),observed_spans(reference,level,path))
        self.assertEqual(set(cached._raw_alias_windows),static_keys)
        self.assertEqual(cached._distance.cache_info().maxsize,32768)
        self.assertEqual(set(cached._static_paths),{(level,id(path))for level,path in cached.paths})

    def test_distance_cache_has_no_coordinate_rounding(self):
        nav=navigation([[0,0],[1,0],[1,1],[0,1]])
        cached=ResourceCatalog(nav,[route([[-10,-10],[-9,-9]])])
        polygon=cached.room_polygons[0][2];near=(2.,.5);next_point=(math.nextafter(2.,math.inf),.5)
        first=cached._distance(near,id(polygon));second=cached._distance(next_point,id(polygon))
        self.assertEqual(first,_point_distance(near,polygon));self.assertEqual(second,_point_distance(next_point,polygon))
        self.assertNotEqual(first,second)


if __name__=='__main__':unittest.main()
