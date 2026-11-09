"""Shared illustrative instrument recipes and existing portable CAD operations.

The two sources describe independent concepts, not manufacturer dimensions.
Both CAD backends consume the same expansion; neither imports the other's CAD.
"""
import ast
import json
import math
from pathlib import Path

import robot_spec
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {name: ROOT / 'model' / (name + '.shared.json')
           for name in ('nanodrop-concept', 'qubit-4-concept')}
RECIPES = {'nanodrop-concept': 'microvolume_pedestal_and_hinged_arm_v1',
           'qubit-4-concept': 'single_tube_chamber_and_hinged_cover_v1'}
PARAMETERS = {'width', 'depth', 'base_h', 'sample_x', 'sample_y', 'sample_z',
              'hinge_y', 'hinge_z', 'max_open'}
digest = robot_spec.digest
evaluate = robot_spec.evaluate


def load(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if (spec['format'] != 'solidcraftbot.instrument-concept/1'
            or spec['units'] != {'length': 'mm', 'angle': 'deg'}
            or spec['recipe'] != RECIPES.get(spec['family'])):
        raise ValueError('Unsupported instrument concept recipe or units')
    if (spec['design']['manufacturer_geometry_used'] is not False
            or spec['design']['manufacturer_logos_used'] is not False
            or spec['design']['dimensions_measured'] is not False):
        raise ValueError('This recipe describes an independent unmeasured concept')
    parameters(spec)
    if spec['family'] == 'nanodrop-concept':
        sample = spec['sample_reference']
        if (sample['kind'] != 'hemispherical_drop'
                or type(sample['volume_ul']) not in (int, float)
                or not 1 <= sample['volume_ul'] <= 2):
            raise ValueError('Illustrative drop must be in the declared 1-2 uL range')
    elif spec['sample_reference']['kind'] != 'generic_capped_tube':
        raise ValueError('Single-tube concept requires its generic tube reference')
    if set(spec['poses_deg']) != {'closed', 'loading'} or spec['poses_deg']['closed'] != 0:
        raise ValueError('Closed and loading poses required')
    if spec['default_pose'] not in spec['poses_deg']:
        raise ValueError('Unknown saved pose')
    return spec


def parameters(spec, overrides=None):
    if set(spec['parameters']) != PARAMETERS:
        raise ValueError('Only declared instrument concept parameters are supported')
    for name in overrides or {}:
        if name in spec['parameters'] and any(isinstance(n, ast.Name) for n in ast.walk(
                ast.parse(str(spec['parameters'][name]['expression']), mode='eval'))):
            raise ValueError('Override the driving parameter instead of derived ' + name)
    values = robot_spec.parameters(spec, overrides)
    for name, value in values.items():
        definition = spec['parameters'][name]
        lo, hi = definition['range']
        unit = 'deg' if name == 'max_open' else 'mm'
        if definition['unit'] != unit or not lo <= value <= hi:
            raise ValueError('Parameter outside declared range: ' + name)
    if any(type(a) not in (int, float) or not 0 <= a <= values['max_open']
           for a in spec['poses_deg'].values()):
        raise ValueError('Pose outside hinge limits')
    return values


def expanded(spec, p):
    result = {'id': spec['id'], 'status': spec['status'],
              'components': [{'id': 'Frame', 'grounded': True},
                             {'id': 'MovingArm', 'grounded': False}],
              'bodies': [], 'operations': [],
              'joints': [{'id': 'Hinge', 'type': 'revolute', 'parent': 'Frame',
                          'child': 'MovingArm', 'origin': ['sample_x', 'hinge_y', 'hinge_z'],
                          'axis': [-1, 0, 0], 'reference_x': [0, 1, 0],
                          'limit_parameter': 'max_open', 'limits_deg': [0, p['max_open']]}]}

    def body(name, color, component='Frame', role='concept_enclosure', opacity=1):
        result['bodies'].append({'id': name, 'component': component, 'role': role,
                                'appearance': {'color': color, 'opacity': opacity}})
        return name

    def op(name, target, kind, origin, action='create', **shape):
        result['operations'].append({'id': name, 'body': target, 'action': action,
                                     'shape': {'kind': kind, 'origin': origin, **shape}})

    def box(name, size, origin, color, component='Frame', role='concept_enclosure'):
        target = body(name, color, component, role)
        op(name, target, 'box', origin, size=size)
        return target

    def cylinder(name, radius, height, origin, color, component='Frame',
                 role='concept_structure', axis=None, opacity=1):
        target = body(name, color, component, role, opacity)
        op(name, target, 'cylinder', origin, radius=radius, height=height,
           axis=axis or [0, 0, 1])
        return target

    def screen(name, x, width, points, color):
        target = body(name, color, role='illustrative_display')
        result['operations'].append({'id': name, 'body': target, 'action': 'create',
                                     'shape': {'kind': 'polygon_prism', 'plane': 'YZ',
                                               'offset': x, 'depth': width, 'points': points}})

    box('Housing', ['width', 'depth', 'base_h'], ['-width/2', '-depth/2', 4], '#d2dce1')
    box('LowerBand', ['width-4', 'depth-4', 8], ['2-width/2', '2-depth/2', 4], '#253e4b')
    for suffix, x, y in [('FL', '14-width/2', '14-depth/2'),
                         ('FR', 'width/2-14', '14-depth/2'),
                         ('RL', '14-width/2', 'depth/2-14'),
                         ('RR', 'width/2-14', 'depth/2-14')]:
        cylinder('Foot_' + suffix, 7, 4, [x, y, 0], '#26333a')
    if spec['family'] == 'nanodrop-concept':
        box('MeasurementDeck', [58, 'depth-28', 4], ['sample_x-29', '14-depth/2', 'base_h+4'], '#527c86')
        cylinder('PedestalMount', 13, 5, ['sample_x', 'sample_y', 'base_h+8'], '#a5b5bb')
        cylinder('LowerPedestal', 2.4, 2.7, ['sample_x', 'sample_y', 'sample_z-3'], '#d3dce0', role='lower_measurement_pedestal')
        cylinder('LowerOpticalFace', 1.35, 0.3, ['sample_x', 'sample_y', 'sample_z-0.3'], '#e4e9eb', role='flat_sample_surface')
        # 1 uL equals 1 mm^3. A hemisphere makes the displayed volume explicit.
        radius = (3 * spec['sample_reference']['volume_ul'] / (2 * math.pi)) ** (1/3)
        drop = body('SampleDrop', '#218cc4', role='illustrative_fluid', opacity=0.8)
        op('SampleDrop', drop, 'sphere', ['sample_x', 'sample_y', 'sample_z'], radius=radius)
        op('DropLowerHalf', drop, 'box', [f'sample_x-{2*radius}', f'sample_y-{2*radius}', f'sample_z-{2*radius}'],
           action='cut', size=[4*radius, 4*radius, 2*radius])
        screen('DisplayHousing', '12-width/2', 'width/2-25',
               [[8, 'base_h+4'], [86, 'base_h+4'], [86, 'base_h+61'], [8, 'base_h+15']], '#284954')
        screen('DisplayGlass', '17-width/2', 'width/2-35',
               [[16, 'base_h+20.4'], [78, 'base_h+57'], [78, 'base_h+58'], [16, 'base_h+21.4']], '#102a3c')
        for index, height in enumerate([8, 17, 30, 21, 10]):
            box('Spectrum_' + str(index), [4, 2, height], [f'{21+index*9}-width/2', 47, 'base_h+40'], '#50d1c0', role='illustrative_display')
        bottom, length = 'hinge_z-6', 'hinge_y-sample_y+9'
        arm = box('Lever', [18, length, 10], ['sample_x-9', 'sample_y-9', bottom], '#168e91', 'MovingArm', 'sampling_lever')
        op('LeverEye', arm, 'cylinder', ['sample_x-9', 'hinge_y', 'hinge_z'], action='join', radius=8, height=18, axis=[1, 0, 0])
        op('LeverBore', arm, 'cylinder', ['sample_x-10', 'hinge_y', 'hinge_z'], action='cut', radius=4.4, height=20, axis=[1, 0, 0])
        box('FingerGrip', [27, 16, 7], ['sample_x-13.5', 'sample_y-12', 'hinge_z+4'], '#294956', 'MovingArm', 'lever_grip')
        cylinder('UpperProbe', 2.4, 5.8, ['sample_x', 'sample_y', 'sample_z+1.2'], '#c6d2d9', 'MovingArm', 'upper_measurement_probe')
        cylinder('UpperOpticalFace', 1.35, 0.25, ['sample_x', 'sample_y', 'sample_z+1.2'], '#dce8ee', 'MovingArm', 'upper_sample_surface')
        support_offset, support_width, pin_radius = 10, 7, 4
    else:
        # A real recess is cut through the chassis into the single-tube collar.
        op('ChamberRecess', 'Housing', 'cylinder', ['sample_x', 'sample_y', 'sample_z-30'], action='cut', radius=4.5, height=35, axis=[0, 0, 1])
        collar = cylinder('ChamberCollar', 21, 12, ['sample_x', 'sample_y', 'sample_z-12'], '#375a67', role='sample_chamber')
        op('ChamberOpening', collar, 'cylinder', ['sample_x', 'sample_y', 'sample_z-13'], action='cut', radius=4.5, height=14, axis=[0, 0, 1])
        ring = cylinder('ChamberRim', 10, 1.2, ['sample_x', 'sample_y', 'sample_z'], '#adc2c9', role='sample_chamber_rim')
        op('RimOpening', ring, 'cylinder', ['sample_x', 'sample_y', 'sample_z-0.1'], action='cut', radius=4.5, height=1.4, axis=[0, 0, 1])
        tube = cylinder('ReferenceTube', 3.75, 20, ['sample_x', 'sample_y', 'sample_z-24'], '#bdd5dd', role='tube_shape_reference', opacity=0.4)
        op('TubeBottom', tube, 'cone', ['sample_x', 'sample_y', 'sample_z-29'], action='join', radius=0.7, top_radius=3.75, height=5, axis=[0, 0, 1])
        op('TubeInterior', tube, 'cylinder', ['sample_x', 'sample_y', 'sample_z-23'], action='cut', radius=3.15, height=20, axis=[0, 0, 1])
        cylinder('TubeCap', 4.2, 2.5, ['sample_x', 'sample_y', 'sample_z-4'], '#a4c6d0', role='tube_shape_reference', opacity=0.7)
        screen('DisplayHousing', '12-width/2', 'width-24',
               [['12-depth/2', 'base_h+4'], [3, 'base_h+4'], [3, 'base_h+26'], ['12-depth/2', 'base_h+9']], '#365866')
        screen('DisplayGlass', '19-width/2', 'width-38',
               [['22-depth/2', 'base_h+11.7'], [-5, 'base_h+25.7'], [-5, 'base_h+26.5'], ['22-depth/2', 'base_h+12.5']], '#153348')
        for index in range(3):
            screen('DisplayTile_' + str(index), f'{24+index*37}-width/2', 30,
                   [[-58, 'base_h+18.4'], [-28, 'base_h+22.7'], [-28, 'base_h+23.4'], [-58, 'base_h+19.1']], '#4ab4b6' if index != 1 else '#9cae83')
        arm = box('Cover', [48, 'hinge_y-sample_y+24', 8], ['sample_x-24', 'sample_y-24', 'sample_z+4'], '#168e91', 'MovingArm', 'chamber_cover')
        op('CoverEye', arm, 'cylinder', ['sample_x-24', 'hinge_y', 'hinge_z'], action='join', radius=7, height=48, axis=[1, 0, 0])
        op('CoverBore', arm, 'cylinder', ['sample_x-25', 'hinge_y', 'hinge_z'], action='cut', radius=3.4, height=50, axis=[1, 0, 0])
        box('CoverGrip', [24, 7, 4], ['sample_x-12', 'sample_y-27', 'sample_z+12'], '#294956', 'MovingArm', 'cover_grip')
        support_offset, support_width, pin_radius = 25, 6, 3
    for suffix, x in [('Left', f'sample_x-{support_offset+support_width}'), ('Right', f'sample_x+{support_offset}')]:
        box('HingeSupport_' + suffix, [support_width, 18, 'hinge_z-base_h'], [x, 'hinge_y-9', 'base_h+4'], '#536e7a')
    cylinder('HingePin', pin_radius, 2*(support_offset+support_width),
             [f'sample_x-{support_offset+support_width}', 'hinge_y', 'hinge_z'], '#b1bdc5', axis=[1, 0, 0])
    result['parameter_values'] = p
    return result


def pose(spec, p, name=None):
    return {'Hinge': spec['poses_deg'][name or spec['default_pose']]}


def validate_pose(source, values):
    if (set(values) != {'Hinge'} or type(values['Hinge']) not in (int, float)
            or not math.isfinite(values['Hinge'])
            or not 0 <= values['Hinge'] <= source['joints'][0]['limits_deg'][1]):
        raise ValueError('Hinge requires degrees within its concept limits')


def samples(spec, p):
    return [{'id': 'hinge_%02d' % i, 'joint_values': {'Hinge': p['max_open'] * i/15}}
            for i in range(16)]


def transform(spec, p, component, point, angle):
    if component == 'Frame':
        return list(point)
    x, y, z = point
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    dy, dz = y-p['hinge_y'], z-p['hinge_z']
    return [x, p['hinge_y'] + c*dy + s*dz, p['hinge_z'] - s*dy + c*dz]


def interfaces(spec, p, angle=0):
    frames = {'sample_surface': [p['sample_x'], p['sample_y'], p['sample_z']],
              'hinge': [p['sample_x'], p['hinge_y'], p['hinge_z']]}
    if spec['family'] == 'nanodrop-concept':
        frames['upper_surface'] = transform(spec, p, 'MovingArm',
                                             [p['sample_x'], p['sample_y'], p['sample_z']+1.2], angle)
    else:
        frames['tube_axis'] = [p['sample_x'], p['sample_y'], p['sample_z']-24]
    return frames


def solidcraft_commands(spec, p):
    # The provider interface reuses the existing primitive and hinge adapter.
    class Provider:
        SOURCE = SOURCES[spec['family']]
        expanded = staticmethod(expanded)
        samples = staticmethod(samples)
        pose = staticmethod(pose)
    commands = portable.solidcraft_commands(spec, p, Provider)
    for command in commands:
        if command['command'] == 'document.metadata.set':
            command['params'] = {'values': {'org.solidcraftbot.instrument-concept': {
                'source': str(SOURCES[spec['family']].relative_to(ROOT)),
                'source_sha256': digest(SOURCES[spec['family']]),
                'status': spec['status'], 'recipe': spec['recipe']}}}
    commands.append({'command': 'browser.visibility',
                     'params': {'folder': 'sketches', 'visible': False}})
    return commands
