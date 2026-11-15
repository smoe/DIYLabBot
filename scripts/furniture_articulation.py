"""Browser hinge frames derived from existing placed native-source operations.

This additive contract does not add joints to the static CAD building.
"""
import json
import math
from pathlib import Path
import re

import assembly_model as assembly
import relative_floorplan as floor

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/'model/furniture-articulations.schema.json'
QUALIFICATIONS = {'measured_hinge', 'native_articulation', 'swing_clearance_checked'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact(value, keys, name):
    require(isinstance(value, dict) and set(value) == set(keys.split()), 'Explicit '+name+' fields required')


def read(ref):
    return json.loads(assembly.validate_reference(ref, root=ROOT).read_text())


def validate(source):
    exact(source, 'format catalog types', 'articulation source')
    require(source['format'] == 'solidcraftbot.furniture-articulations/1', 'Unsupported articulation source')
    exact(source['catalog'], 'source source_sha256', 'catalog reference')
    catalog = read(source['catalog'])
    require(isinstance(source['types'], dict) and source['types'], 'Articulated types required')
    for type_id, joints in source['types'].items():
        parts = catalog['types'].get(type_id)
        require(isinstance(parts, list), 'Articulation needs a catalog part list')
        bodies = {p['id']: p for p in parts if p['action'] == 'create'}
        require(isinstance(joints, dict) and joints, 'Named articulations required')
        for identity, joint in joints.items():
            exact(joint, 'id type moving_parts hinge axis front limits_deg states reference_state basis qualification', 'joint')
            require(joint['id'] == identity and joint['type'] == 'revolute', 'Named revolute joint required')
            moving = joint['moving_parts']
            require(isinstance(moving, list) and moving and all(isinstance(v, str) for v in moving)
                    and len(set(moving)) == len(moving) and set(moving) <= set(bodies), 'Unknown or duplicate moving parts')
            exact(joint['hinge'], 'part edge', 'hinge')
            require(joint['hinge']['part'] in moving, 'Hinge part must move')
            hinge = bodies[joint['hinge']['part']]
            require(hinge['shape']['kind'] == 'box', 'Hinge part must be a box')
            require(joint['hinge']['edge'] == {'x': 'min', 'y': 'max'}, 'Supported vertical hinge edge required')
            for field, size in [('axis', 3), ('front', 3), ('limits_deg', 2)]:
                values = joint[field]
                require(isinstance(values, list) and len(values) == size
                        and all(type(v) in (int, float) and math.isfinite(v) for v in values),
                        'Finite numeric joint '+field+' required')
            exact(joint['states'], 'closed open', 'joint states')
            require(all(type(v) in (int, float) and math.isfinite(v) for v in joint['states'].values()),
                    'Finite numeric joint states required')
            require(joint['axis'] == [0, 0, 1] and joint['front'] == [0, 1, 0], 'Local +Z axis and +Y front required')
            require(joint['states'] == {'closed': 0, 'open': 90} and joint['limits_deg'] == [0, 90]
                    and joint['reference_state'] == 'closed', 'Explicit closed/open reference and limits required')
            require(joint['basis'] == 'presentation_assumption', 'Illustrative articulation basis required')
            require(isinstance(joint['qualification'], dict) and set(joint['qualification']) == QUALIFICATIONS
                    and all(v is False for v in joint['qualification'].values()), 'Articulation does not qualify measured/native/swing behaviour')
    return catalog


def parameter(value, unit, bounds):
    exact(value, 'value unit range basis', 'display parameter')
    require(value['unit'] == unit and value['basis'] == 'presentation_assumption', 'Typed display assumption required')
    declared = value['range']
    require(isinstance(declared, list) and len(declared) == 2
            and all(type(v) in (int, float) and math.isfinite(v) for v in declared+[value['value']])
            and bounds[0] <= declared[0] <= value['value'] <= declared[1] <= bounds[1]
            and declared[0] < declared[1], 'Finite display parameter within range required')
    return value['value']


def validate_requests(objects):
    require(isinstance(objects, list), 'Object list required')
    ids = set()
    for item in objects:
        exact(item, 'id room instance articulation label commands state_labels duration view_distance', 'object')
        require(all(isinstance(item[k], str) and item[k] for k in ('id', 'room', 'instance', 'articulation', 'label')), 'Object references and labels required')
        require(item['id'] == '.'.join(item[k] for k in ('room', 'instance', 'articulation'))
                and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){2}', item['id'])
                and item['id'] not in ids, 'Unique stable object reference required')
        ids.add(item['id'])
        for field, keys in [('commands', 'open close view'), ('state_labels', 'closed opening open closing')]:
            exact(item[field], keys, field)
            require(all(isinstance(v, str) and v for v in item[field].values()), 'Object labels required')
        parameter(item['duration'], 's', (.1, 10))
        parameter(item['view_distance'], 'mm', (300, 3000))


def compile_objects(ref, objects, building, parameters, interface, expanded, plans, eye_height):
    validate_requests(objects)
    source = read(ref)
    catalog = validate(source)
    furnishings = read(building['sources']['furnishings'])
    require(source['catalog'] == furnishings['catalog'], 'Articulation and furnishings catalog pins must match')
    body_ids = {body['id'] for body in expanded['bodies']}
    operations = {op['body']: op for op in expanded['operations'] if op['action'] == 'create'}
    result = []
    for item in objects:
        room = next((v for v in furnishings['rooms'] if v['id'] == item['room']), None)
        require(room is not None, 'Unknown object room')
        instance = next((v for v in room['instances'] if v['id'] == item['instance']), None)
        require(instance is not None and instance['type'] == 'fridge', 'Unknown or unsupported object instance')
        joint = source['types'].get(instance['type'], {}).get(item['articulation'])
        require(joint is not None, 'Unknown object articulation')
        parts = {v['id']: v for v in catalog['types'][instance['type']] if v['action'] == 'create'}
        prefix = room['id']+'_'+instance['id']+'_'
        moving = [prefix+parts[name]['body'] for name in joint['moving_parts']]
        room_report = next(v for v in interface['furnishings']['rooms'] if v['id'] == room['id'])
        require(set(moving) <= body_ids & set(room_report['body_ids']), 'Missing placed articulated bodies')
        shape = operations[prefix+parts[joint['hinge']['part']]['body']]['shape']
        require(shape['kind'] == 'polygon_prism' and shape['plane'] == 'XY' and len(shape['points']) == 4, 'Placed box footprint required')
        points = shape['points']
        require(floor.signed_area(points) > 0, 'Unmirrored ordered box footprint required')
        # place_parts preserves (x,y),(x+w,y),(x+w,y+d),(x,y+d).
        hinge = points[3]+[shape['offset']]
        front = [points[3][i]-points[0][i] for i in (0, 1)]
        length = math.hypot(*front)
        require(length > 0, 'Nonzero placed front direction required')
        front = [v/length for v in front]+[0]
        target = [sum(pt[i] for pt in points)/4 for i in (0, 1)]+[shape['offset']+shape['depth']/2]
        distance = parameter(item['view_distance'], 'mm', (300, 3000))
        level = next(v for v in interface['levels'] if v['id'] == room['level'])
        eye = [target[i]+front[i]*distance for i in (0, 1)]+[level['z_mm']+eye_height]
        plan = plans[room['level']]
        areas = {v['id'] for v in plan['areas']}
        local = [v/parameters['display_scale'] for v in eye[:2]]
        require(any(floor.point_membership(local, floor.outline(plan, name)) == 1
                    for name in room['template_areas'] if name in areas), 'Object viewpoint outside kitchen source areas')
        result.append({'id': item['id'], 'label': item['label'], 'scene': 'building', 'level_id': room['level'],
                       'joint': {'id': joint['id'], 'type': joint['type'], 'origin_mm': hinge, 'axis': joint['axis'], 'limits_deg': joint['limits_deg']},
                       'front': front, 'moving_body_ids': moving, 'states': joint['states'], 'reference_state': joint['reference_state'],
                       'commands': {k: {'label': item['commands'][k], 'target_state': k if k == 'open' else 'closed'} for k in ('open', 'close')},
                       'view_label': item['commands']['view'], 'state_labels': item['state_labels'],
                       'duration_s': parameter(item['duration'], 's', (.1, 10)), 'viewpoint': {'eye_mm': eye, 'target_mm': target},
                       'basis': joint['basis'], 'qualification': joint['qualification']})
    return result


def dependencies(ref):
    source = read(ref)
    validate(source)
    return [ROOT/ref['source'], SCHEMA, Path(__file__), ROOT/source['catalog']['source']]
