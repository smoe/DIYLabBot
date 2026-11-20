"""Static canonical BF01 conflict regions; never receives fleet world poses.

Candidate resource names from separate routes are not independent locks when
regions overlap. This catalog closes that relation before execution. Selected
rooms linked by doors share one room resource, including both door windows.
Wide passing lanes remain unreserved away from their merge regions.
"""
import collections
import copy
import hashlib
import math

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
    def __init__(self,navigation,routes):
        self.nav=navigation;self.guard=navigation.radius+navigation.reserve+4
        self.parent={};self.kind={};self.regions=[];self.room_alias={};self.room_polygons=[]
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
                self.regions.append({'level':level,'alias':alias,'polygon':polygon,'bounds':_bounds(polygon)})

    def _spans(self,level,path,canonical=True):
        marked=collections.defaultdict(list)
        # Select rooms actually visited by the centreline; their fixed portal
        # guards separately cover nearby paths that merely skim an open door.
        visited=[]
        for lev,alias,polygon in self.room_polygons:
            if lev==level and any(_point_distance(path.evaluate((a+b)/2)[0][:2],polygon)<=(b-a)/2+1e-6 for a,b,_,_ in path.samples):
                visited.append((alias,polygon))
        for a,b,_,_ in path.samples:
            centre=path.evaluate((a+b)/2)[0][:2];movement=(b-a)/2+1e-6
            candidates=set()
            for key in self._cells(level,([v-movement for v in centre],[v+movement for v in centre]),padding=20):
                candidates.update(self._index.get(key,()))
            aliases=set()
            for i in candidates:
                row=self.regions[i]
                if _point_distance(centre,row['polygon'])<=movement:aliases.add(row['alias'])
            for alias,polygon in visited:
                if _point_distance(centre,polygon)<=self.guard+movement:aliases.add(alias)
            for alias in aliases:
                key=self.canonical[alias]if canonical else self._find(alias)
                marked[key].append((a,b))
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
