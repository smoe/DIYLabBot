"""Conservative disk closing of BF01 supporting surfaces, without CAD imports.

The strict native triangle-union test remains the fast path. For missing
regions, an inward disk polygon dilates the native surfaces and an outward
disk polygon erodes the result. Exact rational polygon coverage never accepts
an area tolerance. Already-supported points are retained by the mathematical
extensivity of closing; no outward fringe is added at a free convex edge.
"""
from fractions import Fraction as Q
from functools import lru_cache
import math


def _number(value):
    if isinstance(value, Q):
        return value
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite support geometry coordinate required')
    return Q(value)


def _cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def _area(poly):
    return sum(_cross(a, b) for a, b in zip(poly, poly[1:]+poly[:1]))/2


def _convex_hull(points):
    points = sorted(set(tuple(p) for p in points))
    if len(points) < 3:
        return points
    def half(rows):
        out = []
        for p in rows:
            while len(out) > 1 and _cross((out[-1][0]-out[-2][0], out[-1][1]-out[-2][1]),
                                         (p[0]-out[-1][0], p[1]-out[-1][1])) <= 0:
                out.pop()
            out.append(p)
        return out
    return half(points)[:-1]+half(list(reversed(points)))[:-1]


def _ccw(poly):
    result = [tuple(_number(v) for v in p) for p in poly]
    if len(result) < 3 or any(len(p) != 2 for p in result):
        raise ValueError('Nondegenerate XY support polygon required')
    signed = _area(result)
    if not signed:
        raise ValueError('Positive-area support polygon required')
    result = result if signed > 0 else list(reversed(result))
    if any(_cross((b[0]-a[0], b[1]-a[1]), (p[0]-a[0], p[1]-a[1])) < 0
           for a, b in zip(result, result[1:]+result[:1]) for p in result):
        raise ValueError('Convex support polygon required')
    return result


def _clip_convex(poly, clipper):
    result = poly
    for a, b in zip(clipper, clipper[1:]+clipper[:1]):
        if not result:
            break
        edge = (b[0]-a[0], b[1]-a[1])
        def distance(p):
            return _cross(edge, (p[0]-a[0], p[1]-a[1]))
        output = []
        previous = result[-1]
        dprev = distance(previous)
        for current in result:
            dcur = distance(current)
            if (dprev >= 0) != (dcur >= 0):
                u = dprev/(dprev-dcur)
                output.append(tuple(previous[k]+u*(current[k]-previous[k]) for k in range(2)))
            if dcur >= 0:
                output.append(current)
            previous, dprev = current, dcur
        result = output
    return result


def _interval_union(rows):
    if not rows:
        return []
    merged = []
    for lo, hi in sorted(rows):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _missing_intervals(query_span, covered):
    lo, hi = query_span
    result = []
    cursor = lo
    for a, b in covered:
        a, b = max(a, lo), min(b, hi)
        if a > cursor:
            result.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        result.append((cursor, hi))
    return result


def polygon_union_covers(polygons, query, *, missing_regions=False, _convex_inputs=False):
    """Exact finite convex-polygon union coverage, sharing the floor core.

    All edge crossings enter the x arrangement. Within every resulting strip,
    vertical interval endpoints and their order are affine. The mean lengths
    at1/4 and3/4 give their exact integral. Optional missing cells are the
    corresponding exact trapezoids; they contain no invented support area.
    """
    from building_fleet_clearance import _intersection_x, _union_length
    target = query if _convex_inputs else _ccw(query)
    clipped = []
    seen = set()
    target_lo = [min(p[k] for p in target) for k in range(2)]
    target_hi = [max(p[k] for p in target) for k in range(2)]
    for raw in polygons:
        poly = raw if _convex_inputs else _ccw(raw)
        if any(max(p[k] for p in poly) < target_lo[k] or
               min(p[k] for p in poly) > target_hi[k] for k in range(2)):
            continue
        poly = _clip_convex(poly, target)
        if len(poly) >= 3 and _area(poly):
            poly = _convex_hull(poly)
            identity = tuple(poly)
            if identity not in seen:
                seen.add(identity)
                clipped.append(poly)
    required = _area(target)
    xs = {p[0] for p in target}
    xs.update(p[0] for poly in clipped for p in poly)
    edges = [(a, b) for poly in clipped for a, b in zip(poly, poly[1:]+poly[:1])]
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i+1:]:
            if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
                continue
            x = _intersection_x(a, b, c, d)
            if x is not None:
                xs.add(x)
    # A strip samples each edge many times. Form its exact affine function
    # once and retain the same open x-domain used by the vertical section.
    def edge_lines(poly):
        lines = []
        for a, b in zip(poly, poly[1:]+poly[:1]):
            if a[0] != b[0]:
                lo, hi = (a[0], b[0]) if a[0] < b[0] else (b[0], a[0])
                slope = (b[1]-a[1])/(b[0]-a[0])
                lines.append((lo, hi, slope, a[1]-slope*a[0]))
        return lines
    def vertical(lines, x):
        ys = [slope*x+offset for lo,hi,slope,offset in lines if lo<x<hi]
        return (min(ys),max(ys)) if ys else None
    target_lines = edge_lines(target)
    supports = [edge_lines(poly) for poly in clipped]
    area = Q(0)
    cells = []
    strips = 0
    xs = sorted(xs)
    for a, b in zip(xs, xs[1:]):
        if a == b:
            continue
        samples = ((3*a+b)/4, (a+3*b)/4)
        lengths = []
        holes = []
        for x in samples:
            span = vertical(target_lines, x)
            if span is None:
                raise ArithmeticError('Convex query strip has no interior vertical section')
            rows = [row for lines in supports if (row := vertical(lines, x)) is not None]
            rows = _interval_union(rows)
            lengths.append(_union_length(rows))
            if missing_regions:
                holes.append(_missing_intervals(span, rows))
        area += (b-a)*(lengths[0]+lengths[1])/2
        strips += 1
        if missing_regions:
            if len(holes[0]) != len(holes[1]):
                raise ArithmeticError('Missing an arrangement crossing')
            for (l1, h1), (l3, h3) in zip(*holes):
                cell = [(a, (3*l1-l3)/2), (b, (3*l3-l1)/2),
                        (b, (3*h3-h1)/2), (a, (3*h1-h3)/2)]
                cell = _convex_hull(cell)
                if len(cell) >= 3 and _area(cell):
                    cells.append(cell)
    missing = required-area
    if missing < 0:
        raise ArithmeticError('Clipped support union exceeds query area')
    if missing_regions and sum(_area(cell) for cell in cells) != missing:
        raise ArithmeticError('Missing support cell areas do not balance')
    result = {'passed': missing == 0, 'covered_area_mm2': float(area),
              'required_area_mm2': float(required), 'missing_area_mm2': float(missing),
              'strips': strips, 'method': 'exact rational convex-clipped polygon union; all edge crossings; no area tolerance'}
    if missing_regions:
        result['_missing_cells'] = cells
    return result


def _sqrt_upper(value):
    result = Q(math.sqrt(float(value)))
    while result*result < value:
        result = Q(math.nextafter(float(result), math.inf))
    return result


def _direction(index, sides):
    if index*4 % sides == 0:
        quadrant = index*4//sides
        return ((Q(1), Q(0)), (Q(0), Q(1)), (Q(-1), Q(0)), (Q(0), Q(-1)))[quadrant]
    angle = index*2*math.pi/sides
    return Q(math.cos(angle)), Q(math.sin(angle))


@lru_cache(maxsize=48)
def disk_enclosures(radius_mm, sides=8):
    """Exact checks for an inward polygon and outward tangent-halfplane polygon."""
    radius = _number(radius_mm)
    if radius <= 0 or type(sides) is not int or sides < 8 or sides > 128 or sides % 4:
        raise ValueError('Positive radius and8..128 polygon sides divisible by4 required')
    inner = []
    halfplanes = []
    for i in range(sides):
        normal = _direction(i, sides)
        p = tuple(radius*v for v in normal)
        while sum(v*v for v in p) > radius*radius:
            factor = Q(math.nextafter(1., 0.))
            p = tuple(v*factor for v in p)
        inner.append(p)
        squared = radius*radius*sum(v*v for v in normal)
        halfplanes.append((normal, _sqrt_upper(squared)))
    outer = []
    for (n, a), (m, b) in zip(halfplanes, halfplanes[1:]+halfplanes[:1]):
        determinant = _cross(n, m)
        if determinant <= 0:
            raise ArithmeticError('Ordered outward disk normals required')
        outer.append(((a*m[1]-n[1]*b)/determinant,
                      (n[0]*b-a*m[0])/determinant))
    if not all(sum(v*v for v in p) <= radius*radius for p in inner):
        raise ArithmeticError('Inward disk polygon escaped the exact disk')
    if not all(h*h >= radius*radius*sum(v*v for v in n) for n, h in halfplanes):
        raise ArithmeticError('Outward disk halfplane excludes part of the disk')
    if not all(sum(n[k]*p[k] for k in range(2)) <= h for p in outer for n, h in halfplanes):
        raise ArithmeticError('Outward disk halfplanes are not a convex enclosure')
    return tuple(inner), tuple(outer), {
        'sides': sides, 'radius_mm': float(radius),
        'inner_vertex_norms_within_disk': True,
        'outer_halfplanes_contain_disk': True,
        'basis': 'Exact Fraction inequalities; inward vertices and outward tangent-halfplane intersections'}


def _sum_polygon(first, second):
    return _convex_hull([(a[0]+b[0], a[1]+b[1]) for a in first for b in second])


def _merge_convex_cells(polygons):
    """Remove exact triangulation seams without adding any supporting area.

    Oppositely oriented complete shared edges put convex cell interiors on
    opposite sides. Their union is convex exactly when the convex hull area
    equals the two original areas. Same-side overlaps are never merged.
    """
    cells = list(polygons)
    while True:
        edges = {}
        merged = False
        for i, poly in enumerate(cells):
            for a, b in zip(poly, poly[1:]+poly[:1]):
                other = edges.get((b, a))
                if other is not None:
                    hull = _convex_hull(poly+cells[other])
                    if _area(hull) == _area(poly)+_area(cells[other]):
                        cells = [p for j, p in enumerate(cells) if j not in (i, other)]+[hull]
                        merged = True
                        break
                edges[(a, b)] = i
            if merged:
                break
        if not merged:
            return cells


def _components(cells):
    parent = list(range(len(cells)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def span_at(poly, x):
        values = [p[1] for p in poly if p[0] == x]
        return (min(values), max(values)) if values else None
    starts, ends = {}, {}
    for i, poly in enumerate(cells):
        starts.setdefault(min(p[0] for p in poly), []).append(i)
        ends.setdefault(max(p[0] for p in poly), []).append(i)
    for x in starts.keys() & ends.keys():
        for i in starts[x]:
            lo, hi = span_at(cells[i], x)
            for j in ends[x]:
                a, b = span_at(cells[j], x)
                if min(hi, b) >= max(lo, a):
                    pi, pj = find(i), find(j)
                    if pi != pj:
                        parent[max(pi, pj)] = min(pi, pj)
    groups = {}
    for i, poly in enumerate(cells):
        groups.setdefault(find(i), []).append(poly)
    return list(groups.values())


def _centroid(poly):
    denominator = 6*_area(poly)
    return tuple(sum((a[k]+b[k])*_cross(a, b) for a, b in zip(poly, poly[1:]+poly[:1]))/denominator
                 for k in range(2))


def _nearest(point, a, b):
    delta = (b[0]-a[0], b[1]-a[1])
    norm = sum(v*v for v in delta)
    t = min(Q(1), max(Q(0), sum((point[k]-a[k])*delta[k] for k in range(2))/norm)) if norm else Q(0)
    return tuple(a[k]+t*delta[k] for k in range(2))


def _line_span(poly, point, direction):
    low = high = None
    for a, b in zip(poly, poly[1:]+poly[:1]):
        edge = (b[0]-a[0], b[1]-a[1])
        constant = _cross(edge, (point[0]-a[0], point[1]-a[1]))
        slope = _cross(edge, direction)
        if not slope:
            if constant < 0:
                return None
        elif slope > 0:
            cut = -constant/slope
            low = cut if low is None else max(low, cut)
        else:
            cut = -constant/slope
            high = cut if high is None else min(high, cut)
    if low is None or high is None or high < low:
        return None
    return low, high


def _chord(point, polygons, body_ids, maximum_gap):
    directions = set()
    near_points = set()
    def add(direction):
        if direction == (0, 0):
            return
        base = direction[0] or direction[1]
        directions.add(tuple(v/base for v in direction))
    for poly in polygons:
        for a, b in zip(poly, poly[1:]+poly[:1]):
            nearest = _nearest(point, a, b)
            if maximum_gap is None or sum((nearest[k]-point[k])**2 for k in range(2)) <= maximum_gap*maximum_gap:
                near_points.add(nearest)
                add((a[1]-b[1], b[0]-a[0]))
    for a in near_points:
        for b in near_points:
            if a < b:
                add(tuple(b[k]-a[k] for k in range(2)))
    best = None
    for direction in directions:
        rows = []
        for poly, identity in zip(polygons, body_ids):
            span = _line_span(poly, point, direction)
            if span is not None:
                rows.append((*span, identity))
        merged = []
        for low, high, identity in sorted(rows):
            if merged and low <= merged[-1]['high']:
                row = merged[-1]
                if high > row['high']:
                    row['high'], row['right'] = high, {identity}
                elif high == row['high']:
                    row['right'].add(identity)
                if low == row['low']:
                    row['left'].add(identity)
            else:
                merged.append({'low': low, 'high': high, 'left': {identity}, 'right': {identity}})
        for first, second in zip(merged, merged[1:]):
            if first['high'] < 0 < second['low']:
                squared = (second['low']-first['high'])**2*sum(v*v for v in direction)
                if best is None or squared < best['squared']:
                    best = {'squared': squared,
                            'left': tuple(point[k]+first['high']*direction[k] for k in range(2)),
                            'right': tuple(point[k]+second['low']*direction[k] for k in range(2)),
                            'bodies': sorted(first['right'] | second['left'])}
    return best


def query_padding_mm(max_gap_mm, polygon_sides=8):
    """Minimum native-index padding needed by the inward/outward certificates."""
    radius = _number(max_gap_mm)/2
    if radius < 0:
        raise ValueError('Nonnegative maximum support gap required')
    if not radius:
        return 0.
    inner, outer, _ = disk_enclosures(radius, polygon_sides)
    upper = max(_sqrt_upper(sum(v*v for v in p)) for p in outer)+radius
    return math.nextafter(float(upper), math.inf)


def rectangle_query(centre, yaw, half_length, half_width):
    """Construct the authoritative WORLD query using exact affine products.

    Trigonometric coefficients are the declared Float64 evaluation of yaw,
    converted once to rationals. Coordinates are never rotated into a local
    frame and back or rounded after the affine products.
    """
    if len(centre) != 2:
        raise ValueError('Two-dimensional support query centre required')
    origin = tuple(_number(v) for v in centre)
    angle = _number(yaw)
    L, W = _number(half_length), _number(half_width)
    if L <= 0 or W <= 0:
        raise ValueError('Positive full-footprint query dimensions required')
    c, s = Q(math.cos(float(angle))), Q(math.sin(float(angle)))
    return [(origin[0]+c*x-s*y, origin[1]+s*x+c*y)
            for x, y in [(-L, -W), (L, -W), (L, W), (-L, W)]]


@lru_cache(maxsize=128)
def _cached_dilation(cells, radius, sides):
    inner, _, _ = disk_enclosures(radius, sides)
    return tuple(tuple(_sum_polygon(poly, inner)) for poly in cells)


def support_covers(triangles, centre, yaw, half_length, half_width, max_gap_mm,
                   *, body_ids=None, curve_ref=None, polygon_sides=8, refinements=(16, 32),
                   return_exact_cells=False):
    """Prove full WORLD rectangle support after conservative disk closing.

    Raw native WORLD coordinates become exact rationals; all query affine
    products, disk bounds and union areas are then rational. The caller must
    supply all native triangles within query_padding_mm of the rectangle.
    Private exact patches are returned only on request; their Float64 display
    counterparts are never valid support inputs for a certificate cache.
    """
    gap = _number(max_gap_mm)
    if gap < 0:
        raise ValueError('Nonnegative maximum support gap required')
    if type(return_exact_cells) is not bool:
        raise ValueError('Explicit exact-cell output selection required')
    triangles = tuple(triangles)
    if body_ids is None:
        body_ids = tuple('triangle:'+str(i) for i in range(len(triangles)))
    else:
        body_ids = tuple(body_ids)
    if len(body_ids) != len(triangles) or any(not isinstance(v, str) or not v for v in body_ids):
        raise ValueError('One source body ID per native floor triangle required')
    native_cells = []
    native_ids = []
    for triangle, identity in zip(triangles, body_ids):
        if len(triangle) != 3 or any(len(p) != 2 for p in triangle):
            raise ValueError('Native WORLD floor triangles required')
        points = [tuple(_number(v) for v in point) for point in triangle]
        if _area(points):
            native_cells.append(_ccw(points))
            native_ids.append(identity)
    rectangle = rectangle_query(centre, yaw, half_length, half_width)
    coverage_cells = _merge_convex_cells(native_cells)
    strict = polygon_union_covers(coverage_cells, rectangle, missing_regions=True, _convex_inputs=True)
    cells = strict.pop('_missing_cells')
    if strict['passed'] or not gap:
        result = {**strict, 'rule_applied': False, 'applications': [], 'max_gap_mm': float(gap),
                  'coordinate_method': 'WORLD exact Fraction native coordinates and query affine products'}
        if return_exact_cells:
            result['_certified_patches'] = ()
        return result
    attempts = []
    accepted = None
    for sides in dict.fromkeys((polygon_sides, *refinements)):
        inner, outer, enclosure = disk_enclosures(gap/2, sides)
        dilated = _cached_dilation(tuple(tuple(poly) for poly in coverage_cells), gap/2, sides)
        proofs = [polygon_union_covers(dilated, _sum_polygon(cell, outer), _convex_inputs=True) for cell in cells]
        attempts.append({'sides': sides, 'passed': all(p['passed'] for p in proofs),
                         'uncovered_certificate_area_mm2': sum(p['missing_area_mm2'] for p in proofs)})
        if attempts[-1]['passed']:
            accepted = enclosure
            break
    def display(point):
        return [float(point[0]), float(point[1])]
    applications = []
    for group in _components(cells):
        largest = max(group, key=_area)
        sample = _centroid(largest)
        chord = _chord(sample, native_cells, native_ids, gap if accepted is not None else None)
        polys = [[display(p) for p in poly] for poly in group]
        points = [p for poly in polys for p in poly]
        item = {'polygons_mm': polys,
                'bounds_mm': {'min': [min(p[k] for p in points) for k in range(2)],
                              'max': [max(p[k] for p in points) for k in range(2)]},
                'region_area_mm2': float(sum(_area(poly) for poly in group)),
                'measurement_point_mm': display(sample),
                'width_mm': math.sqrt(float(chord['squared'])) if chord else None,
                'width_basis': 'shortest measured native-support chord through the reported missing-cell centroid; not slot length',
                'adjacent_bodies': chord['bodies'] if chord else [],
                'curve_refs': [] if curve_ref is None else [curve_ref]}
        if chord:
            item['support_chord_mm'] = [display(chord['left']), display(chord['right'])]
            item['width_squared_mm2_exact'] = [str(chord['squared'].numerator), str(chord['squared'].denominator)]
        applications.append(item)
    if accepted is None:
        result = {**strict, 'rule_applied': False, 'applications': [], 'max_gap_mm': float(gap),
                  'unsupported_regions': applications,
                  'coordinate_method': 'WORLD exact Fraction native coordinates and query affine products',
                  'closing_attempts': attempts, 'reason': 'conservative_disk_closing_did_not_cover_query'}
        if return_exact_cells:
            result['_certified_patches'] = ()
        return result
    for application in applications:
        application['filled_area_mm2'] = application.pop('region_area_mm2')
    result = {'passed': True, 'covered_area_mm2': strict['required_area_mm2'],
            'required_area_mm2': strict['required_area_mm2'], 'missing_area_mm2': 0.,
            'original_missing_area_mm2': strict['missing_area_mm2'], 'rule_applied': True,
            'max_gap_mm': float(gap), 'applications': applications,
            'closing_enclosure': accepted, 'closing_attempts': attempts,
            'method': 'Exact original union retained; each exact convex missing cell outward-buffer covered by inward-dilated native union; conservative subset of true disk closing',
            'coordinate_method': 'WORLD exact Fraction native coordinates and query affine products',
            'wheel_qualified': False}
    if return_exact_cells:
        result['_certified_patches'] = tuple(tuple(poly) for poly in cells)
    return result
