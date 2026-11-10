"""Analytic FK derivatives and conservative numerical interval motion bounds.

Coordinates follow pickup.Kinematics: fixed construction frames, six local-Z
revolute joints, a rigid base and a flange-to-tool offset, all lengths in mm.
Sample points must be fixed TOOL-local coordinates. This is kinematics only;
neither limits nor these numerical enclosures establish biological suitability.
"""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion

LINEAR = ('position_mm', 'velocity_mm_s', 'acceleration_mm_s2', 'jerk_mm_s3')
ANGULAR = ('angular_velocity_rad_s', 'angular_acceleration_rad_s2', 'angular_jerk_rad_s3')
BINOMIAL = ((1,), (1, 1), (1, 2, 1), (1, 3, 3, 1))


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite kinematic coordinate required')
    return float(value)


def _outward(value, direction):
    return math.nextafter(value, direction) if value else 0.


class Interval:
    """Binary64 interval enclosure; not a formal floating-point certificate."""
    __slots__ = ('lo', 'hi')

    def __init__(self, lo, hi=None):
        self.lo, self.hi = _finite(lo), _finite(lo if hi is None else hi)
        if self.lo > self.hi:
            raise ValueError('Invalid numerical interval')

    @staticmethod
    def lift(value):
        return value if isinstance(value, Interval) else Interval(value)

    def __add__(self, other):
        other = self.lift(other)
        return Interval(_outward(self.lo + other.lo, -math.inf),
                        _outward(self.hi + other.hi, math.inf))

    __radd__ = __add__

    def __neg__(self):
        return Interval(-self.hi, -self.lo)

    def __sub__(self, other):
        return self + -self.lift(other)

    def __rsub__(self, other):
        return self.lift(other) + -self

    def __mul__(self, other):
        other = self.lift(other)
        products = (self.lo * other.lo, self.lo * other.hi,
                    self.hi * other.lo, self.hi * other.hi)
        return Interval(_outward(min(products), -math.inf), _outward(max(products), math.inf))

    __rmul__ = __mul__

    def sin(self):
        if self.hi - self.lo >= 2 * math.pi or max(abs(self.lo), abs(self.hi)) > 1e12:
            return Interval(-1., 1.)
        values = [math.sin(self.lo), math.sin(self.hi)]
        for phase, value in ((math.pi / 2, 1.), (-math.pi / 2, -1.)):
            if math.ceil((self.lo - phase) / (2 * math.pi)) <= math.floor((self.hi - phase) / (2 * math.pi)):
                values.append(value)
        return Interval(max(-1., _outward(min(values), -math.inf)),
                        min(1., _outward(max(values), math.inf)))

    def cos(self):
        return (self + math.pi / 2).sin()


class Jet:
    """Value and actual time derivatives through third order (not Taylor terms)."""
    __slots__ = ('d',)

    def __init__(self, value, velocity=0., acceleration=0., jerk=0.):
        self.d = (value, velocity, acceleration, jerk)

    @staticmethod
    def lift(value):
        return value if isinstance(value, Jet) else Jet(value)

    def __add__(self, other):
        other = self.lift(other)
        return Jet(*(a + b for a, b in zip(self.d, other.d)))

    __radd__ = __add__

    def __neg__(self):
        return Jet(*(-value for value in self.d))

    def __sub__(self, other):
        return self + -self.lift(other)

    def __rsub__(self, other):
        return self.lift(other) + -self

    def __mul__(self, other):
        other = self.lift(other)
        return Jet(*(sum(BINOMIAL[n][k] * self.d[k] * other.d[n - k]
                         for k in range(n + 1)) for n in range(4)))

    __rmul__ = __mul__

    def sincos(self):
        x, v, a, j = self.d
        s = x.sin() if isinstance(x, Interval) else math.sin(x)
        c = x.cos() if isinstance(x, Interval) else math.cos(x)
        return (Jet(s, c * v, c * a - s * v * v,
                    c * j - 3 * s * v * a - c * v * v * v),
                Jet(c, -s * v, -s * a - c * v * v,
                    -s * j - 3 * c * v * a + s * v * v * v))


def _matrix(value):
    if len(value) != 4 or any(len(row) != 4 for row in value):
        raise ValueError('A rigid 4x4 frame is required')
    m = [[_finite(x) for x in row] for row in value]
    if m[3] != [0., 0., 0., 1.]:
        raise ValueError('Invalid homogeneous frame')
    if any(abs(sum(m[k][i] * m[k][j] for k in range(3)) - int(i == j)) > 1e-8
           for i in range(3) for j in range(3)):
        raise ValueError('Kinematic frames must be rigid')
    determinant = sum(m[0][i] * (m[1][(i + 1) % 3] * m[2][(i + 2) % 3]
                                 - m[1][(i + 2) % 3] * m[2][(i + 1) % 3]) for i in range(3))
    if determinant < 0:
        raise ValueError('Kinematic frames must preserve orientation')
    return m


def _inverse(m):
    return [[m[j][i] for j in range(3)] + [-sum(m[j][i] * m[j][3] for j in range(3))]
            for i in range(3)] + [[0., 0., 0., 1.]]


def _multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _compose(rotation, position, constant):
    return ([[sum(rotation[i][k] * constant[k][j] for k in range(3)) for j in range(3)]
             for i in range(3)],
            [position[i] + sum(rotation[i][k] * constant[k][3] for k in range(3)) for i in range(3)])


def _point(rotation, position, local):
    return [position[i] + sum(rotation[i][k] * local[k] for k in range(3)) for i in range(3)]


def _linear(jets):
    return {name: [value.d[order] for value in jets] for order, name in enumerate(LINEAR)}


class KinematicJets:
    """Compile static frame products once for repeated derivative evaluations."""
    def __init__(self, kin):
        frames = [_matrix(frame) for frame in kin.frames]
        if not frames:
            raise ValueError('Joint frames are required')
        self.start = _multiply(_matrix(kin.base), frames[0])
        self.bridges = [_multiply(_inverse(a), b) for a, b in zip(frames, frames[1:])]
        self.bridges.append(_inverse(frames[-1]))
        self.tool = [_finite(x) for x in kin.flange]
        if len(self.tool) != 3:
            raise ValueError('A three-dimensional flange offset is required')
        self.tool[2] += _finite(kin.length)

    def _raw(self, state, points_mm):
        q = [Jet(*(state[field][i] for field in motion.FIELDS)) for i in range(len(self.bridges))]
        rotation = [[Jet(self.start[i][j]) for j in range(3)] for i in range(3)]
        position = [Jet(self.start[i][3]) for i in range(3)]
        angular = [[0., 0., 0.] for _ in ANGULAR]
        for joint, bridge in zip(q, self.bridges):
            # A joint axis depends on preceding joints, not on its own turn.
            for axis in range(3):
                z = rotation[axis][2].d
                angular[0][axis] += z[0] * joint.d[1]
                angular[1][axis] += z[1] * joint.d[1] + z[0] * joint.d[2]
                angular[2][axis] += z[2] * joint.d[1] + 2 * z[1] * joint.d[2] + z[0] * joint.d[3]
            sine, cosine = joint.sincos()
            rotation = [[row[0] * cosine + row[1] * sine,
                         -row[0] * sine + row[1] * cosine, row[2]] for row in rotation]
            rotation, position = _compose(rotation, position, bridge)
        tool = _point(rotation, position, self.tool)
        return {**_linear(tool), 'rotation': [[v.d[0] for v in row] for row in rotation],
                **dict(zip(ANGULAR, angular)),
                'points': [_linear(_point(rotation, tool, local)) for local in points_mm]}

    def evaluate(self, state, points_mm=()):
        try:
            values = {field: [_finite(x) for x in state[field]] for field in motion.FIELDS}
        except KeyError:
            raise ValueError('Joint position, velocity, acceleration and jerk are required') from None
        if any(len(v) != len(self.bridges) for v in values.values()):
            raise ValueError('Joint state dimension must match kinematic frames')
        result = self._raw(values, _local_points(points_mm))
        numbers = [x for name in (*LINEAR, *ANGULAR) for x in result[name]]
        numbers += [x for point in result['points'] for vector in point.values() for x in vector]
        if not all(math.isfinite(x) for x in numbers):
            raise ValueError('FK derivative overflow')
        return result


def _local_points(points):
    result = [[_finite(value) for value in point] for point in points]
    if any(len(point) != 3 for point in result):
        raise ValueError('Sample points must be three-dimensional TOOL-local coordinates')
    return result


def evaluate(kin, state, points_mm=()):
    return (kin if isinstance(kin, KinematicJets) else KinematicJets(kin)).evaluate(state, points_mm)


def _polynomial_interval(coefficients, lower, upper, factor):
    candidates = [lower, upper, *motion.real_roots(motion.derivative(coefficients), lower, upper)]
    values = [motion.polynomial(coefficients, u) / factor for u in candidates]
    return Interval(_outward(min(values), -math.inf), _outward(max(values), math.inf))


def _norm_upper(vector):
    result = math.sqrt(math.fsum(max(abs(x.lo), abs(x.hi)) ** 2
                                if isinstance(x, Interval) else x * x for x in vector))
    if not math.isfinite(result):
        raise ValueError('FK interval bounds overflow')
    return _outward(result, math.inf)


def bounds(kin, points, points_mm=(), subdivisions=2):
    """Enclose motion norms over the whole curve, not only sampled instants.

    Exact numerical polynomial-extremum ranges for q/v/a/j are propagated
    through interval trigonometry and third-order FK jets. Correlations are
    discarded, so the enclosure may overestimate maxima. Subdivision tightens
    it. Binary64 root/trigonometric arithmetic is not a formal FP certificate.
    """
    if type(subdivisions) is not int or subdivisions < 1:
        raise ValueError('A positive integer subdivision count is required')
    model = kin if isinstance(kin, KinematicJets) else KinematicJets(kin)
    curve = points if isinstance(points, motion.Curve) else motion.Curve(points)
    if len(curve.points[0][motion.FIELDS[0]]) != len(model.bridges):
        raise ValueError('Curve dimension must match kinematic frames')
    local = _local_points(points_mm)
    tool = {field: 0. for field in LINEAR[1:]}
    samples = [{field: 0. for field in LINEAR[1:]} for _ in local]
    angular = {field: 0. for field in ANGULAR}
    count = 0
    for index, segment in enumerate(curve.segments):
        h = curve.times[index + 1] - curve.times[index]
        polynomials = [[motion.derivative(c, order) for c in segment] for order in range(4)]
        for step in range(subdivisions):
            lower, upper = step / subdivisions, (step + 1) / subdivisions
            state = {field: [_polynomial_interval(c, lower, upper, h ** order) for c in polynomials[order]]
                     for order, field in enumerate(motion.FIELDS)}
            raw = model._raw(state, local)
            for field in LINEAR[1:]:
                tool[field] = max(tool[field], _norm_upper(raw[field]))
            for target, source in zip(samples, raw['points']):
                for field in LINEAR[1:]:
                    target[field] = max(target[field], _norm_upper(source[field]))
            for field in ANGULAR:
                angular[field] = max(angular[field], _norm_upper(raw[field]))
            count += 1
    return {'scope': 'conservative_numeric_interval', 'formal_floating_point_certificate': False,
            'intervals': count, 'subdivisions': subdivisions, 'tool': tool, 'points': samples,
            **{field: max(point[field] for point in samples) if samples else tool[field]
               for field in LINEAR[1:]}, **angular}


def adaptive_bounds(kin, points, points_mm=(), subdivisions=4,
                    max_subdivisions=64, limits=None):
    """Refine the worst conservative FK segment instead of the whole track.

    Every returned upper bound is the union of interval enclosures, exactly as
    in ``bounds``. Actual endpoint/midpoint evaluations are lower estimates used
    ONLY to decide whether refinement is worthwhile. They never replace an
    interval upper bound. Refinement stops at a 10% factor gap or the configured
    maximum on the current worst segment; no physical motion cap is loosened.
    """
    if (type(subdivisions) is not int or subdivisions<1
            or type(max_subdivisions) is not int or max_subdivisions<subdivisions
            or max_subdivisions%subdivisions
            or (max_subdivisions//subdivisions)&((max_subdivisions//subdivisions)-1)):
        raise ValueError('Adaptive subdivisions require a positive base and a power-of-two maximum multiple')
    if not isinstance(limits,dict):raise ValueError('Explicit synthetic sample motion limits required')
    try:
        caps={field:_finite(limits['sample_translation'][name]) for field,name in zip(LINEAR[1:],
              ('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'))}
        caps.update({field:math.radians(_finite(limits['sample_rotation'][name])) for field,name in zip(ANGULAR,
                     ('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'))})
    except (KeyError,TypeError) as error:raise ValueError('Complete translation and angular sample limits required') from error
    if min(caps.values())<=0.:raise ValueError('Positive finite sample motion limits required')
    orders=dict(zip((*LINEAR[1:],*ANGULAR),(1,2,3,1,2,3)))
    model=kin if isinstance(kin,KinematicJets) else KinematicJets(kin)
    curve=points if isinstance(points,motion.Curve) else motion.Curve(points)
    if len(curve.points[0][motion.FIELDS[0]])!=len(model.bridges):
        raise ValueError('Curve dimension must match kinematic frames')
    local=_local_points(points_mm);sampled={field:0. for field in caps};sample_cache=set()
    evaluated_intervals=0;actual_evaluations=0
    def factor(values):return max((values[field]/caps[field])**(1/orders[field]) for field in caps)
    def empty():
        return {'tool':{field:0. for field in LINEAR[1:]},
                'points':[{field:0. for field in LINEAR[1:]} for _ in local],
                'angular':{field:0. for field in ANGULAR}}
    def include(target,raw,interval=True):
        norm=_norm_upper if interval else lambda vector:math.sqrt(math.fsum(v*v for v in vector))
        for field in LINEAR[1:]:target['tool'][field]=max(target['tool'][field],norm(raw[field]))
        for a,b in zip(target['points'],raw['points']):
            for field in LINEAR[1:]:a[field]=max(a[field],norm(b[field]))
        for field in ANGULAR:target['angular'][field]=max(target['angular'][field],norm(raw[field]))
    def metrics(target):
        return {**{field:max(p[field] for p in target['points']) if local else target['tool'][field] for field in LINEAR[1:]},
                **target['angular']}
    # Polynomial critical points are independent of the subdivision. Isolate
    # them once per actual quintic and reuse them when ranges are refined.
    compiled=[]
    for segment in curve.segments:
        derivatives=[[motion.derivative(c,order) for c in segment] for order in range(4)]
        critical=[[motion.real_roots(motion.derivative(c)) for c in row] for row in derivatives]
        compiled.append((derivatives,critical))
    def refine(index,count):
        nonlocal evaluated_intervals,actual_evaluations
        h=curve.times[index+1]-curve.times[index];derivatives,critical=compiled[index];result=empty()
        for step in range(count):
            lo,hi=step/count,(step+1)/count;state={}
            for order,field in enumerate(motion.FIELDS):
                state[field]=[]
                for c,roots in zip(derivatives[order],critical[order]):
                    values=[motion.polynomial(c,u)/h**order for u in (lo,hi,*[r for r in roots if lo<=r<=hi])]
                    state[field].append(Interval(_outward(min(values),-math.inf),_outward(max(values),math.inf)))
            include(result,model._raw(state,local));evaluated_intervals+=1
        for step in range(2*count+1):
            u=step/(2*count);key=(index,u)
            if key in sample_cache:continue
            sample_cache.add(key);t=curve.times[index+1] if u==1. else curve.times[index]+u*h
            raw=model.evaluate(motion.evaluate(curve,t,side='left' if u==1. else 'right'),points_mm=local)
            observed=empty();include(observed,raw,False)
            for field,value in metrics(observed).items():sampled[field]=max(sampled[field],value)
            actual_evaluations+=1
        result.update(subdivisions=count,factor=factor(metrics(result)))
        return result
    segments=[refine(i,subdivisions) for i in range(len(curve.segments))]
    reason='sampled_factor_gap'
    while True:
        index=max(range(len(segments)),key=lambda i:segments[i]['factor']);worst=segments[index]
        lower=factor(sampled)
        if worst['factor']<=lower*1.1:break
        if worst['subdivisions']==max_subdivisions:reason='worst_segment_at_maximum';break
        segments[index]=refine(index,worst['subdivisions']*2)
    result=empty()
    for segment in segments:
        for field in LINEAR[1:]:result['tool'][field]=max(result['tool'][field],segment['tool'][field])
        for a,b in zip(result['points'],segment['points']):
            for field in LINEAR[1:]:a[field]=max(a[field],b[field])
        for field in ANGULAR:result['angular'][field]=max(result['angular'][field],segment['angular'][field])
    values=metrics(result)
    return {'scope':'conservative_numeric_interval','formal_floating_point_certificate':False,
            'intervals':sum(s['subdivisions'] for s in segments),'subdivisions':subdivisions,
            'tool':result['tool'],'points':result['points'],**values,
            'adaptive':{'maximum_subdivisions':max_subdivisions,'segment_subdivisions':[s['subdivisions'] for s in segments],
                        'evaluated_intervals':evaluated_intervals,'actual_evaluations':actual_evaluations,
                        'sampled_peaks':sampled,'sampled_factor_lower':factor(sampled),'factor_upper':factor(values),
                        'target_factor_ratio':1.1,'stop_reason':reason,
                        'scope':'Actual sample values guide refinement only; returned bounds remain interval upper enclosures.'}}
