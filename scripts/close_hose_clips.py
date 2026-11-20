"""Portable, source-derived split clips for the SP02 close-arm hose variant.

These clearance-fit printed clamps are conceptual. Their native rigid attachment
does not prove elastic closure, axial retention, fastener strength or print fit.
No robot geometry or hole pattern is copied into this helper.
"""
import math

import robot_spec as robot


STATIONS = ('j3_parent', 'j3_child', 'j4_parent', 'j4_child',
            'j5_parent', 'j5_child', 'j6_parent')


def expanded(arm, p, stations):
    """Return portable parts, host-link mounts and local fit interfaces.

    A station names its existing source host and a small mount recipe. All
    dimensions of that host are resolved from the leading robot recipe.
    """
    if not isinstance(stations, dict) or set(stations) != set(STATIONS):
        raise ValueError('All seven close-hose support stations are required')
    ap = robot.parameters(arm);values = {**ap, **p}
    val = lambda v: robot.evaluate(v, values)
    vec = lambda v: [val(x) for x in v]
    required = ('hoseOuterRadius', 'hoseClipLength', 'clipHoseGap', 'clipWall', 'mountGap', 'mountWall')
    if any(type(p.get(k)) not in (int, float) or not math.isfinite(p[k]) or p[k] <= 0 for k in required):
        raise ValueError('Positive finite clip and mount dimensions are required')
    if not .6 <= p['clipWall'] <= 3 or not .6 <= p['mountWall'] <= 3:
        raise ValueError('Concept clip walls must remain within the declared .6–3 mm design range')
    hosts = {}
    for link in robot.expanded(arm)['links']:
        for operation in link['recipe']:
            if operation['action'] == 'create':
                hosts[operation['body']] = (link['id'], operation['primitive'])
    result = {'components': [], 'bodies': [], 'operations': [], 'mounts': {}, 'support_interfaces': {}}

    def box(origin, size):
        if min(size) <= 0:raise ValueError('A clip bridge has a nonpositive extent')
        return {'kind': 'box', 'origin': origin, 'size': size}

    def cylinder(center, radius, height, axis=(0, 0, 1)):
        return {'kind': 'cylinder', 'origin': [c-a*height/2 for c, a in zip(center, axis)],
                'radius': radius, 'height': height, 'axis': list(axis)}

    body_ids = set()
    for name in STATIONS:
        station = stations[name]
        required_fields = {'link', 'body_id', 'host_body', 'center_mm', 'tangent', 'x_axis', 'mount'}
        if not isinstance(station, dict) or set(station) != required_fields:
            raise ValueError('Every clip station needs a complete source frame and mount recipe: '+name)
        if station['host_body'] not in hosts or hosts[station['host_body']][0] != station['link']:
            raise ValueError('Clip host is absent from its declared robot link: '+name)
        center, tangent, x_axis = map(vec, (station['center_mm'], station['tangent'], station['x_axis']))
        if (abs(sum(v*v for v in tangent)-1) > 1e-9 or abs(sum(v*v for v in x_axis)-1) > 1e-9
                or abs(sum(a*b for a, b in zip(tangent, x_axis))) > 1e-9
                or abs(abs(tangent[2])-1) > 1e-9 or max(abs(v) for v in tangent[:2]) > 1e-9):
            raise ValueError('This source-derived clip recipe requires an orthonormal, axial ±Z groove: '+name)
        source = hosts[station['host_body']][1]
        kind = station['mount'].get('kind')
        if set(station['mount'])-{'kind', 'band_center_z_mm'}:
            raise ValueError('Unknown clip mount recipe field')
        body = station['body_id'];component = 'CloseHose_'+name
        if not isinstance(body, str) or not body or body in hosts or body in body_ids:
            raise ValueError('Clip body IDs must be new and nonempty')
        body_ids.add(body)
        result['components'].append({'id': component, 'grounded': True})
        result['bodies'].append({'id': body, 'component': component, 'role': 'assumed_split_hose_clip',
                                'appearance': {'color': '#397d9c', 'opacity': 1}})
        result['mounts'][component] = {'link': station['link'], 'zero_transform': robot.identity()}
        solids, cuts = [], []
        host_fit = {'body': station['host_body'], 'radial_or_face_gap_mm': p['mountGap'],
                    'retention': 'Assumed closure of a clearance-fit split clamp; force and axial retention unqualified'}
        slit_direction = (0, 1)
        if kind in ('plate_edge', 'root_edge'):
            if source['kind'] != 'box':raise ValueError('An edge clamp requires a source box host')
            origin, size = vec(source['origin']), vec(source['size']);end = [a+b for a, b in zip(origin, size)]
            g, w = p['mountGap'], p['mountWall'];height = 6.
            if kind == 'plate_edge':
                z = center[2]-4
                # U section opens toward +X around the existing negative-X edge.
                solids.append(box([origin[0]-w-g, origin[1]-w-g, z-height/2],
                                  [4+w+g, size[1]+2*(w+g), height]))
                cuts.append(box([origin[0]-g, origin[1]-g, z-height/2-.1],
                                [5+w+g, size[1]+2*g, height+.2]))
                beam_start = origin[0]+1
                solids.append(box([beam_start, center[1]-1.5, center[2]-5],
                                  [center[0]-beam_start,
                                   origin[1]-g-w/2-(center[1]-1.5), 6]))
                slit_direction = (1, 0)
            else:
                z = center[2]
                # Root-edge U section; move outboard before crossing parent plate Y.
                solids.append(box([end[0]-3, origin[1]-w-g, z-height/2],
                                  [3+w+g, size[1]+2*(w+g), height]))
                cuts.append(box([end[0]-4, origin[1]-g, z-height/2-.1],
                                [4+g, size[1]+2*g, height+.2]))
                solids.append(box([end[0]+w/2, -20, z-3],
                                  [center[0]+2-end[0]-w/2, 6, 6]))
                solids.append(box([center[0]-2, center[1], z-3], [4, -17-center[1], 6]))
                slit_direction = (0, -1)
            host_fit.update(kind='box_edge', origin_mm=origin, size_mm=size,
                            source_edge='negative_x' if kind == 'plate_edge' else 'positive_x')
        elif kind in ('post_collar', 'tube_band'):
            if source['kind'] != 'cylinder' or vec(source.get('axis', [0, 0, 1])) != [0, 0, 1]:
                raise ValueError('A collar requires an existing +Z cylinder host')
            host_center = vec(source['origin']);radius = val(source['radius'])
            host_center[2] = val(station['mount'].get('band_center_z_mm', center[2]))
            low, high = vec(source['origin'])[2], vec(source['origin'])[2]+val(source.get('length', source.get('height')))
            if not low+3 < host_center[2] < high-3:
                raise ValueError('The clamp extends beyond its actual source host')
            inner, outer = radius+p['mountGap'], radius+p['mountGap']+p['mountWall']
            solids.append(cylinder(host_center, outer, 6))
            # Extended bore cuts all bridges as well; no hidden host penetration.
            cuts.append(cylinder(host_center, inner, 2*abs(center[2]-host_center[2])+6.2))
            delta = [center[i]-host_center[i] for i in (0, 1)]
            if abs(delta[0]) > 1e-9 and abs(delta[1]) > 1e-9:
                # J5 band: fixed positive-Y rail outside the yoke bridge.
                solids.append(box([center[0]-1.5, host_center[1]+radius-4, host_center[2]-3],
                                  [3, center[1]-host_center[1]-radius+4, 6]))
                rail_width = 2*p['mountWall']+p['clipWall']
                rail_far_y = center[1]-p['hoseOuterRadius']-p['clipWall']/2
                solids.append(box([center[0]-rail_width/2, rail_far_y-rail_width, host_center[2]],
                                  [rail_width, rail_width, center[2]-host_center[2]]))
            elif abs(delta[1]) > 1e-9:
                solids.append(box([center[0]-1.5, min(center[1], host_center[1]), host_center[2]-3],
                                  [3, abs(delta[1]), 6]))
            elif abs(delta[0]) > 1e-9:
                solids.append(box([min(center[0], host_center[0]), center[1]-1.5, host_center[2]-3],
                                  [abs(delta[0]), 3, 6]))
            else:raise ValueError('A hose seat cannot coincide with its host axis')
            if abs(delta[0]) > abs(delta[1]):
                slit_direction = (-1 if delta[0] < 0 else 1, 0)
            else:slit_direction = (0, -1 if delta[1] < 0 else 1)
            # Open host collar opposite its bridge. A physical split is visible.
            if slit_direction[0]:
                sign = -slit_direction[0]
                cuts.append(box([host_center[0] if sign > 0 else host_center[0]-outer-.1,
                                 host_center[1]-.3, host_center[2]-3.1], [outer+.1, .6, 6.2]))
            else:
                sign = -slit_direction[1]
                cuts.append(box([host_center[0]-.3,
                                 host_center[1] if sign > 0 else host_center[1]-outer-.1,
                                 host_center[2]-3.1], [.6, outer+.1, 6.2]))
            host_fit.update(kind='cylinder', center_mm=host_center, axis=[0, 0, 1],
                            source_radius_mm=radius, bore_radius_mm=inner, outer_radius_mm=outer,
                            physical_support_length_mm=6, source_span_mm=[low, high])
        else:raise ValueError('Unknown close-hose mount recipe: '+str(kind))
        bore = p['hoseOuterRadius']+p['clipHoseGap'];outer = bore+p['clipWall']
        solids.append(cylinder(center, outer, p['hoseClipLength'], tangent))
        cuts.append(cylinder(center, bore, p['hoseClipLength']+.2, tangent))
        # Groove opening points away from its supporting beam.
        if slit_direction[0]:
            sign = slit_direction[0]
            cuts.append(box([center[0] if sign > 0 else center[0]-outer-.1,
                             center[1]-.3, center[2]-p['hoseClipLength']/2-.1], [outer+.1, .6, p['hoseClipLength']+.2]))
        else:
            sign = slit_direction[1]
            cuts.append(box([center[0]-.3, center[1] if sign > 0 else center[1]-outer-.1,
                             center[2]-p['hoseClipLength']/2-.1], [.6, outer+.1, p['hoseClipLength']+.2]))
        for index, primitive in enumerate(solids+cuts):
            result['operations'].append({'id': body+'_Feature'+str(index), 'body': body,
                'action': 'create' if index == 0 else 'join' if index < len(solids) else 'cut', 'shape': primitive})
        result['support_interfaces'][name] = {'clip_body': body, 'component': component,
            'link': station['link'], 'host_body': station['host_body'], 'mount_kind': kind,
            'center_mm': center, 'axis': tangent, 'x_axis': x_axis,
            'physical_support_length_mm': p['hoseClipLength'], 'tube_outer_radius_mm': p['hoseOuterRadius'],
            'bore_radius_mm': bore, 'radial_clearance_mm': p['clipHoseGap'],
            'host_fit': host_fit, 'split_width_mm': .6, 'slot_direction_xy': list(slit_direction),
            'qualification': {'retention_verified': False, 'strength_verified': False, 'manufacturing_fit_verified': False}}
    return result
