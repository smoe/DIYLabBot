"""Conservative source-only envelopes for finite SP02 hose design trials.

Cuts never reduce an envelope. Positive margins prove separation from the
enclosing primitives; an envelope hit is inconclusive, not a native collision.
No CAD output is an input to this check.
"""
import itertools
import math

import pneumatic_hose as hose
import robot_spec as robot
import spatial_hose_carrier as carrier


def _box(points):
    return {'min': [min(p[i] for p in points) for i in range(3)],
            'max': [max(p[i] for p in points) for i in range(3)]}


def _corners(box):
    return list(itertools.product(*zip(box['min'], box['max'])))


def primitive_bounds(shape, parameters):
    """Enclose the supported shared primitive, including vendor source bounds."""
    val = lambda value: robot.evaluate(value, parameters)
    vec = lambda values: [val(v) for v in values]
    origin = vec(shape['origin']);kind = shape['kind']
    if kind == 'box':
        size = vec(shape['size'])
        return _box([origin, [a+b for a, b in zip(origin, size)]])
    if kind in ('cylinder', 'cone'):
        axis = hose._unit(vec(shape.get('axis', [0, 0, 1])))
        length = val(shape.get('height', shape.get('length')))
        radii = [val(shape['radius']), val(shape.get('top_radius', shape['radius']))]
        ends = [origin, hose._add(origin, hose._mul(axis, length))]
        extents = [[radius*math.sqrt(max(0, 1-a*a)) for a in axis] for radius in radii]
        return {'min': [min(p[i]-r[i] for p, r in zip(ends, extents)) for i in range(3)],
                'max': [max(p[i]+r[i] for p, r in zip(ends, extents)) for i in range(3)]}
    if kind == 'vendor_step':
        transform = robot.frame({'frame': {'origin': origin, 'axis': vec(shape['axis']),
                                          'x': vec(shape['x'])}}, {})
        return _box([robot.transform(transform, p) for p in _corners(shape['bbox_mm'])])
    if kind == 'polygon_prism':
        u, v = vec(shape['u_axis']), vec(shape['v_axis']);normal = hose._unit(hose._cross(u, v))
        depth = val(shape['depth'])
        return _box([[origin[i]+val(a)*u[i]+val(b)*v[i]+d*normal[i] for i in range(3)]
                     for loop in shape['loops'] for a, b in loop for d in (0, depth)])
    raise ValueError('No conservative source envelope for primitive '+str(kind))


def source_envelopes(arm, own, arm_parameters, own_parameters):
    """Enclose each body by its uncut positive primitives, never by a cut void.

    Circular plates keep their circular enclosure: an AABB corner is empty
    space, not evidence that a close hose touches the plate. Unsupported
    primitives retain their conservative boxes. Native checks remain separate.
    """
    result = []
    def collect(operations, parameters, component, arm_body):
        bodies = {};primitives = {}
        for operation in operations:
            action = operation['action']
            if action in ('cut', 'subtract'):
                continue
            if action == 'translate':
                delta = [robot.evaluate(v, parameters) for v in operation['vector']]
                for target in operation['targets']:
                    old = bodies[target]
                    bodies[target] = {key: [v+d for v, d in zip(values, delta)] for key, values in old.items()}
                    for primitive in primitives[target]:
                        primitive['origin'] = [v+d for v, d in zip(primitive['origin'], delta)]
                continue
            if action not in ('create', 'union', 'join'):
                raise ValueError('No conservative source envelope for action '+str(action))
            if operation.get('role') == 'viewing_cone':
                continue
            shape = operation.get('primitive', operation.get('shape'))
            bounds = primitive_bounds(shape, parameters)
            value = lambda v: robot.evaluate(v, parameters)
            if shape['kind'] in {'cylinder', 'cone'}:
                enclosure = {'kind': 'cylinder', 'origin': [value(v) for v in shape['origin']],
                    'axis': hose._unit([value(v) for v in shape.get('axis', [0, 0, 1])]),
                    'height': value(shape.get('height', shape.get('length'))),
                    'radius': max(value(shape['radius']), value(shape.get('top_radius', shape['radius'])))}
            else:
                enclosure = {'kind': 'box', 'origin': list(bounds['min']),
                             'size': [hi-lo for lo, hi in zip(bounds['min'], bounds['max'])]}
            targets = [operation['body']] if action == 'create' else operation.get('targets', [operation.get('body')])
            for target in targets:
                if target is None:
                    raise ValueError('A source envelope operation needs a target')
                old = bodies.get(target)
                bodies[target] = bounds if old is None else _box(_corners(old)+_corners(bounds))
                if action == 'create':primitives[target] = []
                import copy
                primitives.setdefault(target, []).append(copy.deepcopy(enclosure))
        for name, bounds in bodies.items():
            padding = 1e-6
            padded = {'min': [v-padding for v in bounds['min']], 'max': [v+padding for v in bounds['max']]}
            result.append({'body': name, 'component': component, 'bbox': padded,
                           'enclosing_primitives': primitives[name],
                           'numeric_envelope_padding_mm': padding, 'arm_body': arm_body})
    expanded = robot.expanded(arm)
    for link in expanded['links']:
        collect(link['recipe'], arm_parameters, link['id'], True)
    for component in own['components']:
        names = {body['id'] for body in own['bodies'] if body['component'] == component['id']}
        collect([op for op in own['operations'] if op['body'] in names], own_parameters, component['id'], False)
    return result


def _point_box_distance(point, box):
    return math.sqrt(sum(max(0, box['min'][i]-point[i], point[i]-box['max'][i])**2 for i in range(3)))


def _point_envelope_distance(point, body):
    """Distance to a union of solid enclosing primitives is a safe lower bound."""
    if 'enclosing_primitives' not in body:
        return _point_box_distance(point, body['bbox'])
    distances = []
    for primitive in body['enclosing_primitives']:
        if primitive['kind'] == 'box':
            origin = primitive['origin']
            box = {'min': origin, 'max': [a+b for a, b in zip(origin, primitive['size'])]}
            distances.append(_point_box_distance(point, box))
        elif primitive['kind'] == 'cylinder':
            delta = hose._sub(point, primitive['origin']);axial = hose._dot(delta, primitive['axis'])
            radial = math.sqrt(max(0., hose._dot(delta, delta)-axial*axial))
            distances.append(math.hypot(max(0., radial-primitive['radius']),
                                       max(0., -axial, axial-primitive['height'])))
        else:
            raise ValueError('Unsupported source enclosing primitive')
    if not distances:raise ValueError('A source body needs a nonempty conservative enclosure')
    return min(distances)-math.sqrt(3)*body.get('numeric_envelope_padding_mm', 0.)


def check_route(path, envelopes, matrices, tube_radius, guard_radius, *, sample_step_mm=2.0,
                socket_mating_bodies=None, minimum_sample_step_mm=.05):
    """Bound all centerline intervals by distance's 1-Lipschitz property.

    Every body is enclosed by its local box, avoiding lossy world-box rotation.
    Native mating checks handle only each explicitly named socket's intended
    port/clamp pair. Other tooling is checked even beside an inserted section.
    The complete hose, including socket straights, is checked against the arm.
    """
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (tube_radius, guard_radius, sample_step_mm, minimum_sample_step_mm))
            or not 0 < tube_radius <= guard_radius or not 0 < minimum_sample_step_mm <= sample_step_mm):
        raise ValueError('Positive finite hose/guard radii and sampling step are required')
    inverse = {key: robot.inverse(value) for key, value in matrices.items()}
    parts = path['length_accounting']['parts']
    allowed_kinds = {'inserted', 'socket_strain_relief', 'connector_straight_lead',
                     'clip_straight', 'bare_span', 'nominal_carrier'}
    if (type(path['length_mm']) not in (int, float) or not math.isfinite(path['length_mm'])
            or path['length_mm'] <= 0 or not isinstance(parts, list) or not parts):
        raise ValueError('A complete positive material partition is required')
    if any(part.get('kind') not in allowed_kinds or type(part.get('length_mm')) not in (int, float)
           or not math.isfinite(part['length_mm']) or part['length_mm'] <= 0 for part in parts):
        raise ValueError('Unknown material kind or invalid region length')
    if abs(sum(part['length_mm'] for part in parts)-path['length_mm']) > 1e-7:
        raise ValueError('Material regions must cover the complete hose exactly once')
    mating = {} if socket_mating_bodies is None else socket_mating_bodies
    if (not isinstance(mating, dict) or set(mating)-{'pump', 'tip'}
            or any(not isinstance(names, (list, tuple)) or not names
                   or any(not isinstance(name, str) or not name for name in names)
                   or len(set(names)) != len(names) for names in mating.values())):
        raise ValueError('Socket exclusions require explicit pump/tip body-name lists')
    intervals = [];offset = 0.0
    for part in parts:
        intervals.append((offset, offset+part['length_mm'], part));offset += part['length_mm']
    count = max(1, math.ceil(path['length_mm']/sample_step_mm))
    minimum = math.inf;witness = None;refined = 0;evaluations = 0
    finest = path['length_mm']/count
    position_cache = {}
    for body in envelopes:
        inv = inverse[body['component']]
        for index in range(count):
            stack = [(path['length_mm']*index/count, path['length_mm']*(index+1)/count)]
            while stack:
                start, end = stack.pop();width = end-start
                regions = [part for a, b, part in intervals if a <= end and b >= start]
                kinds = {part['kind'] for part in regions}
                intended = bool(regions) and all(body['body'] in mating.get(part.get('id', '').split('_')[0], ())
                    and part['kind'] in {'inserted', 'socket_strain_relief', 'connector_straight_lead'}
                    for part in regions)
                if not body['arm_body'] and intended:
                    continue  # Mandatory exact socket mating is checked independently.
                radius = guard_radius if 'nominal_carrier' in kinds else tube_radius
                distance = (start+end)/2
                if distance not in position_cache:
                    position_cache[distance] = carrier.path_position(path, distance)['point_mm']
                point = position_cache[distance]
                gap = _point_envelope_distance(robot.transform(inv, point), body)-radius
                margin = gap-width/2;evaluations += 1;finest = min(finest, width)
                if margin <= 0 and gap > 0 and width > minimum_sample_step_mm:
                    stack.extend([(start, distance), (distance, end)]);refined += 1
                    continue
                if margin < minimum:
                    minimum = margin;witness = {'body': body['body'], 'component': body['component'],
                        'arc_length_mm': distance, 'interval_mm': [start, end],
                        'centerline_point_mm': point, 'margin_lower_bound_mm': margin}
                if margin <= 0:
                    return {'passed': False, 'classification': 'envelope_proximity', 'witness': witness,
                            'maximum_sample_step_mm': sample_step_mm,
                            'minimum_sample_step_mm': minimum_sample_step_mm,
                            'finest_interval_mm': finest, 'refined_interval_count': refined,
                            'scope': 'Conservative source-envelope test; a hit is not a proven native collision'}
    return {'passed': True, 'minimum_margin_lower_bound_mm': minimum if math.isfinite(minimum) else None,
            'witness': witness, 'maximum_sample_step_mm': sample_step_mm,
            'minimum_sample_step_mm': minimum_sample_step_mm, 'finest_interval_mm': finest,
            'refined_interval_count': refined, 'interval_evaluations': evaluations,
            'scope': 'Source-only uncut positive primitive enclosures and adaptive interval distance bounds; not motion or hardware qualification'}
