"""Portable exact line/arc centreline and hollow pneumatic-hose sweep.

The two CAD adapters receive the same tangent circular fillets.  They do not
independently fit splines.  Bend and volume values describe this static geometry;
they do not qualify a selected hose, pressure response or full-range routing.
"""
import math

SOLIDCRAFT_PROFILE_SEAM_DEG = 90


def _sub(a, b):
    return [x-y for x, y in zip(a, b)]


def _add(a, b):
    return [x+y for x, y in zip(a, b)]


def _mul(a, value):
    return [x*value for x in a]


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _unit(a):
    length = math.sqrt(_dot(a, a))
    if length < 1e-9:
        raise ValueError('A hose direction requires distinct points')
    return _mul(a, 1/length)


def _point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('Hose points need three finite coordinates in mm')
    return list(map(float, value))


def _rotate(vector, axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    return _add(_add(_mul(vector, c), _mul(_cross(axis, vector), s)),
                _mul(axis, _dot(axis, vector)*(1-c)))


class HoseBendError(ValueError):
    """A hard geometric route constraint failed, with a serializable witness."""

    def __init__(self, message, witness):
        super().__init__(message)
        self.witness = witness


def _endpoint_straights(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in value)):
        raise ValueError('Endpoint straight lengths need two nonnegative finite values in mm')
    return list(map(float, value))


def centerline(control_points, bend_radius=12.0, sample_step_mm=3.0, *,
               endpoint_straights_mm=(0.0, 0.0)):
    """Round corners at the requested hard radius, or reject the route.

    Each span must contain both adjacent tangent setbacks R*tan(turn/2),
    together with its endpoint's requested straight lead. Collinear construction
    points do not consume tangent space. No radius is silently reduced.
    Endpoint leads can reserve connector, clamp or guide-exit straight lengths;
    the caller supplies their physical meaning and qualification separately.
    """
    if not isinstance(control_points, (list, tuple)):
        raise ValueError('Hose controls must be a sequence of points')
    points = [_point(p) for p in control_points]
    if len(points) < 2:
        raise ValueError('A hose needs at least two points')
    if (type(bend_radius) not in (int, float) or not math.isfinite(bend_radius) or bend_radius <= 0
            or type(sample_step_mm) not in (int, float) or not math.isfinite(sample_step_mm) or sample_step_mm <= 0):
        raise ValueError('Positive finite bend radius and sampling step required')
    leads = _endpoint_straights(endpoint_straights_mm)
    original_lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    if min(original_lengths) < 1e-6:
        raise ValueError('Consecutive hose points must be distinct')
    active = [0]
    for i, b in enumerate(points[1:-1], 1):
        incoming = _unit(_sub(b, points[i-1]))
        outgoing = _unit(_sub(points[i+1], b))
        angle = math.acos(max(-1.0, min(1.0, _dot(incoming, outgoing))))
        if math.pi-angle < 1e-5:
            raise HoseBendError('Hose route reverses at control %d' % i,
                                {'kind': 'reversal', 'control_index': i, 'point_mm': b,
                                 'required_radius_mm': float(bend_radius)})
        if angle >= 1e-7:
            active.append(i)
    active.append(len(points)-1)
    effective = [points[i] for i in active]
    lengths = [math.dist(a, b) for a, b in zip(effective, effective[1:])]
    setbacks = [0.0]*len(effective)
    corners = []
    for i, b in enumerate(effective[1:-1], 1):
        incoming = _unit(_sub(b, effective[i-1]))
        outgoing = _unit(_sub(effective[i+1], b))
        angle = math.acos(max(-1.0, min(1.0, _dot(incoming, outgoing))))
        distance = bend_radius*math.tan(angle/2)
        setbacks[i] = distance
        corners.append((incoming, outgoing, angle))
    spans = []
    for i, available in enumerate(lengths):
        reserved = [leads[0] if i == 0 else 0.0,
                    leads[1] if i == len(lengths)-1 else 0.0]
        required = setbacks[i]+setbacks[i+1]+sum(reserved)
        witness = {'kind': 'insufficient_tangent_space',
                   'segment_index': i, 'control_indices': [active[i], active[i+1]],
                   'start_mm': effective[i], 'end_mm': effective[i+1],
                   'available_mm': available, 'required_mm': required,
                   'tangent_setbacks_mm': [setbacks[i], setbacks[i+1]],
                   'endpoint_straights_mm': reserved, 'required_radius_mm': float(bend_radius)}
        if required > available+1e-9:
            raise HoseBendError('Hose span %d (controls %d..%d) needs %.9g mm for radius %.9g mm '
                                'and endpoint straights, but has %.9g mm' %
                                (i, active[i], active[i+1], required, bend_radius, available), witness)
        spans.append({**witness, 'remaining_straight_mm': max(0.0, available-setbacks[i]-setbacks[i+1]),
                      'unreserved_straight_mm': max(0.0, available-required)})
    rounded = []
    for i, (incoming, outgoing, angle) in enumerate(corners, 1):
        b = effective[i];distance = setbacks[i];radius = float(bend_radius)
        start, end = _sub(b, _mul(incoming, distance)), _add(b, _mul(outgoing, distance))
        centre = _add(b, _mul(_unit(_sub(outgoing, incoming)), radius/math.cos(angle/2)))
        axis = _unit(_cross(incoming, outgoing))
        radial = _sub(start, centre)
        through = _add(centre, _rotate(radial, axis, angle/2))
        rounded.append({'kind': 'arc', 'start_mm': start, 'through_mm': through,
                        'end_mm': end, 'center_mm': centre, 'axis': axis,
                        'radius_mm': radius, 'sweep_rad': angle, 'length_mm': radius*angle})
    segments, current = [], points[0]

    def line(end):
        nonlocal current
        length = math.dist(current, end)
        if length > 1e-7:
            segments.append({'kind': 'line', 'start_mm': current, 'end_mm': end,
                             'length_mm': length})
        current = end

    for rounded_corner in rounded:
        line(rounded_corner['start_mm'])
        segments.append(rounded_corner)
        current = rounded_corner['end_mm']
    line(points[-1])
    samples = [points[0]]
    for segment in segments:
        count = max(1, math.ceil(segment['length_mm']/sample_step_mm))
        for j in range(1, count+1):
            t = j/count
            if j == count:
                point = segment['end_mm']
            elif segment['kind'] == 'line':
                point = _add(segment['start_mm'], _mul(_sub(segment['end_mm'], segment['start_mm']), t))
            else:
                point = _add(segment['center_mm'], _rotate(_sub(segment['start_mm'], segment['center_mm']),
                    segment['axis'], t*segment['sweep_rad']))
            samples.append(point)
    radii = [s['radius_mm'] for s in segments if s['kind'] == 'arc']
    return {'format': 'solidcraftbot.static-hose-centerline/1', 'controls_mm': points,
            'segments': segments, 'sample_points_mm': samples,
            'length_mm': sum(s['length_mm'] for s in segments),
            'requested_bend_radius_mm': float(bend_radius),
            'min_bend_radius_mm': min(radii) if radii else None,
            'bend_constraints': {'hard_minimum_radius_mm': float(bend_radius),
                                 'endpoint_straights_mm': leads, 'spans': spans},
            'qualified': False}


def _path(value):
    if isinstance(value, dict):
        if value.get('format') != 'solidcraftbot.static-hose-centerline/1' or not value.get('segments'):
            raise ValueError('Unsupported hose centreline')
        return value
    return centerline(value)


def _radii(inner_radius, outer_radius, path):
    if (any(type(r) not in (int, float) or not math.isfinite(r) for r in (inner_radius, outer_radius))
            or not 0 < inner_radius < outer_radius):
        raise ValueError('Hose radii need 0 < inner < outer')
    minimum = path['min_bend_radius_mm']
    if minimum is not None and minimum <= outer_radius:
        raise ValueError('Drawn hose bend radius must exceed its outer radius')


def diagnostics(path, inner_radius, outer_radius):
    path = _path(path)
    _radii(inner_radius, outer_radius, path)
    return {'length_mm': path['length_mm'], 'min_bend_radius_mm': path['min_bend_radius_mm'],
            'air_volume_ul': math.pi*inner_radius**2*path['length_mm'],
            'wall_volume_mm3': math.pi*(outer_radius**2-inner_radius**2)*path['length_mm'],
            'inner_radius_mm': inner_radius, 'outer_radius_mm': outer_radius,
            'scope': 'Static ideal circular sweep only; no selected-hose, compliance, pressure or full-joint-range qualification'}


def _start_frame(path):
    segment = path['segments'][0]
    if segment['kind'] == 'line':
        tangent = _unit(_sub(segment['end_mm'], segment['start_mm']))
    else:
        tangent = _unit(_cross(segment['axis'], _sub(segment['start_mm'], segment['center_mm'])))
    seed = [1., 0., 0.] if abs(tangent[0]) < .8 else [0., 1., 0.]
    x = _unit(_sub(seed, _mul(tangent, _dot(seed, tangent))))
    return segment['start_mm'], tangent, x, _cross(tangent, x)


def solidcraft_commands(path, inner_radius, outer_radius, name='PneumaticHose'):
    """Sweep the annulus with a fixed, geometry-preserving circle parameter seam."""
    path = _path(path)
    _radii(inner_radius, outer_radius, path)
    if not isinstance(name, str) or not name or not name.replace('_', '').isalnum():
        raise ValueError('Hose name must be a simple CAD identifier')
    start, tangent, x, y = _start_frame(path)
    # A quarter turn only changes the rational circles' parameter origins.
    # SMLib can otherwise reject the analytic/NURBS correspondence on a thin,
    # large-radius torus after spatial placement.  The annulus and wire remain
    # exactly the same; FreeCAD's independent segment construction is untouched.
    x, y = y, _mul(x, -1)
    commands = []
    def add(command, **params):
        commands.append({'command': command, 'params': params})
    add('sketch.create', name=name+'_Path', plane='XY')
    add('sketch.options', sketch_3d=True)
    for segment in path['segments']:
        if segment['kind'] == 'line':
            add('sketch.line3d', points=[segment['start_mm'], segment['end_mm']])
        else:
            add('sketch.arc3d', start=segment['start_mm'], through=segment['through_mm'], end=segment['end_mm'])
    add('sketch.finish')
    add('sketch.create', name=name+'_OuterProfile', plane={'origin': start, 'x_dir': x, 'y_dir': y})
    add('sketch.circle.center', center=[0, 0], radius=outer_radius)
    add('sketch.circle.center', center=[0, 0], radius=inner_radius)
    add('sketch.finish')
    # The outer-boundary selection retains its inner loop as a hole.  Selecting
    # all profile regions would also include the inner disc and fill the lumen.
    # One annular sweep avoids a numerically unstable Boolean between coincident
    # swept torus surfaces on long, spatially routed hoses.
    add('solid.sweep', sketch=name+'_OuterProfile', path_sketch=name+'_Path',
        path=['w'+str(i+1) for i in range(len(path['segments']))],
        profiles=[{'curves': ['c1']}], orientation='perpendicular',
        operation='new', name=name, body_name=name)
    add('appearance.assign', bodies=[name], color='#66b8d4', opacity=.85)
    add('browser.visibility', folder='sketches', visible=False)
    return commands


def freecad_wire(Part, App, path):
    """The exact common centreline as a native wire, also usable for bore probes."""
    path = _path(path)
    edges = []
    for s in path['segments']:
        if s['kind'] == 'line':
            edges.append(Part.makeLine(App.Vector(*s['start_mm']), App.Vector(*s['end_mm'])))
        else:
            edges.append(Part.Arc(App.Vector(*s['start_mm']), App.Vector(*s['through_mm']), App.Vector(*s['end_mm'])).toShape())
    return Part.Wire(edges)


def self_clearance_diagnostics(path, outer_radius, sample_step_mm=.5):
    """Screen nonlocal tube branches with finite samples and a spacing margin.

    The distance bound covers station pairs whose arc-length separation is
    at least the excluded neighborhood plus one sample step. Local sweep
    topology and dynamic self-clearance remain separate native/physical checks.
    """
    path = _path(path)
    if (type(outer_radius) not in (int, float) or not math.isfinite(outer_radius) or outer_radius <= 0
            or type(sample_step_mm) not in (int, float) or not math.isfinite(sample_step_mm) or sample_step_mm <= 0):
        raise ValueError('Positive finite tube radius and self-clearance sample step required')
    _joined_path(path)
    points = [list(path['segments'][0]['start_mm'])]
    positions, indices = [0.0], [0]
    covered = 0.0
    for index, segment in enumerate(path['segments']):
        count = max(1, math.ceil(segment['length_mm']/sample_step_mm))
        for j in range(1, count+1):
            fraction = j/count
            if j == count:
                point = list(segment['end_mm'])
            elif segment['kind'] == 'line':
                point = _add(segment['start_mm'], _mul(_sub(segment['end_mm'], segment['start_mm']), fraction))
            else:
                point = _add(segment['center_mm'], _rotate(_sub(segment['start_mm'], segment['center_mm']),
                                                          segment['axis'], segment['sweep_rad']*fraction))
            points.append(point);positions.append(covered+segment['length_mm']*fraction);indices.append(index)
        covered += segment['length_mm']
    exclusion = 4*outer_radius+2*sample_step_mm
    minimum, witness, pairs = math.inf, None, 0
    for i, point in enumerate(points):
        for j in range(i+1, len(points)):
            if positions[j]-positions[i] < exclusion:
                continue
            pairs += 1
            distance = math.dist(point, points[j])
            if distance < minimum:
                minimum = distance
                witness = {'first': {'segment_index': indices[i], 'arc_length_mm': positions[i], 'point_mm': point},
                           'second': {'segment_index': indices[j], 'arc_length_mm': positions[j], 'point_mm': points[j]}}
    bound = max(0.0, minimum-sample_step_mm) if math.isfinite(minimum) else None
    return {'passed': bound is None or bound > 2*outer_radius,
            'sample_count': len(points), 'checked_pairs': pairs, 'sample_step_mm': sample_step_mm,
            'excluded_arc_length_neighborhood_mm': exclusion,
            'distance_bound_pair_domain_minimum_arc_separation_mm': exclusion+sample_step_mm,
            'minimum_sampled_centerline_distance_mm': minimum if math.isfinite(minimum) else None,
            'sample_spacing_distance_lower_bound_mm': bound,
            'required_centerline_separation_mm': 2*outer_radius,
            'near_segment_witness': witness, 'continuous_self_clearance_verified': False,
            'scope': 'Finite static nonlocal station-pair screening with a sample-spacing distance bound; '
                     'the excluded local neighborhood, native sweep topology and dynamic/hardware behavior are not qualified'}


def freecad_shape(Part, App, path, inner_radius, outer_radius):
    """Fuse exact segment annuli and verify a continuous, unobstructed native tube.

    OCC can return a valid tiny remnant when two long whole-wire pipe shells
    are subtracted.  Local annuli avoid that operation; analytic volume and
    endpoint/lumen witnesses still reject Boolean loss and real self-crossings.
    """
    path = _path(path)
    _radii(inner_radius, outer_radius, path)
    _joined_path(path)
    pieces = []
    for segment in path['segments']:
        start, tangent, _, _ = _start_frame({'segments': [segment]})
        if segment['kind'] == 'line':
            length = math.dist(segment['start_mm'], segment['end_mm'])

            def sweep(radius):
                return Part.makeCylinder(radius, length, App.Vector(*start), App.Vector(*tangent))
        else:
            wire = freecad_wire(Part, App, {'format': path['format'], 'segments': [segment]})

            def sweep(radius):
                profile = Part.Wire([Part.makeCircle(radius, App.Vector(*start), App.Vector(*tangent))])
                return wire.makePipeShell([profile], True, False)
        piece = sweep(outer_radius).cut(sweep(inner_radius)).removeSplitter()
        expected = math.pi*(outer_radius**2-inner_radius**2)*segment['length_mm']
        if (not piece.isValid() or len(piece.Solids) != 1 or piece.Volume <= 0
                or abs(piece.Volume-expected) > 1e-5):
            raise ValueError('Native hose segment did not form its complete annulus')
        pieces.append(piece.Solids[0])
    result = (pieces[0].multiFuse(pieces[1:]) if len(pieces) > 1 else pieces[0]).removeSplitter()
    if not result.isValid() or len(result.Solids) != 1 or result.Volume <= 0:
        raise ValueError('Native hose sweep did not form one valid hollow solid')
    expected = math.pi*(outer_radius**2-inner_radius**2)*path['length_mm']
    if abs(result.Volume-expected) > 1e-5:
        raise ValueError('Native hose wall volume mismatch (observed %.12g, expected %.12g mm3); '
                         'possible self-intersection or Boolean loss' % (result.Volume, expected))
    if result.common(freecad_wire(Part, App, path)).Length > 1e-7:
        raise ValueError('Native hose material obstructs the shared centerline')
    for end in (False, True):
        station = path['segments'][-1 if end else 0]
        point = station['end_mm' if end else 'start_mm']
        frame = _start_frame({'segments': [station]})
        tangent = (frame[1] if not end or station['kind'] == 'line' else
                   _unit(_cross(station['axis'], _sub(point, station['center_mm']))))
        seed = [1., 0., 0.] if abs(tangent[0]) < .8 else [0., 1., 0.]
        radial = _unit(_sub(seed, _mul(tangent, _dot(seed, tangent))))
        wall = _add(point, _mul(radial, (inner_radius+outer_radius)/2))
        center_gap = result.distToShape(Part.Vertex(App.Vector(*point)))[0]
        wall_gap = result.distToShape(Part.Vertex(App.Vector(*wall)))[0]
        if abs(center_gap-inner_radius) > 1e-6 or wall_gap > 1e-7:
            raise ValueError('Native hose endpoint annulus or open bore is missing')
    return result.Solids[0]


def _joined_path(path):
    """A circular sweep cannot hide a C0-only splice as a positive bend radius."""
    for before, after in zip(path['segments'], path['segments'][1:]):
        if math.dist(before['end_mm'], after['start_mm']) > 1e-7:
            raise ValueError('Native hose segments must meet at a common endpoint')
        incoming = (_unit(_sub(before['end_mm'], before['start_mm'])) if before['kind'] == 'line'
                    else _unit(_cross(before['axis'], _sub(before['end_mm'], before['center_mm']))))
        outgoing = _start_frame({'segments': [after]})[1]
        if math.dist(incoming, outgoing) > 1e-7:
            raise ValueError('Native hose segments must have a common tangent')
