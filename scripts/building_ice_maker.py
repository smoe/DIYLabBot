"""Bind the IM01 tabletop model to the existing wet bench's drained tray."""
import math
from pathlib import Path

import assembly_model
import ice_maker_model as appliance
from microscope_model import bounds, shape_bounds


def source_path(placement):
    if (set(placement) != {'id', 'source', 'variant', 'support', 'front_inset_mm'}
            or placement['variant'] != 'countertop'
            or not all(isinstance(placement[key], str) and placement[key].isidentifier()
                       for key in ('id', 'support'))
            or type(placement['front_inset_mm']) not in (int, float)
            or not math.isfinite(placement['front_inset_mm'])
            or placement['front_inset_mm'] < 0):
        raise ValueError('A countertop appliance requires a pinned model and tray-relative pose')
    return assembly_model.validate_reference(placement['source'], root=appliance.ROOT)


def dependencies(placement):
    scripts = appliance.ROOT/'scripts'
    return [source_path(placement), appliance.SCHEMA, Path(__file__),
            scripts/'ice_maker_model.py', scripts/'microscope_model.py']


def place_shape(shape, point, vector, normal):
    """Apply the wet bench's cardinal pose to evaluated IM01 primitives."""
    kind = shape['kind']
    if kind == 'box':
        low = shape['origin']
        a, b = point(*low), point(*(x+size for x, size in zip(low, shape['size'])))
        return {**shape, 'origin': [min(x, y) for x, y in zip(a, b)],
                'size': [abs(x-y) for x, y in zip(a, b)]}
    if kind == 'cylinder':
        return {**shape, 'origin': point(*shape['origin']), 'axis': vector(shape['axis'])}
    if kind == 'polygon_prism' and shape['plane'] == 'YZ':
        start = point(shape['offset'], 0, 0)[normal]
        end = point(shape['offset']+shape['depth'], 0, 0)[normal]
        profile = [point(0, y, z) for y, z in shape['points']]
        return {**shape, 'plane': ('YZ', 'XZ')[normal], 'fixed': True,
                'offset': min(start, end), 'points': [[p[1-normal], p[2]] for p in profile]}
    raise ValueError('Unsupported ice-maker primitive at building placement')


def add_to_wet_bench(placement, item, fixture, result, numeric_shape):
    spec = appliance.variant(appliance.load(source_path(placement)), placement['variant'])
    values = appliance.parameters(spec)
    local = appliance.expanded(spec, values)
    interface = appliance.interfaces(spec, values)
    prefix = item['id']+'_'+placement['id']
    support = item['id']+'_'+placement['support']
    wet_prefix = item['id']+'_'+fixture['id']+'_'
    host = {body['id']: body for body in result['bodies'] if body['id'].startswith(wet_prefix)}
    tray = [op for op in result['operations'] if op['body'] == support]
    if host.get(support, {}).get('role') != 'glass_drip_area':
        raise ValueError('Ice maker must refer to the actual drying tray of its wet bench')
    hollow, = [op['shape'] for op in tray if op['action'] == 'cut'
               and op['shape']['kind'] == 'polygon_prism' and op['shape']['plane'] == 'XY']
    drain, = [op['shape'] for op in tray if op['action'] == 'cut' and op['shape']['kind'] == 'cylinder']
    floor = shape_bounds(hollow)
    front = [round(v) for v in fixture['n']]
    if (sum(abs(v) for v in front) != 1 or math.dist(front, fixture['n']) > 1e-8
            or len(hollow['points']) != 4
            or set(map(tuple, hollow['points'])) != {(x, y) for x in (floor['min'][0], floor['max'][0])
                                                       for y in (floor['min'][1], floor['max'][1])}):
        raise ValueError('Ice maker requires a rectangular tray on a cardinal wall')
    width_axis = 1 if front[0] else 0
    depth_axis = 1-width_axis
    sign = front[depth_axis]
    width, depth, _ = interface['envelope_mm']
    edge = floor['max' if sign > 0 else 'min'][depth_axis]
    origin = [(lo+hi)/2 for lo, hi in zip(floor['min'], floor['max'])]
    origin[depth_axis] = edge-sign*(placement['front_inset_mm']+depth/2)
    origin[2] = hollow['offset']
    if width > floor['max'][width_axis]-floor['min'][width_axis]:
        raise ValueError('Ice maker is wider than the drying tray')

    def vector(coords):
        x, y, z = coords
        return [-front[1]*x-front[0]*y, front[0]*x-front[1]*y, z]

    def point(x, y, z):
        return [offset+v for offset, v in zip(origin, vector((x, y, z)))]

    ops = [{**op, 'id': prefix+'_'+op['id'], 'body': prefix+'_'+op['body'],
            'shape': place_shape(numeric_shape(op['shape'], values), point, vector, width_axis)}
           for op in local['operations']]
    volume = bounds(ops)
    if any(volume['min'][i] < floor['min'][i] or volume['max'][i] > floor['max'][i]
           for i in (0, 1)):
        raise ValueError('Ice maker must fit wholly inside the drying tray rim')
    pads = [op['shape'] for op in ops if op['action'] == 'create' and '_FootPad_' in op['body']]
    for pad in pads:
        centre = pad['origin']
        if centre[2] != hollow['offset'] or math.dist(centre[:2], drain['origin'][:2]) <= pad['radius']+drain['radius']:
            raise ValueError('Each ice-maker foot must rest on the tray floor clear of the drain')
    for op in result['operations']:
        if op['body'] in host and op['body'] != support and op['action'] != 'cut':
            other = shape_bounds(op['shape'])
            if all(min(other['max'][i], volume['max'][i])-max(other['min'][i], volume['min'][i]) > 1e-6
                   for i in range(3)):
                raise ValueError('Ice maker intersects wet bench component: '+op['body'])

    bodies = [{**body, 'id': prefix+'_'+body['id'], 'component': prefix, 'source_body_id': body['id'],
               'level_id': item['level'], 'laboratory_id': item['id'], 'room_id': item['area']}
              for body in local['bodies']]
    result['components'].append({'id': prefix, 'grounded': True})
    result['bodies'].extend(bodies)
    result['operations'].extend(ops)
    return {'id': placement['id'], 'source': placement['source'], 'variant': placement['variant'],
            'support_body_id': support, 'origin_mm': origin, 'front': front+[0],
            'support_floor_z_mm': hollow['offset'], 'foot_centres_mm': [p['origin'] for p in pads],
            'footprint_mm': [point(x, y, 0)[:2] for x, y in
                             ((-width/2, -depth/2), (width/2, -depth/2), (width/2, depth/2), (-width/2, depth/2))],
            'body_ids': [body['id'] for body in bodies]}
