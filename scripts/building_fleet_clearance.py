"""Continuous BF01 planar mesh clearance and exact floor-union support.

The ordinary floor certificate uses an expanded oriented vehicle rectangle,
not a circumscribed disc or cell-centre support. All clipped floor coordinates
are exact rational representations of the transformed Float64 inputs; seams,
overlap and small holes are handled without an area-acceptance tolerance.
Dynamic cabin stages retain their separate native/service proof.
"""
from fractions import Fraction as Q
import bisect
import itertools
import json
import math
import building_fleet_navigation as nav
import building_fleet_model as model
import building_fleet_geometry as geometry
from building_fleet_l01 import _rectangle_distance
import tr01_floor_motion as floor


def signed_area(polygon):
    return sum(a[0]*b[1]-b[0]*a[1]for a,b in zip(polygon,polygon[1:]+polygon[:1]))/2


def _clip(poly,axis,bound,greater):
    if not poly:return []
    out=[];previous=poly[-1];pin=previous[axis]>=bound if greater else previous[axis]<=bound
    for current in poly:
        inside=current[axis]>=bound if greater else current[axis]<=bound
        if inside!=pin:
            u=(bound-previous[axis])/(current[axis]-previous[axis]);out.append(tuple(previous[k]+u*(current[k]-previous[k])for k in range(2)))
        if inside:out.append(current)
        previous,pin=current,inside
    return out


def _cross(a,b):return a[0]*b[1]-a[1]*b[0]


def _intersection_x(a,b,c,d):
    ab=(b[0]-a[0],b[1]-a[1]);cd=(d[0]-c[0],d[1]-c[1]);den=_cross(ab,cd)
    if not den:return None
    ac=(c[0]-a[0],c[1]-a[1]);u=_cross(ac,cd)/den;v=_cross(ac,ab)/den
    return a[0]+u*ab[0]if 0<=u<=1 and 0<=v<=1 else None


def _vertical(poly,x):
    ys=[]
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if a[0]!=b[0]and min(a[0],b[0])<x<max(a[0],b[0]):ys.append(a[1]+(x-a[0])*(b[1]-a[1])/(b[0]-a[0]))
    return (min(ys),max(ys))if ys else None


def _union_length(intervals):
    if not intervals:return Q(0)
    ordered=sorted(intervals);low,high=ordered[0];total=Q(0)
    for a,b in ordered[1:]:
        if a>high:total+=high-low;low,high=a,b
        else:high=max(high,b)
    return total+high-low


def floor_union_covers(triangles,centre,yaw,half_length,half_width):
    """Exact clipped-union area and coverage of one oriented rectangle.

    The x arrangement includes every clipped polygon vertex and every edge
    intersection. Between successive events all upper/lower edges retain their
    ordering; union length is affine. The mean of1/4 and3/4 strip samples is
    therefore its exact integral. No epsilon can erase a positive missing area.
    """
    values=[*centre,yaw,half_length,half_width]
    if any(type(v)not in (int,float)or not math.isfinite(v)for v in values)or half_length<=0 or half_width<=0:raise ValueError('Finite positive floor query rectangle required')
    c,s=math.cos(yaw),math.sin(yaw);L,W=Q(half_length),Q(half_width);polys=[]
    for triangle in triangles:
        if len(triangle)!=3:raise ValueError('Native floor triangle required')
        poly=[]
        for point in triangle:
            dx,dy=point[0]-centre[0],point[1]-centre[1];x,y=dx*c+dy*s,-dx*s+dy*c
            if not math.isfinite(x)or not math.isfinite(y):raise ValueError('Finite native floor coordinates required')
            poly.append((Q(x),Q(y)))
        for axis,bound,greater in [(0,-L,True),(0,L,False),(1,-W,True),(1,W,False)]:poly=_clip(poly,axis,bound,greater)
        if len(poly)>=3 and signed_area(poly)!=0:polys.append(poly)
    required=4*L*W
    if not polys:return {'passed':False,'covered_area_mm2':0.,'required_area_mm2':float(required),'missing_area_mm2':float(required),'strips':0,'method':'exact rational clipped triangle union'}
    xs={x for poly in polys for x,y in poly};edges=[(a,b)for poly in polys for a,b in zip(poly,poly[1:]+poly[:1])]
    for i,(a,b)in enumerate(edges):
        for c,d in edges[i+1:]:
            x=_intersection_x(a,b,c,d)
            if x is not None:xs.add(x)
    xs=sorted(xs|{-L,L});area=Q(0);strips=0
    for a,b in zip(xs,xs[1:]):
        if a==b:continue
        lengths=[]
        for x in ((3*a+b)/4,(a+3*b)/4):lengths.append(_union_length([span for poly in polys if(span:=_vertical(poly,x))is not None]))
        area+=(b-a)*(lengths[0]+lengths[1])/2;strips+=1
    missing=required-area
    if missing<0:raise ArithmeticError('Clipped floor union exceeds query area')
    return {'passed':missing==0,'covered_area_mm2':float(area),'required_area_mm2':float(required),'missing_area_mm2':float(missing),'strips':strips,'method':'exact rational clipped triangle union, all arrangement edge crossings; no area tolerance'}


class PolygonIndex:
    def __init__(self,polygons,cell_mm=1000):
        self.polygons=polygons;self.cell=cell_mm;self.cells={};self.large=[]
        for i,poly in enumerate(polygons):
            lo=[min(p[k]for p in poly)for k in range(2)];hi=[max(p[k]for p in poly)for k in range(2)];axes=[range(math.floor(lo[k]/cell_mm),math.floor(hi[k]/cell_mm)+1)for k in range(2)]
            if math.prod(map(len,axes))>10000:self.large.append(i)
            else:
                for key in itertools.product(*axes):self.cells.setdefault(key,[]).append(i)
    def query(self,lo,hi):
        ids=set(self.large)
        for x in range(math.floor(lo[0]/self.cell),math.floor(hi[0]/self.cell)+1):
            for y in range(math.floor(lo[1]/self.cell),math.floor(hi[1]/self.cell)+1):ids.update(self.cells.get((x,y),[]))
        return [self.polygons[i]for i in sorted(ids)]


def _extrema(curve,start,end):
    from types import SimpleNamespace
    first=max(0,bisect.bisect_right(curve.times,start)-1);last=min(len(curve.segments),bisect.bisect_left(curve.times,end)+1)
    return floor.extrema(SimpleNamespace(times=curve.times[first:last+1],segments=curve.segments[first:last]),start,end)


def _rectangle(centre,yaw,L,W):
    c,s=math.cos(yaw),math.sin(yaw)
    return [[centre[0]+c*x-s*y,centre[1]+s*x+c*y]for x,y in [(-L,-W),(L,-W),(L,W),(-L,W)]]


_TOPOLOGY_CACHE={}


class ClearanceCertificate:
    def __init__(self,mesh,level,config,extra_exclusions=(),benchareas_ifL01=True,lift_context=None):
        model.validate(config);self.mesh=mesh;self.level=level;self.config=config
        self.lift_context=lift_context
        if lift_context is not None:
            from building_fleet_lift_geometry import PortSupportContext
            if not isinstance(lift_context,PortSupportContext)or lift_context.level!=level or lift_context.source!=config:
                raise ValueError('A source-matched lift support context is required')
        from building_fleet_floor import floor_support
        self.floor_bank=floor_support(mesh,level,config)
        vehicle=geometry.vehicle_envelope();self.L=max(abs(vehicle['min'][0]),abs(vehicle['max'][0]));self.W=max(abs(vehicle['min'][1]),abs(vehicle['max'][1]));self.radius=math.hypot(self.L,self.W)
        sensor=model.resolved_sensor(config);self.reserve=sensor['clearance_mm']+config['geometry']['localization_tolerance_mm'];self.mesh_error=mesh.scene['linear_tessellation_deflection_mm']+math.sqrt(3)*mesh.scene['maximum_float32_error_mm']
        levels={v['id']:v for v in mesh.manifest['levels']}
        if level not in levels:raise ValueError('Known source floor required')
        z=levels[level]['z_mm'];self.floor_triangles=self.floor_bank.triangles;self.obstacles=[];self.obstacle_names=[]
        hidden=mesh.manifest.get('hidden_body_ids',{});hidden=set(hidden.get('building',[])if isinstance(hidden,dict)else hidden)
        dynamic=set(next(o for o in mesh.manifest['objects']if o['id']==mesh.manifest['elevator']['object_id'])['moving_body_ids'])
        for obj in mesh.manifest['objects']:
            if obj.get('mechanism')=='lift_door':dynamic.update(obj['moving_body_ids'])
        for group in mesh.scene['groups']:
            if group['id']in hidden or group['role']=='viewing_cone':continue
            bounds=mesh.bounds(group)
            support=group['role']=='concept_storey_slab'and abs(bounds['max'][2]-z)<.05
            if support:continue
            if group['id']in dynamic or group['role']in nav.DYNAMIC_ROLES:continue
            low=z+config['geometry']['floor_band_start_mm']-self.mesh_error;high=z+vehicle['height_mm']+config['geometry']['height_reserve_mm']+self.mesh_error
            if bounds['max'][2]<low or bounds['min'][2]>high:continue
            for triangle in mesh.triangles(group):
                poly=nav.clip_height(triangle,low,high)
                if poly:self.obstacles.append(poly);self.obstacle_names.append(group['id'])
        topo_key=json.dumps([config['sources']['building'],config['sources']['walkthrough'],config['exclusions']['KG_technical_areas']],sort_keys=True)
        if topo_key not in _TOPOLOGY_CACHE:_TOPOLOGY_CACHE[topo_key]=nav.topology(excluded_by_level={'KG':config['exclusions']['KG_technical_areas']})
        topo=_TOPOLOGY_CACHE[topo_key]
        entry=topo[level];plan=entry['plan'];scale=entry['display_scale']
        for area in plan['areas']:
            if area['id']in entry['excluded_areas']:
                if area['id']=='LiftCore'and lift_context is not None:continue
                self.obstacles.append([[v*scale for v in point]for point in nav.floor.area_points(plan,area)]);self.obstacle_names.append('ExcludedArea.'+area['id'])
        for exclusion in extra_exclusions:
            if not isinstance(exclusion,dict)or set(exclusion)!={'id','polygon_mm'}:raise ValueError('Extra exclusion needs id and polygon_mm')
            self.obstacles.append(exclusion['polygon_mm']);self.obstacle_names.append(exclusion['id'])
        if level=='OG3':
            if benchareas_ifL01 is not True:raise ValueError('Existing L01 bench protections cannot be disabled')
            import building_fleet_l01 as l01
            for work in l01.definition()['work_areas']:
                self.obstacles.append(work['world_polygon_mm']);self.obstacle_names.append('BenchSafety.'+work['id'])
        self.floor_index=PolygonIndex(self.floor_triangles);self.obstacle_index=PolygonIndex(self.obstacles)
        self.obstacle_ids={id(poly):i for i,poly in enumerate(self.obstacles)}
        # Membership alone is used to exclude an initial enclosed solid. Never
        # apply this grid's circumscribed-disc clearance to a narrow doorway.
        self.start_grid=nav.build_grid(mesh,level,vehicle['height_mm']+config['geometry']['height_reserve_mm'],config['geometry']['grid_step_mm'],topological=topo)

    def distance(self,xy,yaw):
        best=500.;name='distance_cap_lower_bound';extent=self.radius+best+self.mesh_error;lo=[v-extent for v in xy];hi=[v+extent for v in xy]
        for poly in self.obstacle_index.query(lo,hi):
            value=_rectangle_distance(poly,xy,yaw,self.L,self.W)
            if value<best:best,name=value,self.obstacle_names[self.obstacle_ids[id(poly)]]
            if best==0:break
        return best-self.mesh_error,name

    def support(self,xy,yaw,movement,*,start_s=None,end_s=None,curve_ref=None):
        L=self.L+self.reserve+self.mesh_error+movement;W=self.W+self.reserve+self.mesh_error+movement
        result=self.floor_bank.covers(xy,yaw,L,W,curve_ref=curve_ref)
        if self.lift_context is None:return result
        if start_s is None or end_s is None:raise ValueError('The compiled lift support interval is required')
        triangles,body_ids=self.floor_bank.selected(xy,yaw,L,W)
        return self.lift_context.support(xy,yaw,L,W,start_s=start_s,end_s=end_s,
            ordinary_triangles=triangles,ordinary_body_ids=body_ids,
            ordinary_result=result,curve_ref=curve_ref)

    def check(self,curve,max_depth=24):
        first=curve.evaluate(curve.times[0])[floor.F[0]];cell=self.start_grid.cell(first[:2])
        if self.lift_context is None and(cell is None or self.start_grid.blocked[cell]):return {'passed':False,'reason':'initial_pose_not_proven_outside_closed_projected_solids'}
        if self.lift_context is not None:
            # The semantic shaft mask may be removed only for an allocated
            # port stage. Keep an independent physical closed-solid test:
            # raster filling a hollow cabin would incorrectly block boarding.
            from building_fleet_lift_checks import posed_mesh
            actual=posed_mesh(self.mesh,self.lift_context.timeline.values(curve.times[0]))
            z=next(row['z_mm']for row in actual.manifest['levels']if row['id']==self.level)
            low=z+self.config['geometry']['floor_band_start_mm'];high=z+geometry.vehicle_envelope()['height_mm']
            for group in actual.scene['groups']:
                if group['role']=='viewing_cone':continue
                bounds=actual.bounds(group)
                if any(not bounds['min'][k]<=first[k]<=bounds['max'][k]for k in range(2)):continue
                a,b=max(low,bounds['min'][2]),min(high,bounds['max'][2])
                if b<=a:continue
                membership=nav.closed_mesh_membership(actual,group['id'],[*first[:2],(a+b)/2])
                if membership['inside']or membership['boundary']:
                    return {'passed':False,'reason':'initial_pose_inside_or_on_closed_native_solid',
                            'body_id':group['id'],'membership':membership}
        accepted=[];evaluations=0;applications=[];queue=[(a,b,0)for a,b in zip(curve.times,curve.times[1:])]
        while queue:
            start,end,depth=queue.pop();mid=(start+end)/2;pose=curve.evaluate(mid)[floor.F[0]];bounds=_extrema(curve,start,end)
            translation=math.hypot(*[max(abs(bounds[k][i]-pose[i])for k in ('min','max'))for i in range(2)]);turn=max(abs(bounds[k][2]-pose[2])for k in ('min','max'));movement=math.nextafter(translation+self.radius*turn,math.inf)
            distance,body=self.distance(pose[:2],pose[2]);lower=math.nextafter(distance-movement,-math.inf);evaluations+=1
            if distance<self.reserve:return {'passed':False,'reason':'midpoint_mesh_or_exclusion_clearance','time_s':[start,end],'midpoint_pose_mm_rad':pose,'midpoint_clearance_mm':distance,'limiting_body':body,'evaluations':evaluations}
            # An impossible static midpoint cannot be repaired by splitting;
            # a larger interval-support failure may be a conservative envelope.
            def floor_at(inflation,left,right):
                try:return self.support(pose[:2],pose[2],inflation,start_s=left,end_s=right,
                    curve_ref={'level':self.level,'time_s':[left,right]})
                except ValueError as exc:return {'passed':False,'reason':str(exc),'lift_gate_failed':True}
            support=floor_at(movement,start,end)if lower>=self.reserve else None
            if lower>=self.reserve and support['passed']:
                applications.extend(support.get('applications',[]))
                accepted.append({'time_s':[start,end],'clearance_lower_mm':lower,'limiting_body':body,'floor_support':True,'support_rule_applied':support.get('rule_applied',False),'height_exception_applied':support.get('lift_height_exception_applied',False),'depth':depth});continue
            if depth>=max_depth:return {'passed':False,'reason':'interval_clearance_or_exact_floor_union_unresolved','time_s':[start,end],'midpoint_pose_mm_rad':pose,'interval_clearance_lower_mm':lower,'floor_union':support,'limiting_body':body,'evaluations':evaluations}
            if support is not None and not floor_at(0,mid,mid)['passed']:return {'passed':False,'reason':'midpoint_expanded_oriented_rectangle_lacks_floor_union','time_s':[start,end],'midpoint_pose_mm_rad':pose,'floor_union':floor_at(0,mid,mid),'evaluations':evaluations}
            queue.extend([(start,mid,depth+1),(mid,end,depth+1)])
        return {'passed':True,'minimum_interval_clearance_lower_mm':min(v['clearance_lower_mm']for v in accepted),'intervals':accepted,'evaluations':evaluations,'minimum_clearance_mm':self.reserve,'mesh_reserve_mm':self.mesh_error,'support_applications':applications,'lift_support':self.lift_context.report()if self.lift_context else None,'floor_support_method':'canonical exact native union plus conservative owner disk closing; full expanded oriented rectangle and source-gated lift-only raised surfaces','qualification':{'native_BRep_curve_checked':False,'dynamic_lift_checked':False,'bench_zones_changed':False},'scope':'Continuous actual PVA x/y/yaw projected-surface and excluded-area clearance plus whole-rectangle floor-union coverage; static enclosed-body start membership checked. Independent native BRep and lift-stage proofs remain required.'}


_CACHE={}
def check_motion(mesh,curve,level,config,extra_exclusions=(),benchareas_ifL01=True,lift_context=None):
    model.validate(config)
    bench_revision=''
    if level=='OG3':
        import building_fleet_l01 as l01
        l01.load();bench_revision=model.digest(l01.SOURCE)
    key=(id(mesh),level,bench_revision,json.dumps(config,sort_keys=True,allow_nan=False),json.dumps(extra_exclusions,sort_keys=True,allow_nan=False),benchareas_ifL01,id(lift_context))
    if key not in _CACHE:_CACHE[key]=ClearanceCertificate(mesh,level,config,extra_exclusions,benchareas_ifL01,lift_context)
    return _CACHE[key].check(curve)
