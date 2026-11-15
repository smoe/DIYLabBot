"""Source-bound elliptical-table seating in the confirmed Kernbereich.

The alcove remains a building-plan variant.  This helper creates furniture
only, using the common catalogue instancer.  It does not create room geometry,
slabs, barriers, physical walking routes or a new CAD-specific representation.
"""
import math
from pathlib import Path
import re

import relative_floorplan as floor

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/'model/atrium-seating.schema.json'
FORMAT = 'solidcraftbot.atrium-seating/1'
OVAL_DIMENSIONS = {'length', 'width', 'height', 'top_t', 'leg_size', 'leg_inset_x', 'leg_inset_y'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+name+' fields')


def numeric(value, low, high, name):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            'Invalid '+name)


def identifier(value):
    return isinstance(value, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', value) is not None


def oval_dimensions(definition, overrides=None):
    exact(definition, 'recipe basis parameters colors part_ids max_chord_deviation_mm', 'oval table recipe')
    require(definition['recipe'] == 'elliptical_table', 'An elliptical-table recipe is required')
    numeric(definition['max_chord_deviation_mm'], .1, 2, 'ellipse profile deviation')
    require(isinstance(definition['basis'], str) and definition['basis'], 'Oval-table assumption basis required')
    require(set(definition['parameters']) == OVAL_DIMENSIONS, 'Explicit oval-table dimensions required')
    require(isinstance(overrides or {}, dict) and not set(overrides or {})-OVAL_DIMENSIONS,
            'Unknown oval-table dimension override')
    values = {}
    for name, dimension in definition['parameters'].items():
        exact(dimension, 'default unit range basis', 'oval table dimension')
        require(dimension['unit'] == 'mm' and dimension['basis'] == 'presentation_assumption',
                'Oval-table dimensions require mm and an assumption basis')
        limits = dimension['range']
        require(isinstance(limits, list) and len(limits) == 2, 'Finite oval-table dimension range required')
        for limit in limits:
            numeric(limit, .001, 50000, 'oval-table dimension bound')
        require(limits[0] <= limits[1], 'Ordered oval-table dimension bounds required')
        numeric(dimension['default'], *limits, 'default '+name)
        value = (overrides or {}).get(name, dimension['default'])
        numeric(value, *limits, name)
        values[name] = value
    exact(definition['colors'], 'top legs', 'oval table colours')
    require(all(isinstance(value, str) and re.fullmatch('#[0-9a-fA-F]{6}', value)
                for value in definition['colors'].values()), 'RGB oval-table colours required')
    exact(definition['part_ids'], 'top start_start start_end end_start end_end', 'oval table part IDs')
    require(all(identifier(value) for value in definition['part_ids'].values())
            and len(set(definition['part_ids'].values())) == 5, 'Distinct oval-table part IDs required')
    require(values['length'] > values['width'] and values['height'] > values['top_t'],
            'Oval tabletop requires length greater than width and positive support height')
    require(definition['max_chord_deviation_mm'] < values['width']/2,
            'Ellipse profile deviation must be smaller than its minor radius')
    require(values['leg_inset_x']+values['leg_size'] < values['length']/2
            and values['leg_inset_y']+values['leg_size'] < values['width']/2,
            'Oval-table legs need distinct, separated support stations')
    return values


def oval_parts(definition, overrides=None):
    """Lower a bounded elliptical outline to one portable polygon extrusion.

    An ellipse is an affine image of a unit circle.  Multiplying the circular
    chord sagitta by its major radius bounds the profile error for every arc.
    Four equal quadrants retain the exact catalogue length and width.
    """
    values = oval_dimensions(definition, overrides)
    length, width, height, top_t, leg = [values[key] for key in ('length', 'width', 'height', 'top_t', 'leg_size')]
    major, minor = length/2, width/2
    deviation = definition['max_chord_deviation_mm']
    segments = 4*max(4, math.ceil(math.pi/(4*math.acos(1-deviation/major))))
    points = [[major*math.cos(2*math.pi*i/segments), minor*math.sin(2*math.pi*i/segments)]
              for i in range(segments)]
    parts = []
    def add(name, body, color, shape, action='create'):
        parts.append({'id': name, 'body': body, 'color': color, 'action': action, 'shape': shape})
    top = definition['part_ids']['top']
    add(top, top, definition['colors']['top'], {'kind': 'polygon_prism', 'plane': 'XY',
        'points': points, 'offset': height-top_t, 'depth': top_t, 'fixed': True})
    xvalues = {'start': -length/2+values['leg_inset_x'],
               'end': length/2-values['leg_inset_x']-leg}
    yvalues = {'start': -width/2+values['leg_inset_y'],
               'end': width/2-values['leg_inset_y']-leg}
    for xside, x in xvalues.items():
        for yside, y in yvalues.items():
            corners = [[x+dx, y+dy] for dx in (0, leg) for dy in (0, leg)]
            for xx, yy in corners:
                require(floor.point_membership([xx, yy], points) >= 0,
                        'Oval-table support extends beyond its tabletop')
            name = definition['part_ids'][xside+'_'+yside]
            add(name, name, definition['colors']['legs'], {'kind': 'box',
                'origin': [x, y, 0], 'size': [leg, leg, height-top_t]})
    return parts


def validate(group):
    exact(group, 'format id anchor levels table_type chair_type table_overrides_mm chair_station_fraction table_edge_gap_mm clearances_mm basis', 'atrium seating group')
    require(group['format'] == FORMAT and identifier(group['id']) and identifier(group['anchor']),
            'Stable atrium seating identity and anchor required')
    require(group['levels'] == ['OG1', 'OG2', 'OG3'], 'Exactly one seating group on each of OG1, OG2 and OG3 is supported')
    require(identifier(group['table_type']) and identifier(group['chair_type'])
            and isinstance(group['table_overrides_mm'], dict), 'Catalogue types and explicit table overrides required')
    numeric(group['chair_station_fraction'], .1, .4, 'chair station fraction')
    numeric(group['table_edge_gap_mm'], 20, 500, 'table/chair gap')
    exact(group['clearances_mm'], 'entry wall guard', 'static seating clearances')
    for name, value in group['clearances_mm'].items():
        numeric(value, 0, 2000, name+' clearance')
    require(group['basis'] == 'presentation_assumption', 'Seating dimensions remain presentation assumptions')
    return group


def operation_bounds(shape):
    """Conservative bounds of the existing, horizontal portable primitives."""
    kind = shape['kind']
    if kind == 'box':
        low = shape['origin']
        high = [low[i]+shape['size'][i] for i in range(3)]
    elif kind == 'polygon_prism':
        require(shape.get('plane', 'XY') == 'XY', 'Horizontal seating profiles required')
        low = [min(point[i] for point in shape['points']) for i in (0, 1)]+[shape['offset']]
        high = [max(point[i] for point in shape['points']) for i in (0, 1)]+[shape['offset']+shape['depth']]
    elif kind in ('cylinder', 'cone', 'sphere'):
        require(shape.get('axis', [0, 0, 1]) == [0, 0, 1], 'Vertical seating primitives required')
        radius = max(shape['radius'], shape.get('top_radius', shape['radius']))
        origin = shape['origin']
        low = [origin[0]-radius, origin[1]-radius, origin[2]-(radius if kind == 'sphere' else 0)]
        high = [origin[0]+radius, origin[1]+radius, origin[2]+(radius if kind == 'sphere' else shape['height'])]
    else:
        raise ValueError('Unsupported seating-bound primitive: '+str(kind))
    require(all(type(value) in (int, float) and math.isfinite(value) for value in low+high),
            'Finite seating bounds required')
    require(all(high[i] > low[i] for i in range(3)), 'Positive seating-bound extents required')
    return {'min': list(low), 'max': list(high)}


def body_bounds(operations):
    result = {}
    for operation in operations:
        if operation['action'] == 'cut':
            continue
        bounds = operation_bounds(operation['shape'])
        name = operation['body']
        if operation['action'] == 'create':
            require(name not in result, 'Duplicate seating-bound body')
            result[name] = bounds
        else:
            require(operation['action'] == 'join' and name in result, 'Seating join requires its created body')
            result[name] = {'min': [min(result[name]['min'][i], bounds['min'][i]) for i in range(3)],
                            'max': [max(result[name]['max'][i], bounds['max'][i]) for i in range(3)]}
    return result


def combine_bounds(bounds):
    bounds = list(bounds)
    require(bool(bounds), 'Nonempty seating geometry required')
    return {'min': [min(item['min'][i] for item in bounds) for i in range(3)],
            'max': [max(item['max'][i] for item in bounds) for i in range(3)]}


def _frame(group, anchor, p):
    exact(anchor, 'id level_id plan area_refs entry_boundary_ids guard_boundary_ids guard_post_mm', 'atrium seating anchor')
    require(anchor['id'] == group['anchor'] and anchor['level_id'] in group['levels'], 'Seating anchor or level differs from its template')
    for field in ('area_refs', 'entry_boundary_ids', 'guard_boundary_ids'):
        require(isinstance(anchor[field], list) and anchor[field] and len(anchor[field]) == len(set(anchor[field]))
                and all(identifier(value) for value in anchor[field]), 'Unique existing alcove references required')
    numeric(anchor['guard_post_mm'], 1, 200, 'guard post thickness')
    numeric(p['display_scale'], 1, 1000000, 'presentation scale')
    numeric(p['display_thickness'], 1, 1000, 'presentation wall thickness')
    plan = anchor['plan']
    areas = {area['id']: area for area in plan['areas']}
    require(set(anchor['area_refs']) <= set(areas), 'Unknown seating alcove area')
    require(all(areas[name]['kind'] == 'corridor' for name in anchor['area_refs']),
            'Seating alcove must be explicitly open corridor space in the composed plan')
    selected = [areas[name] for name in anchor['area_refs']]
    incidence = {}
    for area in selected:
        for edge in area['boundary']:
            incidence[edge['wall']] = incidence.get(edge['wall'], 0)+1
    outer = {name for name, count in incidence.items() if count == 1}
    require(set(anchor['entry_boundary_ids']+anchor['guard_boundary_ids']) <= outer,
            'Entry and guard lines must bound the alcove union')
    require(not set(anchor['entry_boundary_ids']) & set(anchor['guard_boundary_ids']), 'Entry and guard edges differ')
    walls = {wall['id']: wall for wall in plan['walls']}
    require(all(walls[name]['kind'] == 'open_boundary'
                for name in anchor['entry_boundary_ids']+anchor['guard_boundary_ids']),
            'Seating entry and guarded atrium edges must be explicitly open in the composed plan')
    scale = p['display_scale']
    def ends(name):
        return [[value*scale for value in plan['vertices'][walls[name][key]]] for key in ('start', 'end')]
    def midpoint(names):
        total, sums = 0., [0., 0.]
        for name in names:
            a, b = ends(name)
            length = math.dist(a, b)
            require(length > 0, 'Nonzero alcove edge required')
            total += length
            for i in (0, 1):
                sums[i] += (a[i]+b[i])*length/2
        return [value/total for value in sums]
    entry = midpoint(anchor['entry_boundary_ids'])
    guard = midpoint(anchor['guard_boundary_ids'])
    depth = math.dist(entry, guard)
    require(depth > 0, 'Separated entry and atrium edges required')
    xaxis = [(guard[i]-entry[i])/depth for i in (0, 1)]
    yaxis = [-xaxis[1], xaxis[0]]
    center = [(entry[i]+guard[i])/2 for i in (0, 1)]
    def local(point):
        return [sum((point[i]-center[i])*axis[i] for i in (0, 1)) for axis in (xaxis, yaxis)]
    polygons = [[[value*scale for value in point] for point in floor.outline(plan, area)] for area in selected]
    local_polygons = [[local(point) for point in polygon] for polygon in polygons]
    points = [point for polygon in local_polygons for point in polygon]
    lo = [min(point[i] for point in points) for i in (0, 1)]
    hi = [max(point[i] for point in points) for i in (0, 1)]
    tolerance = 1e-6
    for names, x in [(anchor['entry_boundary_ids'], lo[0]), (anchor['guard_boundary_ids'], hi[0])]:
        require(all(abs(local(point)[0]-x) < tolerance for name in names for point in ends(name)),
                'Opposite, parallel full-width alcove entry and guard edges required')
        intervals = sorted([sorted(local(point)[1] for point in ends(name)) for name in names])
        cursor = lo[1]
        for start, end in intervals:
            require(abs(start-cursor) < tolerance, 'Alcove entry/guard boundary coverage has a gap or overlap')
            cursor = end
        require(abs(cursor-hi[1]) < tolerance, 'Alcove entry/guard boundaries must cover their full side')
    require(abs(lo[1]+hi[1]) < tolerance, 'Entry and guard edges must share the alcove transverse center')
    # Explicitly support a tiled rectangle, not a bounding-box substitute for
    # a concave area or a gap between two unrelated rooms.
    for polygon in local_polygons:
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            require(abs(a[0]-b[0]) < tolerance or abs(a[1]-b[1]) < tolerance,
                    'Rectilinear seating alcove required')
    xs = sorted(set(round(point[0], 7) for point in points))
    ys = sorted(set(round(point[1], 7) for point in points))
    for xa, xb in zip(xs, xs[1:]):
        for ya, yb in zip(ys, ys[1:]):
            point = [(xa+xb)/2, (ya+yb)/2]
            require(sum(floor.point_membership(point, polygon) == 1 for polygon in local_polygons) == 1,
                    'Seating alcove areas must tile one rectangle without a gap or overlap')
    return {'center': center, 'xaxis': xaxis, 'yaxis': yaxis, 'lo': lo, 'hi': hi,
            'polygons_mm': polygons, 'entry_mm': entry, 'guard_mm': guard}


def compile(catalog, group, anchor, p, level_z):
    """Instantiate one level of the declared, source-bound seating template."""
    import building_furnishings as furniture
    validate(group)
    numeric(level_z, -100000, 100000, 'level datum')
    require(catalog.get('units') == {'length': 'mm', 'angle': 'deg'}, 'Typed shared furniture catalogue required')
    require(group['table_type'] in catalog['types'] and group['chair_type'] in catalog['types'], 'Known seating catalogue types required')
    frame = _frame(group, anchor, p)
    definition = catalog['types'][group['table_type']]
    dimensions = oval_dimensions(definition, group['table_overrides_mm'])
    chair_parts = furniture.parts_for(catalog, group['chair_type'])
    local_chair = combine_bounds(body_bounds([{'body': part['body'], 'action': part['action'], 'shape': part['shape']}
                                             for part in chair_parts]).values())
    require(local_chair['min'][1] < 0, 'Dining-chair forward direction must be catalogue -Y')
    station = dimensions['length']*group['chair_station_fraction']
    row = dimensions['width']/2+group['table_edge_gap_mm']-local_chair['min'][1]
    poses = [('Table', group['table_type'], [0., 0.], 0.)]
    for side, yy, yaw in [('Near', -row, 180.), ('Far', row, 0.)]:
        for suffix, xx in [('Start', -station), ('End', station)]:
            poses.append(('Chair'+side+suffix, group['chair_type'], [xx, yy], yaw))
    prefix = group['id']+'_'+anchor['level_id']
    component = prefix+'_Furniture'
    trial, local_instances = [], []
    for name, kind, xy, yaw in poses:
        parts = furniture.parts_for(catalog, kind, group['table_overrides_mm'] if name == 'Table' else None)
        angle = math.radians(yaw)
        def placed(x, y, z):
            return [xy[0]+math.cos(angle)*x-math.sin(angle)*y,
                    xy[1]+math.sin(angle)*x+math.cos(angle)*y, z]
        part = furniture.place_parts(parts, prefix+'_'+name, component, placed)
        trial.extend(part['operations'])
        local_instances.append({'id': prefix+'_'+name, 'body_ids': part['body_ids'],
                                'bounds': combine_bounds(body_bounds(part['operations']).values())})
    local_bounds = combine_bounds([item['bounds'] for item in local_instances])
    clearances = group['clearances_mm']
    lower = [frame['lo'][0]+clearances['entry'], frame['lo'][1]+p['display_thickness']/2+clearances['wall']]
    upper = [frame['hi'][0]-anchor['guard_post_mm']/2-clearances['guard'],
             frame['hi'][1]-p['display_thickness']/2-clearances['wall']]
    center_xy = [max(lower[i]-local_bounds['min'][i], min(0., upper[i]-local_bounds['max'][i])) for i in (0, 1)]
    require(all(lower[i]-local_bounds['min'][i] <= upper[i]-local_bounds['max'][i] for i in (0, 1)),
            'Full-size seating does not fit the declared alcove and static clearances')
    require(all(abs(item['bounds']['min'][2]) < 1e-7 for item in local_instances),
            'Every seating instance needs floor contact in its catalogue pose')
    pairs = []
    bounds_by_body = body_bounds(trial)
    owner = {name: item['id'] for item in local_instances for name in item['body_ids']}
    names = list(bounds_by_body)
    for index, name in enumerate(names):
        for other in names[index+1:]:
            if owner[name] == owner[other]:
                continue
            a, b = bounds_by_body[name], bounds_by_body[other]
            overlap = min(min(a['max'][i], b['max'][i])-max(a['min'][i], b['min'][i]) for i in range(3))
            require(overlap <= 1e-7, 'Seating catalogue instances have a positive-volume AABB candidate')
            pairs.append([name, other])
    origin = [frame['center'][i]+sum(center_xy[j]*frame[axis][i] for j, axis in enumerate(('xaxis', 'yaxis')))
              for i in (0, 1)]+[level_z]
    angle = math.degrees(math.atan2(frame['xaxis'][1], frame['xaxis'][0]))
    result = {'components': [{'id': component, 'grounded': True}], 'bodies': [], 'operations': []}
    instances = []
    for name, kind, xy, yaw in poses:
        world = [origin[i]+xy[0]*frame['xaxis'][i]+xy[1]*frame['yaxis'][i] for i in (0, 1)]+[level_z]
        parts = furniture.parts_for(catalog, kind, group['table_overrides_mm'] if name == 'Table' else None)
        theta = math.radians(angle+yaw)
        def placed(x, y, z):
            return [world[0]+math.cos(theta)*x-math.sin(theta)*y,
                    world[1]+math.sin(theta)*x+math.cos(theta)*y, world[2]+z]
        part = furniture.place_parts(parts, prefix+'_'+name, component, placed)
        for key in ('bodies', 'operations'):
            result[key].extend(part[key])
        instances.append({'id': prefix+'_'+name, 'type': kind, 'origin_mm': world,
                          'yaw_deg': angle+yaw, 'body_ids': part['body_ids']})
    result['body_ids'] = [body['id'] for body in result['bodies']]
    for body in result['bodies']:
        body['level_id'] = anchor['level_id']
    result['interface'] = {'id': prefix, 'template_id': group['id'], 'anchor_id': anchor['id'],
        'level_id': anchor['level_id'], 'level_z_mm': level_z,
        'area_refs': list(anchor['area_refs']), 'entry_boundary_ids': list(anchor['entry_boundary_ids']),
        'guard_boundary_ids': list(anchor['guard_boundary_ids']), 'body_ids': result['body_ids'],
        'instances': instances, 'table_count': 1, 'chair_count': 4,
        'origin_mm': origin, 'frame_x': frame['xaxis'], 'frame_y': frame['yaxis'],
        'source_area_polygons_mm': frame['polygons_mm'],
        'catalogue_dimensions_mm': dimensions, 'instance_scale': 1,
        'static_clearance_mm': {'entry': local_bounds['min'][0]+center_xy[0]-frame['lo'][0],
            'guard': frame['hi'][0]-anchor['guard_post_mm']/2-local_bounds['max'][0]-center_xy[0],
            'wall_low': local_bounds['min'][1]+center_xy[1]-frame['lo'][1]-p['display_thickness']/2,
            'wall_high': frame['hi'][1]-p['display_thickness']/2-local_bounds['max'][1]-center_xy[1]},
        'inter_instance_body_pairs': len(pairs), 'positive_aabb_candidates': 0,
        'pair_bounds_frame': 'source_alcove_axes',
        'floor_contact_confirmed_in_source': True, 'dimensions_measured': False,
        'swept_chair_access_checked': False, 'structural_qualified': False,
        'scope': 'Portable source geometry and conservative static body/edge bounds; native models require separate verification'}
    return result


def dependencies():
    return [Path(__file__), SCHEMA]
