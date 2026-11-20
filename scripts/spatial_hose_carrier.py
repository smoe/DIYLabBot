"""Static exact-circle carrier envelopes and nominal arc-length collar stations.

The caller supplies source-bound endpoints in a declared guide frame. No robot,
CAD artifact, ball-joint mechanics, pressure or dynamic hose model is consulted.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import pneumatic_hose

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/spatial-hose-carrier.shared.json'


def _number(value, name, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (positive and value <= 0)):
        raise ValueError('Invalid finite carrier quantity: '+name)
    return float(value)


def _vector(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('A finite three-vector is required')
    return [_number(v, 'vector') for v in value]


def _add(a, b): return [x+y for x, y in zip(a, b)]
def _sub(a, b): return [x-y for x, y in zip(a, b)]
def _mul(a, scale): return [x*scale for x in a]
def _dot(a, b): return sum(x*y for x, y in zip(a, b))
def _norm(a): return math.sqrt(_dot(a, a))
def _cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _unit(a):
    length = _norm(a)
    if length < 1e-10:
        raise ValueError('A nonzero carrier tangent is required')
    return _mul(a, 1/length)


def validate(profile):
    schema = json.loads((ROOT/'model/spatial-hose-carrier.schema.json').read_text())
    if not isinstance(profile, dict) or set(profile) != set(schema['required']):
        raise ValueError('Unsupported carrier source fields')
    for key in ('format', 'id', 'units'):
        if profile[key] != schema['properties'][key]['const']:
            raise ValueError('Unsupported carrier source: '+key)
    for key in ('reference', 'geometry', 'guide_fit', 'qualification', 'open_requirements'):
        required = set(schema['properties'][key]['required'])
        allowed = required | ({'seed_mode'} if key == 'guide_fit' else set())
        if (not isinstance(profile[key], dict) or not required <= set(profile[key])
                or not set(profile[key]) <= allowed):
            raise ValueError('Invalid carrier source section: '+key)
    if any(type(value) is not bool or value for value in profile['qualification'].values()):
        raise ValueError('Carrier hardware and articulation remain unqualified')
    if any(value is not None for value in profile['open_requirements'].values()):
        raise ValueError('Carrier article, channel, mounts and articulation requirements remain open')
    ref = profile['reference']
    for key in ('published_outer_diameter_mm', 'published_bend_radius_mm', 'published_pitch_mm'):
        if ref[key] != schema['properties']['reference']['properties'][key]['const']:
            raise ValueError('Published carrier reference dimensions must not be silently changed')
    brochure = ref['brochure']
    if not isinstance(brochure, dict) or set(brochure) != {'path', 'sha256', 'url', 'revision_scope'}:
        raise ValueError('A pinned historical manufacturer reference is required')
    path = (ROOT/brochure['path']).resolve()
    if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != brochure['sha256']:
        raise ValueError('Carrier reference checksum mismatch')
    g = profile['geometry'];lo, hi = g['nominal_link_count_range']
    if (g['nominal_link_count_range'] != [20, 120] or type(g['nominal_link_count']) is not int
            or not lo <= g['nominal_link_count'] <= hi):
        raise ValueError('Nominal carrier collar count outside declared range')
    for key in ('nominal_pitch_mm', 'outer_radius_mm', 'inner_radius_mm', 'minimum_centerline_bend_radius_mm'):
        _number(g[key], key, True)
    if (g['nominal_pitch_mm'] != 11.3 or g['outer_radius_mm'] != 17.25
            or not 0 < g['inner_radius_mm'] < g['outer_radius_mm']
            or g['minimum_centerline_bend_radius_mm'] < 50):
        raise ValueError('Carrier envelope or bend requirement contradicts reference')
    ring = g['ring_geometry']
    if not isinstance(ring, dict) or set(ring) != {'width_mm', 'outer_radius_mm', 'inner_radius_mm'}:
        raise ValueError('Nominal collar geometry is required')
    for key, value in ring.items():
        _number(value, key, True)
    deviation = ring['width_mm']**2/(8*(g['minimum_centerline_bend_radius_mm']-ring['outer_radius_mm']))
    if (ring['width_mm'] >= g['nominal_pitch_mm']
            or ring['outer_radius_mm']+deviation >= g['outer_radius_mm']
            or ring['inner_radius_mm']-deviation <= g['inner_radius_mm']
            or ring['inner_radius_mm'] >= ring['outer_radius_mm']):
        raise ValueError('Nominal collars need positive conservative envelope margins')
    f = profile['guide_fit']
    if f['family'] != 'two_exact_spatial_biarcs':
        raise ValueError('Unsupported carrier guide family')
    if f.get('seed_mode', 'chord_midpoint') not in ('chord_midpoint', 'endpoint_biarc'):
        raise ValueError('Unsupported carrier guide seed mode')
    if not isinstance(f['offsets_xz_mm'], list) or not f['offsets_xz_mm']:
        raise ValueError('At least one declared carrier guide offset is required')
    for offset in f['offsets_xz_mm']:
        if not isinstance(offset, list) or len(offset) != 2:
            raise ValueError('Guide offsets must be X/Z pairs')
        for value in offset:
            _number(value, 'guide offset')
    limits = f['service_y_range_mm']
    if not isinstance(limits, list) or len(limits) != 2:
        raise ValueError('A finite service-guide interval is required')
    for value in limits:
        _number(value, 'service guide')
    if not 0 <= limits[0] < limits[1]:
        raise ValueError('Invalid service-guide interval')
    for key in ('service_y_step_mm', 'length_tolerance_mm', 'sample_step_mm'):
        _number(f[key], key, True)
    if type(f['fit_iterations']) is not int or not 1 <= f['fit_iterations'] <= 80:
        raise ValueError('A bounded integer fit iteration count is required')
    for value in (profile['status'], g['pitch_scope'], f['scope'], *profile['limitations']):
        if not isinstance(value, str) or not value:
            raise ValueError('Carrier scope and limitations must remain explicit')
    return profile


def load(path=SOURCE):
    return validate(json.loads(Path(path).read_text()))


def _rotate(v, axis, angle):
    return _add(_add(_mul(v, math.cos(angle)), _mul(_cross(axis, v), math.sin(angle))),
                _mul(axis, _dot(axis, v)*(1-math.cos(angle))))


def _arc(start, end, tangent):
    delta = _sub(end, start)
    normal = _sub(delta, _mul(tangent, _dot(delta, tangent)))
    squared = _dot(normal, normal)
    if squared < 1e-16:
        if _dot(delta, tangent) <= 0:
            raise ValueError('A backwards collinear arc has no finite circle')
        return {'kind': 'line', 'start_mm': start, 'end_mm': end, 'length_mm': _norm(delta)}
    center = _add(start, _mul(normal, _dot(delta, delta)/(2*squared)))
    radial = _sub(start, center);radius = _norm(radial)
    axis = _unit(_cross(tangent, delta));end_radial = _sub(end, center)
    angle = math.atan2(_dot(axis, _cross(radial, end_radial)), _dot(radial, end_radial)) % (2*math.pi)
    if angle < 1e-12:
        raise ValueError('Degenerate circular carrier arc')
    return {'kind': 'arc', 'start_mm': start, 'end_mm': end,
            'through_mm': _add(center, _rotate(radial, axis, angle/2)),
            'center_mm': center, 'axis': axis, 'radius_mm': radius,
            'sweep_rad': angle, 'length_mm': radius*angle}


def _biarc(start, end, tangent_start, tangent_end):
    delta = _sub(end, start)
    a = 2*(1-max(-1.0, min(1.0, _dot(tangent_start, tangent_end))))
    b = 2*_dot(delta, _add(tangent_start, tangent_end));squared = _dot(delta, delta)
    if squared < 1e-14:
        raise ValueError('Biarc endpoints must be distinct')
    if a < 1e-10:
        if b <= 0:
            raise ValueError('Parallel backwards biarc is unsupported')
        distance = squared/b
    else:
        distance = (-b+math.sqrt(b*b+4*a*squared))/(2*a)
    join = _mul(_add(_add(start, end), _mul(_sub(tangent_start, tangent_end), distance)), .5)
    first = _arc(start, join, tangent_start)
    second = _arc(end, join, _mul(tangent_end, -1))
    second['start_mm'], second['end_mm'] = second['end_mm'], second['start_mm']
    if second['kind'] == 'arc':
        second['axis'] = _mul(second['axis'], -1)
    return [first, second]


def _at(segment, fraction):
    if segment['kind'] == 'line':
        return (_add(segment['start_mm'], _mul(_sub(segment['end_mm'], segment['start_mm']), fraction)),
                _unit(_sub(segment['end_mm'], segment['start_mm'])))
    radial = _rotate(_sub(segment['start_mm'], segment['center_mm']), segment['axis'],
                     segment['sweep_rad']*fraction)
    return _add(segment['center_mm'], radial), _unit(_cross(segment['axis'], radial))


def path_position(path, distance_mm):
    """Return an exact center and tangent at an arc-length station."""
    value = _number(distance_mm, 'arc-length station')
    if not 0 <= value <= path['length_mm']:
        raise ValueError('Carrier station outside the path')
    for index, segment in enumerate(path['segments']):
        if value <= segment['length_mm'] or index == len(path['segments'])-1:
            fraction = max(0.0, min(1.0, value/segment['length_mm']))
            point, tangent = _at(segment, fraction)
            if fraction == 0: point = list(segment['start_mm'])
            if fraction == 1: point = list(segment['end_mm'])
            return {'point_mm': point, 'tangent': tangent}
        value -= segment['length_mm']
    raise ValueError('Empty carrier path')


def _path(segments, controls, minimum_radius, step):
    samples = [list(segments[0]['start_mm'])]
    for segment in segments:
        count = max(1, math.ceil(segment['length_mm']/step))
        samples.extend(_at(segment, i/count)[0] if i < count else list(segment['end_mm'])
                       for i in range(1, count+1))
    radii = [segment['radius_mm'] for segment in segments if segment['kind'] == 'arc']
    return {'format': 'solidcraftbot.static-hose-centerline/1', 'controls_mm': controls,
            'segments': segments, 'sample_points_mm': samples,
            'length_mm': sum(segment['length_mm'] for segment in segments),
            'requested_bend_radius_mm': minimum_radius,
            'min_bend_radius_mm': min(radii) if radii else None, 'qualified': False}


def biarc_path(start_mm, end_mm, start_tangent, end_tangent, minimum_radius_mm, *,
               endpoint_straights_mm=(0.0, 0.0), sample_step_mm=3.0):
    """Connect framed endpoints with exact G1 arcs and hard radius/lead checks.

    This is one endpoint-tangent biarc construction, not a shortest-route or
    collision planner. A failed radius constraint is never repaired by shrinking
    it; callers can choose another source-defined frame or route family.
    """
    start, end = _vector(start_mm), _vector(end_mm)
    t0, t1 = _unit(_vector(start_tangent)), _unit(_vector(end_tangent))
    minimum = _number(minimum_radius_mm, 'minimum bend radius', True)
    step = _number(sample_step_mm, 'sample step', True)
    leads = pneumatic_hose._endpoint_straights(endpoint_straights_mm)
    inner_start = _add(start, _mul(t0, leads[0]))
    inner_end = _sub(end, _mul(t1, leads[1]))
    witness = {'kind': 'endpoint_tangent_biarc', 'start_mm': start, 'end_mm': end,
               'start_tangent': t0, 'end_tangent': t1,
               'endpoint_straights_mm': leads, 'required_radius_mm': minimum}
    try:
        arcs = _biarc(inner_start, inner_end, t0, t1)
    except ValueError as error:
        raise pneumatic_hose.HoseBendError('Endpoint-tangent biarc is infeasible: '+str(error), witness) from error
    for index, segment in enumerate(arcs):
        if segment['kind'] == 'arc' and segment['radius_mm'] < minimum-1e-9:
            raise pneumatic_hose.HoseBendError(
                'Endpoint-tangent biarc %d has radius %.9g mm below required %.9g mm' %
                (index, segment['radius_mm'], minimum),
                {**witness, 'segment_index': index, 'achieved_radius_mm': segment['radius_mm'],
                 'arc_start_mm': segment['start_mm'], 'arc_end_mm': segment['end_mm']})
    segments = []
    if leads[0] > 0:
        segments.append({'kind': 'line', 'start_mm': start, 'end_mm': inner_start, 'length_mm': leads[0]})
    segments.extend(arcs)
    if leads[1] > 0:
        segments.append({'kind': 'line', 'start_mm': inner_end, 'end_mm': end, 'length_mm': leads[1]})
    controls = [start]+([inner_start] if leads[0] > 0 else [])
    controls += [arcs[0]['end_mm']]+([inner_end] if leads[1] > 0 else [])+[end]
    result = _path(segments, controls, minimum, step)
    pneumatic_hose._joined_path(result)
    result['endpoint_tangent_constraints'] = witness
    return result


def _nonlocal_samples(path, outer_radius, step=5):
    """Reject nearby nonlocal stations; record finite coverage, not tube reach."""
    points, distances = [], []
    covered = 0.0
    for segment in path['segments']:
        count = max(1, math.ceil(segment['length_mm']/step))
        for index in range(count):
            points.append(_at(segment, index/count)[0])
            distances.append(covered+segment['length_mm']*index/count)
        covered += segment['length_mm']
    points.append(path['segments'][-1]['end_mm']);distances.append(covered)
    exclusion = 2*path['requested_bend_radius_mm']
    minimum = math.inf
    for i, point in enumerate(points):
        for j in range(i+1, len(points)):
            if distances[j]-distances[i] >= exclusion:
                minimum = min(minimum, math.dist(point, points[j]))
    bound = minimum-step
    return {'passed': bound > 2*outer_radius,
            'maximum_sample_step_mm': step,
            'excluded_arc_length_neighborhood_mm': exclusion,
            'minimum_sampled_distance_mm': minimum if math.isfinite(minimum) else None,
            'sample_spacing_distance_lower_bound_mm': bound if math.isfinite(bound) else None,
            'scope': 'Finite nonlocal station pairs with a sample-spacing margin; local sweep topology and continuous tube reach require native checks'}


def fit(profile, start_mm, end_mm, start_tangent, end_tangent, *, guide_offset_xz_mm=None,
        search_axes=None, endpoint_straights_mm=(0.0, 0.0), seed_mode=None):
    """Fit four G1 circular arcs to the fixed nominal carrier length.

    Radius is constant on each native arc. ``search_axes`` are orthonormal
    right-handed X/Y/Z vectors in the caller's coordinates; offsets are relative
    to the declared seed. The default seed is the core chord midpoint; the
    endpoint-biarc seed uses that biarc's exact join and tangent instead.
    Optional endpoint straights are part of
    the nominal length, not added afterwards. The finite offset/interval search
    makes no completeness, clearance, self-intersection or motion claim.
    """
    start, end = _vector(start_mm), _vector(end_mm)
    t0, t1 = _unit(_vector(start_tangent)), _unit(_vector(end_tangent))
    leads = pneumatic_hose._endpoint_straights(endpoint_straights_mm)
    if search_axes is None:
        axes = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
    else:
        if not isinstance(search_axes, (list, tuple)) or len(search_axes) != 3:
            raise ValueError('Carrier search frame needs three orthonormal right-handed axes')
        axes = [_vector(axis) for axis in search_axes]
        if (any(abs(_dot(a, b)-(1 if i == j else 0)) > 1e-8
                for i, a in enumerate(axes) for j, b in enumerate(axes))
                or _dot(_cross(axes[0], axes[1]), axes[2]) < 1-1e-8):
            raise ValueError('Carrier search axes must be orthonormal and right-handed')
    inner_start = _add(start, _mul(t0, leads[0]))
    inner_end = _sub(end, _mul(t1, leads[1]))
    mode = profile['guide_fit'].get('seed_mode', 'chord_midpoint') if seed_mode is None else seed_mode
    if mode == 'endpoint_biarc':
        seed = _biarc(inner_start, inner_end, t0, t1)
        midpoint, middle_tangent = _at(seed[0], 1)
    elif mode == 'chord_midpoint':
        middle_tangent = _unit(_sub(inner_end, inner_start))
        midpoint = _mul(_add(inner_start, inner_end), .5)
    else:
        raise ValueError('Unsupported carrier guide seed mode')
    g, f = profile['geometry'], profile['guide_fit']
    target = g['nominal_link_count']*g['nominal_pitch_mm'];minimum = g['minimum_centerline_bend_radius_mm']
    core_target = target-sum(leads)
    if (core_target <= 0 or _norm(_sub(end, start)) > target+f['length_tolerance_mm']
            or _norm(_sub(inner_end, inner_start)) > core_target+f['length_tolerance_mm']):
        raise ValueError('Nominal carrier length cannot span its endpoints')
    offsets = f['offsets_xz_mm']
    if guide_offset_xz_mm is not None:
        if not isinstance(guide_offset_xz_mm, (list, tuple)) or len(guide_offset_xz_mm) != 2:
            raise ValueError('A forced guide offset must be an X/Z pair')
        offsets = [[_number(value, 'guide offset') for value in guide_offset_xz_mm]]
    lo, hi = f['service_y_range_mm'];intervals = max(1, math.ceil((hi-lo)/f['service_y_step_mm']))
    attempted = 0
    for x, z in offsets:
        def evaluate(y):
            displacement = [sum(axis[i]*value for axis, value in zip(axes, (x, y, z))) for i in range(3)]
            point = _add(midpoint, displacement)
            segments = _biarc(inner_start, point, t0, middle_tangent)+_biarc(point, inner_end, middle_tangent, t1)
            if leads[0] > 0:
                segments.insert(0, {'kind': 'line', 'start_mm': start, 'end_mm': inner_start, 'length_mm': leads[0]})
            if leads[1] > 0:
                segments.append({'kind': 'line', 'start_mm': inner_end, 'end_mm': end, 'length_mm': leads[1]})
            length = sum(segment['length_mm'] for segment in segments)
            radii = [segment['radius_mm'] for segment in segments if segment['kind'] == 'arc']
            return length, min(radii, default=math.inf), segments, point

        previous = None
        for index in range(intervals+1):
            y = lo if index == 0 else hi if index == intervals else lo+(hi-lo)*index/intervals
            attempted += 1
            try:
                current = evaluate(y)
            except ValueError:
                previous = None
                continue
            if previous is not None and (current[0]-target)*(previous[1][0]-target) <= 0:
                low, high = previous[0], y
                try:
                    for _ in range(f['fit_iterations']):
                        mid = (low+high)/2;candidate = evaluate(mid)
                        if (candidate[0]-target)*(previous[1][0]-target) > 0: low = mid
                        else: high = mid
                    chosen = (low+high)/2;length, radius, segments, point = evaluate(chosen)
                except ValueError:
                    previous = (y, current)
                    continue
                if radius >= minimum and abs(length-target) <= f['length_tolerance_mm']:
                    controls = [start]+([inner_start] if leads[0] > 0 else [])+[point]
                    controls += ([inner_end] if leads[1] > 0 else [])+[end]
                    result = _path(segments, controls, minimum, f['sample_step_mm'])
                    pneumatic_hose._joined_path(result)
                    self_check = _nonlocal_samples(result, g['outer_radius_mm'])
                    if not self_check['passed']:
                        previous = (y, current)
                        continue
                    result['carrier_fit'] = {'nominal_link_count': g['nominal_link_count'],
                        'nominal_pitch_mm': g['nominal_pitch_mm'], 'target_length_mm': target,
                        'length_error_mm': length-target, 'guide_offset_xz_mm': [x, z],
                        'search_axes': axes, 'endpoint_straights_mm': leads,
                        'seed_mode': mode,
                        'service_y_mm': chosen, 'evaluated_bracket_endpoints': attempted,
                        'nonlocal_self_check': self_check,
                        'scope': 'Static exact circles and nominal arc-length pitch; arm clearance, continuous tube reach and dynamics unverified'}
                    return result
            previous = (y, current)
    raise ValueError('No declared static carrier guide meets nominal length and circular-arc radius')


def transform_path(path, matrix):
    """Rigidly place the exact source curve without refitting or resampling."""
    if (not isinstance(matrix, (list, tuple)) or len(matrix) != 4
            or any(not isinstance(row, (list, tuple)) or len(row) != 4 for row in matrix)):
        raise ValueError('A rigid 4x4 placement matrix is required')
    matrix = [[_number(value, 'placement') for value in row] for row in matrix]
    if any(abs(matrix[3][i]-(1 if i == 3 else 0)) > 1e-9 for i in range(4)):
        raise ValueError('Invalid homogeneous placement')
    columns = [[matrix[i][j] for i in range(3)] for j in range(3)]
    if (any(abs(_dot(a, b)-(1 if i == j else 0)) > 1e-8
            for i, a in enumerate(columns) for j, b in enumerate(columns))
            or _dot(_cross(columns[0], columns[1]), columns[2]) < 1-1e-8):
        raise ValueError('Carrier placement must preserve lengths and handedness')
    def vector(v): return [sum(matrix[i][j]*v[j] for j in range(3)) for i in range(3)]
    def point(v): return [x+matrix[i][3] for i, x in enumerate(vector(v))]
    result = copy.deepcopy(path)
    for key in ('controls_mm', 'sample_points_mm'):
        result[key] = [point(v) for v in path[key]]
    for segment in result['segments']:
        for key in ('start_mm', 'end_mm', 'through_mm', 'center_mm'):
            if key in segment: segment[key] = point(segment[key])
        if 'axis' in segment: segment['axis'] = vector(segment['axis'])
    return result


def carrier_records(profile, world_path):
    """Describe one conservative swept envelope and contained nominal collars."""
    g = profile['geometry'];ring = g['ring_geometry']
    target = g['nominal_link_count']*g['nominal_pitch_mm']
    if abs(world_path['length_mm']-target) > profile['guide_fit']['length_tolerance_mm']:
        raise ValueError('Carrier path length differs from nominal collar interval count')
    minimum = world_path['min_bend_radius_mm']
    if minimum is not None and minimum < g['minimum_centerline_bend_radius_mm']:
        raise ValueError('Carrier path violates the published radius proxy')
    deviation = ring['width_mm']**2/(8*(g['minimum_centerline_bend_radius_mm']-ring['outer_radius_mm']))
    links = []
    for index in range(g['nominal_link_count']):
        distance = (index+.5)*g['nominal_pitch_mm'];station = path_position(world_path, distance)
        links.append({'id': 'CarrierLink'+str(index).zfill(3), 'component': 'CarrierSnapshot',
                      'center_mm': station['point_mm'], 'axis': station['tangent'],
                      'origin_mm': _sub(station['point_mm'], _mul(station['tangent'], ring['width_mm']/2)),
                      'width_mm': ring['width_mm'], 'outer_radius_mm': ring['outer_radius_mm'],
                      'inner_radius_mm': ring['inner_radius_mm'], 'arc_length_mm': distance,
                      'role': 'nominal_arc_length_collar'})
    return {'path': world_path, 'outer_radius_mm': g['outer_radius_mm'], 'inner_radius_mm': g['inner_radius_mm'],
            'pitch_mm': g['nominal_pitch_mm'], 'nominal_link_count': g['nominal_link_count'], 'links': links,
            'native_aliases': [link['id'] for link in links],
            'component': 'CarrierSnapshot',
            'collar_containment': {'local_curve_deviation_bound_mm': deviation,
                'outer_margin_lower_bound_mm': g['outer_radius_mm']-ring['outer_radius_mm']-deviation,
                'inner_margin_lower_bound_mm': ring['inner_radius_mm']-g['inner_radius_mm']-deviation,
                'scope': 'Local curvature-bound containment; does not prove global self-clearance'},
            'scope': g['pitch_scope'], 'qualification': copy.deepcopy(profile['qualification'])}


def freecad_envelope(Part, App, record):
    return pneumatic_hose.freecad_shape(Part, App, record['path'], record['inner_radius_mm'], record['outer_radius_mm'])


def solidcraft_envelope_commands(record, name='CarrierEnvelope'):
    return pneumatic_hose.solidcraft_commands(record['path'], record['inner_radius_mm'], record['outer_radius_mm'], name)


def freecad_guard(Part, App, record):
    """Filled outer collision guard; never part of delivered material bodies."""
    path = record['path'];start = path_position(path, 0)
    profile = Part.Wire([Part.makeCircle(record['outer_radius_mm'],
        App.Vector(*start['point_mm']), App.Vector(*start['tangent']))])
    result = pneumatic_hose.freecad_wire(Part, App, path).makePipeShell([profile], True, False).removeSplitter()
    if not result.isValid() or len(result.Solids) != 1 or result.Volume <= 0:
        raise ValueError('Carrier collision guard must be one valid filled solid')
    return result.Solids[0]


def freecad_links(Part, App, record):
    """Independent native annular collars grouped as one semantic compound."""
    solids = []
    for link in record['links']:
        origin, axis = App.Vector(*link['origin_mm']), App.Vector(*link['axis'])
        outer = Part.makeCylinder(link['outer_radius_mm'], link['width_mm'], origin, axis)
        inner = Part.makeCylinder(link['inner_radius_mm'], link['width_mm'], origin, axis)
        ring = outer.cut(inner).removeSplitter()
        if not ring.isValid() or len(ring.Solids) != 1 or ring.Volume <= 0:
            raise ValueError('Carrier collar did not form one valid solid')
        solids.append(ring.Solids[0])
    compound = Part.makeCompound(solids)
    if not compound.isValid() or len(compound.Solids) != record['nominal_link_count']:
        raise ValueError('Carrier collar compound has the wrong nominal count')
    return compound


def solidcraft_links_commands(record, name='CarrierLinks'):
    """Return native commands; record.native_aliases supplies semantic grouping."""
    commands = []
    for link in record['links']:
        axis = link['axis'];seed = [1., 0, 0] if abs(axis[0]) < .8 else [0., 1., 0]
        x = _unit(_sub(seed, _mul(axis, _dot(seed, axis))));y = _cross(axis, x)
        identifier = link['id']
        commands.extend([
            {'command': 'sketch.create', 'params': {'name': name+'_'+identifier+'_Profile',
                'plane': {'origin': link['origin_mm'], 'x_dir': x, 'y_dir': y}}},
            {'command': 'sketch.circle.center', 'params': {'center': [0, 0], 'radius': link['outer_radius_mm']}},
            {'command': 'sketch.circle.center', 'params': {'center': [0, 0], 'radius': link['inner_radius_mm']}},
            {'command': 'sketch.finish', 'params': {}},
            {'command': 'solid.extrude', 'params': {'distance': link['width_mm'],
                'profiles': [{'curves': ['c1']}], 'operation': 'new', 'name': identifier, 'body_name': identifier}},
            {'command': 'appearance.assign', 'params': {'bodies': [identifier], 'color': '#252a30', 'opacity': 1}}])
    return commands
