"""BF01 world-only sensing and independent interval clearance audit.

Only this module consumes simultaneous vehicle truth. Its sensor output is an
anonymous first-return scan; controllers must receive neither ``truth`` nor
this world's internal spatial index. These primitives do not themselves claim
a completed fleet mission or a native BRep proof.
"""
import collections
import math
from functools import cached_property

from building_fleet_model import scan_beam_count
from l01_local_traffic import ray_disc,ray_box
import tr01_floor_motion as floor


def ray_segment(ox, oy, dx, dy, a, b):
    """Nonnegative first ray/closed-segment intersection, including endpoints."""
    sx, sy = b[0]-a[0], b[1]-a[1]
    cross = dx*sy-dy*sx
    qx, qy = a[0]-ox, a[1]-oy
    if abs(cross) < 1e-12:
        if abs(qx*dy-qy*dx) > 1e-9:
            return math.inf
        values = [(p[0]-ox)*dx+(p[1]-oy)*dy for p in (a,b)]
        if max(values) < 0: return math.inf
        return max(0, min(values))
    distance = (qx*sy-qy*sx)/cross
    fraction = (qx*dy-qy*dx)/cross
    return distance if distance >= -1e-9 and -1e-9 <= fraction <= 1+1e-9 else math.inf


def point_segment_distance(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    norm = dx*dx+dy*dy
    u = min(1, max(0, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/norm)) if norm else 0
    return math.hypot(point[0]-a[0]-u*dx, point[1]-a[1]-u*dy)


def footprint(row):
    length,width = row['footprint_mm']; x,y,yaw = row['pose_mm']; c,s = math.cos(yaw),math.sin(yaw)
    if length <= 0 or width <= 0 or not all(math.isfinite(v) for v in [length,width]):
        raise ValueError('Conservative positive native footprint required')
    return [(x+c*dx-s*dy,y+s*dx+c*dy) for dx,dy in
            [(-length/2,-width/2),(length/2,-width/2),(length/2,width/2),(-length/2,width/2)]]


def polygon_segment_distance(polygon, a, b):
    edges = list(zip(polygon,polygon[1:]+polygon[:1]))
    def inside(point):
        cross = [(q[0]-p[0])*(point[1]-p[1])-(q[1]-p[1])*(point[0]-p[0]) for p,q in edges]
        return all(v >= -1e-9 for v in cross) or all(v <= 1e-9 for v in cross)
    if inside(a) or inside(b): return 0.
    dx,dy = b[0]-a[0],b[1]-a[1]; length = math.hypot(dx,dy)
    if length:
        for p,q in edges:
            if ray_segment(*a,dx/length,dy/length,p,q) <= length+1e-9:
                return 0.
    return min([*[point_segment_distance(p,a,b) for p in polygon],
                *[point_segment_distance(p,ea,eb) for p in (a,b) for ea,eb in edges]])


def _polygon_distance_uncached(first, second):
    return min(min(polygon_segment_distance(first,a,b) for a,b in zip(second,second[1:]+second[:1])),
               min(polygon_segment_distance(second,a,b) for a,b in zip(first,first[1:]+first[:1])))


_POLYGON_DISTANCE_CACHE=collections.OrderedDict()
_POLYGON_DISTANCE_FUNCTIONS=None


def polygon_distance(first,second):
    """Cache exact ordered vertices only; callers retain all live conditions."""
    global _POLYGON_DISTANCE_FUNCTIONS
    functions=(_polygon_distance_uncached,polygon_segment_distance,point_segment_distance,ray_segment)
    previous=_POLYGON_DISTANCE_FUNCTIONS
    if previous is None or any(a is not b for a,b in zip(previous,functions)):
        _POLYGON_DISTANCE_FUNCTIONS=functions;_POLYGON_DISTANCE_CACHE.clear()
    polygons=[]
    for polygon in(first,second):
        if type(polygon)not in(list,tuple)or len(polygon)<3:return _polygon_distance_uncached(first,second)
        points=[]
        for point in polygon:
            if type(point)not in(list,tuple)or len(point)!=2:return _polygon_distance_uncached(first,second)
            values=[]
            for value in point:
                if type(value)is float and math.isfinite(value):values.append(('float',value.hex()))
                elif type(value)is int:values.append(('int',value))
                else:return _polygon_distance_uncached(first,second)
            points.append(tuple(values))
        polygons.append(tuple(points))
    key=tuple(polygons);cache=_POLYGON_DISTANCE_CACHE
    if key in cache:
        cache.move_to_end(key);return cache[key]
    result=_polygon_distance_uncached(first,second);cache[key]=result
    if len(cache)>2048:cache.popitem(last=False)
    return result


class SegmentIndex:
    """Uniform cells accelerate exact ray tests, without changing returns."""
    def __init__(self, segments, cell_mm=500):
        if not math.isfinite(cell_mm) or cell_mm <= 0:
            raise ValueError('Positive ray-index cell size required')
        self.segments = [(tuple(a), tuple(b)) for a,b in segments]; self.cell = cell_mm; self.cells = {}
        for index, (a,b) in enumerate(self.segments):
            for x in range(math.floor(min(a[0],b[0])/cell_mm), math.floor(max(a[0],b[0])/cell_mm)+1):
                for y in range(math.floor(min(a[1],b[1])/cell_mm), math.floor(max(a[1],b[1])/cell_mm)+1):
                    self.cells.setdefault((x,y), []).append(index)

    @cached_property
    def _ray_bounds(self):
        # Derived from the occupied cells for both native and restored indexes.
        # A one-cell margin includes every side cell visited at a grid corner.
        if not self.cells:
            return None
        xs, ys = zip(*self.cells)
        return ((min(xs)-1)*self.cell, (min(ys)-1)*self.cell,
                (max(xs)+2)*self.cell, (max(ys)+2)*self.cell)

    def ray(self, origin, direction, distance):
        ox,oy=origin;dx,dy=direction;ix,iy=math.floor(ox/self.cell),math.floor(oy/self.cell)
        bounds = self._ray_bounds
        if bounds is None:
            return distance
        xmin, ymin, xmax, ymax = bounds
        if (ox < xmin and ox + dx*distance < xmin or ox > xmax and ox + dx*distance > xmax or
                oy < ymin and oy + dy*distance < ymin or oy > ymax and oy + dy*distance > ymax):
            # On a unit beam of at most 2^16 cells, accumulated binary64
            # traversal error is below the margin. Keep the original traversal
            # for extreme coordinates, ranges or non-unit fixture directions.
            if (0 <= distance <= 65536*self.cell and abs(dx) <= 1 and abs(dy) <= 1 and
                    abs(ix) < 2**40 and abs(iy) < 2**40):
                return distance
        sx,sy=(1 if dx>=0 else-1),(1 if dy>=0 else-1)
        tx=((ix+(1 if sx>0 else 0))*self.cell-ox)/dx if dx else math.inf
        ty=((iy+(1 if sy>0 else 0))*self.cell-oy)/dy if dy else math.inf
        stepx=self.cell/abs(dx)if dx else math.inf;stepy=self.cell/abs(dy)if dy else math.inf
        seen=set();best=distance
        while True:
            for index in self.cells.get((ix,iy),()):
                if index in seen:continue
                seen.add(index);best=min(best,ray_segment(ox,oy,dx,dy,*self.segments[index]))
            boundary=min(tx,ty)
            if best<boundary or boundary>distance:return best
            # At a grid corner both side cells may contain a tangent endpoint.
            # Visit them too before the diagonal cell, retaining closed edges.
            if tx==ty:
                for cell in((ix+sx,iy),(ix,iy+sy)):
                    for index in self.cells.get(cell,()):
                        if index not in seen:
                            seen.add(index);best=min(best,ray_segment(ox,oy,dx,dy,*self.segments[index]))
                ix+=sx;iy+=sy;tx+=stepx;ty+=stepy
            elif tx<ty:ix+=sx;tx+=stepx
            else:iy+=sy;ty+=stepy

    def nearest(self, point, radius):
        candidates = set(); x,y = point
        for ix in range(math.floor((x-radius)/self.cell), math.floor((x+radius)/self.cell)+1):
            for iy in range(math.floor((y-radius)/self.cell), math.floor((y+radius)/self.cell)+1):
                candidates.update(self.cells.get((ix,iy), ()))
        return min(radius, min((point_segment_distance(point,*self.segments[i]) for i in candidates), default=radius))

    def matches(self,point,tolerance):
        """Actual map-match observation, unlike a capped clearance lower bound."""
        x,y=point;candidates=set()
        for ix in range(math.floor((x-tolerance)/self.cell),math.floor((x+tolerance)/self.cell)+1):
            for iy in range(math.floor((y-tolerance)/self.cell),math.floor((y+tolerance)/self.cell)+1):candidates.update(self.cells.get((ix,iy),()))
        return any(point_segment_distance(point,*self.segments[i])<=tolerance for i in candidates)


class SensorWorld:
    """Synthetic 360-degree horizontal first-return model, one level at a time.

    Static segments must be native height-band slices in the initial door pose.
    Vehicle returns use full conservative oriented rectangles, with an explicit
    disc-only fixture fallback. Floors, error bounds and stale delivery remain
    separate contracts; this ideal generator adds no random noise.
    """
    def __init__(self, settings, static_segments_by_level, cell_mm=500, cabin_segments_by_sides=None, landing_segments_by_level_sides=None,
                 prepared_indices=None):
        self.settings = dict(settings)
        step = settings['angular_step_deg']
        count = scan_beam_count(step)
        if settings['range_mm'] <= 0:
            raise ValueError('A positive scan range is required')
        if prepared_indices is None:
            self.static = {level:SegmentIndex(segments,cell_mm) for level,segments in static_segments_by_level.items()}
            self.cabin={tuple(sides):SegmentIndex(segments,cell_mm)for sides,segments in(cabin_segments_by_sides or{}).items()}
            self.landings={(level,tuple(sides)):SegmentIndex(segments,cell_mm)
                           for(level,sides),segments in(landing_segments_by_level_sides or{}).items()}
        else:
            if set(prepared_indices) != {'static','cabin','landings'}:
                raise ValueError('All three checked source ray-index mappings are required')
            self.static,self.cabin,self.landings=(prepared_indices[name]for name in('static','cabin','landings'))
            if (set(self.static)!=set(static_segments_by_level)or
                    set(self.cabin)!=set(cabin_segments_by_sides or{})or
                    set(self.landings)!=set(landing_segments_by_level_sides or{})):
                raise ValueError('Prepared indices must cover the same complete source geometry')
        self.scans = 0; self.rays = 0;self.rectangle_rays=0;self.disc_rays=0
        self._beam_angles = tuple((angle, math.sin(angle), math.cos(angle))
                                  for angle in (math.radians(index * step) for index in range(count)))
        self.peer_candidates=0;self.range_pruned_peers=0
        self._raw_cache=collections.OrderedDict();self._raw_cache_limit=128
        self.raw_cache_hits=0;self.raw_cache_misses=0;self.raw_rays=0
        self._static_cache=collections.OrderedDict();self._static_cache_limit=128
        self.static_cache_hits=0;self.static_cache_misses=0;self.static_rays=0

    @staticmethod
    def visible(own, other, lift):
        if abs(own['z_mm']-other['z_mm']) > 1e-6:
            return False
        if not own.get('aboard',False) and not other.get('aboard',False):
            return own['level'] == other['level']
        if own.get('aboard',False) and other.get('aboard',False):
            return True
        return bool(lift['doors_open'] and own['level'] == other['level'] == lift['level'])

    @staticmethod
    def rectangle_can_return(ox,oy,c,s,box,sensor_range):
        """Reject only boxes no source beam can reach before the range cap.

        Each computed peer-frame direction component is bounded by the outward
        rounded L1 rotation norm, since both source beam components lie in
        [-1,1]. A positive slab-entry numerator uses exactly the subtraction
        and division of ray_box. Monotone floating-point division therefore
        proves that every possible entry is at or beyond the range cap. This
        bounds the complete rectangle, including rotated corners; no centre
        distance or approximate angular visibility test discards a peer.
        """
        bound=math.nextafter(abs(c)+abs(s),math.inf)
        if (not all(math.isfinite(v)for v in (ox,oy,bound,*box))or bound<=0
                or box[0]>box[2]or box[1]>box[3]):return True
        for origin,minimum,maximum in zip((ox,oy),box[:2],box[2:]):
            gap=minimum-origin if origin<minimum else origin-maximum if origin>maximum else 0.
            if gap/bound>=sensor_range:return False
        return True

    @staticmethod
    def _exact_key(value):
        # Numeric equality alone collapses signed zero and large int/float
        # distinctions. Keep the actual arithmetic inputs, with no rounding.
        if type(value)is float:return ('float',value.hex())
        if isinstance(value,(list,tuple)):return tuple(SensorWorld._exact_key(v)for v in value)
        return (type(value).__name__,value)

    def _rectangle_beams(self, yaw, c, s, ox, oy, box, sensor_range):
        """Broad phase for a rectangle's angular extent, with exact ray tests after it."""
        count = len(self._beam_angles)
        all_beams = range(count)
        if (not abs(yaw) <= 1e6 or not 0 < sensor_range <= 1e12 or
                not all(math.isfinite(v) and abs(v) <= 1e12 for v in (ox, oy, *box)) or
                box[:2] != (-box[2], -box[3]) or min(box[2:]) <= 0):
            return all_beams
        if not math.isclose(math.hypot(c, s), 1., rel_tol=0, abs_tol=1e-14):
            return all_beams

        # A reported hit before the range cap can miss the true slab by at
        # most range * 1e-12 on each ray_box near-parallel axis. Include both
        # axes, plus arithmetic roundoff, in the enclosing disc.
        scale = max(sensor_range, abs(ox), abs(oy), box[2], box[3])
        radius = math.hypot(box[2], box[3]) + 2e-12 * sensor_range + 64 * math.ulp(scale)
        distance = math.hypot(ox, oy)
        if distance <= radius:
            return all_beams
        half_angle = math.asin(radius / distance)
        centre = (math.atan2(-oy, -ox) + math.atan2(s, c) - yaw) % math.tau
        step = math.radians(self.settings['angular_step_deg'])
        # Retain one complete beam outside each rounded angular endpoint.
        # Also covers cancellation in subtracting yaw before wrapping.
        start = math.floor((centre - half_angle) / step) - 1
        stop = math.ceil((centre + half_angle) / step) + 2
        if stop - start >= count:
            return all_beams
        return (index % count for index in range(start, stop))

    def _first_returns(self,x,y,yaw,static,landing,cabin,peers):
        """Raw ideal distances only; no timestamps, output lists or noise."""
        sensor_range=self.settings['range_mm']
        directions=tuple((math.cos(yaw+angle),math.sin(yaw+angle))for angle,_,_ in self._beam_angles)
        key=(self._exact_key((x,y,yaw,sensor_range)),static,landing,cabin)
        static_distances=self._static_cache.get(key)
        if static_distances is None:
            self.static_cache_misses+=1;values=[]
            for dx,dy in directions:
                distance=static.ray((x,y),(dx,dy),sensor_range)if static is not None else sensor_range
                if landing is not None:distance=min(distance,landing.ray((x,y),(dx,dy),sensor_range))
                if cabin is not None:distance=min(distance,cabin.ray((x,y),(dx,dy),sensor_range))
                values.append(distance)
            static_distances=tuple(values);self.static_rays+=len(directions)
            if self._static_cache_limit:
                self._static_cache[key]=static_distances
                if len(self._static_cache)>self._static_cache_limit:self._static_cache.popitem(last=False)
        else:
            self.static_cache_hits+=1;self._static_cache.move_to_end(key)
        # Each beam still sees the static minimum followed by peers in their
        # original order, including signed-zero ties.
        distances = list(static_distances)
        for peer in peers:
            if peer[0] == 'rectangle':
                _,c,s,ox,oy,box=peer
                count = 0
                for index in self._rectangle_beams(yaw, c, s, ox, oy, box, sensor_range):
                    dx,dy=directions[index]
                    rx,ry=dx*c+dy*s,-dx*s+dy*c
                    distances[index]=min(distances[index],ray_box(ox,oy,rx,ry,box))
                    count += 1
                self.rectangle_rays += count
            else:
                _,cx,cy,radius=peer
                for index,(dx,dy) in enumerate(directions):
                    distances[index]=min(distances[index],ray_disc(x,y,dx,dy,cx,cy,radius))
                self.disc_rays += len(directions)
        self.raw_rays+=len(self._beam_angles)
        return tuple(distances)

    def scan(self, vehicle_id, truth, now, lift):
        own = truth[vehicle_id]; x,y,yaw = own['pose_mm']; sensor_range = self.settings['range_mm']
        if own['level'] not in self.static:
            raise ValueError('Native static scan geometry missing at the own level')
        on_floor=abs(own.get('floor_z_mm',own['z_mm'])-own['z_mm'])<1e-6
        static=self.static[own['level']]if on_floor else None
        sides=tuple(sorted(lift.get('open_sides',())))if lift['doors_open']else()
        landed=(on_floor and own['level']==lift.get('level')
                and abs(own['z_mm']-lift.get('z_mm',math.inf))<1e-6)
        landing=self.landings.get((own['level'],sides if landed else()),self.landings.get((own['level'],())))if on_floor else None
        cabin=self.cabin.get(sides)if(own.get('aboard',False)or abs(own['z_mm']-lift.get('z_mm',math.inf))<1e-6)else None
        peers=[];peer_keys=[]
        for key,other in truth.items():
            if key==vehicle_id or not self.visible(own,other,lift):continue
            self.peer_candidates+=1
            if 'footprint_mm'in other:
                cx,cy,heading=other['pose_mm'];c,s=math.cos(heading),math.sin(heading)
                length,width=other['footprint_mm'];box=(-length/2,-width/2,length/2,width/2)
                ox,oy=(x-cx)*c+(y-cy)*s,-(x-cx)*s+(y-cy)*c
                if not self.rectangle_can_return(ox,oy,c,s,box,sensor_range):
                    self.range_pruned_peers+=1;continue
                peers.append(('rectangle',c,s,ox,oy,box));shape=other['footprint_mm']
            else:
                peers.append(('disc',*other['pose_mm'][:2],other['radius_mm']));shape=other['radius_mm']
            peer_keys.append(self._exact_key((other['pose_mm'],shape,other['level'],other['z_mm'],other.get('aboard',False),peers[-1])))
        # All lift branches are resolved above into the actual selected source
        # indexes and visible peer geometry. These are precisely the immutable
        # inputs to _first_returns; unrelated lift travel cannot change them.
        key=(self._exact_key((own['pose_mm'],own['level'],own['z_mm'],own.get('floor_z_mm',own['z_mm']),own.get('aboard',False))),
             self._exact_key(sensor_range),static,landing,cabin,tuple(peer_keys))
        distances=self._raw_cache.get(key)
        if distances is None:
            self.raw_cache_misses+=1
            distances=self._first_returns(x,y,yaw,static,landing,cabin,peers)
            if self._raw_cache_limit:
                self._raw_cache[key]=distances
                if len(self._raw_cache)>self._raw_cache_limit:self._raw_cache.popitem(last=False)
        else:
            self.raw_cache_hits+=1;self._raw_cache.move_to_end(key)
        returns=[]
        for (_,local_side,local_forward),distance in zip(self._beam_angles,distances):
            if distance < sensor_range:
                returns.append([local_side*distance,local_forward*distance])
        self.scans += 1; self.rays += len(self._beam_angles)
        return {'captured_s':now, 'returns_local_mm':returns}

    def statistics(self):
        return {'scans':self.scans, 'rays':self.rays,
                'static_index':'uniform cells, exact ray/segment first intersections',
                'dynamic_returns':'anonymous full oriented native-envelope rectangles at own cabin height; explicit disc-only fixture fallback',
                'rectangle_ray_tests':self.rectangle_rays,'disc_fixture_ray_tests':self.disc_rays,
                'visible_peer_candidates':self.peer_candidates,'whole_rectangle_range_rejections':self.range_pruned_peers,
                'raw_beam_evaluations':self.raw_rays,
                'source_geometry_beam_evaluations':self.static_rays,
                'source_geometry_cache':{'hits':self.static_cache_hits,'misses':self.static_cache_misses,
                    'entries':len(self._static_cache),'capacity':self._static_cache_limit,
                    'key':'exact own ray frame/range and strong selected immutable source indices',
                    'value':'ordered static, landing and cabin minimum only; current peers are merged afterward'},
                'raw_first_return_cache':{'hits':self.raw_cache_hits,'misses':self.raw_cache_misses,
                    'entries':len(self._raw_cache),'capacity':self._raw_cache_limit,
                    'key':'exact own pose, immutable selected source indexes, ordered relevant exact peer geometry; no pose quantization',
                    'value':'immutable ideal capped beam distances only; timestamps and output lists are fresh'},
                'landing_door_returns':'source closed doors on non-cabin floors; source open active-side pose only at the fully open aligned cabin',
                'people_simulated':False, 'real_sensor_qualified':False}


class IntervalAuditor:
    """Disc lower bounds from both endpoints and whole-interval speed bounds.

    Let L bound relative speed. The closest endpoint is at most dt/2 away in
    time, so min(endpoint gaps)-L*dt/2 is a valid lower distance bound. This is
    deliberately independent of controllers, scans and resource ownership.
    A disc rejection can use a conservative native-rectangle fallback only when
    an explicit whole-interval angular-speed bound is supplied too. The latter
    bounds rotational surface motion by circumscribed radius * angular speed.
    Actual native BRep checks remain separate.
    """
    def __init__(self, clearance_mm, static_by_level, *, prepared_indices=None):
        if not math.isfinite(clearance_mm) or clearance_mm < 0:
            raise ValueError('Nonnegative declared reserve required')
        self.clearance = clearance_mm
        self.static = ({level:SegmentIndex(segments) for level,segments in static_by_level.items()}
                       if prepared_indices is None else prepared_indices)
        if set(self.static)!=set(static_by_level):
            raise ValueError('Prepared audit indices must cover the complete source geometry')
        self.minima = {'vehicle_vehicle':math.inf, 'vehicle_static':math.inf}
        self.checks = 0; self.oriented_fallbacks = 0;self.refined_intervals=0

    @staticmethod
    def _extent(length,width,low,high):
        half_l,half_w=length/2,width/2
        if high-low>=2*math.pi:return math.hypot(half_l,half_w)
        values=[low,high];angle=math.atan2(half_w,half_l)
        for k in range(math.floor(low/math.pi)-2,math.ceil(high/math.pi)+3):
            for theta in(k*math.pi+angle,k*math.pi-angle):
                if low<=theta<=high:values.append(theta)
        return max(half_l*abs(math.cos(v))+half_w*abs(math.sin(v))for v in values)

    @classmethod
    def curve_box(cls,row,curve,start,end):
        bounds=floor.extrema(curve,start,end);lo,hi=bounds['min'],bounds['max']
        if 'footprint_mm'in row:
            length,width=row['footprint_mm'];hx=cls._extent(length,width,lo[2],hi[2]);hy=cls._extent(width,length,lo[2],hi[2])
        else:hx=hy=row['radius_mm']
        return {'min':[lo[0]-hx,lo[1]-hy],'max':[hi[0]+hx,hi[1]+hy]},bounds

    @staticmethod
    def _box_gap(a,b):
        return math.hypot(*[max(0,a['min'][k]-b['max'][k],b['min'][k]-a['max'][k])for k in range(2)])

    def _pair_curve_bound(self,a,b,first,second,start,end,depth=0):
        self.refined_intervals+=1
        first_box,first_bounds=self.curve_box(a,first,start,end);second_box,second_bounds=self.curve_box(b,second,start,end)
        lower=self._box_gap(first_box,second_box)
        if lower>=self.clearance-1e-6:return lower
        mid=(start+end)/2;pa=first.evaluate(mid)[floor.F[0]];pb=second.evaluate(mid)[floor.F[0]]
        if 'footprint_mm'in a and 'footprint_mm'in b:
            actual=polygon_distance(footprint(dict(a,pose_mm=pa)),footprint(dict(b,pose_mm=pb)))
        else:actual=math.dist(pa[:2],pb[:2])-a['radius_mm']-b['radius_mm']
        if actual<self.clearance-1e-6:raise RuntimeError('BF01 actual pair clearance below declared reserve')
        if depth>=20 or end-start<=1e-7:raise RuntimeError('BF01 pair interval could not be certified without reducing reserve')
        return min(self._pair_curve_bound(a,b,first,second,start,mid,depth+1),self._pair_curve_bound(a,b,first,second,mid,end,depth+1))

    def _static_curve_bound(self,row,curve,index,start,end,depth=0):
        self.refined_intervals+=1;box,bounds=self.curve_box(row,curve,start,end)
        candidates=set()
        for x in range(math.floor((box['min'][0]-self.clearance)/index.cell),math.floor((box['max'][0]+self.clearance)/index.cell)+1):
            for y in range(math.floor((box['min'][1]-self.clearance)/index.cell),math.floor((box['max'][1]+self.clearance)/index.cell)+1):candidates.update(index.cells.get((x,y),()))
        if not candidates:return self.clearance
        mid=(start+end)/2;pose=curve.evaluate(mid)[floor.F[0]]
        if 'footprint_mm'in row:
            polygon=footprint(dict(row,pose_mm=pose));actual=min(polygon_segment_distance(polygon,*index.segments[i])for i in candidates)
        else:actual=min(point_segment_distance(pose[:2],*index.segments[i])for i in candidates)-row['radius_mm']
        movement=math.hypot(*[max(abs(bounds[k][i]-pose[i])for k in('min','max'))for i in range(2)])
        movement+=row['radius_mm']*max(abs(bounds[k][2]-pose[2])for k in('min','max'))
        lower=actual-movement
        if lower>=self.clearance-1e-6:return lower
        if actual<self.clearance-1e-6:raise RuntimeError('BF01 actual static clearance below declared reserve')
        if depth>=20 or end-start<=1e-7:raise RuntimeError('BF01 static interval could not be certified without reducing reserve')
        return min(self._static_curve_bound(row,curve,index,start,mid,depth+1),self._static_curve_bound(row,curve,index,mid,end,depth+1))

    @staticmethod
    def motion_bound(value):
        if isinstance(value,dict):
            if set(value) != {'linear_mm_s','yaw_rad_s'}:
                raise ValueError('Explicit linear and angular interval bounds required')
            v,w = value['linear_mm_s'],value['yaw_rad_s']
        else: v,w = value,None
        if not math.isfinite(v) or v < 0 or w is not None and (not math.isfinite(w) or w < 0):
            raise ValueError('Conservative finite motion bounds required')
        return v,w

    @staticmethod
    def shape_bound(a,b,linear,angular):
        if angular is None or 'footprint_mm' not in a or 'footprint_mm' not in b:
            return None
        if a['footprint_mm'] != b['footprint_mm']:
            raise ValueError('The conservative footprint cannot change during a drive interval')
        radius = math.hypot(*a['footprint_mm'])/2
        return linear+radius*angular

    def static_rectangle_bound(self, index, a,b, linear,angular,dt):
        bound = self.shape_bound(a,b,linear,angular)
        if bound is None: return -math.inf
        endpoint = min(self._static_endpoint_distance(index, row) for row in (a,b))
        return endpoint-bound*dt/2

    def _pair_endpoint_distance(self,first,second):
        """Reuse exact planar geometry, never a motion or interval certificate."""
        functions=(footprint,polygon_distance,polygon_segment_distance,point_segment_distance,ray_segment)
        previous=getattr(self,'_pair_endpoint_functions',None)
        if previous is None or any(a is not b for a,b in zip(previous,functions)):
            self._pair_endpoint_functions=functions
            self._pair_endpoint_distances=collections.OrderedDict()
            self._endpoint_footprints=collections.OrderedDict()
        def key(row):
            result=[]
            for field in('pose_mm','footprint_mm'):
                values=[]
                for value in row[field]:
                    if type(value)is float and math.isfinite(value):values.append(('float',value.hex()))
                    elif type(value)is int:values.append(('int',value))
                    else:return None
                result.append(tuple(values))
            return tuple(result)
        a,b=key(first),key(second)
        if a is None or b is None:return polygon_distance(footprint(first),footprint(second))
        pair=(a,b);distances=self._pair_endpoint_distances
        if pair in distances:
            distances.move_to_end(pair);return distances[pair]
        polygons=[];corners=self._endpoint_footprints
        for row,identity in((first,a),(second,b)):
            if identity not in corners:
                corners[identity]=tuple(tuple(point)for point in footprint(row))
                if len(corners)>2048:corners.popitem(last=False)
            else:corners.move_to_end(identity)
            # Keep the same list-of-tuples primitive input without exposing
            # mutable cache storage to a geometric caller.
            polygons.append(list(corners[identity]))
        result=polygon_distance(*polygons);distances[pair]=result
        if len(distances)>2048:distances.popitem(last=False)
        return result

    @staticmethod
    def _static_endpoint_distance(index, row):
        polygon = footprint(row)
        if not hasattr(index, '_endpoint_source'):
            from types import MappingProxyType
            # Freeze the exact source at first use, allowing other floors to
            # restore their checked source indices only when first requested.
            index.segments = tuple(index.segments)
            index._endpoint_source = index.segments
            index.cells = MappingProxyType({cell:tuple(members)for cell,members in index.cells.items()})
            index._endpoint_cells = index.cells
            index._endpoint_cell = (type(index.cell),float(index.cell).hex())
            index._endpoint_scale = max((abs(value)for segment in index.segments for point in segment for value in point),default=1.)
            index._endpoint_segment_length = max((math.dist(*segment)for segment in index.segments),default=0.)
            index._endpoint_distances = collections.OrderedDict()
        if (getattr(index, '_endpoint_source', None) is not index.segments or
                index._endpoint_cells is not index.cells or
                index._endpoint_cell != (type(index.cell),float(index.cell).hex())):
            return min((polygon_segment_distance(polygon, *segment)
                        for segment in index.segments), default=math.inf)
        key = tuple(tuple(float(value).hex() for value in point) for point in polygon)
        cache = index._endpoint_distances
        if key not in cache:
            # A segment omitted by this padded cell query is farther than the
            # expansion margin from the polygon AABB. Once an actual original
            # distance is within that margin, no omitted segment can improve
            # it. Padding only widens candidate selection; it never changes a
            # measured distance, contact predicate or declared reserve.
            edges=[math.dist(a,b)for a,b in zip(polygon,polygon[1:]+polygon[:1])]
            scale=max(index._endpoint_scale,1.,*[abs(v)for p in polygon for v in p],*edges)
            fallback=(not index.segments or not all(math.isfinite(v)and v>0 for v in edges)or
                not math.isfinite(scale)or scale>math.sqrt(float.fromhex('0x1.fffffffffffffp+1023'))/16)
            # Degenerate rounded rectangles cannot supply the separating-box
            # argument used below. Preserve the original complete scan there.
            turns=[abs((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
                   for a,b,c in zip(polygon,polygon[1:]+polygon[:1],polygon[2:]+polygon[:2])]
            if any(turn<.5*edges[i]*edges[(i+1)%4]for i,turn in enumerate(turns)):fallback=True
            gap=math.inf;best_index=len(index.segments);seen=set();margin=index.cell
            # Cover the unchanged primitives' closed-contact arithmetic as
            # well as outward rounding of very large translated coordinates.
            padding=(1024*math.ulp(scale)+4e-9/min(edges)+
                     4e-9*max(index._endpoint_segment_length,*edges))if not fallback else 0.
            bounds=[min(p[k]for p in polygon)for k in range(2)]+[max(p[k]for p in polygon)for k in range(2)]
            while not fallback:
                limits=[math.floor((bounds[k]-margin-padding)/index.cell)-1 for k in range(2)]+[
                    math.floor((bounds[k+2]+margin+padding)/index.cell)+1 for k in range(2)]
                count=(limits[2]-limits[0]+1)*(limits[3]-limits[1]+1)
                if count>max(4096,4*len(index.cells)):
                    fallback=True;break
                candidates=set()
                for x in range(limits[0],limits[2]+1):
                    for y in range(limits[1],limits[3]+1):candidates.update(index.cells.get((x,y),()))
                for i in sorted(candidates-seen):
                    if type(i)is not int or not 0<=i<len(index.segments):fallback=True;break
                    actual=polygon_segment_distance(polygon,*index.segments[i])
                    if math.isnan(actual):fallback=True;break
                    if actual<gap or actual==gap and i<best_index:gap,best_index=actual,i
                if fallback:break
                seen.update(candidates)
                if gap<=margin or len(seen)==len(index.segments):break
                margin*=2
            cache[key] = (min((polygon_segment_distance(polygon,*segment)for segment in index.segments),default=math.inf)
                          if fallback else gap)
            if len(cache) > 128:
                cache.popitem(last=False)
        else:
            cache.move_to_end(key)
        return cache[key]

    def audit(self, previous, current, dt, speed_bounds, *,curves=None,start_s=None,end_s=None):
        if not math.isfinite(dt) or dt <= 0 or set(previous) != set(current) or set(current) != set(speed_bounds):
            raise ValueError('Complete simultaneous endpoint truth and positive interval required')
        if curves is not None and(set(curves)!=set(current)or start_s is None or end_s is None or abs(end_s-start_s-dt)>1e-8):
            raise ValueError('Complete actual PVA interval curves and exact time window required')
        vehicles = sorted(current)
        for vehicle in vehicles:
            a,b = previous[vehicle],current[vehicle]; speed,angular = self.motion_bound(speed_bounds[vehicle])
            if math.dist(a['pose_mm'][:2],b['pose_mm'][:2]) > speed*dt+1e-6:
                raise ValueError('Actual displacement exceeds supplied motion bound')
            if angular is not None:
                difference = abs(math.remainder(b['pose_mm'][2]-a['pose_mm'][2],2*math.pi))
                if difference > angular*dt+1e-9:
                    raise ValueError('Actual yaw displacement exceeds supplied angular bound')
            if a.get('aboard',False) or b.get('aboard',False):
                continue  # Dynamic cabin and portal boundaries have a separate native proof.
            if a['level'] != b['level']:
                raise ValueError('Floor transition outside the cabin')
            index = self.static[a['level']]; radius = max(a['radius_mm'],b['radius_mm'])
            search = radius+self.clearance+speed*dt
            gap = min(index.nearest(p['pose_mm'][:2],search) for p in (a,b))-radius-speed*dt/2
            if gap < self.clearance-1e-6:
                oriented = self.static_rectangle_bound(index,a,b,speed,angular,dt)
                if oriented >= self.clearance-1e-6:
                    gap = oriented; self.oriented_fallbacks += 1
            if gap<self.clearance-1e-6 and curves is not None:
                gap=self._static_curve_bound(b,curves[vehicle],index,start_s,end_s)
            self.minima['vehicle_static'] = min(self.minima['vehicle_static'],gap)
            if gap < self.clearance-1e-6:
                raise RuntimeError('BF01 static interval clearance below declared reserve: '+vehicle)
        for i,vehicle in enumerate(vehicles):
            for other in vehicles[i+1:]:
                a,b = previous[vehicle],current[vehicle]; c,d = previous[other],current[other]
                if a['level'] != c['level'] or b['level'] != d['level']:
                    continue
                if any(abs(p['z_mm']-q['z_mm']) > 1e-6 for p,q in ((a,c),(b,d))):
                    continue
                radius = max(a['radius_mm'],b['radius_mm'])+max(c['radius_mm'],d['radius_mm'])
                gap = min(math.dist(a['pose_mm'][:2],c['pose_mm'][:2]),math.dist(b['pose_mm'][:2],d['pose_mm'][:2]))-radius
                v1,w1 = self.motion_bound(speed_bounds[vehicle]); v2,w2 = self.motion_bound(speed_bounds[other])
                gap -= (v1+v2)*dt/2
                if gap < self.clearance-1e-6:
                    b1,b2 = self.shape_bound(a,b,v1,w1),self.shape_bound(c,d,v2,w2)
                    if b1 is not None and b2 is not None:
                        oriented = min(self._pair_endpoint_distance(a,c),self._pair_endpoint_distance(b,d))-(b1+b2)*dt/2
                        if oriented >= self.clearance-1e-6:
                            gap = oriented; self.oriented_fallbacks += 1
                if gap<self.clearance-1e-6 and curves is not None:
                    gap=self._pair_curve_bound(b,d,curves[vehicle],curves[other],start_s,end_s)
                self.minima['vehicle_vehicle'] = min(self.minima['vehicle_vehicle'],gap)
                if gap < self.clearance-1e-6:
                    raise RuntimeError('BF01 pair interval clearance below declared reserve: '+vehicle+'/'+other)
        self.checks += 1

    def statistics(self):
        return {'intervals':self.checks, 'lower_bounds_mm':{k:v if math.isfinite(v) else None for k,v in self.minima.items()},
                'oriented_fallbacks':self.oriented_fallbacks,
                'polynomial_refinement_intervals':self.refined_intervals,
                'scope':'Disc broad phase with explicit angular-bound native-rectangle fallback; cabin/door native BRep proofs required separately'}
