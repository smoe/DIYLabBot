"""Source-bound static foyer displays; shared native geometry, no camera runtime."""
import copy
import math
from pathlib import Path

import building_furnishings as furniture
import relative_floorplan as floor
import wall_worktops
import microscope_model as bounds

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/'model/foyer-monitor-wall.schema.json'


def dependencies(ref):
    source = furniture.read(ref)
    return [ROOT/ref['source'], ROOT/source['catalog']['source'], SCHEMA,
            Path(__file__), ROOT/'scripts/building_furnishings.py',
            ROOT/'scripts/wall_worktops.py', ROOT/'scripts/microscope_model.py']


def exact(value, fields, where):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError('Invalid '+where+' fields')


def number(value, minimum, maximum, where):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('Invalid '+where)
    return value


def monitor_count(rows, columns):
    if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
        raise ValueError('Monitor grid dimensions must be positive integers')
    return rows*columns


def validate(source):
    exact(source, 'format id level area catalog monitor_type anchor grid basis', 'monitor source')
    if (source['format'] != 'solidcraftbot.foyer-monitor-wall/1'
            or source['id'] != 'FoyerMonitorWall' or source['level'] != 'EG'
            or source['area'] != 'R0_019' or not isinstance(source['basis'], str) or not source['basis']):
        raise ValueError('Explicit owner-selected foyer binding required')
    exact(source['anchor'], 'wall fraction back_gap_mm', 'monitor anchor')
    anchor = source['anchor']
    if anchor['wall'] != 'W052':
        raise ValueError('Foyer monitors require their owner-selected closed wall')
    number(anchor['fraction'], 0, 1, 'wall fraction')
    number(anchor['back_gap_mm'], 1, 100, 'monitor wall gap')
    grid = source['grid']
    exact(grid, 'rows columns horizontal_gap_mm vertical_gap_mm case_bottom_mm', 'monitor grid')
    monitor_count(grid['rows'], grid['columns'])
    for field in ('horizontal_gap_mm', 'vertical_gap_mm'):
        number(grid[field], 1, 200, 'monitor spacing')
    number(grid['case_bottom_mm'], 500, 2000, 'monitor mounting height')
    definition = source['monitor_type']
    exact(definition, 'extends omit_parts parts', 'wall monitor type')
    if (definition['extends'] != 'office_computer'
            or definition['omit_parts'] != ['MonitorStand', 'MonitorFoot', 'MiniPC', 'MiniPCPower']):
        raise ValueError('Wall displays must inherit the existing monitor without desktop parts')
    if not isinstance(definition['parts'], list) or len(definition['parts']) != 1:
        raise ValueError('One explicit wall mount required per monitor')
    mount = definition['parts'][0]
    exact(mount, 'id body color action shape', 'monitor mount')
    if mount['id'] != 'WallMount' or mount['body'] != 'WallMount' or mount['action'] != 'create':
        raise ValueError('One named constructive wall mount required')
    exact(mount['shape'], 'kind origin size', 'wall mount shape')
    shape = mount['shape']
    if shape['kind'] != 'box' or len(shape['origin']) != 3 or len(shape['size']) != 3:
        raise ValueError('Portable rectangular wall mount required')
    for value in shape['origin']:
        number(value, -500, 1000, 'mount coordinate')
    for value in shape['size']:
        number(value, 1, 500, 'mount size')
    if abs(shape['origin'][1]+anchor['back_gap_mm']) > 1e-7 or abs(shape['origin'][1]+shape['size'][1]) > 1e-7:
        raise ValueError('Mount must span exactly from wall surface to case back')
    return source


def compile(ref, plans, p, levels):
    source = validate(furniture.read(ref))
    catalog = copy.deepcopy(furniture.read(source['catalog']))
    # The derived type is local to this composition; office catalog bytes stay intact.
    catalog['types']['wall_monitor'] = copy.deepcopy(source['monitor_type'])
    parts = furniture.parts_for(catalog, 'wall_monitor')
    if {part['body'] for part in parts} != {'MonitorCase', 'MonitorScreen', 'WallMount'}:
        raise ValueError('Complete inherited case, screen and wall mount required')
    if any(part['action'] != 'create' or part['shape']['kind'] != 'box' for part in parts):
        raise ValueError('Wall monitor currently supports inherited constructive boxes')
    case = next(part['shape'] for part in parts if part['body'] == 'MonitorCase')
    screen = next(part['shape'] for part in parts if part['body'] == 'MonitorScreen')
    if abs(case['origin'][1]) > 1e-7 or abs(screen['origin'][1]-(case['origin'][1]+case['size'][1])) > 1e-7:
        raise ValueError('Inherited monitor screen must face local +Y')
    plan = plans[source['level']]
    area = next(a for a in plan['areas'] if a['id'] == source['area'])
    wall = source['anchor']['wall']
    if any(opening['wall'] == wall for opening in plan['openings']):
        raise ValueError('A monitor array cannot cover a source opening')
    a, tangent, front, length = wall_worktops.wall_frame(plan, area, wall, p)
    # A right-handed planar transform sends catalog +Y towards the foyer.
    right = [front[1], -front[0]]
    grid, anchor = source['grid'], source['anchor']
    width = grid['columns']*case['size'][0]+(grid['columns']-1)*grid['horizontal_gap_mm']
    height = grid['rows']*case['size'][2]+(grid['rows']-1)*grid['vertical_gap_mm']
    centre = [a[i]+tangent[i]*length*anchor['fraction'] for i in (0, 1)]
    edge_margin = min(length*anchor['fraction']-width/2, length*(1-anchor['fraction'])-width/2)
    if edge_margin < 100:
        raise ValueError('Monitor raster leaves insufficient wall-end margin')
    level = next(level for level in levels if level['id'] == source['level'])
    if grid['case_bottom_mm']+height > level['clear_top_mm']-level['z_mm']:
        raise ValueError('Monitor raster exceeds the assumed storey height')
    base = [centre[i]+front[i]*(p['display_thickness']/2+anchor['back_gap_mm']) for i in (0, 1)]
    result = {'components': [], 'bodies': [], 'operations': [], 'joints': []}
    monitors, all_ids = [], []
    for row in range(grid['rows']):
        for column in range(grid['columns']):
            index = row*grid['columns']+column+1
            name = source['id']+'_M'+str(index).zfill(2)
            offset = ((grid['columns']-1)/2-column)*(case['size'][0]+grid['horizontal_gap_mm'])
            bottom = grid['case_bottom_mm']+(grid['rows']-1-row)*(case['size'][2]+grid['vertical_gap_mm'])
            z0 = level['z_mm']+bottom-case['origin'][2]
            def placed(x, y, z):
                return [base[0]+right[0]*(offset+x)+front[0]*y,
                        base[1]+right[1]*(offset+x)+front[1]*y, z0+z]
            native = furniture.place_parts(parts, name, name, placed, scale=1)
            result['components'].append({'id': name, 'grounded': True})
            for body in native['bodies']:
                body.update(level_id=source['level'], room_id=source['area'], role='foyer_monitor')
            for key in ('bodies', 'operations'):
                result[key].extend(native[key])
            ids = native['body_ids']; all_ids.extend(ids)
            origin = placed(screen['origin'][0]+screen['size'][0]/2,
                            screen['origin'][1]+screen['size'][1],
                            screen['origin'][2]+screen['size'][2]/2)
            monitors.append({'id': source['id']+'.M'+str(index).zfill(2), 'label': 'Monitor '+str(index),
                'body_ids': ids, 'case_body_id': name+'_MonitorCase', 'screen_body_id': name+'_MonitorScreen',
                'screen_frame': {'origin_mm': origin, 'x_axis': [-v for v in right]+[0], 'y_axis': [0, 0, 1],
                                 'normal': front+[0], 'width_mm': screen['size'][0], 'height_mm': screen['size'][2]}})
    # Aim the walkthrough crosshair at a screen even when the grid centre is a gap.
    centre_monitor = ((grid['rows']-1)//2)*grid['columns']+(grid['columns']-1)//2
    target = monitors[centre_monitor]['screen_frame']['origin_mm']
    eye = [target[i]+front[i]*1800 for i in (0,1)]+[level['z_mm']+1600]
    polygon = [[v*p['display_scale'] for v in xy] for xy in floor.outline(plan, area)]
    if floor.point_membership(eye[:2], polygon) != 1:
        raise ValueError('Monitor viewpoint must be inside the source foyer area')
    for op in result['operations']:
        bb = bounds.shape_bounds(op['shape'])
        if any(floor.point_membership([x,y],polygon)<0 for x in (bb['min'][0],bb['max'][0]) for y in (bb['min'][1],bb['max'][1])):
            raise ValueError('Monitor geometry leaves the source foyer area')
    result['interface'] = {'id': source['id'], 'level_id': source['level'], 'area': source['area'],
        'wall': wall, 'wall_body_id': source['level']+'__Wall_'+wall, 'scale': 1,
        'body_ids': all_ids, 'monitors': monitors, 'wall_length_mm': length,
        'grid_rows': grid['rows'], 'grid_columns': grid['columns'],
        'wall_end_margin_mm': edge_margin, 'grid_width_mm': width, 'grid_height_mm': height,
        'case_bottom_mm': grid['case_bottom_mm'], 'back_gap_mm': anchor['back_gap_mm'],
        'viewpoint': {'eye_mm': eye, 'target_mm': target}, 'front': front+[0],
        'building_fixed': True, 'mounting_qualified': False, 'metric_registration_qualified': False,
        'basis': source['basis']}
    return result


def clearance_pairs(interface, geometry):
    """Native bounds identify only potentially touching foreign body pairs."""
    if not interface:
        return []
    by_id = {entry['body']: entry for entry in geometry}
    own = set(interface['body_ids'])
    pairs = []
    for name in sorted(own):
        a = by_id[name]['bbox']
        for other, entry in by_id.items():
            if other in own or other == interface['wall_body_id']:
                continue
            b = entry['bbox']
            if all(a['max'][i] >= b['min'][i]-1e-7 and b['max'][i] >= a['min'][i]-1e-7 for i in range(3)):
                pairs.append((name, other))
    return pairs


def validate_instances(interface, body_names):
    """Require one disjoint case, screen and mount per declared grid position."""
    count = monitor_count(interface.get('grid_rows'), interface.get('grid_columns'))
    monitors = interface.get('monitors', [])
    bodies = {name for monitor in monitors for name in monitor['body_ids']}
    expected = interface.get('body_ids', [])
    if (len(monitors) != count or len({monitor['id'] for monitor in monitors}) != count
            or len(bodies) != count*3 or len(expected) != count*3
            or bodies != set(expected) or not bodies <= set(body_names)
            or interface['wall_body_id'] in bodies):
        raise ValueError(f'{count} complete disjoint native monitor instances are required')
    for monitor in monitors:
        display = {monitor['case_body_id'], monitor['screen_body_id']}
        if (len(monitor['body_ids']) != 3 or len(display) != 2
                or not display <= set(monitor['body_ids'])):
            raise ValueError('Each native monitor must have distinct case, screen and mount bodies')
    return monitors


def native_bounds_checks(interface, geometry):
    """Check complete native instance bounds and world separation in either CAD."""
    if not interface:
        return []
    by_id = {entry['body']: entry for entry in geometry}
    checks = []
    for monitor in validate_instances(interface, by_id):
        case = by_id[monitor['case_body_id']]['bbox']
        screen = by_id[monitor['screen_body_id']]['bbox']
        normal = monitor['screen_frame']['normal']
        c = [(case['min'][i]+case['max'][i])/2 for i in range(3)]
        s = [(screen['min'][i]+screen['max'][i])/2 for i in range(3)]
        checks.append({'id':monitor['id']+'_ScreenFront', 'passed':sum((s[i]-c[i])*normal[i] for i in range(3))>0,
                       'scope':'Native case/screen bounds face the source foyer side'})
    pairs = clearance_pairs(interface, geometry)
    checks.append({'id':interface['id']+'_ForeignBounds', 'passed':not pairs,
                   'scope':'All native building bodies except monitor instances and the intended W052 mounting wall; no swept-door or real-world qualification',
                   'excluded_mount_wall':interface['wall_body_id'], 'candidate_pairs':[list(pair) for pair in pairs]})
    return checks
