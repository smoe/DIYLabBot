"""BF01 world-only sensing and independent interval clearance audit.

Only this module consumes simultaneous vehicle truth. Its sensor output is an
anonymous first-return scan; controllers must receive neither ``truth`` nor
this world's internal spatial index. These primitives do not themselves claim
a completed fleet mission or a native BRep proof.
"""
import math

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


def polygon_distance(first, second):
    return min(min(polygon_segment_distance(first,a,b) for a,b in zip(second,second[1:]+second[:1])),
               min(polygon_segment_distance(second,a,b) for a,b in zip(first,first[1:]+first[:1])))


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

    def ray(self, origin, direction, distance):
        ox,oy=origin;dx,dy=direction;ix,iy=math.floor(ox/self.cell),math.floor(oy/self.cell)
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
    Vehicle returns are conservative discs. Floors, scan error bounds and stale
    delivery are separate contracts; this ideal generator adds no random noise.
    """
    def __init__(self, settings, static_segments_by_level, cell_mm=500, cabin_segments_by_sides=None):
        self.settings = dict(settings)
        step = settings['angular_step_deg']
        if type(step) is not int or step <= 0 or 360 % step or settings['range_mm'] <= 0:
            raise ValueError('A full-circle integer beam grid and positive range required')
        self.static = {level:SegmentIndex(segments,cell_mm) for level,segments in static_segments_by_level.items()}
        self.cabin={tuple(sides):SegmentIndex(segments,cell_mm)for sides,segments in(cabin_segments_by_sides or{}).items()}
        self.scans = 0; self.rays = 0;self.rectangle_rays=0;self.disc_rays=0

    @staticmethod
    def visible(own, other, lift):
        if abs(own['z_mm']-other['z_mm']) > 1e-6:
            return False
        if not own.get('aboard',False) and not other.get('aboard',False):
            return own['level'] == other['level']
        if own.get('aboard',False) and other.get('aboard',False):
            return True
        return bool(lift['doors_open'] and own['level'] == other['level'] == lift['level'])

    def scan(self, vehicle_id, truth, now, lift):
        own = truth[vehicle_id]; x,y,yaw = own['pose_mm']; sensor_range = self.settings['range_mm']
        if own['level'] not in self.static:
            raise ValueError('Native static scan geometry missing at the own level')
        others=[p for key,p in truth.items()if key!=vehicle_id and self.visible(own,p,lift)]
        returns = []
        for degrees in range(0,360,self.settings['angular_step_deg']):
            angle = math.radians(degrees); heading = yaw+angle; dx,dy = math.cos(heading),math.sin(heading)
            on_floor=abs(own.get('floor_z_mm',own['z_mm'])-own['z_mm'])<1e-6
            distance=self.static[own['level']].ray((x,y),(dx,dy),sensor_range)if on_floor else sensor_range
            sides=tuple(sorted(lift.get('open_sides',())))if lift['doors_open']else()
            cabin=self.cabin.get(sides)
            if cabin is not None and(own.get('aboard',False)or abs(own['z_mm']-lift.get('z_mm',math.inf))<1e-6):
                distance=min(distance,cabin.ray((x,y),(dx,dy),sensor_range))
            for other in others:
                if 'footprint_mm'in other:
                    cx,cy,heading=other['pose_mm'];c,s=math.cos(heading),math.sin(heading)
                    length,width=other['footprint_mm']
                    ox,oy=(x-cx)*c+(y-cy)*s,-(x-cx)*s+(y-cy)*c
                    rx,ry=dx*c+dy*s,-dx*s+dy*c
                    measured=ray_box(ox,oy,rx,ry,[-length/2,-width/2,length/2,width/2]);self.rectangle_rays+=1
                else:
                    measured=ray_disc(x,y,dx,dy,*other['pose_mm'][:2],other['radius_mm']);self.disc_rays+=1
                distance=min(distance,measured)
            if distance < sensor_range:
                returns.append([math.sin(angle)*distance,math.cos(angle)*distance])
        self.scans += 1; self.rays += 360//self.settings['angular_step_deg']
        return {'captured_s':now, 'returns_local_mm':returns}

    def statistics(self):
        return {'scans':self.scans, 'rays':self.rays,
                'static_index':'uniform cells, exact ray/segment first intersections',
                'dynamic_returns':'anonymous full oriented native-envelope rectangles at own cabin height; explicit disc-only fixture fallback',
                'rectangle_ray_tests':self.rectangle_rays,'disc_fixture_ray_tests':self.disc_rays,
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
    def __init__(self, clearance_mm, static_by_level):
        if not math.isfinite(clearance_mm) or clearance_mm < 0:
            raise ValueError('Nonnegative declared reserve required')
        self.clearance = clearance_mm
        self.static = {level:SegmentIndex(segments) for level,segments in static_by_level.items()}
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
        polygons = [footprint(row) for row in (a,b)]
        endpoint = min((polygon_segment_distance(poly,*segment) for poly in polygons for segment in index.segments), default=math.inf)
        return endpoint-bound*dt/2

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
                        oriented = min(polygon_distance(footprint(a),footprint(c)),polygon_distance(footprint(b),footprint(d)))-(b1+b2)*dt/2
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
