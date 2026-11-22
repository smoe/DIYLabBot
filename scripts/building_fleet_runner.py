"""BF01 seeded world runner and its immutable static route graph.

Mission planning sees the source map and the vehicle's own task/localization.
Simultaneous vehicle truth is confined to the runner/sensor/auditor boundary.
"""
import bisect
import copy
import math
import heapq
import json
import gzip
import hashlib
import time
from functools import lru_cache
from pathlib import Path as FilePath
from types import SimpleNamespace

import building_fleet_model as model
import building_fleet_navigation as navigation_model
import building_fleet_sim as world_model
import building_fleet_services as service_model
import building_fleet_comm as communication
from building_fleet_dispatch import Dispatcher
from building_fleet_motion import Path,compile_motion
from building_fleet_control import Controller
from building_fleet_depot import FixedHomeMap,check_invariant,exact_home_rest,fixed_home_curve_proof
import tr01_floor_motion as floor


def _projection(point,a,b):
    delta=[b[k]-a[k]for k in range(2)];length=sum(v*v for v in delta)
    u=sum((point[k]-a[k])*delta[k]for k in range(2))/length if length else 0
    projected=[a[k]+u*delta[k]for k in range(2)]
    return u,math.dist(point,projected)


def intersections(a,b,c,d):
    """Closed segment intersections, including endpoints of collinear overlap."""
    first=[b[k]-a[k]for k in range(2)];second=[d[k]-c[k]for k in range(2)]
    cross=first[0]*second[1]-first[1]*second[0];delta=[c[k]-a[k]for k in range(2)]
    if abs(cross)>1e-10:
        u=(delta[0]*second[1]-delta[1]*second[0])/cross
        v=(delta[0]*first[1]-delta[1]*first[0])/cross
        return [(u,v,[a[k]+u*first[k]for k in range(2)])]if-1e-9<=u<=1+1e-9 and-1e-9<=v<=1+1e-9 else[]
    if abs(delta[0]*first[1]-delta[1]*first[0])>1e-7:return[]
    result=[]
    for point in(a,b,c,d):
        u,gap1=_projection(point,a,b);v,gap2=_projection(point,c,d)
        if gap1<1e-7 and gap2<1e-7 and-1e-9<=u<=1+1e-9 and-1e-9<=v<=1+1e-9:
            result.append((max(0,min(1,u)),max(0,min(1,v)),list(point)))
    return result


def splice_hub_paths_with_junction(first,second):
    """Join A→hub and B→hub at their shortest shared static intersection.

    Every returned straight segment is a subsegment of a checked base route.
    No new shortcut across rooms, stairs or unsupported space is introduced.
    The resulting new C2 junction still requires the motion/native checks.
    """
    if len(first)<2 or len(second)<2 or math.dist(first[-1],second[-1])>1e-7:
        raise ValueError('Two complete static paths to the same hub required')
    times1=[0.];times2=[0.]
    for a,b in zip(first,first[1:]):times1.append(times1[-1]+math.dist(a,b))
    for a,b in zip(second,second[1:]):times2.append(times2[-1]+math.dist(a,b))
    best=None
    for i,(a,b)in enumerate(zip(first,first[1:])):
        for j,(c,d)in enumerate(zip(second,second[1:])):
            for u,v,point in intersections(a,b,c,d):
                score=times1[i]+u*math.dist(a,b)+times2[j]+v*math.dist(c,d)
                candidate=(score,i,j,u,v,point)
                if best is None or candidate[:5]<best[:5]:best=candidate
    if best is None:raise ValueError('Static base paths have no common source connection')
    _,i,j,_,_,point=best
    result=[]
    for row in [*first[:i+1],point]:
        if not result or math.dist(result[-1],row)>1e-7:result.append(list(row))
    junction=len(result)-1
    for row in reversed(second[:j+1]):
        if math.dist(result[-1],row)>1e-7:result.append(list(row))
    return result,junction


def splice_hub_paths(first,second):
    return splice_hub_paths_with_junction(first,second)[0]


def local_shortcut_neighbourhood(a,b,c,radius):
    """Bound a replacement centreline inside the existing local path guard."""
    def visit(left,right,depth=0):
        middle=[(x+y)/2 for x,y in zip(left,right)]
        distance=min(world_model.point_segment_distance(middle,a,b),world_model.point_segment_distance(middle,b,c))
        if distance+math.dist(left,right)/2<=radius:return True
        if distance>radius or depth>=20:return False
        return visit(left,middle,depth+1)and visit(middle,right,depth+1)
    return visit(a,c)


class RouteGraph:
    """Immutable base corridors, built before any vehicle or service runs."""
    def __init__(self,navigation,progress=None):
        self.navigation=navigation;self.progress=progress
        self.hubs=copy.deepcopy(navigation.road_hubs)if hasattr(navigation,'road_hubs')else{level:list(rows[0][:2])for level,rows in navigation.waits.items()}
        self.endpoints={level:{tuple(hub)}for level,hub in self.hubs.items()};self.sealed=False;self.centreline={}
        self.repairs={};self._bench_polygons={}

    def add_endpoint(self,level,point):
        if self.sealed:raise ValueError('No route/catalog expansion during a fleet run')
        if level not in self.endpoints or len(point)!=2 or not all(math.isfinite(v)for v in point):raise ValueError('Finite own source-map endpoint required')
        self.endpoints[level].add(tuple(point))

    def prepare(self):
        if self.sealed:raise ValueError('Static route graph already sealed')
        for home in self.navigation.homes.values():
            self.add_endpoint(home['level'],home['departure_xy_mm']);self.add_endpoint(home['level'],home['arrival_xy_mm'])
        for (level,_),inspection in self.navigation.inspections.items():
            self.add_endpoint(level,inspection['points_mm'][0]);self.add_endpoint(level,inspection['points_mm'][-1])
        total=sum(len(points)-1 for points in self.endpoints.values());done=0
        for level,endpoints in self.endpoints.items():
            hub=self.hubs[level]
            for point in sorted(endpoints):
                if math.dist(point,hub)<1e-7:continue
                if self.progress is not None:self.progress({'phase':'static_endpoint','level':level,'point_mm':list(point),'done':done,'total':total})
                self.navigation.route(level,point,hub);done+=1
                key=(level,tuple(point),tuple(hub))
                # Store the source-bound centreline; reversed right lanes would
                # put opposing traffic on the wrong side.
                self.centreline[key]=copy.deepcopy(self.navigation._route_cache[key])
        self.prepare_repairs()
        self.sealed=True
        return self

    def bench_polygons(self,level):
        if level not in self._bench_polygons:
            if level=='OG3':
                import building_fleet_l01 as l01
                self._bench_polygons[level]=[row['world_polygon_mm']for row in l01.definition()['work_areas']]
            else:self._bench_polygons[level]=[]
        return self._bench_polygons[level]

    def shortcut_clear(self,level,a,c):
        """Native swept rectangle/floor and explicit canonical bench masks."""
        nav=self.navigation
        if nav._straight_hits(level,a,c):return False
        yaw=math.atan2(c[1]-a[1],c[0]-a[0]);co,si=math.cos(yaw),math.sin(yaw)
        mesh_error=(nav.mesh.scene['linear_tessellation_deflection_mm']+
                    math.sqrt(3)*nav.mesh.scene['maximum_float32_error_mm'])
        L=nav.envelope['length_mm']/2+nav.reserve+mesh_error;W=nav.envelope['width_mm']/2+nav.reserve+mesh_error
        for polygon in self.bench_polygons(level):
            local=[[(p[0]-a[0])*co+(p[1]-a[1])*si,-(p[0]-a[0])*si+(p[1]-a[1])*co]for p in polygon]
            if navigation_model.polygon_touches_box(local,-L,-W,math.dist(a,c)+L,W):return False
        return True

    def prepare_repairs(self):
        """Register local shared-splice repairs before the resource catalog seals.

        Only the new shared-intersection vertex may be removed. Source graph
        endpoints and all external private approach/exit segments stay intact.
        Runtime never creates or registers an additional connection.
        """
        if self.sealed:raise ValueError('Splice connections must precede static resource catalog closure')
        for level,endpoints in self.endpoints.items():
            hub=tuple(self.hubs[level]);ends=sorted(p for p in endpoints if p!=hub)
            for start in ends:
                for end in ends:
                    if start==end:continue
                    points,index=splice_hub_paths_with_junction(self.centreline[level,start,hub]['points_mm'],self.centreline[level,end,hub]['points_mm'])
                    # Preserve the public initial heading interface as well as
                    # endpoints; the final external private segment is added
                    # by the own mission composer, outside this graph.
                    if not 1<index<len(points)-1:continue
                    a,b,c=points[index-1:index+2]
                    incoming=[b[k]-a[k]for k in range(2)];outgoing=[c[k]-b[k]for k in range(2)]
                    if sum(x*y for x,y in zip(incoming,outgoing))>=0:continue
                    nav=self.navigation
                    if not local_shortcut_neighbourhood(a,b,c,nav.radius+nav.reserve):continue
                    if not self.shortcut_clear(level,a,c):continue
                    repaired=points[:index]+points[index+1:]
                    key=hashlib.sha256(json.dumps([level,a,b,c],separators=(',',':')).encode()).hexdigest()[:16]
                    raw={'level':level,'points_mm':repaired,'resources':[{'id':level+'.splice.'+key,'kind':'passage',
                        'start_index':index-1,'end_index':index}], 'zone_segments':[],'portal_certificates':[],
                        'curve_qualified':False,'search':'Source-certified local obtuse shared-splice visibility repair',
                        'splice_repair':{'removed_shared_vertex_mm':copy.deepcopy(b),'shortcut_mm':[copy.deepcopy(a),copy.deepcopy(c)],
                            'initial_public_segment_preserved':True,'graph_endpoints_preserved':True,
                            'canonical_bench_masks_checked':True,'native_C2_curve_checked':False}}
                    try:route=nav._own_right(raw)
                    except ValueError:continue
                    if any(not self.shortcut_clear(level,p,q)for p,q in zip(route['points_mm'],route['points_mm'][1:])):continue
                    self.repairs[level,start,end]=copy.deepcopy(route)
        if self.progress is not None:self.progress({'phase':'static_splice_repairs','registered_routes':len(self.repairs)})

    def base_routes(self):
        if not self.sealed:raise ValueError('Seal static routes before resource catalog construction')
        from building_fleet_routes import reverse_centreline
        output=[]
        for raw in self.centreline.values():
            output.extend([self.navigation._own_right(copy.deepcopy(raw)),self.navigation._own_right(reverse_centreline(raw))])
        output.extend(copy.deepcopy(list(self.repairs.values())))
        return output

    def route(self,level,start,end):
        if not self.sealed:raise ValueError('Static route graph must precede runtime')
        start,end=tuple(start),tuple(end);hub=tuple(self.hubs[level])
        if start not in self.endpoints[level]or end not in self.endpoints[level]:raise ValueError('Unknown runtime endpoint; static catalog cannot expand live')
        if start==end:
            return {'level':level,'points_mm':[list(start)],'resources':[],'zone_segments':[],
                    'portal_certificates':[],'curve_qualified':False}
        if(level,start,end)in self.repairs:return copy.deepcopy(self.repairs[level,start,end])
        if end==hub:raw=copy.deepcopy(self.centreline[level,start,hub])
        elif start==hub:
            from building_fleet_routes import reverse_centreline
            raw=reverse_centreline(self.centreline[level,end,hub])
        else:
            points=splice_hub_paths(self.centreline[level,start,hub]['points_mm'],self.centreline[level,end,hub]['points_mm'])
            raw={'level':level,'points_mm':points,'resources':[],'zone_segments':[],'portal_certificates':[],
                 'curve_qualified':False,'search':'Shortest shared-intersection splice of source-bound base corridors'}
        return self.navigation._own_right(raw)


class EvidenceWriter:
    """Deterministic own-input evidence outside the browser payload."""
    def __init__(self,output_dir):
        self.directory=FilePath(output_dir);self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'own-controller-observations.jsonl.gz'
        if self.path.exists():raise FileExistsError(self.path)
        self.raw=self.path.open('wb');self.stream=gzip.GzipFile(fileobj=self.raw,mode='wb',mtime=0,compresslevel=1)
        self.counts={};self.closed=False;self.clock_keys=set();self.path_keys=set()
    def write(self,kind,**fields):
        if self.closed:raise RuntimeError('Closed own-input evidence writer')
        self.stream.write((json.dumps({'kind':kind,**fields},separators=(',',':'),allow_nan=False)+'\n').encode())
        self.counts[kind]=self.counts.get(kind,0)+1
    def clock(self,curve):
        if curve is None:return None
        data=json.dumps(curve.points,separators=(',',':'),allow_nan=False);key=hashlib.sha256(data.encode()).hexdigest()
        if key not in self.clock_keys:self.write('stop_clock',id=key,points=curve.points);self.clock_keys.add(key)
        return key
    def route(self,action,caps):
        row={'points_mm':action['points_mm'],'corner_trim_mm':action['corner_trim_mm'],'zone_caps':caps,'reverse':action['reverse']}
        if action.get('corner_trim_caps'):row['corner_trim_caps']=copy.deepcopy(action['corner_trim_caps'])
        data=json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False);key=hashlib.sha256(data.encode()).hexdigest()
        if key not in self.path_keys:self.write('own_path',id=key,**row);self.path_keys.add(key)
        return key
    def close(self):
        if not self.closed:self.stream.close();self.raw.close();self.closed=True
        return {'format':'solidcraftbot.building-fleet-own-input-evidence/1',
                'path':str(self.path.resolve().relative_to(model.ROOT)),
                'sha256':model.digest(self.path),'counts':copy.deepcopy(self.counts),
                'scope':'Actual own anonymous scans, captured own localization, selected scalar stop clocks and own decision states; no peer pose or ID in controller inputs'}


def point_progress(path,points,trim):
    """Ordered original-node event progress, including repeated loop positions."""
    trims=[0.]*len(points);caps={r['point_index']:r['maximum_trim_mm']for r in getattr(path,'corner_trim_caps',[])}
    for i in range(1,len(points)-1):
        a=[points[i][k]-points[i-1][k]for k in range(2)];b=[points[i+1][k]-points[i][k]for k in range(2)]
        if abs(a[0]*b[1]-a[1]*b[0])<=1e-9*math.hypot(*a)*math.hypot(*b)and sum(x*y for x,y in zip(a,b))>0:continue
        trims[i]=min(trim,caps.get(i,trim),math.dist(points[i-1],points[i])*.25,math.dist(points[i],points[i+1])*.25)
    result=[0.];distance=extra=0.
    for i in range(1,len(points)):
        distance+=math.dist(points[i-1],points[i]);extra+=trims[i-1]/3
        result.append(distance+extra+trims[i]/6)
    if abs(result[-1]-path.length)>1e-6*max(1,path.length):raise ValueError('Event progress differs from actual shared CornerPath compilation')
    return result


def zone_caps(source,path,points,zones,trim,progress_zones=()):
    marks=point_progress(path,points,trim);maximum=source['motion']['empty_linear_limits']['velocity_mm_s'];windows=[]
    for row in zones:
        start,end=row['start_index'],row['end_index']
        if not 0<=start<=end<len(points):raise ValueError('Own zone indices outside source path')
        windows.append((marks[start],marks[end],row['velocity_mm_s']))
    windows.extend(progress_zones)
    cuts=sorted({0.,path.length,*[value for a,b,_ in windows for value in(a,b)]});result=[]
    for at in cuts:
        active=min([maximum,*[cap for a,b,cap in windows if a-1e-9<=at<b-1e-9]])
        if not result or active!=result[-1][1]:result.append((at,active))
    return result


def route_shape(points):
    """Report own source geometry, without imposing a new acceptance limit."""
    lengths=[math.dist(a,b)for a,b in zip(points,points[1:])];turns=[]
    for a,b,c in zip(points,points[1:],points[2:]):
        incoming=[b[k]-a[k]for k in range(2)];outgoing=[c[k]-b[k]for k in range(2)]
        norm=math.hypot(*incoming)*math.hypot(*outgoing)
        if norm:turns.append(math.degrees(math.acos(max(-1.,min(1.,sum(x*y for x,y in zip(incoming,outgoing))/norm)))))
    return {'polyline_length_mm':sum(lengths),'maximum_turn_deg':max(turns,default=0.)}


def native_scan_geometry(navigation):
    """Source height-band first-return surfaces with articulation applied once."""
    from building_fleet_lift_checks import posed_mesh
    mesh=navigation.mesh;elevator=mesh.manifest['elevator'];objects={o['id']:o for o in mesh.manifest['objects']}
    cabin_ids=set(objects[elevator['object_id']]['moving_body_ids'])
    doors=[o for o in objects.values()if o.get('mechanism')=='lift_door']
    cabin_doors={b:o for o in doors if o.get('parent_object_id')==elevator['object_id']for b in o['moving_body_ids']}
    landing_doors={b:o for o in doors if o.get('parent_object_id')!=elevator['object_id']for b in o['moving_body_ids']}
    dynamic=cabin_ids|set(cabin_doors)|set(landing_doors)
    floor_segments={};cabin_segments={};landing_segments={}
    def add(output,polygon):
        if len(polygon)<2:return
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            if math.dist(a,b)>1e-8:output.add(tuple(sorted((tuple(a),tuple(b)))))
    for level,z in navigation.level_z.items():
        segments=set()
        for group in mesh.scene['groups']:
            if group['id']in dynamic or group['role']in navigation_model.DYNAMIC_ROLES:continue
            bb=mesh.bounds(group)
            if bb['max'][2]<z+navigation.config['geometry']['floor_band_start_mm']or bb['min'][2]>z+navigation.height:continue
            for triangle in mesh.triangles(group):add(segments,navigation_model.clip_height(triangle,z+navigation.config['geometry']['floor_band_start_mm'],z+navigation.height))
        floor_segments[level]=sorted(segments)
    for sides in((),('inward',),('outward',)):
        values={elevator['object_id']:elevator['reference_z_mm']}
        for obj in doors:values[obj['id']]=obj['states']['open'if obj.get('parent_object_id')==elevator['object_id']and obj['side']in sides else'closed']
        posed=posed_mesh(mesh,values);segments=set();z=elevator['reference_z_mm']
        for group in posed.scene['groups']:
            if group['id']not in cabin_ids and group['id']not in cabin_doors:continue
            for triangle in posed.triangles(group):add(segments,navigation_model.clip_height(triangle,z+navigation.config['geometry']['floor_band_start_mm'],z+navigation.height))
        cabin_segments[sides]=sorted(segments)
    for level,z in navigation.level_z.items():
        for sides in((),('inward',),('outward',)):
            values={obj['id']:obj['states']['open'if obj.get('level_id')==level and obj.get('side')in sides else'closed']
                    for obj in doors if obj.get('parent_object_id')!=elevator['object_id']}
            posed=posed_mesh(mesh,values);segments=set()
            for group in posed.scene['groups']:
                if group['id']not in landing_doors:continue
                bb=posed.bounds(group)
                if bb['max'][2]<z+navigation.config['geometry']['floor_band_start_mm']or bb['min'][2]>z+navigation.height:continue
                for triangle in posed.triangles(group):add(segments,navigation_model.clip_height(triangle,z+navigation.config['geometry']['floor_band_start_mm'],z+navigation.height))
            landing_segments[level,sides]=sorted(segments)
    return floor_segments,cabin_segments,landing_segments


class ResourceGate:
    """Own progress requests, bounded stopping before an ungranted region."""
    def __init__(self,engine,vehicle,controller,level):
        self.engine=engine;self.vehicle=vehicle;self.driver=controller
        self.spans=engine.catalog.spans(level,controller.path);self.index=0
        self.lookahead=controller.settings['range_mm']

    def permit(self,now):
        e=self.engine;driver=self.driver;identity=self.vehicle
        while self.index<len(self.spans):
            span=self.spans[self.index];held=e.resources.holds.get(identity)
            if driver.y>span['end_progress_mm']+1e-7:
                if held==span['resource']:e.release_resource(identity,held,now)
                self.index+=1;continue
            if held is not None and held!=span['resource']:
                # A preceding episode can retain a lease while resting. If this
                # new own curve no longer enters it, its body is source-clear.
                old=[s for s in self.spans if s['resource']==held and s['end_progress_mm']>=driver.y]
                if not old:e.release_resource(identity,held,now);continue
                return False
            if driver.y+self.lookahead<span['start_progress_mm']and held is None:return True
            result=e.resources.request(identity,span['resource'],now);e.drain_resource_events()
            if result['status']=='granted':return True
            brake=driver._checked_brake()
            distance=brake.points[-1][floor.F[0]][0]if brake else 0
            if driver.y+distance>span['start_progress_mm']+1e-6:raise RuntimeError('Own resource request came too late for its checked stopping envelope')
            return False
        held=e.resources.holds.get(identity)
        if held:e.release_resource(identity,held,now)
        return True


class WorldRunner:
    """One deterministic simultaneous world; vehicle inputs stay own-only."""
    def __init__(self,source,navigation,graph,catalog,planner,*,progress=None,geometry_checker=None,output_dir=None):
        self.source=source;self.nav=navigation;self.graph=graph;self.catalog=catalog;self.planner=planner;self.progress=progress
        if not callable(geometry_checker):raise ValueError('Canonical source-gated floor/clearance checker required')
        self.geometry_checker=geometry_checker;self.evidence=EvidenceWriter(output_dir)if output_dir is not None else None
        self.dt=.05;self.now=0.;self.wall_start=time.monotonic();self.sensor=model.resolved_sensor(source)
        from building_fleet_zones import source_regions
        self.zone_regions={level:source_regions(navigation,level)for level in navigation.level_z}
        if self.progress is not None:self.progress({'phase':'native_scan_surfaces','model_time_s':self.now})
        static,cabins,landings=native_scan_geometry(navigation)
        if self.progress is not None:self.progress({'phase':'native_scan_surfaces_ready','model_time_s':self.now})
        self.world=world_model.SensorWorld(self.sensor,static,cabin_segments_by_sides=cabins,landing_segments_by_level_sides=landings)
        self.auditor=world_model.IntervalAuditor(navigation.reserve,static)
        self.resources=service_model.ResourceServices(catalog.resources,navigation.waits)
        self.admission_policy=model.admission_settings(source)
        depot_level=source['depot']['level']
        self.depot_polygons={(depot_level,area):copy.deepcopy(navigation.polygons[depot_level][area])for area in source['depot']['areas']}
        self.depot_aliases={key:catalog.canonical[catalog.room_alias[key]]for key in self.depot_polygons}
        self.depot_maps={identity:FixedHomeMap(identity,navigation.homes,navigation.envelope,self.depot_aliases,
            self.sensor['range_error_mm']+source['geometry']['localization_tolerance_mm'])for identity in navigation.homes}
        self.depot_checks=[];self.depot_invariant_checks=0
        self.dispatcher=Dispatcher(source,navigation.homes)
        self.uplink=communication.Channel(source['communication']['latency_s'],source['missions']['seed'],max(source['communication']['latency_s']))
        self.downlink=communication.Channel(source['communication']['latency_s'],source['missions']['seed'],max(source['communication']['latency_s']))
        self.control_room=communication.ReceivedControlRoom();self.scan_queue=[];self.scan_serial=0
        self.resource_events=[];self.resource_cursor=0;self.inspection_witnesses=[];self.camera_captures={};self.geometry_checks=[];self.driver_checks=[]
        self.lift_requests=[];self.lift_events=[];self.lift_cursor=0;self._motion_cache={};self._geometry_cache={}
        self.route_door_ids=set();self.home_events=[]
        self.mission_receipts=[];self.mission_acknowledgements=[];self.bay_parking_events=[]
        self.vehicles={};self.latest_scans={};self.capture_history={};self.decision={};self.leg_counter=0
        self.heartbeat_step=round(1/self.dt);self.perception_step=round(.5/self.dt);self.scan_step=round(self.sensor['period_s']/self.dt)
        if self.scan_step*self.dt!=self.sensor['period_s']:raise ValueError('Sensor period must be representable on the source integration step')
        for identity,home in sorted(navigation.homes.items()):
            self.vehicles[identity]={'vehicle_id':identity,'pose_mm_rad':home['pose_mm_rad'][:],'level':home['level'],
                'z_mm':navigation.level_z[home['level']],'phase':'home','aboard':False,'home':copy.deepcopy(home),
                'mission_pending':False,'driver':None,'gate':None,'action':None,'markers':[],
                'episodes':[],'done':False,'drives':0,'capture_seq':0,'last_terminal':None,
                'hold_reason':'resource_wait','hold_condition':'own_received_assignment','event_cursor':0,'leg_id':None,'evidence_path_id':None,'action_context':None,'current_area':home['area']}
            self.capture_history[identity]={}
        lift_config=navigation.mesh.manifest['elevator'];walk=model.reference(source,'walkthrough')['elevator']
        # Sensor uncertainty can require more lateral spacing than the geometric
        # minimum. Capacity remains a derived upper bound, never a claimed run.
        gap=max(navigation.reserve,self.sensor['clearance_mm']+self.sensor['range_error_mm']+
            self.sensor['range_mm']*math.sin(math.radians(self.sensor['angular_step_deg']))+source['geometry']['localization_tolerance_mm']+getattr(navigation,'navigation_margin_mm',0))
        width=navigation.envelope['width_mm'];length=navigation.envelope['length_mm'];interior=navigation.cabin_interior_mm
        lanes=copy.deepcopy(planner.cabin_lanes_override)
        if not lanes or len(lanes)>source['lift']['maximum_capacity']:raise ValueError('Planner must supply proven source cabin lanes')
        for i,lane in enumerate(lanes):
            if lane['slot']!=i or lane['footprint_mm']!=[length,width]:raise ValueError('Planner and service cabin footprints differ')
            x,y,_=lane['pose_mm']
            if not(interior['min'][0]+length/2+navigation.reserve<=x<=interior['max'][0]-length/2-navigation.reserve and
                   interior['min'][1]+width/2+navigation.reserve<=y<=interior['max'][1]-width/2-navigation.reserve):raise ValueError('Cabin slot lies outside native interior reserve')
        if len(lanes)==2 and abs(lanes[0]['pose_mm'][1]-lanes[1]['pose_mm'][1])-width<gap-1e-7:raise ValueError('Cabin lanes cannot meet own scan passing envelope')
        self.lift=service_model.LiftService(lift_config,walk['door_duration']['value'],lanes)
        self.cabin_capacity_report={'geometric_maximum':len(service_model.cabin_lanes(interior,[length,width],navigation.reserve,source['lift']['maximum_capacity'])),
            'operating_capacity':len(lanes),'required_passing_gap_mm':gap,'basis':'source native interior, full physical envelope, perception and static reserves'}
        if hasattr(planner,'set_cabin_lanes'):planner.set_cabin_lanes(copy.deepcopy(lanes))

    def own(self,identity):
        row=self.vehicles[identity]
        own={key:copy.deepcopy(row[key])for key in('vehicle_id','pose_mm_rad','level','z_mm','phase','aboard','mission_pending')}
        expected=row['home']['pose_mm_rad'];driver=row['driver']
        own['home']=(not row['aboard']and row['level']==row['home']['level']and
            math.dist(row['pose_mm_rad'][:2],expected[:2])<=self.source['geometry']['localization_tolerance_mm']and
            abs(math.remainder(row['pose_mm_rad'][2]-expected[2],2*math.pi))<1e-6 and
            (driver is None or(abs(driver.v)<1e-8 and abs(driver.a)<1e-8)))
        return own

    def event(self,identity,event,details,now):
        self.uplink.emit(identity,'event',{'event':event,'details':copy.deepcopy(details)},now)

    def drain_resource_events(self):
        while self.resource_cursor<len(self.resources.events):
            row=self.resources.events[self.resource_cursor];self.resource_cursor+=1
            self.resource_events.append({k:row[k]for k in('vehicle_id','time_s','event','resource')})
            self.event(row['vehicle_id'],'passage_granted',{'resource':row['resource'],'wait_s':row['wait_s']},row['time_s'])

    def release_resource(self,identity,resource,now):
        if resource in self.depot_aliases.values():
            state=self.depot_states()[identity]
            occupied=any(alias==resource and level==state['level']and
                world_model.polygon_distance(world_model.footprint(state),self.depot_polygons[level,area])<=self.nav.reserve+1e-7
                for(level,area),alias in self.depot_aliases.items())
            if occupied and not exact_home_rest(identity,state,self.nav.homes):
                raise RuntimeError('Depot token release requires full body clearance or exact own home/rest')
        self.resource_events.append({'vehicle_id':identity,'resource':resource,'time_s':now,'event':'passage_released'})
        self.resources.release(identity,resource,now);self.drain_resource_events()

    def depot_states(self):
        states=self.truth()
        for identity,state in states.items():
            driver=self.vehicles[identity]['driver']
            if driver is None:v=a=[0.,0.,0.]
            else:_,v,a=driver.path.pva(driver.y,driver.v,driver.a)
            state.update(velocity_mm_rad_s=v,acceleration_mm_rad_s2=a)
        return states

    def check_depot_invariant(self):
        self.depot_invariant_checks+=check_invariant(self.depot_states(),self.nav.homes,self.depot_polygons,
            self.depot_aliases,self.resources.owners,self.nav.reserve)

    def request_mission(self,identity,level,now):
        row=self.vehicles[identity]
        if row['mission_pending']:return{'status':'pending'}
        action=row.get('action')
        if action is not None and action['terminal']['kind']in('capacity_home','capacity_wait'):
            # This endpoint was selected after a failed admission. Preserve
            # that compiled leg, and retry after its observed owned-bay/home
            # arrival rather than creating an avoidable mid-leg successor.
            return{'status':'pending_admission'}
        queued=[m for m in self.planner.states[identity]['queue']if m['mission_id']not in self.planner.states[identity]['completed']]
        if any(m['goal']['kind']=='home'for m in queued):return{'status':'already_queued'}
        # A cabin passenger plans relative to its own incoming floor. The
        # future source is a reference to that passenger's fenced exit bay.
        if row['aboard']:
            grant=self.lift.own_grant(identity)
            level=self.lift.ports[grant['destination_port']]['level_id'];role='arrival'
        else:level=row['level'];role='start'
        if any(m['goal']['level']!=level for m in queued):return{'status':'already_queued_foreign'}
        allowed={destination for destination in self.nav.waits if destination!=level and
            self.resources.can_book_mission(identity,level,destination,role)}
        # At most one local batch and one fenced foreign boundary can await
        # this vehicle. A full destination never creates an unusable mission.
        if not queued or(self.dispatcher.ready_to_return(now)and self.nav.homes[identity]['level']==level):allowed.add(level)
        def book(mid,goal):return self.resources.book_mission(identity,mid,level,goal['level'],now,role)
        message=self.dispatcher.assign(identity,level,now,admissible_levels=allowed,book_goal=book)
        if message is None:return{'status':'pending_admission'}
        self.downlink.emit(identity,'event',{'event':'mission_assigned','details':{'mission':message}},now)
        row['mission_pending']=True;return{'status':'pending','mission_id':message['mission_id']}

    def deliver_messages(self,now):
        for message in self.downlink.deliver(now):
            if message['kind']!='event'or message['payload']['event']!='mission_assigned':continue
            mission=message['payload']['details']['mission'];identity=message['vehicle_id']
            if self.dispatcher.missions.get(mission.get('mission_id'))!=mission or mission.get('vehicle_id')!=identity:
                raise RuntimeError('Received assignment differs from its immutable issued mission')
            self.vehicles[identity]['mission_pending']=False
            self.planner.receive_assignment(identity,copy.deepcopy(mission))
            self.mission_receipts.append({'vehicle_id':identity,'mission_id':mission['mission_id'],'received_s':now})
            self.event(identity,'mission_assigned',{'mission_id':mission['mission_id'],'goal':mission['goal'],
                'source_level':mission['source_level'],'booking_id':mission['booking_id'],'acknowledged':True},now)
        for message in self.uplink.deliver(now):
            self.control_room.receive(message)
            if message['kind']!='event':continue
            event=message['payload']['event'];details=message['payload']['details'];identity=message['vehicle_id']
            if event=='mission_assigned'and details.get('acknowledged'):
                self.dispatcher.acknowledge(identity,details['mission_id'])
                self.mission_acknowledgements.append({'vehicle_id':identity,'mission_id':details['mission_id'],'received_s':now})
            if event in('inspection_completed','home_reached')and details.get('mission_id'):
                self.dispatcher.receive_completion(identity,details['mission_id'])

    def lift_snapshot(self):
        value=self.lift.snapshot();value['open_sides']=sorted({p['side']for p in self.lift.ports.values()if p['level_id']==self.lift.level})if value['doors_open']else[]
        return value

    def lift_values(self):
        """Actual numeric source door/cabin FK, not a readiness Boolean."""
        snapshot=self.lift.snapshot();config=self.nav.mesh.manifest['elevator']
        result={config['object_id']:snapshot['z_mm']}
        active={ident for p in self.lift.ports.values()if p['level_id']==snapshot['level']for ident in p.get('door_object_ids',[])}
        for obj in self.nav.mesh.manifest['objects']:
            if obj.get('mechanism')!='lift_door':continue
            fraction=snapshot['door_open_fraction']if obj['id']in active else 0.
            result[obj['id']]=obj['states']['closed']+(obj['states']['open']-obj['states']['closed'])*fraction
        return result

    def truth(self):
        return {identity:{'pose_mm':row['pose_mm_rad'][:],'level':row['level'],'z_mm':row['z_mm'],
            'floor_z_mm':self.nav.level_z[row['level']],'aboard':row['aboard'],'radius_mm':self.nav.radius,
            'footprint_mm':[self.nav.envelope['length_mm'],self.nav.envelope['width_mm']]}
                for identity,row in self.vehicles.items()}

    def sync_lift(self,now):
        for identity,row in self.vehicles.items():
            if row['aboard']:
                row['z_mm']=self.lift.z
                if self.lift.phase in('opening_exit','alighting'):row['level']=self.lift.level
            connected=not(row['aboard']and self.lift.phase=='travelling')
            self.uplink.set_connected(identity,connected,now);self.downlink.set_connected(identity,connected,now)

    def door_line_clear(self):
        from building_fleet_sim import footprint
        snapshot=self.truth();bounds=self.nav.mesh.manifest['elevator']['cabin_bounds_mm'];margin=getattr(self.nav,'navigation_margin_mm',1)
        for port in self.lift.ports.values():
            if port['level_id']!=self.lift.level:continue
            for row in snapshot.values():
                if abs(row['z_mm']-port['z_mm'])>1e-6:continue
                if navigation_model.polygon_touches_box(footprint(row),port['plane_x_mm']-margin,bounds['min'][1]-margin,
                                                        port['plane_x_mm']+margin,bounds['max'][1]+margin):return False
        return True

    def own_grants(self,identity):
        own=self.resources.own_waiting_grants(identity)
        waiting=own['destination']if self.vehicles[identity]['aboard']else own['start']
        return {'waiting_place':waiting,'lift':self.lift.own_grant(identity)}

    def scan_free(self,identity):
        scan=self.latest_scans.get(identity)
        if scan is None or self.now-scan['captured_s']>self.sensor['stale_after_s']:return False
        driver=self.vehicles[identity]['driver']
        if driver is not None:
            gap,_=driver._observed_gap(scan,self.now)
            return gap>self.sensor['clearance_mm']
        return True

    def drain_lift_events(self):
        while self.lift_cursor<len(self.lift.events):
            event=copy.deepcopy(self.lift.events[self.lift_cursor]);self.lift_cursor+=1
            identity=event['vehicle_id'];name=event['event'];now=event['time_s']
            request=next((r for r in reversed(self.lift_requests)if r['vehicle_id']==identity and r.get('exited_s')is None),None)
            if name=='lift_slot_assigned':
                if request is None:raise RuntimeError('Lift assigned a slot without an actual own request')
                request['assigned_s']=now;request['slot']=event['slot']
                event['destination_port']=request['destination_port']
            if name=='lift_exited'and request is not None:request['exited_s']=now
            self.lift_events.append(event)
            self.event(identity,name,{k:v for k,v in event.items()if k not in('vehicle_id','time_s','event')},now)

    def area(self,identity):
        row=self.vehicles[identity]
        for identity,polygon in self.nav.polygons[row['level']].items():
            if navigation_model.point_in_polygon(row['pose_mm_rad'][:2],polygon):return identity
        return 'lift'if row['aboard']else'unassigned'

    def static_return(self,level,lift_phase=None,identity=None):
        index=self.world.static[level]
        tolerance=self.sensor['range_error_mm']+self.source['geometry']['localization_tolerance_mm']
        known=[]
        if lift_phase:
            ident=lift_phase['start_port'if lift_phase['kind']=='boarding'else'destination_port']
            port=self.lift.ports[ident];sides=(port['side'],)
            if sides in self.world.cabin:known.append(self.world.cabin[sides])
            if(level,sides)in self.world.landings:known.append(self.world.landings[level,sides])
        # Only immutable source map indexes and this own allocated port pose
        # enter the callback. Other dynamic door states are not guessed.
        @lru_cache(maxsize=4096)
        def matched(pose,local):
            x,y,yaw=pose;side,forward=local
            point=(x+math.cos(yaw)*forward-math.sin(yaw)*side,
                   y+math.sin(yaw)*forward+math.cos(yaw)*side)
            return index.matches(point,tolerance)or any(surface.matches(point,tolerance)for surface in known)
        depot=self.depot_maps.get(identity)
        def callback(pose,local):return matched(tuple(pose),tuple(local))or(depot is not None and depot.matches(pose,local))
        return callback

    def geometry_context(self,identity,phase):
        row=self.vehicles[identity]
        return {'phase':phase,'vehicle_id':identity,'time_s':self.now,
                'own_grants':self.own_grants(identity),
                'own_grants_at_start':copy.deepcopy(row.get('action_context')),
                'own_waiting_events':[copy.deepcopy(event)for event in self.resources.waiting_events if event['vehicle_id']==identity],
                'lift_state':copy.deepcopy(self.lift_snapshot()),'lift_values_now':self.lift_values(),
                'lift_schedule':copy.deepcopy(self.lift.schedule)}

    def check_geometry(self,identity,action,curve,phase):
        proof=self.geometry_checker(copy.deepcopy(action),curve,self.geometry_context(identity,phase))
        if not isinstance(proof,dict)or proof.get('passed')is not True:
            raise RuntimeError('Canonical '+phase+' curve support/clearance rejected: '+str((identity,proof)))
        self.geometry_checks.append({'vehicle_id':identity,'leg_id':self.vehicles[identity]['leg_id'],
                                     'phase':phase,'proof':copy.deepcopy(proof)})

    def door_markers(self,level,path):
        markers=[];objects=self.nav.mesh.manifest['objects']
        for portal in self.nav.portals[level]:
            if not portal.get('opening'):continue
            door=next((o for o in objects if o.get('mechanism')=='room_door'and o.get('level_id')==level and o.get('opening_id')==portal['opening']),None)
            if door is None:raise ValueError('Source path portal lacks a room-door binding')
            if door.get('initial_state',door['reference_state'])!='open':continue
            centre,normal,tangent=portal['centre_mm'],portal['normal'],portal['tangent']
            def signed(progress):
                p=path.evaluate(progress)[0];return sum((p[k]-centre[k])*normal[k]for k in range(2))
            found=[]
            for a,b,_,_ in path.samples:
                da,db=signed(a),signed(b)
                if da*db>0 or abs(da-db)<1e-10:continue
                lo,hi=a,b
                for _ in range(35):
                    mid=(lo+hi)/2
                    if signed(mid)*da>0:lo=mid
                    else:hi=mid
                progress=(lo+hi)/2;p=path.evaluate(progress)[0]
                if abs(sum((p[k]-centre[k])*tangent[k]for k in range(2)))>portal['opening_width_mm']/2:continue
                if any(abs(progress-old)<1e-5 for old in found):continue
                found.append(progress);self.route_door_ids.add(door['id'])
                markers.append({'event':'door_passed','progress_mm':progress,
                    'details':{'level':level,'opening_id':portal['opening'],'door_object_id':door['id']}})
        return sorted(markers,key=lambda m:m['progress_mm'])

    def start_drive(self,identity,action):
        row=self.vehicles[identity]
        if action['level']!=row['level']or row['driver']is not None:raise RuntimeError('Own drive must begin on its observed level at rest')
        shape=route_shape(action['points_mm'])
        if self.progress is not None:self.progress({'phase':'own_drive_prepare','vehicle_id':identity,
            'level':row['level'],'model_time_s':self.now,'points':len(action['points_mm']),**shape})
        path=Path(action['points_mm'],action['corner_trim_mm'],corner_trim_caps=action.get('corner_trim_caps'))
        if math.dist(path.evaluate(0)[0][:2],row['pose_mm_rad'][:2])>1e-6:raise RuntimeError('Own route does not begin at observed localization')
        from building_fleet_zones import progress_windows
        source_zones=progress_windows(path,self.zone_regions[row['level']],
            self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm,self.source['motion']['zone_velocity_mm_s'])
        caps=zone_caps(self.source,path,action['points_mm'],action['zone_segments'],action['corner_trim_mm'],source_zones)
        key=json.dumps([action['points_mm'],action['corner_trim_mm'],action.get('corner_trim_caps',[]),caps,action['reverse']],sort_keys=True)
        if key not in self._motion_cache:self._motion_cache[key]=compile_motion(path,self.source,reverse=action['reverse'],zone_caps=caps)
        driver=Controller(path,self.source,caps,own_start_s=self.now,radius_mm=self.nav.radius,
            static_return=self.static_return(row['level'],action.get('lift_phase'),identity),motion_program=self._motion_cache[key])
        driver.align_initial_heading(row['pose_mm_rad'][2])
        markers=copy.deepcopy(action['markers'])+self.door_markers(row['level'],path)
        markers.sort(key=lambda m:m['progress_mm'])
        row['action_context']=copy.deepcopy(self.own_grants(identity))
        nominal=driver._cartesian_curve(driver.nominal_clock,0.)
        absolute=[{**p,'time_s':p['time_s']+self.now}for p in nominal.points]
        self.leg_counter+=1;row['leg_id']=self.leg_counter
        nominal=floor.motion.Curve(absolute)
        if row['level']==self.source['depot']['level']:
            proof=fixed_home_curve_proof(nominal,identity,self.nav.homes,self.nav.envelope,self.nav.reserve,row['level'])
            self.depot_checks.append({'vehicle_id':identity,'leg_id':row['leg_id'],'phase':'nominal','proof':proof})
        self.check_geometry(identity,action,nominal,'nominal')
        if self.evidence is not None:row['evidence_path_id']=self.evidence.route(action,caps)
        if any(type(m.get('progress_mm'))not in(int,float)or not 0<=m['progress_mm']<=path.length for m in markers):raise ValueError('Actual monotone own marker progress required')
        if any(a['progress_mm']>b['progress_mm']for a,b in zip(markers,markers[1:])):raise ValueError('Own event progress must be ordered')
        row.update(driver=driver,gate=ResourceGate(self,identity,driver,row['level']),
            action=copy.deepcopy(action),markers=markers,phase='driving',event_cursor=0,leg_id=self.leg_counter)
        row['drives']+=1
        if self.progress is not None:self.progress({'phase':'own_drive_started','vehicle_id':identity,
            'level':row['level'],'model_time_s':self.now,'leg_id':row['leg_id'],
            'nominal_duration_s':driver.nominal_clock.times[-1],**shape})
        self.event(identity,'leg_started',{'leg_id':row['leg_id'],'level':row['level'],'terminal':action['terminal']['kind']},self.now)
        # The worker may receive the successor while moving; it is never
        # consulted as a peer-state or control-room position source.
        if not row['mission_pending']:
            state=self.planner.states[identity]
            queue=[m for m in state['queue']if m['mission_id']not in state['completed']]
            if not any(m['goal']['kind']=='home'for m in queue):self.request_mission(identity,action['prefetch_level'],self.now)

    def require_own_waiting_pose(self,identity,slot=None):
        row=self.vehicles[identity];grant=self.own_grants(identity)['waiting_place']
        if grant.get('status')!='granted'or grant['level']!=row['level']or(slot is not None and grant['slot']!=slot):
            raise RuntimeError('Actual own current-floor waiting grant required')
        target=grant['pose_mm']
        if math.dist(row['pose_mm_rad'][:2],target[:2])>1e-6 or abs(math.remainder(row['pose_mm_rad'][2]-target[2],2*math.pi))>1e-6:
            raise RuntimeError('Lift waiting state does not match actual own bay localization')
        if grant.get('role')!='start'or self.resources.wait_owners.get((grant['level'],grant['slot']))!=identity:
            raise RuntimeError('A physical waiting rest requires its exclusive current source role')
        return grant

    def park_waiting_bay(self,identity,driver):
        """Release the corridor token only at an observed exclusive bay rest.

        The bay reservation remains fenced. Canonical geometry excludes this
        full bay from every other vehicle's nominal and executed curve. Their
        anonymous scans still see the parked vehicle as a dynamic obstacle.
        """
        grant=self.require_own_waiting_pose(identity);row=self.vehicles[identity]
        _,velocity,acceleration=driver.path.pva(driver.y,driver.v,driver.a)
        if max(abs(v)for v in velocity+acceleration)>1e-7:
            raise RuntimeError('A waiting bay cannot release its corridor token while moving')
        held=self.resources.holds.get(identity)
        self.bay_parking_events.append({'event':'waiting_bay_parked','vehicle_id':identity,'time_s':self.now,
            'level':grant['level'],'slot':grant['slot'],'booking_id':grant.get('booking_id'),
            'released_resource':held,'pose_mm_rad':row['pose_mm_rad'][:],
            'velocity_mm_rad_s':velocity,'acceleration_mm_rad_s2':acceleration,
            'condition':'exclusive_current_bay_at_exact_source_pose_and_rest; every_other_curve_excludes_occupied_bay'})
        if held:self.release_resource(identity,held,self.now)

    def idle_action(self,identity):
        row=self.vehicles[identity]
        if row['done']or row['driver']is not None:return
        for _ in range(12):
            action=self.planner.next_action(self.own(identity),self.now,self.own_grants(identity));kind=action['kind']
            if kind=='drive':self.start_drive(identity,action);return
            if kind=='request_mission':
                result=self.request_mission(identity,action['from_level'],self.now)
                if result['status']=='pending_admission':
                    self.planner.on_action_result(identity,action,result,self.now)
                    row['hold_reason']='resource_wait';row['hold_condition']='own_future_lift_endpoint_admission';return
            elif kind=='request_wait':
                raise RuntimeError('A foreign assignment must already contain its own fenced waiting endpoints')
            elif kind=='call_lift':
                if row['phase']not in('lift_wait','capacity_wait'):raise RuntimeError('Lift call requires observed own waiting arrival')
                wait=self.require_own_waiting_pose(identity)
                booking=self.resources.require_mission_booking(identity,action['mission_id'],action['from_level'],action['to_level'])
                if booking['booking_id']!=action['booking_id']:raise RuntimeError('Lift call changed its immutable mission booking')
                result=self.lift.request(identity,action['from_level'],action['to_level'],self.now)
                request=self.lift.requests[identity]
                self.lift_requests.append({'vehicle_id':identity,'start_port':request['start_port'],
                    'destination_port':request['end_port'],'slot':None,'requested_s':self.now,'assigned_s':None,
                    'mission_id':action['mission_id'],'booking_id':booking['booking_id'],
                    'destination_waiting_bay':copy.deepcopy(self.resources.own_waiting_grants(identity)['destination'])})
                self.drain_lift_events()
            elif kind=='complete':
                if not self.own(identity)['home']:raise RuntimeError('Final home completion requires actual own home localization')
                row['done']=True;row['phase']='home';row['hold_reason']='home';row['hold_condition']='observed_final_home'
                result={'status':'completed'}
                self.planner.on_action_result(identity,action,result,self.now)
                self.event(identity,'home_reached',{'mission_id':action['mission_id'],'level':row['level'],'slot':row['home']['slot']},self.now)
                held=self.resources.holds.get(identity)
                if held:self.release_resource(identity,held,self.now)
                waiting=self.resources.wait_holds.get(identity)
                if waiting is not None:
                    poly=self.nav.waiting_bay_polygons[waiting[0]][waiting[1]]
                    if world_model.polygon_distance(world_model.footprint(self.truth()[identity]),poly)<self.nav.reserve-1e-6:raise RuntimeError('Home completion cannot release a physically occupied waiting bay')
                    self.resources.release_waiting_place(identity,self.now)
                return
            elif kind=='hold':
                condition=action.get('condition')
                if not isinstance(condition,str)or not condition:raise ValueError('A hold requires an observed completion condition')
                row['hold_condition']=condition
                row['hold_reason']=('lift_travel'if row['aboard']and self.lift.phase=='travelling'else
                    'lift_door_sequence'if row['aboard']and self.lift.phase!='alighting'else
                    'lift_parked'if row['aboard']else'lift_wait'if'lift'in condition else'resource_wait')
                return
            else:raise ValueError('Unimplemented mission action: '+str(kind))
            self.planner.on_action_result(identity,action,result,self.now)
        raise RuntimeError('Own action transitions did not reach a physical drive or explicit wait')

    def require_port_body_clear(self,identity,port_id):
        port=self.lift.ports[port_id];row=self.vehicles[identity]
        if row['level']!=port['level_id']or abs(row['z_mm']-port['z_mm'])>1e-6:
            raise RuntimeError('Body-clear observation is not at its own destination floor')
        outside=1 if port['exit_eye_mm'][0]>port['plane_x_mm']else-1
        polygon=world_model.footprint(self.truth()[identity])
        boundary=port['plane_x_mm']+outside*(port['wall_thickness_mm']/2+self.nav.reserve)
        if min(outside*(point[0]-boundary)for point in polygon)<-1e-6:
            raise RuntimeError('Own physical footprint has not cleared the active port')

    def process_markers(self,identity):
        row=self.vehicles[identity];driver=row['driver']
        if driver is None:return
        while row['markers']and driver.y>=row['markers'][0]['progress_mm']-1e-7:
            mark=row['markers'].pop(0);event=mark['event'];details=copy.deepcopy(mark['details'])
            if event=='inspection_completed':
                if abs(driver.v)<1e-6:raise RuntimeError('Inspection waypoint became an unnecessary rest endpoint')
                mid=mark['mission_id'];details['mission_id']=mid
                if not navigation_model.point_in_polygon(row['pose_mm_rad'][:2],self.nav.polygons[details['level']][details['area']]):
                    raise RuntimeError('Actual moving inspection witness is outside its source room')
                self.inspection_witnesses.append({'vehicle_id':identity,'time_s':self.now,'level':details['level'],
                    'area':details['area'],'mission_id':mid,'progress_mm':driver.y,'leg_id':row['leg_id']})
                self.event(identity,event,{k:details[k]for k in('level','area','mission_id')},self.now)
            elif event=='lift_exited':
                if not self.scan_free(identity):raise RuntimeError('Lift body-clear marker lacks a fresh own clear scan')
                grant=self.lift.own_grant(identity)
                self.require_port_body_clear(identity,grant['destination_port'])
                result=self.lift.exit(identity,True)
                if result['status']!='accepted':raise RuntimeError('Actual lift exit was not service-ready')
                if result['direction']!=details['direction']:raise RuntimeError('Own exit direction contradicts source active port sides')
                row['aboard']=False;row['z_mm']=self.nav.level_z[row['level']]
                self.resources.promote_destination_waiting_place(identity,row['level'],self.now)
                self.drain_lift_events()
            elif event=='waiting_place_released':
                grant=self.own_grants(identity)['waiting_place']
                if grant.get('status')!='granted'or any(grant.get(k)!=details[k]for k in('level','slot')):raise RuntimeError('Waiting-bay release must identify own actual grant')
                poly=self.nav.waiting_bay_polygons[details['level']][details['slot']]
                if world_model.polygon_distance(world_model.footprint(self.truth()[identity]),poly)<self.nav.reserve-1e-6:raise RuntimeError('Own physical footprint has not cleared its reserved waiting bay')
                self.resources.release_waiting_place(identity,self.now)
            else:
                if event not in communication.EVENTS:raise ValueError('Unknown executed mission marker '+str(event))
                self.event(identity,event,details,self.now)
            self.planner.on_event(identity,event,details,self.now)

    def finish_drive(self,identity):
        row=self.vehicles[identity];driver=row['driver'];action=row['action']
        if driver is None or driver.mode!='arrived':return
        if row['markers']:raise RuntimeError('Drive arrived with unobserved passage events')
        terminal=action['terminal'];kind=terminal['kind']
        if kind=='cabin_park':
            grant=self.lift.own_grant(identity)
            if grant.get('slot')!=terminal['slot']or math.dist(row['pose_mm_rad'][:2],grant['cabin_pose_mm'][:2])>1e-6:raise RuntimeError('Actual parked pose differs from own allocated cabin slot')
            port=self.lift.ports[grant['start_port']];heading=0. if port['cabin_entry_mm'][0]>port['exit_eye_mm'][0]else math.pi
            if abs(math.remainder(row['pose_mm_rad'][2]-heading,2*math.pi))>1e-6:raise RuntimeError('Cabin parking changed the source approach heading')
            if not self.scan_free(identity):
                row['hold_reason']='lift_parked';row['hold_condition']='fresh_own_scan_before_park_ack';return
            result=self.lift.board(identity,True)
            if result['status']!='accepted':raise RuntimeError('Actual cabin parking lacks an open-port own grant')
            self.lift.park(identity);row['aboard']=True;row['phase']='aboard'
            bid=self.resources.active_bookings[identity]
            self.resources.mark_mission_boarded(identity,self.resources.bookings[bid]['mission_id'],self.now)
            self.resources.release_waiting_place(identity,self.now);self.drain_lift_events()
        elif kind=='lift_wait':
            self.require_own_waiting_pose(identity,terminal['slot']);row['phase']='lift_wait'
        elif kind=='same_side_exit_stop':
            self.require_own_waiting_pose(identity,terminal['slot']);row['phase']='landing'
        elif kind=='capacity_wait':
            self.require_own_waiting_pose(identity,terminal['slot']);row['phase']='capacity_wait'
            row['hold_reason']='capacity_wait';row['hold_condition']='own_admissible_successor_assignment'
        elif kind in('home','capacity_home'):
            if not self.own(identity)['home']:raise RuntimeError('Home drive ended outside actual own source home')
            row['phase']=kind
            if kind=='capacity_home':
                row['hold_reason']='capacity_home';row['hold_condition']='own_admissible_successor_assignment'
        else:raise ValueError('Unknown physical drive endpoint '+str(kind))
        actual=floor.motion.Curve(floor.canonical(driver.recorded))
        if row['level']==self.source['depot']['level']:
            proof=fixed_home_curve_proof(actual,identity,self.nav.homes,self.nav.envelope,self.nav.reserve,row['level'])
            self.depot_checks.append({'vehicle_id':identity,'leg_id':row['leg_id'],'phase':'executed','proof':proof})
        self.check_geometry(identity,action,actual,'executed')
        if kind in('lift_wait','same_side_exit_stop','capacity_wait'):self.park_waiting_bay(identity,driver)
        if kind=='capacity_home':
            held=self.resources.holds.get(identity)
            if held:self.release_resource(identity,held,self.now)
        self.driver_checks.append({'vehicle_id':identity,'leg_id':row['leg_id'],'perception_limit':copy.deepcopy(driver.perception_limit),
            'perception_audit':copy.deepcopy(driver.perception_audit),'profiles':copy.deepcopy(driver.profile_checks)})
        self.planner.on_action_result(identity,action,{'status':'arrived','terminal':copy.deepcopy(terminal),
            'pose_mm_rad':row['pose_mm_rad'][:],'level':row['level']},self.now)
        row['last_terminal']=copy.deepcopy(terminal);row['driver']=None;row['gate']=None;row['action']=None

    def observe(self,step):
        truth=self.truth();snapshot=self.lift_snapshot()
        for identity,row in self.vehicles.items():
            self.capture_history[identity][self.now]={'pose_mm_rad':row['pose_mm_rad'][:],'level':row['level'],'z_mm':row['z_mm']}
        if step%self.scan_step==0:
            for identity in self.vehicles:
                scan=self.world.scan(identity,truth,self.now,snapshot);self.scan_serial+=1
                if self.evidence is not None:self.evidence.write('scan',vehicle_id=identity,
                    captured_s=self.now,pose_mm_rad=self.vehicles[identity]['pose_mm_rad'][:],
                    level=self.vehicles[identity]['level'],z_mm=self.vehicles[identity]['z_mm'],returns_local_mm=scan['returns_local_mm'])
                heapq.heappush(self.scan_queue,(round(self.now+self.sensor['latency_s'],9),self.scan_serial,identity,scan))
        while self.scan_queue and self.scan_queue[0][0]<=self.now+1e-9:
            _,_,identity,scan=heapq.heappop(self.scan_queue);self.latest_scans[identity]=scan
        for identity,row in self.vehicles.items():
            if step%self.heartbeat_step==0:
                speed=abs(row['driver'].v)if row['driver']is not None else 0.
                self.uplink.emit(identity,'heartbeat',{'pose_mm':row['pose_mm_rad'][:],'level':row['level'],
                    'area':self.area(identity),'mode':row['phase'],'speed_mm_s':speed},self.now)
            scan=self.latest_scans.get(identity)
            if step%self.perception_step==0 and scan is not None:
                captured=self.capture_history[identity].get(scan['captured_s'])
                if captured is None:raise RuntimeError('Original own capture localization missing')
                points=scan['returns_local_mm'];nearest=min(points,key=lambda p:math.hypot(*p),default=None)
                row['capture_seq']+=1;reference=identity+'-camera-'+str(row['capture_seq'])
                self.camera_captures[reference]={'captured_s':scan['captured_s'],'pose_xyz_mm':[*captured['pose_mm_rad'][:2],captured['z_mm']],
                    'yaw_rad':captured['pose_mm_rad'][2],'level_id':captured['level']}
                self.uplink.emit(identity,'perception',{'captured_s':scan['captured_s'],'pose_mm':captured['pose_mm_rad'][:],
                    'level':captured['level'],'scan':{'return_count':len(points),
                    'nearest_mm':math.hypot(*nearest)if nearest is not None else None,
                    'bearing_rad':math.atan2(nearest[0],nearest[1])if nearest is not None else None},'camera_ref':reference},self.now)
            # Captures retained by camera_ref have already been copied. Only
            # the short anonymous-scan delivery history is needed here.
            for at in list(self.capture_history[identity]):
                if at<self.now-max(1.,2*self.sensor['stale_after_s']):del self.capture_history[identity][at]
        return truth

    @staticmethod
    def public_point(point):
        return {key:copy.deepcopy(point[key])for key in('time_s','pose_mm_rad','velocity_mm_rad_s','acceleration_mm_rad_s2')}

    def interval_points(self,identity,start,end,driver):
        if driver is None:
            pose=self.vehicles[identity]['pose_mm_rad'][:]
            return [{'time_s':at,'pose_mm_rad':pose[:],'velocity_mm_rad_s':[0.,0.,0.],
                     'acceleration_mm_rad_s2':[0.,0.,0.]}for at in(start,end)]
        lo=bisect.bisect_left(driver.record_times,start-1e-9);hi=bisect.bisect_right(driver.record_times,end+1e-9)
        points=[self.public_point(p)for p in driver.recorded[lo:hi]]
        if not points or abs(points[0]['time_s']-start)>1e-8 or abs(points[-1]['time_s']-end)>1e-8:raise RuntimeError('Actual controller PVA does not cover the entire world interval')
        return points

    def append_episode(self,identity,start,end,points,driver,lift_before):
        # Functional arrival/protective-stop knots can fall between world
        # ticks. Separate their exact stationary suffix instead of hiding a
        # zero-speed dwell inside a nominally continuous driving episode.
        for first,last in zip(points,points[1:]):
            self._append_episode_part(identity,first['time_s'],last['time_s'],[first,last],driver,lift_before)

    def _append_episode_part(self,identity,start,end,points,driver,lift_before):
        row=self.vehicles[identity];moving=(math.dist(points[0]['pose_mm_rad'],points[-1]['pose_mm_rad'])>1e-9
                or any(abs(v)>1e-7 for p in points for field in('velocity_mm_rad_s','acceleration_mm_rad_s2')for v in p[field]))
        if moving:
            mode='driving';reason=None;condition=None;attached=False
        elif row['aboard']:
            mode='lift'if lift_before['phase']=='travelling'else'hold';attached=True
            reason='lift_travel'if mode=='lift'else'lift_door_sequence'if lift_before['phase']in('closing_passengers','opening_exit')else'lift_parked'
            condition='source_cabin_destination_and_fully_open_active_port'if mode=='lift'else'own_destination_port_ready'
        else:
            mode='hold';attached=False
            terminal=row['action']['terminal']['kind']if driver is not None and row['action']is not None else None
            if driver is not None and driver.mode=='arrived':
                reason={'cabin_park':'lift_parked','lift_wait':'lift_wait','same_side_exit_stop':'lift_wait','home':'home',
                    'capacity_wait':'capacity_wait','capacity_home':'capacity_home'}[terminal]
                condition='actual_functional_'+terminal+'_arrival'
            else:
                reason=('resource_wait'if driver is not None and driver.reason=='resource_wait'else'protective_stop')if driver is not None else row['hold_reason']
                condition=('own_exclusive_resource_grant'if reason=='resource_wait'else'fresh_clear_anonymous_scan')if driver is not None else row['hold_condition']
        action=row['action'];metadata={'level_id':row['level'],'mode':mode,'attached_cabin':attached,
            'hold_reason':reason,'hold_condition':condition,'leg_id':row['leg_id']if driver is not None else None}
        if (action is not None and action.get('lift_phase')and
                (action['lift_phase']['kind']=='boarding'or row['aboard'])):
            metadata.update(lift_phase=action['lift_phase']['kind'],lift_stage=copy.deepcopy(action['lift_phase']),
                port_id=action['port_id'],cabin_slot=action['cabin_slot'],reverse=action['reverse'])
        elif attached:
            grant=self.lift.own_grant(identity)
            metadata.update(cabin_slot=grant.get('slot'),start_port=grant.get('start_port'),destination_port=grant.get('destination_port'))
        episodes=row['episodes'];previous=episodes[-1]if episodes else None
        if previous is not None:
            last=previous['points'][-1]
            if abs(last['time_s']-start)>1e-8 or any(abs(a-b)>1e-6 for field in('pose_mm_rad','velocity_mm_rad_s','acceleration_mm_rad_s2')for a,b in zip(last[field],points[0][field])):raise RuntimeError('Actual world episodes lost PVA continuity')
        same=(previous is not None and set(previous)-{'start_s','end_s','points'}==set(metadata)
            and all(previous.get(k)==v for k,v in metadata.items()))
        if same:
            previous['end_s']=end
            if mode in('hold','lift'):previous['points'][-1]=points[-1]
            else:previous['points'].extend(points[1:])
        else:episodes.append({**metadata,'start_s':start,'end_s':end,'points':points})

    def advance_world(self,end):
        start=self.now;previous=self.truth();drivers={i:r['driver']for i,r in self.vehicles.items()};lift_before=self.lift_snapshot()
        self.check_depot_invariant()
        for identity,driver in drivers.items():
            if driver is None:continue
            permit=self.vehicles[identity]['gate'].permit(start)
            own_resource=self.resources.own_grants(identity)
            self.depot_maps[identity].set_own_grant(own_resource)
            action=self.vehicles[identity]['action']
            if action.get('lift_phase'):
                phase=action['lift_phase']['kind'];grant=self.lift.own_grant(identity)
                # Body-clear alighting continues on its own route after the
                # slot has actually been released by the marker.
                permit=permit and(grant.get('boarding_ready',False)if phase=='boarding'else
                    grant.get('exit_ready',False)or not self.vehicles[identity]['aboard'])
                if permit and(phase=='boarding'or self.vehicles[identity]['aboard']):
                    from building_fleet_lift_checks import gate_at
                    values=self.lift_values();timeline=SimpleNamespace(values=lambda at:values)
                    gate_at(self.nav.mesh,action['port_id'],timeline,start)
            own_state={'progress_mm':driver.y,'velocity_mm_s':driver.v,'acceleration_mm_s2':driver.a}
            self.decision[identity]=driver.decide(start,self.latest_scans.get(identity),grant_permits=bool(permit))
            margin=driver.perception_audit['minimum_range_margin_mm']
            if margin is None or not math.isfinite(margin)or margin<0:
                raise RuntimeError('Actual own stopping proof exceeds its source observation budget: '+str((identity,start,margin)))
            if self.evidence is not None:
                scan=self.latest_scans.get(identity);stop=driver._checked_brake()
                self.evidence.write('decision',vehicle_id=identity,time_s=start,path_id=self.vehicles[identity]['evidence_path_id'],
                    **own_state,zone_cap_mm_s=driver._zone_cap_at(driver.y),
                    captured_s=scan['captured_s']if scan is not None else None,
                    own_grant_permits=bool(permit),selected_stop_clock=self.evidence.clock(stop),
                    own_conditional_home_map_grant=copy.deepcopy(own_resource),
                    decision=copy.deepcopy(self.decision[identity]),mode=driver.mode,
                    observation_range_margin_mm=driver.perception_audit['minimum_range_margin_mm'])
        for identity,driver in drivers.items():
            if driver is not None:
                value=driver.advance(start,end);self.vehicles[identity]['pose_mm_rad']=value['pose_mm_rad']
                while self.vehicles[identity]['event_cursor']<len(driver.events):
                    event=driver.events[self.vehicles[identity]['event_cursor']];self.vehicles[identity]['event_cursor']+=1
                    self.event(identity,event['event'],{k:v for k,v in event.items()if k not in('time_s','event')},event['time_s'])
        self.now=end
        self.check_depot_invariant()
        clear=self.door_line_clear();self.lift.tick(end,clear);self.drain_lift_events();self.sync_lift(end)
        if clear and self.lift.phase in('closing_pickup','closing_passengers'):
            self.lift_events.append({'event':'door_line_clear','vehicle_id':None,'time_s':end,'level':self.lift.level,'clear':True})
        curves={};speed_bounds={};all_points={}
        for identity,driver in drivers.items():
            points=self.interval_points(identity,start,end,driver);all_points[identity]=points
            curve=floor.motion.Curve(floor.canonical(points));curves[identity]=curve;bounds=floor.motion.bounds(curve)
            speed_bounds[identity]={'linear_mm_s':math.hypot(*bounds[floor.F[1]]['max_abs'][:2]),'yaw_rad_s':bounds[floor.F[1]]['max_abs'][2]}
        self.auditor.audit(previous,self.truth(),end-start,speed_bounds,curves=curves,start_s=start,end_s=end)
        for identity,driver in drivers.items():self.append_episode(identity,start,end,all_points[identity],driver,lift_before)
        for identity,row in self.vehicles.items():
            area=self.area(identity)
            if area!=row['current_area']:
                self.event(identity,'area_entered',{'level':row['level'],'area':area},self.now);row['current_area']=area
            self.process_markers(identity)
        for identity in self.vehicles:self.finish_drive(identity)

    def completed(self):
        return(all(r['done']and self.own(i)['home']for i,r in self.vehicles.items())and
            not self.resources.holds and not self.resources.wait_holds and not self.resources.exit_wait_holds and
            not self.resources.next_wait_holds and not self.resources.active_bookings and not self.resources.next_bookings and
            not self.lift.requests and not self.uplink.pending and not self.downlink.pending and
            not any(self.uplink.buffer.values())and not any(self.downlink.buffer.values())and
            self.dispatcher.acks<=self.dispatcher.completed)

    def run(self):
        maximum=self.source['missions']['maximum_duration_s'];step=0
        while self.now<maximum-1e-8:
            self.deliver_messages(self.now)
            for identity in self.vehicles:
                if self.vehicles[identity]['aboard']and not self.vehicles[identity]['mission_pending']:
                    self.request_mission(identity,self.vehicles[identity]['level'],self.now)
                self.idle_action(identity)
            self.observe(step)
            end=round((step+1)*self.dt,3);self.advance_world(end);step+=1
            if self.progress is not None and step%round(10/self.dt)==0:
                self.progress({'model_time_s':self.now,'completed_visits':sum(self.dispatcher.visits.values()),
                    'home_count':sum(r['done']for r in self.vehicles.values()),'elapsed_wall_s':time.monotonic()-self.wall_start})
            if self.now>=self.source['missions']['minimum_duration_s']and self.completed():return self.program()
        raise RuntimeError('BF01 source maximum duration reached without actual fleet completion; original seed retained')

    def program(self,complete=True):
        if complete and not self.completed():raise RuntimeError('An incomplete world cannot be emitted as a completed fleet program')
        limits=[r['perception_limit']for r in self.driver_checks]
        checked=bool(limits)and all(r['perception_audit']['checks']>0 and
            type(r['perception_audit'].get('minimum_range_margin_mm'))in(int,float)and
            math.isfinite(r['perception_audit']['minimum_range_margin_mm'])and
            r['perception_audit']['minimum_range_margin_mm']>=0 for r in self.driver_checks)
        maximum=max((r['required_range_mm']for r in limits),default=math.inf)
        if complete and(not checked or maximum>self.sensor['range_mm']):
            raise RuntimeError('A complete fleet needs every actual own stopping-range proof')
        return {'format':'solidcraftbot.building-fleet-program/1','complete':bool(complete),'seed':self.source['missions']['seed'],
            'duration_s':self.now,'levels':copy.deepcopy(self.nav.mesh.manifest['levels']),
            'room_route_object_ids':sorted(self.route_door_ids),'targets':copy.deepcopy(self.source['missions']['targets']),
            'homes':copy.deepcopy(self.nav.homes),'lift_schedule':copy.deepcopy(self.lift.schedule),
            'lift_requests':copy.deepcopy(self.lift_requests),'lift_events':copy.deepcopy(self.lift_events),
            'trajectories':[{'vehicle_id':i,'episodes':copy.deepcopy(r['episodes'])}for i,r in self.vehicles.items()],
            'waiting_events':copy.deepcopy(self.resources.waiting_events),
            'mission_assignments':copy.deepcopy(list(self.dispatcher.missions.values())),
            'mission_receipts':copy.deepcopy(self.mission_receipts),'mission_acknowledgements':copy.deepcopy(self.mission_acknowledgements),
            'mission_bookings':copy.deepcopy(list(self.resources.bookings.values())),
            'booking_events':copy.deepcopy(self.resources.booking_events),'bay_parking_events':copy.deepcopy(self.bay_parking_events),
            'inspection_witnesses':copy.deepcopy(self.inspection_witnesses),'resource_events':copy.deepcopy(self.resource_events),
            'received_messages':copy.deepcopy(self.control_room.messages),'camera_captures':copy.deepcopy(self.camera_captures),
            'resource_catalog':self.catalog.report(),'trajectory_checks':{'passed':bool(complete),'reserve_mm':self.nav.reserve,**self.auditor.statistics()},
            'perception_checks':{'passed':bool(complete)and checked and maximum<=self.sensor['range_mm'],'stop_family_checked':checked,
                'maximum_required_range_mm':maximum if math.isfinite(maximum)else None,'drivers':copy.deepcopy(self.driver_checks)},
            'statistics':{'coverage':self.dispatcher.coverage(),'radio':self.uplink.statistics(),'sensor':self.world.statistics(),
                'lift':self.lift.statistics(),'cabin_capacity':copy.deepcopy(self.cabin_capacity_report),
                'elapsed_wall_s':time.monotonic()-self.wall_start,'playback_factor':1},
            'qualification':copy.deepcopy(self.source['qualification']),'geometry_checks':copy.deepcopy(self.geometry_checks),
            'conditional_depot_map':{'fixed_home_curve_checks':copy.deepcopy(self.depot_checks),
                'invariant_observations':self.depot_invariant_checks,'room_resources':[{ 'level':key[0],'area':key[1],'resource':value}for key,value in self.depot_aliases.items()],
                'assumption':'No people in this synthetic empty depot; only fixed source home surfaces under an own exclusive depot-room grant; all other occupants must remain at exact home with zero PVA',
                'real_sensor_qualified':False},
            'source_files_sha256':{**model.source_pins(self.source),**model.protected_pins()},
            'own_input_evidence':self.evidence.close()if self.evidence is not None else None}


def prepare_program(source,navigation,*,progress=None,resource_cache=None):
    """Seal source paths/conflict regions before creating runtime vehicle truth."""
    from building_fleet_missions import MissionPlanner
    from building_fleet_resources import ResourceCatalog
    model.validate(source)
    expected={'BF%02d'%i for i in range(1,source['fleet']['count']+1)}
    if source['fleet']['count']!=20 or set(navigation.homes)!=expected:
        raise ValueError('A BF01 run needs exactly twenty source-derived home slots')
    graph=RouteGraph(navigation,progress=progress);planner=MissionPlanner(source,navigation,graph)
    if progress is not None:progress({'phase':'static_route_preparation'})
    graph.prepare();routes=graph.base_routes()+planner.prepared_routes()
    if progress is not None:progress({'phase':'static_resource_closure','routes':len(routes)})
    if resource_cache is not None and(FilePath(resource_cache)/'cache-report.json').exists():
        catalog=ResourceCatalog.from_cache(navigation,routes,resource_cache)
    else:
        catalog=ResourceCatalog(navigation,routes)
        if resource_cache is not None:catalog.write_cache(resource_cache,routes)
    return graph,catalog,planner


def compile_program(source,navigation,output_dir,*,progress=None,geometry_checker=None,prepared=None,artifacts=None):
    """Run the fixed-seed world or preserve an explicit incomplete failure."""
    source=model.validate(copy.deepcopy(source));directory=FilePath(output_dir)
    if set(navigation.homes)!={'BF%02d'%i for i in range(1,21)}:raise ValueError('Exactly twenty actual source homes required')
    if getattr(navigation,'config',source)!=source:raise ValueError('Navigation belongs to another source revision')
    if not directory.resolve().is_relative_to((model.ROOT/'exports').resolve()):
        raise ValueError('Ignored project-local output directory required')
    if not callable(geometry_checker):raise ValueError('Canonical source-gated geometry checker required')
    if any((directory/name).exists()for name in('program.json','partial-program.json','runtime-failure.json',
            'runtime-source-start.json','own-controller-observations.jsonl.gz')):
        raise FileExistsError('Use a fresh runtime evidence directory')
    generators=('building_fleet_model.py','building_fleet_runner.py','building_fleet_missions.py','building_fleet_services.py',
                'building_fleet_comm.py','building_fleet_control.py','building_fleet_sim.py',
                'building_fleet_motion.py','building_fleet_dispatch.py','building_fleet_resources.py','building_fleet_depot.py','building_fleet_zones.py',
                'building_fleet_geometry_checks.py','building_fleet_lift_geometry.py','building_fleet_lift_checks.py',
                'building_fleet_clearance.py','building_fleet_floor.py','building_fleet_support.py',
                'building_fleet_assignment_checks.py',
                'building_fleet_port_paths.py',
                'check_building_fleet_freecad.py')
    artifact_refs=copy.deepcopy(artifacts or {})
    artifact_pins={}
    if artifacts is not None:
        if set(artifact_refs)!={'walkthrough_report','camera_report'}:raise ValueError('Both checked native report references are required')
        for kind,ref in artifact_refs.items():
            path=model.resolve_pin(ref);artifact_pins[ref['path']]=ref['sha256']
            report=model.read_json(path)
            if kind=='camera_report':
                from export_building_fleet_vehicle_freecad import checked_camera_report
                report=checked_camera_report(path)
            elif path.resolve()!=(navigation.mesh.export/'build-report.json').resolve():
                raise ValueError('Walkthrough report must be the navigation native export')
            artifact_pins.update(report['source_files_sha256'])
            for name,digest in report.get('artifact_sha256',{}).items():
                artifact_pins[report['files'][name]]=digest
    runtime_pins={**(navigation._cache_pins()if hasattr(navigation,'_cache_pins')else{}),
        **model.source_pins(source),**model.protected_pins(),**artifact_pins,
        'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py':model.digest(model.ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py'),
        **{'scripts/'+name:model.digest(model.ROOT/'scripts'/name)for name in generators}}
    directory.mkdir(parents=True,exist_ok=True);runner=None;started=time.monotonic()
    (directory/'runtime-source-start.json').write_text(json.dumps(runtime_pins,indent=2)+'\n')
    try:
        graph,catalog,planner=prepared or prepare_program(source,navigation,progress=progress)
        runner=WorldRunner(source,navigation,graph,catalog,planner,progress=progress,
                           geometry_checker=geometry_checker,output_dir=directory)
        result=runner.run()
        result['statistics']['preparation_and_runtime_elapsed_s']=time.monotonic()-started
        if any(model.digest(model.ROOT/name)!=digest for name,digest in runtime_pins.items()):
            raise RuntimeError('Runtime sources changed during preparation or compilation; original pins retained')
        result['source_files_sha256']=copy.deepcopy(runtime_pins)
        result['artifacts']=artifact_refs
        # Program verification, independent native BReps and browser execution
        # remain their own gates; no compile_checks flags are fabricated here.
        return result
    except BaseException as exc:
        evidence=runner.evidence.close()if runner is not None and runner.evidence is not None else None
        failure={'format':'solidcraftbot.building-fleet-runtime-failure/1','passed':False,
                 'seed':source['missions']['seed'],'exception':type(exc).__name__,'error':str(exc),
                 'interrupted':isinstance(exc,KeyboardInterrupt),
                 'elapsed_s':time.monotonic()-started,'model_time_s':runner.now if runner is not None else 0,
                 'source_files_sha256':copy.deepcopy(runtime_pins),
                 'own_input_evidence':evidence,'complete_fleet_run':False}
        if runner is not None and any(row['episodes']for row in runner.vehicles.values()):
            partial=runner.program(complete=False)
            (directory/'partial-program.json').write_text(json.dumps(partial,indent=2,allow_nan=False)+'\n')
        (directory/'runtime-failure.json').write_text(json.dumps(failure,indent=2,allow_nan=False)+'\n')
        raise
