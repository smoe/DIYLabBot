"""Static, source-referenced lift and shared two-flight stair concept recipe.

No lift controller, moving cabin, normative stair design or
navigation is implemented. Deliberate fusion/support overlaps are auditable.
"""
import copy
import math
import re

import relative_floorplan as floor
import building_guards as guards
import lift_fittings


def require(condition, message):
    if not condition: raise ValueError(message)


def exact(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+name+' fields')


def validate_source(source):
    exact(source, 'status served_extent elevator stairs external_stair qualification limitations', 'circulation')
    require(source['status'] == 'owner_requested_concept_geometry', 'Static owner-requested circulation concept required')
    require(source['served_extent'] == {'from_level': 'KG', 'to_level': 'OG3'}, 'Requested served extent is KG to OG3, with explicit basement concept geometry')
    lift = source['elevator']; exact(lift, 'id area reference_opening sides default_sides stop_overrides deferred_stops cabin_level post_wall_factor cabin_wall_factor cabin_clearance_factor'+(' fittings' if 'fittings' in lift else ''), 'elevator')
    if 'fittings' in lift:
        lift_fittings.validate(lift['fittings'])
    require(lift['id'] == 'BuildingLift' and lift['cabin_level'] == 'EG', 'One cabin indication at EG required')
    exact(lift['sides'], 'outward inward', 'confirmed sides')
    for side, declaration in lift['sides'].items():
        exact(declaration, 'wall label', 'side')
        require(isinstance(declaration['label'], str) and declaration['label'], 'Side label required')
    for name in [lift['id'], lift['area'], lift['reference_opening'], *[s['wall'] for s in lift['sides'].values()]]:
        require(isinstance(name, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', name), 'Stable ASCII circulation reference required')
    require(lift['sides']['outward']['wall'] != lift['sides']['inward']['wall'], 'Opposite elevator sides required')
    require(lift['default_sides'] == ['outward'] and lift['stop_overrides'] == {'EG': ['outward', 'inward'], 'KG': ['inward']}, 'Owner-confirmed active stop policy required')
    require(lift['deferred_stops'] == [], 'All declared stops now have concept geometry')
    for name in ('post_wall_factor', 'cabin_wall_factor', 'cabin_clearance_factor'):
        require(type(lift[name]) in (int, float) and math.isfinite(lift[name]) and 0 < lift[name] <= 1, 'Positive illustrative lift proportion required')
    stairs = source['stairs']; require(isinstance(stairs, dict), 'Invalid stairs fields')
    exact(stairs, 'recipe risers_per_flight landing_fraction center_gap_fraction wall_margin_factor join_slab_fraction instances'+(' guard_profile_ref' if 'guard_profile_ref' in stairs else ''), 'stairs')
    if 'guard_profile_ref' in stairs:
        require(stairs['guard_profile_ref'] == '#/exterior', 'The stair guard must reference the existing exterior atrium profile')
    require(stairs['recipe'] == 'illustrative_two_flight_turnback_v1' and type(stairs['risers_per_flight']) is int and 2 <= stairs['risers_per_flight'] <= 40, 'Bounded shared stepped-stair recipe required')
    for key in ('landing_fraction', 'center_gap_fraction', 'join_slab_fraction'):
        require(type(stairs[key]) in (int, float) and math.isfinite(stairs[key]) and 0 < stairs[key] < .4, 'Positive bounded stair ratio required')
    require(type(stairs['wall_margin_factor']) in (int, float) and math.isfinite(stairs['wall_margin_factor']) and stairs['wall_margin_factor'] >= .5, 'Preserve at least half the presentation wall thickness')
    require(len(stairs['instances']) == 1, 'Exactly one separate right-hand continuous staircase is requested')
    for item in stairs['instances']:
        exact(item, 'id area entry_opening'+(' top_guard_wall' if 'top_guard_wall' in item else ''), 'stair instance')
        require(all(isinstance(name, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', name) for name in item.values()), 'Stable ASCII stair references required')
        require('top_guard_wall' not in item or 'guard_profile_ref' in stairs,
                'A top guard wall requires the referenced guard profile')
    external = source['external_stair']
    exact(external, 'id area entry_opening ground_area ground_exit_neighbor recipe tread_thickness_mm stringer_depth_mm stringer_width_mm landing_thickness_mm status', 'external metal stair')
    for name in ('id', 'area', 'entry_opening', 'ground_area', 'ground_exit_neighbor'):
        require(isinstance(external[name], str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', external[name]), 'Stable external-stair source reference required')
    require(external['id'] != lift['id'] and external['id'] != stairs['instances'][0]['id'] and external['area'] != stairs['instances'][0]['area'], 'Internal stair, external stair and lift are distinct systems')
    require(external['recipe'] == 'illustrative_metal_two_flight_v1' and external['status'] == 'illustrative_unqualified', 'Illustrative open metal recipe required')
    for name in ('tread_thickness_mm', 'stringer_depth_mm', 'stringer_width_mm', 'landing_thickness_mm'):
        require(type(external[name]) in (int, float) and math.isfinite(external[name]) and external[name] > 0, 'Positive finite metal presentation assumption required')
    exact(source['qualification'], 'surveyed_geometry lift_operation_implemented stairs_code_qualified headroom_qualified egress_qualified basement_geometry_implemented', 'circulation qualification')
    require(source['qualification']['basement_geometry_implemented'] is True and all(v is False for k, v in source['qualification'].items() if k != 'basement_geometry_implemented'), 'Concept geometry is not qualified circulation')
    require(isinstance(source['limitations'], list) and source['limitations'] and all(isinstance(v, str) and v for v in source['limitations']), 'Circulation limitations required')


def rectangle(x0, y0, x1, y1): return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def point_distance(point, a, b):
    d = [b[i]-a[i] for i in (0, 1)]; t = max(0, min(1, sum((point[i]-a[i])*d[i] for i in (0, 1))/sum(v*v for v in d)))
    return math.dist(point, [a[i]+t*d[i] for i in (0, 1)])


def inside_rectangle(points, polygon, margin):
    if any(floor.point_membership(p, polygon) != 1 for p in points): return False
    for a, b in zip(points, points[1:]+points[:1]):
        for c, d in zip(polygon, polygon[1:]+polygon[:1]):
            if floor.side(a, b, c)*floor.side(a, b, d) == -1 and floor.side(c, d, a)*floor.side(c, d, b) == -1: return False
    distance = min([point_distance(p, a, b) for p in points for a, b in zip(polygon, polygon[1:]+polygon[:1])] +
                   [point_distance(p, a, b) for p in polygon for a, b in zip(points, points[1:]+points[:1])])
    return distance+1e-7 >= margin


def interior_rectangle(polygon, margin):
    """Keep the Xmax entry and full inset Y span; reject a non-fitting recipe."""
    x0, x1 = min(p[0] for p in polygon)+margin, max(p[0] for p in polygon)-margin
    y0, y1 = min(p[1] for p in polygon)+margin, max(p[1] for p in polygon)-margin
    require(x0 < x1 and y0 < y1, 'No inset circulation rectangle remains')
    for index in range(65):
        left = x0+(x1-x0)*index/65
        points = rectangle(left, y0, x1, y1)
        if inside_rectangle(points, polygon, margin): return [left, y0, x1, y1]
    raise ValueError('The source footprint cannot fit the declared straight-axis circulation recipe')


def compile(source, plan, p, levels, ground_plan=None, ground_support_area=None, *, guard_profile=None):
    validate_source(source)
    guard_ref = source['stairs'].get('guard_profile_ref')
    if guard_ref is not None:
        require(guard_profile is not None, 'Referenced stair guard profile must be supplied explicitly')
        guards.validate_profile(guard_profile)
    else:
        require(guard_profile is None, 'A stair guard profile requires an explicit source reference')
    areas = {a['id']: a for a in plan['areas']}; walls = {w['id']: w for w in plan['walls']}; openings = {o['id']: o for o in plan['openings']}
    if ground_plan is not None:
        ground_areas = {area['id']: area for area in ground_plan['areas']}
        for core in [source['elevator']['area'], source['stairs']['instances'][0]['area']]:
            require(core in areas and core in ground_areas, 'Registered EG must preserve the canonical vertical core areas')
            canonical = floor.outline(plan, areas[core]); registered = floor.outline(ground_plan, ground_areas[core])
            require(abs(floor.signed_area(canonical)-floor.signed_area(registered)) < 1e-10 and all(floor.point_membership(point, registered) == 0 for point in canonical) and all(floor.point_membership(point, canonical) == 0 for point in registered), 'Registered EG core outline differs from the canonical vertical frame')
        ground_walls = {wall['id']: wall for wall in ground_plan['walls']}
        for declaration in source['elevator']['sides'].values():
            name = declaration['wall']; require(name in ground_walls and ground_walls[name]['kind'] == 'wall', 'Registered EG must preserve both explicit lift wall aliases')
            source_ends = {tuple(plan['vertices'][walls[name][key]]) for key in ('start', 'end')}
            ground_ends = {tuple(ground_plan['vertices'][ground_walls[name][key]]) for key in ('start', 'end')}
            require(source_ends == ground_ends, 'Registered EG lift port frame differs from the canonical source')
    scale = p['display_scale']; thickness = p['display_thickness']; slab = p['slab_thickness_mm']; door_h = p['door_height_mm']
    result = {'components': [{'id': source['elevator']['id'], 'grounded': True}], 'bodies': [], 'operations': []}
    detail = []; bridges = []; holes = []; door_probes = []; closed = []; connections = []; shaft_checks = []
    guard_ids = []; guard_groups = []; guard_posts = []; guard_attachments = []; guard_clearances = []; ground_guard_ids = []
    def body(name, role, color, opacity=1, component=None):
        result['bodies'].append({'id': name, 'component': component or source['elevator']['id'], 'role': role, 'appearance': {'color': color, 'opacity': opacity}})
        return name
    def box(name, target, origin, size, action='create'):
        require(all(v > 0 and math.isfinite(v) for v in size), 'Positive finite circulation primitive required')
        result['operations'].append({'id': name, 'body': target, 'action': action, 'shape': {'kind': 'box', 'origin': origin, 'size': size}})
    def cut_prism(name, target, points, z, height):
        result['operations'].append({'id': name, 'body': target, 'action': 'cut', 'shape': {'kind': 'polygon_prism', 'plane': 'XY', 'points': points, 'offset': z, 'depth': height, 'fixed': True}})
    def probe(name, points, z, height, targets, expectation='empty', expected=None):
        item = {'id': name, 'kind': 'polygon_prism', 'points_mm': points, 'offset_mm': z, 'depth_mm': height, 'target_bodies': targets, 'expectation': expectation}
        if len(targets) == 1: item['target_body'] = targets[0]
        if expected is not None:
            item['expected_volumes_mm3'] = expected
            if len(targets) == 1: item['expected_volume_mm3'] = expected[targets[0]]
        return item
    def polygon(area_id):
        require(area_id in areas, 'Existing source circulation area required')
        return [[x*scale, y*scale] for x, y in floor.outline(plan, areas[area_id])]
    def wall_points(wall_id):
        require(wall_id in walls, 'Existing wall reference required')
        return [[v*scale for v in plan['vertices'][walls[wall_id][key]]] for key in ('start', 'end')]
    boundary_ids = set()
    lift = source['elevator']; lift_poly = polygon(lift['area']); lift_area = areas[lift['area']]
    boundary_ids.update(r['wall'] for r in lift_area['boundary'])
    boundary_owners = {r['wall']: lift['id'] for r in lift_area['boundary']}
    require(lift['reference_opening'] in openings, 'Source elevator opening anchor required')
    anchor = openings[lift['reference_opening']]
    require(anchor['wall'] == lift['sides']['outward']['wall'], 'Door template must reference the owner-confirmed outward side')
    a, b = wall_points(anchor['wall']); require(abs(a[0]-b[0]) < 1e-7, 'The selected elevator recipe requires vertical opposite source walls')
    lo, hi = sorted(a[1]+t*(b[1]-a[1]) for t in anchor['interval']); width = hi-lo
    bbox = [min(v[0] for v in lift_poly), min(v[1] for v in lift_poly), max(v[0] for v in lift_poly), max(v[1] for v in lift_poly)]
    for side, declaration in lift['sides'].items():
        require(declaration['wall'] in {r['wall'] for r in lift_area['boundary']} and walls[declaration['wall']]['kind'] == 'wall', 'Lift ports need known source boundary walls')
        c, d = wall_points(declaration['wall'])
        expected_x = bbox[0] if side == 'outward' else bbox[2]
        require(abs(c[0]-d[0]) < 1e-7 and abs(c[0]-expected_x) < 1e-7 and min(c[1], d[1]) <= lo < hi <= max(c[1], d[1]), 'Confirmed opposite elevator wall does not contain the shared door interval')
    post = thickness*lift['post_wall_factor']; cw = thickness*lift['cabin_wall_factor']; gap = thickness*lift['cabin_clearance_factor']
    inner = [bbox[0]+thickness, bbox[1]+thickness, bbox[2]-thickness, bbox[3]-thickness]
    require(inside_rectangle(rectangle(*inner), lift_poly, thickness-.0001), 'Shaft frame must lie inside the referenced footprint')
    shaft_ids = []; bottom = levels[0]['z_mm']; top = levels[-1]['clear_top_mm']; shaft_height = top-bottom
    for label, x, y in [('SW', inner[0], inner[1]), ('NW', inner[0], inner[3]-post), ('SE', inner[2]-post, inner[1]), ('NE', inner[2]-post, inner[3]-post)]:
        name = 'LiftPost_'+label; shaft_ids.append(body(name, 'concept_elevator_shaft_frame', '#c47a35')); box(name+'_Box', name, [x, y, bottom], [post, post, shaft_height])
        points = rectangle(x+post*.25, y+post*.25, x+post*.75, y+post*.75); volume = (post*.5)**2*shaft_height
        shaft_checks.append(probe(name+'_Continuity', points, bottom, shaft_height, [name], 'filled', {name: volume}))
    for level in levels:
        z = level['clear_top_mm']-post
        for tag, origin, size in [('Front', [inner[0], inner[1], z], [inner[2]-inner[0], post, post]), ('Back', [inner[0], inner[3]-post, z], [inner[2]-inner[0], post, post]),
                                  ('West', [inner[0], inner[1], z], [post, inner[3]-inner[1], post]), ('East', [inner[2]-post, inner[1], z], [post, inner[3]-inner[1], post])]:
            name = 'LiftFrame_'+level['id']+'_'+tag; shaft_ids.append(body(name, 'concept_elevator_shaft_frame', '#c47a35')); box(name+'_Box', name, origin, size)
    cabin_rect = [inner[0]+post+gap, inner[1]+post+gap, inner[2]-post-gap, inner[3]-post-gap]
    require(cabin_rect[0]+2*cw < cabin_rect[2] and cabin_rect[1]+cw < lo < hi < cabin_rect[3]-cw, 'Cabin shell cannot fit the shared source door interval')
    cabin = body('BuildingLiftCabin', 'concept_existing_elevator_cabin', '#b887aa'); detail.extend(shaft_ids+[cabin])
    box(cabin+'_Outer', cabin, [cabin_rect[0], cabin_rect[1], -cw], [cabin_rect[2]-cabin_rect[0], cabin_rect[3]-cabin_rect[1], door_h+3*cw])
    box(cabin+'_Hollow', cabin, [cabin_rect[0]+cw, cabin_rect[1]+cw, 0], [cabin_rect[2]-cabin_rect[0]-2*cw, cabin_rect[3]-cabin_rect[1]-2*cw, door_h+cw], 'cut')
    inset = min(width, door_h, thickness, cw)/10; doors_by_level = {}; ports = []; door_frames = []
    for level in levels:
        active = lift['stop_overrides'].get(level['id'], lift['default_sides']); doors_by_level[level['id']] = list(active)
        for side, declaration in lift['sides'].items():
            wx = bbox[0] if side == 'outward' else bbox[2]; target = level['id']+'__Wall_'+declaration['wall']; is_active = side in active
            name = 'LiftPort_'+level['id']+'_'+side
            port = {'id': name, 'level_id': level['id'], 'side': side, 'wall': declaration['wall'], 'active': is_active, 'z_mm': level['z_mm'], 'frame_body_id': None}; ports.append(port)
            port.update(plane_x_mm=wx, height_mm=door_h, wall_thickness_mm=thickness)
            if side == 'outward':
                cut_points = rectangle(wx-thickness, lo, cabin_rect[0]+cw+thickness*.1, hi)
                open_points = rectangle(wx-thickness*.4, lo+inset, cabin_rect[0]+cw-inset, hi-inset)
            else:
                cut_points = rectangle(cabin_rect[2]-cw-thickness*.1, lo, wx+thickness, hi)
                open_points = rectangle(cabin_rect[2]-cw+inset, lo+inset, wx+thickness*.4, hi-inset)
            if is_active:
                frame = 'LiftDoorFrame_'+level['id']+'_'+side
                door_frames.append(body(frame, 'concept_lift_door_frame', '#d39343')); detail.append(frame); port['frame_body_id'] = frame
                box(frame+'_JambLow', frame, [wx-post/2, lo-post, level['z_mm']], [post, post, door_h+post])
                box(frame+'_Header', frame, [wx-post/2, lo-post, level['z_mm']+door_h], [post, width+2*post, post], 'join')
                box(frame+'_JambHigh', frame, [wx-post/2, hi, level['z_mm']], [post, post, door_h+post], 'join')
                cut_prism(name+'_WallCut', target, cut_points, level['z_mm'], door_h)
                targets = [target, frame]
                if level['id'] == lift['cabin_level']:
                    cut_prism(name+'_CabinCut', cabin, cut_points, level['z_mm'], door_h); targets.append(cabin)
                door_probes.append(probe(name+'_Open', open_points, level['z_mm']+inset, door_h-2*inset, targets))
            else:
                points = rectangle(wx-thickness*.25, lo+inset, wx+thickness*.25, hi-inset); height = door_h-2*inset
                volume = thickness*.5*(width-2*inset)*height
                closed.append(probe(name+'_Closed', points, level['z_mm']+inset, height, [target], 'filled', {target: volume}))
    fittings = None
    if 'fittings' in lift:
        fittings = lift_fittings.compile(lift['fittings'], cabin_rect, cw, (lo, hi), ports,
            next(level['z_mm'] for level in levels if level['id'] == lift['cabin_level']), levels)
        for key in ('bodies', 'operations'):
            result[key].extend(fittings[key])
        detail.extend(body['id'] for body in fittings['bodies'])
    stairs = []; recipe = source['stairs']; n = recipe['risers_per_flight']; join = slab*recipe['join_slab_fraction']
    require(0 < join < slab/4, 'Small positive stair fusion overlap required')
    for instance in recipe['instances']:
        require(instance['id'] != lift['id'], 'The stair and building lift are separate assemblies')
        result['components'].append({'id': instance['id'], 'grounded': True})
        area = areas.get(instance['area']); require(area is not None and area['kind'] == 'stairwell', 'Referenced stairwell area required')
        boundary_ids.update(r['wall'] for r in area['boundary']); poly = polygon(instance['area'])
        for ref in area['boundary']:
            require(ref['wall'] not in boundary_owners or boundary_owners[ref['wall']] == instance['id'], 'The separate staircase cannot use the lift enclosure')
            boundary_owners[ref['wall']] = instance['id']
        require(instance['entry_opening'] in openings, 'Existing stair entry opening required')
        entry = openings[instance['entry_opening']]; e0, e1 = wall_points(entry['wall'])
        require(entry['kind'] == 'door' and entry['wall'] in {r['wall'] for r in area['boundary']} and abs(e0[0]-e1[0]) < 1e-7 and abs(e0[0]-max(q[0] for q in poly)) < 1e-7, 'Stair recipe requires its source entry on Xmax')
        x0, y0, x1, y1 = interior_rectangle(poly, thickness*recipe['wall_margin_factor'])
        landing = (x1-x0)*recipe['landing_fraction']; run0 = x0+landing; entry_x = x1-landing; run = entry_x-run0
        total_width = y1-y0; lane = total_width*(1-recipe['center_gap_fraction'])/2
        require(run > 4*join and lane > 4*join and landing > 2*join, 'Stair footprint cannot contain flights and landings')
        connectors = []; stair_ids = []; stair_guard_ids = []; stair_guard_groups = []; post_registry = {}
        if guard_profile is not None:
            post = guard_profile['post_mm']
            require(post < lane/2 and post < landing and post < total_width-2*lane and post < run/4,
                    'The referenced guard profile cannot fit the stair lanes, landing and centre gap')
            first_y = y0+lane-post/2; return_y = y1-lane+post/2
        top_wall = None
        if 'top_guard_wall' in instance:
            wall_id = instance['top_guard_wall']
            require(wall_id in {ref['wall'] for ref in area['boundary']}
                    and walls[wall_id]['kind'] == 'wall',
                    'The top guard must terminate at an existing stairwell boundary wall')
            a, b = wall_points(wall_id)
            require(abs(a[1]-b[1]) < 1e-7 and abs(a[1]-min(q[1] for q in poly)) < 1e-7,
                    'The top guard wall must bound the unused Ymin flight side')
            face_y = a[1]+thickness/2
            terminal_y = face_y+post/2
            require(terminal_y < first_y and min(a[0], b[0])+post/2 < entry_x+run/n
                    < max(a[0], b[0])-post/2,
                    'The source top guard wall must contain the complete terminal post')
            top_wall = {'wall': wall_id, 'interior_face_y_mm': face_y,
                        'terminal_center_y_mm': terminal_y}
        for lower, upper in zip(levels, levels[1:]):
            name = instance['id']+'_'+lower['id']+'_'+upper['id']; stair_ids.append(body(name, 'concept_continuous_stair', '#8599ac', component=instance['id'])); detail.append(name)
            z0, z1 = lower['z_mm'], upper['z_mm']; mid = (z0+z1)/2; rise = (z1-z0)/2/n; tread = run/n
            for k in range(1, n+1):
                left = entry_x-k*tread
                box(name+'_First_'+str(k), name, [left-join, y0, z0-join], [tread+2*join, lane, k*rise+join], 'create' if k == 1 else 'join')
            box(name+'_MidLanding', name, [x0, y0, mid-slab], [landing+join, total_width, slab], 'join')
            for k in range(1, n+1):
                left = run0+(k-1)*tread
                box(name+'_Return_'+str(k), name, [left-join, y1-lane, mid-join], [tread+2*join, lane, k*rise+join], 'join')
            floor_body = upper['id']+'__Area_'+instance['area']; hole = rectangle(x0, y0, entry_x, y1)
            cut_prism(name+'_SlabCut', floor_body, hole, z1-slab-join, slab+2*join)
            holes.append(probe(name+'_SlabHole', rectangle(x0+join, y0+join, entry_x-join, y1-join), z1-slab+join, slab-2*join, [floor_body]))
            witness_width = lane*.2
            for label, xx, yy, zz, expected_parts in [
                ('Bottom', entry_x+join*.25, y0+lane*.4, z0-join*.75, [(name, 1), (lower['id']+'__Area_'+instance['area'], 1)]),
                ('Mid', run0-join*.5, y1-lane*.6, mid-join*.25, [(name, 1)]),
                ('Top', entry_x+join*.25, y1-lane*.6, z1-join*.75, [(name, 1), (floor_body, 1)])]:
                dx = join*.5 if label != 'Mid' else join
                witness_depth = join*.5; volume = dx*witness_width*witness_depth
                expected = {target: volume*fraction for target, fraction in expected_parts}
                connections.append(probe(name+'_'+label+'_Connection', rectangle(xx, yy, xx+dx, yy+witness_width), zz, witness_depth, list(expected), 'filled', expected))
            connectors.append({'id': name, 'body_id': name, 'from_level': lower['id'], 'to_level': upper['id'], 'z0_mm': z0, 'z1_mm': z1, 'mid_z_mm': mid, 'risers': 2*n, 'run_mm': run, 'lane_width_mm': lane, 'entry_x_mm': entry_x, 'slab_hole_probe_id': name+'_SlabHole'})
            if guard_profile is not None:
                require(tread+post < landing,
                        'The source nosing-line guard extensions cannot fit the stair landings')
                rear_x = run0-tread; front_x = entry_x+tread
                top_termination = top_wall if upper['id'] == levels[-1]['id'] else None
                # Slopes follow the tread nosing line. Horizontal extensions
                # join the landing guards without passing bars through treads.
                # Post support comes from the already generated step boxes,
                # never from a second independently maintained stair formula.
                segments = [
                    ('FirstInner', [front_x, first_y, z0], [run0+tread, first_y, mid]),
                    ('FirstTop', [run0+tread, first_y, mid], [rear_x, first_y, mid]),
                    ('MidGap', [rear_x, first_y, mid], [rear_x, return_y, mid]),
                    ('ReturnInner', [rear_x, return_y, mid], [entry_x-tread, return_y, z1]),
                    ('ReturnTop', [entry_x-tread, return_y, z1], [front_x, return_y, z1]),
                    ('UpperGap', [front_x, return_y, z1],
                     [front_x, top_termination['terminal_center_y_mm'] if top_termination else first_y, z1]),
                ]
                step_boxes = [op['shape'] for op in result['operations']
                              if op['body'] == name and op['action'] in {'create', 'join'}
                              and op['shape']['kind'] == 'box']
                entry_floors = {
                    'FirstInner': (lower['id']+'__Area_'+instance['area'], z0),
                    'ReturnTop': (floor_body, z1), 'UpperGap': (floor_body, z1),
                }

                def contains_xy(shape, point):
                    return all(shape['origin'][i]-1e-7 <= point[i] <=
                               shape['origin'][i]+shape['size'][i]+1e-7 for i in (0, 1))

                def contains_xyz(shape, point):
                    return all(shape['origin'][i]-1e-7 <= point[i] <=
                               shape['origin'][i]+shape['size'][i]+1e-7 for i in (0, 1, 2))

                connector_guards = []
                for kind, start, end in segments:
                    group_id = name+'_Guard_'+kind
                    support_boxes = {name: step_boxes}
                    if kind in entry_floors:
                        floor_id, floor_z = entry_floors[kind]
                        # The final closure reaches beyond the recipe inset,
                        # but stays on the existing source floor at the wall.
                        floor_y = top_termination['interior_face_y_mm'] if kind == 'UpperGap' and top_termination else y0
                        require(inside_rectangle(rectangle(entry_x, floor_y, x1, y1), poly, 0),
                                'The top guard landing support must lie within the existing source floor')
                        support_boxes[floor_id] = [{'origin': [entry_x, floor_y, floor_z-slab],
                            'size': [x1-entry_x, y1-floor_y, slab]}]

                    def support_top(point):
                        tops = []
                        for xx in (point[0]-post/2, point[0]+post/2):
                            for yy in (point[1]-post/2, point[1]+post/2):
                                present = [shape['origin'][2]+shape['size'][2]
                                    for boxes in support_boxes.values() for shape in boxes
                                    if contains_xy(shape, (xx, yy))]
                                require(present, 'The guard post footprint has no source stair or landing support')
                                tops.append(max(present))
                        return min(tops)

                    pieces = guards.compile_segment(guard_profile, group_id, start, end,
                        component=instance['id'], post_registry=post_registry, post_embed_mm=join,
                        post_support_z=support_top)
                    result['bodies'].extend(pieces['bodies']); result['operations'].extend(pieces['operations'])
                    interface = pieces['interface']
                    group = {'id': group_id, 'kind': kind, 'connector_id': name,
                             'from_level': lower['id'], 'to_level': upper['id'],
                             'profile_ref': guard_ref, 'start_mm': list(start), 'end_mm': list(end),
                             'height_basis': 'source_nosing_line_with_horizontal_landing_extensions',
                             'body_ids': list(interface['body_ids']),
                             'post_body_ids': [item['body_id'] for item in interface['posts']]}
                    if kind == 'UpperGap' and top_termination:
                        group['wall_termination'] = {
                            'wall': top_termination['wall'],
                            'wall_body_id': upper['id']+'__Wall_'+top_termination['wall'],
                            'interior_face_y_mm': top_termination['interior_face_y_mm'],
                            'terminal_post_body_id': interface['posts'][-1]['body_id'],
                            'contact': 'flush_concept_geometry_not_structural_attachment'}
                    stair_guard_groups.append(group); guard_groups.append(group)
                    for identifier in interface['body_ids']:
                        if identifier not in connector_guards: connector_guards.append(identifier)
                        if identifier not in stair_guard_ids: stair_guard_ids.append(identifier)
                        if identifier not in guard_ids: guard_ids.append(identifier)
                    for item in interface['posts']:
                        if not item['new']: continue
                        base = item['base_mm']; pitch_z = item['pitchline_mm'][2]
                        width = min(post/4, join); depth = join/2; volume = width*width*depth
                        patch = rectangle(base[0]-width/2, base[1]-width/2,
                                          base[0]+width/2, base[1]+width/2)
                        patch_z = (base[2]+join/4, base[2]+join*.75)
                        sample_points = [[xx, yy, zz] for xx, yy in patch for zz in patch_z]
                        supporting = [body_id for body_id, boxes in support_boxes.items()
                            if all(any(contains_xyz(shape, point) for shape in boxes) for point in sample_points)]
                        require(supporting, 'The embedded guard foot has no complete source support witness')
                        support = supporting[0]
                        identifier = item['body_id']+'_Attachment'
                        witness = probe(identifier, patch, base[2]+join/4, depth,
                            [item['body_id'], support], 'filled', {item['body_id']: volume, support: volume})
                        guard_attachments.append(witness)
                        guard_posts.append({'body_id': item['body_id'], 'base_mm': list(base),
                            'top_mm': list(item['top_mm']), 'reference_pitch_z_mm': pitch_z,
                            'support_z_mm': item['support_z_mm'], 'support_body_id': support,
                            'support_body_ids': [support], 'attachment_probe_id': identifier})
                connectors[-1]['guard_body_ids'] = connector_guards
                connectors[-1]['guard_nosing_extension_mm'] = tread
                first_clear = lane-post; landing_clear = landing-tread-post
                guard_height = guard_profile['height_mm']
                for kind, points, z, height in [
                    ('FirstFlight', rectangle(run0+post, y0+first_clear*.2,
                        entry_x-post, y0+first_clear*.8), z0, mid-z0+guard_height+join),
                    ('ReturnFlight', rectangle(run0+post, y1-first_clear*.8,
                        entry_x-post, y1-first_clear*.2), mid, z1-mid+guard_height+join),
                    ('MidTurnback', rectangle(x0+landing_clear*.2, y0+post,
                        x0+landing_clear*.8, y1-post), mid, guard_height+join),
                    ('EntryLanding', rectangle(entry_x+tread+post+landing_clear*.2, y0+post,
                        entry_x+tread+post+landing_clear*.8, y1-post), z1, guard_height+join),
                ]:
                    item = probe(name+'_GuardClear_'+kind, points, z, height, [])
                    item['scope'] = 'new_guard_members_only'
                    guard_clearances.append(item)
                if lower['id'] == levels[0]['id']:
                    ground_guard_ids.extend(identifier for identifier in connector_guards if identifier not in ground_guard_ids)
        stairs.append({'id': instance['id'], 'component_id': instance['id'], 'area': instance['area'], 'entry_opening': instance['entry_opening'], 'interior_rectangle_mm': rectangle(x0, y0, x1, y1), 'connectors': connectors, 'body_ids': stair_ids, 'entry_landing_preserved': True,
                       'served_extent': copy.deepcopy(source['served_extent']), 'classification': 'internal', 'planned_connectors': [],
                       'guard_profile_ref': guard_ref, 'guard_body_ids': stair_guard_ids, 'guard_groups': stair_guard_groups,
                       'guard_safety_qualified': False})
        detail.extend(stair_guard_ids)
        detail.extend(level['id']+'__Area_'+instance['area'] for level in levels)
    # The external steel illustration reuses the same source footprint/layout
    # ratios, but has thin treads and inclined stringers rather than solid steps.
    ext = source['external_stair']; require(ext['area'] in areas and ext['entry_opening'] in openings, 'Existing external stair source area and entry required')
    ext_poly = polygon(ext['area']); entry = openings[ext['entry_opening']]
    e0, e1 = wall_points(entry['wall'])
    require(entry['kind'] == 'door' and entry['wall'] in {ref['wall'] for ref in areas[ext['area']]['boundary']} and abs(e0[0]-e1[0]) < 1e-7 and abs(e0[0]-max(v[0] for v in ext_poly)) < 1e-7, 'External source entrance must remain on Xmax')
    x0, y0, x1, y1 = interior_rectangle(ext_poly, thickness*recipe['wall_margin_factor'])
    landing = (x1-x0)*recipe['landing_fraction']; run0 = x0+landing; entry_x = x1-landing; run = entry_x-run0
    lane = (y1-y0)*(1-recipe['center_gap_fraction'])/2
    plate, sd, sw, lt = (ext[key] for key in ('tread_thickness_mm', 'stringer_depth_mm', 'stringer_width_mm', 'landing_thickness_mm'))
    require(run > 8*join and 2*sw < lane and plate < sd and lt < slab and sw > 2*join, 'Metal stair assumptions do not fit the source footprint')
    if ground_plan is not None:
        ground_areas = {area['id']: area for area in ground_plan['areas']}
        require(ext['ground_area'] in ground_areas and ext['ground_exit_neighbor'] in ground_areas, 'Explicit owner-traced external ground exit and neighbor required')
        support_area = ground_support_area or ext['ground_exit_neighbor']
        require(support_area in ground_areas, 'Existing external ground support area required')
        ground_neighbor = [[x*scale, y*scale] for x, y in floor.outline(ground_plan, ground_areas[support_area])]
        bottom_probe = rectangle(entry_x+join*.25, y0+sw*.25, entry_x+join*.75, y0+sw*.5)
        require(all(floor.point_membership(point, ground_neighbor) == 1 for point in bottom_probe), 'The source-anchored external lower support must lie inside the actual EG neighbor floor')
    ext_component = ext['id']; result['components'].append({'id': ext_component, 'grounded': True})
    roof_level = {'id': 'ROOF', 'z_mm': levels[-1]['clear_top_mm']+slab}
    stops = [*[level for level in levels if level['id'] != 'KG'], roof_level]; metal_landings = []; ext_connectors = []; ext_ids = []; access_checks = []
    entry_ylo, entry_yhi = sorted(e0[1]+fraction*(e1[1]-e0[1]) for fraction in entry['interval'])
    access_margin = min(thickness*.1, (entry_yhi-entry_ylo)*.1)
    access_ylo, access_yhi = entry_ylo+access_margin, entry_yhi-access_margin
    require(y0 < access_ylo < access_yhi < y1, 'External source door must meet the inset entry landing')
    access_areas = [area for area in plan['areas'] if area['id'] != ext['area'] and any(ref['wall'] == entry['wall'] for ref in area['boundary'])]
    require(len(access_areas) == 1 and access_areas[0]['kind'] in {'room', 'corridor'}, 'External upper entry needs one explicit adjacent building floor')
    access_area = access_areas[0]['id']; wall_x = e0[0]
    for level in stops:
        name = ext_component+'_Entry_'+level['id']
        metal_landings.append(body(name, 'concept_external_stair_landing', '#7f898e', component=ext_component)); ext_ids.append(name); detail.append(name)
        # At EG only the outgoing lane needs a base; it remains over the actual
        # owner-traced room22 ground floor. Upper platforms connect both lanes.
        ymax = y0+lane if level['id'] == 'EG' else y1
        box(name+'_Plate', name, [entry_x, y0, level['z_mm']-lt], [x1-entry_x, ymax-y0, lt])
        if level['id'] != 'EG':
            box(name+'_DoorBridge', name, [x1-join, access_ylo, level['z_mm']-lt], [wall_x+2*join-(x1-join), access_yhi-access_ylo, lt], 'join')
            target = ('RoofSlab_' if level['id'] == 'ROOF' else level['id']+'__Area_')+access_area
            witness_points = rectangle(wall_x+join*.25, access_ylo+join, wall_x+join*.75, access_yhi-join)
            witness_h = min(lt, slab)*.25; volume = floor.signed_area(witness_points)*witness_h
            access_checks.append(probe(name+'_BuildingContact', witness_points, level['z_mm']-min(lt,slab)*.75, witness_h, [name,target], 'filled', {name:volume,target:volume}))
    def stringer(name, target, points, yy, action):
        result['operations'].append({'id': name, 'body': target, 'action': action, 'shape': {'kind': 'polygon_prism', 'plane': 'XZ', 'points': points, 'offset': yy, 'depth': sw, 'fixed': True}})
    for index, (lower, upper) in enumerate(zip(stops, stops[1:])):
        name = ext_component+'_'+lower['id']+'_'+upper['id']; ext_ids.append(body(name, 'concept_external_metal_stair', '#737e85', component=ext_component)); detail.append(name)
        z0, z1 = lower['z_mm'], upper['z_mm']; mid = (z0+z1)/2; rise = (z1-z0)/2/n; tread = run/n
        require(plate < rise and sd < (z1-z0)/2, 'Metal members exceed the assumed storey rise')
        # Inclined upper edges intersect each thin tread over a small positive
        # area. Successive native union steps always meet prior solid material.
        first = [[run0-join, mid-sd], [entry_x+join, z0-sd], [entry_x+join, z0+join], [run0-join, mid+join]]
        stringer(name+'_FirstOuter', name, first, y0, 'create')
        box(name+'_FirstTread_1', name, [entry_x-tread-join, y0, z0+rise-plate], [tread+2*join, lane, plate], 'join')
        stringer(name+'_FirstInner', name, first, y0+lane-sw, 'join')
        for k in range(2, n+1):
            box(name+'_FirstTread_'+str(k), name, [entry_x-k*tread-join, y0, z0+k*rise-plate], [tread+2*join, lane, plate], 'join')
        box(name+'_MidLanding', name, [x0, y0, mid-lt], [landing+join, y1-y0, lt], 'join')
        second = [[run0-join, mid-sd], [entry_x+join, z1-sd], [entry_x+join, z1+join], [run0-join, mid+join]]
        stringer(name+'_ReturnInner', name, second, y1-lane, 'join')
        box(name+'_ReturnTread_1', name, [run0-join, y1-lane, mid+rise-plate], [tread+2*join, lane, plate], 'join')
        stringer(name+'_ReturnOuter', name, second, y1-sw, 'join')
        for k in range(2, n+1):
            box(name+'_ReturnTread_'+str(k), name, [run0+(k-1)*tread-join, y1-lane, mid+k*rise-plate], [tread+2*join, lane, plate], 'join')
        for label, xx, yy, zz, targets in [
            ('Bottom', entry_x+join*.25, y0+sw*.25, z0-join*.75, [name, metal_landings[index]]),
            ('Mid', run0-join*.5, y1-lane+sw*.25, mid-join*.75, [name]),
            ('Top', entry_x+join*.25, y1-sw*.75, z1-join*.75, [name, metal_landings[index+1]])]:
            dx = join*.5; dy = sw*.25; height = join*.5; volume = dx*dy*height
            if index == 0 and label == 'Bottom' and ground_plan is not None:
                targets.append('EG__Area_'+support_area)
            item = probe(name+'_'+label+'_Connection', rectangle(xx, yy, xx+dx, yy+dy), zz, height, targets, 'filled', {target: volume for target in targets})
            item['system'] = 'external_metal'; connections.append(item)
        ext_connectors.append({'id': name, 'body_id': name, 'from_level': lower['id'], 'to_level': upper['id'], 'z0_mm': z0, 'z1_mm': z1, 'mid_z_mm': mid, 'risers': 2*n, 'run_mm': run, 'lane_width_mm': lane, 'entry_x_mm': entry_x, 'slab_hole_probe_id': None})
    external = {'id': ext_component, 'component_id': ext_component, 'classification': 'external_metal', 'area': ext['area'], 'entry_opening': ext['entry_opening'], 'body_ids': ext_ids, 'landing_body_ids': metal_landings,
                'interior_rectangle_mm': rectangle(x0, y0, x1, y1), 'connectors': ext_connectors, 'served_extent': {'from_level': 'EG', 'to_level': 'ROOF'}, 'planned_connectors': [],
                'access_floor_area': access_area, 'ground_exit': {'area': ext['ground_area'], 'neighbor_area': ext['ground_exit_neighbor'], 'alignment': 'schematic_source_anchored_not_measured'}, 'metal_dimensions_mm': {key: ext[key] for key in ('tread_thickness_mm', 'stringer_depth_mm', 'stringer_width_mm', 'landing_thickness_mm')}}
    for lower, upper in zip(levels, levels[1:]):
        for wall_id in sorted(boundary_ids):
            wall = walls[wall_id]
            if wall['kind'] != 'wall': continue
            a, b = wall_points(wall_id); dx, dy = b[0]-a[0], b[1]-a[1]; length = math.hypot(dx, dy); nx, ny = -dy/length*thickness/2, dx/length*thickness/2
            points = [[a[0]+nx,a[1]+ny],[b[0]+nx,b[1]+ny],[b[0]-nx,b[1]-ny],[a[0]-nx,a[1]-ny]]
            name = 'WallBridge_'+lower['id']+'_'+wall_id; bridges.append(body(name, 'circulation_wall_bridge', '#a0b5bf', .7, component=boundary_owners[wall_id]))
            result['operations'].append({'id': name+'_Profile', 'body': name, 'action': 'create', 'shape': {'kind': 'polygon_prism', 'plane': 'XY', 'points': points, 'offset': lower['clear_top_mm'], 'depth': upper['z_mm']-lower['clear_top_mm'], 'fixed': True}})
    for item in guard_clearances:
        item['target_bodies'] = list(guard_ids)
    result['interface'] = {'elevator': {'id': lift['id'], 'component_id': lift['id'], 'served_extent': copy.deepcopy(source['served_extent']), 'area': lift['area'], 'shaft_body_ids': shaft_ids, 'cabin_body_ids': [cabin], 'door_frame_body_ids': door_frames, 'sides': copy.deepcopy(lift['sides']), 'ports': ports, 'doors_by_level': doors_by_level, 'deferred_stops': copy.deepcopy(lift['deferred_stops']), 'cabin_level': lift['cabin_level'], 'operation_implemented': False},
        'stairs': stairs, 'external_stairs': [external], 'body_ids': [b['id'] for b in result['bodies']], 'wall_bridge_ids': bridges, 'detail_visibility_ids': detail,
        'served_extent': copy.deepcopy(source['served_extent']),
        'slab_hole_probes': holes, 'door_probes': door_probes, 'closed_door_probes': closed, 'connection_witnesses': connections, 'shaft_witnesses': shaft_checks, 'external_access_witnesses': access_checks,
        'guard_profile_ref': guard_ref, 'guard_body_ids': guard_ids, 'guard_groups': guard_groups,
        'guard_posts': guard_posts, 'guard_attachment_witnesses': guard_attachments,
        'guard_clearance_probes': guard_clearances, 'guard_safety_qualified': False,
        'ground_visibility_ids': [cabin]+[port['frame_body_id'] for port in ports if port['level_id'] == 'EG' and port['frame_body_id']]+[stair['connectors'][0]['body_id'] for stair in stairs]+[ext_connectors[0]['body_id'], metal_landings[0]]+ground_guard_ids,
        'basement_geometry_implemented': True, 'headroom_qualified': False, 'egress_qualified': False, 'limitations': list(source['limitations'])}
    if fittings:
        result['interface']['elevator']['fittings'] = {key: fittings[key] for key in ('door_groups', 'attached_body_ids', 'placements')}
        result['interface']['ground_visibility_ids'].extend(fittings['attached_body_ids'])
        result['interface']['ground_visibility_ids'].extend(body for group in fittings['door_groups']
            if group['parent'] == 'cabin' or any(port['id'] == group['port_id'] and port['level_id'] == lift['cabin_level'] for port in ports)
            for body in group['moving_body_ids'])
    return result
