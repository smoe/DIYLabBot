"""Source-derived viewpoints and interactions in one furnished building frame.

This module compiles cameras, not a navigation mesh or physical walking route.
Native Boolean surfaces are exported separately from checked CAD build reports.
"""
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

import assembly_model as assembly
import building_stack as stack
import relative_floorplan as floor
import furniture_articulation as articulation
import walkthrough_mechanisms as mechanisms
import walkthrough_robots
import walkthrough_elevator

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/building-walkthrough.shared.json'
SCHEMA = ROOT/'model/building-walkthrough.schema.json'
FORMAT = 'solidcraftbot.building-walkthrough/1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+name+' fields')


def number(value, lower, upper, name):
    require(type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper,
            'Invalid '+name)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(spec):
    exact({key: value for key, value in spec.items() if key != 'seminar_film'},
          'format id sources settings rendering default_stop stops qualification limitations articulation_source objects interaction elevator mechanisms navigation', 'walkthrough')
    if 'seminar_film' in spec:
        film = spec['seminar_film']
        exact(film, 'title source_url video_url', 'seminar film')
        require(isinstance(film['title'], str) and film['title'].strip(), 'A film title is required')
        for name, host, prefix in [('source_url', 'commons.wikimedia.org', '/wiki/File:'),
                                   ('video_url', 'upload.wikimedia.org', '/wikipedia/commons/')]:
            value = film[name]
            require(isinstance(value, str), 'A film URL is required')
            url = urlsplit(value)
            require(url.scheme == 'https' and url.netloc == host and url.path.startswith(prefix)
                    and not url.query and not url.fragment, 'A direct Wikimedia film source is required')
    nav = spec['navigation']
    exact(nav, 'camera_radius_mm contact_margin_mm max_contact_iterations max_slides closed_access_areas basis', 'navigation')
    number(nav['camera_radius_mm'], 20, 400, 'camera radius')
    number(nav['contact_margin_mm'], .1, 5, 'contact margin')
    for key, lo, hi in [('max_contact_iterations', 16, 128), ('max_slides', 1, 8)]:
        require(type(nav[key]) is int and lo <= nav[key] <= hi, 'Bounded integer navigation '+key)
    require(nav['basis'] == 'presentation_assumption', 'Camera envelope is an explicit presentation assumption')
    require(isinstance(nav['closed_access_areas'], dict) and all(isinstance(k, str) and isinstance(v, list)
            and all(isinstance(a, str) for a in v) and len(v) == len(set(v))
            for k, v in nav['closed_access_areas'].items()), 'Named access areas required')
    require(spec['format'] == FORMAT and isinstance(spec['id'], str) and
            re.fullmatch('[A-Za-z][A-Za-z0-9_]*', spec['id']), 'Walkthrough identity required')
    exact(spec['interaction'], 'reach', 'interaction policy')
    articulation.parameter(spec['interaction']['reach'], 'mm', (300,4000))
    exact(spec['articulation_source'], 'source source_sha256', 'articulation reference')
    articulation.validate(articulation.read(spec['articulation_source']))
    articulation.validate_requests(spec['objects'])
    mechanisms.validate(spec['mechanisms'])
    walkthrough_elevator.validate(spec['elevator'])
    exact(spec['sources'], 'building', 'scene sources')
    for ref in spec['sources'].values():
        exact(ref, 'source source_sha256', 'pinned scene source')
        assembly.validate_reference(ref, root=ROOT)
    ranges = {'eye_height_mm': (1000, 2200), 'walk_speed_mm_s': (100, 4000),
              'vertical_speed_mm_s': (100, 4000), 'fov_deg': (35, 100),
              'near_mm': (5, 100), 'far_mm': (30000, 300000),
              'look_sensitivity': (.0001, .02)}
    exact(spec['settings'], ' '.join(ranges), 'camera settings')
    for key, bounds in ranges.items():
        number(spec['settings'][key], *bounds, key)
    exact(spec['rendering'], 'opacity_by_role', 'rendering policy')
    exact(spec['rendering']['opacity_by_role'], 'concept_storey_wall circulation_wall_bridge', 'architectural opacity policy')
    for opacity in spec['rendering']['opacity_by_role'].values():
        number(opacity, .1, 1, 'wall display opacity')
    exact(spec['qualification'], 'metric_scale_known lab_to_building_registered collision_checked', 'qualification')
    require(all(value is False for value in spec['qualification'].values()),
            'A visual walkthrough does not qualify metric registration or collision-free routes')
    require(isinstance(spec['limitations'], list) and spec['limitations'] and
            all(isinstance(text, str) and text for text in spec['limitations']), 'Explicit limitations required')
    require(isinstance(spec['stops'], list) and spec['stops'], 'Viewpoints required')
    ids = []
    for stop in spec['stops']:
        exact(stop, 'id label scene level_id anchor', 'viewpoint')
        require(isinstance(stop['id'], str) and re.fullmatch('[a-z][a-z0-9_]*', stop['id']) and
                isinstance(stop['label'], str) and stop['label'], 'Viewpoint identity and label required')
        require(stop['scene'] in spec['sources'], 'Unknown viewpoint scene')
        anchor = stop['anchor']
        require(isinstance(anchor, dict), 'Semantic camera anchor required')
        kind = anchor.get('kind')
        if kind == 'room_entry':
            exact(anchor, 'kind areas opening inset_mm target_height_mm look_at', 'room entry anchor')
            require(stop['scene'] == 'building' and isinstance(anchor['areas'], list) and anchor['areas']
                    and len(set(anchor['areas'])) == len(anchor['areas']), 'Building room areas required')
            number(anchor['inset_mm'], 300, 3000, 'entry inset')
            require(anchor['look_at'] in ('room_end', 'entry'), 'Known doorway-relative view direction required')
        elif kind == 'area_edge':
            exact(anchor, 'kind area wall target_area setback_mm target_height_mm', 'area edge anchor')
            require(stop['scene'] == 'building', 'Building edge required')
            number(anchor['setback_mm'], 300, 3000, 'edge setback')
        elif kind == 'access_entry':
            exact(anchor, 'kind access_id setback_mm target_height_mm', 'access entry anchor')
            require(stop['scene'] == 'building' and isinstance(anchor['access_id'], str) and anchor['access_id'], 'Building access reference required')
            number(anchor['setback_mm'], 300, 1500, 'access camera setback')
        elif kind == 'microscopy':
            exact(anchor, 'kind station eye_offset_mm target_height_mm', 'microscopy viewpoint')
            require(isinstance(anchor['station'], str) and anchor['station'], 'Microscopy station required')
            require(isinstance(anchor['eye_offset_mm'], list) and len(anchor['eye_offset_mm']) == 3, 'Three camera offsets required')
            for value in anchor['eye_offset_mm']:
                number(value, -2000, 2000, 'microscopy camera offset')
        elif kind == 'kitchenette':
            exact(anchor, 'kind station opening inset_mm target_height_mm', 'kitchen viewpoint')
            require(isinstance(anchor['station'],str) and isinstance(anchor['opening'],str), 'Kitchen and entrance references required')
            number(anchor['inset_mm'],0,600,'kitchen entry inset')
        elif kind == 'seminar':
            exact(anchor, 'kind room', 'seminar viewpoint')
            require(isinstance(anchor['room'], str) and anchor['room'], 'A furnished seminar room is required')
        else:
            raise ValueError('Unsupported camera anchor kind')
        if kind != 'seminar':
            number(anchor['target_height_mm'], 100, 2200, 'target height')
        ids.append(stop['id'])
    require(len(ids) == len(set(ids)) and spec['default_stop'] in ids, 'Unique viewpoints and known default required')
    return spec


def wall_endpoints(plan, wall_id):
    wall = next((item for item in plan['walls'] if item['id'] == wall_id), None)
    require(wall is not None, 'Unknown camera anchor wall: '+str(wall_id))
    return [plan['vertices'][wall[key]] for key in ('start', 'end')]


def inward(plan, area_ids, point, tangent):
    """Choose the actual room/corridor side, without depending on wall winding."""
    polygons = [floor.outline(plan, name) for name in area_ids]
    candidates = [[-tangent[1], tangent[0]], [tangent[1], -tangent[0]]]
    inside = lambda xy: any(floor.point_membership(xy, polygon) == 1 for polygon in polygons)
    normals = [normal for normal in candidates if inside([point[i]+normal[i]*1e-5 for i in (0, 1)])]
    require(len(normals) == 1, 'Camera wall must have exactly one selected interior side')
    return normals[0], polygons


def building_camera(anchor, plan, scale, z, eye_height):
    if anchor['kind'] == 'room_entry':
        opening = next((item for item in plan['openings'] if item['id'] == anchor['opening']), None)
        require(opening is not None and opening['kind'] == 'door', 'Existing room door required')
        areas = anchor['areas']
        selected = [area for area in plan['areas'] if area['id'] in areas]
        require(len(selected) == len(areas) and all(area['kind'] == 'room' for area in selected), 'Existing room areas required')
        require(any(any(edge['wall'] == opening['wall'] for edge in area['boundary']) for area in selected),
                'Entry door must bound the selected room')
        a, b = wall_endpoints(plan, opening['wall'])
        fraction = sum(opening['interval'])/2
        point = [a[i]+fraction*(b[i]-a[i]) for i in (0, 1)]
        inset = anchor['inset_mm']
    else:
        areas = [anchor['area']]
        selected = next((area for area in plan['areas'] if area['id'] == areas[0]), None)
        target = next((area for area in plan['areas'] if area['id'] == anchor['target_area']), None)
        require(selected is not None and selected['kind'] == 'corridor' and target is not None and target['kind'] == 'void',
                'Atrium camera requires a corridor beside a source void')
        require(all(any(edge['wall'] == anchor['wall'] for edge in area['boundary']) for area in (selected, target)),
                'View edge must be shared by corridor and atrium')
        a, b = wall_endpoints(plan, anchor['wall'])
        point = [(a[i]+b[i])/2 for i in (0, 1)]
        inset = anchor['setback_mm']
    length = math.dist(a, b)
    require(length > 0, 'Nonzero camera anchor wall required')
    tangent = [(b[i]-a[i])/length for i in (0, 1)]
    normal, polygons = inward(plan, areas, point, tangent)
    eye_xy = [point[i]*scale+normal[i]*inset for i in (0, 1)]
    require(any(floor.point_membership([v/scale for v in eye_xy], polygon) == 1 for polygon in polygons),
            'Camera inset lies outside its source area')
    if anchor['kind'] == 'room_entry':
        # Look along the room from its real entry, toward the farthest interior
        # point on that direction. No room dimensions are copied to this source.
        distance = max(sum((v[i]-point[i])*normal[i] for i in (0, 1)) for polygon in polygons for v in polygon)*scale
        target_xy = ([point[i]*scale for i in (0, 1)] if anchor['look_at'] == 'entry' else
                     [point[i]*scale+normal[i]*distance*.85 for i in (0, 1)])
    else:
        polygon = floor.outline(plan, anchor['target_area'])
        target_xy = [sum(v[i] for v in polygon)/len(polygon)*scale for i in (0, 1)]
    return eye_xy+[z+eye_height], target_xy+[z+anchor['target_height_mm']]



def seminar_window_objects(profile, seminar, expanded):
    """Bind each source sash to one closed-reference browser hinge."""
    if seminar is None or 'window_front' not in seminar:
        return []
    front = seminar['window_front']
    require(isinstance(front, dict) and isinstance(front.get('sashes'), list) and front['sashes'],
            'An installed window front needs its source sashes')
    native_ids = {body['id'] for body in expanded['bodies']}
    identities, driven = set(), set()
    result = []
    def vector(value):
        return (isinstance(value, list) and len(value) == 3 and
                all(type(v) in (int, float) and math.isfinite(v) for v in value))
    for sash in front['sashes']:
        require(isinstance(sash.get('id'), str) and sash['id'] and sash['id'] not in identities,
                'Unique source window sash identity required')
        require(isinstance(sash.get('label'), str) and sash['label'].strip() and
                isinstance(sash.get('wall_id'), str) and sash['wall_id'], 'Named source window sash required')
        moving = sash.get('moving_body_ids')
        require(isinstance(moving, list) and moving and all(isinstance(v, str) for v in moving)
                and len(moving) == len(set(moving)) and set(moving) <= native_ids and not set(moving) & driven,
                'Every moving sash body must exist and have one hinge owner')
        require(vector(sash.get('origin_mm')) and vector(sash.get('axis')) and
                abs(math.hypot(*sash['axis'])-1) < 1e-7, 'Finite unit-axis window hinge required')
        angle = sash.get('angle_deg')
        require(type(angle) in (int, float) and math.isfinite(angle) and 0 < abs(angle) <= 180,
                'Finite nonzero signed source window opening required')
        view = sash.get('viewpoint')
        require(isinstance(view, dict) and vector(view.get('eye_mm')) and vector(view.get('target_mm'))
                and math.dist(view['eye_mm'], view['target_mm']) > 1, 'Source window viewpoint required')
        identity = sash['id']+'.Hinge'
        obj = mechanisms.presentation(profile, identity, seminar['level_id'],
            {'id': 'Hinge', 'type': 'revolute', 'origin_mm': sash['origin_mm'], 'axis': sash['axis'],
             'limits_deg': sorted((0, angle))}, moving, {'closed': 0, 'open': angle}, 'closed',
            view['eye_mm'], view['target_mm'], seminar['id'], sash['label'])
        obj.update(label=sash['label'], mechanism='window', initial_state='closed',
                   seminar_room_id=seminar['id'], sash_id=sash['id'], wall_id=sash['wall_id'])
        result.append(obj)
        identities.add(sash['id']); driven.update(moving)
    return result


def compile(source=None):
    path = SOURCE if source is None else Path(source)
    if not path.is_absolute():
        path = ROOT/path
    raw = path.read_bytes()
    spec = validate(json.loads(raw))
    building_path = assembly.validate_reference(spec['sources']['building'], root=ROOT)
    building = stack.load(building_path)
    p = stack.parameters(building)
    interface = stack.interfaces(building, p)
    levels = [{key: level[key] for key in ('id', 'label', 'z_mm')} for level in interface['levels']]
    level_z = {level['id']: level['z_mm'] for level in levels}
    laboratories = interface.get('laboratories', [])
    equipped = [lab for lab in laboratories if lab.get('layout_source')]
    require(len(equipped) == 1, 'One source-bound equipment layout is required')
    laboratory = equipped[0]
    seminar = interface.get('seminar_room')
    require('seminar_film' not in spec or seminar is not None, 'A seminar film needs an installed screen')
    expanded = stack.expanded(building, p)
    stops = []
    for stop in spec['stops']:
        require(stop['level_id'] in level_z, 'Unknown viewpoint level')
        anchor = stop['anchor']
        if stop['scene'] == 'building':
            if anchor['kind'] == 'seminar':
                require(seminar is not None and seminar['id'] == anchor['room'] and seminar['level_id'] == stop['level_id'],
                        'Seminar viewpoint must reference the furnished room on its actual floor')
                eye = seminar['viewpoint']['eye_mm']
                target = seminar['viewpoint']['target_mm']
            elif anchor['kind'] == 'kitchenette':
                station=interface.get('kitchenette')
                require(station is not None and station['id']==anchor['station'] and station['level_id']==stop['level_id'],
                        'Kitchen viewpoint must reference the installed room')
                entry={'kind':'room_entry','areas':station['template_areas'],'opening':anchor['opening'],
                       'inset_mm':anchor['inset_mm'],'target_height_mm':anchor['target_height_mm'],'look_at':'room_end'}
                eye,_=building_camera(entry,stack.level_plan(building,stop['level_id']),p['display_scale'],
                    level_z[stop['level_id']],spec['settings']['eye_height_mm'])
                target=station['target_mm'][:2]+[level_z[stop['level_id']]+anchor['target_height_mm']]
            elif anchor['kind'] == 'microscopy':
                station=interface.get('microscopy')
                require(station is not None and station['id']==anchor['station'] and station['level_id']==stop['level_id'],
                        'Viewpoint must reference an installed microscope on this floor')
                angle=math.radians(station['instrument_yaw_deg']);c,s=math.cos(angle),math.sin(angle)
                x,y,z=anchor['eye_offset_mm'];base=station['support_origin_mm']
                eye=[base[0]+c*x-s*y,base[1]+s*x+c*y,base[2]+z]
                target=station['specimen_mm'][:2]+[level_z[stop['level_id']]+anchor['target_height_mm']]
                require(floor.point_membership(eye[:2],station['room_interior_polygon_mm'])==1,
                        'Microscopy camera must stay in its source room')
            elif anchor['kind'] == 'access_entry':
                access = next((value for value in interface['atrium_accesses']
                               if value['id'] == anchor['access_id'] and value['level_id'] == stop['level_id']), None)
                seating = next((value for value in interface['furnishings'].get('seating_groups', [])
                                if value['anchor_id'] == anchor['access_id'] and value['level_id'] == stop['level_id']), None)
                require(access is not None and seating is not None, 'Unknown or unfurnished atrium access viewpoint')
                plan = stack.level_plan(building, stop['level_id'])
                length, sums = 0., [0., 0.]
                for name in access['entry_boundary_ids']:
                    a, b = wall_endpoints(plan, name)
                    span = math.dist(a, b)
                    length += span
                    for axis in (0, 1):
                        sums[axis] += (a[axis]+b[axis])*span/2
                eye_xy = [sums[axis]/length*p['display_scale']-seating['frame_x'][axis]*anchor['setback_mm'] for axis in (0, 1)]
                corridor = floor.outline(plan, building['atrium_access']['corridor_area'])
                require(floor.point_membership([value/p['display_scale'] for value in eye_xy], corridor) == 1,
                        'Access camera must stay inside its source corridor')
                eye = eye_xy+[level_z[stop['level_id']]+spec['settings']['eye_height_mm']]
                target = seating['origin_mm'][:2]+[level_z[stop['level_id']]+anchor['target_height_mm']]
            else:
                if anchor['kind'] == 'area_edge':
                    require(anchor['wall'] in building.get('exterior', {}).get('guard_boundaries', []),
                            'Atrium view requires an implemented open guard boundary')
                eye, target = building_camera(anchor, stack.level_plan(building, stop['level_id']), p['display_scale'],
                                              level_z[stop['level_id']], spec['settings']['eye_height_mm'])
        require(math.dist(eye, target) > 100, 'Camera eye and target must differ')
        stops.append({key: stop[key] for key in ('id', 'label', 'scene', 'level_id')} |
                     {'eye_mm': eye, 'target_mm': target, 'anchor': anchor})
    objects = articulation.compile_objects(spec['articulation_source'], spec['objects'], building, p, interface,
        expanded, {v['id']: stack.level_plan(building, v['id']) for v in levels}, spec['settings']['eye_height_mm'])
    objects += articulation.compile_lab_objects(spec['articulation_source'], interface, expanded,
        {v['id']: stack.level_plan(building, v['id']) for v in levels}, p, spec['settings']['eye_height_mm'],
        equipment_profiles=spec['mechanisms']['equipment'])
    objects += mechanisms.room_doors(spec['mechanisms']['room_doors'], interface, expanded,
        {v['id']: stack.level_plan(building, v['id']) for v in levels}, p, spec['settings']['eye_height_mm'],
        spec['navigation']['closed_access_areas'])
    objects += mechanisms.equipment(spec['mechanisms']['equipment'], interface, spec['settings']['eye_height_mm'])
    objects += seminar_window_objects(spec['mechanisms']['room_doors'], seminar, expanded)
    robot_objects, robots = walkthrough_robots.compile(interface)
    objects.extend(robot_objects)
    lift_object, elevator = walkthrough_elevator.compile(spec['elevator'], building, p, interface,
        expanded, stack.level_plan(building, 'OG3'), spec['settings']['eye_height_mm'])
    objects.append(lift_object)
    objects.extend(elevator.pop('door_objects', []))
    plan = stack.level_plan(building, laboratory['level_id'])
    area = next(value for value in plan['areas'] if value['id'] == laboratory['area'])
    wall_ids = {edge['wall'] for edge in area['boundary']}
    openings = [opening['id'] for opening in plan['openings'] if opening['wall'] in wall_ids]
    prefix = laboratory['level_id']+'__'
    shell = {prefix+'Area_'+area['id'], *[prefix+'Wall_'+name for name in wall_ids]}
    shell.update(body['id'] for body in expanded['bodies']
                 if any(body['id'].startswith(prefix+'DoorLeaf_'+name) for name in openings))
    for window in interface['exterior'].get('side_window_groups', []):
        if window['level_id'] == laboratory['level_id'] and window['wall'] in wall_ids:
            shell.update([window['glass_body'], window['frame_body']])
    isolation = {'label': 'Labor isoliert anzeigen', 'laboratory_id': laboratory['id'], 'body_ids': sorted(shell |
        set(laboratory['furniture_body_ids']))}
    paths = [*walkthrough_robots.dependencies(), *articulation.dependencies(spec['articulation_source']), *mechanisms.dependencies(), path, SCHEMA, Path(__file__), ROOT/'scripts/assembly_model.py',
             *stack.source_dependencies(building), ROOT/'scripts/walkthrough_elevator.py',
             ROOT/'scripts/atrium_seating.py']
    pins = {str(item.resolve().relative_to(ROOT)): digest(item) for item in dict.fromkeys(paths)}
    require(digest(path) == hashlib.sha256(raw).hexdigest(), 'Walkthrough source changed while compiling')
    for ref in [*spec['sources'].values(), spec['articulation_source']]:
        require(pins[ref['source']] == ref['source_sha256'], 'Scene source changed while compiling: '+ref['source'])
    return {'format': FORMAT, 'id': spec['id'], 'default_stop': spec['default_stop'], 'stops': stops,
            'interaction': {'reach_mm': articulation.parameter(spec['interaction']['reach'], 'mm', (300,4000))},
            'navigation': spec['navigation'],
            'objects': objects, 'robots': robots, 'elevator': elevator, 'isolation': isolation,
            'laboratories': laboratories, 'microscopy': interface.get('microscopy'), 'kitchenette':interface.get('kitchenette'),
            'places': interface['places'], 'topology': interface['topology'],
            'open_passages': interface['exterior']['open_passages'],
            'room_signs': interface.get('room_signs'),
            **({'seminar_room': {**seminar, 'film': spec.get('seminar_film')}} if seminar is not None else {}),
            'levels': levels, 'settings': spec['settings'], 'rendering': spec['rendering'],
            'scene_sources': {name: {**ref, 'build_report': 'cad/building-stack/shared-build-report.json'}
                              for name, ref in spec['sources'].items()},
            'equipment_source': {**laboratory['layout_source'], 'build_report': 'cad/lab-layout-l01/shared-build-report.json'},
            'hidden_body_ids': {'building': interface['marker_body_ids']},
            'source_files_sha256': pins, 'qualification': spec['qualification'],
            'limitations': spec['limitations']}
