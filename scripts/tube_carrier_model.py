"""H01 semantic source and shared construction operations; no CAD dependencies."""
from pathlib import Path
import copy
import json
import math
import sys
import ast
import robot_spec

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/tube-carrier-h01.shared.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate


def parameters(spec, overrides=None):
    p = robot_spec.parameters(spec, overrides)
    for name, definition in spec['parameters'].items():
        lo, hi = definition['range']
        if definition['unit'] != 'mm' or not lo <= p[name] <= hi:
            raise ValueError('Parameter outside declared range: ' + name)
    return p


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format'] != 'solidcraftbot.tube-carrier/1' or spec['units'] != {'length': 'mm', 'angle': 'deg'}:
        raise ValueError('Unsupported source or units')
    if spec['recipe'] != 'common_shell_keyed_front_dock_and_article_specific_insert_v1':
        raise ValueError('Unknown semantic recipe')
    if [(v['id'], v['bottom']) for v in spec['variants']] != [('V15', 'conical'), ('V20', 'rounded')]:
        raise ValueError('H01 requires both reviewed tube-shape variants')
    p = parameters(spec)
    expanded(spec, p)
    return spec


def expanded(spec, p):
    """Lower common interfaces once, for both independent native CAD adapters."""
    result = {'id': spec['id'], 'status': spec['status'], 'parameters': spec['parameters'],
              'components': [{'id': 'DockFrame', 'grounded': True}], 'bodies': [], 'operations': [], 'joints': []}
    def body(name, component, color, role='structure', opacity=1):
        result['bodies'].append({'id': name, 'component': component, 'role': role,
                                 'appearance': {'color': color, 'opacity': opacity}})
        return name
    def op(name, target, shape, action='create'):
        result['operations'].append({'id': name, 'body': target, 'action': action, 'shape': shape})
    for variant in spec['variants']:
        tag = variant['id']; cx = variant['center_x']; carrier = 'Carrier' + tag; latch = 'DockLatch' + tag
        result['components'] += [{'id': carrier, 'grounded': False}, {'id': latch, 'grounded': False}]
        def box(name, target, size, origin, action='create'):
            op(tag + '_' + name, target, {'kind': 'box', 'size': size,
                'origin': [f'({cx})+({origin[0]})', origin[1], origin[2]]}, action)
        def cylinder(name, target, radius, height, base, action='create'):
            op(tag + '_' + name, target, {'kind': 'cylinder', 'radius': radius, 'height': height,
                'origin': [f'({cx})+({base[0]})', base[1], base[2]]}, action)
        def cone(name, target, radius, top_radius, height, base, action='create'):
            op(tag + '_' + name, target, {'kind': 'cone', 'radius': radius, 'top_radius': top_radius, 'height': height,
                'origin': [f'({cx})+({base[0]})', base[1], base[2]]}, action)
        def sphere(name, target, radius, center, action='create'):
            op(tag + '_' + name, target, {'kind': 'sphere', 'radius': radius,
                'origin': [f'({cx})+({center[0]})', center[1], center[2]]}, action)
        base = body(tag + '_DockBase', 'DockFrame', '#b8c4ce')
        box('Base', base, [44, 50, 6], [-22, -22, 0])
        floor = body(tag + '_DockFloor', 'DockFrame', '#7595a6', 'thermal_contact_concept')
        box('Floor', floor, [30, 36, 2], [-15, -20, 6])
        box('Keyway', floor, [3.6, 38, 2.2], [-12.1, -21, 6.4], 'cut')
        for side in [-1, 1]:
            rail = body(tag + '_Rail' + ('L' if side < 0 else 'R'), 'DockFrame', '#889aab')
            x = -17.4 if side < 0 else 13.4
            box('Rail' + str(side), rail, [4, 22, 6], [x, -10, 8])
            xlip = -17.4 if side < 0 else 11.5
            box('Lip' + str(side), rail, [5.9, 22, 2.5], [xlip, -10, 11.5], 'join')
        stop = body(tag + '_RearStop', 'DockFrame', '#889aab')
        box('Stop', stop, [30, 4, 8], [-15, 12.4, 6])
        lock = body(tag + '_LatchEnvelope', latch, '#e4ac42', 'mechanism_envelope')
        box('Latch', lock, [28, 2, 4], [-14, -14.4, 8])
        shell = body(tag + '_CarrierShell', carrier, '#244b69')
        box('Foot', shell, [26, 24, 3], [-13, -12, 'carrier_bottom_z'])
        box('Housing', shell, [22, 20, 'housing_top_z-carrier_bottom_z-3'],
            [-11, -10, 'carrier_bottom_z+3'], 'join')
        for side in [-1, 1]:
            box('GripPad' + str(side), shell, [7, 10, 8], [-17 if side < 0 else 10, -5, 'grip_pad_z'], 'join')
        box('Key', shell, [3, 18, 1.6], [-11.8, -9, 'carrier_bottom_z-1.4'], 'join')
        cylinder('InsertSocket', shell, 'insert_radius+0.2', 'housing_top_z-carrier_bottom_z+2',
                 [0, 0, 'carrier_bottom_z-1'], 'cut')
        insert = body(tag + '_Insert', carrier, variant['insert_color'], 'article_specific_insert')
        clearance = 'tube_radius+radial_clearance'
        join = 'cone_join_z' if variant['bottom'] == 'conical' else 'tube_bottom_z+tube_radius'
        outer = [[0, 'carrier_bottom_z'], ['insert_radius', 'carrier_bottom_z'], ['insert_radius', 'housing_top_z'],
                 ['insert_radius+1.5', 'housing_top_z'], ['insert_radius+1.5', 'collar_z'], [clearance, 'collar_z']]
        def round_profile(radius):
            return [[f'({radius})*{math.sin(math.radians(angle)):.15g}',
                     f'({join})-({radius})*{math.cos(math.radians(angle)):.15g}'] for angle in spec['rounded_profile_angles_deg']]
        if variant['bottom'] == 'conical':
            cavity = [[clearance, join], ['0.8+radial_clearance', 'tube_bottom_z-radial_clearance'], [0, 'tube_bottom_z-radial_clearance']]
            lower = [[0, 'tube_bottom_z'], [0.8, 'tube_bottom_z'], ['tube_radius', join]]
        else:
            cavity = list(reversed(round_profile(clearance)))
            lower = round_profile('tube_radius')
        op(tag+'_InsertProfile', insert, {'kind': 'revolved_profile', 'center_x': cx, 'points_rz': outer+cavity})
        tube = body(tag + '_ReferenceTube', carrier, '#bfdfeb', 'tube_shape_reference', 0.55)
        tube_profile = lower + [['tube_radius', 'collar_z'], ['collar_radius', 'collar_z'], ['collar_radius', 'collar_z+2'],
                               ['tube_radius-0.7', 'collar_z+2'], ['tube_radius-0.7', 'cone_join_z'], [0, 'cone_join_z']]
        op(tag+'_TubeProfile', tube, {'kind': 'revolved_profile', 'center_x': cx, 'points_rz': tube_profile})
        cap = body(tag + '_CapEnvelope', carrier, '#d6e8f1', 'cap_hinge_envelope', 0.8)
        cylinder('Cap', cap, 5.7, 2, [0, 0, 'collar_z+2'])
        hinge = body(tag + '_HingeEnvelope', carrier, '#d6e8f1', 'cap_hinge_envelope')
        box('Hinge', hinge, [4, 4, 2], [-2, 5, 'collar_z'])
        for side in [-1, 1]:
            clip = body(tag + '_CollarClip' + ('L' if side < 0 else 'R'), carrier, '#efaf47', 'retainer_envelope')
            box('ClipPost' + str(side), clip, [2, 8, 'collar_z+2-housing_top_z+3'],
                [-11.8 if side < 0 else 9.8, -4, 'housing_top_z-3'])
            box('ClipLip' + str(side), clip, [5.6, 8, 1.5],
                [-11.8 if side < 0 else 6.2, -4, 'collar_z+2'], 'join')
        key = body(tag + '_HingeLocator', carrier, '#d38b35', 'orientation_envelope')
        box('HingeBack', key, [8.6, 3, 6], [-4.3, 9.3, 'housing_top_z'])
        for side in [-1, 1]:
            box('HingeSide' + str(side), key, [2, 4, 4], [-4.3 if side < 0 else 2.3, 6.8, 'collar_z-2'], 'join')
        if tag == 'V20':
            tool = body(tag + '_GripperEnvelope', carrier, '#717d89', 'gripper_envelope', 0.75)
            box('GripperBridge', tool, [46.4, 4, 8], [-23.2, -18, 'grip_pad_z+5'])
            for side in [-1, 1]:
                box('GripperFinger' + str(side), tool, [3, 24, 10],
                    [-20.2 if side < 0 else 17.2, -18, 'grip_pad_z-1'], 'join')
        for ident, child, axis, xref, limits in [
                ('Slide' + tag, carrier, [0, -1, 0], [1, 0, 0], [0, p['transfer_travel']]),
                ('Latch' + tag, latch, [1, 0, 0], [0, 1, 0], [0, p['latch_travel']])]:
            result['joints'].append({'id': ident, 'type': 'slider', 'parent': 'DockFrame', 'child': child,
                'origin': [cx, 0, 'carrier_bottom_z'], 'axis': axis, 'reference_x': xref, 'limits_mm': limits})
    if len({b['id'] for b in result['bodies']}) != len(result['bodies']):
        raise ValueError('Duplicate body name')
    for operation in result['operations']:
        shape = numeric_shape(operation['shape'], p)
        if any(shape[k] <= 0 for k in ['radius', 'height'] if k in shape):
            raise ValueError('Nonpositive primitive')
    return result


def numeric_shape(shape, p):
    s = copy.deepcopy(shape)
    if s['kind'] == 'revolved_profile':
        s['center_x'] = evaluate(s['center_x'], p)
        s['points_rz'] = [[evaluate(v, p) for v in point] for point in s['points_rz']]
    for key in ['origin', 'size']:
        if key in s: s[key] = [evaluate(v, p) for v in s[key]]
    for key in ['radius', 'top_radius', 'height']:
        if key in s: s[key] = evaluate(s[key], p)
    return s


def pose(spec, p, name=None):
    return {k: evaluate(v, p) for k, v in spec['poses_mm'][name or spec['display_pose']].items()}


def validate_pose(source, values):
    joints = {j['id']: j for j in source['joints']}
    if set(values) != set(joints): raise ValueError('Pose must specify every slider in mm')
    for name, value in values.items():
        if not math.isfinite(value) or not joints[name]['limits_mm'][0] <= value <= joints[name]['limits_mm'][1]:
            raise ValueError('Slider outside concept limits: ' + name)


def displacement(source, component, values):
    joint = next((j for j in source['joints'] if j['child'] == component), None)
    return [a * values[joint['id']] for a in joint['axis']] if joint else [0, 0, 0]


def samples(spec, p):
    result = [{'id': name, 'values_mm': pose(spec, p, name)} for name in spec['poses_mm']]
    for variant in spec['variants']:
        tag = variant['id']
        for step in range(13):
            values = pose(spec, p, 'both_docked_unlocked')
            values['Slide' + tag] = p['transfer_travel'] * step / 12
            result.append({'id': tag + '_transfer_' + str(step), 'values_mm': values})
        for step in range(5):
            values = pose(spec, p, 'both_docked_locked')
            values['Latch' + tag] = p['latch_travel'] * step / 4
            result.append({'id': tag + '_latch_' + str(step), 'values_mm': values})
    return result


def solidcraft_commands(spec, p, provider=None):
    provider = provider or sys.modules[__name__]
    source = provider.expanded(spec, p); commands = []
    def add(command, **params): commands.append({'command': command, 'params': params})
    for name, definition in spec['parameters'].items():
        derived = any(isinstance(n, ast.Name) for n in ast.walk(ast.parse(str(definition['expression']), mode='eval')))
        unit=definition.get('unit','mm')
        add('parameters.add', name=name, expression=str(definition['expression']) if derived else str(p[name]) + (' '+unit if unit else ''),
            comment=definition['description'] + '; allowed range ' + str(definition['range']) + ' '+unit)
    if hasattr(provider,'native_parameters'):
        for field in provider.native_parameters(spec,p):
            add('parameters.add',name=field['name'],expression=field['expression'] if field['expression'] is not None else str(field['value'])+(' '+field['unit'] if field['unit'] else ''),unit=field['unit'])
    add('document.metadata.set', values={'org.solidcraftbot.tube-carrier': {
        'source': str(provider.SOURCE.relative_to(ROOT)).replace('\\', '/'), 'source_sha256': digest(provider.SOURCE), 'revision': spec['id'], 'status': spec['status']}})
    for operation in source['operations']:
        s = operation['shape']; kind = s['kind']; target = operation['body']
        params = {'operation': operation['action'] if operation['action'] != 'create' else 'new', 'name': operation['id']}
        if operation['action'] == 'create': params['body_name'] = target
        else: params['targets'] = [target]
        if kind == 'polygon_prism':
            add('sketch.create',name=operation['id']+'_Sketch',plane=s['plane'],offset=s['offset'])
            points=[[x,f'-({z})' if s['plane']=='XZ' else z] for x,z in s['points']]
            if s.get('fixed'):points=[[evaluate(v,p) for v in point] for point in points]
            add('sketch.line',points=points,closed=True,infer=False)
            if s.get('fixed'):add('sketch.constraint.fix',entities=['l'+str(i+1) for i in range(len(points))],fixed=True)
            add('sketch.finish');add('solid.extrude',distance=s['depth'],**params)
            continue
        elif kind == 'axis_revolved_profile':
            if s['axis']!='X':raise ValueError('Unsupported revolution axis')
            x,y,z=s['axis_origin']
            add('sketch.create',name=operation['id']+'_Sketch',plane='XY',offset=z)
            add('sketch.line',points=[[str(x),str(y)],[f'({x})+90',str(y)]],construction=True,infer=False)
            add('sketch.line',points=[[f'({x})+({a})',f'({y})+({r})'] for a,r in s['points_ar']],closed=True,infer=False)
            add('sketch.finish');add('solid.revolve',axis='l1',angle='360 deg',**params)
            continue
        elif kind == 'revolved_profile':
            add('sketch.create', name=operation['id']+'_Sketch', plane='XZ')
            add('sketch.line', points=[[s['center_x'], '4'], [s['center_x'], '-60']], construction=True, infer=False)
            add('sketch.line', points=[[f'({s["center_x"]})+({r})', f'-({z})'] for r, z in s['points_rz']], closed=True, infer=False)
            add('sketch.finish')
            add('solid.revolve', axis='l1', angle='360 deg', **params)
            continue
        elif kind == 'box': params.update(corner=s['origin'], **dict(zip(['length', 'width', 'height'], s['size'])))
        elif kind == 'cylinder' and operation['action'] == 'cut' and s.get('axis',[0,0,1])==[0,0,1]:
            # A profile extrusion avoids primitive-boolean tangency failures where
            # the rounded cavity cylinder meets its spherical lower seat.
            add('sketch.create', name=operation['id']+'_Sketch', plane='XY', offset=s['origin'][2])
            add('sketch.circle.center', center=s['origin'][:2], radius=evaluate(s['radius'], p))
            add('sketch.dimension', entities=['c1'], type='radius', value=s['radius'])
            if evaluate(s['origin'][1],p)==0:
                add('sketch.constraint.horizontal_vertical', points=['origin', 'c1.center'], mode='horizontal')
            add('sketch.finish')
            add('solid.extrude', distance=s['height'], **params)
            continue
        elif kind == 'sphere': params.update(center=s['origin'], radius=s['radius'])
        else:
            params.update(base=s['origin'], radius=s['radius'], height=s['height'])
            if 'axis' in s:params['axis']=s['axis']
            if kind == 'cone': params['top_radius'] = s['top_radius']
        add('solid.' + kind, **params)
    for group in source['components']:
        add('component.create', name=group['id'], parent=group.get('parent', 'root'), activate=False, grounded=group['grounded'])
        assigned = [b['id'] for b in source['bodies'] if b['component'] == group['id']]
        if assigned: add('component.move_bodies', component=group['id'], bodies=assigned)
    for b in source['bodies']: add('appearance.assign', bodies=[b['id']], **b['appearance'])
    for joint in source['joints']:
        frame = {'origin': [evaluate(v, p) for v in joint['origin']], 'z': joint['axis'], 'x': joint['reference_x']}
        travel_parameter = joint.get('limit_parameter', 'transfer_travel' if joint['id'].startswith('Slide') else 'latch_travel')
        expression=provider.joint_expression(spec,p,joint) if hasattr(provider,'joint_expression') else None
        add('joint.create', name=joint['id'], type=joint.get('type','slider'), a={'occurrence': joint['parent'], 'frame': frame},
            b={'occurrence': joint['child'], 'frame': frame}, flip=True, values=[expression if expression is not None else 0], limits=[[0, travel_parameter]], quiet=True)
    if hasattr(provider,'coupling_commands'):commands.extend(provider.coupling_commands(spec,p))
    build_samples=provider.build_samples(spec,p) if hasattr(provider,'build_samples') else provider.samples(spec,p)
    for sample in build_samples:
        values=sample.get('joint_values',sample.get('values_mm'))
        if hasattr(provider,'drive_commands'):commands.extend(provider.drive_commands(spec,p,values))
        else:
            for name, value in values.items(): add('joint.drive', joint=name, value=value, quiet=True)
        add('joint.solve')
    if hasattr(provider,'drive_commands'):commands.extend(provider.drive_commands(spec,p,provider.pose(spec,p)))
    else:
        for name, value in provider.pose(spec, p).items(): add('joint.drive', joint=name, value=value, quiet=True)
    add('joint.solve'); add('browser.visibility', folder='joints', visible=False)
    return commands
