"""Derive a browser-only lift from the existing building circulation interface."""
import math

from atrium_seating import body_bounds, combine_bounds
import furniture_articulation as articulation


def validate(source):
    articulation.exact(source, 'id speed'+(' door_duration' if 'door_duration' in source else ''), 'walkthrough elevator')
    if 'door_duration' in source:
        articulation.parameter(source['door_duration'], 's', (.1, 10))
    articulation.require(isinstance(source['id'], str) and source['id'], 'Elevator interface ID required')
    return articulation.parameter(source['speed'], 'mm/s', (100, 3000))


def compile(source, building, parameters, interface, expanded, plan, eye_height):
    speed = validate(source)
    lift = interface['circulation']['elevator']
    articulation.require(source['id'] == lift['id'], 'Existing building elevator required')
    cabins = lift['cabin_body_ids']
    articulation.require(len(cabins) == 1, 'Exactly one moving elevator cabin required')
    bounds = body_bounds([op for op in expanded['operations'] if op['body'] == cabins[0]])[cabins[0]]
    bounds = {'min': list(bounds['min']), 'max': list(bounds['max'])}
    centre = [(a+b)/2 for a, b in zip(bounds['min'], bounds['max'])]
    levels = {level['id']: level for level in interface['levels']}
    reference = lift['cabin_level']
    reference_z = levels[reference]['z_mm']
    walls = {wall['id']: wall for wall in plan['walls']}
    opening = next(item for item in plan['openings']
                   if item['id'] == building['circulation']['elevator']['reference_opening'])
    anchor = walls[opening['wall']]
    a, b = (plan['vertices'][anchor[key]] for key in ('start', 'end'))
    fraction = sum(opening['interval'])/2
    door_y = (a[1]+fraction*(b[1]-a[1]))*parameters['display_scale']
    ports = []
    for port in lift['ports']:
        wall = walls[port['wall']]
        endpoints = [plan['vertices'][wall[key]] for key in ('start', 'end')]
        x = sum(point[0] for point in endpoints)/2*parameters['display_scale']
        outward = -1 if x < centre[0] else 1
        eye_z = port['z_mm']+eye_height
        ports.append({**port,
            'trigger_body_ids': [port['frame_body_id']] if port['active'] else [],
            'cabin_entry_mm': [centre[0], door_y, eye_z],
            'exit_eye_mm': [x+outward*parameters['display_thickness']*2, door_y, eye_z]})
    states = {level: levels[level]['z_mm'] for level in levels
              if any(port['level_id'] == level and port['active'] for port in ports)}
    articulation.require(set(states) == set(levels), 'Every served lift floor needs an active port')
    limits = [min(states.values()), max(states.values())]
    object_id = lift['id']+'.Cabin.Travel'
    viewpoint = next(port for port in ports if port['level_id'] == reference and port['active'])
    obj = {'id': object_id, 'label': 'Aufzug', 'scene': 'building', 'level_id': reference,
        'joint': {'id': 'Travel', 'type': 'prismatic', 'origin_mm': centre,
                  'axis': [0, 0, 1], 'limits_mm': limits},
        'front': [1, 0, 0], 'moving_body_ids': cabins+lift.get('fittings', {}).get('attached_body_ids', []),
        'states': states, 'reference_state': reference,
        'commands': {key: {'label': value['label'], 'target_state': key}
                     for key, value in levels.items()},
        'view_label': 'Aufzug ansehen',
        'state_labels': {**{key: value['label'] for key, value in levels.items()}, 'moving': 'Fahrt'},
        'duration_s': 1.875*(limits[1]-limits[0])/speed,
        'viewpoint': {'eye_mm': viewpoint['exit_eye_mm'],
                      'target_mm': viewpoint['cabin_entry_mm']},
        'basis': 'presentation_assumption',
        'qualification': {'lift_operation_implemented': False, 'collision_checked': False}}
    config = {'object_id': object_id, 'speed_mm_s': speed,
        'speed_basis': 'Peak synthetic presentation speed; quintic duration is 1.875*distance/speed',
        'reference_level': reference, 'reference_z_mm': reference_z,
        'cabin_bounds_mm': bounds, 'ports': ports,
        'lift_operation_implemented': False}
    if lift.get('shaft_body_ids'):
        shaft = body_bounds([op for op in expanded['operations'] if op['body'] in lift['shaft_body_ids']])
        articulation.require(set(shaft) == set(lift['shaft_body_ids']), 'Complete native-source shaft envelope required')
        config['shaft_bounds_mm'] = combine_bounds(shaft.values())
    for port in ports:
        articulation.require(all(math.isfinite(v) for v in port['cabin_entry_mm']+port['exit_eye_mm']),
                             'Finite source-derived lift ports required')
    if 'fittings' in lift:
        articulation.require('door_duration' in source, 'Lift doors require an explicit motion duration')
        door_objects = []
        for group in lift['fittings']['door_groups']:
            cabin = group['parent'] == 'cabin'
            port = None if cabin else next(port for port in ports if port['id'] == group['port_id'])
            door_objects.append({'id': group['id'], 'label': 'Aufzugtür', 'scene': 'building',
                'level_id': reference if cabin else port['level_id'], 'joint': group['joint'],
                'parent_object_id': object_id if cabin else None, 'mechanism': 'lift_door',
                'side': group['side'], 'port_id': group['port_id'], 'front': [1, 0, 0],
                'moving_body_ids': group['moving_body_ids'],
                'states': dict(zip(('closed', 'open'), group['joint']['limits_mm'])), 'reference_state': 'closed',
                'commands': {name: {'label': label, 'target_state': state}
                             for name, label, state in [('open', 'Öffnen', 'open'), ('close', 'Schließen', 'closed')]},
                'state_labels': {'closed': 'Geschlossen', 'opening': 'Wird geöffnet', 'open': 'Offen', 'closing': 'Wird geschlossen'},
                'duration_s': articulation.parameter(source['door_duration'], 's', (.1, 10)),
                'view_label': 'Aufzugtür ansehen', 'basis': 'presentation_assumption',
                'qualification': {'lift_operation_implemented': False, 'collision_checked': False}})
        config['door_objects'] = door_objects
        config['fittings'] = lift['fittings']['placements']
        for port in ports:
            port['door_object_ids'] = [door['id'] for door in door_objects
                if port['active'] and door['side'] == port['side'] and (door['port_id'] == port['id'] or door['parent_object_id'] == object_id)]
            port['trigger_body_ids'] += [body for door in door_objects if door['port_id'] == port['id'] for body in door['moving_body_ids']]
    return obj, config
