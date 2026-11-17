"""Bind existing room-door geometry and device joints to walkthrough controls.

No geometry or instance joint lists are copied into the browser source. Device
command guards are conservative endpoint requirements derived from the native
provider's pose validator (including its cold-storage access contract).
"""
import itertools
import json
import math
from pathlib import Path

import atrium_seating
import furniture_articulation as art
import lab_layout_model as layout
import robot_spec as robot
from tube_cam_model import matrix

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {'freezer_minus20', 'fume_hood_1200', 'nanodrop', 'qubit'}


def validate(source):
    art.exact(source, 'room_doors equipment', 'mechanism profiles')
    art.validate_presentation(source['room_doors'])
    art.require(set(source['equipment']) == ASSETS, 'Requested equipment profiles required')
    for item in source['equipment'].values():
        art.exact(item, 'presentation roles', 'equipment mechanism profile')
        art.validate_presentation(item['presentation'])
        art.require(isinstance(item['roles'], dict) and item['roles'] and
                    all(isinstance(v, str) and v for v in item['roles'].values()), 'Device role labels required')


def presentation(profile, identity, level, joint, moving, states, reference, eye, target, room, label):
    return {'id': identity, 'scene': 'building', 'level_id': level, 'joint': joint,
            'moving_body_ids': moving, 'states': states, 'reference_state': reference,
            **art.presentation_fields(profile, room=room, instance=identity.split('.')[1], articulation=label),
            'viewpoint': {'eye_mm': eye, 'target_mm': target}, 'basis': 'presentation_assumption',
            'qualification': {key: False for key in art.QUALIFICATIONS}}


def room_doors(profile, interface, expanded, plans, parameters, eye_height):
    operations = {op['body']: op for op in expanded['operations'] if op['action'] == 'create'}
    level_labels = {level['id']: level['label'] for level in interface['levels']}
    result = []
    for key, binding in interface['exterior']['door_bindings'].items():
        level, opening_id = key.split('__', 1)
        plan = plans[level]
        door = next(v for v in plan['openings'] if v['id'] == opening_id)
        wall = next(v for v in plan['walls'] if v['id'] == door['wall'])
        a, b = [[v*parameters['display_scale'] for v in plan['vertices'][wall[k]]] for k in ('start', 'end')]
        length = math.dist(a, b)
        closed = [(b[i]-a[i])/length for i in (0, 1)]
        hinge = [a[i]+door['interval'][0]*(b[i]-a[i]) for i in (0, 1)]
        if 'placement' in binding:
            hinge = binding['placement']['hinge_mm']
            closed = binding['placement']['closed_axis']
        shape = operations[binding['leaf_body_id']]['shape']
        art.require(shape['kind'] == 'polygon_prism' and shape['plane'] == 'XY', 'Native door footprint required')
        # Select the actual leaf edge adjoining its source hinge. This follows
        # both the historical default handedness and explicit opening overrides.
        points = shape['points']
        index = next(i for i, point in enumerate(points) if math.dist(point, hinge) < 1e-6)
        tip = next(points[i % len(points)] for i in (index-1, index+1)
                   if abs(math.dist(points[i % len(points)], hinge)-binding['width_mm']) < 1e-6)
        opened = [(tip[i]-hinge[i])/binding['width_mm'] for i in (0, 1)]
        sign = closed[0]*opened[1]-closed[1]*opened[0]
        art.require(abs(abs(sign)-1) < 1e-7, 'Orthogonal native open door required')
        sign = 1 if sign > 0 else -1
        target = [hinge[i]+closed[i]*binding['width_mm']/2 for i in (0, 1)]+[shape['offset']+min(1100, binding['height_mm']/2)]
        distance = art.parameter(profile['view_distance'], 'mm', (300, 3000))
        eye = [target[i]+opened[i]*distance for i in (0, 1)]+[shape['offset']+eye_height]
        result.append(presentation(profile, level+'.'+opening_id+'.Door', level,
            {'id': 'Door', 'type': 'revolute', 'origin_mm': hinge+[shape['offset']], 'axis': [0, 0, sign], 'limits_deg': [0, 90]},
            [binding['leaf_body_id'], *binding['detail_body_ids']], {'closed': 0, 'open': 90}, 'open',
            eye, target, level_labels[level], opening_id) | {'front': opened+[0], 'mechanism': 'room_door',
                'opening_id': opening_id, 'material': binding['material']})
    return result


def command_guards(provider, expanded, states):
    """Derive the public two-state contract from the existing native validator.

    Requiring the other joint to finish at an endpoint is conservative: a door
    that the native validator permits at an intermediate access angle must be
    fully open before this UI allows an insert to move. Exhaustively compare
    the resulting guards with the native endpoint combinations; unsupported
    non-pairwise coupling fails compilation rather than silently losing a rule.
    """
    names = list(states)
    art.require(len(names) <= 12, 'Bounded device endpoint contract required')
    def valid(values):
        try:
            provider.validate_pose(expanded, values)
            return True
        except ValueError:
            return False
    closed = {k: v['closed'] for k, v in states.items()}
    art.require(valid(closed), 'Closed device reference must be valid')
    guards = {k: {'open': [], 'close': []} for k in names}
    for first, second in itertools.permutations(names, 2):
        alone = {**closed, first: states[first]['open']}
        together = {**alone, second: states[second]['open']}
        if not valid(alone) and valid(together):
            guards[first]['open'].append({'joint': second, 'state': 'open'})
            guards[second]['close'].append({'joint': first, 'state': 'closed'})
    for bits in itertools.product(('closed', 'open'), repeat=len(names)):
        pose = dict(zip(names, bits))
        permitted = all(pose[g['joint']] == g['state'] for k in names
                        for g in guards[k]['open' if pose[k] == 'open' else 'close'])
        art.require(permitted == valid({k: states[k][pose[k]] for k in names}),
                    'Native pose constraints need a richer browser contract')
    return guards


def equipment(profiles, interface, eye_height):
    result = []
    for laboratory in interface.get('laboratories', []):
        source = art.read(laboratory['layout_source'])
        instances = {item['id']: item for item in source['instances']}
        for device in laboratory['device_instances']:
            if device['asset'] not in profiles:
                continue
            item = instances[device['id']]
            provider = layout.provider(item['asset'])
            spec = layout.instance_source(source, item)
            p = provider.parameters(spec)
            expanded = provider.expanded(spec, p)
            reference = provider.pose(spec, p, item.get('pose'))
            provider.validate_pose(expanded, reference)
            states = {joint['id']: dict(zip(('closed', 'open'), joint.get('limits_deg', joint.get('limits_mm'))))
                      for joint in expanded['joints']}
            guards = command_guards(provider, expanded, states)
            profile = profiles[item['asset']]
            world = device['world_pose']
            prefix = laboratory['id']+'.'+device['id']+'.'
            for joint in expanded['joints']:
                art.require(joint['parent'] == 'Frame', 'Independent native device joint required')
                bodies = [body for body in expanded['bodies'] if body['component'] == joint['child']]
                primary = next(body for body in bodies if body['role'] in profile['roles'])
                operation = next(op for op in expanded['operations'] if op['body'] == primary['id'] and op['action'] == 'create')
                shape = dict(operation['shape'])
                def numbers(values):
                    return [numbers(v) if isinstance(v, (list, tuple)) else robot.evaluate(v, p) for v in values]
                for field in ('origin', 'size', 'points'):
                    if field in shape:
                        shape[field] = numbers(shape[field])
                for field in ('offset', 'depth'):
                    if field in shape:
                        shape[field] = robot.evaluate(shape[field], p)
                bounds = atrium_seating.operation_bounds(shape)
                centre = [(a+b)/2 for a, b in zip(bounds['min'], bounds['max'])]
                endpoints = [robot.transform(robot.multiply(world, matrix(expanded, joint['child'], p,
                    {**reference, joint['id']: value})), centre) for value in states[joint['id']].values()]
                target = [sum(point[i] for point in endpoints)/2 for i in range(3)]
                front = [-world[i][1] for i in range(3)]
                distance = art.parameter(profile['presentation']['view_distance'], 'mm', (300, 3000))
                eye = [target[i]+distance*front[i] for i in range(3)]
                eye[2] = world[2][3]+min(eye_height, max(350, target[2]-world[2][3]+250))
                values = dict(states[joint['id']])
                initial = next((k for k, v in values.items() if v == reference[joint['id']]), 'reference')
                if initial == 'reference':
                    values[initial] = reference[joint['id']]
                label = profile['roles'][primary['role']]
                if primary['role'] in {'plastic_drawer', 'hinged_cabinet_door'}:
                    label += ' '+str(int(''.join(c for c in joint['id'] if c.isdigit())))
                obj = presentation(profile['presentation'], prefix+joint['id'], laboratory['level_id'],
                    {'id': joint['id'], 'type': 'prismatic' if joint['type'] == 'slider' else joint['type'],
                     'origin_mm': robot.transform(world, numbers(joint['origin'])),
                     'axis': [sum(world[i][j]*joint['axis'][j] for j in range(3)) for i in range(3)],
                     'limits_mm' if joint['type'] == 'slider' else 'limits_deg': list(states[joint['id']].values())},
                    [device['body_prefix']+body['id'] for body in bodies], values, initial,
                    eye, target, laboratory['room'], label)
                obj.update(front=front, mechanism='equipment', asset=item['asset'])
                obj['state_labels']['reference'] = 'Teilweise geöffnet'
                for command, requirements in guards[joint['id']].items():
                    obj['commands'][command]['requires'] = [{'object_id': prefix+g['joint'], 'state': g['state']} for g in requirements]
                result.append(obj)
    return result


def dependencies():
    return [Path(__file__), ROOT/'scripts/lab_equipment.py', ROOT/'scripts/instrument_concept.py',
            ROOT/'scripts/tube_cam_model.py', ROOT/'scripts/robot_spec.py']
