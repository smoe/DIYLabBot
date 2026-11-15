"""Parametric desktop parts and room-bound wall spans, shared by both CADs.

Lengths are illustrative local mm. Wall contact and usable spans are derived
in presentation mm, then expressed in that same local scale exactly once.
"""
import math

import relative_floorplan as floor


DIMENSIONS = {'length', 'depth', 'height', 'top_t', 'leg_size',
              'start_inset', 'end_inset', 'max_leg_span'}


def dimensions(definition, overrides=None):
    if definition.get('recipe') != 'desktop' or set(definition['parameters']) != DIMENSIONS:
        raise ValueError('Unsupported parametric desktop')
    if set(overrides or {}) - DIMENSIONS:
        raise ValueError('Unknown desktop dimension')
    values = {}
    for name, parameter in definition['parameters'].items():
        if (set(parameter) != {'default', 'unit', 'range', 'basis'}
                or parameter['unit'] != 'mm' or parameter['basis'] != 'presentation_assumption'):
            raise ValueError('Desktop dimensions require mm and an assumption basis')
        bounds = parameter['range']; value = (overrides or {}).get(name, parameter['default'])
        if (len(bounds) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                or not 0 < bounds[0] <= bounds[1] or type(value) not in (int, float)
                or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]):
            raise ValueError('Desktop dimension outside declared range: ' + name)
        values[name] = value
    if (values['height'] <= values['top_t'] or
            min(values['length'], values['depth']) <= values['start_inset'] + values['end_inset'] + values['leg_size']):
        raise ValueError('Desktop has no supported interior')
    return values


def desktop_parts(definition, overrides=None, footprint=None):
    """One desktop recipe; defaults retain the historical five part IDs/parts."""
    values = dimensions(definition, overrides)
    length, depth, height, top_t, leg = [values[n] for n in ('length', 'depth', 'height', 'top_t', 'leg_size')]
    parts = []
    def part(name, color, shape):
        parts.append({'id': name, 'body': name, 'color': color, 'action': 'create', 'shape': shape})
    top = ({'kind': 'box', 'origin': [0, 0, height-top_t], 'size': [length, depth, top_t]}
           if footprint is None else {'kind': 'polygon_prism', 'plane': 'XY', 'points': footprint,
                                      'offset': height-top_t, 'depth': top_t, 'fixed': True})
    part(definition['part_ids']['top'], definition['colors']['top'], top)
    start, end = values['start_inset'], length-values['end_inset']
    count = max(1, math.ceil((end-start)/values['max_leg_span']))
    for index in range(count+1):
        x = start if index == 0 else end if index == count else start+(end-start)*index/count
        for side, y in [('start', start), ('end', depth-values['end_inset'])]:
            role = ('start_' if index == 0 else 'end_')+side
            name = definition['part_ids'][role] if index in (0, count) else 'LegMid'+str(index)+'_'+side
            corners = [[x, y], [x+leg, y], [x+leg, y+leg], [x, y+leg]]
            if footprint is not None and any(floor.point_membership(q, footprint) < 0 for q in corners):
                raise ValueError('Desktop support would leave the fitted worktop')
            part(name, definition['colors']['legs'], {'kind': 'box', 'origin': [x, y, 0], 'size': [leg, leg, height-top_t]})
    return parts


def wall_frame(plan, area, wall_id, p):
    edge = next((edge for edge in area['boundary'] if edge['wall'] == wall_id), None)
    if edge is None:
        raise ValueError('Wall span must belong to its referenced room')
    wall = next(w for w in plan['walls'] if w['id'] == wall_id)
    a, b = [[v*p['display_scale'] for v in plan['vertices'][wall[key]]] for key in ('start', 'end')]
    length = math.dist(a, b); tangent = [(b[i]-a[i])/length for i in (0, 1)]
    orientation = 1 if floor.signed_area(floor.outline(plan, area)) > 0 else -1
    inward = [orientation*edge['direction']*v for v in (-tangent[1], tangent[0])]
    return a, tangent, inward, length


def clip(points, origin, normal, distance):
    """Keep the inside of a source wall/room half-plane."""
    result = []
    for a, b in zip(points, points[1:]+points[:1]):
        da = sum((a[i]-origin[i])*normal[i] for i in (0, 1))-distance
        db = sum((b[i]-origin[i])*normal[i] for i in (0, 1))-distance
        if da >= -1e-8:
            result.append(a)
        if (da > 1e-8 and db < -1e-8) or (da < -1e-8 and db > 1e-8):
            t = da/(da-db); result.append([a[i]+t*(b[i]-a[i]) for i in (0, 1)])
    clean = []
    for point in result:
        if not clean or math.dist(point, clean[-1]) > 1e-7:
            clean.append(point)
    if len(clean) > 1 and math.dist(clean[0], clean[-1]) <= 1e-7:
        clean.pop()
    return clean


def fit_spans(room, catalog, plan, p, scale):
    """Resolve anchored desk modules; the window module owns both butt corners."""
    items = [item for item in room['instances'] if 'wall_span' in item]
    if not items:
        return {}
    owners = [item for item in items if item['wall_span']['corner_owner']]
    if len(owners) != 1:
        raise ValueError('A fitted U needs exactly one window/corner owner')
    result = {}
    for item in items:
        span = item['wall_span']
        required = {'area_id', 'wall_id', 'segment', 'back_gap_mm', 'opening_margin_mm', 'corner_owner'}
        if set(span)-required-{'opening_id'} or not required <= set(span):
            raise ValueError('Unsupported wall span fields')
        if (span['area_id'] not in room['template_areas'] or type(span['back_gap_mm']) not in (int,float)
                or span['back_gap_mm'] != 0
                or type(span['corner_owner']) is not bool or item['xyz_mm'] != [0, 0, 0] or item['yaw_deg'] != 0):
            raise ValueError('Wall spans require a zero-offset, flush room-bound pose')
        margin = span['opening_margin_mm']
        if type(margin) not in (int, float) or not math.isfinite(margin) or margin < 0:
            raise ValueError('Wall opening margin must be finite and nonnegative')
        area = next(a for a in plan['areas'] if a['id'] == span['area_id'])
        outline = [[v*p['display_scale'] for v in q] for q in floor.outline(plan, area)]
        for edge in area['boundary']:
            wa, _, normal, _ = wall_frame(plan, area, edge['wall'], p)
            if any(sum((q[i]-wa[i])*normal[i] for i in (0,1)) < -1e-6 for q in outline):
                raise ValueError('Fitted wall worktops currently require a convex room')
        a, tangent, inward, length = wall_frame(plan, area, span['wall_id'], p)
        definition = catalog['types'][item['type']]
        if 'length' in item.get('parameter_overrides_mm', {}):
            raise ValueError('Wall span length is derived from its room')
        values = dimensions(definition, item.get('parameter_overrides_mm'))
        lo, hi = 0, length
        doors = [o for o in plan['openings'] if o['wall'] == span['wall_id'] and o['kind'] == 'door']
        segment = span['segment']
        if segment == 'full':
            if doors or 'opening_id' in span:
                raise ValueError('A full wall worktop cannot cover a doorway')
        else:
            opening = next((o for o in doors if o['id'] == span.get('opening_id')), None)
            if opening is None or len(doors) != 1:
                raise ValueError('A split wall span requires its single source doorway')
            if segment == 'before_opening':
                hi = opening['interval'][0]*length-margin*scale
            elif segment == 'after_opening':
                lo = opening['interval'][1]*length+margin*scale
            else:
                raise ValueError('Unsupported wall span segment')
        if hi <= lo:
            raise ValueError('Doorway leaves no usable wall span')
        back = [a[i]+inward[i]*p['display_thickness']/2 for i in (0, 1)]
        depth = values['depth']*scale
        points = [[back[i]+tangent[i]*x+inward[i]*y for i in (0, 1)] for x,y in [(lo,0),(hi,0),(hi,depth),(lo,depth)]]
        for edge in area['boundary']:
            wa, _, normal, _ = wall_frame(plan, area, edge['wall'], p)
            points = clip(points, wa, normal, p['display_thickness']/2)
            if len(points) < 3:
                raise ValueError('Wall worktop footprint collapsed')
        result[item['id']] = {'points': points, 'back': back, 'tangent': tangent, 'inward': inward,
                              'depth': depth, 'span': span, 'values': values}
    owner = result[owners[0]['id']]
    for item in items:
        fit = result[item['id']]
        if any(fit['values'][key] != owner['values'][key] for key in ('height','top_t')):
            raise ValueError('Continuous worktops require one top height and thickness')
        if item is not owners[0]:
            fit['points'] = clip(fit['points'], owner['back'], owner['inward'], owner['depth'])
        points = fit['points']
        if len(points) < 3 or abs(floor.signed_area(points)) < 1e-5:
            raise ValueError('Corner join leaves no worktop')
        if floor.signed_area(points) < 0:
            points.reverse()
        low = min(sum((q[i]-fit['back'][i])*fit['tangent'][i] for i in (0, 1)) for q in points)
        base = [fit['back'][i]+low*fit['tangent'][i] for i in (0, 1)]
        local = [[sum((q[i]-base[i])*axis[i] for i in (0, 1))/scale for axis in (fit['tangent'],fit['inward'])] for q in points]
        fit.update(base=base, footprint=local)
        fit['values']['length'] = max(q[0] for q in local)
    return result
