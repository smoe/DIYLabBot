"""Separately selected BF01 L01 connector; shared lanes and bench zones unchanged.

The new cross-aisle is derived from the open exit leaf and the actual bound
island front. Existing work-area coordinates are rigidly bound without scale;
none is resized, silently reinterpreted, released or used for docking.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import building_fleet_model as contract
import building_fleet_navigation as navigation
import building_stack as stack
import robot_spec as robot
from cf01_unload_path import CornerPath

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'model/building-fleet-l01-route.shared.json'
SCHEMA=ROOT/'model/building-fleet-l01-route.schema.json'


def load(path=SOURCE):
    s=contract.read_json(path);contract.validate_shape(s,contract.read_json(SCHEMA))
    for ref in s['sources'].values():contract.resolve_pin(ref)
    return s


def _point(matrix,point):
    return[sum(matrix[k][j]*point[j]for j in range(3))+matrix[k][3]for k in range(3)]


def definition(source=None):
    source=load()if source is None else copy.deepcopy(source)
    contract.validate_shape(source,contract.read_json(SCHEMA))
    for ref in source['sources'].values():contract.resolve_pin(ref)
    building=stack.load(ROOT/source['sources']['building']['path']);p=stack.parameters(building)
    interface=stack.interfaces(building,p);lab=next(l for l in interface['laboratories']if l['id']==source['host']['laboratory'])
    expanded=stack.expanded(building,p);ops={o['body']:o for o in expanded['operations']if o['action']=='create'}
    inverse=robot.inverse(lab['transform']);context=lab['evaluated_parameters_mm']
    motion=contract.read_json(ROOT/source['sources']['motion']['path'])
    lanes={k:robot.evaluate(v,context)for k,v in motion['traffic_policy']['lane_centres_mm'].items()}
    workcell=contract.read_json(ROOT/source['sources']['work_areas']['path'])
    work_areas=[]
    for key,item in workcell['work_areas'].items():
        xmin,xmax,ymin,ymax=item['bounds_xy_mm'];local=[[xmin,ymin],[xmax,ymin],[xmax,ymax],[xmin,ymax]]
        if not(0<=xmin<xmax<=context['room_width']and 0<=ymin<ymax<=max(context['left_depth'],context['right_depth'])):
            raise ValueError('Existing work area lies outside bound room; no silent rescaling: '+key)
        work_areas.append({'id':key,'source_bounds_xy_mm':list(item['bounds_xy_mm']),
                           'local_polygon_mm':local,'world_polygon_mm':[_point(lab['transform'],v+[0])[:2]for v in local],
                           'state':'occupied_or_unknown','scale':1})
    portals={}
    for ident in(source['route']['entry_opening'],source['route']['exit_opening']):
        binding=interface['exterior']['door_bindings'][lab['level_id']+'__'+ident]
        shape=ops[binding['leaf_body_id']]['shape']
        if shape['kind']!='polygon_prism' or shape['plane']!='XY':raise ValueError('Source open native door footprint required')
        points=[_point(inverse,xy+[shape['offset']])[:2]for xy in shape['points']]
        portals[ident]={'body_id':binding['leaf_body_id'],'open_leaf_local_polygon_mm':points,
                        'width_mm':binding['width_mm']}
    exit_leaf=portals[source['route']['exit_opening']]['open_leaf_local_polygon_mm']
    leaf_tip=max(xy[1]for xy in exit_leaf);island_front=context['island_start_y'];mid=(leaf_tip+island_front)/2
    # Reuse the fleet's independently lowered physical camera/vehicle envelope;
    # viewing cones and negative cuts never enlarge that envelope.
    from building_fleet_geometry import vehicle_envelope
    import tr01_camera_model as camera
    envelope=vehicle_envelope(camera.expanded(camera.load(ROOT/source['sources']['camera_vehicle']['path'])))
    vehicle_half_length=max(abs(envelope['min'][0]),abs(envelope['max'][0]))
    fleet=contract.load();sensor=contract.read_json(ROOT/fleet['sources']['sensor']['path'])
    reserve=sensor['controller']['clearance_mm']+fleet['geometry']['localization_tolerance_mm']
    half_width=max(abs(envelope['min'][1]),abs(envelope['max'][1]))
    if island_front-leaf_tip<2*(half_width+reserve):raise ValueError('BF01 connector strip too narrow; bench/door unchanged')
    # The native door plane is the bound inner-wall origin minus half thickness.
    outside=-context['wall_t']/2-(vehicle_half_length+reserve+context['wall_t'])
    local=[[lanes[source['route']['entry_lane']],outside],
           [lanes[source['route']['entry_lane']],mid],
           [lanes[source['route']['exit_lane']],mid],
           [lanes[source['route']['exit_lane']],outside]]
    world=[_point(lab['transform'],xy+[0])for xy in local]
    return{'format':'solidcraftbot.building-fleet-l01-geometry/1','source':source,'host':source['host'],
            'transform':lab['transform'],'local_points_xy_mm':local,'world_points_xyz_mm':world,
            'bound_lane_values_mm':lanes,'open_exit_leaf_tip_y_mm':leaf_tip,'island_front_y_mm':island_front,
            'strip_width_mm':island_front-leaf_tip,'strip_residual_after_reserve_mm':island_front-leaf_tip-2*(half_width+reserve),
            'corner_trim_mm':motion['curve']['corner_trim_mm'],'portals':portals,'work_areas':work_areas,
            'grid_step_mm':fleet['geometry']['grid_step_mm'],
            'vehicle':{'half_length_mm':vehicle_half_length,'half_width_mm':half_width,'reserve_mm':reserve,
                       'height_mm':envelope['height_mm']+fleet['geometry']['height_reserve_mm'],
                       'floor_band_start_mm':fleet['geometry']['floor_band_start_mm']},
            'scope':'Geometry proposal until continuous clearance and independent native exported-curve checks pass'}


def pieces(definition_):
    xy=[v[:2]+[0.]for v in definition_['world_points_xyz_mm']];output=[];cursor=xy[0]
    for i,corner in enumerate(xy[1:-1],1):
        trim=min(definition_['corner_trim_mm'],math.dist(xy[i-1],corner)*.25,math.dist(corner,xy[i+1])*.25)
        blend=CornerPath(xy[i-1],corner,xy[i+1],0.,0.,trim)
        if math.dist(cursor,blend.controls[0])>1e-8:output.append([cursor,blend.controls[0]])
        output.append(blend.controls);cursor=blend.controls[-1]
    output.append([cursor,xy[-1]])
    return output


def _split(controls):
    rows=[copy.deepcopy(controls)]
    while len(rows[-1])>1:rows.append([[(a+b)/2 for a,b in zip(x,y)]for x,y in zip(rows[-1],rows[-1][1:])])
    return[row[0]for row in rows],[row[-1]for row in reversed(rows)]


def _point_segment(p,a,b):
    v=[b[k]-a[k]for k in range(2)];n=sum(x*x for x in v)
    u=max(0.,min(1.,sum((p[k]-a[k])*v[k]for k in range(2))/n))if n else 0.
    return math.hypot(*(p[k]-a[k]-u*v[k]for k in range(2)))


def _rectangle_distance(polygon,centre,yaw,half_length,half_width):
    c,s=math.cos(yaw),math.sin(yaw)
    points=[[(p[0]-centre[0])*c+(p[1]-centre[1])*s,
             -(p[0]-centre[0])*s+(p[1]-centre[1])*c]for p in polygon]
    if navigation.polygon_touches_box(points,-half_length,-half_width,half_length,half_width):return 0.
    rectangle=[[-half_length,-half_width],[half_length,-half_width],[half_length,half_width],[-half_length,half_width]]
    # Both vertex-to-opposite-edge directions are required for the exact planar
    # polygon distance. SAT above has already rejected crossing edges.
    return min([_point_segment(p,a,b)for p in points for a,b in zip(rectangle,rectangle[1:]+rectangle[:1])]+
               [_point_segment(p,a,b)for p in rectangle for a,b in zip(points,points[1:]+points[:1])])


class ClearanceCertificate:
    """Continuous mesh/bench clearance with convex Bezier interval hulls.

    Every accepted interval has a midpoint polygon distance minus a bound for
    translation and orientation change. The bound uses all control points and
    the tangent cone of the derivative Bezier curve. Failure never qualifies a
    route by merely increasing sample density.
    """
    def __init__(self,mesh,definition_):
        self.mesh=mesh;self.definition=definition_;v=definition_['vehicle']
        self.half_length=v['half_length_mm'];self.half_width=v['half_width_mm']
        self.radius=math.hypot(self.half_length,self.half_width)
        self.reserve=v['reserve_mm'];self.mesh_error=math.sqrt(3)*mesh.scene['maximum_float32_error_mm']+mesh.scene['linear_tessellation_deflection_mm']
        xyz=definition_['world_points_xyz_mm'];z=xyz[0][2]
        lo=[min(p[k]for p in xyz)-2*self.radius-self.reserve for k in range(2)]
        hi=[max(p[k]for p in xyz)+2*self.radius+self.reserve for k in range(2)]
        self.polygons=[];self.body_ids=set();self.floor_grid=navigation.ClearanceGrid(mesh.scene['bounds_mm'],definition_.get('grid_step_mm',50))
        for group in mesh.scene['groups']:
            bounds=mesh.bounds(group)
            floor=group['role']=='concept_storey_slab'and abs(bounds['max'][2]-z)<.05
            if floor:
                for tri in mesh.triangles(group):
                    if all(abs(p[2]-z)<.05 for p in tri):self.floor_grid.raster([p[:2]for p in tri],True)
                continue
            if group['role']in navigation.DYNAMIC_ROLES:continue
            if bounds['max'][2]<z+v.get('floor_band_start_mm',20)-self.mesh_error or bounds['min'][2]>z+v['height_mm']+self.mesh_error:continue
            if any(bounds['max'][k]<lo[k]or bounds['min'][k]>hi[k]for k in range(2)):continue
            for tri in mesh.triangles(group):
                poly=navigation.clip_height(tri,z+v.get('floor_band_start_mm',20)-self.mesh_error,z+v['height_mm']+self.mesh_error)
                if poly:
                    self.polygons.append((group['id'],poly,[min(p[k]for p in poly)for k in range(2)],[max(p[k]for p in poly)for k in range(2)]));self.body_ids.add(group['id'])
        for area in definition_['work_areas']:
            poly=area['world_polygon_mm'];self.polygons.append(('BenchSafety.'+area['id'],poly,[min(p[k]for p in poly)for k in range(2)],[max(p[k]for p in poly)for k in range(2)]))
        self.floor_grid.finalize()

    def distance(self,xy,yaw):
        best=500.;body='distance_cap_lower_bound'
        for ident,polygon,lo,hi in self.polygons:
            # Disc-to-box lower bound is valid for every oriented rectangle.
            boxdistance=math.hypot(*[max(lo[k]-xy[k],0.,xy[k]-hi[k])for k in range(2)])-self.radius
            if boxdistance>=best:continue
            value=_rectangle_distance(polygon,xy,yaw,self.half_length,self.half_width)
            if value<best:best,body=value,ident
            if best<=0:break
        floor=self.floor_grid.clearance_lower_mm(xy)-self.radius
        if floor<best:return max(0.,floor)-self.mesh_error,'NativeFloorSupport'
        return best-self.mesh_error,body

    def check(self,controls,max_depth=22):
        accepted=[];stack_=[(controls,0,0.,1.)];evaluations=0
        while stack_:
            part,depth,start,end=stack_.pop();mid=CornerPath._bezier(part,.5)
            deriv=[[len(part[:-1])*(b-a)for a,b in zip(x,y)]for x,y in zip(part,part[1:])]
            velocity=CornerPath._bezier(deriv,.5)
            if math.hypot(*velocity[:2])<1e-10:raise ValueError('Connector contains a translational stop/cusp')
            yaw=math.atan2(velocity[1],velocity[0])
            angles=[math.atan2(math.sin(math.atan2(v[1],v[0])-yaw),math.cos(math.atan2(v[1],v[0])-yaw))for v in deriv if math.hypot(*v[:2])>1e-12]
            cone=max(abs(a)for a in angles)
            # Tangents remain in this cone when it spans less than pi. A wider
            # cone must be subdivided before making an orientation claim.
            translation=max(math.dist(mid[:2],point[:2])for point in part)
            movement=translation+self.radius*cone
            distance,body=self.distance(mid[:2],yaw);evaluations+=1
            lower=distance-movement
            if cone<math.pi/2 and lower>=self.reserve:
                accepted.append({'u':[start,end],'clearance_lower_mm':lower,'limiting_body':body,'depth':depth});continue
            if distance<self.reserve or depth>=max_depth:
                return{'passed':False,'reason':'continuous_clearance_not_proven','u':[start,end],
                       'midpoint_mm_rad':mid[:2]+[yaw],'midpoint_clearance_mm':distance,
                       'interval_clearance_lower_mm':lower,'limiting_body':body,'depth':depth,'evaluations':evaluations}
            left,right=_split(part);half=(start+end)/2
            stack_.extend([(right,depth+1,half,end),(left,depth+1,start,half)])
        return{'passed':True,'minimum_interval_clearance_lower_mm':min(a['clearance_lower_mm']for a in accepted),
                'intervals':accepted,'evaluations':evaluations,'mesh_float_and_tessellation_reserve_mm':self.mesh_error,
                'body_count':len(self.body_ids),'polygon_count':len(self.polygons),
                'scope':'Native mesh projected-height and unchanged bench-zone interval certificate; native 3D exported-curve proof separate'}


def check_geometry(mesh,definition_=None):
    definition_=definition()if definition_ is None else definition_
    checker=ClearanceCertificate(mesh,definition_);results=[checker.check(p)for p in pieces(definition_)]
    return{'passed':all(r['passed']for r in results),'pieces':results,'definition':definition_,
           'qualification':{'native_BRep_curve_checked':False,'motion_limits_checked':False,'bench_zones_changed':False}}


def check_exported_motion(mesh,curve,definition_=None,max_depth=24):
    """Certificate for the actual exported x/y/yaw polynomial, not its source path.

    Translation and yaw bounds include polynomial extrema between nodes. The
    caller must additionally check dynamics/no-stop and quantized output using
    the existing motion mathematics; this function checks geometry only.
    """
    import tr01_floor_motion as floor
    definition_=definition()if definition_ is None else definition_
    checker=ClearanceCertificate(mesh,definition_);accepted=[];evaluations=0
    stack_=[(a,b,0)for a,b in zip(curve.times,curve.times[1:])]
    while stack_:
        start,end,depth=stack_.pop();mid=(start+end)/2;pose=curve.evaluate(mid)[floor.F[0]]
        bounds=floor.extrema(curve,start,end,0)
        shift=math.hypot(*[max(abs(bounds['min'][k]-pose[k]),abs(bounds['max'][k]-pose[k]))for k in range(2)])
        turn=max(abs(bounds['min'][2]-pose[2]),abs(bounds['max'][2]-pose[2]))
        distance,body=checker.distance(pose[:2],pose[2]);lower=distance-shift-checker.radius*turn;evaluations+=1
        if lower>=checker.reserve:
            accepted.append({'time_s':[start,end],'clearance_lower_mm':lower,'limiting_body':body,'depth':depth});continue
        if distance<checker.reserve or depth>=max_depth:
            return{'passed':False,'time_s':[start,end],'midpoint_pose_mm_rad':pose,
                    'midpoint_clearance_mm':distance,'interval_clearance_lower_mm':lower,
                    'limiting_body':body,'depth':depth,'evaluations':evaluations}
        stack_.extend([(start,mid,depth+1),(mid,end,depth+1)])
    return{'passed':True,'minimum_interval_clearance_lower_mm':min(a['clearance_lower_mm']for a in accepted),
            'intervals':accepted,'evaluations':evaluations,
            'mesh_float_and_tessellation_reserve_mm':checker.mesh_error,
            'scope':'Actual exported polynomial including yaw and all between-node extrema; independent native3D audit separate'}
