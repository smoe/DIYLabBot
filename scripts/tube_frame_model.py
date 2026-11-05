"""H02 semantic open-frame / split-receiver recipe, shared by both native CADs."""
from pathlib import Path
import ast
import json
import math
import sys
import robot_spec
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/tube-frame-h02.shared.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate
numeric_shape = portable.numeric_shape


def parameters(spec, overrides=None):
    for name in overrides or {}:
        if name in spec['parameters'] and any(isinstance(n, ast.Name) for n in ast.walk(ast.parse(str(spec['parameters'][name]['expression']), mode='eval'))):
            raise ValueError('Change the driving parameter instead of derived '+name)
    p = portable.parameters(spec, overrides)
    return p


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format'] != 'solidcraftbot.tube-frame/1' or spec['units'] != {'length': 'mm', 'angle': 'deg'}:
        raise ValueError('Unsupported H02 source or units')
    if spec['recipe'] != 'open_optical_frame_bottom_lifter_split_receiver_v1': raise ValueError('Unknown recipe')
    p = parameters(spec)
    for sample in samples(spec, p): protocol_support(p, sample['values_mm'])
    return spec


def state(p, name):
    t, g, r, opening = p['eject_travel'], p['contact_gap'], p['receiver_travel'], p['jaw_open']
    values = {'ready': [0, 0, 0, opening], 'contact': [0, g, 0, opening],
              'lifted': [t, t+g, 0, opening], 'captured': [t, t+g, 0, 0],
              'supported': [t, 0, 0, 0], 'carried': [t+r, 0, r, 0]}[name]
    return dict(zip(['TubeLift', 'Pusher', 'ReceiverLift', 'Jaw'], values))


def pose(spec, p, name=None):
    name = name or spec['display_pose']; result = {}
    for v in spec['variants']:
        s = state(p, spec['display_states'][v['id']] if name == 'comparison' else name)
        for key in ['TubeLift', 'Pusher', 'ReceiverLift']: result[key+v['id']] = s[key]
        result['JawL'+v['id']] = result['JawR'+v['id']] = s['Jaw']
    return result


def protocol_support(p, values):
    result = []
    for tag in ['V15', 'V20']:
        t, push, receiver = (values[k+tag] for k in ['TubeLift', 'Pusher', 'ReceiverLift'])
        left, right = values['JawL'+tag], values['JawR'+tag]
        closed = abs(left)+abs(right) < 1e-7
        donor = abs(t) < 1e-7
        pusher = abs(push-t-p['contact_gap']) < 1e-7
        captured = closed and abs(t-p['eject_travel']-receiver) < 1e-7
        if not (donor or pusher or captured): raise ValueError('Unsupported tube state '+tag)
        if min(left, right) < p['jaw_open']-1e-7 and abs(t-p['eject_travel']-receiver) > 1e-7:
            raise ValueError('Receiver closure before alignment '+tag)
        if receiver > 1e-7 and (not captured or push > 1e-7): raise ValueError('Departure before pusher withdrawal '+tag)
        result.append({'variant': tag, 'donor_support': donor, 'pusher_support': pusher,
                       'receiver_support': captured, 'passed': True})
    return result


def samples(spec, p):
    result = [{'id': name, 'values_mm': pose(spec, p, name)} for name in ['comparison']+spec['protocol_states']]
    for start, end in zip(spec['protocol_states'], spec['protocol_states'][1:]):
        a, b = pose(spec, p, start), pose(spec, p, end)
        for i in range(1, 7):
            values = {k: a[k]+(b[k]-a[k])*i/6 for k in a}
            result.append({'id': start+'_to_'+end+'_'+str(i), 'values_mm': values,
                           'support': protocol_support(p, values)})
    return result


def expanded(spec, p):
    out = {'id': spec['id'], 'status': spec['status'], 'components': [{'id': 'DockFrame', 'grounded': True}],
           'parameters': spec['parameters'], 'bodies': [], 'operations': [], 'joints': []}
    for variant in spec['variants']:
        tag, cx = variant['id'], variant['center_x']; seat_z, seat_r = variant['seat_z'], variant['seat_radius']
        tube, push, recv, left, right = [k+tag for k in ['Tube', 'Ejector', 'Receiver', 'JawL', 'JawR']]
        out['components'] += [{'id': n, 'grounded': False, **({'parent': recv} if n in [left, right] else {})} for n in [tube, push, recv, left, right]]
        def body(suffix, component, color, role='structure', opacity=1):
            name = tag+'_'+suffix
            out['bodies'].append({'id': name, 'component': component, 'role': role, 'appearance': {'color': color, 'opacity': opacity}})
            return name
        def op(suffix, target, shape, action='create'):
            out['operations'].append({'id': tag+'_'+suffix, 'body': target, 'action': action, 'shape': shape})
        def box(suffix, target, size, origin, action='create'):
            op(suffix, target, {'kind': 'box', 'size': size, 'origin': [f'({cx})+({origin[0]})', origin[1], origin[2]]}, action)
        def cylinder(suffix, target, radius, height, z, action='create'):
            op(suffix, target, {'kind': 'cylinder', 'radius': radius, 'height': height, 'origin': [cx, 0, z]}, action)
        def profile(suffix, target, points):
            op(suffix, target, {'kind': 'revolved_profile', 'center_x': cx, 'points_rz': points})
        base = body('DockBase', 'DockFrame', '#adbfcf')
        box('Base', base, [44, 40, 6], [-22, -20, 0])
        cylinder('BasePusherOpening', base, 2.6, 8, -1, 'cut')
        frame = body('CarrierShell', 'DockFrame', '#244b69', 'open_optical_frame')
        box('Foot', frame, [26, 24, 2], [-13, -12, 6])
        for side in [-1, 1]:
            box('BackPost'+str(side), frame, [3, 4, 'frame_guide_z+2-8'], [-11 if side < 0 else 8, 3, 8], 'join')
            box('GripPad'+str(side), frame, [7, 8, 6], [-17 if side < 0 else 10, -4, 23], 'join')
        cylinder('GuideRing', frame, 9.5, 2, 'frame_guide_z', 'join')
        cylinder('UpperGuideBore', frame, 'tube_radius+radial_clearance', 4, 'frame_guide_z-1', 'cut')
        cylinder('OpenFoot', frame, 6.8, 4, 5, 'cut')
        seat = body('LowerSeat', 'DockFrame', variant['color'], 'lower_exterior_seat')
        cylinder('Seat', seat, 9.5, 2, f'({seat_z})-2')
        cylinder('SeatOpening', seat, seat_r, 4, f'({seat_z})-3', 'cut')
        motor = body('PusherDriveEnvelope', 'DockFrame', '#738396', 'actuator_envelope')
        box('PusherDrive', motor, [14, 14, 'pusher_limit+pusher_engagement+drive_margin'],
            [-7, -7, '-pusher_limit-pusher_engagement-drive_margin'])
        cylinder('DriveShaftBore', motor, 1.4, 'pusher_limit+pusher_engagement+drive_margin+2',
                 '-pusher_limit-pusher_engagement-drive_margin-1', 'cut')
        lifter = body('BottomLifter', push, '#efac45', 'external_bottom_pusher')
        if variant['bottom'] == 'conical':
            cup_r = '0.8+(tube_radius-0.8)/4'; cup_top = 'tube_bottom_z-contact_gap+(cone_join_z-tube_bottom_z)/4'
            inside = [[cup_r, cup_top], [0.8, 'tube_bottom_z-contact_gap'], [0, 'tube_bottom_z-contact_gap']]
            lower = [[0, 'tube_bottom_z'], [0.8, 'tube_bottom_z'], ['tube_radius', 'cone_join_z']]
        else:
            cup_r = 'tube_radius*0.258819045102521'; cup_top = 'tube_bottom_z-contact_gap+tube_radius*0.034074173710932'
            inside = [[cup_r, cup_top], [0, 'tube_bottom_z-contact_gap']]
            lower = [[f'tube_radius*{math.sin(math.radians(a)):.15g}', f'tube_bottom_z+tube_radius*{1-math.cos(math.radians(a)):.15g}'] for a in spec['rounded_profile_angles_deg']]
        profile('PusherCup', lifter, [[0, 'tube_bottom_z-contact_gap-2'], [f'({cup_r})+0.3', 'tube_bottom_z-contact_gap-2'],
                [f'({cup_r})+0.3', cup_top]]+inside)
        cylinder('Pushrod', lifter, 1.2, 'pusher_limit+pusher_engagement+tube_bottom_z-contact_gap-1',
                 '-pusher_limit-pusher_engagement', 'join')
        reference = body('ReferenceTube', tube, '#cbe9ef', 'tube_shape_reference', 0.35)
        profile('TubeProfile', reference, lower+[['tube_radius', 'collar_z'], ['collar_radius', 'collar_z'],
                ['collar_radius', 'collar_z+2'], ['tube_radius-0.7', 'collar_z+2'], ['tube_radius-0.7', 'cone_join_z'], [0, 'cone_join_z']])
        fluid = body('FluidReference', tube, '#168bda', 'illustrative_fluid', 0.85)
        cylinder('FluidPatch', fluid, 'tube_radius-0.85', 'fluid_h', 'fluid_z')
        keepout = body('MouthKeepout', tube, '#c775dc', 'clearance_envelope', 0.12)
        cylinder('MouthNoContact', keepout, 8, 8, 'collar_z-1')
        bridge = body('ReceiverBridge', recv, '#788d9b', 'receiver_carriage_envelope')
        box('ReceiverRail', bridge, [44, 6, 6], [-22, 10, 'receiver_guide_z+3'])
        for side, group in [(-1, left), (1, right)]:
            jaw = body('ReceiverJaw'+('L' if side < 0 else 'R'), group, '#db9144', 'split_receiver_seat_and_guide')
            bottom = f'({seat_z})+eject_travel-2'
            box('ReceiverSeat'+str(side), jaw, [10, 16, 2], [-10 if side < 0 else 0, -8, bottom])
            cylinder('ReceiverSeatBore'+str(side), jaw, seat_r, 4, f'({seat_z})+eject_travel-3', 'cut')
            box('ReceiverPost'+str(side), jaw, [3, 3, f'receiver_guide_z+2-({bottom})'],
                [-10 if side < 0 else 7, 5, bottom], 'join')
            box('ReceiverGuide'+str(side), jaw, [10, 16, 2], [-10 if side < 0 else 0, -8, 'receiver_guide_z'], 'join')
            cylinder('ReceiverGuideBore'+str(side), jaw, 'tube_radius+radial_clearance', 4, 'receiver_guide_z-1', 'cut')
            box('ReceiverSlideShoe'+str(side), jaw, [3, 8, 2],
                [-10 if side < 0 else 7, 5, 'receiver_guide_z+1'], 'join')
        for name, child, parent, axis, xref, limit in [
            ('TubeLift', tube, 'DockFrame', [0,0,1], [1,0,0], 'tube_lift_limit'),
            ('Pusher', push, 'DockFrame', [0,0,1], [1,0,0], 'pusher_limit'),
            ('ReceiverLift', recv, 'DockFrame', [0,0,1], [1,0,0], 'receiver_travel'),
            ('JawL', left, recv, [-1,0,0], [0,1,0], 'jaw_open'),
            ('JawR', right, recv, [1,0,0], [0,1,0], 'jaw_open')]:
            out['joints'].append({'id': name+tag, 'type': 'slider', 'parent': parent, 'child': child,
                'origin': [cx, 0, 'collar_z'], 'axis': axis, 'reference_x': xref,
                'limit_parameter': limit, 'limits_mm': [0, p[limit]]})
    return out


def validate_pose(source, values): return portable.validate_pose(source, values)


def displacement(source, component, values):
    joint = next((j for j in source['joints'] if j['child'] == component), None)
    if not joint: return [0, 0, 0]
    parent = displacement(source, joint['parent'], values)
    return [a+axis*values[joint['id']] for a, axis in zip(parent, joint['axis'])]


def solidcraft_commands(spec, p): return portable.solidcraft_commands(spec, p, provider=sys.modules[__name__])


def analytic_checks(actual, spec, p):
    result = []; bodies = {b['name']: b for b in actual['bodies']}
    for v in spec['variants']:
        expected = 44*40*6-math.pi*2.6**2*6
        error = abs(bodies[v['id']+'_DockBase']['volume_mm3']-expected)/expected
        result.append({'body': v['id']+'_DockBase', 'expected_volume_mm3': expected, 'relative_error': error, 'passed': error < 0.001})
    return result


def check_interface_geometry(spec, p, geometry):
    bodies = {b['body']: b for b in geometry}; result = []
    for v in spec['variants']:
        frame = bodies[v['id']+'_CarrierShell']; seat = bodies[v['id']+'_LowerSeat']
        width = frame['bbox']['max'][0]-frame['bbox']['min'][0]
        z = evaluate(v['seat_z'], p)
        result.append({'variant': v['id'], 'grip_width_mm': width, 'seat_plane_z_mm': z,
            'seat_opening_radius_mm': evaluate(v['seat_radius'], p), 'pusher_base_hole_radius_mm': 2.6,
            'passed': abs(width-34) < 1e-7 and abs(seat['bbox']['max'][2]-z) < 1e-7})
    return result


def optical_rays(spec, p):
    return [{'id': v['id']+'_front_'+str(z), 'start': [evaluate(v['center_x'], p), -35, z],
             'end': [evaluate(v['center_x'], p), 0, z]} for v in spec['variants'] for z in spec['interface_contract']['camera_target_z_mm']]


def render_plan(spec, p):
    hidden = ['clearance_envelope']
    return [
        {'id': 'optical', 'path': 'frame-optical.png', 'pose': 'ready', 'width': 1300, 'height': 700,
         'hide_roles': hidden+['receiver_carriage_envelope', 'split_receiver_seat_and_guide', 'actuator_envelope', 'external_bottom_pusher'],
         'camera': {'target': [0, 0, 22], 'yaw': -0.25, 'pitch': 0.18, 'distance': 110, 'fov': 0}},
        {'id': 'capture', 'path': 'frame-capture.png', 'pose': 'captured', 'variant': 'V20', 'width': 900, 'height': 1000,
         'hide_roles': hidden,
         'camera': {'target': [p['module_pitch']/2, 0, 16], 'yaw': -0.5, 'pitch': 0.18, 'distance': 175, 'fov': 0}},
        {'id': 'held', 'path': 'frame-held.png', 'pose': 'carried', 'variant': 'V20', 'width': 900, 'height': 1000,
         'hide_roles': hidden,
         'camera': {'target': [p['module_pitch']/2, 0, 26], 'yaw': -0.5, 'pitch': 0.18, 'distance': 195, 'fov': 0}}
    ]
