"""C2 quintic joint curves and polynomial-extremum bounds; no ROS dependency.

Points use seconds and radians. Bounds examine every polynomial interval and
both one-sided knot limits, rather than estimating derivatives from samples.
Root isolation is numerical in binary64, with outward rounding of extrema.
"""
from bisect import bisect_left, bisect_right
import math
import sys

FIELDS = ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2', 'jerks_rad_s3')


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + ' must be finite')
    return float(value)


def _vector(value, name, size=None):
    if not isinstance(value, (list, tuple)) or not value or size is not None and len(value) != size:
        raise ValueError(name + ' has an invalid dimension')
    return [_number(v, name) for v in value]


def _points(points):
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        raise ValueError('At least two trajectory points required')
    result = []
    size = None
    previous = None
    for point in points:
        if not isinstance(point, dict):
            raise ValueError('A canonical trajectory point is required')
        try:
            t = _number(point['time_s'], 'time')
            p = _vector(point[FIELDS[0]], 'position', size)
            size = len(p)
            v = _vector(point[FIELDS[1]], 'velocity', size)
            a = _vector(point[FIELDS[2]], 'acceleration', size)
        except KeyError:
            raise ValueError('Complete position, velocity and acceleration required') from None
        if previous is not None and t <= previous:
            raise ValueError('Trajectory times must strictly increase')
        result.append({'time_s': t, FIELDS[0]: p, FIELDS[1]: v, FIELDS[2]: a})
        previous = t
    return result


def derivative(coefficients, order=1):
    result = list(coefficients)
    for _ in range(order):
        result = [i * value for i, value in enumerate(result)][1:] or [0.]
    return result


def polynomial(coefficients, u):
    value = 0.
    for coefficient in reversed(coefficients):
        value = value * u + coefficient
    return value


def real_roots(coefficients, lower=0., upper=1.):
    """All real roots of a degree <=4 polynomial on a closed interval.

    Derivative roots partition the interval into monotone pieces. Testing the
    partition points also retains repeated/tangent roots with no sign change.
    """
    c = [_number(value, 'polynomial coefficient') for value in coefficients]
    while len(c) > 1 and c[-1] == 0:
        c.pop()
    if len(c) > 5:
        raise ValueError('Root isolation supports degree at most four')
    if len(c) <= 1:
        return []
    lo, hi = _number(lower, 'lower root bound'), _number(upper, 'upper root bound')
    if lo > hi:
        raise ValueError('Invalid root interval')
    scale = max(abs(value) for value in c)
    c = [value / scale for value in c]
    if len(c) == 2:
        root = -c[0] / c[1]
        return [min(hi, max(lo, root))] if lo <= root <= hi else []
    critical = real_roots(derivative(c), lo, hi)
    cuts = sorted(set([lo, *critical, hi]))
    tolerance = 32 * sys.float_info.epsilon * sum(abs(value) for value in c)
    roots = [u for u in cuts if abs(polynomial(c, u)) <= tolerance]
    for left, right in zip(cuts, cuts[1:]):
        fl, fr = polynomial(c, left), polynomial(c, right)
        # A numerically zero critical point is already retained above. Do not
        # manufacture two sign-change roots around a rounded tangent root.
        if abs(fl) <= tolerance or abs(fr) <= tolerance or (fl > 0) == (fr > 0):
            continue
        for _ in range(100):
            middle = (left + right) / 2
            if middle in (left, right):
                break
            fm = polynomial(c, middle)
            if fm == 0:
                left = right = middle
                break
            if (fm > 0) == (fl > 0):
                left, fl = middle, fm
            else:
                right = middle
        roots.append((left + right) / 2)
    result = []
    for root in sorted(roots):
        if not result or abs(root - result[-1]) > 8 * sys.float_info.epsilon * max(1., abs(root)):
            result.append(root)
    return result


def _coefficients(a, b):
    h = b['time_s'] - a['time_s']
    result = []
    for p0, p1, v0, v1, a0, a1 in zip(a[FIELDS[0]], b[FIELDS[0]],
                                     a[FIELDS[1]], b[FIELDS[1]], a[FIELDS[2]], b[FIELDS[2]]):
        dp = p1 - p0 - h * v0 - h * h * a0 / 2
        dv = h * (v1 - v0) - h * h * a0
        da = h * h * (a1 - a0)
        c = [p0, h * v0, h * h * a0 / 2,
             10 * dp - 4 * dv + da / 2,
             -15 * dp + 7 * dv - da,
             6 * dp - 3 * dv + da / 2]
        if not all(math.isfinite(value) for value in c):
            raise ValueError('Quintic coefficients overflow')
        result.append(c)
    return result


def coefficients(a, b):
    """Per-coordinate [c0..c5], in u=(t-a.time_s)/(b.time_s-a.time_s)."""
    return _coefficients(*_points([a, b]))


def _local_derivatives(times, positions, index):
    """Degree-four Lagrange derivatives on five nearby, centered time nodes."""
    start = max(0, min(index - 2, len(times) - 5))
    indices = range(start, start + 5)
    center = times[index]
    scale = max(abs(times[k] - center) for k in indices)
    nodes = [(times[k] - center) / scale for k in indices]
    velocity, acceleration = [], []
    for j, node in enumerate(nodes):
        coefficients = [1.]
        denominator = 1.
        for k, other in enumerate(nodes):
            if k == j:
                continue
            extended = [0.] * (len(coefficients) + 1)
            for power in range(len(extended)):
                extended[power] = math.fsum((
                    -other * coefficients[power] if power < len(coefficients) else 0.,
                    coefficients[power - 1] if power else 0.))
            coefficients = extended
            denominator *= node - other
        if not denominator or not math.isfinite(denominator):
            raise ValueError('Ill-conditioned local derivative time nodes')
        velocity.append(coefficients[1] / denominator / scale)
        acceleration.append(2 * coefficients[2] / denominator / scale / scale)
    # Subtract the central value: constants have zero derivatives, and need
    # not cancel through large positive and negative interpolation weights.
    def estimate(weights):
        result = [math.fsum(weight * (positions[k][axis] - positions[index][axis])
                            for k, weight in zip(indices, weights))
                  for axis in range(len(positions[index]))]
        if not all(math.isfinite(value) for value in result):
            raise ValueError('Local derivative fit overflow')
        return result
    return estimate(velocity), estimate(acceleration)


def from_positions(times, positions, rest_endpoints=True):
    """Fit local degree-four v/a from five points; stop at both ends.

    This constructs a C2 curve, not a guarantee that its extrema satisfy any
    chosen motion limits. Call bounds() on the resulting actual quintics.
    Fewer than five points retain the local quadratic/linear fallback.
    """
    if type(rest_endpoints) is not bool:
        raise ValueError('rest_endpoints must be Boolean')
    if len(times) != len(positions) or len(times) < 2:
        raise ValueError('Matching time/position lists with at least two points required')
    ts = [_number(t, 'time') for t in times]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise ValueError('Trajectory times must strictly increase')
    ps = []
    for position in positions:
        ps.append(_vector(position, 'position', len(ps[0]) if ps else None))
    size = len(ps[0])
    vs = [[0.] * size for _ in ts]
    acc = [[0.] * size for _ in ts]
    if len(ts) >= 5:
        for i in range(1 if rest_endpoints else 0, len(ts) - (1 if rest_endpoints else 0)):
            vs[i], acc[i] = _local_derivatives(ts, ps, i)
    else:
        slopes = [[(y - x) / (b - a) for x, y in zip(p0, p1)]
                  for a, b, p0, p1 in zip(ts, ts[1:], ps, ps[1:])]
        for i in range(1, len(ts) - 1):
            left, right = ts[i] - ts[i - 1], ts[i + 1] - ts[i]
            vs[i] = [(right * a + left * b) / (left + right) for a, b in zip(slopes[i - 1], slopes[i])]
            acc[i] = [2 * (b - a) / (left + right) for a, b in zip(slopes[i - 1], slopes[i])]
        if not rest_endpoints:
            if len(ts) == 2:
                vs[0], vs[-1] = slopes[0][:], slopes[0][:]
            else:
                acc[0], acc[-1] = acc[1][:], acc[-2][:]
                vs[0] = [v - a * (ts[1] - ts[0]) / 2 for v, a in zip(slopes[0], acc[0])]
                vs[-1] = [v + a * (ts[-1] - ts[-2]) / 2 for v, a in zip(slopes[-1], acc[-1])]
    return _points([{'time_s': t, FIELDS[0]: p, FIELDS[1]: v, FIELDS[2]: a}
                    for t, p, v, a in zip(ts, ps, vs, acc)])


class Curve:
    """A validated reusable curve for repeated FK/playback evaluation."""
    def __init__(self, points):
        self.points = _points(points)
        self.times = [p['time_s'] for p in self.points]
        self.segments = [_coefficients(a, b) for a, b in zip(self.points, self.points[1:])]

    def evaluate(self, t, side='right'):
        t = _number(t, 'evaluation time')
        if side not in ('left', 'right'):
            raise ValueError('Knot side must be left or right')
        if t < self.times[0] or t > self.times[-1]:
            point = self.points[0] if t < self.times[0] else self.points[-1]
            return {'time_s': t, FIELDS[0]: point[FIELDS[0]][:],
                    **{field: [0.] * len(point[FIELDS[0]]) for field in FIELDS[1:]}}
        search = bisect_left if side == 'left' else bisect_right
        index = max(0, min(len(self.segments) - 1, search(self.times, t) - 1))
        a, b = self.points[index:index + 2]
        h = b['time_s'] - a['time_s']
        u = (t - a['time_s']) / h
        result = {'time_s': t}
        for order, field in enumerate(FIELDS):
            result[field] = [polynomial(derivative(c, order), u) / h ** order
                             for c in self.segments[index]]
        if u == 0 or u == 1:
            point = a if u == 0 else b
            for field in FIELDS[:3]:
                result[field] = point[field][:]
        if not all(math.isfinite(value) for field in FIELDS for value in result[field]):
            raise ValueError('Quintic evaluation overflow')
        return result


def evaluate(points, t, side='right'):
    return (points if isinstance(points, Curve) else Curve(points)).evaluate(t, side)


def bounds(points):
    """Polynomial extrema over every interval, including one-sided knot limits."""
    curve = points if isinstance(points, Curve) else Curve(points)
    size = len(curve.points[0][FIELDS[0]])
    result = {field: {'min': [math.inf] * size, 'max': [-math.inf] * size} for field in FIELDS}
    for index, segment in enumerate(curve.segments):
        h = curve.times[index + 1] - curve.times[index]
        for joint, c in enumerate(segment):
            for order, field in enumerate(FIELDS):
                values = derivative(c, order)
                candidates = [0., 1., *real_roots(derivative(values))]
                extrema = [polynomial(values, u) / h ** order for u in candidates]
                if not all(math.isfinite(value) for value in extrema):
                    raise ValueError('Quintic bounds overflow')
                result[field]['min'][joint] = min(result[field]['min'][joint], *extrema)
                result[field]['max'][joint] = max(result[field]['max'][joint], *extrema)
    for item in result.values():
        item['min'] = [math.nextafter(value, -math.inf) if value else 0. for value in item['min']]
        item['max'] = [math.nextafter(value, math.inf) if value else 0. for value in item['max']]
        item['max_abs'] = [max(abs(a), abs(b)) for a, b in zip(item['min'], item['max'])]
    return result


def scale(points, timefactor, offset=0.):
    factor = _number(timefactor, 'time factor')
    offset = _number(offset, 'time offset')
    if factor <= 0:
        raise ValueError('Time factor must be positive')
    source = points.points if isinstance(points, Curve) else _points(points)
    return _points([{'time_s': offset + factor * p['time_s'], FIELDS[0]: p[FIELDS[0]][:],
                     FIELDS[1]: [v / factor for v in p[FIELDS[1]]],
                     FIELDS[2]: [a / factor ** 2 for a in p[FIELDS[2]]]}
                    for p in source])


def septic(u, order=0):
    """Normalized rest-to-rest reference with zero endpoint v, a and jerk."""
    u = _number(u, 'normalized time')
    if type(order) is not int or not 0 <= order <= 3 or not 0 <= u <= 1:
        raise ValueError('Septic requires u in [0,1] and derivative order 0..3')
    if u in (0., 1.):
        return u if order == 0 else 0.
    return polynomial(derivative([0., 0., 0., 0., 35., -84., 70., -20.], order), u)


def rest_to_rest(distance, velocity, acceleration, jerk):
    """Symmetric scalar seven-phase jerk-limited S-curve from 0 to distance.

    Constant-jerk phases are cubic polynomials, represented by the same PVA
    quintic-Hermite contract. Zero-duration acceleration/cruise phases are
    omitted. Limits are numerical inputs, not qualified actuator ratings.
    A zero displacement is a hold, not a positive-duration movement.
    """
    distance = _number(distance, 'distance')
    velocity = _number(velocity, 'velocity limit')
    acceleration = _number(acceleration, 'acceleration limit')
    jerk = _number(jerk, 'jerk limit')
    if distance == 0 or min(velocity, acceleration, jerk) <= 0:
        raise ValueError('Nonzero distance and positive S-curve limits required')
    sign, length = (1. if distance > 0 else -1.), abs(distance)
    try:
        if velocity >= acceleration * acceleration / jerk:
            tj = acceleration / jerk
            ta = max(0., velocity / acceleration - tj)
        else:
            tj, ta = math.sqrt(velocity / jerk), 0.
        cruise_distance = velocity * (2 * tj + ta)
        if length >= cruise_distance:
            tv = (length - cruise_distance) / velocity
        elif length >= 2 * acceleration ** 3 / jerk ** 2:
            tj = acceleration / jerk
            ta = max(0., (-3 * tj + math.sqrt(tj * tj + 4 * length / acceleration)) / 2)
            tv = 0.
        else:
            tj, ta, tv = (length / (2 * jerk)) ** (1 / 3), 0., 0.
        durations = [tj, ta, tj, tv, tj, ta, tj]
        if tj <= 0 or not all(math.isfinite(value) and value >= 0 for value in durations):
            raise ValueError
        result = [{'time_s': 0., FIELDS[0]: [0.], FIELDS[1]: [0.], FIELDS[2]: [0.]}]
        position = speed = acc = time = 0.
        for duration, phase in zip(durations, (1., 0., -1., 0., -1., 0., 1.)):
            if duration == 0:
                continue
            phase_jerk = sign * jerk * phase
            position += speed * duration + acc * duration ** 2 / 2 + phase_jerk * duration ** 3 / 6
            speed += acc * duration + phase_jerk * duration ** 2 / 2
            acc += phase_jerk * duration
            time += duration
            result.append({'time_s': time, FIELDS[0]: [position], FIELDS[1]: [speed], FIELDS[2]: [acc]})
        result[-1][FIELDS[0]] = [distance]
        result[-1][FIELDS[1]] = [0.]
        result[-1][FIELDS[2]] = [0.]
        return _points(result)
    except (OverflowError, ZeroDivisionError, ValueError):
        raise ValueError('S-curve parameters cannot be represented reliably') from None
