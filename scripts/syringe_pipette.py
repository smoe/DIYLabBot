"""One portable construction source for the unqualified SP01 air pipette."""
import ast
import copy
import json
import math
from pathlib import Path

import robot_spec
import tube_carrier_model as portable
from tube_cam_model import matrix as component_matrix, pose_change_point

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/syringe-pipette.shared.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate
DRIVERS = {'radiusFine', 'radiusCoarse', 'glassWall', 'spacing', 'axisZ',
           'pipeBore', 'pipeWall', 'headSeatRadius', 'headTravel', 'valveAngle'}
JOINTS = {'StrokeFine', 'StrokeCoarse', 'ValveFine', 'ValveCoarse', 'HeadRemoval'}


def materialize(spec):
    """Derive strokes once from semantic capacities; 1 uL equals 1 mm^3."""
    result = copy.deepcopy(spec)
    for row in result['syringes']:
        radius = row['radius_parameter']
        result['parameters'][row['stroke_parameter']] = {
            'expression': f'{row["nominal_capacity_ul"]}/({math.pi}*{radius}*{radius})',
            'unit': 'mm', 'range': [30, 85],
            'description': 'Derived nominal geometric stroke; not a dosing calibration'}
    return result


def load(path=SOURCE):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    required = {'format', 'id', 'recipe', 'status', 'units', 'target_volume_ul',
                'parameters', 'syringes', 'tip_heads', 'default_head', 'poses',
                'default_pose', 'air_path', 'qualification', 'open_requirements',
                'connections', 'limitations'}
    if (set(raw) != required or raw['format'] != 'solidcraftbot.syringe-pipette/1'
            or raw['recipe'] != 'isolated_air_syringes_and_exchangeable_head/1'
            or raw['units'] != {'length': 'mm', 'angle': 'deg', 'volume': 'uL'}):
        raise ValueError('Unsupported SP01 source contract')
    if set(raw['parameters']) != DRIVERS or raw['target_volume_ul'] != [1, 1000]:
        raise ValueError('Unsupported SP01 parameters or target range')
    qualification = {'dimensions_measured', 'dosing_accuracy_verified', 'leakage_verified',
                     'luer_conformity_verified', 'tip_compatibility_verified',
                     'actuation_implemented', 'robot_mount_verified'}
    if (set(raw['qualification']) != qualification
            or any(type(v) is not bool or v for v in raw['qualification'].values())):
        raise ValueError('SP01 performance and dimensions remain unqualified')
    unknowns = {'fine_syringe_article', 'coarse_syringe_article', 'valve_article',
                'tip_articles', 'actual_syringe_dimensions_mm', 'permitted_dose_error_ul',
                'permitted_repeatability_cv_percent', 'permitted_leak_rate_ul_s',
                'test_pressure_kpa', 'hold_time_s', 'liquid_and_temperature',
                'motor_torque_and_drive_pitch', 'seals_and_tolerances'}
    if (set(raw['open_requirements']) != unknowns
            or any(v is not None for v in raw['open_requirements'].values())):
        raise ValueError('Unresolved physical requirements must remain null')
    if [(v['id'], v['nominal_capacity_ul'], v['radius_parameter'], v['stroke_parameter'])
        for v in raw['syringes']] != [('Fine', 1000, 'radiusFine', 'strokeFine'),
                                    ('Coarse', 10000, 'radiusCoarse', 'strokeCoarse')]:
        raise ValueError('The two independent nominal syringe classes are required')
    if set(raw['tip_heads']) != {'micro', 'macro'} or raw['default_head'] not in raw['tip_heads']:
        raise ValueError('Both exchangeable illustrative head profiles are required')
    for profile in raw['tip_heads'].values():
        for name in ('tip_length_mm', 'tip_top_radius_mm', 'tip_exit_radius_mm', 'wall_mm', 'cone_radius_mm'):
            value = profile[name]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid head dimension: '+name)
        if (profile['wall_mm'] >= profile['tip_exit_radius_mm']
                or profile['tip_exit_radius_mm'] >= profile['tip_top_radius_mm']
                or profile['cone_radius_mm'] <= profile['tip_top_radius_mm']):
            raise ValueError('Invalid hollow tip or adapter profile')
    if set(raw['poses']) != {'park', 'fine', 'coarse', 'both_closed', 'head_removed'}:
        raise ValueError('Required isolation and head-exchange states are missing')
    if raw['air_path'] != {'branches': [
            {'syringe': 'Fine', 'isolation_joint': 'ValveFine'},
            {'syringe': 'Coarse', 'isolation_joint': 'ValveCoarse'}],
            'common_node': 'Manifold', 'outlet': 'TipHead', 'selector_valve_implemented': False}:
        raise ValueError('Each air branch needs its own isolation valve')
    spec = materialize(raw)
    p = parameters(spec)
    for name in spec['poses']:
        pose(spec, p, name)
    return spec


def parameters(spec, overrides=None):
    overrides = overrides or {}
    if set(overrides)-DRIVERS:
        raise ValueError('Only independent construction parameters may be overridden')
    for name in DRIVERS:
        definition = spec['parameters'][name]
        value = overrides.get(name, definition['expression'])
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not definition['range'][0] <= value <= definition['range'][1]):
            raise ValueError('Invalid independent parameter: '+name)
    p = robot_spec.parameters(spec, overrides)
    for name, definition in spec['parameters'].items():
        unit = 'deg' if name == 'valveAngle' else 'mm'
        if (definition['unit'] != unit or not definition['range'][0] <= p[name] <= definition['range'][1]):
            raise ValueError('Parameter outside declared range or units: '+name)
    for row in spec['syringes']:
        swept = math.pi*p[row['radius_parameter']]**2*p[row['stroke_parameter']]
        if abs(swept-row['nominal_capacity_ul']) > 1e-8:
            raise ValueError('Derived stroke must preserve the nominal geometric capacity')
    return p


def cad_spec(spec, p):
    """Bridge to the existing linear primitive adapter; restore native formulas after build."""
    result = copy.deepcopy(spec)
    for row in result['syringes']:
        name = row['stroke_parameter']
        result['parameters'][name]['expression'] = p[name]
    return result


def native_parameter_expressions(spec, prefix='ModelParameters.'):
    return {v['stroke_parameter']: f'{v["nominal_capacity_ul"]} mm^3 / '
            f'({math.pi} * {prefix}{v["radius_parameter"]} * {prefix}{v["radius_parameter"]})'
            for v in spec['syringes']}


def selected_head(spec, head=None):
    head = spec['default_head'] if head is None else head
    if not isinstance(head, str) or head not in spec['tip_heads']:
        raise ValueError('Unknown exchangeable head')
    return head


def expanded(spec, p, head=None):
    head = selected_head(spec, head)
    s = {'id': spec['id'], 'status': spec['status'], 'parameter_values': p,
         'components': [{'id': 'Frame', 'grounded': True}], 'bodies': [],
         'operations': [], 'joints': []}

    def body(name, kind, origin, color='#637e8d', component='Frame',
             role='assumed_structure', opacity=1, **shape):
        s['bodies'].append({'id': name, 'component': component, 'role': role,
                            'appearance': {'color': color, 'opacity': opacity}})
        op(name, name, kind, origin, **shape)
        return name

    def op(name, target, kind, origin, action='create', **shape):
        s['operations'].append({'id': name, 'body': target, 'action': action,
                                'shape': {'kind': kind, 'origin': origin, **shape}})

    def box(name, origin, size, **kw):
        return body(name, 'box', origin, size=size, **kw)

    def cyl(name, origin, radius, height, axis=(0, 1, 0), **kw):
        return body(name, 'cylinder', origin, radius=radius, height=height, axis=list(axis), **kw)

    def bore(name, target, origin, radius, height, axis=(0, 1, 0)):
        op(name, target, 'cylinder', origin, action='cut', radius=radius,
           height=height, axis=list(axis))

    def pipe(name, origin, length, axis=(0, 1, 0)):
        cyl(name, origin, 'pipeBore+pipeWall', length, axis, color='#acbdc3', role='air_line_envelope')
        bore(name+'_Bore', name, origin, 'pipeBore', length, axis)

    def joint(name, group, kind, origin, axis, limit, reference=(1, 0, 0)):
        s['components'].append({'id': group, 'grounded': False})
        s['joints'].append({'id': name, 'type': kind, 'parent': 'Frame', 'child': group,
                            'origin': origin, 'axis': list(axis), 'reference_x': list(reference),
                            'limit_parameter': limit,
                            'limits_deg' if kind == 'revolute' else 'limits_mm': [0, p[limit]]})

    box('MountingPlate', ['-spacing/2-40', -45, 0], ['spacing+80', 255, 6], color='#d5dfe3')
    box('ControllerEnvelope', [-22, 150, 6], [44, 48, 26], color='#334b5b', role='unimplemented_controller')
    for row in spec['syringes']:
        tag, r, stroke, x, color = (row[k] for k in
            ('id', 'radius_parameter', 'stroke_parameter', 'x_expression', 'color'))
        plunger, rotor = 'Plunger'+tag, 'Rotor'+tag
        joint('Stroke'+tag, plunger, 'slider', [x, -43, 'axisZ'], (0, 1, 0), stroke)
        joint('Valve'+tag, rotor, 'revolute', [x, -68, 'axisZ'], (0, 0, 1), 'valveAngle')
        cyl('Glass'+tag, [x, -45, 'axisZ'], r+'+glassWall', stroke+'+8',
            color='#b6d9e4', opacity=.32, role='unmeasured_glass_barrel')
        bore('Glass'+tag+'_Interior', 'Glass'+tag, [x, -45, 'axisZ'], r, stroke+'+8')
        cyl('Nose'+tag, [x, -53, 'axisZ'], r+'+glassWall', 8, color='#d4e1e1', role='syringe_end_envelope')
        bore('Nose'+tag+'_Air', 'Nose'+tag, [x, -53, 'axisZ'], 'pipeBore', 8)
        cyl('LuerEnvelope'+tag, [x, -59, 'axisZ'], 4.5, 6, color=color, role='unverified_luer_lock_envelope')
        bore('LuerEnvelope'+tag+'_Air', 'LuerEnvelope'+tag, [x, -59, 'axisZ'], 'pipeBore', 6)
        for suffix, y in [('Front', -43), ('Rear', stroke+'-41')]:
            cyl('Clamp'+tag+suffix, [x, y, 'axisZ'], r+'+glassWall+3', 4, color=color)
            bore('Clamp'+tag+suffix+'_Clearance', 'Clamp'+tag+suffix,
                 [x, y, 'axisZ'], r+'+glassWall+0.2', 4)
            box('Support'+tag+suffix, [f'({x})-3', y, 6], [6, 4, f'axisZ-({r})-glassWall-5.8'], color=color)
        cyl('Seal'+tag, [x, -43, 'axisZ'], r+'-0.08', 3,
            color='#f0eee4', component=plunger, role='illustrative_unqualified_piston_seal')
        cyl('PlungerRod'+tag, [x, -40, 'axisZ'], 1.2, 120, color='#a9b7be', component=plunger)
        box('Carriage'+tag, [f'({x})-8', 76, 'axisZ-4'], [16, 8, 42], color=color, component=plunger)
        bore('Carriage'+tag+'_ScrewClearance', 'Carriage'+tag,
             [x, 75, 'axisZ+30'], 2.2, 10)
        cyl('LeadScrewEnvelope'+tag, [x, 65, 'axisZ+30'], 2, 115,
            color='#9ba9b1', role='unselected_spindle_envelope')
        box('MotorEnvelope'+tag, [f'({x})-15', 180, 'axisZ+15'], [30, 30, 30],
            color='#344953', role='unselected_motor_envelope')
        box('MotorSupport'+tag, [f'({x})-15', 190, 6], [30, 15, 'axisZ+9'], color='#8298a4')
        box('NamePlate'+tag, [f'({x})-14', 160, 6], [28, 14, 2], color=color, role='capacity_class_marker')
        # A through-bored rotor is distinct from its fixed housing and independent mate.
        box('ValveBody'+tag, [f'({x})-9', -77, 'axisZ-8'], [18, 18, 16],
            color='#aec1c6', role='isolation_valve_housing')
        bore('ValveBody'+tag+'_RotorCavity', 'ValveBody'+tag,
             [x, -68, 'axisZ-9'], 6.1, 18, (0, 0, 1))
        bore('ValveBody'+tag+'_Air', 'ValveBody'+tag, [x, -78, 'axisZ'], 'pipeBore', 20)
        cyl('ValveRotor'+tag, [x, -68, 'axisZ-7'], 6, 14, (0, 0, 1),
            color=color, component=rotor, role='unqualified_valve_rotor')
        bore('ValveRotor'+tag+'_Air', 'ValveRotor'+tag,
             [x, -75, 'axisZ'], 'pipeBore', 14)
        cyl('ValveStem'+tag, [x, -68, 'axisZ+7'], 2, 5, (0, 0, 1), color=color, component=rotor)
        box('ValveHandle'+tag, [f'({x})-2', -70, 'axisZ+12'], [4, 17, 3], color=color, component=rotor)
        pipe('BranchAir'+tag, [x, -95, 'axisZ'], 18)
    pipe('CommonAir', ['-spacing/2', -95, 'axisZ'], 'spacing', (1, 0, 0))
    # Intersecting tube envelopes must not cap the other branch's drawn lumen.
    for row in spec['syringes']:
        tag, x = row['id'], row['x_expression']
        bore('CommonAir_'+tag+'_Tee', 'CommonAir', [x, -98, 'axisZ'], 'pipeBore', 8)
        bore('BranchAir'+tag+'_Tee', 'BranchAir'+tag,
             [f'({x})-4', -95, 'axisZ'], 'pipeBore', 8, (1, 0, 0))
    bore('CommonAir_HeadTee', 'CommonAir', [0, -95, 'axisZ-4'], 'pipeBore', 8, (0, 0, 1))
    box('Manifold', [-10, -102, 'axisZ-6'], [20, 14, 12], color='#567f8a', role='common_air_manifold')
    bore('Manifold_X', 'Manifold', [-11, -95, 'axisZ'], 'pipeBore', 22, (1, 0, 0))
    bore('Manifold_Z', 'Manifold', [0, -95, 'axisZ-7'], 'pipeBore', 14, (0, 0, 1))
    box('PressureSensorEnvelope', [-7, -101, 'axisZ+7'], [14, 12, 11], color='#31556d', role='unselected_pressure_sensor')
    cyl('HeadReceiver', [0, -95, 'axisZ-21'], 'headSeatRadius', 15, (0, 0, 1),
        color='#bdcbd0', role='common_unqualified_head_interface')
    bore('HeadReceiver_Air', 'HeadReceiver', [0, -95, 'axisZ-21'], 'pipeBore', 15, (0, 0, 1))
    joint('HeadRemoval', 'TipHead', 'slider', [0, -95, 'axisZ-21'], (0, 0, -1), 'headTravel')
    hp = spec['tip_heads'][head]
    cyl('HeadCollar', [0, -95, 'axisZ-33'], 'headSeatRadius', 11.7, (0, 0, 1),
        color=hp['color'], component='TipHead', role='removable_head')
    bore('HeadCollar_Air', 'HeadCollar', [0, -95, 'axisZ-33'], 'pipeBore', 11.7, (0, 0, 1))
    body('TipCone', 'cone', [0, -95, 'axisZ-48'], color=hp['color'], component='TipHead',
         role='unverified_tip_cone', radius=hp['tip_top_radius_mm']-.2,
         top_radius=hp['cone_radius_mm'], height=15, axis=[0, 0, 1])
    bore('TipCone_Air', 'TipCone', [0, -95, 'axisZ-48'], 'pipeBore', 15, (0, 0, 1))
    length = hp['tip_length_mm']
    body('DisposableTip', 'cone', [0, -95, f'axisZ-48-{length}'],
         color='#acd4df', opacity=.5, component='TipHead', role='unqualified_consumable_tip',
         radius=hp['tip_exit_radius_mm'], top_radius=hp['tip_top_radius_mm'], height=length, axis=[0, 0, 1])
    op('DisposableTip_Interior', 'DisposableTip', 'cone', [0, -95, f'axisZ-48-{length}'],
       action='cut', radius=hp['tip_exit_radius_mm']-hp['wall_mm'],
       top_radius=hp['tip_top_radius_mm']-hp['wall_mm'], height=length+.01, axis=[0, 0, 1])
    s['interfaces'] = interfaces(spec, p, head=head)
    return s


def validate_pose(source, values):
    if set(values) != JOINTS:
        raise ValueError('Every independent joint is required')
    for j in source['joints']:
        value = values[j['id']]
        limits = j.get('limits_mm', j.get('limits_deg'))
        if type(value) not in (int, float) or not math.isfinite(value) or not limits[0] <= value <= limits[1]:
            raise ValueError('Invalid joint position: '+j['id'])


def pose(spec, p, name=None):
    name = name or spec['default_pose']
    if name not in spec['poses']:
        raise ValueError('Unknown presentation pose')
    values = {k: evaluate(v, p) for k, v in spec['poses'][name].items()}
    # No recursive expanded/pose validation dependency.
    source = {'joints': [{'id': k, 'limits_mm': [0, p['stroke'+k[6:]] if k.startswith('Stroke')
                         else p['headTravel'] if k == 'HeadRemoval' else p['valveAngle']]} for k in JOINTS]}
    validate_pose(source, values)
    return values


def samples(spec, p):
    result = [{'id': name, 'joint_values': pose(spec, p, name)} for name in spec['poses']]
    for tag in ('Fine', 'Coarse'):
        for step in range(11):
            values = pose(spec, p, 'park');values['Stroke'+tag] = p['stroke'+tag]*(step/10)
            result.append({'id': tag+'_stroke_'+str(step), 'joint_values': values})
        for angle in (0, 45, 90):
            values = pose(spec, p, 'park');values['Valve'+tag] = angle
            result.append({'id': tag+'_valve_'+str(angle), 'joint_values': values})
    return result


def build_samples(spec, p):
    return [{'id': name, 'joint_values': pose(spec, p, name)} for name in spec['poses']]


def interfaces(spec, p, values=None, head=None):
    head = selected_head(spec, head)
    values = values or pose(spec, p)
    hp = spec['tip_heads'][head]
    return {'head_receiver_mm': [0, -95, p['axisZ']-21],
            'head_mating_face_mm': [0, -95, p['axisZ']-21.3-values['HeadRemoval']],
            'tip_tcp_mm': [0, -95, p['axisZ']-48-hp['tip_length_mm']-values['HeadRemoval']],
            'syringes': {row['id']: {'axis_origin_mm': [evaluate(row['x_expression'], p), -45, p['axisZ']],
                'stroke_mm': p[row['stroke_parameter']], 'nominal_capacity_ul': row['nominal_capacity_ul'],
                'geometric_swept_volume_ul': math.pi*p[row['radius_parameter']]**2*p[row['stroke_parameter']],
                'calibrated_dispensed_volume_ul': None} for row in spec['syringes']},
            'qualification': copy.deepcopy(spec['qualification'])}


def geometry_probes(spec, p, values, head=None):
    head = selected_head(spec, head)
    rows = []
    for row in spec['syringes']:
        tag = row['id'];x = evaluate(row['x_expression'], p);z = p['axisZ']
        # Witness centerline only; a blocked line does not qualify a valve seal.
        if values['Valve'+tag] in (0, 90):
            rows.append({'id': tag+'_valve_centerline',
                         'body_ids': ['ValveBody'+tag, 'ValveRotor'+tag],
                         'start_mm': [x, -78, z], 'end_mm': [x, -58, z],
                         'expected': 'clear' if values['Valve'+tag] == 0 else 'blocked'})
        rows.append({'id': tag+'_empty_barrel_axis', 'body_ids': ['Glass'+tag],
                     'start_mm': [x, -45, z], 'end_mm': [x, -37+p[row['stroke_parameter']], z], 'expected': 'clear'})
        rows.append({'id': tag+'_neck_axis', 'body_ids': ['Nose'+tag, 'LuerEnvelope'+tag],
                     'start_mm': [x, -59, z], 'end_mm': [x, -45, z], 'expected': 'clear'})
        rows.append({'id': tag+'_branch_tee', 'body_ids': ['BranchAir'+tag, 'CommonAir'],
                     'start_mm': [x, -95, z], 'end_mm': [x, -77, z], 'expected': 'clear'})
    offset = values['HeadRemoval']
    rows.append({'id': 'common_air_axis', 'body_ids': ['CommonAir', 'Manifold'],
                 'start_mm': [-p['spacing']/2, -95, p['axisZ']],
                 'end_mm': [p['spacing']/2, -95, p['axisZ']], 'expected': 'clear'})
    rows.append({'id': 'fixed_head_outlet', 'body_ids': ['CommonAir', 'Manifold', 'HeadReceiver'],
                 'start_mm': [0, -95, p['axisZ']-21], 'end_mm': [0, -95, p['axisZ']+1], 'expected': 'clear'})
    if offset == 0:
        rows.append({'id': 'attached_head_axis', 'body_ids': ['HeadReceiver', 'HeadCollar'],
                     'start_mm': [0, -95, p['axisZ']-33], 'end_mm': [0, -95, p['axisZ']-6], 'expected': 'clear'})
    rows.append({'id': 'head_air_axis', 'body_ids': ['HeadCollar', 'TipCone', 'DisposableTip'],
                 'start_mm': [0, -95, p['axisZ']-48-spec['tip_heads'][head]['tip_length_mm']-offset],
                 'end_mm': [0, -95, p['axisZ']-21.3-offset], 'expected': 'clear'})
    return rows


def geometry_checks(spec, p, geometry, head=None):
    bodies = {b['body']: b for b in geometry};checks = []
    for row in spec['syringes']:
        tag = row['id'];r = p[row['radius_parameter']];length = p[row['stroke_parameter']]+8
        expected = math.pi*((r+p['glassWall'])**2-r**2)*length
        actual = bodies['Glass'+tag]['volume_mm3']
        checks.append({'id': tag+'_hollow_glass_volume', 'expected_mm3': expected,
                       'actual_mm3': actual, 'passed': abs(actual-expected) < 1e-5})
    return checks


def solidcraft_commands(spec, p, head=None):
    head = selected_head(spec, head)
    class Provider:
        SOURCE = globals()['SOURCE']
        expanded = staticmethod(lambda source, values: expanded(source, values, head))
        pose = staticmethod(pose)
        samples = staticmethod(samples)
        build_samples = staticmethod(build_samples)
    commands = portable.solidcraft_commands(cad_spec(spec, p), p, Provider)
    expressions = native_parameter_expressions(spec, prefix='')
    for command in commands:
        if command['command'] == 'parameters.add' and command['params']['name'] in expressions:
            command['params']['expression'] = expressions[command['params']['name']]
        if command['command'] == 'document.metadata.set':
            command['params'] = {'values': {'org.solidcraftbot.syringe-pipette': {
                'source': str(SOURCE.relative_to(ROOT)), 'source_sha256': digest(SOURCE),
                'head': head, 'qualification': spec['qualification'], 'status': spec['status']}}}
    commands.append({'command': 'browser.visibility', 'params': {'folder': 'sketches', 'visible': False}})
    return commands
