"""Dedicated 1 mL pump and fixed wrist tip, referencing the actual arm and SP01."""
import copy
import json
import math
import re
from pathlib import Path

import assembly_model
import pneumatic_hose
import spatial_hose_carrier as carrier
import arm_syringe_clearance as clearance
import arm_syringe_routing as routing
import robot_spec as robot
import syringe_pipette as syringe
import tube_carrier_model as portable
from tube_cam_model import matrix as component_matrix

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/arm-syringe.shared.json'
digest = robot.digest
evaluate = robot.evaluate


def load(path=SOURCE):
    s = json.loads(Path(path).read_text())
    schema = json.loads((ROOT/'model/arm-syringe.schema.json').read_text())
    if not isinstance(s, dict) or set(s) != set(schema['required']):
        raise ValueError('Unsupported arm-syringe source fields')
    for name, definition in schema['properties'].items():
        if 'const' in definition and s[name] != definition['const']:
            raise ValueError('Unsupported dedicated 1 mL source field: '+name)
    for key in ('robot', 'syringe_library', 'hose_carrier'):
        if not isinstance(s[key], dict) or set(s[key]) != {'source', 'source_sha256'}:
            raise ValueError('A pinned assembly reference is required: '+key)
        path = assembly_model.validate_reference(s[key])
        if key == 'hose_carrier':
            carrier.load(path)
    if (s['head_mount']['changeable_during_operation'] is not False
            or s['inspiration']['inspected'] is not False):
        raise ValueError('Fixed tooling and uninspected inspiration must remain explicit')
    qualifiers = {'dimensions_measured', 'dosing_accuracy_verified', 'leakage_verified',
                  'actuator_force_verified', 'mount_strength_verified',
                  'hose_full_range_verified', 'hardware_execution_implemented'}
    if (not isinstance(s['qualification'], dict) or set(s['qualification']) != qualifiers
            or any(type(v) is not bool or v for v in s['qualification'].values())):
        raise ValueError('Hardware performance remains unqualified')
    if (not isinstance(s['open_requirements'], dict)
            or set(s['open_requirements']) != set(schema['properties']['open_requirements']['required'])
            or any(v is not None for v in s['open_requirements'].values())):
        raise ValueError('Physical measurements and acceptance limits remain open')
    if (not isinstance(s['states'], dict)
            or not set(schema['properties']['states']['required']) <= set(s['states'])
            or any(not re.fullmatch(r'[a-z][a-z0-9_]*', name) for name in s['states'])):
        raise ValueError('All existing named static inspection configurations are required')
    a = arm(s)
    window = s['operating_window_deg']
    if (not isinstance(window, dict) or set(window) != {j['id'] for j in a['joints']}
            or s['operating_window_status'] != 'Tooling usage assumption; not robot limits or hardware qualification'):
        raise ValueError('A complete tooling operating window is required')
    for joint in a['joints']:
        value = window[joint['id']]
        if (not isinstance(value, dict) or set(value) != {'range', 'reason'}
                or not isinstance(value['range'], list) or len(value['range']) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in value['range'])
                or not joint['limits_deg'][0] <= value['range'][0] < value['range'][1] <= joint['limits_deg'][1]
                or not isinstance(value['reason'], str) or not value['reason']):
            raise ValueError('Invalid tooling operating window: '+joint['id'])
    if s['default_state'] not in s['states']:
        raise ValueError('Unknown default inspection state')
    for row in s['states'].values():
        if (not isinstance(row, dict) or not {'joints_deg', 'stroke_fraction', 'valve_deg'} <= set(row)
                or set(row)-{'joints_deg', 'stroke_fraction', 'valve_deg', 'hard_end_reference'}
                or not isinstance(row['joints_deg'], list) or len(row['joints_deg']) != 6
                or type(row['stroke_fraction']) not in (int, float)
                or not math.isfinite(row['stroke_fraction']) or not 0 <= row['stroke_fraction'] <= 1):
            raise ValueError('Invalid static inspection configuration')
        for q, joint in zip(row['joints_deg'], a['joints']):
            lo, hi = window[joint['id']]['range']
            if type(q) not in (int, float) or not math.isfinite(q) or not lo <= q <= hi:
                raise ValueError('Arm configuration outside tooling operating window')
        if type(row['valve_deg']) not in (int, float) or row['valve_deg'] not in (0, 90):
            raise ValueError('Inspection valve state must be open or closed')
        if 'hard_end_reference' in row and (row['hard_end_reference'] is not True or row['stroke_fraction'] not in (0, 1)):
            raise ValueError('Hard-end references must explicitly identify a piston hard end')
    if (not isinstance(s['limitations'], list) or not s['limitations']
            or any(not isinstance(value, str) or not value for value in s['limitations'])):
        raise ValueError('Concept limitations must be retained')
    p = parameters(s)
    for row in s['states'].values():
        stroke = row['stroke_fraction']*p['strokeFine']
        if not row.get('hard_end_reference') and not p['strokeReserve'] <= stroke <= p['strokeFine']-p['strokeReserve']:
            raise ValueError('State piston stroke is outside the reserved operating window')
    design = s['hose_length_design']
    numbers = {'scan_max_step_deg', 'max_service_loop_mm', 'loop_sample_step_mm', 'cut_resolution_mm',
               'clearance_sample_step_mm', 'clearance_minimum_step_mm'}
    if (not isinstance(design, dict) or set(design) != numbers | {'allowances', 'scope'}
            or any(type(design[k]) not in (int, float) or not math.isfinite(design[k]) or design[k] <= 0
                   for k in numbers)
            or design['clearance_minimum_step_mm'] > design['clearance_sample_step_mm']
            or design['loop_sample_step_mm'] > design['max_service_loop_mm']
            or not isinstance(design['scope'], str) or not design['scope']):
        raise ValueError('Explicit sampled hose-length design assumptions are required')
    ids = set()
    if not isinstance(design['allowances'], list) or not design['allowances']:
        raise ValueError('Itemized hose cutting allowances are required')
    for item in design['allowances']:
        if (not isinstance(item, dict) or set(item) != {'id', 'value_mm', 'reason'}
                or not isinstance(item['id'], str) or not item['id'] or item['id'] in ids
                or type(item['value_mm']) not in (int, float) or not math.isfinite(item['value_mm'])
                or item['value_mm'] < 0 or not isinstance(item['reason'], str) or not item['reason']):
            raise ValueError('Every cutting allowance needs a unique id, finite value and reason')
        ids.add(item['id'])
    connection_interfaces(s, p)
    tip_seat(s, p)
    validate_route_source(s, p, a)
    return s


def arm(spec):
    return robot.load(ROOT/spec['robot']['source'])


def library(spec):
    return syringe.load(ROOT/spec['syringe_library']['source'])


def parameters(spec, overrides=None):
    overrides = overrides or {}
    required = {'outboard', 'pitch', 'hoseInnerRadius', 'hoseOuterRadius',
                'hoseLength', 'hoseBendRadius', 'strokeReserve',
                'socketRadialClearance', 'hoseInsertionDepth', 'strainReliefLength',
                'connectorStraightLead', 'tipEngagementLength', 'tipTaperRelief'}
    if not isinstance(spec['parameters'], dict) or set(spec['parameters']) != required:
        raise ValueError('All declared arm-pump parameters are required')
    if set(overrides)-set(spec['parameters']):
        raise ValueError('Unknown arm-pump parameter')
    p = syringe.parameters(library(spec))
    for name, definition in spec['parameters'].items():
        if (not isinstance(definition, dict)
                or set(definition) != {'value', 'unit', 'range', 'meaning'}
                or not isinstance(definition['range'], list) or len(definition['range']) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                       for v in definition['range'])
                or definition['range'][0] > definition['range'][1]
                or not isinstance(definition['meaning'], str) or not definition['meaning']):
            raise ValueError('Invalid arm-pump parameter definition: '+name)
        value = overrides.get(name, definition['value'])
        if (type(value) not in (int, float) or not math.isfinite(value)
                or definition['unit'] != 'mm' or not definition['range'][0] <= value <= definition['range'][1]):
            raise ValueError('Invalid arm-pump dimension: '+name)
        p[name] = float(value)
    if p['hoseOuterRadius'] <= p['hoseInnerRadius']:
        raise ValueError('Tube requires a positive wall thickness')
    if p['hoseBendRadius'] < 12:
        raise ValueError('The provisional bare-hose minimum radius is 12 mm')
    if p['socketRadialClearance'] <= 0 or p['tipTaperRelief'] <= 0:
        raise ValueError('Socket clearance and tip taper relief must be positive')
    if p['outboard']-p['axisZ']-25 < 5:
        raise ValueError('The clamp needs positive clearance beyond the arm plate edge')
    if not 0 < p['strokeReserve'] < p['strokeFine']/2:
        raise ValueError('Stroke reserve must leave a positive piston operating span')
    p['maxMotorAngle'] = 360*p['strokeFine']/p['pitch']
    return p


def connection_interfaces(spec, p, component_matrices=None):
    """Material ends, junctions and supported exits from one socket definition.

    The tube bottoms on the annular floor. The finite positive OD gap is an
    assumed compression/ferrule interface, not a demonstrated pneumatic seal.
    """
    source = spec['connections']
    if (set(source) != {'kind', 'status', 'pump', 'tip'}
            or source['kind'] != 'tube_in_socket' or not source['status']):
        raise ValueError('Explicit tube-in-socket connection definitions are required')
    records = {}
    for key in ('pump', 'tip'):
        row = source[key]
        if set(row) != {'body', 'clamp_body', 'component', 'floor', 'outward', 'x', 'outer_radius_mm', 'through_length_mm'}:
            raise ValueError('Invalid socket definition: '+key)
        floor = [evaluate(v, p) for v in row['floor']]
        out = pneumatic_hose._unit([evaluate(v, p) for v in row['outward']])
        x = pneumatic_hose._unit([evaluate(v, p) for v in row['x']])
        if abs(sum(a*b for a, b in zip(out, x))) > 1e-9:
            raise ValueError('Socket frame axes must be perpendicular')
        socket = p['hoseOuterRadius']+p['socketRadialClearance']
        if not socket < row['outer_radius_mm'] or row['through_length_mm'] <= 0:
            raise ValueError('Socket needs a positive wall and through-bore length')
        at = lambda d: [v+d*a for v, a in zip(floor, out)]
        y = pneumatic_hose._cross(out, x)
        wall_radius = (p['hoseInnerRadius']+p['hoseOuterRadius'])/2
        witness = [[v+wall_radius*(math.cos(t)*a+math.sin(t)*b)
                    for v, a, b in zip(floor, x, y)] for t in (0, math.pi/2, math.pi, 3*math.pi/2)]
        record = {'body': row['body'], 'clamp_body': row['clamp_body'], 'component': row['component'], 'outward': out, 'x_axis': x,
                  'material_end_mm': floor, 'pneumatic_junction_mm': floor,
                  'socket_mouth_mm': at(p['hoseInsertionDepth']),
                  'unsupported_exit_mm': at(p['hoseInsertionDepth']+p['strainReliefLength']),
                  'bend_start_mm': at(p['hoseInsertionDepth']+p['strainReliefLength']+p['connectorStraightLead']),
                  'floor_witness_points_mm': witness, 'insertion_depth_mm': p['hoseInsertionDepth'],
                  'radial_clearance_mm': p['socketRadialClearance'], 'socket_radius_mm': socket,
                  'tube_inner_radius_mm': p['hoseInnerRadius'], 'tube_outer_radius_mm': p['hoseOuterRadius'],
                  'outer_radius_mm': row['outer_radius_mm'], 'through_length_mm': row['through_length_mm'],
                  'strain_relief_length_mm': p['strainReliefLength'], 'straight_lead_mm': p['connectorStraightLead'],
                  'seal_qualified': False, 'assumption': source['status']}
        if component_matrices is not None:
            matrix = component_matrices[row['component']]
            for name in ('outward', 'x_axis'):
                record[name] = [sum(matrix[i][j]*record[name][j] for j in range(3)) for i in range(3)]
            for name in ('material_end_mm', 'pneumatic_junction_mm', 'socket_mouth_mm',
                         'unsupported_exit_mm', 'bend_start_mm'):
                record[name] = robot.transform(matrix, record[name])
            record['floor_witness_points_mm'] = [robot.transform(matrix, point) for point in witness]
        records[key] = record
    return records


def tip_seat(spec, p):
    """SP02 shaft fits the existing consumable at one lower seal circle."""
    if spec['tip_seat'] != {'kind': 'relieved_shaft_single_seal_circle',
                           'status': 'Derived SP02 taper seat; insertion, retention force and gas tightness unqualified',
                           'consumable_component': 'ConsumableTip', 'shaft_body': 'TipShaft', 'tip_body': 'DisposableTip'}:
        raise ValueError('Unsupported fixed-tip seat definition')
    hp = library(spec)['tip_heads'][spec['fixed_tip_head']]
    length = hp['tip_length_mm'];engagement = p['tipEngagementLength']
    top = p['axisZ']-48;bottom = top-length
    inner0 = hp['tip_exit_radius_mm']-hp['wall_mm']
    # Preserve the inherited cutter's actual slope, including its .01mm overrun.
    slope = (hp['tip_top_radius_mm']-hp['wall_mm']-inner0)/(length+.01)
    seal_z = top-engagement;seal_r = inner0+slope*(length-engagement)
    mouth_inner = inner0+slope*length;shaft_top = mouth_inner-p['tipTaperRelief']
    if not 0 < engagement < length or not p['pipeBore'] < seal_r < shaft_top < mouth_inner:
        raise ValueError('The derived tip seat requires a hollow relieved taper')
    return {'shaft_body': 'TipShaft', 'tip_body': 'DisposableTip', 'component': 'ConsumableTip',
            'seal_center_mm': [0, -95, seal_z], 'seal_radius_mm': seal_r,
            'tip_top_z_mm': top, 'tip_bottom_z_mm': bottom, 'shaft_top_z_mm': p['axisZ']-33,
            'shaft_mouth_radius_mm': shaft_top, 'tip_mouth_inner_radius_mm': mouth_inner,
            'engagement_length_mm': engagement, 'mouth_radial_relief_mm': p['tipTaperRelief'],
            'shaft_bore_radius_mm': p['pipeBore'], 'tip_inner_slope': slope,
            'tip_inner_exit_radius_mm': inner0, 'tip_tcp_mm': [0, -95, bottom],
            'insertion_force_qualified': False, 'seal_qualified': False}


def route_parameters(spec, p, a=None, mounting=None):
    """Robot dimensions plus the derived zero-pose head air-junction plane."""
    a = arm(spec) if a is None else a
    mounting = mounts(spec, p) if mounting is None else mounting
    point = robot.transform(mounting['WristHead']['zero_transform'],
                            connection_interfaces(spec, p)['tip']['pneumatic_junction_mm'])
    return {**robot.parameters(a), 'tip_air_zero_z': point[2]}


def validate_route_source(spec, p, a):
    config = spec['carrier_routing']
    if (not isinstance(config, dict)
            or set(config) != {'frames', 'sequence', 'guide', 'bare_fit', 'crossings', 'sample_step_mm'}):
        raise ValueError('The framed hose route requires a complete source recipe')
    values = {**route_parameters(spec, p, a), **p, 'serviceLoop': 0}
    def number(value):
        if type(value) not in (int, float, str):
            raise ValueError('Frame dimensions require finite numbers or supported expressions')
        try:
            result = evaluate(value, values)
        except (KeyError, TypeError, SyntaxError, ZeroDivisionError, OverflowError, ValueError) as error:
            raise ValueError('Invalid routing frame expression: '+repr(value)) from error
        if not math.isfinite(result):
            raise ValueError('Frame dimensions must be finite')
        return result
    def vector(value):
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError('A source frame requires three-coordinate vectors')
        return [number(v) for v in value]
    frames = config['frames'];links = {link['id'] for link in a['links']}
    if not isinstance(frames, dict) or len(frames) < 2:
        raise ValueError('Guide anchors and routing support frames are required')
    for name, frame in frames.items():
        if (not re.fullmatch(r'[a-z][a-z0-9_]*', name) or not isinstance(frame, dict)
                or set(frame) != {'link', 'origin', 'tangent', 'x', 'clamp_length_mm'}
                or frame['link'] not in links):
            raise ValueError('Unsupported source routing frame: '+str(name))
        vector(frame['origin']);t, x = vector(frame['tangent']), vector(frame['x'])
        if (abs(sum(v*v for v in t)-1) > 1e-9 or abs(sum(v*v for v in x)-1) > 1e-9
                or abs(sum(a*b for a, b in zip(t, x))) > 1e-9 or number(frame['clamp_length_mm']) < 0):
            raise ValueError('Routing frames need orthonormal axes and a nonnegative clamp length')
    sequence = config['sequence']
    if (not isinstance(sequence, list) or len(sequence) != len(frames)+2
            or any(not isinstance(v, str) for v in sequence) or len(set(sequence)) != len(sequence)
            or sequence[0] != 'pump' or sequence[-1] != 'tip' or set(sequence) != set(frames) | {'pump', 'tip'}):
        raise ValueError('The route must visit each declared frame exactly once from pump to tip')
    guide = config['guide']
    if (not isinstance(guide, dict) or set(guide) != {'from', 'to', 'search_frame', 'endpoint_straights_mm', 'external_straights_mm'}
            or guide['from'] not in frames or guide['to'] not in frames or guide['search_frame'] not in frames
            or (guide['from'], guide['to']) not in list(zip(sequence, sequence[1:]))
            or any(number(frames[k]['clamp_length_mm']) != 0 for k in (guide['from'], guide['to']))):
        raise ValueError('The guide needs consecutive source anchors with no duplicated node clamp')
    for key in ('endpoint_straights_mm', 'external_straights_mm'):
        leads = guide[key]
        if (not isinstance(leads, list) or len(leads) != 2
                or any(number(v) < p['connectorStraightLead'] for v in leads)):
            raise ValueError('Guide internal and external straight lengths must be explicit and sufficient')
    fit = config['bare_fit']
    if (not isinstance(fit, dict) or set(fit) != {'tangent_distance_multipliers'}
            or not isinstance(fit['tangent_distance_multipliers'], list) or not fit['tangent_distance_multipliers']
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in fit['tangent_distance_multipliers'])
            or number(config['sample_step_mm']) <= 0):
        raise ValueError('A bounded positive bare-span candidate family and sampling step are required')
    crossings = config['crossings']
    if not isinstance(crossings, dict) or set(crossings) != {'J3_Elbow', 'J4_ForearmRoll', 'J5_WristPitch', 'J6_FlangeRoll'}:
        raise ValueError('All four crossed joint interfaces must be declared')
    for reference in crossings.values():
        if isinstance(reference, str):
            if reference not in frames:
                raise ValueError('Unknown crossing support frame')
        elif (not isinstance(reference, dict) or set(reference) != {'interface', 'station'}
              or reference['interface'] not in {'pump', 'tip'}
              or reference['station'] not in {'material_end_mm', 'pneumatic_junction_mm', 'socket_mouth_mm', 'unsupported_exit_mm', 'bend_start_mm'}):
            raise ValueError('Crossings need an explicit support or connection station')
    if crossings['J6_FlangeRoll'] != {'interface': 'tip', 'station': 'unsupported_exit_mm'}:
        raise ValueError('J6 crossing is defined by the head-mounted strain-relief exit')


def native_spec(spec, p):
    base = syringe.cad_spec(library(spec), p)
    defs = {k: copy.deepcopy(v) for k, v in base['parameters'].items()
            if k not in ('radiusCoarse', 'strokeCoarse')}
    for k, v in spec['parameters'].items():
        defs[k] = {'expression': p[k], 'unit': v['unit'], 'range': v['range'], 'description': v['meaning']}
    for k in ('pitch', 'maxMotorAngle'):
        defs[k] = {'expression': p[k], 'unit': 'deg' if k == 'maxMotorAngle' else 'mm',
                   'range': [p[k], p[k]], 'description': 'Assumed screw lead and derived motor travel'}
    return {'id': spec['id'], 'status': spec['status'], 'parameters': defs}


cad_spec = native_spec


def pose(spec, p, name=None):
    row = spec['states'][name or spec['default_state']]
    stroke = p['strokeFine']*row['stroke_fraction']
    if not row.get('hard_end_reference') and not p['strokeReserve'] <= stroke <= p['strokeFine']-p['strokeReserve']:
        raise ValueError('State piston stroke is outside the evaluated reserve window')
    return {'PumpStroke': stroke, 'MotorRotation': stroke/p['pitch']*360,
            'IsolationValve': row['valve_deg']}


def validate_pose(source, values):
    if set(values) != {j['id'] for j in source['joints']}:
        raise ValueError('Every actuator coordinate is required')
    for j in source['joints']:
        v = values[j['id']];lo, hi = j.get('limits_mm', j.get('limits_deg'))
        if type(v) not in (int, float) or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError('Actuator outside inspection limits')


def expanded(spec, p):
    """Reuse the Fine pump and fixed head from the single leading SP01 recipe."""
    original = syringe.expanded(library(spec), p, spec['fixed_tip_head'])
    keep = {b['id'] for b in original['bodies']
            if ('Fine' in b['id'] and not b['id'].startswith('BranchAir'))
            or b['id'] in {'HeadCollar', 'DisposableTip'}}
    groups = {'Frame': 'PumpFrame', 'PlungerFine': 'PumpCarriage',
              'RotorFine': 'PumpValve', 'TipHead': 'WristHead'}
    result = {'id': spec['id'], 'status': spec['status'], 'parameter_values': p,
              'components': [{'id': g, 'grounded': g in {'PumpFrame', 'WristHead', 'ArmBracket'}}
                             for g in ('PumpFrame', 'PumpCarriage', 'PumpDrive', 'PumpValve', 'WristHead', 'ArmBracket', 'ConsumableTip')],
              'bodies': [], 'operations': [], 'joints': []}
    for b in original['bodies']:
        if b['id'] not in keep:continue
        b = copy.deepcopy(b);b['component'] = groups[b['component']]
        if b['id'] == 'LeadScrewEnvelopeFine':b['component'] = 'PumpDrive'
        if b['id'] == 'DisposableTip':b['component'] = 'ConsumableTip'
        result['bodies'].append(b)
    result['operations'] = [copy.deepcopy(o) for o in original['operations'] if o['body'] in keep]
    x = '-spacing/2'

    def add(name, kind, origin, component, color, **shape):
        result['bodies'].append({'id': name, 'component': component,
            'role': 'assumed_'+name, 'appearance': {'color': color, 'opacity': 1}})
        op(name, name, kind, origin, **shape)

    def op(name, target, kind, origin, action='create', **shape):
        result['operations'].append({'id': name, 'body': target, 'action': action,
            'shape': {'kind': kind, 'origin': origin, **shape}})

    add('SinglePumpPlate', 'box', [f'({x})-24', -45, 0], 'PumpFrame', '#a5b8c1', size=[48, 255, 6])
    add('PumpControllerEnvelope', 'box', [f'({x})-14', 120, 6], 'PumpFrame', '#2d5366', size=[28, 40, 18])
    for side in (-1, 1):
        gx = f'({x})+({side*11})'
        add('LinearGuide'+str(side), 'cylinder', [gx, 65, 'axisZ+22'], 'PumpFrame', '#acbcc5',
            radius=1.5, height=113, axis=[0, 1, 0])
    for tag, y in [('Front', 62), ('Rear', 166)]:
        add('GuideSupport'+tag, 'box', [f'({x})-17', y, 6], 'PumpFrame', '#7b9aab',
            size=[34, 4, 'axisZ+21'])
        op('GuideSupport'+tag+'_RodClearance', 'GuideSupport'+tag, 'cylinder',
           [x, y, 'axisZ'], 'cut', radius=1.4, height=4, axis=[0, 1, 0])
    add('GuideCarriage', 'box', [f'({x})-15', 76, 'axisZ+19'], 'PumpCarriage', '#287fa9', size=[30, 8, 6])
    for side in (-1, 1):
        op('GuideClearance'+str(side), 'GuideCarriage', 'cylinder',
           [f'({x})+({side*11})', 75, 'axisZ+22'], 'cut', radius=1.7, height=10, axis=[0, 1, 0])
    add('ScrewCoupler', 'cylinder', [x, 174, 'axisZ+30'], 'PumpDrive', '#398bb0', radius=3.5, height=6, axis=[0, 1, 0])
    add('ScrewIndex', 'box', [f'({x})+1.8', 170, 'axisZ+29'], 'PumpDrive', '#f1b53e', size=[2, 3, 2])
    add('DriveNutEnvelope', 'box', [f'({x})-5', 78, 'axisZ+25'], 'PumpCarriage', '#b5a059', size=[10, 6, 10])
    op('DriveNutClearance', 'DriveNutEnvelope', 'cylinder', [x, 77, 'axisZ+30'], 'cut', radius=2.3, height=8, axis=[0, 1, 0])
    op('DriveNutSeat', 'CarriageFine', 'box', [f'({x})-5.2', 77.8, 'axisZ+24.8'],
       'cut', size=[10.4, 6.4, 10.4])
    add('FrontScrewBearing', 'cylinder', [x, 65, 'axisZ+30'], 'PumpFrame', '#6c94a4', radius=5, height=6, axis=[0, 1, 0])
    op('FrontBearingClearance', 'FrontScrewBearing', 'cylinder', [x, 64, 'axisZ+30'], 'cut', radius=2.3, height=8, axis=[0, 1, 0])
    add('CarriageSwitchFlag', 'box', [f'({x})+6', 80, 'axisZ+36'], 'PumpCarriage', '#deaa3f', size=[16, 2, 7])
    for tag, y in [('Advanced', '76+strokeReserve'), ('Retracted', '82+strokeFine-strokeReserve')]:
        # Open-sided fork around the flag's terminal end. Its body stays beyond
        # the carriage block; the flag stem exits through the open side.
        add('EndstopEnvelope'+tag, 'box', [f'({x})+17', y, 'axisZ+34'], 'PumpFrame', '#deaa3f', size=[9, 4, 11])
        op('EndstopAperture'+tag, 'EndstopEnvelope'+tag, 'box',
           [f'({x})+16.5', f'({y})-1', 'axisZ+35.5'], 'cut', size=[6, 6, 8])
    interfaces = connection_interfaces(spec, p)
    for label, interface in interfaces.items():
        body, component = interface['body'], interface['component']
        inward = [-v for v in interface['outward']]
        mouth, floor = interface['socket_mouth_mm'], interface['material_end_mm']
        add(body, 'cylinder', mouth, component, '#3787a2', radius=interface['outer_radius_mm'],
            height='hoseInsertionDepth+'+str(interface['through_length_mm']), axis=inward)
        op(body+'_Socket', body, 'cylinder', mouth, 'cut',
           radius='hoseOuterRadius+socketRadialClearance', height='hoseInsertionDepth', axis=inward)
        op(body+'_Bore', body, 'cylinder', floor, 'cut', radius='hoseInnerRadius',
           height=interface['through_length_mm'], axis=inward)
        clamp = interface['clamp_body']
        add(clamp, 'cylinder', mouth, component, '#637f8c', radius=2.5,
            height='strainReliefLength', axis=interface['outward'])
        op(clamp+'_Clearance', clamp, 'cylinder', mouth, 'cut', radius='hoseOuterRadius+socketRadialClearance',
           height='strainReliefLength', axis=interface['outward'])
    head_floor = interfaces['tip']['material_end_mm']
    op('HeadCollar_SideAir', 'HeadCollar', 'cylinder', head_floor, 'cut',
       radius='hoseInnerRadius', height=1-head_floor[0], axis=[1, 0, 0])
    seat = tip_seat(spec, p)
    hp = library(spec)['tip_heads'][spec['fixed_tip_head']]
    add('TipShaft', 'cone', seat['seal_center_mm'], 'WristHead', hp['color'],
        radius=seat['seal_radius_mm'], top_radius=seat['shaft_mouth_radius_mm'],
        height='tipEngagementLength', axis=[0, 0, 1])
    op('TipShaft_Upper', 'TipShaft', 'cone', [0, -95, seat['tip_top_z_mm']], 'join',
       radius=seat['shaft_mouth_radius_mm'], top_radius=hp['cone_radius_mm'], height=15, axis=[0, 0, 1])
    op('TipShaft_Air', 'TipShaft', 'cylinder', seat['seal_center_mm'], 'cut',
       radius='pipeBore', height='tipEngagementLength+15', axis=[0, 0, 1])
    # A flat conceptual flange pad touches the flange face; no invented bolt standard.
    add('TipFlangePad', 'cylinder', [0, -95, 'axisZ-21.3'], 'WristHead', '#a7bfc8', radius=14, height=4, axis=[0, 0, 1])
    for i, z in enumerate((205, 305)):
        add('ClampBridge'+str(i), 'box', ['axisZ-outboard', -34, z], 'ArmBracket', '#34809b', size=[5, 68, 8])
        for label, y in [('L', -34), ('R', 28)]:
            add('ClampPad'+label+str(i), 'box', ['axisZ-outboard', y, z], 'ArmBracket', '#34809b', size=['outboard-axisZ-25', 6, 8])
    for name, child, kind, origin, axis, limit, ref in [
        ('PumpStroke', 'PumpCarriage', 'slider', [x, -43, 'axisZ'], [0, 1, 0], 'strokeFine', [1, 0, 0]),
        ('MotorRotation', 'PumpDrive', 'revolute', [x, 0, 'axisZ+30'], [0, 1, 0], 'maxMotorAngle', [1, 0, 0]),
        ('IsolationValve', 'PumpValve', 'revolute', [x, -68, 'axisZ'], [0, 0, 1], 'valveAngle', [1, 0, 0])]:
        result['joints'].append({'id': name, 'type': kind, 'parent': 'PumpFrame', 'child': child,
            'origin': origin, 'axis': axis, 'reference_x': ref, 'limit_parameter': limit,
            'limits_deg' if kind == 'revolute' else 'limits_mm': [0, p[limit]]})
    return result


def pump_mount_plate_axis_bounds(spec, p):
    """Derive the mounting plate span so reversal preserves both clamp faces."""
    source = expanded(spec, p)
    fixed = {'SinglePumpPlate'}
    spans = []
    for operation in source['operations']:
        if operation['body'] not in fixed or operation['action'] != 'create':continue
        shape = operation['shape']
        origin = [evaluate(v, p) for v in shape['origin']]
        if shape['kind'] == 'box':
            spans.append((origin[1], origin[1]+evaluate(shape['size'][1], p)))
        elif shape['kind'] in ('cylinder', 'cone'):
            axis = [evaluate(v, p) for v in shape['axis']]
            norm = math.sqrt(sum(v*v for v in axis))
            axial = axis[1]/norm
            radius = max(evaluate(shape['radius'], p), evaluate(shape.get('top_radius', shape['radius']), p))
            radial = radius*math.sqrt(max(0, 1-axial*axial))
            end = origin[1]+axial*evaluate(shape['height'], p)
            spans.append((min(origin[1], end)-radial, max(origin[1], end)+radial))
        else:
            raise ValueError('Unsupported fixed pump envelope primitive: '+shape['kind'])
    if not spans:raise ValueError('The mounting plate has no axial geometry')
    return min(v[0] for v in spans), max(v[1] for v in spans)


def mounts(spec, p):
    a = arm(spec);ap = robot.parameters(a)
    fine_x = -p['spacing']/2
    lower, upper = pump_mount_plate_axis_bounds(spec, p)
    pump = [[0, 0, -1, -p['outboard']+p['axisZ']], [1, 0, 0, -fine_x],
            [0, -1, 0, ap['shoulder_z']+spec['pump_mount']['shoulder_offset_mm']+lower+upper], [0, 0, 0, 1]]
    flange = [evaluate(v, ap) for v in a['flange_reference']['point']]
    top = p['axisZ']-21.3
    head = [[1, 0, 0, flange[0]], [0, -1, 0, flange[1]-95],
            [0, 0, -1, flange[2]+spec['head_mount']['flange_gap_mm']+top], [0, 0, 0, 1]]
    return {'PumpFrame': {'link': 'L2_UpperArm', 'zero_transform': pump},
            'WristHead': {'link': 'L6_BareFlange', 'zero_transform': head},
            'ConsumableTip': {'link': 'L6_BareFlange', 'zero_transform': head},
            'ArmBracket': {'link': 'L2_UpperArm', 'zero_transform': robot.identity()}}


def allowed_contacts(spec, p=None):
    return [{'a': 'ClampPad'+label+str(i), 'b': 'Upper_plate_'+label,
             'reason': 'Provisional clamp contact at the existing plate edge'}
            for label in ('L', 'R') for i in (0, 1)]+[
                {'a': 'TipFlangePad', 'b': 'Bare_tool_flange', 'reason': 'Provisional tool pad on flange face'}]+[
                {'a': a, 'b': b, 'reason': reason} for a, b, reason in [
                    ('MotorEnvelopeFine', 'LeadScrewEnvelopeFine', 'Idealized motor-to-screw shaft interface'),
                    ('MotorEnvelopeFine', 'ScrewCoupler', 'Coupler abuts the motor shaft envelope'),
                    ('SinglePumpPlate', 'ClampBridge0', 'Provisional bracket meets pump plate at its mounting face'),
                    ('SinglePumpPlate', 'ClampBridge1', 'Provisional bracket meets pump plate at its mounting face'),
                    ('PneumaticHose', 'PumpHoseBarb', 'Tube annular material end bottoms only on the declared socket floor'),
                    ('PneumaticHose', 'TipSidePort', 'Tube annular material end bottoms only on the declared socket floor'),
                    ('TipShaft', 'DisposableTip', 'Derived relieved taper touches only at the declared lower seal circle'),
                    ('TipFlangePad', 'J6_output_coupler', 'Tool pad shares the existing flange/coupler mounting plane')]]


def _placements(spec, p, joints_deg, state_id, context):
    frames = robot.forward(context['arm'], joints_deg)
    mounted = {key: robot.multiply(frames[value['link']], value['zero_transform'])
               for key, value in context['mounts'].items()}
    coordinates = pose(spec, p, state_id)
    for group in ('PumpCarriage', 'PumpDrive', 'PumpValve'):
        mounted[group] = robot.multiply(mounted['PumpFrame'],
            component_matrix(context['own'], group, p, coordinates))
    return frames, mounted


def _route_clearance(spec, p, path, frames, mounted, context):
    interfaces = connection_interfaces(spec, p, mounted)
    mating = {key: [row['body'], row['clamp_body']] for key, row in interfaces.items()}
    design = spec['hose_length_design']
    return clearance.check_route(path, context['envelopes'], {**frames, **mounted},
        p['hoseOuterRadius'], context['carrier_profile']['geometry']['outer_radius_mm'],
        sample_step_mm=design.get('clearance_sample_step_mm', 2.0),
        minimum_sample_step_mm=design.get('clearance_minimum_step_mm', .05),
        socket_mating_bodies=mating)


def prepare_route_context(spec, p):
    """Source-only kinematics and conservative envelopes for one evaluation."""
    a = arm(spec);own = expanded(spec, p);mounting = mounts(spec, p)
    ap = route_parameters(spec, p, a, mounting)
    context = {'arm': a, 'parameters': ap, 'mounts': mounting, 'own': own,
               'carrier_profile': carrier.load(ROOT/spec['hose_carrier']['source']),
               'routing_config': spec['carrier_routing'],
               'connection_interfaces': connection_interfaces,
               'envelopes': clearance.source_envelopes(a, own, ap, p)}
    def bare_span_check(path, from_frame, to_frame, frames, mounted):
        trial = dict(path)
        trial['length_accounting'] = {'parts': [{'id': from_frame+'__'+to_frame,
            'kind': 'bare_span', 'length_mm': path['length_mm']}]}
        return _route_clearance(spec, p, trial, frames, mounted, context)
    context['bare_span_clearance'] = bare_span_check
    return context


def route_at(spec, p, joints_deg, slack, *, context=None, state_id=None):
    """Compile framed physical spans; arbitrary grid points remain diagnostics."""
    context = context or prepare_route_context(spec, p)
    a = context['arm']
    if (len(joints_deg) != 6 or type(slack) not in (int, float)
            or not math.isfinite(slack) or not 0 <= slack <= spec['hose_length_design']['max_service_loop_mm']):
        raise ValueError('Invalid static hose scan coordinate')
    for value, joint in zip(joints_deg, a['joints']):
        lo, hi = spec['operating_window_deg'][joint['id']]['range']
        if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError('Route coordinate outside the tooling inspection domain')
    frames, mounted = _placements(spec, p, joints_deg, state_id or spec['default_state'], context)
    path = routing.route(spec, p, frames, mounted, slack, context)
    path['joints_deg'] = list(joints_deg)
    return path


_NAMED_BAND_CACHE = {}


def named_length_band(spec, p, *, context=None):
    """Finite, source-pinned named-pose design; selected cuts checked separately."""
    dependencies = [Path(__file__), SOURCE, ROOT/'model/arm-syringe.schema.json',
                    ROOT/spec['robot']['source'], ROOT/spec['syringe_library']['source']]+source_dependencies(spec)
    pin_key = [(str(path), digest(path)) for path in dependencies]
    key = json.dumps([spec, p, pin_key], sort_keys=True, allow_nan=False)
    if key in _NAMED_BAND_CACHE:
        return _NAMED_BAND_CACHE[key]
    context = context or prepare_route_context(spec, p)
    design = spec['hose_length_design']
    maximum, step = design['max_service_loop_mm'], design['loop_sample_step_mm']
    intervals = math.ceil(maximum/step)
    loops = [maximum*i/intervals for i in range(intervals+1)]
    poses = {name: _placements(spec, p, row['joints_deg'], name, context)
             for name, row in spec['states'].items()}
    def evaluate_route(name, slack):
        frames, mounted = poses[name]
        return routing.route(spec, p, frames, mounted, slack, context)
    def check_route(path, name, slack):
        frames, mounted = poses[name]
        return _route_clearance(spec, p, path, frames, mounted, context)
    band = routing.compile_named_band(spec['states'], evaluate_route, loops, p=p,
        clearance_check=check_route, allowances=design['allowances'],
        cut_resolution_mm=design['cut_resolution_mm'])
    if pin_key != [(str(path), digest(path)) for path in dependencies]:
        raise ValueError('Source files changed during the named-pose length study')
    band['source_files_sha256'] = {str(path.relative_to(ROOT)): checksum for path, (_, checksum) in zip(dependencies, pin_key)}
    _NAMED_BAND_CACHE[key] = band
    return band


def air_volumes(spec, p, stroke):
    """Idealized connected bore budget; no measured cavity or delivered-dose claim."""
    # The seal's leading face is at local Y=-43+stroke; nose stops at -45.
    # Fitting path: nose8 + Luer6 + valve18 + socket floor through-bore. The valve's
    # through rotor shares the same18mm path; it is not counted a second time.
    # The perpendicular head inlet crosses the central bore; subtract their
    # unequal-radius cylinder intersection instead of counting that air twice.
    r = p['pipeBore'];small = p['hoseInnerRadius']
    syringe_air = math.pi*p['radiusFine']**2*(2+stroke)
    fittings = math.pi*r*r*(8+6+18)+math.pi*small*small*spec['connections']['pump']['through_length_mm']
    seat = tip_seat(spec, p)
    length = seat['seal_center_mm'][2]-seat['tip_bottom_z_mm']
    r0, r1 = seat['tip_inner_exit_radius_mm'], seat['seal_radius_mm']
    tip = math.pi*length*(r0*r0+r0*r1+r1*r1)/3
    # The socket floor and collar-side cutter form a union from X=-9 to+1, including a blind
    # overrun past the r0.8 central bore. Integrate one half of their cylinder
    # intersection with z=small*sin(theta), which removes endpoint cusps.
    steps = 400
    step = math.pi/steps
    def section(theta):
        return 2*small*small*math.cos(theta)**2*math.sqrt(max(0, r*r-small*small*math.sin(theta)**2))
    half_overlap = step/3*(section(-math.pi/2)+section(math.pi/2)+sum(
        (4 if i % 2 else 2)*section(-math.pi/2+i*step) for i in range(1, steps)))
    central_length = p['axisZ']-21.3-seat['seal_center_mm'][2]
    side_length = 1-connection_interfaces(spec, p)['tip']['material_end_mm'][0]
    head = math.pi*r*r*central_length+tip+math.pi*small*small*side_length-2*half_overlap
    tube = math.pi*small*small*p['hoseLength']
    e = seat['engagement_length_mm'];a = seat['seal_radius_mm']
    b, c = seat['tip_mouth_inner_radius_mm'], seat['shaft_mouth_radius_mm']
    relief = math.pi*e*((a*a+a*b+b*b)-(a*a+a*c+c*c))/3
    return {'syringe': syringe_air, 'fittings': fittings, 'tube': tube, 'head': head,
            'total': syringe_air+fittings+tube+head,
            'unpressurized_tip_relief_air_ul': relief,
            'scope': 'Geometric cavity volume only; not liquid dose, compressibility or measured dead volume',
            'assumptions': ['Open-valve connected path; closed valve isolates cavities without removing their geometric air volume.',
                            'Ideal seal at its modeled leading face, perfect junctions; excludes annular seal/rotor gaps and connector compliance.',
                            'Tube lumen includes both inserted portions once; socket bores begin at the floors.',
                            'Tip volume ends at its lower seal circle; ambient taper-relief air is reported separately, outside the ideal connected total.',
                            'Side inlet includes its blind+1mm cutter overrun; bore overlap removed by400-panel endpoint-smoothed Simpson integration.']}


def air_path_recipe(spec, p, stroke):
    """Ideal open-valve cavity inventory for an independent native union.

    The tube lumen is supplied separately from its exact centerline. This is
    not a requirement that an isolated-valve state has an open whole circuit.
    """
    seat = tip_seat(spec, p);x = -p['spacing']/2
    interfaces = connection_interfaces(spec, p)
    return [
        {'id': 'SyringeAir', 'component': 'PumpFrame', 'shape': {'kind': 'cylinder', 'origin': [x, -45, p['axisZ']], 'radius': p['radiusFine'], 'height': 2+stroke, 'axis': [0, 1, 0]}},
        {'id': 'CoreFittingAir', 'component': 'PumpFrame', 'shape': {'kind': 'cylinder', 'origin': [x, -77, p['axisZ']], 'radius': p['pipeBore'], 'height': 32, 'axis': [0, 1, 0]}},
        {'id': 'PumpFloorAir', 'component': 'PumpFrame', 'shape': {'kind': 'cylinder', 'origin': interfaces['pump']['material_end_mm'], 'radius': p['hoseInnerRadius'], 'height': interfaces['pump']['through_length_mm'], 'axis': [0, 1, 0]}},
        {'id': 'HeadBoreAir', 'component': 'WristHead', 'shape': {'kind': 'cylinder', 'origin': seat['seal_center_mm'], 'radius': p['pipeBore'], 'height': p['axisZ']-21.3-seat['seal_center_mm'][2], 'axis': [0, 0, 1]}},
        {'id': 'HeadSideAir', 'component': 'WristHead', 'shape': {'kind': 'cylinder', 'origin': interfaces['tip']['material_end_mm'], 'radius': p['hoseInnerRadius'], 'height': 1-interfaces['tip']['material_end_mm'][0], 'axis': [1, 0, 0]}},
        {'id': 'TipCavityAir', 'component': 'ConsumableTip', 'shape': {'kind': 'cone', 'origin': [0, -95, seat['tip_bottom_z_mm']], 'radius': seat['tip_inner_exit_radius_mm'], 'top_radius': seat['seal_radius_mm'], 'height': seat['seal_center_mm'][2]-seat['tip_bottom_z_mm'], 'axis': [0, 0, 1]}},
    ]


def state(spec, p, name=None, *, loop_parameter_mm=None):
    name = name or spec['default_state'];row = spec['states'][name]
    context = prepare_route_context(spec, p)
    frames, placed = _placements(spec, p, row['joints_deg'], name, context)
    q = pose(spec, p, name)
    if loop_parameter_mm is None:
        band = named_length_band(spec, p, context=context)
        if band['status'] != 'demonstrated' or name not in band['selected_states']:
            raise ValueError('Named-pose hose design is blocked: '+json.dumps(band['failures']))
        selected = band['selected_states'][name]
        loop_parameter_mm = selected['loop_parameter_mm']
        route = selected['route']
    else:
        route = route_at(spec, p, row['joints_deg'], loop_parameter_mm, context=context, state_id=name)
    if abs(route['length_mm']-p['hoseLength']) > 1e-6:
        raise ValueError('Source hose cut does not match the independently evaluated framed route')
    self_check = pneumatic_hose.self_clearance_diagnostics(route, p['hoseOuterRadius'])
    if not self_check['passed']:
        raise ValueError('Static hose branches violate the finite self-clearance screen: '+str(self_check['near_segment_witness']))
    source_check = _route_clearance(spec, p, route, frames, placed, context)
    if not source_check['passed']:
        raise ValueError('Static hose route is not separated from the conservative source envelopes: '+json.dumps(source_check))
    crossings = {key: {'distance_to_axis_mm': value['radial_standoff_mm'],
                       'axis_point_mm': value['axis_origin_mm'], 'axis_direction': value['axis_direction'],
                       'waypoint_mm': value['point_mm'], 'frame_id': value['frame_id'],
                       'scope': 'Declared support/crossing frame; not the whole-route minimum distance'}
                 for key, value in route['framed_crossings'].items()}
    return {'id': name, 'joints_deg': row['joints_deg'], 'stroke_mm': q['PumpStroke'],
            'motor_angle_deg': q['MotorRotation'], 'valve_angle_deg': q['IsolationValve'],
            'part_matrices': placed, 'hose_path': route, 'hose_self_clearance': self_check,
            'source_clearance': source_check, 'length_accounting': route['length_accounting'],
            'carrier': carrier.carrier_records(context['carrier_profile'], route['carrier_path']),
            'hose_points_mm': route['sample_points_mm'],
            'hose_inner_radius_mm': p['hoseInnerRadius'], 'hose_outer_radius_mm': p['hoseOuterRadius'],
            'hose_slack_parameter_mm': loop_parameter_mm,
            'theoretical_displacement_ul': math.pi*p['radiusFine']**2*q['PumpStroke'],
            'actual_dispensed_volume_ul': None,
            'metrics': {'hose_crossings': crossings, 'enclosed_air_volume_ul': air_volumes(spec, p, q['PumpStroke'])},
            'connection_interfaces': connection_interfaces(spec, p, placed),
            'tip_seat': tip_seat(spec, p),
            'tip_tcp_mm': robot.transform(placed['ConsumableTip'], tip_seat(spec, p)['tip_tcp_mm'])}


def samples(spec, p):
    return [{'id': k, 'joint_values': pose(spec, p, k)} for k in spec['states']]


build_samples = samples


def source_dependencies(spec):
    return [ROOT/'scripts/arm_syringe_window.py', ROOT/'scripts/arm_syringe_routing.py',
            ROOT/'scripts/arm_syringe_clearance.py', ROOT/'scripts/robot_components.py', ROOT/'scripts/robot_cameras.py',
            ROOT/arm(spec)['vendor_library']['path'], ROOT/'scripts/spatial_hose_carrier.py',
            ROOT/'model/spatial-hose-carrier.schema.json', ROOT/spec['hose_carrier']['source'],
            ROOT/'cad/vendor/igus/triflex-r-reference.pdf']


def solidcraft_commands(spec, p):
    class Provider:
        SOURCE = globals()['SOURCE']
        expanded = staticmethod(expanded)
        pose = staticmethod(pose)
        samples = staticmethod(samples)
    return portable.solidcraft_commands(native_spec(spec, p), p, Provider)
