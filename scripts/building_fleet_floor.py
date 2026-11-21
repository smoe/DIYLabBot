"""Source ordinary floors and the single BF01 support-rule query boundary.

Lift-only raised support is provided by a separately gated source context.
Native triangles stay immutable; no raster dilation is treated as floor proof.
"""
import collections
from fractions import Fraction as Q
import math

import building_fleet_model as model
import building_fleet_support as rule


class FloorSupport:
    def __init__(self,mesh,level,config):
        self.mesh=mesh;self.level=level;self.config=config
        settings=model.support_settings(config)
        self.gap=settings['gap']['maximum'];self.padding=rule.query_padding_mm(self.gap)
        levels={row['id']:row for row in mesh.manifest['levels']}
        if level not in levels:raise ValueError('A current source floor level is required')
        self.z=levels[level]['z_mm'];self.triangles=[];self.body_ids=[]
        # Only source floor slabs at their declared floor height are ordinary
        # support. The source lift finish/sills require their own FK/door gate.
        error=mesh.scene['maximum_float32_error_mm']
        self.height_tolerance=max(math.ulp(float(self.z))*4,error)
        by_body=collections.defaultdict(list)
        for group in mesh.scene['groups']:
            if group['role']!='concept_storey_slab':continue
            bounds=mesh.bounds(group)
            if abs(bounds['max'][2]-self.z)>self.height_tolerance:continue
            for triangle in mesh.triangles(group):
                if all(abs(p[2]-self.z)<=self.height_tolerance for p in triangle):
                    points=[p[:2]for p in triangle]
                    if rule._area([tuple(Q(v)for v in p)for p in points])==0:continue
                    self.triangles.append(points);self.body_ids.append(group['id'])
                    by_body[group['id']].append(rule._ccw([tuple(Q(v)for v in p)for p in points]))
        from building_fleet_clearance import PolygonIndex
        self.index=PolygonIndex(self.triangles)
        self.ids={id(poly):name for poly,name in zip(self.triangles,self.body_ids)}
        self.cells=[];self.cell_bodies={}
        original=[]
        for name,triangles in by_body.items():
            for polygon in rule._merge_convex_cells(triangles):
                original.append((polygon,name))
        # Exact convex merging across shared native slab seams changes no
        # floor area. Keep each contributing body identity on the merged cell.
        self.cells=rule._merge_convex_cells([poly for poly,_ in original])
        for polygon in self.cells:
            self.cell_bodies[id(polygon)]=sorted({name for poly,name in original
                if all(rule._cross((b[0]-a[0],b[1]-a[1]),(p[0]-a[0],p[1]-a[1]))>=0
                    for a,b in zip(polygon,polygon[1:]+polygon[:1])for p in poly)})
        self.cell_index=PolygonIndex(self.cells)
        self.applications=[]

    @staticmethod
    def query_polygon(centre,yaw,L,W):
        return rule.rectangle_query(centre,yaw,L,W)

    def selected(self,centre,yaw,L,W):
        polygon=self.query_polygon(centre,yaw,L,W)
        lo=[float(min(p[k]for p in polygon))-self.padding for k in range(2)]
        hi=[float(max(p[k]for p in polygon))+self.padding for k in range(2)]
        triangles=self.index.query(lo,hi)
        return triangles,[self.ids[id(p)]for p in triangles]

    def covers(self,centre,yaw,L,W,*,curve_ref=None):
        query=self.query_polygon(centre,yaw,L,W)
        lo=[float(min(p[k]for p in query))for k in range(2)];hi=[float(max(p[k]for p in query))for k in range(2)]
        candidates=self.cell_index.query(lo,hi)
        for polygon in candidates:
            if all(rule._cross((b[0]-a[0],b[1]-a[1]),(p[0]-a[0],p[1]-a[1]))>=0
                   for a,b in zip(polygon,polygon[1:]+polygon[:1])for p in query):
                area=float(rule._area(query))
                return {'passed':True,'rule_applied':False,'applications':[],'max_gap_mm':self.gap,
                        'covered_area_mm2':area,'required_area_mm2':area,'missing_area_mm2':0.,
                        'source_body_ids':self.cell_bodies[id(polygon)],
                        'method':'Exact rational oriented rectangle contained in an unchanged convex native floor cell'}
        strict=rule.polygon_union_covers(candidates,query,_convex_inputs=True)
        if strict['passed']:
            return {**strict,'rule_applied':False,'applications':[],'max_gap_mm':self.gap,
                    'source_body_ids':sorted({name for p in candidates for name in self.cell_bodies[id(p)]})}
        triangles,identities=self.selected(centre,yaw,L,W)
        result=rule.support_covers(triangles,centre,yaw,L,W,self.gap,body_ids=identities,curve_ref=curve_ref)
        if result.get('rule_applied'):self.applications.extend(result['applications'])
        return result

    def line(self,start,end,radius_mm,*,curve_ref=None):
        length=math.dist(start,end)
        yaw=math.atan2(end[1]-start[1],end[0]-start[0])if length else 0.
        return self.covers([(a+b)/2 for a,b in zip(start,end)],yaw,length/2+radius_mm,radius_mm,curve_ref=curve_ref)


_CACHE={}
def floor_support(mesh,level,config):
    # A compile keeps the checked source and mesh immutable. New source bytes
    # or support policy create a different bank; source pins are rechecked at
    # public compile/check boundaries rather than rehashing every raster edge.
    key=(id(mesh),level,model.digest(model.SOURCE),model.digest(model.SCHEMA))
    if key not in _CACHE:_CACHE[key]=FloorSupport(mesh,level,config)
    return _CACHE[key]
