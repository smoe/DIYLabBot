"""BF01 static navigation primitives in source-derived building coordinates.

Raster clearance is conservative: cells touched by a sliced native triangle are
occupied; an unsupported centre is occupied too. The exact squared Euclidean
transform measures distance to occupied cell centres. Subtracting one complete
cell diagonal bounds the distance to geometry and to the support boundary.
The circumscribed vehicle disc is a broad phase only: narrow passages require
an oriented-footprint proof before a route may be compiled.
"""
import array
import base64
import collections
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys

import building_stack as stack
import relative_floorplan as floor
import robot_spec as robot

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = frozenset({'R3_028', 'R3_017', 'ExternalStairGround', 'Atrium', 'LiftCore'})
DYNAMIC_ROLES = frozenset({'concept_existing_elevator_cabin', 'concept_lift_door_leaf',
                          'concept_lift_floor_finish', 'concept_lift_handrail',
                          'concept_lift_handrail_bracket', 'concept_lift_control_panel',
                          'concept_lift_floor_display', 'concept_lift_telephone',
                          'concept_lift_telephone_receiver'})


def squared_distance_transform_1d(values):
    """Exact lower envelope of integer-coordinate parabolas; O(n)."""
    n = len(values)
    sites = [i for i, value in enumerate(values) if math.isfinite(value)]
    if not sites:
        return [math.inf] * n
    vertices = [sites[0]]
    cuts = [-math.inf, math.inf]
    for q in sites[1:]:
        while True:
            v = vertices[-1]
            cut = ((values[q] + q*q) - (values[v] + v*v))/(2*(q-v))
            if len(vertices) == 1 or cut > cuts[-2]:
                break
            vertices.pop(); cuts.pop(-2)
        cuts[-1] = cut; cuts.append(math.inf); vertices.append(q)
    output = []
    k = 0
    for q in range(n):
        while cuts[k+1] < q:
            k += 1
        v = vertices[k]
        output.append((q-v)**2 + values[v])
    return output


def squared_distance_transform(blocked, width, height):
    if width <= 0 or height <= 0 or len(blocked) != width*height:
        raise ValueError('A rectangular nonempty raster is required')
    intermediate = array.array('d', [0])*(width*height)
    for y in range(height):
        row = squared_distance_transform_1d([0 if blocked[y*width+x] else math.inf for x in range(width)])
        intermediate[y*width:(y+1)*width] = array.array('d', row)
    output = array.array('d', [0])*(width*height)
    for x in range(width):
        column = squared_distance_transform_1d([intermediate[y*width+x] for y in range(height)])
        for y, value in enumerate(column):
            output[y*width+x] = value
    return output


def point_in_polygon(point, polygon):
    x, y = point; inside = False
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def clip_height(points, lower, upper):
    result = [list(p) for p in points]
    for z, keep_above in ((lower, True), (upper, False)):
        clipped = []
        if not result:
            break
        for a, b in zip(result, result[1:]+result[:1]):
            ai, bi = (a[2] >= z, b[2] >= z) if keep_above else (a[2] <= z, b[2] <= z)
            if ai:
                clipped.append(a)
            if ai != bi:
                u = (z-a[2])/(b[2]-a[2])
                clipped.append([a[k]+u*(b[k]-a[k]) for k in range(3)])
        result = clipped
    return [p[:2] for p in result]


def polygon_touches_box(polygon, xmin, ymin, xmax, ymax):
    """Separating-axis test, including zero-area clipped vertical triangles."""
    if not polygon:
        return False
    box = [(xmin,ymin),(xmax,ymin),(xmax,ymax),(xmin,ymax)]
    axes = [(1,0),(0,1)]
    axes += [(-(b[1]-a[1]), b[0]-a[0]) for a,b in zip(polygon,polygon[1:]+polygon[:1])]
    for ax, ay in axes:
        if ax == 0 and ay == 0:
            continue
        first = [ax*p[0]+ay*p[1] for p in polygon]
        second = [ax*p[0]+ay*p[1] for p in box]
        if max(first) < min(second)-1e-7 or max(second) < min(first)-1e-7:
            return False
    return True


def initial_transform(obj, point):
    """Same reference-relative joint convention as the walkthrough engine."""
    joint = obj['joint']; state = obj.get('initial_state', obj['reference_state'])
    delta = obj['states'][state]-obj['states'][obj['reference_state']]
    if joint['type'] == 'prismatic':
        return [point[k]+joint['axis'][k]*delta for k in range(3)]
    if joint['type'] != 'revolute':
        raise ValueError('Unsupported native presentation joint')
    axis = joint['axis']; norm = math.sqrt(sum(v*v for v in axis))
    ax = [v/norm for v in axis]; angle = math.radians(delta)
    c, s = math.cos(angle), math.sin(angle); origin = joint['origin_mm']
    q = [point[k]-origin[k] for k in range(3)]; dot = sum(a*b for a,b in zip(ax,q))
    cross = [ax[1]*q[2]-ax[2]*q[1], ax[2]*q[0]-ax[0]*q[2], ax[0]*q[1]-ax[1]*q[0]]
    return [origin[k]+c*q[k]+s*cross[k]+(1-c)*ax[k]*dot for k in range(3)]


class NativeMesh:
    def __init__(self, export, root=ROOT):
        root=Path(root).resolve();self.export=Path(export).resolve()
        if not self.export.is_relative_to(root):raise ValueError('Project-local fleet export required')
        report = json.loads((self.export/'build-report.json').read_text())
        if report.get('format')!='solidcraftbot.building-walkthrough-build/1' or report.get('passed') is not True or not report.get('source_files_sha256') or set(report.get('files',{}))!={'html','native_mesh','manifest'}:
            raise ValueError('A successful current walkthrough export is required')
        for name, digest in report['source_files_sha256'].items():
            path = (root/name).resolve()
            if not path.is_relative_to(root):raise ValueError('External source pin: '+name)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Stale walkthrough source: '+name)
        for key,name in report['files'].items():
            path=(self.export/Path(name).name).resolve()
            if not path.is_relative_to(self.export) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=report['artifact_sha256'][key]:
                raise ValueError('Changed walkthrough artifact: '+name)
        self.manifest = json.loads((self.export/'manifest.json').read_text())
        bundle=json.loads((self.export/'native-mesh.json').read_text())
        if self.manifest.get('format')!='solidcraftbot.building-walkthrough/1' or bundle.get('format')!='solidcraftbot.building-walkthrough-mesh/1':raise ValueError('Unsupported checked export format')
        self.scene=bundle['scenes']['building']
        self.positions = array.array('f'); self.positions.frombytes(base64.b64decode(self.scene['positions_base64']))
        self.indices = array.array('I'); self.indices.frombytes(base64.b64decode(self.scene['indices_base64']))
        if sys.byteorder != 'little':
            self.positions.byteswap(); self.indices.byteswap()
        self.transforms = collections.defaultdict(list)
        objects = {obj['id']:obj for obj in self.manifest['objects']}
        for obj in objects.values():
            chain = [obj]
            parent = obj.get('parent_object_id')
            while parent:
                chain.append(objects[parent]); parent = objects[parent].get('parent_object_id')
            for body in obj['moving_body_ids']:
                self.transforms[body] = chain

    def bounds(self, group):
        bounds=group['bounds_mm']
        if group['id']not in self.transforms:return bounds
        # A posed mesh is a shallow copy with a different articulation tree.
        # Fence cached bounds by this instance and by its numeric joint values.
        chain=self.transforms[group['id']]
        signature=tuple((id(obj),obj['states'][obj.get('initial_state',obj['reference_state'])],
                         obj['states'][obj['reference_state']])for obj in chain)
        key=(id(self),group['id'],signature)
        cache=getattr(self,'_posed_bounds_cache',None)
        if cache is None:self._posed_bounds_cache=cache={}
        if key in cache:return cache[key]
        points=[]
        for x in (bounds['min'][0],bounds['max'][0]):
            for y in (bounds['min'][1],bounds['max'][1]):
                for z in (bounds['min'][2],bounds['max'][2]):
                    point=[x,y,z]
                    for obj in chain:point=initial_transform(obj,point)
                    points.append(point)
        result={'min':[min(p[k]for p in points)for k in range(3)],
                'max':[max(p[k]for p in points)for k in range(3)]}
        cache[key]=result
        return result

    def triangles(self, group):
        for i in range(group['index_start'],group['index_start']+group['index_count'],3):
            points = []
            for idx in self.indices[i:i+3]:
                point = list(self.positions[3*idx:3*idx+3])
                for obj in self.transforms.get(group['id'], []):
                    point = initial_transform(obj,point)
                points.append(point)
            yield points


class ClearanceGrid:
    def __init__(self, bounds, resolution_mm=50):
        if not math.isfinite(resolution_mm) or resolution_mm <= 0:
            raise ValueError('Positive raster resolution required')
        self.floor_support=None;self._floor_edges={}
        self.resolution_mm = resolution_mm
        self.origin = [math.floor(v/resolution_mm)*resolution_mm-resolution_mm for v in bounds['min'][:2]]
        self.width,self.height = [math.ceil((v-self.origin[k])/resolution_mm)+2 for k,v in enumerate(bounds['max'][:2])]
        self.blocked = bytearray(self.width*self.height)
        self.supported = bytearray(self.width*self.height)
        self.distance_squared = None

    def centre(self, index):
        x,y = index%self.width,index//self.width
        return [self.origin[0]+(x+.5)*self.resolution_mm,self.origin[1]+(y+.5)*self.resolution_mm]

    def cell(self, xy):
        x,y = [math.floor((xy[k]-self.origin[k])/self.resolution_mm) for k in range(2)]
        return y*self.width+x if 0 <= x < self.width and 0 <= y < self.height else None

    def candidates(self, polygon):
        if not polygon:
            return
        xs,ys = zip(*polygon); r=self.resolution_mm
        x0=max(0,math.floor((min(xs)-self.origin[0])/r));x1=min(self.width-1,math.floor((max(xs)-self.origin[0])/r))
        y0=max(0,math.floor((min(ys)-self.origin[1])/r));y1=min(self.height-1,math.floor((max(ys)-self.origin[1])/r))
        for y in range(y0,y1+1):
            for x in range(x0,x1+1):
                yield y*self.width+x

    def raster(self, polygon, support=False):
        r = self.resolution_mm
        for i in self.candidates(polygon):
            c = self.centre(i)
            if support:
                if point_in_polygon(c,polygon):self.supported[i]=1
            elif polygon_touches_box(polygon,c[0]-r/2,c[1]-r/2,c[0]+r/2,c[1]+r/2):
                self.blocked[i]=1

    def raster_solid(self, polygons):
        """Fill bounded components of a closed body's projected surface.

        Native solids spanning the whole height band can project only their
        sides. Leaving that bounded interior empty would admit impossible
        depot poses inside equipment. Interior cavities are conservatively
        blocked too; this approximation may reject a route, never qualify it.
        """
        hits=set();r=self.resolution_mm
        for polygon in polygons:
            for i in self.candidates(polygon):
                c=self.centre(i)
                if polygon_touches_box(polygon,c[0]-r/2,c[1]-r/2,c[0]+r/2,c[1]+r/2):hits.add(i)
        if not hits:return
        x0=max(0,min(i%self.width for i in hits)-1);x1=min(self.width-1,max(i%self.width for i in hits)+1)
        y0=max(0,min(i//self.width for i in hits)-1);y1=min(self.height-1,max(i//self.width for i in hits)+1)
        outside=set();queue=collections.deque()
        for y in range(y0,y1+1):
            for x in (x0,x1):
                i=y*self.width+x
                if i not in hits and i not in outside:outside.add(i);queue.append(i)
        for x in range(x0,x1+1):
            for y in (y0,y1):
                i=y*self.width+x
                if i not in hits and i not in outside:outside.add(i);queue.append(i)
        while queue:
            i=queue.popleft();x,y=i%self.width,i//self.width
            for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                j=ny*self.width+nx
                if x0<=nx<=x1 and y0<=ny<=y1 and j not in outside and j not in hits:outside.add(j);queue.append(j)
        for y in range(y0,y1+1):
            for x in range(x0,x1+1):
                i=y*self.width+x
                if i not in outside:self.blocked[i]=1

    def finalize(self):
        for i, supported in enumerate(self.supported):
            if not supported:self.blocked[i]=1
        self.distance_squared=squared_distance_transform(self.blocked,self.width,self.height)
        return self

    def clearance_lower_mm(self, xy):
        i=self.cell(xy)
        if i is None or self.distance_squared is None:return 0
        # Full diagonal accounts for occupied/support centre discretization and
        # a query anywhere inside its cell rather than at its centre.
        return max(0,math.sqrt(self.distance_squared[i])*self.resolution_mm-math.sqrt(2)*self.resolution_mm)

    def proposal_line_free(self,a,b,radius_mm):
        """Conservative raster proposal; never a native floor qualification."""
        stack_=[(a,b,0)]
        while stack_:
            x,y,depth=stack_.pop();length=math.dist(x,y)
            if min(self.clearance_lower_mm(x),self.clearance_lower_mm(y))-length/2 >= radius_mm:continue
            mid=[(x[k]+y[k])/2 for k in range(2)]
            if self.clearance_lower_mm(mid)<radius_mm or depth>=24:return False
            stack_.extend([(x,mid,depth+1),(mid,y,depth+1)])
        return True

    def line_free(self,a,b,radius_mm):
        """Adaptive Lipschitz and canonical whole-sweep floor certificate."""
        if not self.proposal_line_free(a,b,radius_mm):return False
        provider=getattr(self,'floor_support',None)
        if provider is not None:
            key=(tuple(a),tuple(b),radius_mm)
            cache=getattr(self,'_floor_edges',{})
            if key not in cache:
                proof=provider.line(a,b,radius_mm,curve_ref={'scope':'static_route_edge','level':provider.level,'points_mm':[list(a),list(b)]})
                if len(cache)>20000:cache.clear()
                cache[key]=proof['passed'];self._floor_edges=cache
            return cache[key]
        return True

    def search(self,start,end,radius_mm,edge_validator=None):
        first,last=self.cell(start),self.cell(end)
        centres={};clearances={};edge_results={}
        def centre(i):
            if i not in centres:centres[i]=self.centre(i)
            return centres[i]
        def clearance(i):
            if i not in clearances:clearances[i]=self.clearance_lower_mm(centre(i))
            return clearances[i]
        def usable(i):return i is not None and clearance(i)>=radius_mm
        if not usable(first) or not usable(last):raise ValueError('Endpoint lacks conservative disc clearance')
        queue=[(0,first,0)];cost={first:0};previous={first:None}
        while queue:
            _,i,pushed_cost=heapq.heappop(queue)
            if pushed_cost!=cost[i]:continue
            if i==last:break
            x,y=i%self.width,i//self.width
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nx,ny=x+dx,y+dy
                if not(0<=nx<self.width and 0<=ny<self.height):continue
                j=ny*self.width+nx
                if not usable(j):continue
                # Both adjacent cell-centre endpoint clearances are cached.
                # The same Lipschitz bound certifies their whole short edge;
                # unresolved edges retain the adaptive proposal check.
                distance=math.hypot(dx,dy)*self.resolution_mm
                if min(clearance(i),clearance(j))-distance/2<radius_mm and not self.proposal_line_free(centre(i),centre(j),radius_mm):continue
                if edge_validator is not None:
                    edge=(i,j)
                    if edge not in edge_results:edge_results[edge]=edge_validator(centre(i),centre(j))
                    if not edge_results[edge]:continue
                score=cost[i]+distance*(1+radius_mm/max(radius_mm,clearance(j)))
                if score<cost.get(j,math.inf):
                    cost[j]=score;previous[j]=i
                    heapq.heappush(queue,(score+math.dist(centre(j),end),j,score))
        if last not in previous:raise ValueError('No conservative disc route; rectangle qualification required before declaring inaccessible')
        result=[];i=last
        while i is not None:result.append(self.centre(i));i=previous[i]
        result.reverse();result[0]=list(start);result[-1]=list(end)
        # Endpoint replacement also needs its own proof.
        if any(not self.line_free(a,b,radius_mm)or(edge_validator is not None and not edge_validator(a,b))for a,b in zip(result,result[1:])):raise ValueError('Endpoint connection failed')
        reduced=[result[0]];i=0
        while i<len(result)-1:
            j=len(result)-1
            while j>i+1 and(not self.line_free(result[i],result[j],radius_mm)or(edge_validator is not None and not edge_validator(result[i],result[j]))):j-=1
            reduced.append(result[j]);i=j
        return reduced


def topology(spec=None, navigation=None, excluded_by_level=None):
    spec=stack.load() if spec is None else spec
    navigation=json.loads((ROOT/'model/building-walkthrough.shared.json').read_text())['navigation'] if navigation is None else navigation
    parameters=stack.parameters(spec);interface=stack.interfaces(spec,parameters);result={}
    for level in interface['levels']:
        ident=level['id'];plan=stack.level_plan(spec,ident);excluded=EXCLUDED|set(navigation['closed_access_areas'].get(ident,[]))|set((excluded_by_level or {}).get(ident,[]))
        incidence={w['id']:[a['id'] for a in plan['areas'] if any(e['wall']==w['id'] for e in a['boundary'])] for w in plan['walls']}
        ports=[port for port in interface['circulation']['elevator']['ports'] if port['level_id']==ident and port['active']]
        neighbors={port['id']:[a for a in incidence[port['wall']] if a!='LiftCore'] for port in ports}
        if any(not ns or any(n in excluded for n in ns) for ns in neighbors.values()):raise ValueError('Active lift port has no permitted landing: '+ident)
        connections=[e for e in floor.topology(plan)['connections'] if e['kind'] in ('door','open_boundary') and len(e['areas'])==2 and not(set(e['areas'])&excluded)]
        result[ident]={'plan':plan,'active_ports':ports,'landing_neighbors':neighbors,'connections':connections,'excluded_areas':sorted(excluded),'display_scale':parameters['display_scale']}
    return result


def build_grid(mesh, level, vehicle_height_mm, resolution_mm=50, topological=None, support_config=None):
    """Slice checked native triangle surfaces, with floors and forbidden areas."""
    topological=topology() if topological is None else topological;entry=topological[level]
    z=next(row['z_mm'] for row in mesh.manifest['levels'] if row['id']==level)
    grid=ClearanceGrid(mesh.scene['bounds_mm'],resolution_mm)
    if support_config is None:
        import building_fleet_model as fleet_model
        support_config=fleet_model.load()
    from building_fleet_floor import floor_support
    grid.floor_support=floor_support(mesh,level,support_config)
    for triangle in grid.floor_support.triangles:grid.raster(triangle,True)
    dynamic_ids=set(next(o for o in mesh.manifest['objects'] if o['id']==mesh.manifest['elevator']['object_id'])['moving_body_ids'])
    for obj in mesh.manifest['objects']:
        if obj.get('mechanism')=='lift_door':dynamic_ids.update(obj['moving_body_ids'])
    for group in mesh.scene['groups']:
        if group['id'] in dynamic_ids or group['role'] in DYNAMIC_ROLES:continue
        bounds=mesh.bounds(group)
        support=group['role']=='concept_storey_slab' and abs(bounds['max'][2]-z)<.05
        if support:continue
        if bounds['max'][2]<z+20 or bounds['min'][2]>z+vehicle_height_mm:continue
        polygons=[]
        for triangle in mesh.triangles(group):
            if support:
                if all(abs(v[2]-z)<.05 for v in triangle):grid.raster([v[:2] for v in triangle],True)
            else:
                polygon=clip_height(triangle,z+20,z+vehicle_height_mm)
                if polygon:polygons.append(polygon)
        if polygons:grid.raster_solid(polygons)
    plan=entry['plan'];scale=entry['display_scale']
    for area in plan['areas']:
        if area['id'] not in entry['excluded_areas']:continue
        polygon=floor.area_points(plan,area)
        grid.raster([[v*scale for v in point] for point in polygon])
    return grid.finalize()


def _native_band_index(mesh, lower, upper):
    """Index immutable posed native bounds; retain exact clipped polygons."""
    key=(id(mesh),id(mesh.transforms),lower,upper)
    cache=getattr(mesh,'_fleet_band_cache',None)
    if cache is None:mesh._fleet_band_cache=cache={}
    if key in cache:return cache[key]
    rows=[];cells={};large=[];step=1000
    for group in mesh.scene['groups']:
        if group['role']in DYNAMIC_ROLES:continue
        bounds=mesh.bounds(group)
        if bounds['max'][2]<lower or bounds['min'][2]>upper:continue
        i=len(rows);rows.append((group,bounds))
        axes=[range(math.floor(bounds['min'][k]/step),math.floor(bounds['max'][k]/step)+1)for k in range(2)]
        if len(axes[0])*len(axes[1])>10000:large.append(i)
        else:
            for x in axes[0]:
                for y in axes[1]:cells.setdefault((x,y),[]).append(i)
    result=(rows,cells,large,{},step);cache[key]=result
    return result


def native_rectangle_collisions(mesh, level, start, end, yaw_rad,
                                half_length_mm, half_width_mm,
                                height_mm, reserve_mm=0):
    """Exact projection SAT for a fixed-yaw straight swept rectangle.

    This proves absence of contact with the native triangle surface over the
    whole segment, rather than sampling poses. Lengthwise motion is required;
    diagonal translation relative to the vehicle needs the convex swept hull.
    A collision result is conservative and is never a proof of unreachability.
    """
    c,s=math.cos(yaw_rad),math.sin(yaw_rad)
    tangent=(c,s);normal=(-s,c);delta=[end[k]-start[k] for k in range(2)]
    if abs(sum(delta[k]*normal[k]for k in range(2)))>1e-6:
        raise ValueError('Straight rectangle certificate requires motion parallel to heading')
    length=sum(delta[k]*tangent[k]for k in range(2));lo=min(0,length)-half_length_mm-reserve_mm;hi=max(0,length)+half_length_mm+reserve_mm
    width=half_width_mm+reserve_mm
    z=next(row['z_mm']for row in mesh.manifest['levels']if row['id']==level)
    body=set();lower=z+20;upper=z+height_mm
    bound_min=[min(start[k],end[k])-math.hypot(half_length_mm+reserve_mm,width) for k in range(2)]
    bound_max=[max(start[k],end[k])+math.hypot(half_length_mm+reserve_mm,width) for k in range(2)]
    rows,cells,large,polygons,step=_native_band_index(mesh,lower,upper)
    candidates=set(large)
    for x in range(math.floor(bound_min[0]/step),math.floor(bound_max[0]/step)+1):
        for y in range(math.floor(bound_min[1]/step),math.floor(bound_max[1]/step)+1):candidates.update(cells.get((x,y),[]))
    for i in sorted(candidates):
        group,bounds=rows[i]
        # These bounds already include the complete source articulation chain.
        if any(bounds['max'][k]<bound_min[k]or bounds['min'][k]>bound_max[k]for k in range(2)):continue
        if i not in polygons:polygons[i]=[p for tri in mesh.triangles(group)if(p:=clip_height(tri,lower,upper))]
        for polygon in polygons[i]:
            local=[[(p[0]-start[0])*tangent[0]+(p[1]-start[1])*tangent[1],
                    (p[0]-start[0])*normal[0]+(p[1]-start[1])*normal[1]]for p in polygon]
            if polygon_touches_box(local,lo,-width,hi,width):body.add(group['id']);break
    return sorted(body)


def opening_portals(topological, level, approach_mm=700):
    """Source-centred portal lines with source wall normals and area ownership."""
    entry=topological[level];plan=entry['plan'];scale=entry['display_scale']
    walls={w['id']:w for w in plan['walls']};openings={o['id']:o for o in plan['openings']};areas={a['id']:a for a in plan['areas']}
    result=[]
    for edge in entry['connections']:
        wall=walls[edge['wall']];a,b=[[v*scale for v in plan['vertices'][wall[k]]]for k in ('start','end')]
        length=math.dist(a,b);tan=[(b[k]-a[k])/length for k in range(2)];normal=[-tan[1],tan[0]]
        interval=openings[edge['opening']]['interval']if'opening'in edge else[0,1]
        midpoint=[a[k]+sum(interval)/2*(b[k]-a[k])for k in range(2)]
        points=[[midpoint[k]+sign*approach_mm*normal[k]for k in range(2)]for sign in(-1,1)]
        owners=[]
        for point in points:
            owners.append(next((ident for ident in edge['areas']if point_in_polygon(point,[[v*scale for v in xy]for xy in floor.area_points(plan,areas[ident])])),None))
        result.append({'id':level+'.'+edge.get('opening',edge['wall']),
                       'kind':edge['kind'],'areas':list(edge['areas']),
                       'opening':edge.get('opening'),'wall':edge['wall'],
                       'opening_width_mm':length*(interval[1]-interval[0]),
                       'centre_mm':midpoint,'tangent':tan,'normal':normal,
                       'approach_mm':points,'approach_areas':owners,
                       'geometry_qualified':False})
    return result


def transformed_l01_lanes(laboratory, motion_source=None):
    """Evaluate the existing lane expressions in the bound room variant."""
    motion_source=json.loads((ROOT/'model/tr01-l01.motion.json').read_text())if motion_source is None else motion_source
    p=laboratory['evaluated_parameters_mm'];matrix=laboratory['transform']
    values={name:robot.evaluate(expr,p)for name,expr in motion_source['traffic_policy']['lane_centres_mm'].items()}
    local=[[values['left'],values['front']],[values['right'],values['front']],
           [values['right'],values['rear']],[values['left'],values['rear']]]
    def world(point):return[sum(matrix[k][j]*point[j]for j in range(2))+matrix[k][3]for k in range(2)]
    vertices=[world(v)for v in local]
    return{'source':'model/tr01-l01.motion.json#/traffic_policy/lane_centres_mm',
           'bound_values_mm':values,'vertices_mm':vertices,
           'segments_mm':[[a,b]for a,b in zip(vertices,vertices[1:]+vertices[:1])],
           'ingress_qualified':False}


def closed_mesh_membership(mesh, body_id, point):
    """Interior witness for a closed native body using distinct upward hits.

    A degenerate/on-boundary witness is not accepted. This is a negative
    feasibility witness, not an affirmative route-clearance qualification.
    """
    group=next(g for g in mesh.scene['groups']if g['id']==body_id);hits=[]
    for triangle in mesh.triangles(group):
        a,b,c=triangle
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-10:continue
        u=((b[1]-c[1])*(point[0]-c[0])+(c[0]-b[0])*(point[1]-c[1]))/den
        v=((c[1]-a[1])*(point[0]-c[0])+(a[0]-c[0])*(point[1]-c[1]))/den
        if min(u,v,1-u-v)<-1e-9:continue
        z=u*a[2]+v*b[2]+(1-u-v)*c[2]
        if abs(z-point[2])<=1e-7:return{'inside':False,'boundary':True,'upward_hits_mm':[]}
        if z>point[2]:hits.append(z)
    unique=[]
    for z in sorted(hits):
        if not unique or abs(z-unique[-1])>1e-5:unique.append(z)
    return{'inside':len(unique)%2==1,'boundary':False,'upward_hits_mm':unique}


def check_l01_feasibility(mesh):
    """Reject the currently prescribed L01 centre-lane graph if cut twice.

    Scope is the existing transformed lane graph with its existing corner trim,
    not all conceivable curves in the room. No lane, furniture or door state
    is changed to make the required inspection pass appear feasible.
    """
    import sample_transport_model as transport
    building=stack.load();interface=stack.interfaces(building,stack.parameters(building));lab=interface['laboratories'][0]
    lanes=transformed_l01_lanes(lab);vertices=lanes['vertices_mm']
    motion=json.loads((ROOT/'model/tr01-l01.motion.json').read_text());trim=motion['curve']['corner_trim_mm']
    vehicle=transport.load();p=transport.parameters(vehicle);variant=next(v for v in vehicle['variants']if v['id']=='Floor_T48')
    operations=transport.expanded(vehicle,p,variant)['operations'];by_id={op['id']:op for op in operations}
    chassis=by_id['ChassisBlank']['shape'];outer=by_id['CoverOuter']['shape'];inner=by_id['CoverInside']['shape']
    chassis_z=chassis['origin'][2]+chassis['size'][2]/2
    skin_low=inner['origin'][2]+inner['size'][2];skin_high=outer['origin'][2]+outer['size'][2]
    if skin_low>=skin_high:raise ValueError('No guaranteed top cover solid witness')
    skin_z=(skin_low+skin_high)/2
    level_z=next(l['z_mm']for l in mesh.manifest['levels']if l['id']==lab['level_id'])
    door=next(o for o in mesh.manifest['objects']if o.get('opening_id')=='D3_003B'and o['level_id']==lab['level_id'])
    if door['initial_state']!='open' or door['reference_state']!='open':raise ValueError('L01 rejection requires the recorded open native reference door')
    leaf=next(g for g in mesh.scene['groups']if g['id']=='OG3__DoorLeaf_D3_003B');bounds=mesh.bounds(leaf)
    front_centre=[sum(bounds[k][0]for k in ('min','max'))/2,vertices[0][1]]
    front_local=[0,0,chassis_z];front_point=front_centre+[level_z+chassis_z]
    front=closed_mesh_membership(mesh,leaf['id'],front_point)
    # Fixed witness selected on the untrimmed rear straight. Its local Y lies
    # inside the actual cover top skin (not the wider bumper envelope).
    rear_centre=[9000.,vertices[2][1]];rear_local=[0,-50.,skin_z]
    if not outer['origin'][1]<rear_local[1]<outer['origin'][1]+outer['size'][1]:raise ValueError('Cover witness outside actual source solid')
    rear_point=[rear_centre[0]+rear_local[0],rear_centre[1]+rear_local[1],level_z+rear_local[2]]
    rear=closed_mesh_membership(mesh,'Lab3003_WindowBenchRight_Worktop',rear_point)
    witnesses=[]
    for ident,centre,local,point,membership,ends,body in [
            ('front',front_centre,front_local,front_point,front,(vertices[0],vertices[1]),leaf['id']),
            ('rear',rear_centre,rear_local,rear_point,rear,(vertices[2],vertices[3]),'Lab3003_WindowBenchRight_Worktop')]:
        distances=[math.dist(centre,end)for end in ends]
        witnesses.append({'lane':ident,'vehicle_centre_xy_mm':centre,'vehicle_solid_point_local_mm':local,
                          'world_point_mm':point,'body_id':body,'membership':membership,
                          'distance_to_lane_endpoints_mm':distances,
                          'outside_existing_corner_blends':min(distances)>trim})
    blocked=all(w['membership']['inside']and w['outside_existing_corner_blends']for w in witnesses)
    return{'passed':False,'rejection_proven':blocked,'status':'blocked_existing_lane_graph'if blocked else'unproven_existing_lane_graph',
           'lane_vertices_mm':vertices,'bound_lane_values_mm':lanes['bound_values_mm'],
           'corner_trim_mm':trim,'witnesses':witnesses,
           'door_initial_state':door['initial_state'],'door_reference_state':door['reference_state'],
           'components_after_witness_cuts':[['left_front','left_rear'],['right_front','right_rear']]if blocked else None,
           'reason':'Front and rear connections of the prescribed L01 lane ring intersect actual native solids. Opposite door components cannot connect; a same-door return would require reversal, an in-place turn or a new off-centre loop.'if blocked else'No affirmative route proof is provided by this diagnostic.',
           'qualification':{'unconstrained_room_unreachability_claimed':False,'BRep_interference_executed':False,
                            'full_fleet_compiled':False,'clearance_inflation_used':False}}
