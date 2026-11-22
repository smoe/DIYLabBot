"""Exact cached/full-route resource closure equivalence, without CAD claims.

The reference below preserves the former uncached/full-route sample algorithm.
Fixtures are bounded static maps and are never exported as fleet programmes.
"""
import collections
import copy
import math
import random
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


def reference_raw_windows(catalog,level,path):
    """Former uncached all-room/all-sample algorithm, before any alias unions."""
    marked=collections.defaultdict(list);visited=[]
    for lev,alias,polygon in catalog.room_polygons:
        if lev==level and any(_point_distance(path.evaluate((a+b)/2)[0][:2],polygon)<=(b-a)/2+1e-6 for a,b,_,_ in path.samples):visited.append((alias,polygon))
    for a,b,_,_ in path.samples:
        centre=path.evaluate((a+b)/2)[0][:2];movement=(b-a)/2+1e-6;candidates=set()
        for key in catalog._cells(level,([v-movement for v in centre],[v+movement for v in centre]),padding=20):candidates.update(catalog._index.get(key,()))
        aliases={catalog.regions[i]['alias']for i in candidates if _point_distance(centre,catalog.regions[i]['polygon'])<=movement}
        aliases.update(alias for alias,polygon in visited if _point_distance(centre,polygon)<=catalog.guard+movement)
        for alias in aliases:marked[alias].append((a,b))
    return dict(marked)


class ResourceOptimizationReview(unittest.TestCase):
    def assert_equivalent(self,nav,bank,queries):
        original=copy.deepcopy(bank);reference=FullRouteReference(nav,bank);cached=ResourceCatalog(nav,bank)
        self.assertEqual(bank,original)
        self.assertEqual(cached.canonical,reference.canonical);self.assertEqual(cached.resources,reference.resources)
        self.assertEqual(len(cached.paths),len(reference.paths),'Every complete static path must remain present')
        for (level,path),(_,reference_path)in zip(cached.paths,reference.paths):
            self.assertEqual(cached._raw_windows(level,path),reference_raw_windows(reference,level,reference_path),
                             'Raw alias/sample windows must agree before canonical closure can conceal a discrepancy')
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

    def test_capped_complete_paths_keep_uncached_alias_windows_and_queries(self):
        row=route([[-500,0],[0,0],[0,500],[700,500]],'EG.capped')
        row.update(corner_trim_mm=250,corner_trim_caps=[{'point_index':2,'maximum_trim_mm':20},
                                                      {'point_index':1,'maximum_trim_mm':35}])
        reference,cached=self.assert_equivalent(navigation(),[row],[('EG',row['points_mm'])])
        path=MotionPath(row['points_mm'],250,corner_trim_caps=row['corner_trim_caps'])
        self.assertEqual(observed_spans(cached,'EG',path),observed_spans(reference,'EG',path))

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

    def test_threshold_broad_phase_never_discards_original_contact(self):
        rng=random.Random(20261122)
        for offset in(0.,-1e9,1e12):
            polygon=[[offset-31,offset-17],[offset+23,offset-17],
                     [offset+23,offset+19],[offset-2,offset+3],[offset-31,offset+19]]
            bounds=resources._bounds(polygon)
            points=[[offset+rng.uniform(-100,100),offset+rng.uniform(-100,100)]for _ in range(300)]
            for vertex in polygon:
                points.extend([[math.nextafter(vertex[0],x),math.nextafter(vertex[1],y)]
                               for x in(-math.inf,math.inf)for y in(-math.inf,math.inf)])
            for point in points:
                distance=_point_distance(point,polygon)
                for threshold in(0.,distance,math.nextafter(distance,0.),math.nextafter(distance,math.inf),10.):
                    if distance<=threshold:
                        self.assertTrue(resources._bounds_may_reach(point,bounds,threshold),
                                        (point,distance,threshold))

    def test_many_room_index_keeps_full_route_closure_and_avoids_far_distances(self):
        nav=navigation();rooms={}
        for index in range(24):
            x=2000*(index%6);y=2000*(index//6)
            rooms[str(index)]=[[x,y],[x+500,y],[x+500,y+500],[x,y+500]]
        nav.polygons['EG']=rooms
        nav.config['missions']['targets']=[{'level':'EG','area':area}for area in rooms]
        nav.topological['EG']['plan']['areas']=[{'id':area,'kind':'room'}for area in rooms]
        bank=[route([[-100,250],[11000,250]],'EG.A'),
              route([[-100,2250],[11000,2250]],'EG.B'),
              route([[250,-100],[250,7000]],'EG.C'),
              route([[4250,-100],[4250,7000]],'EG.D')]
        reference,cached=self.assert_equivalent(nav,bank,
            [('EG',[[-200,260],[11200,260]]),('EG',[[4260,-200],[4260,7200]])])
        cached._distance.cache_clear();cached._within.cache_clear();cached._candidates.cache_clear()
        path=MotionPath([[-500,-500],[-400,-500]],1)
        with patch.object(resources,'_point_distance',wraps=resources._point_distance)as calculation:
            self.assertEqual(cached._raw_windows('EG',path),{})
            self.assertEqual(calculation.call_count,0,'Far room and guard boxes need no polygon distances')
        self.assertEqual(len(cached.paths),len(bank))

    def test_threshold_memos_keep_adjacent_float_values_and_bounded_keys(self):
        cached=ResourceCatalog(navigation([[0,0],[1,0],[1,1],[0,1]]),
                               [route([[-10,-10],[-9,-9]])])
        identity=id(cached.room_polygons[0][2]);point=(2.,.5)
        below=math.nextafter(1.,0.)
        self.assertFalse(cached._within(point,identity,below))
        self.assertTrue(cached._within(point,identity,1.))
        self.assertEqual(cached._within.cache_info().maxsize,65536)
        self.assertEqual(cached._candidates.cache_info().maxsize,32768)
        self.assertNotEqual(cached._within(point,identity,1.),
                            cached._within((math.nextafter(2.,math.inf),.5),identity,1.))

    def test_overflow_and_underflow_prone_ray_predicates_keep_original_result(self):
        cases=[([[0.,0.],[1e200,1e200],[0.,1e200]],[2e200,.5e200]),
               ([[0.,0.],[2e-150,2e-174],[0.,2e-174]],[2.2e-150,1.9e-174])]
        for polygon,point in cases:
            with self.subTest(polygon=polygon):
                self.assertEqual(_point_distance(point,polygon),0.,'Fixture exercises original ray arithmetic')
                self.assertTrue(resources._bounds_may_reach(point,resources._bounds(polygon),0.))
        self.assertTrue(resources._bounds_may_reach((math.inf,0.),([0.,0.],[1.,1.]),1.))

    def test_numerically_unsafe_room_stays_in_candidates_without_grid_expansion(self):
        polygon=[[0.,0.],[2e-150,2e-174],[0.,2e-174]]
        nav=navigation(polygon);cached=ResourceCatalog(nav,[route([[-10,-10],[-9,-9]])])
        self.assertEqual(cached._unindexed_rooms['EG'],[0])
        point=(2.2e-150,1.9e-174)
        self.assertIn(0,cached._candidates('EG',point,0.,True))
        identity=id(cached.room_polygons[0][2])
        self.assertTrue(cached._within(point,identity,0.))

    def test_identical_geometry_shares_only_exact_distance_math_not_aliases(self):
        cached=ResourceCatalog(navigation(),[route([[-500,0],[500,0]],'EG.A'),
                                               route([[-500,0],[500,0]],'EG.B')])
        first,second=cached.regions[0],next(row for row in cached.regions if row['alias']=='EG.B')
        self.assertEqual(first['polygon'],second['polygon'])
        self.assertNotEqual(first['alias'],second['alias'])
        self.assertEqual(cached._polygon_canonical[id(first['polygon'])],cached._polygon_canonical[id(second['polygon'])])


if __name__=='__main__':unittest.main()
