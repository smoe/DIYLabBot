"""Derive corridor-facing room plaques from the effective room/door graph."""
import math
import re
import textwrap

import building_doors as doors
import building_room_labels as labels
import marker_label
import relative_floorplan as floor


def validate(source):
    fields = {'format', 'selection', 'side', 'width_mm', 'minimum_width_mm', 'height_mm',
              'center_height_mm', 'jamb_gap_mm', 'wall_gap_mm', 'thickness_mm',
              'text_height_mm', 'line_width_mm', 'text_margin_mm', 'background_color',
              'ink_color', 'basis', 'letter_case'}
    if not isinstance(source, dict) or set(source) != fields:
        raise ValueError('Explicit room-sign appearance and placement assumptions required')
    if (source['format'] != 'solidcraftbot.corridor-room-signs/1'
            or source['selection'] != 'known_room_corridor_doors'
            or source['side'] != 'right_from_corridor'
            or source['basis'] != 'unmeasured_presentation_assumption'
            or source['letter_case'] != 'uppercase'):
        raise ValueError('Known room doors and corridor-relative right side required')
    for key, value in source.items():
        if key.endswith('_mm') and (type(value) not in (int, float)
                or not math.isfinite(value) or not 0 < value < 3000):
            raise ValueError('Positive finite room-sign dimension required: '+key)
    if not (source['minimum_width_mm'] <= source['width_mm']
            and 2*source['text_margin_mm'] < source['minimum_width_mm']
            and source['line_width_mm'] < source['text_height_mm']/4
            and source['height_mm']/2 < source['center_height_mm']):
        raise ValueError('Room-sign plate and lettering must fit their declared dimensions')
    for key in ('background_color', 'ink_color'):
        if not isinstance(source[key], str) or not re.fullmatch('#[0-9a-fA-F]{6}', source[key]):
            raise ValueError('Room-sign RGB colors required')


def text_lines(text, width, source):
    """Fit at most three centered lines without changing the label's meaning."""
    text = text.upper()
    height = source['text_height_mm']; margin = source['text_margin_mm']
    for char in text:
        if char not in marker_label.PATHS and char not in {' ', '\n'}:
            raise ValueError('Unsupported room-sign character: '+repr(char))
    while height >= 6:
        columns = max(1, int((width-2*margin)/(height*.78)))
        # TextWrapper versions differ at a long-word boundary after a space.
        # Invisible trailing whitespace must not affect glyph centering.
        lines = [line.rstrip() for paragraph in text.splitlines()
                 for line in textwrap.wrap(paragraph, width=columns, break_long_words=True,
                                           break_on_hyphens=False)]
        if lines and len(lines) <= 3 and len(lines)*height*1.6 <= source['height_mm']-2*margin:
            return lines, height
        height -= .5
    raise ValueError('Known room name cannot fit its right-jamb plaque: '+text)


def right_wall_run(plan, opening, corridor, jamb, right, scale, omitted):
    """Continue across collinear wall graph edges, stopping at any aperture."""
    runs = []
    for wall in plan['walls']:
        if wall['kind'] != 'wall' or wall['id'] in omitted:
            continue
        if not any(edge['wall'] == wall['id'] for edge in corridor['boundary']):
            continue
        ends = [[v*scale for v in plan['vertices'][wall[k]]] for k in ('start', 'end')]
        if any(abs((point[0]-jamb[0])*right[1]-(point[1]-jamb[1])*right[0]) > 1e-6 for point in ends):
            continue
        coordinates = [sum((point[i]-jamb[i])*right[i] for i in (0, 1)) for point in ends]
        pieces = [sorted(coordinates)]
        for other in plan['openings']:
            if other['wall'] != wall['id']:
                continue
            low, high = sorted(coordinates[0]+t*(coordinates[1]-coordinates[0]) for t in other['interval'])
            pieces = [(a, min(b, low)) for a, b in pieces if a < low] + [(max(a, high), b) for a, b in pieces if b > high]
        runs.extend((a, b, wall['id']) for a, b in pieces if b > a)
    end = 0.; supports = []
    while True:
        candidates = [(b, name) for a, b, name in runs if a <= end+1e-6 and b > end+1e-6]
        if not candidates:
            return end, supports
        end, name = max(candidates)
        supports.append(name)


def right_return(plan, opening, corridor, room, jamb, right, front, scale, source, half_wall, omitted, available):
    """Use the immediately adjoining right recess face when the jamb is narrow."""
    if available > source['width_mm']+source['jamb_gap_mm']+half_wall+source['text_margin_mm']:
        return None
    wall = next(w for w in plan['walls'] if w['id'] == opening['wall'])
    ends = [[v*scale for v in plan['vertices'][wall[k]]] for k in ('start', 'end')]
    corner = max(ends, key=lambda point: sum((point[i]-jamb[i])*right[i] for i in (0, 1)))
    if abs(sum((corner[i]-jamb[i])*right[i] for i in (0, 1))-available) > 1e-6:
        return None
    opening_width = (opening['interval'][1]-opening['interval'][0])*math.dist(*ends)
    door_center = [jamb[i]-right[i]*opening_width/2 for i in (0, 1)]
    winding = 1 if floor.signed_area(floor.outline(plan, corridor)) > 0 else -1
    for edge in corridor['boundary']:
        candidate = next(w for w in plan['walls'] if w['id'] == edge['wall'])
        if candidate['kind'] != 'wall' or candidate['id'] == wall['id'] or candidate['id'] in omitted:
            continue
        a, b = [[v*scale for v in plan['vertices'][candidate[k]]] for k in ('start', 'end')]
        if min(math.dist(a, corner), math.dist(b, corner)) > 1e-6:
            continue
        length = math.dist(a, b); axis = [(b[i]-a[i])/length for i in (0, 1)]
        normal = [-axis[1]*edge['direction']*winding, axis[0]*edge['direction']*winding]
        tangent = [-normal[1], normal[0]]
        # The boundary supplies the corridor-facing side.  Visibility is later
        # checked from actual interior corridor points, not a guessed 1 m ray.
        origin = [corner[i]+normal[i]*(half_wall+source['wall_gap_mm']) for i in (0, 1)]
        far = b if math.dist(a, corner) < 1e-6 else a
        reach = sum((far[i]-corner[i])*tangent[i] for i in (0, 1))
        width = min(source['width_mm'], reach-half_wall-source['jamb_gap_mm']-source['text_margin_mm'])
        offset = half_wall+source['jamb_gap_mm']+width/2
        center = [origin[i]+tangent[i]*offset for i in (0, 1)]
        if (width < source['minimum_width_mm']
                or sum((center[i]-door_center[i])*right[i] for i in (0, 1)) <= opening_width/4
                or any(item['wall'] == candidate['id'] for item in plan['openings'])):
            continue
        return center, tangent, normal, [candidate['id']], width
    return None


def _ccw(polygon):
    return list(reversed(polygon)) if floor.signed_area(polygon) < 0 else list(polygon)


def convex_intersection(first, second):
    """Clip one convex polygon by another; retain contact points as well."""
    result = _ccw(first)
    for a, b in zip(_ccw(second), _ccw(second)[1:]+_ccw(second)[:1]):
        previous = result
        result = []
        if not previous:
            break
        def side(point):
            return (b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
        start = previous[-1]; start_side = side(start)
        for end in previous:
            end_side = side(end)
            if (end_side >= 0) != (start_side >= 0):
                fraction = start_side/(start_side-end_side)
                result.append([start[i]+fraction*(end[i]-start[i]) for i in (0, 1)])
            if end_side >= 0:
                result.append(end)
            start, start_side = end, end_side
    return result


def _point_segment(point, a, b):
    delta = [b[i]-a[i] for i in (0, 1)]
    squared = sum(v*v for v in delta)
    fraction = max(0., min(1., sum((point[i]-a[i])*delta[i] for i in (0, 1))/squared))
    nearest = [a[i]+fraction*delta[i] for i in (0, 1)]
    return math.dist(point, nearest), nearest


def polygon_gap(first, second):
    """Return exact planar polygon distance and the two closest-point witnesses."""
    overlap = convex_intersection(first, second)
    if overlap:
        witness = overlap[0]
        return {'gap_mm': 0., 'first_point_mm': witness, 'second_point_mm': witness,
                'overlap_area_mm2': abs(floor.signed_area(overlap)) if len(overlap) >= 3 else 0.}
    best = None
    for swap, points, edges in [(False, first, second), (True, second, first)]:
        for point in points:
            for a, b in zip(edges, edges[1:]+edges[:1]):
                distance, closest = _point_segment(point, a, b)
                if best is None or distance < best['gap_mm']:
                    best = {'gap_mm': distance, 'first_point_mm': closest if swap else point,
                            'second_point_mm': point if swap else closest, 'overlap_area_mm2': 0.}
    return best


def wall_material(plan, p, level_id, z_min, z_max, omitted_wall_ids=()):
    """Keep actual wall strips at the full plaque's storey-local height interval.

    A void is subtracted only if the complete vertical plaque envelope lies
    inside that aperture.  Unknown openings leave material in place.  Strip
    ends and thickness match relative_floorplan's portable wall recipe.
    """
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (z_min, z_max)) or z_min >= z_max:
        raise ValueError('Ordered finite storey-local plaque heights required')
    scale = p['display_scale']; half = p['display_thickness']/2
    height = p.get('display_height', p.get('clear_height_mm'))
    omitted = set(omitted_wall_ids); result = []
    for wall in plan['walls']:
        if (wall['kind'] != 'wall' or wall['id'] in omitted
                or level_id+'__Wall_'+wall['id'] in omitted):
            continue
        a, b = [[value*scale for value in plan['vertices'][wall[key]]] for key in ('start', 'end')]
        length = math.dist(a, b)
        if length <= 0:
            raise ValueError('Wall material needs a nonzero source segment')
        normal = [-(b[1]-a[1])/length, (b[0]-a[0])/length]
        pieces = [(0., 1.)]
        for opening in plan['openings']:
            if opening['wall'] != wall['id'] or opening['kind'] not in {'door', 'window'}:
                continue
            if opening['kind'] == 'door':
                bottom, top = 0., p['door_height_mm']
            else:
                if height is None:
                    raise ValueError('Window material needs the actual display height')
                bottom, top = .35*height, .75*height
            if not bottom <= z_min < z_max <= top:
                continue
            low, high = opening['interval']
            pieces = [(start, min(end, low)) for start, end in pieces if start < low] + [
                      (max(start, high), end) for start, end in pieces if end > high]
        for low, high in pieces:
            start = [a[i]+low*(b[i]-a[i]) for i in (0, 1)]
            end = [a[i]+high*(b[i]-a[i]) for i in (0, 1)]
            polygon = [[point[i]+side*half*normal[i] for i in (0, 1)]
                       for point, side in [(start, 1), (end, 1), (end, -1), (start, -1)]]
            result.append({'wall_id': level_id+'__Wall_'+wall['id'],
                           'source_wall_id': wall['id'], 'polygon_mm': _ccw(polygon),
                           'source_interval': [low, high]})
    return result


def material_gap(polygon, material):
    """Measure the full footprint against every retained wall-material piece."""
    if not material:
        raise ValueError('Plaque fit requires retained wall material, not an empty scene')
    low = [min(point[i] for point in polygon) for i in (0, 1)]
    high = [max(point[i] for point in polygon) for i in (0, 1)]
    def lower_bound(item):
        other = item['polygon_mm']
        return math.sqrt(sum(max(0., min(p[i] for p in other)-high[i],
                                 low[i]-max(p[i] for p in other))**2 for i in (0, 1)))
    best = None
    for bound, item in sorted([(lower_bound(item), item) for item in material], key=lambda row: row[0]):
        if best is not None and bound >= best['minimum_gap_mm']:
            continue
        measured = polygon_gap(polygon, item['polygon_mm'])
        if best is None or measured['gap_mm'] < best['minimum_gap_mm']:
            best = {'minimum_gap_mm': measured['gap_mm'], 'closest_wall_id': item['wall_id'],
                    'plaque_point_mm': measured['first_point_mm'],
                    'wall_point_mm': measured['second_point_mm'],
                    'overlap_area_mm2': measured['overlap_area_mm2']}
    return {**best, 'checked_wall_piece_count': len(material),
            'method': 'convex polygon clipping and exact segment-distance witnesses'}


def fit_width(left_edge, right, front, max_width, source, material):
    """Shrink only the right edge; nested footprints make feasibility monotonic."""
    minimum = source['minimum_width_mm']; required = source['wall_gap_mm']
    tolerance = 1e-7
    depth = source['thickness_mm']+source['line_width_mm']
    if max_width < minimum:
        return None
    def measure(width):
        polygon = _ccw([[left_edge[i]+right[i]*along+front[i]*across for i in (0, 1)]
                       for along, across in [(0, 0), (width, 0), (width, depth), (0, depth)]])
        observed = material_gap(polygon, material)
        return {**observed, 'passed': observed['minimum_gap_mm']+tolerance >= required,
                'required_gap_mm': required, 'numeric_distance_tolerance_mm': tolerance,
                'footprint_mm': polygon, 'footprint_depth_mm': depth}
    maximum_observation = measure(max_width)
    if maximum_observation['passed']:
        width, clearance = max_width, maximum_observation
    else:
        minimum_observation = measure(minimum)
        if not minimum_observation['passed']:
            return None
        low, high = minimum, max_width
        for _ in range(48):
            middle = (low+high)/2
            if measure(middle)['passed']:
                low = middle
            else:
                high = middle
        width = max(minimum, low-1e-6)
        clearance = measure(width)
    if not clearance['passed'] or clearance['minimum_gap_mm'] <= 0:
        raise ValueError('Shrunk plaque lacks a positive actual wall-material gap')
    return {'center_mm': [left_edge[i]+right[i]*width/2 for i in (0, 1)],
            'width_mm': width, 'clearance': clearance,
            'maximum_requested_width_mm': max_width, 'width_reduction_mm': max_width-width}


def leaf_material(geometry, level_id, z_min, z_max):
    """Enclose current native-source door leaves, conservatively filling holes.

    Native leaf prisms are used directly.  Their circular viewing cuts may
    remove material; keeping those holes filled is a conservative fit bound,
    and cannot accept a plaque which intersects an open door's solid material.
    """
    if geometry is None:
        return []
    leaves = {body['id'] for body in geometry['bodies']
              if body['id'].startswith(level_id+'__DoorLeaf_')
              and body['role'].startswith('concept_open_')
              and body['role'].endswith('_room_door')}
    result = []; seen = set()
    for op in geometry['operations']:
        if op['body'] not in leaves or op['action'] == 'cut':
            continue
        shape = op['shape']
        if shape['kind'] != 'polygon_prism' or shape['plane'] != 'XY':
            raise ValueError('Existing door-leaf material needs its actual XY prism footprint')
        seen.add(op['body'])
        if shape['offset'] > z_max or shape['offset']+shape['depth'] < z_min:
            continue
        result.append({'wall_id': op['body'], 'polygon_mm': _ccw(shape['points']),
                       'material_kind': 'open_door_leaf', 'source_operation': op['id']})
    if seen != leaves:
        raise ValueError('Every existing open door leaf needs a source material enclosure')
    return result


def _segment_hits_polygon(start, end, polygon):
    """Clip a finite line segment against a closed convex material polygon."""
    low, high = 0., 1.; points = _ccw(polygon)
    for a, b in zip(points, points[1:]+points[:1]):
        def side(point):
            return (b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
        first, last = side(start), side(end)
        if first < 0 and last < 0:
            return False
        if (first < 0) != (last < 0):
            crossing = first/(first-last)
            if first < 0:
                low = max(low, crossing)
            else:
                high = min(high, crossing)
            if low > high:
                return False
    return low <= high


def corridor_viewpoint(plan, corridor, center, right, front, door_center, approach,
                       scale, material, z, source):
    """Find a front-facing center ray from the actual corridor interior.

    This finite source witness is additional evidence, not native ray tracing
    or a visibility claim for every point along the corridor.
    """
    polygon = [[value*scale for value in point] for point in floor.outline(plan, corridor)]
    target = [center[i]+front[i]*(source['thickness_mm']+source['line_width_mm']+.01)
              for i in (0, 1)]
    candidates = []
    for origin, normal in [(center, front), (door_center, approach)]:
        for distance in (500., 300., 800., 1200.):
            for lateral in (0., -source['width_mm'], source['width_mm'],
                            -2*source['width_mm'], 2*source['width_mm']):
                candidates.append([origin[i]+normal[i]*distance+right[i]*lateral for i in (0, 1)])
    for eye in candidates:
        if floor.point_membership(eye, polygon) != 1:
            continue
        distance = math.dist(eye, target)
        cosine = sum((eye[i]-target[i])*front[i] for i in (0, 1))/distance
        if cosine <= .1 or any(_segment_hits_polygon(eye, target, item['polygon_mm']) for item in material):
            continue
        return {'eye_mm': eye+[z], 'target_mm': target+[z],
                'corridor_id': corridor['id'], 'inside_actual_corridor': True,
                'front_cosine': cosine, 'distance_mm': distance,
                'source_center_ray_clear': True,
                'scope': 'Finite interior-corridor center-ray witness against source wall/open-leaf enclosures; native visibility remains a separate check'}
    return None


def compile(source, spec, plans, p, levels, omitted_wall_ids=(), door_geometry=None):
    validate(source)
    names = labels.labels(spec, plans)
    result = {'components': [{'id': 'RoomSigns', 'grounded': True}], 'bodies': [], 'operations': []}
    signs = []; seen = set(); omitted = set(omitted_wall_ids)
    scale = p['display_scale']; half_wall = p['display_thickness']/2
    for level in levels:
        plan = plans[level['id']]
        material = wall_material(plan, p, level['id'],
            source['center_height_mm']-source['height_mm']/2-source['wall_gap_mm'],
            source['center_height_mm']+source['height_mm']/2+source['wall_gap_mm'], omitted)
        leaves = leaf_material(door_geometry, level['id'],
            level['z_mm']+source['center_height_mm']-source['height_mm']/2-source['wall_gap_mm'],
            level['z_mm']+source['center_height_mm']+source['height_mm']/2+source['wall_gap_mm'])
        material += leaves
        ray_material = wall_material(plan, p, level['id'],
            source['center_height_mm']-.001, source['center_height_mm']+.001, omitted)+leaves
        wall_ids = {wall['id'] for wall in plan['walls']}
        for opening in plan['openings']:
            if opening['wall'] not in wall_ids:
                raise ValueError('Opening refers to a missing wall: '+opening['wall'])
            if opening['kind'] != 'door':
                continue
            wall_id = level['id']+'__Wall_'+opening['wall']
            if wall_id in omitted:
                continue
            adjacent = [area for area in plan['areas']
                        if any(edge['wall'] == opening['wall'] for edge in area['boundary'])]
            corridors = [area for area in adjacent if area['kind'] == 'corridor']
            rooms = [area for area in adjacent if area['kind'] != 'corridor'
                     and (level['id'], area['id']) in names]
            if len(corridors) != 1 or len(rooms) != 1 or len(adjacent) != 2:
                continue
            corridor, room = corridors[0], rooms[0]
            label = names[level['id'], room['id']]
            frame = doors.handed_frame(plan, opening, {'approach_from': corridor['id'],
                'opens_into': room['id'], 'hinge_side': 'right'}, scale)
            right, front = frame['right_vector'], frame['approach_normal']
            jamb = frame['hinge_mm']
            ahead, supporting_walls = right_wall_run(plan, opening, corridor, jamb, right, scale,
                {name.removeprefix(level['id']+'__Wall_') for name in omitted if name.startswith(level['id']+'__Wall_')})
            wall = next(w for w in plan['walls'] if w['id'] == opening['wall'])
            ends = [[value*scale for value in plan['vertices'][wall[key]]] for key in ('start', 'end')]
            opening_width = math.dist(*ends)*(opening['interval'][1]-opening['interval'][0])
            door_center = [jamb[i]-right[i]*opening_width/2 for i in (0, 1)]
            gaps = {source['jamb_gap_mm'], max(source['jamb_gap_mm'], 25.)}
            own_leaf = level['id']+'__DoorLeaf_'+opening['id']
            for leaf in leaves:
                if leaf['wall_id'] == own_leaf:
                    reach = max(sum((point[i]-jamb[i])*right[i] for i in (0, 1))
                                for point in leaf['polygon_mm'])
                    gaps.add(max(source['jamb_gap_mm'], reach+source['wall_gap_mm']+1e-6))
            candidates = []
            for gap in sorted(gaps):
                settings = {**source, 'jamb_gap_mm': gap}
                width = min(source['width_mm'], ahead-gap-source['text_margin_mm'])
                left_edge = [jamb[i]+right[i]*gap+front[i]*(half_wall+source['wall_gap_mm']) for i in (0, 1)]
                fitted = fit_width(left_edge, right, front, width, source, material)
                options = [(fitted, right, front, supporting_walls, 'right_jamb_wall')]
                returned = right_return(plan, opening, corridor, room, jamb, right, front, scale, settings,
                    half_wall, {name.removeprefix(level['id']+'__Wall_') for name in omitted if name.startswith(level['id']+'__Wall_')}, ahead)
                if returned is not None:
                    center, tangent, normal, hosts, return_width = returned
                    first_edge = [center[i]-tangent[i]*return_width/2 for i in (0, 1)]
                    options.append((fit_width(first_edge, tangent, normal, return_width, source, material),
                                    tangent, normal, hosts, 'immediate_right_recess_wall'))
                for fitted, tangent, normal, hosts, placement in options:
                    if fitted is None:
                        continue
                    observer = corridor_viewpoint(plan, corridor, fitted['center_mm'], tangent, normal,
                        door_center, front, scale, ray_material,
                        level['z_mm']+source['center_height_mm'], source)
                    if observer is not None:
                        candidates.append({'fitted': fitted, 'right': tangent, 'front': normal,
                            'supporting_walls': hosts, 'placement': placement, 'gap': gap, 'viewpoint': observer})
            if not candidates:
                raise ValueError('Insufficient visible right-jamb wall/door material for room sign: '+
                                 level['id']+'__'+opening['id'])
            straight = [item for item in candidates if item['placement'] == 'right_jamb_wall']
            chosen = min(straight or candidates, key=lambda item: (-item['fitted']['width_mm'],
                item['placement'] != 'right_jamb_wall', item['gap']))
            fitted, right, front = chosen['fitted'], chosen['right'], chosen['front']
            supporting_walls, placement = chosen['supporting_walls'], chosen['placement']
            center, width = fitted['center_mm'], fitted['width_mm']
            lines, height = text_lines(label['text'], width, source)
            z = level['z_mm']+source['center_height_mm']
            def point(x, y, depth):
                return [center[i]+right[i]*x+front[i]*depth for i in (0, 1)]+[z+y]
            name = level['id']+'__RoomSign_'+opening['id']; plate = name+'_Plate'; ink = name+'_Ink'
            for body, role, color in [(plate, 'room_sign_plate', source['background_color']),
                                      (ink, 'room_sign_ink', source['ink_color'])]:
                result['bodies'].append({'id': body, 'component': 'RoomSigns', 'role': role,
                    'level_id': level['id'], 'appearance': {'color': color, 'opacity': 1},
                    **({'geometry_semantics': 'disconnected_surface_annotation'} if body == ink else {})})
            points = [point(x, 0, depth)[:2] for x, depth in [(-width/2, 0), (width/2, 0),
                       (width/2, source['thickness_mm']), (-width/2, source['thickness_mm'])]]
            if floor.signed_area(points) < 0:
                points.reverse()
            result['operations'].append({'id': plate+'_Shape', 'body': plate, 'action': 'create',
                'shape': {'kind': 'polygon_prism', 'plane': 'XY', 'points': points,
                          'offset': z-source['height_mm']/2, 'depth': source['height_mm'], 'fixed': True}})
            strokes = 0; radius = source['line_width_mm']/2; cylinders = []; glyph_spans = []
            for row, text in enumerate(lines):
                x0 = -((len(text)-1)*.78+.6)*height/2
                y0 = ((len(lines)-1)/2-row)*height*1.6-height*.4
                for index, char in enumerate(text):
                    first_stroke = strokes
                    for path in marker_label.PATHS.get(char, []):
                        points = [tuple(map(float, item.split(','))) for item in path.split()]
                        for a, b in zip(points, points[1:]):
                            first, last = [[v[0]*.6*height, v[1]*height, 0.] for v in (a, b)]
                            length = math.dist(first, last)
                            cylinders.append({'origin': first, 'radius': radius,
                                'height': length, 'axis': [(b-a)/length for a, b in zip(first, last)]})
                            strokes += 1
                    if strokes > first_stroke:
                        glyph_spans.append({'start': first_stroke, 'count': strokes-first_stroke,
                                            'offset_mm': [x0+index*.78*height, y0, 0.]})
            if not strokes:
                raise ValueError('A room sign requires visible lettering')
            result['operations'].append({'id': ink+'_Strokes', 'body': ink, 'action': 'create',
                'shape': {'kind': 'cylinder_bundle', 'cylinders': cylinders, 'combine': 'union',
                          'glyph_spans': glyph_spans,
                          'coordinate_frame': 'glyph_local_mm',
                          'frame': {'origin': point(0, 0, source['thickness_mm']+radius),
                                    'x': right+[0], 'y': [0, 0, 1], 'z': front+[0]}}})
            signs.append({'id': name, 'level_id': level['id'], 'opening_id': opening['id'],
                'area_id': room['id'], 'corridor_id': corridor['id'], 'text': label['text'],
                'label_basis': label['basis'], 'lines': lines, 'text_height_mm': height,
                'letter_case': source['letter_case'],
                'width_mm': width, 'height_mm': source['height_mm'], 'center_mm': center+[z],
                'right_jamb_mm': jamb+[z], 'right_vector': right+[0], 'front_normal': front+[0],
                'wall_body_id': wall_id, 'body_ids': [plate, ink], 'stroke_count': strokes})
            signs[-1]['placement'] = placement
            signs[-1]['support_wall_body_ids'] = [level['id']+'__Wall_'+name for name in supporting_walls]
            signs[-1]['wall_material_clearance'] = fitted['clearance']
            signs[-1]['wall_material_clearance']['height_envelope_local_mm'] = [
                source['center_height_mm']-source['height_mm']/2-source['wall_gap_mm'],
                source['center_height_mm']+source['height_mm']/2+source['wall_gap_mm']]
            signs[-1]['width_reduction_mm'] = source['width_mm']-width
            signs[-1]['effective_jamb_gap_mm'] = chosen['gap']
            signs[-1]['source_viewpoint'] = chosen['viewpoint']
            signs[-1]['open_leaf_material_checked'] = door_geometry is not None
            seen.add((level['id'], room['id']))
    result['interface'] = {'signs': signs, 'body_ids': [body['id'] for body in result['bodies']],
        'unplaced_rooms': [{'level_id': key[0], 'area_id': key[1], **record,
                           'reason': 'no_retained_direct_corridor_door'}
                          for key, record in names.items() if key not in seen],
        'placement_basis': source['basis'], 'signage_qualified': False,
        'scope': 'Known names on retained direct corridor doors; no invented room uses or door openings'}
    return result


def physical_source(source):
    """Leave ordinary parts with their existing native construction adapter."""
    ink = {op['body'] for op in source['operations'] if op['shape']['kind'] == 'cylinder_bundle'}
    return {**source, 'bodies': [body for body in source['bodies'] if body['id'] not in ink],
            'operations': [op for op in source['operations'] if op['body'] not in ink]}


def solidcraft_ink_commands(source):
    """Union local glyph strokes, then place the disjoint annotation rigidly."""
    commands = []; bodies = {body['id']: body for body in source['bodies']}
    for op in source['operations']:
        shape = op['shape']
        if shape['kind'] != 'cylinder_bundle':
            continue
        validate_bundle(shape)
        glyph_names = []
        for index, span in enumerate(shape['glyph_spans']):
            glyph = op['body'] if index == 0 else op['body']+'_Glyph'+str(index)
            glyph_names.append(glyph); tools = []
            for stroke, cylinder in enumerate(shape['cylinders'][span['start']:span['start']+span['count']]):
                name = glyph if stroke == 0 else glyph+'_StrokeTool'+str(stroke)
                if stroke:
                    tools.append(name)
                commands.append({'command': 'solid.cylinder', 'params': {
                    'operation': 'new', 'name': name+'_Primitive', 'body_name': name,
                    'base': cylinder['origin'], 'axis': cylinder['axis'],
                    'radius': cylinder['radius'], 'height': cylinder['height']}})
            if tools:
                commands.append({'command': 'solid.combine', 'params': {'target': glyph,
                    'tools': tools, 'operation': 'join', 'touching': 'one_body', 'keep_tools': False}})
            commands.append({'command': 'solid.move', 'params': {'bodies': [glyph], 'translate': span['offset_mm']}})
        if len(glyph_names) > 1:
            commands.append({'command': 'solid.combine', 'params': {'target': op['body'],
                'tools': glyph_names[1:], 'operation': 'join', 'touching': 'one_body', 'keep_tools': False}})
        frame = shape['frame']; yaw = math.degrees(math.atan2(frame['x'][1], frame['x'][0]))
        commands.extend([{'command': 'solid.move', 'params': {'bodies': [op['body']], 'axis': [1, 0, 0], 'angle': '90 deg'}},
            {'command': 'solid.move', 'params': {'bodies': [op['body']], 'axis': [0, 0, 1], 'angle': str(yaw)+' deg'}},
            {'command': 'solid.move', 'params': {'bodies': [op['body']], 'translate': frame['origin']}}])
        body = bodies[op['body']]
        commands.extend([{'command': 'component.move_bodies', 'params': {
            'component': body['component'], 'bodies': [body['id']]}},
            {'command': 'appearance.assign', 'params': {'bodies': [body['id']], **body['appearance']}}])
    return commands


def validate_bundle(shape):
    if (set(shape) != {'kind', 'cylinders', 'combine', 'glyph_spans', 'frame', 'coordinate_frame'} or shape['kind'] != 'cylinder_bundle'
            or shape['combine'] != 'union' or not isinstance(shape['cylinders'], list)
            or not shape['cylinders'] or shape['coordinate_frame'] != 'glyph_local_mm'
            or not isinstance(shape['glyph_spans'], list) or not shape['glyph_spans']):
        raise ValueError('A pen annotation requires a nonempty union of source cylinders')
    for cylinder in shape['cylinders']:
        if set(cylinder) != {'origin', 'axis', 'radius', 'height'}:
            raise ValueError('Explicit source pen cylinder required')
        if (any(not isinstance(cylinder[k], list) or len(cylinder[k]) != 3 for k in ('origin', 'axis'))
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in cylinder['origin']+cylinder['axis']+[cylinder['radius'], cylinder['height']])
                or cylinder['radius'] <= 0 or cylinder['height'] <= 0
                or cylinder['origin'][2] != 0 or cylinder['axis'][2] != 0
                or abs(sum(v*v for v in cylinder['axis'])-1) > 1e-9):
            raise ValueError('Finite positive closed pen strokes and unit axes required')
    cursor = 0
    for span in shape['glyph_spans']:
        if (set(span) != {'start', 'count', 'offset_mm'} or type(span['start']) is not int
                or type(span['count']) is not int or span['start'] != cursor or span['count'] <= 0
                or not isinstance(span['offset_mm'], list) or len(span['offset_mm']) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in span['offset_mm'])
                or span['offset_mm'][2] != 0):
            raise ValueError('Contiguous complete local glyph partitions required')
        cursor += span['count']
    if cursor != len(shape['cylinders']):
        raise ValueError('Every source pen stroke must belong to exactly one glyph')
    frame = shape['frame']
    if (not isinstance(frame, dict) or set(frame) != {'origin', 'x', 'y', 'z'}
            or any(not isinstance(v, list) or len(v) != 3 for v in frame.values())
            or any(type(v) not in (int, float) or not math.isfinite(v) for row in frame.values() for v in row)
            or frame['y'] != [0, 0, 1] or abs(frame['x'][2]) > 1e-9
            or abs(sum(v*v for v in frame['x'])-1) > 1e-9
            or any(abs(a-b) > 1e-9 for a, b in zip(frame['z'], [frame['x'][1], -frame['x'][0], 0]))):
        raise ValueError('A proper upright rigid room-sign frame is required')
