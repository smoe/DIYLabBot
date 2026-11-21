"""Source-bound BF01 destinations, depot poses and geometric route graph.

This is static navigation. Tokens and anonymous observations belong to the
runtime; a route result conveys no foreign vehicle state and grants no access.
"""
import collections
import bisect
import copy
import heapq
import math
import array
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys

import building_fleet_navigation as nav
import building_fleet_model as model
import building_stack as stack
from building_fleet_geometry import vehicle_envelope


def area_polygons(topological):
    return {level:{area['id']:[[v*data['display_scale'] for v in xy] for xy in nav.floor.area_points(data['plan'],area)]
                   for area in data['plan']['areas']} for level,data in topological.items()}


def segment_in_polygon(a,b,polygon):
    """Classify every interval cut by source polygon edges, not sparse samples."""
    if not nav.point_in_polygon(a,polygon)or not nav.point_in_polygon(b,polygon):return False
    dx,dy=b[0]-a[0],b[1]-a[1];cuts=[0.,1.]
    for p,q in zip(polygon,polygon[1:]+polygon[:1]):
        ex,ey=q[0]-p[0],q[1]-p[1];cross=dx*ey-dy*ex
        if abs(cross)<1e-12:continue
        px,py=p[0]-a[0],p[1]-a[1]
        t,u=(px*ey-py*ex)/cross,(px*dy-py*dx)/cross
        if 1e-10<t<1-1e-10 and -1e-10<=u<=1+1e-10:return False
    cuts=sorted(set(cuts))
    return all(nav.point_in_polygon([a[k]+(b[k]-a[k])*(lo+hi)/2 for k in range(2)],polygon)
               for lo,hi in zip(cuts,cuts[1:]))


def home_slots(grid, polygon, count, radius_mm, reserve_mm, existing=()):
    """Pack only proved supported free space; no corridor fallback is possible.

    A complete disc-shaped launch/arrival neighbourhood is retained per home.
    This is intentionally sparser than a maximum packing problem.
    """
    if type(count) is not int or count < 0:
        raise ValueError('Nonnegative home count required')
    if count==0:return[]
    separation = 2*radius_mm+reserve_mm
    candidates = [grid.centre(i) for i in grid.candidates(polygon)
                  if nav.point_in_polygon(grid.centre(i),polygon)
                  and grid.clearance_lower_mm(grid.centre(i)) >= radius_mm+reserve_mm]
    # Prefer independent clearance, then deterministic source-coordinate order.
    candidates.sort(key=lambda p:(-grid.clearance_lower_mm(p),p[1],p[0]))
    slots=[]
    for point in candidates:
        if all(math.dist(point,other) >= separation for other in [*existing,*slots]):
            slots.append(point)
            if len(slots) == count:return slots
    raise ValueError('Depot free area cannot provide the requested independent home envelopes')


def inspection_loop(grid, polygon, radius_mm, reserve_mm, preferred=None):
    """A positive-area loop, rather than a point visit or an in-place reversal."""
    threshold = radius_mm+reserve_mm
    candidates = [grid.centre(i) for i in grid.candidates(polygon)
                  if nav.point_in_polygon(grid.centre(i),polygon)
                  and grid.clearance_lower_mm(grid.centre(i)) >= threshold]
    candidates.sort(key=lambda p:(math.dist(p,preferred) if preferred else 0,-grid.clearance_lower_mm(p),p))
    # A rectilinear loop can be rounded continuously inside its free disc. Its
    # final native/C2 certificate is required after root Path construction.
    for centre in candidates:
        available = grid.clearance_lower_mm(centre)-threshold
        maximum=available/math.sqrt(2)
        if maximum<=1e-6:continue
        def proposed(half):
            return [[centre[0]-half,centre[1]-half],[centre[0]+half,centre[1]-half],
                    [centre[0]+half,centre[1]+half],[centre[0]-half,centre[1]+half],
                    [centre[0]-half,centre[1]-half]]
        def proved(points):
            return all(segment_in_polygon(a,b,polygon)and grid.line_free(a,b,threshold)for a,b in zip(points,points[1:]))
        low,high=0.,maximum
        if proved(proposed(high)):return proposed(high)
        for _ in range(24):
            half=(low+high)/2
            if proved(proposed(half)):low=half
            else:high=half
        if low>1e-6:return proposed(low)
    raise ValueError('No supported positive-area inspection loop with declared clearance')


def depot_rows(grid, polygon, length_mm, width_mm, radius_mm, reserve_mm):
    """Through-parking rows with forward departure and same-yaw rear arrival.

    Both lateral ends have a proved bypass. A home is between parallel front
    and rear aisles, so returning never requires backing or an in-place turn.
    Rows retain conservative whole-vehicle turning space at both aisles.
    """
    clearance=radius_mm+reserve_mm; spacing=width_mm+reserve_mm
    distance=3*radius_mm+reserve_mm; bypass=2*radius_mm+reserve_mm
    xs,ys=zip(*polygon);resolution=max(100,grid.resolution_mm*2);rows=[]
    for y in range(math.ceil((min(ys)+distance+clearance)/resolution)*resolution,
                   math.floor((max(ys)-distance-clearance)/resolution)*resolution+1,resolution):
        usable=[]
        for x in range(math.ceil(min(xs)/resolution)*resolution,math.floor(max(xs)/resolution)*resolution+1,resolution):
            point=[x,y];rear=[x,y-distance];front=[x,y+distance]
            if nav.point_in_polygon(point,polygon)and segment_in_polygon(rear,front,polygon)and grid.line_free(rear,front,clearance):usable.append(point)
        if not usable:continue
        # Consecutive independent slots; trim ends until a complete empty bypass
        # exists around the row, rather than inventing a corridor parking bay.
        for first in range(len(usable)):
            slots=[]
            for point in usable[first:]:
                if not slots or point[0]-slots[-1][0]>=spacing:slots.append(point)
            while slots:
                left,right=slots[0][0]-bypass,slots[-1][0]+bypass
                ring=[[left,y-distance],[right,y-distance],[right,y+distance],[left,y+distance],[left,y-distance]]
                if all(segment_in_polygon(a,b,polygon)and grid.line_free(a,b,clearance)for a,b in zip(ring,ring[1:])):
                    rows.append({'points':slots,'aisle_loop_mm':ring,'distance_mm':distance,'y_mm':y,
                                 'minimum_slot_gap_mm':spacing,'bypass_mm':bypass})
                    break
                slots.pop()
            if rows and rows[-1]['y_mm']==y:break
    rows.sort(key=lambda r:r['y_mm']);ys=[row['y_mm']for row in rows]
    best=[0];choice=[]
    for i,row in enumerate(rows):
        before=bisect.bisect_right(ys,row['y_mm']-2*distance,hi=i)
        include=best[before]+len(row['points']);exclude=best[-1]
        best.append(max(include,exclude));choice.append((include>exclude,before))
    selected=[];i=len(rows)
    while i:
        take,before=choice[i-1]
        if take:selected.append(rows[i-1]);i=before
        else:i-=1
    return list(reversed(selected))


def reverse_centreline(result):
    """Reverse geometry only; direction-specific lanes are applied afterwards."""
    reverse=copy.deepcopy(result);reverse['points_mm'].reverse();count=len(result['points_mm'])
    for name in('resources','zone_segments'):
        reverse[name].reverse()
        for row in reverse[name]:
            a,b=row['start_index'],row['end_index'];row['start_index'],row['end_index']=count-1-b,count-1-a
            if 'segment_index'in row:row['segment_index']=count-2-row['segment_index'];row['segment_fraction']=1-row['segment_fraction']
    reverse['portal_certificates'].reverse()
    for proof in reverse['portal_certificates']:
        if 'segment_index'in proof:proof['segment_index']=count-2-proof['segment_index']
        if 'points_mm'in proof:proof['points_mm'].reverse()
        if 'source_area'in proof:proof['source_area'],proof['destination_area']=proof['destination_area'],proof['source_area']
        proof['yaw_rad']=math.remainder(proof['yaw_rad']+math.pi,2*math.pi)
    return reverse


class Navigation:
    def __init__(self, config, export_dir):
        self.config = model.validate(copy.deepcopy(config))
        self.mesh = nav.NativeMesh(export_dir)
        building = model.reference(config,'building'); walkthrough = model.reference(config,'walkthrough')
        excluded={'KG':config['exclusions']['KG_technical_areas']}
        self.topological = nav.topology(building,walkthrough['navigation'],excluded)
        self.polygons = area_polygons(self.topological)
        self.envelope = vehicle_envelope(); self.sensor = model.resolved_sensor(config)
        self.reserve = self.sensor['clearance_mm']+config['geometry']['localization_tolerance_mm']
        self.radius = self.envelope['radius_mm']; self.height = self.envelope['height_mm']+config['geometry']['height_reserve_mm']
        self.navigation_margin_mm=walkthrough['navigation']['contact_margin_mm']
        self.grids = {level:nav.build_grid(self.mesh,level,self.height,config['geometry']['grid_step_mm'],self.topological) for level in self.topological}
        self.portals = {level:nav.opening_portals(self.topological,level) for level in self.topological}
        self._area_routes = {}; self._portal_proofs = {}; self._route_cache = {}; self._area_cells={}
        self.homes={}; self.waits={}; self.inspections={}; self.qualification={'native_route_checked':False,'fleet_compiled':False}
        self._derive_cabin(building)
        self._derive_locations()
        self._derive_waiting_bays()

    def _cache_pins(self):
        names=('building_fleet_routes.py','building_fleet_navigation.py','building_fleet_geometry.py',
               'building_fleet_sim.py','tr01_camera_model.py','building_fleet_l01.py',
               'building_fleet_floor.py','building_fleet_support.py','building_fleet_clearance.py')
        l01=model.reference(self.config,'l01_route')
        for ref in l01['sources'].values():model.resolve_pin(ref)
        return {**model.source_pins(self.config),**model.protected_pins(),
                **{ref['path']:ref['sha256']for ref in l01['sources'].values()},
                'model/building-fleet-l01-route.schema.json':model.digest(model.ROOT/'model/building-fleet-l01-route.schema.json'),
                **{'scripts/'+name:model.digest(model.ROOT/'scripts'/name)for name in names}}

    def write_cache(self,directory):
        """Write pure data with exact generators/export/configuration bindings."""
        model.validate(self.config)
        directory=Path(directory).resolve();allowed=(model.ROOT/'exports/building-fleet').resolve()
        if not directory.is_relative_to(allowed):raise ValueError('Navigation cache must stay in the ignored BF01 output tree')
        directory.mkdir(parents=True,exist_ok=False)
        def encode_grid(grid):
            distances=array.array('d',grid.distance_squared)
            if sys.byteorder!='little':distances.byteswap()
            return {'origin':grid.origin,'width':grid.width,'height':grid.height,'resolution_mm':grid.resolution_mm,
                    'blocked':base64.b64encode(grid.blocked).decode(),'supported':base64.b64encode(grid.supported).decode(),
                    'distance_squared_le':base64.b64encode(distances.tobytes()).decode()}
        pins=self._cache_pins()
        payload={'topological':self.topological,'polygons':self.polygons,'envelope':self.envelope,
                 'reserve_mm':self.reserve,'height_mm':self.height,'grids':{level:encode_grid(grid)for level,grid in self.grids.items()},
                 'portals':self.portals,'homes':self.homes,'waits':self.waits,
                 'road_hubs':self.road_hubs,'waiting_bay_polygons':self.waiting_bay_polygons,
                 'inspections':[{'level':level,'area':area,'data':data}for(level,area),data in self.inspections.items()],
                 'cabin_interior_mm':self.cabin_interior_mm,'level_z':self.level_z,'depot_rows':self.depot_rows,
                 'centreline_routes':[{'level':level,'start':list(start),'end':list(end),'route':route}
                                      for(level,start,end),route in self._route_cache.items()if start<=end]}
        data=gzip.compress(json.dumps(payload,separators=(',',':'),allow_nan=False).encode(),compresslevel=6,mtime=0)
        (directory/'navigation.json.gz').write_bytes(data)
        if pins!=self._cache_pins():raise ValueError('Navigation sources changed during cache export')
        report={'format':'solidcraftbot.building-fleet-navigation-cache/1','source_files_sha256':pins,
                'walkthrough_build_report_sha256':model.digest(self.mesh.export/'build-report.json'),
                'config_sha256':hashlib.sha256(json.dumps(self.config,sort_keys=True,allow_nan=False).encode()).hexdigest(),
                'file':'navigation.json.gz','artifact_sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
                'qualification':{'curve_qualified':False,'fleet_compiled':False,'navigation_qualified':False},
                'scope':'Pure static derived navigation cache; no runtime vehicle state, controller, world truth, executable pickle or native-motion qualification.'}
        (directory/'cache-report.json').write_text(json.dumps(report,indent=2)+'\n')
        return report

    @classmethod
    def from_cache(cls,config,export_dir,directory):
        """Reject stale/altered cache bytes before accepting any derived map."""
        directory=Path(directory);report=model.read_json(directory/'cache-report.json')
        if report.get('format')!='solidcraftbot.building-fleet-navigation-cache/1'or report.get('file')!='navigation.json.gz':
            raise ValueError('Unsupported navigation cache contract')
        if report.get('qualification')!={'curve_qualified':False,'fleet_compiled':False,'navigation_qualified':False}:
            raise ValueError('A static cache cannot assert completed motion qualification')
        n=cls.__new__(cls);n.config=model.validate(copy.deepcopy(config));n.mesh=nav.NativeMesh(export_dir)
        if report['source_files_sha256']!=n._cache_pins():raise ValueError('Navigation cache source or generator pins are stale')
        if report['walkthrough_build_report_sha256']!=model.digest(n.mesh.export/'build-report.json'):raise ValueError('Navigation cache refers to another walkthrough export')
        expected=hashlib.sha256(json.dumps(config,sort_keys=True,allow_nan=False).encode()).hexdigest()
        if report['config_sha256']!=expected:raise ValueError('Navigation cache configuration changed')
        data=(directory/report['file']).read_bytes()
        if len(data)!=report['bytes']or hashlib.sha256(data).hexdigest()!=report['artifact_sha256']:raise ValueError('Navigation cache artifact changed')
        with gzip.GzipFile(fileobj=io.BytesIO(data))as stream:
            raw=stream.read(512*1024*1024+1)
        if len(raw)>512*1024*1024:raise ValueError('Navigation cache exceeds bounded decode size')
        payload=json.loads(raw,parse_constant=lambda value:(_ for _ in()).throw(ValueError('Nonfinite cache JSON')))
        def decode_grid(row):
            grid=nav.ClearanceGrid.__new__(nav.ClearanceGrid)
            for key in('width','height'):
                if type(row[key])is not int or not 1<=row[key]<=20000:raise ValueError('Invalid cached grid dimensions')
            grid.width,grid.height=row['width'],row['height'];count=grid.width*grid.height
            grid.origin=row['origin'];grid.resolution_mm=row['resolution_mm']
            if len(grid.origin)!=2 or any(type(v)not in(int,float)or not math.isfinite(v)for v in grid.origin)or grid.resolution_mm!=config['geometry']['grid_step_mm']:raise ValueError('Invalid cached grid reference frame')
            grid.blocked=bytearray(base64.b64decode(row['blocked'],validate=True));grid.supported=bytearray(base64.b64decode(row['supported'],validate=True))
            grid.distance_squared=array.array('d');grid.distance_squared.frombytes(base64.b64decode(row['distance_squared_le'],validate=True))
            if sys.byteorder!='little':grid.distance_squared.byteswap()
            if len(grid.blocked)!=count or len(grid.supported)!=count or len(grid.distance_squared)!=count:raise ValueError('Incomplete cached grid arrays')
            if any(v not in(0,1)for v in grid.blocked+grid.supported)or any(math.isnan(v)or v<0 for v in grid.distance_squared):raise ValueError('Invalid cached map values')
            return grid
        n.topological=payload['topological'];n.polygons=payload['polygons'];n.envelope=vehicle_envelope()
        n.sensor=model.resolved_sensor(config);n.reserve=n.sensor['clearance_mm']+config['geometry']['localization_tolerance_mm']
        n.radius=n.envelope['radius_mm'];n.height=n.envelope['height_mm']+config['geometry']['height_reserve_mm']
        n.navigation_margin_mm=model.reference(config,'walkthrough')['navigation']['contact_margin_mm']
        if payload['envelope']!=n.envelope or payload['reserve_mm']!=n.reserve or payload['height_mm']!=n.height:raise ValueError('Cached vehicle envelope or reserve differs')
        n.grids={level:decode_grid(grid)for level,grid in payload['grids'].items()};n.portals=payload['portals']
        from building_fleet_floor import floor_support
        for level,grid in n.grids.items():grid.floor_support=floor_support(n.mesh,level,config);grid._floor_edges={}
        n.road_hubs=payload['road_hubs'];n.waiting_bay_polygons=payload['waiting_bay_polygons']
        n.homes=payload['homes'];n.waits=payload['waits'];n.inspections={(row['level'],row['area']):row['data']for row in payload['inspections']}
        n.cabin_interior_mm=payload['cabin_interior_mm'];n.level_z=payload['level_z'];n.depot_rows=payload['depot_rows']
        if set(n.homes)!={f'BF{i:02d}'for i in range(1,21)}or set(n.inspections)!={(row['level'],row['area'])for row in config['missions']['targets']}:raise ValueError('Cached required homes or targets are incomplete')
        n._route_cache={}
        for row in payload['centreline_routes']:
            key=row['level'],tuple(row['start']),tuple(row['end']);n._route_cache[key]=row['route']
            n._route_cache[(key[0],key[2],key[1])]=reverse_centreline(row['route'])
        n._area_routes={};n._portal_proofs={};n._area_cells={};n.qualification={'native_route_checked':False,'fleet_compiled':False}
        return n

    def _derive_cabin(self, building):
        source = stack.expanded(building,stack.parameters(building))
        candidates=[op for op in source['operations'] if op['id']=='BuildingLiftCabin_Hollow']
        if len(candidates)!=1 or candidates[0]['shape']['kind']!='box':
            raise ValueError('Existing native-source cabin hollow required')
        shape=candidates[0]['shape'];lo=shape['origin'];hi=[lo[k]+shape['size'][k]for k in range(3)]
        self.cabin_interior_mm={'min':list(lo),'max':hi}

    def _derive_locations(self):
        threshold=self.radius+self.reserve
        self.level_z={row['id']:row['z_mm']for row in self.mesh.manifest['levels']}
        for level,data in self.topological.items():
            active=[p for p in self.mesh.manifest['elevator']['ports']if p['level_id']==level and p['active']]
            if len(active)!=1:raise ValueError('BF01 requires an explicit active landing side per level')
            port=active[0];landing=self.polygons[level][data['landing_neighbors'][port['id']][0]]
            candidates=[self.grids[level].centre(i)for i in self.grids[level].candidates(landing)
                        if nav.point_in_polygon(self.grids[level].centre(i),landing)
                        and self.grids[level].clearance_lower_mm(self.grids[level].centre(i))>=threshold]
            candidates.sort(key=lambda p:(math.dist(p,port['exit_eye_mm'][:2]),p))
            picked=[]
            for point in candidates:
                # Wait outside source door/shaft bounds; preserve the direct
                # landing approach by retaining a whole extra vehicle width.
                if math.dist(point,port['exit_eye_mm'][:2])<2*threshold:continue
                if all(math.dist(point,p)>2*self.radius+self.reserve for p in picked):picked.append(point)
                if len(picked)==2:break
            if not picked:raise ValueError('No free lift waiting place outside the door sweep: '+level)
            self.waits[level]=[[*p,0.]for p in picked]
        # Through-parking retains forward approach/exit routes with the other
        # nineteen vehicles parked. Sparse side bypasses prevent packing traps.
        level=self.config['depot']['level'];areas=self.config['depot']['areas'];count=self.config['depot']['slots']
        grids=self.grids[level];area_slots={a:[]for a in areas};self.depot_rows={}
        for area in areas:
            rows=depot_rows(grids,self.polygons[level][area],self.envelope['length_mm'],self.envelope['width_mm'],self.radius,self.reserve)
            self.depot_rows[area]=rows
            for row_index,row in enumerate(rows):
                for point in row['points']:area_slots[area].append((point,row_index,row))
        if any(not points for points in area_slots.values())or sum(map(len,area_slots.values()))<count:
            raise ValueError('Source depots lack twenty independently accessible forward through-parking bays; try a different native-proved layout before claiming physical impossibility')
        # Use both rooms, then consume the proved capacity; no fixed 10/10 split.
        selected={a:[]for a in areas};cursor=0
        while sum(map(len,selected.values()))<count:
            area=areas[cursor%len(areas)];cursor+=1
            if len(selected[area])<len(area_slots[area]):selected[area].append(area_slots[area][len(selected[area])])
        ident=1
        for area,points in selected.items():
            for slot,(point,row_index,row)in enumerate(points):
                d=row['distance_mm']
                self.homes[f'BF{ident:02d}']={'level':level,'area':area,'slot':slot,'row':row_index,
                    'pose_mm_rad':[*point,math.pi/2], 'departure_xy_mm':[point[0],point[1]+d],
                    'arrival_xy_mm':[point[0],point[1]-d], 'aisle_loop_mm':copy.deepcopy(row['aisle_loop_mm'])};ident+=1
        for target in self.config['missions']['targets']:
            level,area=target['level'],target['area']
            if level=='OG3' and area=='R3_003':
                # This special source-bound connector is compiled separately;
                # a generic inspection square must never replace L01 lanes.
                import building_fleet_l01
                definition=building_fleet_l01.definition(model.reference(self.config,'l01_route'))
                self.inspections[(level,area)]={'kind':'inspection_pass','resource':level+'.room.'+area,
                    'points_mm':[point[:2]for point in definition['world_points_xyz_mm']],
                    'basis':target['basis'],'connector_source':self.config['sources']['l01_route']['path'],
                    'corner_trim_mm':definition['corner_trim_mm'],'geometry_definition':definition}
                continue
            try:points=inspection_loop(self.grids[level],self.polygons[level][area],self.radius,self.reserve)
            except ValueError as error:raise ValueError(level+'/'+area+': '+str(error))from error
            self.inspections[(level,area)]={'points_mm':points,'resource':level+'.room.'+area,
                                           'basis':target['basis'],'kind':'inspection_pass'}

    def _derive_waiting_bays(self):
        """Reserve fixed source-derived bays; ordinary routes cannot use them.

        A road hub must retain a complete rotation envelope outside every
        parked bay. The hub is not itself a waiting place or a token grant.
        Its connections are separately proved by the static route graph.
        """
        from building_fleet_sim import footprint,point_segment_distance
        self.waiting_bay_polygons={};self.road_hubs={}
        for level,places in self.waits.items():
            port=next(p for p in self.mesh.manifest['elevator']['ports']if p['active']and p['level_id']==level)
            direction=1 if port['cabin_entry_mm'][0]>port['exit_eye_mm'][0]else-1
            # Face the cabin before stopping; no turn on the spot at the bay.
            for place in places:place[2]=0. if direction>0 else math.pi
            landing=self.polygons[level][self.topological[level]['landing_neighbors'][port['id']][0]]
            grid=self.grids[level];threshold=self.radius+self.reserve
            candidates=[grid.centre(i)for i in grid.candidates(landing)
                        if nav.point_in_polygon(grid.centre(i),landing)
                        and grid.clearance_lower_mm(grid.centre(i))>=threshold]
            def polygons(rows):
                return [footprint({'pose_mm':p,'footprint_mm':[self.envelope['length_mm'],self.envelope['width_mm']]})for p in rows]
            def free_hubs(bays):
                return [p for p in candidates if all(not nav.point_in_polygon(p,poly)
                         and min(point_segment_distance(p,a,b)for a,b in zip(poly,poly[1:]+poly[:1]))>=threshold
                         for poly in bays)]
            bays=polygons(places);hubs=free_hubs(bays)
            # Two waiting places are useful only when ordinary traffic retains
            # a free hub. One is a supported source-derived waiting capacity.
            if not hubs and len(places)>1:
                choices=[]
                for p in places:
                    ps=polygons([p]);hs=free_hubs(ps)
                    if hs:choices.append((math.dist(p[:2],port['exit_eye_mm'][:2]),p,ps,hs))
                if choices:
                    _,place,bays,hubs=min(choices,key=lambda row:(row[0],row[1]));self.waits[level]=[place]
            if not hubs:raise ValueError('No ordinary road hub outside fixed lift waiting bay envelopes: '+level)
            centre=[sum(p[k]for p in self.waits[level])/len(self.waits[level])for k in range(2)]
            hubs.sort(key=lambda p:(math.dist(p,centre),p))
            self.road_hubs[level]=hubs[0];self.waiting_bay_polygons[level]=bays

    def area_at(self, level, point):
        result=[area for area,poly in self.polygons[level].items()if area not in self.topological[level]['excluded_areas']and nav.point_in_polygon(point,poly)]
        if len(result)!=1:raise ValueError('Route endpoint must belong to one permitted source area: '+str((level,point,result)))
        return result[0]

    def _area_route(self,level,area,start,end):
        key=(level,area,tuple(start),tuple(end))
        if key in self._area_routes:return copy.deepcopy(self._area_routes[key])
        grid=self.grids[level];polygon=self.polygons[level][area];threshold=self.radius+self.reserve
        # The ordinary disc search is restricted to this area. Portal crossing
        # is a separate fixed-heading rectangle certificate, never a radius cut.
        def allowed(p):return nav.point_in_polygon(p,polygon)
        parked=[h['pose_mm_rad'][:2]for h in getattr(self,'homes',{}).values()if h['level']==level and h['area']==area]
        parked.extend(p[:2]for p in getattr(self,'waits',{}).get(level,[])if nav.point_in_polygon(p[:2],polygon))
        separation=2*self.radius+self.reserve
        def parked_free(a,b):
            from building_fleet_sim import point_segment_distance
            return all(point_segment_distance(point,a,b)>=separation-1e-7 for point in parked)
        def line(a,b):
            return segment_in_polygon(a,b,polygon)and parked_free(a,b)and grid.line_free(a,b,threshold)
        if line(start,end):result=[list(start),list(end)]
        else:
            first,last=grid.cell(start),grid.cell(end)
            if not hasattr(self,'_area_cells'):self._area_cells={}
            mask_key=(level,area)
            if mask_key not in self._area_cells:
                cells={};full=set();half=grid.resolution_mm/2
                for i in grid.candidates(polygon):
                    centre=grid.centre(i);lower=grid.clearance_lower_mm(centre)
                    if lower>=threshold and allowed(centre)and parked_free(centre,centre):
                        cells[i]=lower
                        square=[[centre[0]-half,centre[1]-half],[centre[0]+half,centre[1]-half],
                                [centre[0]+half,centre[1]+half],[centre[0]-half,centre[1]+half]]
                        if all(segment_in_polygon(a,b,polygon)for a,b in zip(square,square[1:]+square[:1]))and all(math.dist(centre,p)-math.sqrt(2)*half>=separation for p in parked):full.add(i)
                self._area_cells[mask_key]=(cells,full)
            cells,full=self._area_cells[mask_key]
            def usable(i):return i in cells
            if not usable(first)or not usable(last):raise ValueError('Area route endpoint needs a separate oriented clearance proof')
            queue=[(0,first)];cost={first:0.};previous={first:None};closed=set()
            while queue:
                _,i=heapq.heappop(queue)
                if i in closed:continue
                closed.add(i)
                if i==last:break
                x,y=i%grid.width,i//grid.width
                for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                    nx,ny=x+dx,y+dy
                    if not 0<=nx<grid.width or not 0<=ny<grid.height:continue
                    j=ny*grid.width+nx
                    if not usable(j):continue
                    distance=math.hypot(dx,dy)*grid.resolution_mm
                    if not(i in full and j in full and min(cells[i],cells[j])-distance/2>=threshold)and not line(grid.centre(i),grid.centre(j)):continue
                    new=cost[i]+distance*(1+threshold/max(threshold,cells[j]))
                    if new<cost.get(j,math.inf):cost[j]=new;previous[j]=i;heapq.heappush(queue,(new+math.dist(grid.centre(j),end),j))
            if last not in previous:raise ValueError('No conservative route inside source area '+level+'/'+area)
            raw=[];i=last
            while i is not None:raw.append(grid.centre(i));i=previous[i]
            raw.reverse();raw[0]=list(start);raw[-1]=list(end)
            result=[raw[0]];i=0
            while i<len(raw)-1:
                j=len(raw)-1
                while j>i+1 and not line(raw[i],raw[j]):j-=1
                if not line(raw[i],raw[j]):raise ValueError('Area route endpoint replacement is not certified')
                result.append(raw[j]);i=j
        self._area_routes[key]=result;return copy.deepcopy(result)

    def _portal(self,level,portal,source_area):
        key=(level,portal['id'],source_area)
        if key in self._portal_proofs:return copy.deepcopy(self._portal_proofs[key])
        if source_area not in portal['areas']:
            raise ValueError('Portal must adjoin the requested source area')
        if portal['opening_width_mm']<self.envelope['width_mm']+2*self.reserve:
            raise ValueError('Door is narrower than the physical footprint and declared reserve: '+portal['id'])
        if portal.get('opening'):
            doors=[o for o in self.mesh.manifest['objects']if o.get('mechanism')=='room_door'and o.get('level_id')==level and o.get('opening_id')==portal['opening']]
            if len(doors)!=1 or doors[0].get('initial_state',doors[0]['reference_state'])!='open':
                raise ValueError('Route door is not explicitly open in the checked start state: '+portal['id'])
        destination=next(area for area in portal['areas']if area!=source_area)
        maximum=(portal['opening_width_mm']-self.envelope['width_mm'])/2-self.reserve
        step=self.config['geometry']['grid_step_mm'];offsets=[0.]
        for offset in range(step,math.floor(maximum/step)*step+1,step):offsets.extend([offset,-offset])
        rejected=[];a=b=None
        for offset in offsets:
            centre=[portal['centre_mm'][k]+offset*portal['tangent'][k]for k in range(2)]
            def anchor(area):
                polygon=self.polygons[level][area];xs,ys=zip(*polygon)
                maximum_distance=math.hypot(max(xs)-min(xs),max(ys)-min(ys))
                minimum=self.envelope['length_mm']/2+self.reserve
                for sign in(-1,1):
                    edge=[centre[k]+sign*step*1e-6*portal['normal'][k]for k in range(2)]
                    if not nav.point_in_polygon(edge,polygon):continue
                    for distance in range(math.ceil(minimum/step)*step,math.ceil(maximum_distance/step)*step+1,step):
                        point=[centre[k]+sign*distance*portal['normal'][k]for k in range(2)]
                        if not nav.point_in_polygon(point,polygon):continue
                        if self.grids[level].clearance_lower_mm(point)>=self.radius+self.reserve and segment_in_polygon(edge,point,polygon):return point
                return None
            x,y=anchor(source_area),anchor(destination)
            if x is None or y is None:
                rejected.append({'tangent_offset_mm':offset,'reason':'No conservative rotation-capable anchor on the source-derived door normal'});continue
            yaw=math.atan2(y[1]-x[1],y[0]-x[0])
            if self.grids[level].line_free(x,y,self.radius+self.reserve):
                a,b=x,y;certificate='native raster Lipschitz disc';break
            collisions=nav.native_rectangle_collisions(self.mesh,level,x,y,yaw,self.envelope['length_mm']/2,
                self.envelope['width_mm']/2,self.height,self.reserve)
            if not collisions:a,b=x,y;certificate='fixed-yaw native triangle swept rectangle';break
            rejected.append({'tangent_offset_mm':offset,'bodies':collisions})
        if a is None:raise ValueError('No native-proved fixed-yaw portal sweep: '+portal['id']+' '+repr(rejected))
        result={'id':portal['id'],'points_mm':[a,b],'source_area':source_area,
                'destination_area':destination,
                'kind':'room'if any(x.startswith(('R','K0_'))for x in portal['areas'])else'passage',
                'reserve_mm':self.reserve,'certificate':certificate,'yaw_rad':yaw}
        self._portal_proofs[key]=result;return copy.deepcopy(result)

    def _straight_hits(self,level,a,b):
        if not hasattr(self,'_straight_cache'):self._straight_cache={}
        key=(level,tuple(a),tuple(b))
        if key in self._straight_cache:return self._straight_cache[key][:]
        yaw=math.atan2(b[1]-a[1],b[0]-a[0]);c,s=math.cos(yaw),math.sin(yaw);distance=math.dist(a,b)
        half_length=self.envelope['length_mm']/2+self.reserve;half_width=self.envelope['width_mm']/2+self.reserve
        lo,hi=-half_length,distance+half_length;hits=[]
        for area in self.topological[level]['excluded_areas']:
            if area not in self.polygons[level]:continue
            poly=[[(p[0]-a[0])*c+(p[1]-a[1])*s,-(p[0]-a[0])*s+(p[1]-a[1])*c]for p in self.polygons[level][area]]
            if nav.polygon_touches_box(poly,lo,-half_width,hi,half_width):hits.append('ExcludedArea.'+area)
        from building_fleet_sim import footprint
        for ident,home in self.homes.items():
            if home['level']!=level:continue
            physical=footprint({'pose_mm':home['pose_mm_rad'],'footprint_mm':[self.envelope['length_mm'],self.envelope['width_mm']]})
            poly=[[(p[0]-a[0])*c+(p[1]-a[1])*s,-(p[0]-a[0])*s+(p[1]-a[1])*c]for p in physical]
            if nav.polygon_touches_box(poly,lo,-half_width,hi,half_width):hits.append('ReservedDepotBay.'+ident)
        for slot,physical in enumerate(getattr(self,'waiting_bay_polygons',{}).get(level,[])):
            poly=[[(p[0]-a[0])*c+(p[1]-a[1])*s,-(p[0]-a[0])*s+(p[1]-a[1])*c]for p in physical]
            if nav.polygon_touches_box(poly,lo,-half_width,hi,half_width):hits.append('ReservedLiftWaitingBay.'+level+'.'+str(slot))
        hits.extend(nav.native_rectangle_collisions(self.mesh,level,a,b,yaw,self.envelope['length_mm']/2,
            self.envelope['width_mm']/2,self.height,self.reserve))
        if not hits:
            from building_fleet_floor import floor_support
            import building_fleet_support as support_rule
            bank=floor_support(self.mesh,level,self.config)
            mesh_error=self.mesh.scene['linear_tessellation_deflection_mm']+math.sqrt(3)*self.mesh.scene['maximum_float32_error_mm']
            proof=bank.covers([(x+y)/2 for x,y in zip(a,b)],yaw,
                math.dist(a,b)/2+self.envelope['length_mm']/2+self.reserve+mesh_error,
                self.envelope['width_mm']/2+self.reserve+mesh_error,
                curve_ref={'scope':'fixed_heading_route','level':level,'points_mm':[list(a),list(b)]})
            if not proof['passed']:hits.append('NativeFloorSupportR1')
        self._straight_cache[key]=hits[:];self._straight_cache[(level,tuple(b),tuple(a))]=hits[:]
        return hits

    def _rectangle_candidate(self,level,start,end):
        """Width-filtered search proposes a path; full swept rectangles prove it.

        The smaller search radius is never a qualification radius. Every full
        segment, its floor band and excluded source areas are checked below;
        corners remain explicitly unqualified until the C2/native program audit.
        """
        if not hasattr(self,'_travel_grids'):self._travel_grids={}
        if level not in self._travel_grids:
            grid=copy.copy(self.grids[level]);grid.blocked=bytearray(grid.blocked)
            from building_fleet_sim import footprint
            for home in self.homes.values():
                if home['level']==level:
                    poly=footprint({'pose_mm':home['pose_mm_rad'],'footprint_mm':[self.envelope['length_mm'],self.envelope['width_mm']]})
                    grid.raster(poly)
            for poly in getattr(self,'waiting_bay_polygons',{}).get(level,[]):grid.raster(poly)
            self._travel_grids[level]=grid.finalize()
        grid=self._travel_grids[level]
        base=self.envelope['width_mm']/2+self.reserve;points=None;failures=[]
        # Cell-centre/touched-cell conservatism can reject an otherwise open
        # rectangular corridor. Relax only this proposal filter by one/two
        # source raster steps; full native reserve below remains unchanged.
        for radius in(base,max(1,base-grid.resolution_mm),max(1,base-2*grid.resolution_mm)):
            try:proposed=grid.search(start,end,radius)
            except ValueError as error:failures.append(str(error));continue
            repaired=[proposed[0]];valid=True
            for a,b in zip(proposed,proposed[1:]):
                hit=self._straight_hits(level,a,b)
                if not hit:repaired.append(b);continue
                alternatives=[[a,[b[0],a[1]],b],[a,[a[0],b[1]],b]]
                alternative=next((points for points in alternatives if all(math.dist(x,y)>1e-7 and grid.line_free(x,y,radius)
                                  and not self._straight_hits(level,x,y)for x,y in zip(points,points[1:]))),None)
                if alternative:repaired.extend(alternative[1:])
                else:failures.append('Full rectangle candidate edge '+repr((a,b))+' intersects '+repr(hit));valid=False;break
            if valid:points=repaired;break
        if points is None:
            # A disc shortcut may cut a corner that the full oriented body
            # cannot pass. Repeat the source-grid search with the actual
            # fixed-heading sweep at edges AND shortcut reduction, rather
            # than hand-inserting a target-specific coordinate into a cache.
            def edge_free(a,b):
                if grid.proposal_line_free(a,b,self.radius+self.reserve):return True
                return not self._straight_hits(level,a,b)
            for radius in(base,max(1,base-grid.resolution_mm),max(1,base-2*grid.resolution_mm)):
                try:
                    candidate=grid.search(start,end,radius,edge_validator=edge_free)
                    if all(not self._straight_hits(level,a,b)for a,b in zip(candidate,candidate[1:])):
                        points=candidate;break
                except ValueError as error:failures.append(str(error))
        if points is None:raise ValueError('No full-native-rectangle candidate: '+repr(failures))
        proofs=[]
        for index,(a,b)in enumerate(zip(points,points[1:])):
            yaw=math.atan2(b[1]-a[1],b[0]-a[0]);collisions=self._straight_hits(level,a,b)
            if collisions:raise ValueError('Full candidate swept rectangle collides on segment '+str(index)+': '+','.join(collisions))
            proofs.append({'segment_index':index,'certificate':'fixed-yaw native triangle swept rectangle','yaw_rad':yaw,'reserve_mm':self.reserve})
        resources=[];zones=[]
        for portal in self.portals[level]:
            normal,tangent,centre=portal['normal'],portal['tangent'],portal['centre_mm']
            for i,(a,b)in enumerate(zip(points,points[1:])):
                da=sum((a[k]-centre[k])*normal[k]for k in range(2));db=sum((b[k]-centre[k])*normal[k]for k in range(2))
                if da*db>0 or abs(da-db)<1e-9:continue
                u=da/(da-db);crossing=[a[k]+u*(b[k]-a[k])for k in range(2)]
                if abs(sum((crossing[k]-centre[k])*tangent[k]for k in range(2)))>portal['opening_width_mm']/2:continue
                if portal.get('opening'):
                    doors=[o for o in self.mesh.manifest['objects']if o.get('level_id')==level and o.get('opening_id')==portal['opening']and o.get('mechanism')=='room_door']
                    if len(doors)!=1 or doors[0].get('initial_state',doors[0]['reference_state'])!='open':raise ValueError('Candidate crosses a route door not open at start')
                resources.append({'id':portal['id'],'kind':'passage','start_index':max(0,i-1),'end_index':min(len(points)-1,i+2),
                                  'crossing_mm':crossing,'segment_index':i,'segment_fraction':u,
                                  'areas':portal['areas']})
                zones.append({'start_index':max(0,i-1),'end_index':min(len(points)-1,i+2),'velocity_mm_s':self.config['motion']['zone_velocity_mm_s']})
        return {'level':level,'points_mm':points,'resources':resources,'zone_segments':zones,'portal_certificates':proofs,
                'curve_qualified':False,'reserve_mm':self.reserve,'search':'width candidate + full native fixed-heading rectangles; C2 corners pending'}

    def route(self,level,startxy,endxy):
        startxy=list(startxy[:2]);endxy=list(endxy[:2]);key=(level,tuple(startxy),tuple(endxy))
        if key in self._route_cache:return self._own_right(copy.deepcopy(self._route_cache[key]))
        source,target=self.area_at(level,startxy),self.area_at(level,endxy)
        try:
            candidate=self._rectangle_candidate(level,startxy,endxy)
            return self._remember_route(key,candidate)
        except ValueError:
            pass  # A failed candidate is not physical unreachability; try graph alternatives.
        # Area graph search is independent of the raster. A failed oriented
        # portal is retained as a failure and is not silently narrowed.
        graph=collections.defaultdict(list)
        for portal in self.portals[level]:
            a,b=portal['areas'];graph[a].append((b,portal));graph[b].append((a,portal))
        serial=0;queue=[(math.dist(startxy,endxy),0.,serial,source,startxy,[])];best={(source,tuple(startxy)):0.};selected=None;rejections=[]
        while queue:
            _,cost,_,area,position,history=heapq.heappop(queue)
            if cost>best.get((area,tuple(position)),math.inf):continue
            if area==target:
                try:
                    final=self._area_route(level,area,position,endxy);selected=(history,final);break
                except ValueError as error:rejections.append(str(error))
            for other,portal in graph[area]:
                try:
                    proof=self._portal(level,portal,area);approach=proof['points_mm'];within=self._area_route(level,area,position,approach[0])
                except ValueError as error:
                    rejections.append(str(error));continue
                addition=sum(math.dist(a,b)for a,b in zip(within,within[1:]))+math.dist(*approach)
                new=cost+addition;state=(other,tuple(approach[1]))
                if new<best.get(state,math.inf)-1e-7:
                    best[state]=new;serial+=1;heapq.heappush(queue,(new+math.dist(approach[1],endxy),new,serial,other,approach[1],history+[(within,proof)]))
        if selected is None:
            try:return self._remember_route(key,self._rectangle_candidate(level,startxy,endxy))
            except ValueError as error:raise ValueError('No proved route between source areas '+source+' / '+target+'; full-width candidate: '+str(error)+'; area graph failures: '+repr(sorted(set(rejections))))from error
        edges,final=selected;points=[startxy];resources=[];zones=[];proofs=[]
        def append(rows):
            for point in rows:
                if math.dist(points[-1],point)>1e-7:points.append(list(point))
        for within,proof in edges:
            approach=proof['points_mm'];append(within);begin=len(points)-1
            append(approach);end=len(points)-1;proofs.append(proof)
            resources.append({'id':proof['id'],'kind':proof['kind'],'start_index':begin,'end_index':end})
            zones.append({'start_index':begin,'end_index':end,'velocity_mm_s':self.config['motion']['zone_velocity_mm_s']})
        append(final)
        result={'level':level,'points_mm':points,'resources':resources,'zone_segments':zones,'portal_certificates':proofs,
                'curve_qualified':False,'reserve_mm':self.reserve}
        return self._remember_route(key,result)

    def _remember_route(self,key,result):
        self._route_cache[key]=copy.deepcopy(result)
        level,start,end=key;reverse=reverse_centreline(result)
        self._route_cache[(level,end,start)]=reverse
        return self._own_right(copy.deepcopy(result))

    def _own_right(self,result):
        """Direction-specific paired lanes; centreline caches stay reversible.

        Only full paired native rectangle proposals in source corridor areas
        receive right lanes. Merges and non-qualified spans remain exclusive.
        Rounded curves and simultaneous temporal occupancy still require their
        independent program audit; no JavaScript or controller replans them.
        """
        level=result['level'];original=result['points_mm'];points=[original[0]];wide=[];narrow=[];zones=[];merges=[]
        kinds={area['id']:area['kind']for area in self.topological[level]['plan']['areas']}
        sensor=getattr(self,'sensor',{})
        perception_gap=sensor.get('clearance_mm',0)+sensor.get('range_error_mm',0)+sensor.get('range_mm',0)*math.sin(math.radians(sensor.get('angular_step_deg',0)))+self.config.get('geometry',{}).get('localization_tolerance_mm',0)
        passing_gap=max(self.reserve,perception_gap)+getattr(self,'navigation_margin_mm',0)
        offset=(self.envelope['width_mm']+passing_gap)/2;guard=2*self.radius+self.reserve
        for a,b in zip(original,original[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1];cuts={0.,1.}
            for polygon in self.polygons[level].values():
                for p,q in zip(polygon,polygon[1:]+polygon[:1]):
                    ex,ey=q[0]-p[0],q[1]-p[1];cross=dx*ey-dy*ex
                    if abs(cross)<1e-9:continue
                    px,py=p[0]-a[0],p[1]-a[1];t,u=(px*ey-py*ex)/cross,(px*dy-py*dx)/cross
                    if 1e-8<t<1-1e-8 and 0<=u<=1:cuts.add(t)
            cuts=sorted(cuts)
            for lower,upper in zip(cuts,cuts[1:]):
                x=[a[k]+(b[k]-a[k])*lower for k in range(2)];y=[a[k]+(b[k]-a[k])*upper for k in range(2)]
                if math.dist(x,y)<1e-5:continue
                centre=[(x[k]+y[k])/2 for k in range(2)]
                try:area=self.area_at(level,centre)
                except ValueError:area='source-boundary'
                begin=len(points)-1;length=math.dist(x,y);tangent=[(y[k]-x[k])/length for k in range(2)];right=[tangent[1],-tangent[0]]
                lane=None
                if kinds.get(area)=='corridor'and length>4*guard+self.envelope['length_mm']+2*self.reserve:
                    entry=[x[k]+guard*tangent[k]for k in range(2)];exit=[y[k]-guard*tangent[k]for k in range(2)]
                    candidates=[]
                    for sign in(1,-1):
                        first=[x[k]+2*guard*tangent[k]+sign*offset*right[k]for k in range(2)]
                        last=[y[k]-2*guard*tangent[k]+sign*offset*right[k]for k in range(2)]
                        proposed=[x,entry,first,last,exit,y]
                        if any(self._straight_hits(level,p,q)for p,q in zip(proposed,proposed[1:])):break
                        candidates.append(proposed)
                    if len(candidates)==2:lane=candidates[0]
                if lane:
                    for point in lane[1:]:
                        if math.dist(points[-1],point)>1e-7:points.append(point)
                    wide.append({'area':area,'start_index':begin+2,'end_index':begin+3,
                                 'offset_mm':offset,'passing_gap_mm':passing_gap,'paired_static_rectangle_checked':True,'curve_qualified':False})
                    for index,anchor in((begin,lane[0]),(begin+3,lane[-1])):
                        node=','.join(str(round(v/(2*guard)))for v in anchor)
                        merges.append({'id':level+'.merge.'+area+'.'+node,'kind':'passage',
                                       'start_index':index,'end_index':min(begin+5,index+2),'basis':'exclusive source-area lane merge'})
                else:
                    if math.dist(points[-1],y)>1e-7:points.append(y)
                    if kinds.get(area)=='corridor':
                        narrow.append({'id':level+'.narrow.'+area,'kind':'passage','start_index':begin,
                                       'end_index':len(points)-1,'basis':'paired native lane proposal not qualified; conservative exclusive span'})
                if kinds.get(area)!='corridor':zones.append({'start_index':begin,'end_index':len(points)-1,
                    'velocity_mm_s':self.config['motion']['zone_velocity_mm_s']})
        # Source doors stay at the same boundary coordinates. Rebind their
        # windows to the refined own-direction polyline, never to reverse lanes.
        for row in result['resources']:
            if 'crossing_mm'in row:
                target=row['crossing_mm'];best=(math.inf,0)
                for i,(a,b)in enumerate(zip(points,points[1:])):
                    from building_fleet_sim import point_segment_distance
                    gap=point_segment_distance(target,a,b)
                    if gap<best[0]:best=(gap,i)
                row['start_index']=max(0,best[1]-1);row['end_index']=min(len(points)-1,best[1]+2)
            else:
                a=original[row['start_index']];b=original[row['end_index']]
                row['start_index']=min(range(len(points)),key=lambda i:math.dist(points[i],a))
                row['end_index']=min(range(len(points)),key=lambda i:math.dist(points[i],b))
        result['centreline_mm']=original;result['points_mm']=points
        result['centreline_portal_certificates']=result['portal_certificates']
        result['portal_certificates']=[]
        for i,(a,b)in enumerate(zip(points,points[1:])):
            hit=self._straight_hits(level,a,b)
            if hit:raise ValueError('Direction-specific lane proposal failed actual swept rectangle '+repr(hit))
            result['portal_certificates'].append({'segment_index':i,'certificate':'fixed-yaw native triangle swept rectangle',
                'yaw_rad':math.atan2(b[1]-a[1],b[0]-a[0]),'reserve_mm':self.reserve})
        result['resources'].extend(narrow+merges);result['zone_segments']=zones+[
            {'start_index':r['start_index'],'end_index':r['end_index'],'velocity_mm_s':self.config['motion']['zone_velocity_mm_s']}
            for r in result['resources']if r.get('crossing_mm')]
        result['right_lane_segments']=wide;result['bottleneck_spans']=narrow+merges
        result['curve_qualified']=False
        return result
