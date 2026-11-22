"""Derive both IM01 ice-bin cases and their common portable CAD operations."""
import json
from pathlib import Path
import sys

import assembly_model
import robot_spec
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/ice-maker-im01.shared.json'
SCHEMA = ROOT/'model/ice-maker-im01.schema.json'
VARIANTS = {'floor_standing': 'floor', 'countertop': 'worktop'}
SUPPORTS = ('FL', 'FR', 'RL', 'RR')
digest = robot_spec.digest
evaluate = robot_spec.evaluate


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if (spec['format'] != 'solidcraftbot.ice-maker/1' or spec['units'] != {'length': 'mm'}
            or spec['recipe'] != 'sloped_front_open_ice_bin_v1' or set(spec['variants']) != set(VARIANTS)):
        raise ValueError('Unsupported ice maker contract')
    for name, support in VARIANTS.items():
        case = spec['variants'][name]
        if case['support'] != support or set(case['overrides']) != (set() if name == 'floor_standing' else {'bin_height'}):
            raise ValueError('Only bin height differs between floor and worktop variants')
    floor, table = (parameters(variant(spec, name)) for name in VARIANTS)
    if interfaces(spec, floor)['bin_below_sill_l'] <= interfaces(spec, table)['bin_below_sill_l']:
        raise ValueError('The floor variant must have more clear bin volume')
    return spec


def variant(spec, name):
    if name not in VARIANTS:
        raise ValueError('Unknown ice maker variant: '+name)
    selected = assembly_model.parameter_variant(spec, spec['variants'][name]['overrides'])
    return selected


def parameters(spec):
    values = robot_spec.parameters(spec)
    for name, p in spec['parameters'].items():
        lo, hi = p['range']
        if p['unit'] != 'mm' or not lo <= values[name] <= hi:
            raise ValueError('Ice maker parameter outside its stated range: '+name)
    if (values['width'] - 2*(values['side_wall']+values['liner']) <= 0
            or values['depth'] - values['front_wall'] - values['rear_wall'] - 2*values['liner'] <= 0
            or values['sill'] <= values['bin_floor'] + values['liner']):
        raise ValueError('Positive clear ice storage dimensions required')
    return values


def support_points():
    return [('46-width/2', '48-depth/2'), ('width/2-46', '48-depth/2'),
            ('46-width/2', 'depth/2-48'), ('width/2-46', 'depth/2-48')]


def interfaces(spec, p):
    x = p['width']/2 - p['side_wall'] - p['liner']
    y = [p['front_wall'] - p['depth']/2 + p['liner'], p['depth']/2 - p['rear_wall'] - p['liner']]
    z = [p['bin_floor'] + p['liner'], p['sill']]
    return {'envelope_mm': [p['width'], p['depth'], p['total_height']],
            'bin_below_sill_l': 2*x*(y[1]-y[0])*(z[1]-z[0])/1_000_000,
            'bin_x_mm': [-x, x], 'bin_y_mm': y, 'bin_z_mm': z,
            'opening_z_mm': [p['sill'], p['bin_top']],
            'support_centres_mm': [[evaluate(x, p), evaluate(y, p), 0] for x, y in support_points()]}


def expanded(spec, p):
    result = {'id': spec['id'], 'status': spec['status'],
              'components': [{'id': 'IceMaker', 'grounded': True}],
              'bodies': [], 'operations': [], 'joints': []}
    steel, graphite, blue = '#c2ccd2', '#252b31', '#3165ad'
    front, rear = '-depth/2', 'depth/2'
    left, right = 'side_wall-width/2', 'width/2-side_wall'
    bin_front, bin_rear = 'front_wall-depth/2', 'depth/2-rear_wall'
    bin_width = 'width-2*side_wall'
    bin_depth = 'depth-front_wall-rear_wall'
    clear_width = bin_width+'-2*liner'

    def operation(name, target, shape, action='create'):
        result['operations'].append({'id': name, 'body': target, 'action': action, 'shape': shape})

    def create(name, shape, color, role):
        result['bodies'].append({'id': name, 'component': 'IceMaker', 'role': role,
                                 'appearance': {'color': color, 'opacity': 1}})
        operation(name, name, shape)

    def box_shape(origin, size):
        return {'kind': 'box', 'origin': origin, 'size': size}

    def box(name, origin, size, color, role):
        create(name, box_shape(origin, size), color, role)

    def profile(offset, depth, points):
        return {'kind': 'polygon_prism', 'plane': 'YZ', 'offset': offset, 'depth': depth, 'points': points}

    def cylinder(name, origin, radius, height, color, role, axis=(0, 0, 1)):
        create(name, {'kind': 'cylinder', 'origin': origin, 'radius': radius, 'height': height,
                      'axis': list(axis)}, color, role)

    # X runs across the front, Y points back, and four pads rest on Z=0.
    create('Casing', profile('-width/2', 'width', [
        [front+'+4', 'foot_height'], [rear, 'foot_height'], [rear, 'total_height-6'],
        [front+'+front_setback', 'total_height-6'], [front, 'panel_top'],
        [front+'+4', 'panel_top']]), graphite, 'enclosure')
    operation('BinAndOpening', 'Casing', profile(left, bin_width, [
        [bin_front, 'bin_floor'], [bin_rear, 'bin_floor'], [bin_rear, 'bin_top'],
        [front+'-2', 'bin_top'], [front+'-2', 'sill'], [bin_front, 'sill']]), 'cut')
    operation('GrilleRecess', 'Casing', box_shape([-132, front, 'foot_height+48'], [264, 26, 124]), 'cut')
    for side, x in [('L', '-width/2-1'), ('R', 'width/2-4')]:
        for col in range(2):
            for row in range(5):
                operation(f'SideVent_{side}{col}{row}', 'Casing',
                          box_shape([x, 35+60*col, f'foot_height+{40+11*row}'], [5, 47, 4]), 'cut')
    box('TopCap', ['-width/2', front+'+front_setback', 'total_height-6'],
        ['width', 'depth-front_setback', 6], steel, 'cap')
    box('FrontPanel', ['-width/2', front+'+2', 'foot_height'],
        ['width', 2, 'panel_top-foot_height'], steel, 'stainless_front')
    for col in range(6):
        for row in range(10):
            operation(f'FrontVent_{col}{row}', 'FrontPanel',
                      box_shape([-123+42*col, front+'+1', f'foot_height+{54+12*row}'], [36, 4, 5]), 'cut')

    box('BinFloorLiner', [left, bin_front, 'bin_floor'],
        [bin_width, bin_depth, 'liner'], '#4a74b5', 'bin_liner')
    for side, x in [('L', left), ('R', right+'-liner')]:
        box('BinSideLiner_'+side, [x, bin_front, 'bin_floor+liner'],
            ['liner', bin_depth, 'bin_height-liner'], blue, 'bin_liner')
    box('BinBackLiner', [left+'+liner', bin_rear+'-liner', 'bin_floor+liner'],
        [clear_width, 'liner', 'bin_height-liner'], '#416db1', 'bin_liner')
    box('BinFrontLiner', [left+'+liner', bin_front, 'bin_floor+liner'],
        [clear_width, 'liner', 'sill-bin_floor-liner'], blue, 'bin_liner')
    create('HopperFlapOpen', profile(left+'+liner', clear_width, [
        [front, 'bin_top-23'], [front+'+7', 'bin_top-29'],
        [front+'+78', 'bin_top-6'], [front+'+76', 'bin_top']]), '#343c46', 'illustrative_open_flap')

    box('ControlBezel', [-52, front+'+0.8', 'panel_top-79'], [104, 1.2, 62], '#2c3338', 'control_panel')
    box('Display', [-23, front, 'panel_top-52'], [46, 0.8, 22], '#142630', 'display')
    for index in range(5):
        cylinder(f'Button{index+1}', [-36+18*index, front, 'panel_top-65'], 5, 0.8,
                 '#a0acb2', 'control_button', (0, 1, 0))
    for index, color in enumerate(('#54b97c', '#69c592', '#adbc7c', '#dc8264')):
        cylinder(f'Indicator{index+1}', [-32+21*index, front, 'panel_top-23'], 2.4, 0.8,
                 color, 'status_indicator', (0, 1, 0))
    for tag, (x, y) in zip(SUPPORTS, support_points()):
        cylinder('FootPad_'+tag, [x, y, 0], 16, 10, '#25292e', 'support_foot')
        cylinder('FootPost_'+tag, [x, y, 10], 10, 'foot_height-10', '#626b72', 'support_foot')
    return result


def pose(spec, p, name=None):
    return {}


def samples(spec, p):
    return []


def solidcraft_commands(spec, p):
    return portable.solidcraft_commands(spec, p, sys.modules[__name__])
