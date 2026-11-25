"""Continuous separation of a limited depot departure from a complete leader route."""
import math

from building_fleet_model import load
from building_fleet_motion import _bezier_split
from building_fleet_navigation import point_in_polygon
from building_fleet_sim import polygon_distance


def _limits(step, velocity, acceleration):
    if velocity is None or acceleration is None:
        limits = load()['motion']['empty_linear_limits']
        if velocity is None:
            velocity = limits['velocity_mm_s']
        if acceleration is None:
            acceleration = limits['acceleration_mm_s2']
    if not all(type(n) in (float, int) and math.isfinite(n) and n > 0
               for n in (step, velocity, acceleration)) or step > .05:
        raise ValueError('Positive BF01 scalar limits and a step of at most 50 ms required')
    # Controller._valid_stop_clock allows this relative tolerance on scalar extrema.
    return step, velocity * (1 + 1e-6), acceleration * (1 + 1e-6)


def _fit_margin(pieces, limits):
    """Bound executed quintic XY departure from the geometric path in one tick.

    Every recorded knot lies on Path. The XY derivative-control hulls bound
    D=|P'| and G=|P''|, so endpoints of a tick are at most D*V*dt apart.
    The endpoint XY jets are bounded by D*V and G*V^2+D*A. The two inner
    Bernstein controls on each side of a quintic Hermite segment are within
    2*dt*|v|/5 + dt^2*|a|/20 of that endpoint. Their hull is in the same
    radius tube around the endpoint chord. Each point of that chord lies
    within half its length of an endpoint on the actual path.
    """
    dt, velocity, acceleration = limits
    first, second = (max(math.hypot(*p[:2]) for piece in pieces
                         for p in piece['derivatives'][order]) for order in (0, 1))
    return .9 * first * velocity * dt + (first * acceleration + second * velocity**2) * dt**2 / 20


def _straight_frame(path):
    if not path.pieces or len(path.pieces[0]['controls']) != 2:
        return None
    a, b = path.pieces[0]['controls']
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    if not length or not math.isfinite(length):
        return None
    ux, uy = dx/length, dy/length

    def project(p):
        x, y = p[0]-a[0], p[1]-a[1]
        return (ux*x + uy*y, ux*y - uy*x)

    return project, length


def _clear(controls, length, distance, depth=0):
    """Lower-bound distance from an entire Bezier hull to [0,length] on X."""
    return _clear_box(controls, 0., length, 0., distance, depth)


def _clear_box(controls, xmin, xmax, half_width, distance, depth=0):
    """Withhold approval if a control hull cannot be separated from a box."""
    xs, ys = zip(*controls)
    gap_x = max(0., xmin-max(xs), min(xs)-xmax)
    gap_y = max(0., -half_width-max(ys), min(ys)-half_width)
    if math.hypot(gap_x, gap_y) > distance:
        return True
    # The two end controls lie on the actual curve. Ambiguity at the depth
    # limit withholds a grant, including exact tangency.
    if depth == 14 or any(math.hypot(max(0., xmin-x, x-xmax), max(0., abs(y)-half_width)) <= distance
                          for x, y in (controls[0], controls[-1])):
        return False
    left, right = _bezier_split(controls)
    return (_clear_box(left, xmin, xmax, half_width, distance, depth+1)
            and _clear_box(right, xmin, xmax, half_width, distance, depth+1))


def _roundoff(points):
    scale = max(abs(n) for point in points for n in point[:2])
    # Cover coordinate subtraction, rotation, up to 14 de Casteljau halvings
    # and mm-level controller endpoint comparisons.
    return 1e-4 + 256 * math.ulp(scale)


def independent_starter_end(leader_path, follower_path, radius_mm, reserve_mm, *,
                            max_step_s=.05, velocity_mm_s=None, acceleration_mm_s2=None):
    """Return a certified follower progress bound against the entire leader path.

    The caller must bind these paths and scalar bounds to the same live
    actions, and retain all existing motion, native and next-step checks.
    Clearance covers both physical circumdiscs and both executed fitted paths.
    """
    if not math.isfinite(radius_mm) or radius_mm <= 0 or not math.isfinite(reserve_mm) or reserve_mm < 0:
        raise ValueError('Finite positive circumradius and nonnegative reserve required')
    limits = _limits(max_step_s, velocity_mm_s, acceleration_mm_s2)
    frame = _straight_frame(follower_path)
    if frame is None or not leader_path.pieces:
        return 0.
    project, length = frame
    controls = [piece['controls'] for piece in leader_path.pieces]
    margin = 2*radius_mm + reserve_mm + _fit_margin(leader_path.pieces, limits)
    margin += _fit_margin(follower_path.pieces[:1], limits)
    margin += _roundoff(p for piece in [*controls, follower_path.pieces[0]['controls']] for p in piece)
    hulls = [[project(point) for point in piece] for piece in controls]

    def clear(progress):
        return all(_clear(hull, length * (progress / follower_path.ends[0]), margin) for hull in hulls)

    end = follower_path.ends[0]
    if clear(end):
        return end
    if not clear(0.):
        return 0.
    # Always return a proved lower endpoint. Bisection determines how much
    # usable straight track to grant, never whether an ambiguous hull is safe.
    lower, upper = 0., end
    while upper - lower > .01:
        middle = (lower + upper)/2
        if clear(middle):
            lower = middle
        else:
            upper = middle
    return lower


def _straight_sweep(first, last, along, half_width):
    """Exact rectangle sweep for a fixed orientation, including reverse."""
    x0,y0 = first
    x1,y1 = last
    length = math.hypot(x1-x0, y1-y0)
    ux,uy = (x1-x0)/length, (y1-y0)/length
    sx,sy = -uy*half_width, ux*half_width
    ax,ay = ux*along, uy*along
    return [(x0-ax-sx,y0-ay-sy), (x1+ax-sx,y1+ay-sy),
            (x1+ax+sx,y1+ay+sy), (x0-ax+sx,y0-ay+sy)]


def rectangular_starter_end(protected_path, follower_path, envelope, reserve_mm, *,
                            max_step_s=.05, velocity_mm_s=None, acceleration_mm_s2=None):
    """Bound a private straight prefix against every step of an immutable path.

    Admission is conditional on checking the Cartesian velocity bound on
    every actual emitted interval, including a refit at a fallback step.
    Each point is within half a step's travel of its nearer timed endpoint.
    With both endpoint jets on one straight the fit keeps its yaw and
    lateral coordinate. Curves and the adjacent scalar-step bands also
    get the circumdisc proof for endpoints on different pieces.
    """
    length, width = envelope['length_mm'], envelope['width_mm']
    if (not all(type(n) in (int,float) and math.isfinite(n) and n>0 for n in (length,width))
            or type(reserve_mm) not in (int,float) or not math.isfinite(reserve_mm) or reserve_mm<0):
        raise ValueError('Positive footprint dimensions and nonnegative reserve required')
    limits = _limits(max_step_s,velocity_mm_s,acceleration_mm_s2)
    frame = _straight_frame(follower_path)
    if frame is None or not protected_path.pieces:
        return 0.
    project, follower_length = frame
    half_length, half_width = length/2, width/2
    radius = math.hypot(half_length,half_width)
    follower_piece = follower_path.pieces[0]
    protected_pieces = protected_path.pieces
    roundoff = _roundoff(point for piece in [follower_piece,*protected_pieces] for point in piece['controls'])
    # The controller allows 1 µrad each for the initial heading and its own-pose
    # alignment. Account for both rectangles without adding lateral fit error.
    clearance = reserve_mm+roundoff+4e-6*radius
    fit = math.nextafter(limits[0]*limits[1]/2,math.inf)
    disc_clearance = clearance+radius+fit
    along = half_length+fit
    band = limits[0]*limits[1]+roundoff
    rectangles, mixed_hulls = [], []

    for index, piece in enumerate(protected_pieces):
        controls = [project(point) for point in piece['controls']]
        if len(controls)!=2:
            mixed_hulls.append(controls)
            continue
        first,last = controls
        rectangles.append(_straight_sweep(first,last,along,half_width))
        fraction = min(1.,band/piece['weight'])
        if index:
            cut = tuple(a+(b-a)*fraction for a,b in zip(first,last))
            mixed_hulls.append([first,cut])
        if index+1<len(protected_pieces):
            cut = tuple(b+(a-b)*fraction for a,b in zip(first,last))
            mixed_hulls.append([cut,last])

    maximum = follower_path.ends[0]
    if len(follower_path.pieces)>1:
        # The rolling controller admits up to 1e-5 mm numerical horizon slack.
        maximum -= 2e-5
    if maximum<=0:
        return 0.

    def clear(progress):
        end = along+follower_length*(progress/follower_path.ends[0])
        swept = [(-along,-half_width),(end,-half_width),(end,half_width),(-along,half_width)]
        return (all(polygon_distance(swept,rectangle)>clearance for rectangle in rectangles)
                and all(_clear_box(hull,-along,end,half_width,disc_clearance) for hull in mixed_hulls))

    if clear(maximum):
        return maximum
    if not clear(0.):
        return 0.
    lower,upper = 0.,maximum
    while upper-lower>.01:
        middle = (lower+upper)/2
        if clear(middle):
            lower = middle
        else:
            upper = middle
    return lower


def inside_departure_room(path, horizon, polygon, margin, *,
                          max_step_s=.05, velocity_mm_s=None, acceleration_mm_s2=None):
    """Certify the expanded straight sweep is in the original simple room polygon."""
    if not math.isfinite(margin) or margin < 0:
        raise ValueError('Finite nonnegative room envelope margin required')
    frame = _straight_frame(path)
    if (frame is None or len(polygon) < 3 or not 0 < horizon <= path.ends[0] or
            not all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in polygon)):
        return False
    a, b = path.pieces[0]['controls']
    if not point_in_polygon(a[:2], polygon):
        return False
    limits = _limits(max_step_s, velocity_mm_s, acceleration_mm_s2)
    clearance = margin + _fit_margin(path.pieces[:1], limits) + _roundoff([a, b, *polygon])
    project, length = frame
    edges = [project(point) for point in polygon]
    length *= horizon / path.ends[0]
    return all(_clear([a, b], length, clearance) for a, b in zip(edges, edges[1:]+edges[:1]))
