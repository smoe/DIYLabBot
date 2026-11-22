"""Static canonical BF01 conflict regions; never receives fleet world poses.

Candidate resource names from separate routes are not independent locks when
regions overlap. This catalog closes that relation before execution. Selected
rooms linked by doors share one room resource, including both door windows.
Wide passing lanes remain unreserved away from their merge regions.
"""
import collections
import copy
import hashlib
import json
import math
import sys
from pathlib import Path as FilePath
from functools import lru_cache

import building_fleet_model as model
from building_fleet_motion import Path
from building_fleet_navigation import point_in_polygon


def _bounds(poly):
    return ([min(p[k]for p in poly)for k in range(2)],[max(p[k]for p in poly)for k in range(2)])


def _inside(point,poly):
    return point_in_polygon(point,poly)


def _point_distance(point,poly):
    from building_fleet_sim import point_segment_distance
    if _inside(point,poly):return 0.
    return min(point_segment_distance(point,a,b)for a,b in zip(poly,poly[1:]+poly[:1]))


_BROAD_PHASE_MIN=math.sqrt(math.sqrt(sys.float_info.min))
_BROAD_PHASE_MAX=math.sqrt(math.sqrt(sys.float_info.max))


def _broad_phase_finite(values):
    """Keep overflow/underflow-prone arithmetic on the original predicate."""
    return all(math.isfinite(v)and(v==0 or _BROAD_PHASE_MIN<=abs(v)<=_BROAD_PHASE_MAX)for v in values)


def _bounds_may_reach(point,bounds,threshold):
    """One-sided broad phase; the original polygon distance decides contact.

    Roundoff padding covers the subtraction/multiply/divide chain in the
    original ray and segment predicates, including cancellation at large
    offsets. Ambiguous boundary queries therefore keep the original test.
    This numerical envelope changes no physical guard or distance threshold.
    """
    lo,hi=bounds
    if not _broad_phase_finite((*point,*lo,*hi,threshold)):return True
    padding=32*max(math.ulp(v)for v in(*point,*lo,*hi,threshold))
    reach=threshold+padding
    return all(lo[k]-point[k]<=reach and point[k]-hi[k]<=reach for k in range(2))


def _positive_overlap(a,b):
    """Positive-area overlap for convex catalog guards; touching is insufficient."""
    lo,hi=_bounds(a);other_lo,other_hi=_bounds(b)
    if any(min(hi[k],other_hi[k])-max(lo[k],other_lo[k])<=1e-8 for k in range(2)):return False
    # All guard polygons are convex. Strict separating axes distinguish a
    # shared wall line from a common traversable region.
    for poly in(a,b):
        for p,q in zip(poly,poly[1:]+poly[:1]):
            x,y=-(q[1]-p[1]),q[0]-p[0]
            if math.hypot(x,y)<1e-12:continue
            av=[x*p[0]+y*p[1]for p in a];bv=[x*p[0]+y*p[1]for p in b]
            if min(max(av),max(bv))-max(min(av),min(bv))<=1e-8:return False
    return True


def _guards(points,radius):
    polygons=[];sides=16;outer=radius/math.cos(math.pi/sides)
    for x,y in points:
        polygons.append([[x+outer*math.cos(2*math.pi*i/sides),y+outer*math.sin(2*math.pi*i/sides)]for i in range(sides)])
    for a,b in zip(points,points[1:]):
        length=math.dist(a,b)
        if length<1e-8:continue
        nx,ny=-(b[1]-a[1])/length*radius,(b[0]-a[0])/length*radius
        polygons.append([[a[0]+nx,a[1]+ny],[b[0]+nx,b[1]+ny],[b[0]-nx,b[1]-ny],[a[0]-nx,a[1]-ny]])
    return polygons


class ResourceCatalog:
    def __init__(self,navigation,routes,*,_cached_canonical=None):
        self.nav=navigation;self.guard=navigation.radius+navigation.reserve+4
        self.parent={};self.kind={};self.regions=[];self.room_alias={};self.room_polygons=[];self._region_keys=set()
        self.paths=[];self._frozen=False
        active={(r['level'],r['area'])for r in navigation.config['missions']['targets']}
        active|={(navigation.config['depot']['level'],area)for area in navigation.config['depot']['areas']}
        # Closed-door transit offices are room resources too. Public open
        # foyer/circulation areas are not merged into an artificial floor lock.
        # Explicit target/depot roles remain authoritative even with open edges.
        for level,entry in navigation.topological.items():
            edges=entry['connections']
            for area in entry.get('plan',{}).get('areas',[]):
                ident=area['id']
                incident=[edge for edge in edges if ident in edge['areas']]
                if (area['kind']=='room' and ident not in entry.get('excluded_areas',[]) and incident
                        and not any(edge.get('kind')=='open_boundary'for edge in incident)):
                    active.add((level,ident))
        for level,area in sorted(active):
            alias=level+'.room.'+area;self._add(alias,'room');self.room_alias[(level,area)]=alias
            self.room_polygons.append((level,alias,navigation.polygons[level][area]))
        for level,entry in navigation.topological.items():
            for edge in entry['connections']:
                areas=edge['areas']
                if len(areas)==2 and all((level,a)in active for a in areas):
                    self._union(*(self.room_alias[(level,a)]for a in areas))
        portals={}
        for level,entry in navigation.topological.items():
            for edge in entry['connections']:
                portals[level+'.'+edge.get('opening',edge['wall'])]=(level,edge['areas'])
        for route in routes:
            self._route(route,portals)
        # Exact immutable geometry only. Bounded point-query memoization never
        # rounds coordinates and cannot retain an unbounded runtime path bank.
        self._polygon_refs={id(p):p for _,_,p in self.room_polygons}
        self._polygon_refs.update({id(row['polygon']):row['polygon']for row in self.regions})
        self._polygon_bounds={identity:_bounds(polygon)for identity,polygon in self._polygon_refs.items()}
        self._polygon_numeric_safe={identity:_broad_phase_finite(v for point in polygon for v in point)
                                    for identity,polygon in self._polygon_refs.items()}
        exact_geometry={};self._polygon_canonical={}
        for identity,polygon in self._polygon_refs.items():
            key=tuple(tuple(point)for point in polygon)
            self._polygon_canonical[identity]=exact_geometry.setdefault(key,identity)
        self._distance=lru_cache(maxsize=32768)(lambda point,identity:_point_distance(point,self._polygon_refs[identity]))
        self._within=lru_cache(maxsize=65536)(lambda point,identity,threshold:
            (not self._polygon_numeric_safe[identity]or _bounds_may_reach(point,self._polygon_bounds[identity],threshold))
            and self._distance(point,self._polygon_canonical[identity])<=threshold)
        self._room_index=collections.defaultdict(list);self._rooms_by_level=collections.defaultdict(list)
        self._unindexed_rooms=collections.defaultdict(list);self._room_numeric_padding={}
        for index,(level,_,polygon)in enumerate(self.room_polygons):
            self._rooms_by_level[level].append(index)
            if not self._polygon_numeric_safe[id(polygon)]:
                self._unindexed_rooms[level].append(index);continue
            self._room_numeric_padding[level]=max(self._room_numeric_padding.get(level,20),
                32*max(math.ulp(v)for point in polygon for v in point))
            for key in self._cells(level,self._polygon_bounds[id(polygon)],padding=0):self._room_index[key].append(index)
        self._static_paths={(level,id(path)):path for level,path in self.paths};self._raw_alias_windows={}
        # Geometry closes differing aliases before any vehicle requests a token.
        index=collections.defaultdict(list)
        for i,row in enumerate(self.regions):
            for key in self._cells(row['level'],row['bounds'],padding=0):
                for j in index[key]:
                    other=self.regions[j]
                    if self._find(row['alias'])!=self._find(other['alias']) and _positive_overlap(row['polygon'],other['polygon']):
                        self._union(row['alias'],other['alias'])
                index[key].append(i)
        # A path can only hold one narrow token. Close overlaps of conservative
        # progress windows as a static relation too, not as a runtime shortcut.
        self._index=index
        # A finer lookup partitions the same immutable polygons; guard size is
        # only a bin width here, never a changed physical conflict envelope.
        self._query_cell_size=self.guard;self._query_index=collections.defaultdict(list)
        self._region_coarse_bounds=[]
        for i,row in enumerate(self.regions):
            self._region_coarse_bounds.append(tuple(tuple(math.floor(v/1000)for v in pair)for pair in row['bounds']))
            for key in self._query_cells(row['level'],row['bounds'],0):self._query_index[key].append(i)
        self._candidates=lru_cache(maxsize=32768)(self._candidate_indices)
        if _cached_canonical is not None:
            self._restore_closure(_cached_canonical)
            self._frozen=True
            return
        for _ in range(max(1,len(self.parent))):
            changed=False
            for level,path in self.paths:
                spans=self._spans(level,path,canonical=False)
                for i,a in enumerate(spans):
                    for b in spans[i+1:]:
                        if b['start_progress_mm']>=a['end_progress_mm']-1e-7:break
                        if self._find(a['resource'])!=self._find(b['resource']):
                            self._union(a['resource'],b['resource']);changed=True
            if not changed:break
        else:raise RuntimeError('Static conflict-region closure did not converge')
        grouped=collections.defaultdict(list)
        for alias in self.parent:grouped[self._find(alias)].append(alias)
        self.canonical={};self.resources={}
        for aliases in grouped.values():
            level=aliases[0].split('.')[0]
            identifier=level+'.resource.'+hashlib.sha256('\n'.join(sorted(aliases)).encode()).hexdigest()[:16]
            for alias in aliases:self.canonical[alias]=identifier
            self.resources[identifier]='room'if any(self.kind[a]=='room'for a in aliases)else'passage'
        self._frozen=True

    def _restore_closure(self, canonical):
        """Restore only a source/input-bound closure, never cached geometry."""
        if type(canonical)is not dict or set(canonical)!=set(self.parent):
            raise ValueError('Cached resource aliases differ from current source routes')
        groups=collections.defaultdict(list)
        for alias,resource in canonical.items():
            if not isinstance(resource,str):raise ValueError('Named immutable resource required')
            groups[resource].append(alias)
        self.canonical={};self.resources={}
        for resource,aliases in groups.items():
            levels={a.split('.')[0]for a in aliases}
            if len(levels)!=1:raise ValueError('A resource closure cannot join different floors')
            expected=next(iter(levels))+'.resource.'+hashlib.sha256('\n'.join(sorted(aliases)).encode()).hexdigest()[:16]
            if resource!=expected:raise ValueError('Cached canonical resource identity changed')
            for alias in aliases:self.canonical[alias]=resource
            self.resources[resource]='room'if any(self.kind[a]=='room'for a in aliases)else'passage'
        mandatory=collections.defaultdict(set)
        for alias in self.parent:mandatory[self._find(alias)].add(self.canonical[alias])
        if any(len(resources)!=1 for resources in mandatory.values()):
            raise ValueError('Cached closure splits a current source adjacency or geometric overlap')
        for aliases in groups.values():
            for alias in aliases[1:]:self._union(aliases[0],alias)

    def _cache_pins(self):
        if not callable(getattr(self.nav,'_cache_pins',None)):
            raise ValueError('Source-bound navigation required for resource caching')
        names=('building_fleet_resources.py','building_fleet_missions.py','building_fleet_motion.py')
        return {**self.nav._cache_pins(),**{'scripts/'+name:model.digest(model.ROOT/'scripts'/name)for name in names}}

    @staticmethod
    def route_bank_hash(routes):
        return hashlib.sha256(json.dumps(routes,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

    @staticmethod
    def _cache_directory(directory):
        path=FilePath(directory).resolve()
        if not path.is_relative_to((model.ROOT/'exports/building-fleet').resolve()):
            raise ValueError('Resource cache must remain in ignored BF01 exports')
        return path

    def write_cache(self,directory,routes):
        """Persist only static closure data with exact source and route pins."""
        if not self._frozen:raise ValueError('Close all source resources before caching')
        directory=self._cache_directory(directory);pins=self._cache_pins();bank=self.route_bank_hash(routes)
        if (directory/'cache-report.json').exists():raise FileExistsError(directory)
        directory.mkdir(parents=True,exist_ok=True)
        raw=(json.dumps({'canonical':self.canonical},sort_keys=True,separators=(',',':'))+'\n').encode()
        report={'format':'solidcraftbot.building-fleet-resource-cache/1','source_files_sha256':pins,
                'route_bank_sha256':bank,'route_count':len(routes),'file':'closure.json',
                'bytes':len(raw),'artifact_sha256':hashlib.sha256(raw).hexdigest(),
                'scope':'Immutable source-route conflict closure only; no runtime state, motion qualification or executable pickle'}
        (directory/'closure.json').write_bytes(raw)
        if pins!=self._cache_pins():raise ValueError('Resource cache sources changed during export')
        (directory/'cache-report.json').write_text(json.dumps(report,indent=2)+'\n')
        return report

    @classmethod
    def from_cache(cls,navigation,routes,directory):
        directory=cls._cache_directory(directory);report=model.read_json(directory/'cache-report.json')
        probe=object.__new__(cls);probe.nav=navigation;pins=probe._cache_pins()
        fields={'format','source_files_sha256','route_bank_sha256','route_count','file','bytes','artifact_sha256','scope'}
        if (set(report)!=fields or report.get('format')!='solidcraftbot.building-fleet-resource-cache/1'
                or report.get('file')!='closure.json' or report.get('source_files_sha256')!=pins
                or report.get('route_bank_sha256')!=cls.route_bank_hash(routes)
                or report.get('route_count')!=len(routes)):
            raise ValueError('Resource cache source or complete route-bank pins are stale')
        artifact=(directory/'closure.json').resolve()
        if not artifact.is_relative_to(directory)or artifact.stat().st_size>4*1024*1024:
            raise ValueError('Bounded project-local resource cache required')
        raw=artifact.read_bytes()
        if len(raw)>4*1024*1024 or len(raw)!=report.get('bytes')or hashlib.sha256(raw).hexdigest()!=report.get('artifact_sha256'):
            raise ValueError('Resource closure cache bytes changed')
        data=json.loads(raw,parse_constant=lambda value:(_ for _ in()).throw(ValueError('Nonfinite cache data')))
        if type(data)is not dict or set(data)!={'canonical'}:raise ValueError('Only immutable canonical closure data is accepted')
        result=cls(navigation,routes,_cached_canonical=data['canonical'])
        if pins!=result._cache_pins():raise ValueError('Resource cache sources changed during reconstruction')
        return result

    def _add(self,alias,kind):
        if alias not in self.parent:self.parent[alias]=alias;self.kind[alias]=kind
        elif kind=='room':self.kind[alias]='room'

    def _find(self,alias):
        while self.parent[alias]!=alias:
            self.parent[alias]=self.parent[self.parent[alias]];alias=self.parent[alias]
        return alias

    def _union(self,a,b):
        a,b=self._find(a),self._find(b)
        if a!=b:self.parent[max(a,b)]=min(a,b)

    @staticmethod
    def _cells(level,bounds,padding=20):
        lo,hi=bounds
        for x in range(math.floor((lo[0]-padding)/1000),math.floor((hi[0]+padding)/1000)+1):
            for y in range(math.floor((lo[1]-padding)/1000),math.floor((hi[1]+padding)/1000)+1):yield level,x,y

    def _route(self,route,portals):
        points=route['points_mm'];level=route['level']
        if len(points)<2:return
        # Reverse cusps are a geometry error, never a reason to spin in place.
        self.paths.append((level,Path(points,route.get('corner_trim_mm',250))))
        for row in route.get('resources',[]):
            alias=row['id'];kind=row.get('kind','passage');areas=row.get('areas',portals.get(alias,(level,[]))[1])
            rooms=[self.room_alias[(level,a)]for a in areas if(level,a)in self.room_alias]
            if rooms:
                target=rooms[0];self._add(alias,'room');self._union(alias,target)
                for other in rooms[1:]:self._union(alias,other)
            else:self._add(alias,'passage'if kind!='room'else'room')
            if 'crossing_mm'in row:
                anchors=[row['crossing_mm']]
            else:
                begin=max(0,min(len(points)-1,row['start_index']));end=max(begin,min(len(points)-1,row['end_index']))
                anchors=points[begin:end+1]
            for polygon in _guards(anchors,self.guard):
                key=(level,alias,tuple(tuple(p)for p in polygon))
                if key not in self._region_keys:
                    self._region_keys.add(key)
                    self.regions.append({'level':level,'alias':alias,'polygon':polygon,'bounds':_bounds(polygon)})

    def _raw_windows(self,level,path):
        """Whole-route room semantics and exact raw aliases, before unions."""
        marked=collections.defaultdict(list)
        samples=[(a,b,tuple(path.position((a+b)/2)),(b-a)/2+1e-6)for a,b,_,_ in path.samples]
        # Select rooms actually visited by the centreline; their fixed portal
        # guards separately cover nearby paths that merely skim an open door.
        visited_indices=set()
        for _,_,centre,movement in samples:
            for index in self._candidates(level,centre,movement,True):
                if index in visited_indices:continue
                _,_,polygon=self.room_polygons[index]
                if self._within(centre,id(polygon),movement):visited_indices.add(index)
        visited=[self.room_polygons[index][1:]for index in sorted(visited_indices)]
        for a,b,centre,movement in samples:
            aliases=set()
            for i in self._candidates(level,centre,movement,False):
                row=self.regions[i]
                if self._within(centre,id(row['polygon']),movement):aliases.add(row['alias'])
            for alias,polygon in visited:
                if self._within(centre,id(polygon),self.guard+movement):aliases.add(alias)
            for alias in aliases:marked[alias].append((a,b))
        return dict(marked)

    def _candidate_indices(self,level,centre,movement,rooms):
        """Exact query keys and immutable per-floor indices; no live path bank."""
        index=self._room_index if rooms else self._query_index
        # Retain the former 20mm bin padding and enlarge it only for numerical
        # cancellation at unusually large coordinate offsets. Final distance
        # decisions still use the original, unexpanded movement threshold.
        safe=_broad_phase_finite((*centre,movement))
        if rooms and not safe:return frozenset(self._rooms_by_level.get(level,()))
        if not rooms and not safe:
            result=set()
            for key in self._cells(level,([v-movement for v in centre],[v+movement for v in centre]),padding=20):
                result.update(self._index.get(key,()))
            return frozenset(result)
        padding=max(20,32*max(math.ulp(v)for v in(*centre,movement)))if safe else 20
        if rooms:padding=max(padding,self._room_numeric_padding.get(level,20))
        result=set(self._unindexed_rooms.get(level,()))if rooms else set()
        bounds=([v-movement for v in centre],[v+movement for v in centre])
        cells=self._cells(level,bounds,padding)if rooms else self._query_cells(level,bounds,padding)
        for key in cells:
            result.update(index.get(key,()))
        if not rooms:
            # Preserve the former coarse-bin selection exactly as an outer
            # gate, including its original floating-point boundary arithmetic.
            qlo=[math.floor((v-movement-20)/1000)for v in centre]
            qhi=[math.floor((v+movement+20)/1000)for v in centre]
            result={i for i in result if all(self._region_coarse_bounds[i][0][k]<=qhi[k]
                                           and self._region_coarse_bounds[i][1][k]>=qlo[k]for k in range(2))}
        return frozenset(result)

    def _query_cells(self,level,bounds,padding):
        lo,hi=bounds;size=self._query_cell_size
        for x in range(math.floor((lo[0]-padding)/size),math.floor((hi[0]+padding)/size)+1):
            for y in range(math.floor((lo[1]-padding)/size),math.floor((hi[1]+padding)/size)+1):yield level,x,y

    def _spans(self,level,path,canonical=True):
        identity=(level,id(path));raw=self._raw_alias_windows.get(identity)
        if raw is None:
            raw=self._raw_windows(level,path)
            if self._static_paths.get(identity)is path:self._raw_alias_windows[identity]=raw
        marked=collections.defaultdict(list)
        for alias,intervals in raw.items():
            key=self.canonical[alias]if canonical else self._find(alias)
            marked[key].extend(intervals)
        spans=[]
        for resource,intervals in marked.items():
            intervals.sort();start,end=intervals[0]
            for a,b in intervals[1:]:
                if a<=end+1e-6:end=max(end,b)
                else:
                    spans.append({'resource':resource,'start_progress_mm':start,'end_progress_mm':end});start,end=a,b
            spans.append({'resource':resource,'start_progress_mm':start,'end_progress_mm':end})
        return sorted(spans,key=lambda row:(row['start_progress_mm'],row['end_progress_mm'],row['resource']))

    def spans(self,level,path):
        if not self._frozen:raise RuntimeError('Resource catalog is not closed')
        spans=self._spans(level,path)
        for a,b in zip(spans,spans[1:]):
            if b['start_progress_mm']<a['end_progress_mm']-1e-6 and a['resource']!=b['resource']:
                raise ValueError('New path overlaps independent static resource regions; rebuild catalog before execution')
        return spans

    def normalize(self,route):
        result=copy.deepcopy(route);path=Path(result['points_mm'],result.get('corner_trim_mm',250))
        result['resource_spans']=self.spans(result['level'],path)
        return result

    def report(self):
        return {'format':'solidcraftbot.building-fleet-resource-catalog/1',
                'resources':self.resources,'aliases':self.canonical,
                'regions':[{**r,'resource':self.canonical[r['alias']]}for r in self.regions],
                'room_polygons':[{'level':lev,'resource':self.canonical[alias],'polygon':poly}
                                 for lev,alias,poly in self.room_polygons],
                'room_guard_mm':self.guard,
                'basis':'source-room adjacency and immutable overlapping static route guards; no live fleet poses',
                'whole_floor_mutex_added':False}
