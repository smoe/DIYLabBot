"""Fit referenced laboratory furniture to actual room boundaries, without scaling.

The layout is an unmeasured presentation. Positive footprint and access checks
do not qualify laboratory clearances, plumbing or extraction performance.
"""
import copy
import functools
import json
import math
from pathlib import Path

import assembly_model as assembly
import building_furnishings as placed
import furniture_model as furniture
import lab_equipment as equipment
import lab_room_model as room
import relative_floorplan as floor
import robot_spec as robot

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(ref):
    source = json.loads(assembly.validate_reference(ref, root=ROOT).read_text())
    return validate(source)


def validate(source):
    require(set(source) == {'format', 'id', 'units', 'reference_room', 'hood_source', 'hood_profile',
                           'prototype_instances', 'lift_area', 'wet_corner', 'island', 'parameters', 'basis', 'limitations'},
            'Only the referenced basic laboratory profile fields are supported')
    require(source['format'] == 'solidcraftbot.basic-laboratory-furnishings/1', 'Basic laboratory profile required')
    require(source['units'] == {'length': 'mm', 'angle': 'deg'}, 'Explicit furnishing units required')
    require(source['wet_corner'] == 'nearest_usable_lift_corner' and source['island'] == 'back_to_back',
            'Confirmed wet-corner and central-pair rules required')
    for key in ('reference_room', 'hood_source'):
        assembly.validate_reference(source[key], root=ROOT)
    require(source['hood_profile'] == 'fume_hood_1200', 'Supported hood profile required')
    require(set(source['prototype_instances']) == {'side', 'window', 'wet', 'island'}, 'Four furniture prototype references required')
    require(set(source['parameters']) == {'wall_gap', 'minimum_aisle', 'door_clearance', 'fixture_gap', 'minimum_run',
            'fit_increment', 'maximum_corner_setback', 'island_search_step', 'island_length_step', 'compact_aisle'},
            'Explicit basic laboratory layout parameters required')
    for name, value in source['parameters'].items():
        require(set(value) == {'value', 'unit', 'range', 'basis'} and value['unit'] == 'mm'
                and value['basis'] == 'presentation_assumption'
                and type(value['value']) in (int, float) and math.isfinite(value['value'])
                and isinstance(value['range'], list) and len(value['range']) == 2
                and all(type(v) in (int, float) and math.isfinite(v) for v in value['range'])
                and 0 <= value['range'][0] <= value['value'] <= value['range'][1], 'Invalid layout parameter: '+name)
        require(value['value'] > 0 or name in {'wall_gap', 'door_clearance', 'maximum_corner_setback'},
                'Positive layout dimension required: '+name)
    require(600 <= source['parameters']['compact_aisle']['value'] <= source['parameters']['minimum_aisle']['value'],
            'Ordered declared presentation aisles required')
    return source


def dependencies(ref):
    source = load(ref)
    reference = room.load(assembly.validate_reference(source['reference_room'], root=ROOT))
    return [ROOT/ref['source'], ROOT/'model/basic-laboratory-furnishings.schema.json', Path(__file__),
            ROOT/source['reference_room']['source'], ROOT/source['hood_source']['source'],
            ROOT/'scripts/lab_equipment.py', ROOT/'scripts/furniture_model.py', *room.source_dependencies(reference)]


def add(a, b, amount=1):
    return [a[i]+amount*b[i] for i in (0, 1)]


def dot(a, b):
    return sum(a[i]*b[i] for i in (0, 1))


def edge_pairs(poly):
    return zip(poly, poly[1:]+poly[:1])


def point_segment(point, a, b):
    v = add(b, a, -1)
    t = max(0., min(1., dot(add(point, a, -1), v)/dot(v, v)))
    return math.dist(point, add(a, v, t))


def crosses(a, b, c, d):
    return floor.cross(a, b, c)*floor.cross(a, b, d) < -1e-6 and floor.cross(c, d, a)*floor.cross(c, d, b) < -1e-6


def separation(a, b):
    if any(floor.point_membership(p, b) >= 0 for p in a) or any(floor.point_membership(p, a) >= 0 for p in b):
        return 0.
    if any(crosses(u, v, x, y) for u, v in edge_pairs(a) for x, y in edge_pairs(b)):
        return 0.
    return min([point_segment(p, x, y) for p in a for x, y in edge_pairs(b)] +
               [point_segment(p, x, y) for p in b for x, y in edge_pairs(a)])


def fits(poly, outline, margin):
    if any(floor.point_membership(p, outline) != 1 for p in poly):
        return False
    if any(crosses(u, v, x, y) for u, v in edge_pairs(poly) for x, y in edge_pairs(outline)):
        return False
    distance = min([point_segment(p, x, y) for p in poly for x, y in edge_pairs(outline)] +
                   [point_segment(p, x, y) for p in outline for x, y in edge_pairs(poly)])
    return distance >= margin-1e-5


def rectangle(origin, x, y, width, length):
    return [origin, add(origin, x, width), add(add(origin, x, width), y, length), add(origin, y, length)]


def boundaries(plan, area, scale):
    """Retain source edges, including doorway cuts on segmented/concave plans."""
    walls = {w['id']: w for w in plan['walls']}
    outline = [[v*scale for v in p] for p in floor.outline(plan, area)]
    if floor.signed_area(outline) < 0:
        outline.reverse()
    result = []
    for a, b in edge_pairs(outline):
        length = math.dist(a, b); tangent = [(b[i]-a[i])/length for i in (0, 1)]
        refs = [w for w in walls.values() if
                all(point_segment([v*scale for v in plan['vertices'][w[key]]], a, b) < 1e-5 for key in ('start', 'end'))]
        require(refs, 'Room edge must retain its source wall')
        wall_ids = {w['id'] for w in refs}
        adjacent = [other for other in plan['areas'] if other['id'] != area and
                    any(e['wall'] in wall_ids for e in other['boundary'])]
        doors = []
        for opening in plan['openings']:
            if opening['kind'] != 'door' or opening['wall'] not in wall_ids:
                continue
            wall = walls[opening['wall']]
            u, v = [[n*scale for n in plan['vertices'][wall[key]]] for key in ('start', 'end')]
            ends = [add(u, add(v, u, -1), t) for t in opening['interval']]
            doors.append({'id': opening['id'], 'points': ends,
                          'interval': sorted(dot(add(p, a, -1), tangent) for p in ends)})
        result.append({'a': a, 'b': b, 't': tangent, 'n': [-tangent[1], tangent[0]], 'length': length,
                       'walls': sorted(wall_ids), 'facade': not adjacent, 'doors': doors,
                       'entrance': any(other['kind'] == 'corridor' for other in adjacent)})
    return outline, result


def door_keepouts(edges, clearance):
    return [{'id': door['id'], 'polygon': rectangle(add(edge['a'], edge['t'], door['interval'][0]-clearance),
                 edge['t'], edge['n'], math.dist(*door['points'])+2*clearance,
                 math.dist(*door['points'])+clearance)}
            for edge in edges for door in edge['doors']]


def layout(source, item, plan, parameters, reference):
    # Memoize this pure fitting calculation by all input bytes. No native proof
    # or source pin is rewritten or accepted from a different source revision.
    key = json.dumps([source, item, plan, parameters, reference], sort_keys=True)
    return copy.deepcopy(_cached_layout(key))


@functools.lru_cache(maxsize=32)
def _cached_layout(key):
    return _layout(*json.loads(key))


def _layout(source, item, plan, parameters, reference):
    """Geometric layout only: stable source references and derived instance poses."""
    standard = _fit_layout(source, item, plan, parameters, reference, compact=False)
    if any(f['kind'] == 'island' for f in standard['fixtures']):
        return standard
    for compact, reverse_priority in ((False, True), (True, False), (True, True)):
        candidate = _fit_layout(source, item, plan, parameters, reference, compact, reverse_priority)
        if any(f['kind'] == 'island' for f in candidate['fixtures']) and any(f['kind'] == 'wet' for f in candidate['fixtures']):
            if compact:
                candidate['notes'].append('Compact bench depths within the reference parameter ranges and the declared compact aisle were used to retain the central pair.')
            return candidate
    return standard


def _fit_layout(source, item, plan, parameters, reference, compact, reverse_priority=False):
    p = room.parameters(reference)
    settings = {k: v['value'] for k, v in source['parameters'].items()}
    if compact:
        for name in ('bench_depth', 'window_bench_depth', 'island_half_width'):
            p[name] = reference['parameters'][name]['range'][0]
        settings['minimum_aisle'] = settings['compact_aisle']
    outline, edges = boundaries(plan, item['area'], parameters['display_scale'])
    lift = [[v*parameters['display_scale'] for v in p] for p in floor.outline(plan, source['lift_area'])]
    wall_face = parameters['display_thickness']/2
    margin = wall_face+settings['wall_gap']
    keepouts = door_keepouts(edges, settings['door_clearance'])
    corners = []
    for index, point in enumerate(outline):
        before, after = edges[index-1], edges[index]
        turn = math.degrees(math.atan2(before['t'][0]*after['t'][1]-before['t'][1]*after['t'][0], dot(before['t'], after['t'])))
        if turn >= 30:
            corners.append({'point_mm': point, 'index': index,
                            'usable_wall_length_mm': max(before['length'], after['length']),
                            'distance_to_lift_mm': min(point_segment(point, a, b) for a, b in edge_pairs(lift))})
    require(corners, 'Room needs a usable corner')
    usable = [c for c in corners if c['usable_wall_length_mm'] >= reference['parameters']['wet_length']['range'][0]+margin]
    require(usable, 'Room needs a corner with a wall long enough for the referenced sink bench')
    corner = min(usable, key=lambda c: (c['distance_to_lift_mm'], c['point_mm']))
    catalog = equipment.load(assembly.validate_reference(source['hood_source'], root=ROOT))
    hood_spec = equipment.materialize(catalog, source['hood_profile']); hp = equipment.parameters(hood_spec)
    fixtures, notes = [], []
    if corner != min(corners, key=lambda c: c['distance_to_lift_mm']):
        notes.append('The tiny entrance recess cannot hold the referenced sink bench; the nearest corner with a usable adjoining wall is used.')

    def access(poly_origin, n, t, width, length):
        span = min(600., length)
        return rectangle(add(add(poly_origin, n, width+1), t, (length-span)/2),
                         t, n, span, settings['minimum_aisle'])

    def accessible(zone, others):
        return fits(zone, outline, wall_face) and all(separation(zone, d['polygon_mm']) > 1e-5 for d in others)

    def clear(poly, gap=0):
        return fits(poly, outline, margin) and all(separation(poly, d['polygon']) > 1e-5 for d in keepouts) and all(
            separation(poly, f['polygon_mm']) >= max(gap, settings['minimum_aisle'] if f['kind'] == 'island' else 1e-4) and
            separation(poly, f['access_polygon_mm']) > 1e-5 for f in fixtures)

    # Try either wall adjoining the nearest corner, never a different corner.
    adjoining = [(corner['index'], False), (corner['index']-1, True)]
    for edge_index, reverse in reversed(adjoining) if reverse_priority else adjoining:
        edge = edges[edge_index]; n = edge['n']; t = [-v for v in edge['t']] if reverse else edge['t']
        for wet_length in (p['wet_length'], reference['parameters']['wet_length']['range'][0]):
            offsets = [margin+k*settings['fit_increment'] for k in
                       range(1+int(settings['maximum_corner_setback']/settings['fit_increment']))]
            for offset in offsets:
                wet_origin = add(add(corner['point_mm'], t, offset), n, margin)
                wet_poly = rectangle(wet_origin, n, t, p['wet_depth'], wet_length)
                other = edges[corner['index']] if reverse else edges[corner['index']-1]
                other_t = other['t'] if reverse else [-v for v in other['t']]
                arrangements = [(add(wet_origin, t, wet_length+settings['fixture_gap']), n, t, edge['walls'], 'straight'),
                    (add(add(corner['point_mm'], other_t, margin+p['wet_depth']+settings['fixture_gap']), other['n'], margin),
                     other['n'], other_t, other['walls'], 'corner')]
                # Follow a bent sidewall beyond the first edge rather than
                # extending a straight counter outside the registered room.
                following = edges[(edge_index-1 if reverse else edge_index+1) % len(edges)]
                ft = [-v for v in following['t']] if reverse else following['t']
                node = edge['a'] if reverse else edge['b']
                wet_end = add(wet_origin, t, wet_length)
                if dot(t, ft) > .9:
                    begin = dot(add(wet_end, node, -1), ft)+settings['fixture_gap']
                    for extra in (0, settings['fixture_gap'], 2*settings['fixture_gap']):
                        start = add(add(node, ft, max(0, begin)+extra), following['n'], margin)
                        arrangements.append((start, following['n'], ft, following['walls'], 'following_wall'))
                for hood_start, hn, ht, hw, arrangement in arrangements:
                    hood_poly = rectangle(hood_start, hn, ht, hp['depth'], hp['width'])
                    if not clear(wet_poly) or not clear(hood_poly) or separation(wet_poly, hood_poly) < settings['fixture_gap']-1e-5:
                        continue
                    wet_zone = access(wet_origin, n, t, p['wet_depth'], wet_length)
                    hood_zone = access(hood_start, hn, ht, hp['depth'], hp['width'])
                    if not accessible(wet_zone, [{'polygon_mm': hood_poly}]) or not accessible(hood_zone, [{'polygon_mm': wet_poly}]):
                        continue
                    fixtures.extend([
                        {'id': 'WetStation', 'kind': 'wet', 'polygon_mm': wet_poly, 'n': n, 't': t,
                         'origin_mm': wet_origin, 'length_mm': wet_length, 'width_mm': p['wet_depth'], 'walls': edge['walls'],
                         'access_polygon_mm': wet_zone, 'corner_setback_mm': offset},
                        {'id': 'Hood01', 'kind': 'hood', 'polygon_mm': hood_poly, 'n': hn, 't': ht,
                         'origin_mm': hood_start, 'length_mm': hp['width'], 'width_mm': hp['depth'], 'walls': hw,
                         'access_polygon_mm': hood_zone, 'wet_adjacency': arrangement,
                         'gap_to_wet_mm': separation(wet_poly, hood_poly)}])
                    break
                if fixtures: break
            if fixtures: break
        if fixtures: break
    if not fixtures:
        notes.append('The fixed sink/hood pair does not fit beside the nearest lift corner with the source door clearances; room geometry or fixture specification needs review.')

    def wall_runs(facade):
        # Reserve the central pair before filling the sidewalls. Otherwise a
        # greedy full-length wall run can consume its only usable aisle.
        step = settings['fit_increment']
        for edge in edges:
            if edge['entrance'] or edge['facade'] != facade: continue
            depth = p['window_bench_depth'] if facade else p['bench_depth']
            available, start = [], None
            count = math.floor(edge['length']/step)
            for k in range(count):
                a, b = k*step, (k+1)*step
                origin = add(add(edge['a'], edge['t'], a), edge['n'], margin)
                poly = rectangle(origin, edge['n'], edge['t'], depth, b-a)
                free = clear(poly, settings['fixture_gap'])
                if free and start is None: start = a
                if start is not None and (not free or k == count-1):
                    end = a if not free else b
                    if end-start >= settings['minimum_run']:
                        available.append((start, end))
                    start = None
            for run, (start, end) in enumerate(available, 1):
                origin = add(add(edge['a'], edge['t'], start), edge['n'], margin)
                poly = rectangle(origin, edge['n'], edge['t'], depth, end-start)
                if not clear(poly, settings['fixture_gap']): continue
                zone = access(origin, edge['n'], edge['t'], depth, end-start)
                if not accessible(zone, fixtures): continue
                fixtures.append({'id': ('Window' if facade else 'Side')+'_'+edge['walls'][0]+'_'+str(run),
                    'kind': 'window' if facade else 'side', 'polygon_mm': poly, 'n': edge['n'], 't': edge['t'],
                    'origin_mm': origin, 'length_mm': end-start, 'width_mm': depth, 'walls': edge['walls'], 'access_polygon_mm': zone})

    wall_runs(facade=True)
    if not compact:
        wall_runs(facade=False)

    # A central pair must leave the declared passage on every side. The
    # numerical search is a placement heuristic, not an optimal packing proof.
    axes = [edge['t'] for edge in sorted(edges, key=lambda edge: -edge['length']) if not edge['facade'] and not edge['entrance']]
    if not axes: axes = [[0., 1.]]
    centre = [sum(v[i] for v in outline)/len(outline) for i in (0, 1)]
    found = False
    for y in axes[:2]:
        x = [y[1], -y[0]]
        coordinates = [[dot(add(v, centre, -1), axis) for v in outline] for axis in (x, y)]
        if max(coordinates[0])-min(coordinates[0]) < 2*(p['island_half_width']+margin+settings['minimum_aisle']):
            continue
        ranges = [range(math.ceil(min(values)/settings['island_search_step']),
                        math.floor(max(values)/settings['island_search_step'])+1) for values in coordinates]
        candidates = [centre]+sorted([add(add(centre, x, i*settings['island_search_step']), y, j*settings['island_search_step'])
            for i in ranges[0] for j in ranges[1]], key=lambda v: math.dist(v, centre))
        lengths = [p['island_length']-k*settings['island_length_step'] for k in range(1+int(
            (p['island_length']-reference['parameters']['island_length']['range'][0])/settings['island_length_step']))]
        if lengths[-1] != reference['parameters']['island_length']['range'][0]:
            lengths.append(reference['parameters']['island_length']['range'][0])
        for length in lengths:
            for candidate in candidates:
                origin = add(add(candidate, x, -p['island_half_width']), y, -length/2)
                poly = rectangle(origin, x, y, 2*p['island_half_width'], length)
                if (fits(poly, outline, margin+settings['minimum_aisle']) and
                        all(separation(poly, f['polygon_mm']) >= settings['minimum_aisle'] for f in fixtures) and
                        all(separation(poly, d['polygon']) > 1e-5 for d in keepouts)):
                    for suffix, shift, front in (('Left', 0, 'negative_x'), ('Right', p['island_half_width'], 'positive_x')):
                        start = add(origin, x, shift)
                        fixtures.append({'id': 'Island'+suffix, 'kind': 'island', 'origin_mm': start, 'n': x, 't': y,
                            'width_mm': p['island_half_width'], 'length_mm': length, 'front': front,
                            'polygon_mm': rectangle(start, x, y, p['island_half_width'], length), 'walls': [],
                            'access_polygon_mm': access(start, x, y, p['island_half_width'], length) if front == 'positive_x'
                                else access(add(start, x, p['island_half_width']), [-v for v in x], y, p['island_half_width'], length)})
                    found = True
                    break
            if found: break
        if found: break
    if not found:
        notes.append('No central double bench fits the declared passages in this unmeasured footprint; the middle remains free.')
    if compact:
        wall_runs(facade=False)
    return {'outline': outline, 'fixtures': fixtures, 'corner': corner, 'corner_candidates': corners,
            'keepouts': keepouts, 'notes': notes, 'settings': settings, 'reference_parameters': p,
            'hood_spec': hood_spec, 'hood_parameters': hp, 'wall_margin_mm': margin, 'compact': compact}


def numeric_shape(shape, p):
    result = copy.deepcopy(shape)
    def numbers(value):
        return [numbers(v) for v in value] if isinstance(value, (list, tuple)) else robot.evaluate(value, p)
    for key in ('origin', 'size', 'points', 'axis'):
        if key in result: result[key] = numbers(result[key])
    for key in ('z', 'height', 'radius', 'top_radius', 'offset', 'depth'):
        if key in result: result[key] = numbers(result[key])
    if result['kind'] == 'polygon_prism' and 'z' in result:
        result.update(plane='XY', offset=result.pop('z'), depth=result.pop('height'))
    return result


def compile_instance(profile_ref, source, item, plan, parameters, z, reference=None):
    reference = reference or room.load(assembly.validate_reference(source['reference_room'], root=ROOT))
    design = layout(source, item, plan, parameters, reference)
    p = design['reference_parameters']
    prototypes = {i['id']: i for i in reference['_furnishings']['instances']}
    result = {'components': [], 'bodies': [], 'operations': [], 'joints': []}
    instances, frames, places = [], [], []
    for fixture in design['fixtures']:
        n, t = fixture['n'], fixture['t']
        if fixture['kind'] == 'hood':
            local = equipment.expanded(design['hood_spec'], design['hood_parameters'])
            values = design['hood_parameters']
            x, y = [-n[1], n[0]], [-n[0], -n[1]]
            pose_origin = add(add(fixture['origin_mm'], t, fixture['length_mm']/2), n, values['body_depth'])
            def point(a, b, c):
                return [pose_origin[i]+x[i]*a+y[i]*b for i in (0, 1)]+[z+c]
            def vector(v):
                return [x[i]*v[0]+y[i]*v[1] for i in (0, 1)]+[v[2]]
            prefix = item['id']+'_Hood01'
            component_prefix = prefix+'_'
            instance_type = 'fume_hood'
            top = values['worktop_z']
        else:
            prototype = copy.deepcopy(prototypes[source['prototype_instances'][fixture['kind']]])
            prototype['id'] = fixture['id']; prototype['component'] = fixture['id']
            rebound = {'width', 'depth', 'front_delta'} if fixture['kind'] == 'window' else {'width', 'length'}
            prototype['bindings'] = {key: robot.evaluate(value, p) for key, value in prototype['bindings'].items() if key not in rebound}
            origin = list(fixture['origin_mm'])
            if fixture['kind'] == 'window':
                x, y = t, n
                prototype['bindings'].update(width=fixture['length_mm'], depth=fixture['width_mm'], front_delta=0)
            else:
                x, y = n, t
                front = fixture.get('front', 'positive_x')
                if x[0]*y[1]-x[1]*y[0] < 0:
                    origin = add(origin, n, fixture['width_mm']); x = [-v for v in n]; front = 'negative_x'
                prototype['bindings'].update(width=fixture['width_mm'], length=fixture['length_mm'])
                prototype['front'] = front
            require(abs(x[0]*y[1]-x[1]*y[0]-1) < 1e-8, 'Furniture pose must be a rotation, not scaling or reflection')
            prototype['xyz'] = origin+[z]; prototype['yaw_deg'] = math.degrees(math.atan2(x[1], x[0]))
            prototype['frames'] = {key: fixture['id']+'.'+key for key in prototype.get('frames', {})}
            local = furniture.instantiate(reference['_catalog'], prototype, {})
            values = {}; prefix = item['id']; component_prefix = prefix+'_'
            point = lambda a, b, c: [a, b, c]
            vector = lambda v: list(v)
            instance_type = prototype['type']; top = prototype['bindings']['height']
        local_bodies = {b['id']: b for b in local['bodies']}
        operations = []
        for operation in local['operations']:
            shape = numeric_shape(operation['shape'], values)
            if 'axis' in shape:
                shape['axis'] = vector(shape['axis'])
            operations.append({**operation, 'shape': shape, 'color': local_bodies[operation['body']]['appearance']['color']})
        world = placed.place_parts(operations, prefix, component_prefix+fixture['id'], point)
        for body in world['bodies']:
            original = local_bodies[body['id'][len(prefix)+1:]]
            body.update({**original, 'id': body['id'], 'component': component_prefix+original['component'],
                         'level_id': item['level'], 'laboratory_id': item['id'], 'source_body_id': original['id']})
        result['bodies'].extend(world['bodies']); result['operations'].extend(world['operations'])
        components = {b['component'] for b in world['bodies']}
        result['components'].extend({'id': name, 'grounded': True} for name in sorted(components))
        for joint in local['joints']:
            moving = [prefix+'_'+b['id'] for b in local['bodies'] if b['component'] == joint['child']]
            require(moving, 'Placed furniture joint must own existing bodies')
            limits_key = 'limits_deg' if joint['type'] == 'revolute' else 'limits_mm'
            limits = [robot.evaluate(v, values) for v in joint[limits_key]]
            origin = point(*[robot.evaluate(v, values) for v in joint['origin']])
            front = [-v for v in n] if fixture.get('front') == 'negative_x' else n
            derived = {**joint, 'id': prefix+'_'+joint['id'], 'origin': origin, 'origin_mm': origin,
                'axis': vector(joint['axis']), 'reference_x': vector(joint.get('reference_x', [1, 0, 0])),
                'parent': component_prefix+joint['parent'], 'child': component_prefix+joint['child'],
                'instance_id': fixture['id'], 'instance_type': instance_type,
                'articulation_id': joint['id'].removeprefix(fixture['id']+'_'),
                'moving_body_ids': moving, 'front': front+[0], limits_key: limits,
                'value': robot.evaluate(joint.get('value', 0), values)}
            if fixture['kind'] == 'hood':
                roles = {b['role'] for b in local['bodies'] if b['component'] == joint['child']}
                derived.update(equipment_asset=source['hood_profile'],
                               equipment_role='vertical_sash' if 'vertical_sash' in roles else 'hinged_cabinet_door')
            result['joints'].append(derived)
        frame_id = item['id']+'.'+fixture['id']+'.Worktop'
        origin = [sum(v[i] for v in fixture['polygon_mm'])/4 for i in (0, 1)]+[z+top]
        frames.append({'id': frame_id, 'origin': origin, 'origin_mm': origin, 'source_origin': [0, 0, top],
                       'x_axis': t+[0], 'z_axis': [0, 0, 1]})
        places.append({'id': frame_id, 'kind': 'work_surface', 'frame_id': frame_id,
                       'polygon_mm': [xy+[z+top] for xy in fixture['polygon_mm']]})
        instances.append({'id': fixture['id'], 'type': instance_type, 'body_ids': world['body_ids'],
                          'source_instance': source['prototype_instances'].get(fixture['kind']),
                          'layout_kind': fixture['kind'], 'footprint_mm': fixture['polygon_mm'],
                          'access_polygon_mm': fixture['access_polygon_mm'], 'walls': fixture['walls']})
    furniture_ids = [b['id'] for b in result['bodies']]
    appliances = []
    if 'ice_maker' in item:
        import building_ice_maker
        wet, = [fixture for fixture in design['fixtures'] if fixture['kind'] == 'wet']
        appliances.append(building_ice_maker.add_to_wet_bench(item['ice_maker'], item, wet, result, numeric_shape))
    body_ids = [b['id'] for b in result['bodies']]
    result['interface'] = {'id': item['id'], 'room': item['room'], 'level_id': item['level'], 'area': item['area'],
        'template_areas': [item['area']], 'furnishing_profile': profile_ref,
        'body_ids': body_ids, 'furniture_body_ids': furniture_ids, 'native_equipment_included': True,
        'device_instances': [], 'frames': frames, 'joints': result['joints'], 'instances': instances, 'places': places,
        'interior_polygon_mm': design['outline'], 'wet_corner': design['corner'],
        'wet_corner_candidates': design['corner_candidates'], 'door_keepouts': design['keepouts'],
        'wet_pair_placed': any(f['kind'] == 'wet' for f in design['fixtures']),
        'central_double_bench_placed': any(f['kind'] == 'island' for f in design['fixtures']),
        'compact_layout': design['compact'],
        'minimum_aisle_mm': design['settings']['minimum_aisle'],
        'furniture_room_check': {'passed': all(fits(f['polygon_mm'], design['outline'], design['wall_margin_mm']) for f in design['fixtures']),
                                'method': 'polygon_containment_and_boundary_distance', 'wall_margin_mm': design['wall_margin_mm']},
        'limitations': design['notes'], 'placement_qualified': False, 'metric_registration_qualified': False,
        'source_refs': {'profile': profile_ref, 'room': source['reference_room'], 'hood': source['hood_source']}}
    if appliances:
        result['interface']['native_appliances'] = appliances
    return result
