"""Referenced three-arm review composition and portable analytical fixtures."""
import copy
import json
import math
import re
from pathlib import Path

import assembly_model as assembly
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import instrument_concept as instruments
import robot_spec as robot
import solidcraft_vendor as vendor
import synthetic_lab_scene as scene_model
import synthetic_workspace as workspace

ROOT = robot.ROOT
SOURCE = ROOT/'model/two-arm-analytics.shared.json'
KIT = ROOT/'model/analytics-tools.shared.json'
UNITS = {'length': 'mm', 'angle': 'deg'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def kit_load(path=KIT):
    spec = read(path)
    if set(spec) != {'format', 'id', 'units', 'robot_mount', 'cases', 'status', 'limitations'}:
        raise ValueError('Unsupported analytical tool source fields')
    if spec['format'] != 'solidcraftbot.analytics-tools/1' or spec['units'] != UNITS:
        raise ValueError('Analytical tool source contract')
    assembly.validate_reference(spec['robot_mount'])
    fields = {
        'flange_pipette_envelope': {'tcp_length_mm', 'color'},
        'tube_holder_grid': {'rows', 'columns', 'pitch_mm', 'plate_height_mm', 'tube_radius_mm', 'tube_height_mm', 'closed', 'color'},
        'reagent_bottle': {'radius_mm', 'height_mm', 'color'},
        'fresh_tip_grid': {'rows', 'columns', 'pitch_mm', 'color'},
        'wipe_cartridge': {'size_mm', 'color'},
        'corner_post_mount': {'height_mm', 'color'}}
    for case in spec['cases'].values():
        if case.get('operation') not in fields or set(case) != fields[case['operation']] | {'operation'}:
            raise ValueError('Unsupported analytical fixture operation')
        for key, value in case.items():
            if key.endswith('_mm'):
                values = value if isinstance(value, list) else [value]
                if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
                    raise ValueError('Positive finite fixture dimensions required')
            if key in {'rows', 'columns'} and (type(value) is not int or not 1 <= value <= 12):
                raise ValueError('Bounded integer fixture grid required')
        if 'closed' in case and type(case['closed']) is not bool:
            raise ValueError('Tube closure reference must be boolean')
        if not re.fullmatch('#[0-9a-fA-F]{6}', case['color']):
            raise ValueError('Fixture color required')
    return spec


def kit_parts(spec, name):
    """One lowering of each semantic operation, used by both native CADs."""
    case = spec['cases'][name]
    kind, color = case['operation'], case['color']
    parts, frames = [], {}

    def shape(kind, origin, **dimensions):
        return {'kind': kind, 'origin': origin, **dimensions}

    def add(name, primitive, color=color, cuts=None, additions=None, opacity=1):
        parts.append({'id': name, 'shape': primitive, 'cuts': cuts or [], 'additions': additions or [],
                      'appearance': {'color': color, 'opacity': opacity}, 'role': 'unqualified_concept_fixture'})

    def box(origin, size):
        return shape('box', origin, size=size)

    def cyl(origin, radius, height):
        return shape('cylinder', origin, radius=radius, height=height)

    def cone(origin, radius, top_radius, height):
        return shape('cone', origin, radius=radius, top_radius=top_radius, height=height)

    if kind == 'flange_pipette_envelope':
        length = case['tcp_length_mm']
        add('Mount', cyl([0, 0, 0], length/8, length*.03), '#d5a03a')
        add('PipetteBody', cyl([0, 0, length*.03], length*.075, length*.39))
        add('DosingActuatorEnvelope', box([length*.055, -length*.05, length*.05],
                                         [length*.13, length*.10, length*.30]), '#cf9741')
        add('Barrel', cyl([0, 0, length*.42], length*.025, length*.35), '#dce5e8')
        add('TipCone', cone([0, 0, length*.77], length*.025, length*.018, length*.03), '#93b4c7')
        add('PipetteTip', cone([0, 0, length*.80], length*.018, length*.0018, length*.20), '#a9d3df', opacity=.7)
        frames['tcp'] = [0, 0, length]
    elif kind == 'tube_holder_grid':
        rows, cols, pitch = case['rows'], case['columns'], case['pitch_mm']
        radius, height, plate = case['tube_radius_mm'], case['tube_height_mm'], case['plate_height_mm']
        if pitch <= 2*(radius+1) or plate >= height:
            raise ValueError('Tube references need separated mouths above the holder')
        sx, sy = (cols-1)*pitch+pitch*1.5, (rows-1)*pitch+pitch*1.5
        floor, wall, taper = plate/8, radius/10, height/3
        holes = []
        for row in range(rows):
            for col in range(cols):
                x, y = (col-(cols-1)/2)*pitch, (row-(rows-1)/2)*pitch
                index = row*cols+col+1
                holes.append(cyl([x, y, floor], radius+wall, plate))
                tube = cone([x, y, floor], radius*.16, radius, taper)
                additions = [cyl([x, y, floor+taper], radius, height-taper)]
                cuts = [cyl([x, y, floor+taper], radius-wall, height-taper+wall)]
                add('Tube%02d'%index, tube, '#b6d9e5', cuts, additions, .65)
                if case['closed']:
                    add('Cap%02d'%index, cyl([x, y, floor+height], radius+wall, radius/3))
                frames['mouth_%02d'%index] = [x, y, floor+height]
                frames['grip_%02d'%index] = [x, y, floor+height-8]
        add('Holder', box([-sx/2, -sy/2, 0], [sx, sy, plate]), cuts=holes)
    elif kind == 'reagent_bottle':
        radius, height = case['radius_mm'], case['height_mm']
        add('Bottle', cyl([0, 0, 0], radius, height*.8),
            additions=[cone([0, 0, height*.8], radius, radius*.45, height*.2)],
            cuts=[cyl([0, 0, height/8], radius*.85, height*.675),
                  cone([0, 0, height*.8], radius*.85, radius*.32, height*.2),
                  cyl([0, 0, height-1], radius*.32, 2)])
        add('Neck', cyl([0, 0, height], radius*.45, height*.16),
            cuts=[cyl([0, 0, height-1], radius*.32, height*.20)], color='#dde5e5')
        frames['mouth'] = [0, 0, height*1.16]
    elif kind == 'fresh_tip_grid':
        rows, cols, pitch = case['rows'], case['columns'], case['pitch_mm']
        sx, sy, height = (cols-1)*pitch+pitch*1.5, (rows-1)*pitch+pitch*1.5, pitch*2.5
        cuts = []
        for row in range(rows):
            for col in range(cols):
                x, y = (col-(cols-1)/2)*pitch, (row-(rows-1)/2)*pitch
                index = row*cols+col+1
                cuts.append(cyl([x, y, -1], pitch*.12, pitch+2))
                add('FreshTip%02d'%index, cone([x, y, 0], pitch*.025, pitch*.20, height), '#cee0e6', opacity=.7)
                frames['tip_%02d'%index] = [x, y, height]
        add('TipTray', box([-sx/2, -sy/2, 0], [sx, sy, pitch]), cuts=cuts)
    elif kind == 'wipe_cartridge':
        sx, sy, height = case['size_mm']
        add('Cartridge', box([-sx/2, -sy/2, 0], [sx, sy, height]), '#657e88')
        add('FreshWipe', box([-sx*.42, -sy*.42, height], [sx*.84, sy*.84, height*.18]))
    elif kind == 'corner_post_mount':
        arm = robot.load(assembly.validate_reference(spec['robot_mount']))
        base = next(op['primitive'] for link in robot.expanded(arm)['links'] for op in link['recipe']
                    if op.get('body') == 'Base_plate' and op['action'] == 'create')
        width, depth, thickness = [robot.evaluate(v, robot.parameters(arm)) for v in base['size']]
        height, pad = case['height_mm'], min(width, depth)/7
        for index, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
            x, y = sx*(width/2-pad/2), sy*(depth/2-pad/2)
            add('Foot'+str(index), box([x-pad/2, y-pad/2, 0], [pad, pad, thickness/2]))
            add('Post'+str(index), box([x-pad/4, y-pad/4, thickness/2], [pad/2, pad/2, height-thickness]))
            add('Support'+str(index), box([x-pad/2, y-pad/2, height-thickness/2], [pad, pad, thickness/2]))
    return parts, frames


def load(path=SOURCE):
    spec = read(path)
    if set(spec) != {'format', 'id', 'units', 'workspace', 'context', 'arm_tasks', 'limitations'}:
        raise ValueError('Unsupported analytical scene fields')
    if spec['format'] != 'solidcraftbot.two-arm-analytics/1' or spec['units'] != UNITS:
        raise ValueError('Analytical scene contract')
    spatial = workspace.load(assembly.validate_reference(spec['workspace']))
    context = spec['context']
    if set(context) != {'workspace', 'pickup', 'device_ids', 'time_s'} or context['device_ids'] != ['Arm', 'CF01', 'Rack']:
        raise ValueError('CF01 context must select its existing three devices')
    if context['time_s'] != 21.5:
        raise ValueError('This static concept uses the existing CF01 Grasp snapshot at 21.5 s')
    assembly.validate_reference(context['workspace'])
    if assembly.validate_reference(context['pickup']) != pickup.SOURCE:
        raise ValueError('Use the existing CF01 pickup source')
    if pickup.load()['environment'] != context['workspace']:
        raise ValueError('CF01 context source binding mismatch')
    arms = {k: v for k, v in spatial['devices'].items() if v['asset'] == 'arm'}
    if set(arms) != set(spec['arm_tasks']) or len(arms) != 2:
        raise ValueError('Exactly two analytical arms and tasks required')
    variants = [assembly.load_instance(robot, v['source'], v.get('overrides')) for v in arms.values()]
    if variants[0] != variants[1]:
        raise ValueError('Analytical arms must reference one identical arm variant')
    if {v['role'] for v in spec['arm_tasks'].values()} != {'tube_handling', 'pipetting'}:
        raise ValueError('Handling and pipetting roles required')
    kits = {}
    for device in spatial['devices'].values():
        source = device['source']
        if 'case' in source:
            path = assembly.validate_reference(source)
            kit = kits.setdefault(str(path), kit_load(path))
            kit_parts(kit, source['case'])
    for identity, task in spec['arm_tasks'].items():
        if set(task) != {'role', 'tool', 'target_instance', 'target_interface', 'offset_mm'}:
            raise ValueError('Unsupported analytical arm task')
        assembly.validate_reference(task['tool'])
        workspace.pose(task['offset_mm'], 0)
        if task['target_instance'] not in spatial['devices']:
            raise ValueError('Task requires a referenced passive fixture')
        target = spatial['devices'][task['target_instance']]
        part_spec = kit_load(assembly.validate_reference(target['source']))
        if task['target_interface'] not in kit_parts(part_spec, target['source']['case'])[1]:
            raise ValueError('Unknown fixture interface')
    return spec, spatial


def arm_states(spec, spatial):
    result = {}
    for identity, task in spec['arm_tasks'].items():
        item = spatial['devices'][identity]
        arm = assembly.load_instance(robot, item['source'], item.get('overrides'))
        context = copy.deepcopy(pickup.load())
        context['arm_fixture'].update(position_mm=[item['matrix'][i][3] for i in range(3)], yaw_deg=item['yaw_deg'])
        length = context['gripper']['flange_to_grip_mm']
        if task['role'] == 'pipetting':
            source = kit_load(assembly.validate_reference(task['tool']))
            length = kit_parts(source, task['tool']['case'])[1]['tcp'][2]
        context['gripper']['flange_to_grip_mm'] = length
        kin = pickup.Kinematics(arm, context)
        target_item = spatial['devices'][task['target_instance']]
        kit = kit_load(assembly.validate_reference(target_item['source']))
        local = kit_parts(kit, target_item['source']['case'])[1][task['target_interface']]
        point = robot.transform(target_item['matrix'], local)
        point = [a+b for a, b in zip(point, task['offset_mm'])]
        target = pickup.tool_target(point, 0)
        q = kin.inverse(target, context['ik_seed_deg'])
        error = kin.residual(q, target)
        tcp = kin.tool(q)
        result[identity] = {'joints_deg': q, 'world_links': kin.forward(q), 'tcp_matrix': tcp,
                            'flange_matrix': robot.multiply(tcp, workspace.pose([0, 0, -length], 0)),
                            'target_mm': point, 'position_error_mm': math.sqrt(sum(e*e for e in error[:3])),
                            'orientation_error_deg': math.degrees(math.sqrt(sum(e*e for e in error[3:]))/100),
                            'tool_length_mm': length, 'limits_deg': kin.limits,
                            'passed': all(lo <= v <= hi for v, (lo, hi) in zip(q, kin.limits)) and math.sqrt(sum(e*e for e in error)) < .04}
    return result


def primitive_commands(identity, parts, matrix, component_suffix=''):
    prefix = re.sub(r'[^A-Za-z0-9_]', '_', identity)+'_'
    commands, manifest = [], []
    for part in parts:
        name = prefix+part['id']
        operations = [('new', part['shape']), *[('join', s) for s in part.get('additions', [])],
                      *[('cut', s) for s in part.get('cuts', [])]]
        for i, (operation, shape) in enumerate(operations):
            args = {'name': name+'_'+str(i), 'operation': operation}
            args.update({'body_name': name} if i == 0 else {'targets': [name]})
            if shape['kind'] == 'box':
                args.update(corner=shape['origin'], **dict(zip(['length', 'width', 'height'], shape['size'])))
            else:
                args.update(base=shape['origin'], axis=[0, 0, 1], radius=shape['radius'], height=shape['height'])
                if shape['kind'] == 'cone':
                    args['top_radius'] = shape['top_radius']
            commands.append({'command': 'solid.'+shape['kind'], 'params': args})
        commands.append({'command': 'appearance.assign', 'params': {'bodies': [name], **part['appearance']}})
        manifest.append({'instance': identity, 'source_body': part['id'], 'names': [name]})
    component = prefix+'Frame'+component_suffix
    commands.extend([{'command': 'component.create', 'params': {'name': component, 'parent': 'root', 'activate': False, 'grounded': True}},
                     {'command': 'component.move_bodies', 'params': {'component': component, 'bodies': [n for b in manifest for n in b['names']]}},
                     {'command': 'occurrence.move', 'params': {'occurrence': component+':1', 'space': 'world', 'matrix': matrix, 'move_grounded': True}}])
    return commands, manifest


def namespace(commands, identity, parameters, names):
    prefix = re.sub(r'[^A-Za-z0-9_]', '_', identity)+'_'
    names = set(names) | set(parameters)
    names.update(c['params']['name'] for c in commands if 'name' in c['params'])
    mapping = {n: prefix+n for n in names}
    expression = re.compile(r'\b('+'|'.join(map(re.escape, parameters))+r')\b')

    def rename(value):
        if isinstance(value, str):
            return mapping[value] if value in mapping else expression.sub(lambda m: mapping[m[0]], value)
        if isinstance(value, list):
            return [rename(v) for v in value]
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        return value
    result = []
    for original in commands:
        if original['command'].startswith('joint.') or original['command'] == 'document.metadata.set':
            continue
        command = rename(original)
        if command['command'] == 'component.create':
            command['params']['grounded'] = True
        result.append(command)
    return result, mapping


def arm_commands(item, state, sections):
    arm = assembly.load_instance(robot, item['source'], item.get('overrides'))
    expanded = robot.expanded(arm)
    bodies = [{'id': op['body'], 'group': link['id'], 'role': op['role']}
              for link in expanded['links'] for op in link['recipe'] if op['action'] == 'create']
    excluded = {b['id'] for b in bodies if b['role'] == 'viewing_cone'}
    commands, aliases = vendor.replace_imports(robot.solidcraft_commands(arm), sections)
    kept = []
    for command in commands:
        command = copy.deepcopy(command)
        args = command['params']
        if args.get('body_name') in excluded or args.get('body') in excluded:
            continue
        for field in ['bodies', 'targets']:
            if field in args:
                args[field] = [n for n in args[field] if n not in excluded]
                if not args[field]:
                    break
        else:
            kept.append(command)
    names = [n for b in bodies for n in aliases.get(b['id'], [b['id']])]
    commands, mapping = namespace(kept, item['id'], arm['parameters'], names)
    for group, matrix in state['world_links'].items():
        commands.append({'command': 'occurrence.move', 'params': {'occurrence': mapping[group]+':1', 'space': 'world', 'matrix': matrix, 'move_grounded': True}})
    manifest = [{'instance': item['id'], 'source_body': b['id'], 'names': [mapping[n] for n in aliases.get(b['id'], [b['id']])]}
                for b in bodies if b['id'] not in excluded]
    return commands, manifest


def source_dependencies(path=SOURCE):
    found = set()

    def visit(path):
        path = Path(path)
        if path in found:
            return
        found.add(path)

        def walk(value):
            if isinstance(value, dict):
                if isinstance(value.get('source'), str) and value['source'].startswith('model/'):
                    visit(assembly.validate_reference(value))
                else:
                    for child in value.values():
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(read(path))
    visit(path)
    return sorted(found)
