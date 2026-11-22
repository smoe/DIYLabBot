"""Derive individually outward-opening seminar glazing from retained wall edges.

Native geometry is the closed reference. Browser hinges are interfaces of those
same bodies; dimensions and handing remain unmeasured presentation assumptions.
"""
import math
import re

import building_roof as roof
import relative_floorplan as floor
import wall_worktops


FIELDS = {'id', 'area', 'wall_ids', 'sill_mm', 'head_mm', 'jamb_mm', 'mullion_mm',
          'max_sash_width_mm', 'frame_mm', 'sash_depth_mm', 'glass_mm',
          'open_angle_deg', 'basis'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(config):
    require(isinstance(config, dict) and set(config) == FIELDS, 'Explicit seminar window-front fields required')
    for name in ('id', 'area', 'basis'):
        require(isinstance(config[name], str) and bool(config[name].strip()), 'Nonempty seminar window '+name+' required')
    names = config['wall_ids']
    require(isinstance(names, list) and bool(names) and all(isinstance(n, str) and n for n in names)
            and len(set(names)) == len(names), 'Unique seminar window facade wall IDs required')
    for name in FIELDS-{'id', 'area', 'wall_ids', 'basis'}:
        value = config[name]
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                'Positive finite seminar window dimension required: '+name)
    require(config['head_mm'] > config['sill_mm']+4*config['frame_mm'], 'Seminar window band has no glazed height')
    require(config['max_sash_width_mm'] > 4*config['frame_mm'], 'Seminar window subdivision has no glazed width')
    require(config['glass_mm'] < config['sash_depth_mm'] and config['open_angle_deg'] < 90,
            'Seminar window glass/opening assumptions are incompatible')
    return config


def point_segment_distance(point, a, b):
    delta = [b[i]-a[i] for i in (0, 1)]
    denominator = sum(v*v for v in delta)
    require(denominator > 0, 'Degenerate seminar room wall')
    fraction = max(0, min(1, sum((point[i]-a[i])*delta[i] for i in (0, 1))/denominator))
    return math.dist(point[:2], [a[i]+fraction*delta[i] for i in (0, 1)])


def selected_edges(config, plan, area):
    """Include registration-created segments while preserving boundary order."""
    bases = config['wall_ids']
    belongs = lambda name: any(name == base or re.fullmatch(re.escape(base)+r'_Align[1-9][0-9]*', name) for base in bases)
    boundary = area['boundary']; selected = [edge for edge in boundary if belongs(edge['wall'])]
    require(all(any(edge['wall'] == base for edge in selected) for base in bases), 'Seminar facade wall missing from its source room')
    require(len({e['wall'] for e in selected}) == len(selected), 'Repeated seminar facade wall')
    # Rotate at the beginning of the one connected run, independently of room
    # winding and of the source graph's arbitrary first boundary reference.
    starts = [i for i, edge in enumerate(boundary) if belongs(edge['wall']) and not belongs(boundary[i-1]['wall'])]
    require(len(starts) == 1, 'Seminar glazing must use one contiguous facade chain')
    ordered = boundary[starts[0]:]+boundary[:starts[0]]
    selected = ordered[:len(selected)]
    require(all(belongs(e['wall']) for e in selected), 'Seminar facade chain has an omitted intervening wall')
    exterior = {edge['wall'] for edge in roof.outer_contour(plan,
        [a for a in plan['areas'] if a['kind'] != 'void' and a['id'] not in {'R3_017', 'ExternalStairGround', 'ExternalLink'}])}
    require({e['wall'] for e in selected} <= exterior, 'Seminar windows must cut actual exterior room walls')
    return selected


def compile(config, plan, p, level):
    config = validate(config)
    if 'EG' in plan:
        plan = plan['EG']
    require(level['id'] == 'EG', 'Seminar window frontage belongs to EG')
    area = next((a for a in plan['areas'] if a['id'] == config['area']), None)
    require(area is not None, 'Seminar window source room is missing')
    edges = selected_edges(config, plan, area)
    walls = {wall['id']: wall for wall in plan['walls']}
    require(all(walls[e['wall']]['kind'] == 'wall' for e in edges), 'Seminar window cuts require retained physical walls')
    require(not any(o['wall'] in {e['wall'] for e in edges} for o in plan['openings']),
            'Seminar window band cannot replace an existing source opening')
    scale, thickness = p['display_scale'], p['display_thickness']
    require(type(scale) in (int, float) and math.isfinite(scale) and scale > 0
            and type(thickness) in (int, float) and math.isfinite(thickness) and thickness > 0,
            'Finite positive seminar window presentation scale/thickness required')
    z0 = level['z_mm']; ceiling = level['clear_top_mm']
    require(z0+config['head_mm'] < ceiling, 'Seminar window head leaves its actual storey')
    polygon = [[v*scale for v in xy] for xy in floor.outline(plan, area)]
    frames = []
    for edge in edges:
        wall = walls[edge['wall']]
        start = wall['start' if edge['direction'] == 1 else 'end']
        end = wall['end' if edge['direction'] == 1 else 'start']
        a, b = [[v*scale for v in plan['vertices'][name]] for name in (start, end)]
        length = math.dist(a, b)
        require(length > 0, 'Seminar facade has a zero-length registered segment')
        _, _, inward, _ = wall_worktops.wall_frame(plan, area, edge['wall'], p)
        frames.append({'wall_id': edge['wall'], 'a': a, 'b': b, 'length': length,
                       'tangent': [(b[i]-a[i])/length for i in (0, 1)], 'outward': [-v for v in inward]})
    require(all(math.dist(a['b'], b['a']) < 1e-6 for a, b in zip(frames, frames[1:])), 'Seminar facade chain is disconnected')
    total = sum(f['length'] for f in frames)
    require(total > 2*config['jamb_mm']+4*config['frame_mm'], 'Seminar window facade has no usable band')
    result = {'components': [], 'bodies': [], 'operations': [], 'window_probes': []}
    sashes, segments = [], []
    prefix, frame = config['id'], config['frame_mm']
    bottom, head = z0+config['sill_mm'], z0+config['head_mm']
    fit_gap = min(config['glass_mm']/2, frame/10)
    band_station = 0
    def component(name):
        result['components'].append({'id': name, 'grounded': True})
        return name
    fixed_component = component(prefix+'_FixedFrames')
    def body(name, component_id, role, color, opacity=1):
        identity = prefix+'_'+name
        result['bodies'].append({'id': identity, 'component': component_id, 'level_id': level['id'],
            'room_id': config['area'], 'role': role, 'appearance': {'color': color, 'opacity': opacity}})
        return identity
    def prism(identity, body_id, section, x0, x1, y0, y1, low, high, action='create'):
        a, tangent, outward = section['a'], section['tangent'], section['outward']
        xy = [[a[i]+tangent[i]*x+outward[i]*y for i in (0, 1)]
              for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        result['operations'].append({'id': identity, 'body': body_id, 'action': action,
            'shape': {'kind': 'polygon_prism', 'plane': 'XY', 'points': xy,
                      'offset': low, 'depth': high-low, 'fixed': True}})
        return xy
    for section in frames:
        length = section['length']; end_station = band_station+length
        lo = max(0, config['jamb_mm']-band_station, config['mullion_mm']/2 if band_station > 0 else 0)
        hi = min(length, total-config['jamb_mm']-band_station,
                 length-config['mullion_mm']/2 if end_station < total-1e-7 else length)
        intervals = []
        if hi-lo <= 4*frame+2*fit_gap:
            intervals.append({'kind': 'transition_mullion', 'interval_mm': [0, length]})
        else:
            intervals.append({'kind': 'end_jamb' if band_station == 0 else 'mullion', 'interval_mm': [0, lo]})
            count = math.ceil((hi-lo+config['mullion_mm'])/(config['max_sash_width_mm']+config['mullion_mm']))
            width = (hi-lo-(count-1)*config['mullion_mm'])/count
            require(width > 4*frame+2*fit_gap, 'Seminar sash subdivision removes its glazing')
            for index in range(count):
                left = lo+index*(width+config['mullion_mm']); right = left+width
                identity = prefix+'_Sash'+str(len(sashes)+1).zfill(2)
                target = level['id']+'__Wall_'+section['wall_id']
                cut = prism(identity+'_WallCut', target, section, left, right, -thickness*.7, thickness*.7, bottom, head, 'cut')
                fixed = body(identity[len(prefix)+1:]+'_Frame', fixed_component, 'concept_seminar_window_frame', '#c2c6c9')
                prism(fixed+'_Outer', fixed, section, left, right, thickness/2-config['sash_depth_mm'], thickness/2, bottom, head)
                prism(fixed+'_Inner', fixed, section, left+frame, right-frame,
                      thickness/2-config['sash_depth_mm']-1, thickness/2+1, bottom+frame, head-frame, 'cut')
                moving = component(identity+'_Moving')
                sash = body(identity[len(prefix)+1:]+'_SashFrame', moving, 'concept_seminar_window_sash', '#c2c6c9')
                x0, x1 = left+frame+fit_gap, right-frame-fit_gap
                y0, y1 = thickness/2+fit_gap, thickness/2+fit_gap+config['sash_depth_mm']
                zlow, zhigh = bottom+frame+fit_gap, head-frame-fit_gap
                prism(sash+'_Outer', sash, section, x0, x1, y0, y1, zlow, zhigh)
                prism(sash+'_Inner', sash, section, x0+frame, x1-frame, y0-1, y1+1, zlow+frame, zhigh-frame, 'cut')
                glass = body(identity[len(prefix)+1:]+'_Glass', moving, 'concept_seminar_window_glass', '#a9d4e4', .28)
                glass_x0, glass_x1 = x0+frame+fit_gap, x1-frame-fit_gap
                glass_z0, glass_z1 = zlow+frame+fit_gap, zhigh-frame-fit_gap
                require(glass_x0 < glass_x1 and glass_z0 < glass_z1, 'Seminar sash has no positive pane')
                prism(glass+'_Pane', glass, section, glass_x0, glass_x1,
                      (y0+y1-config['glass_mm'])/2, (y0+y1+config['glass_mm'])/2, glass_z0, glass_z1)
                handle = body(identity[len(prefix)+1:]+'_Handle', moving, 'concept_seminar_window_handle', '#424b51')
                handle_width = min(12, frame/2)
                handle_height = min(100, (zhigh-zlow)/5)
                prism(handle+'_Grip', handle, section, x1-frame/2-handle_width/2, x1-frame/2+handle_width/2,
                      y0-min(12, config['sash_depth_mm']/4), y0,
                      (zlow+zhigh-handle_height)/2, (zlow+zhigh+handle_height)/2)
                def point(x, y, z):
                    return [section['a'][i]+section['tangent'][i]*x+section['outward'][i]*y for i in (0, 1)]+[z]
                target_point = point((left+right)/2, (y0+y1)/2, (bottom+head)/2)
                eye = None
                for distance in (300, 450, 650, 900, 1200):
                    for lateral in (0, -width*.2, width*.2):
                        candidate = point((left+right)/2+lateral, -thickness/2-distance, z0+1600)
                        gap = min(point_segment_distance(candidate, a, b) for a, b in zip(polygon, polygon[1:]+polygon[:1]))-thickness/2
                        if floor.point_membership(candidate[:2], polygon) == 1 and gap >= 160:
                            eye = candidate; eye_gap = gap; break
                    if eye is not None:
                        break
                require(eye is not None, 'Seminar sash has no viewpoint inside the inset source room')
                sign = 1 if section['tangent'][0]*section['outward'][1]-section['tangent'][1]*section['outward'][0] > 0 else -1
                sashes.append({'id': identity, 'label': 'Fenster '+str(len(sashes)+1), 'wall_id': section['wall_id'],
                    'target_wall_body_id': target, 'fixed_frame_body_id': fixed, 'moving_body_ids': [sash, glass, handle],
                    'glass_body_id': glass, 'sash_frame_body_id': sash, 'origin_mm': point(x0, y1, zlow),
                    'handle_body_id': handle,
                    'axis': [0, 0, 1], 'angle_deg': sign*config['open_angle_deg'], 'reference_angle_deg': 0,
                    'closed_angle_deg': 0, 'tangent': section['tangent']+[0], 'outward': section['outward']+[0],
                    'aperture_interval_mm': [left, right], 'aperture_z_mm': [bottom, head],
                    'closed_sash_bounds_local_mm': {'x': [x0, x1], 'y': [y0, y1], 'z': [zlow, zhigh]},
                    'frame_outward_plane_mm': thickness/2, 'hinge_clearance_mm': fit_gap,
                    'viewpoint': {'eye_mm': eye, 'target_mm': target_point}, 'viewpoint_wall_clearance_mm': eye_gap})
                inset = min(frame/4, width/10)
                probe_xy = [[section['a'][j]+section['tangent'][j]*x+section['outward'][j]*y for j in (0, 1)]
                            for x, y in ((left+inset, -thickness*.4), (right-inset, -thickness*.4),
                                         (right-inset, thickness*.4), (left+inset, thickness*.4))]
                result['window_probes'].append({'id': identity+'_Aperture', 'target_body': target,
                    'kind': 'polygon_prism', 'points_mm': probe_xy, 'offset_mm': bottom+inset,
                    'depth_mm': head-bottom-2*inset, 'display_inset_mm': inset, 'visualization_only': True})
                intervals.append({'kind': 'sash_aperture', 'interval_mm': [left, right], 'sash_id': identity})
                if index < count-1:
                    intervals.append({'kind': 'mullion', 'interval_mm': [right, right+config['mullion_mm']]})
            intervals.append({'kind': 'end_jamb' if abs(end_station-total) < 1e-7 else 'mullion', 'interval_mm': [hi, length]})
        segments.append({'wall_id': section['wall_id'], 'target_wall_body_id': level['id']+'__Wall_'+section['wall_id'],
            'length_mm': length, 'band_interval_mm': [band_station, end_station], 'coverage': intervals})
        band_station = end_station
    require(bool(sashes), 'Seminar facade produced no opening sashes')
    result['interface'] = {'id': prefix, 'level_id': level['id'], 'area_id': config['area'],
        'source_wall_ids': list(config['wall_ids']), 'effective_wall_ids': [e['wall'] for e in edges],
        'body_ids': [b['id'] for b in result['bodies']], 'sashes': sashes, 'segments': segments,
        'band_length_mm': total, 'z_bounds_mm': [bottom, head], 'native_reference': 'closed',
        'room_boundary_polygon_mm': polygon, 'dimensions_measured': False, 'hardware_qualified': False,
        'sweep_collision_qualified': False, 'weather_sealing_qualified': False,
        'basis': config['basis'], 'scope': 'One outward opening per pane; native closed reference and source-derived browser hinges. Full sweep versus neighboring building equipment is not qualified.'}
    return result
