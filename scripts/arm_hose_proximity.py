"""Finite, conservative closeness bounds for link-local hose runs.

A source material witness gives an UPPER distance bound to the real host,
whereas distance to its enclosing box would give only a lower bound. Unsupported
vendor solids contribute no invented witnesses. Native checks use their actual
shapes independently. No motion or mechanical qualification is implied.
"""
import math

import arm_syringe_clearance as clearance
import pneumatic_hose as hose
import robot_spec as robot
import spatial_hose_carrier as carrier


def _inside(shape, p, point):
    val = lambda value: robot.evaluate(value, p)
    origin = [val(v) for v in shape['origin']]
    delta = hose._sub(point, origin)
    if shape['kind'] == 'box':
        return all(-1e-9 <= d <= val(size)+1e-9 for d, size in zip(delta, shape['size']))
    if shape['kind'] in {'cylinder', 'cone'}:
        axis = hose._unit([val(v) for v in shape.get('axis', [0, 0, 1])])
        height = val(shape.get('height', shape.get('length')))
        z = hose._dot(delta, axis)
        radius = val(shape['radius'])
        if shape['kind'] == 'cone':
            radius += (val(shape['top_radius'])-radius)*z/height
        radial = hose._sub(delta, hose._mul(axis, z))
        return -1e-9 <= z <= height+1e-9 and hose._dot(radial, radial) <= radius*radius+1e-9
    raise ValueError('No source material membership for '+shape['kind'])


def _body_terms(operations, parameters):
    """Keep the portable CSG recipe, including later translations."""
    result = {}
    for operation in operations:
        action = operation['action']
        if action == 'translate':
            delta = [robot.evaluate(v, parameters) for v in operation['vector']]
            for target in operation['targets']:
                for _, shape in result[target]:
                    shape['origin'] = [robot.evaluate(v, parameters)+d for v, d in zip(shape['origin'], delta)]
            continue
        targets = [operation['body']] if action == 'create' else operation.get('targets', [operation.get('body')])
        shape = operation.get('primitive', operation.get('shape'))
        if shape is None:raise ValueError('A material witness needs portable CSG geometry')
        import copy
        for target in targets:
            if action == 'create':result[target] = []
            result[target].append((action, copy.deepcopy(shape)))
    return result


def _membership(terms, parameters, point):
    solid = False
    for action, shape in terms:
        inside = _inside(shape, parameters, point)
        if action == 'create':solid = inside
        elif action in {'join', 'union'}:solid |= inside
        elif action in {'cut', 'subtract'}:solid &= not inside
        else:raise ValueError('Unsupported material witness action '+action)
    return solid


def _candidates(shape, parameters, step):
    val = lambda v: robot.evaluate(v, parameters)
    origin = [val(v) for v in shape['origin']]
    if shape['kind'] == 'box':
        import itertools
        axes = []
        for size in shape['size']:
            length = val(size);n = max(1, math.ceil(length/step))
            axes.append([length*(i+.5)/n for i in range(n)])
        return [[a+b for a, b in zip(origin, point)] for point in itertools.product(*axes)]
    if shape['kind'] in {'cylinder', 'cone'}:
        axis = hose._unit([val(v) for v in shape.get('axis', [0, 0, 1])])
        ref = [1, 0, 0] if abs(axis[0]) < .8 else [0, 1, 0]
        x = hose._unit(hose._cross(axis, ref));y = hose._cross(axis, x)
        height = val(shape.get('height', shape.get('length')))
        nz = max(1, math.ceil(height/step));points = []
        for iz in range(nz):
            z = height*(iz+.5)/nz;r = val(shape['radius'])
            if shape['kind'] == 'cone':r += (val(shape['top_radius'])-r)*z/height
            n = max(8, math.ceil(2*math.pi*r/step))
            for fraction in (.25, .5, .75, max(.8, 1-.1/r)):
                for i in range(n):
                    t = i*2*math.pi/n
                    points.append([origin[k]+z*axis[k]+r*fraction*(math.cos(t)*x[k]+math.sin(t)*y[k]) for k in range(3)])
        return points
    return []


def material_witnesses(arm, own, arm_parameters, parameters, host_names, step_mm=5):
    """Witnesses lie in source CSG material; cuts never become solid witnesses."""
    recipes = {}
    for link in robot.expanded(arm)['links']:
        for body, terms in _body_terms(link['recipe'], arm_parameters).items():
            recipes[body] = (link['id'], terms, arm_parameters)
    for component in own['components']:
        names = {row['id'] for row in own['bodies'] if row['component'] == component['id']}
        operations = [row for row in own['operations'] if row['body'] in names]
        for body, terms in _body_terms(operations, parameters).items():
            recipes[body] = (component['id'], terms, parameters)
    result = {}
    for name in host_names:
        if name not in recipes:raise ValueError('Unknown structural closeness host '+name)
        component, terms, values = recipes[name]
        if any(shape['kind'] not in {'box', 'cylinder', 'cone'} for _, shape in terms):
            result[name] = {'component': component, 'points_mm': [], 'status': 'native_shape_required'}
            continue
        points = []
        for action, shape in terms:
            if action in {'create', 'join', 'union'}:
                points.extend(point for point in _candidates(shape, values, step_mm)
                              if _membership(terms, values, point))
        if not points:raise ValueError('No actual source material witnesses for host '+name)
        result[name] = {'component': component, 'points_mm': points, 'status': 'source_material_witnesses'}
    return result


def bounds(path, spec, p, frames, mounted, context, sample_step_mm=2):
    """Bound every interval, retaining the actual material witness at the maximum."""
    if not 0 < sample_step_mm <= 2:raise ValueError('Closeness sampling must be at most2 mm')
    config = spec['hose_routing'];matrix = {**frames, **mounted}
    names = {name for section in config['sections'] for name in section.get('host_bodies', [])}
    if not names <= set(context.get('material_witnesses', {})):
        context['material_witnesses'] = material_witnesses(context['arm'], context['own'],
            context['parameters'], p, names | set(context.get('material_witnesses', {})))
    witnesses = context['material_witnesses']
    records = {r['id']: r for r in path['section_records']};out = {};passed = True
    offsets = [0.]
    for segment in path['segments']:offsets.append(offsets[-1]+segment['length_mm'])
    joints = {j['id']: j for j in context['arm']['joints']}
    for section in config['sections']:
        record = records[section['id']]
        start_index = record['segment_start_index'];count = record['segment_count']
        start, end = offsets[start_index], offsets[start_index+count]
        intervals = max(1, math.ceil((end-start)/sample_step_mm));width = (end-start)/intervals
        if section['kind'] == 'fixed_link':
            points = [(name, robot.transform(matrix[row['component']], point), point)
                for name in section['host_bodies'] for row in [witnesses[name]] for point in row['points_mm']]
            if not points:raise ValueError('Rigid hose run has no structural material witnesses')
            maximum = -1.;worst = None
            for index in range(intervals):
                station = start+(index+.5)*width;point = carrier.path_position(path, station)['point_mm']
                nearest = min(points, key=lambda row: math.dist(row[1], point));distance = math.dist(nearest[1], point)
                upper = distance+width/2
                if upper > maximum:
                    maximum = upper;worst = {'host_body': nearest[0], 'host_material_point_mm': nearest[1],
                        'host_material_point_local_mm': nearest[2], 'centerline_point_mm': point,
                        'arc_length_mm': station, 'sample_distance_mm': distance}
            ok = maximum <= section['max_offset_mm']+1e-9
            out[section['id']] = {'passed': ok, 'maximum_host_distance_upper_bound_mm': maximum,
                'required_maximum_mm': section['max_offset_mm'], 'witness': worst,
                'maximum_arc_interval_mm': width, 'interval_count': intervals,
                'scope': 'Upper bound from verified source CSG material witnesses and distance Lipschitz continuity; native shape check separate'}
        else:
            joint = joints[section['joint']];parent = frames[joint['parent']]
            origin = robot.transform(parent, [robot.evaluate(v, context['parameters']) for v in joint['frame']['origin']])
            axis = hose._unit([sum(parent[i][j]*robot.evaluate(joint['frame']['axis'][j], context['parameters']) for j in range(3)) for i in range(3)])
            radial_max = 0.;axial_min = math.inf;axial_max = -math.inf
            for index in range(intervals):
                point = carrier.path_position(path, start+(index+.5)*width)['point_mm'];delta = hose._sub(point, origin)
                axial = hose._dot(delta, axis);radial = math.sqrt(max(0, hose._dot(delta, delta)-axial*axial))
                radial_max = max(radial_max, radial+width/2)
                axial_min = min(axial_min, axial-width/2);axial_max = max(axial_max, axial+width/2)
            lo, hi = section['axial_range_mm']
            ok = radial_max <= section['max_reach_mm']+1e-9 and axial_min >= lo-1e-9 and axial_max <= hi+1e-9
            out[section['id']] = {'passed': ok, 'maximum_radial_reach_upper_bound_mm': radial_max,
                'required_maximum_radial_reach_mm': section['max_reach_mm'],
                'axial_range_outer_bound_mm': [axial_min, axial_max], 'required_axial_range_mm': [lo, hi],
                'maximum_arc_interval_mm': width, 'interval_count': intervals,
                'scope': 'Joint-axis pocket bounded over every centerline interval; no continuous pose coverage'}
        passed &= ok
    return {'passed': passed, 'sections': out, 'qualification': {'continuous_motion_verified': False}}
