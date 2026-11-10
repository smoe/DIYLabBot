"""Portable hollow glassware, removable closures and geometric access references."""
import copy
import json
import math
from pathlib import Path
import re

import assembly_model as assembly
import robot_spec as robot
import tube_carrier_model as portable

ROOT = robot.ROOT
SOURCE = ROOT / 'model/lab-glassware.shared.json'
digest = robot.digest
evaluate = robot.evaluate
RECIPES = {
    'beaker': 'hollow_beaker_with_pour_spout/1',
    'funnel': 'open_conical_funnel_with_continuous_stem/1',
    'bottle': 'hollow_shoulder_bottle_with_removable_closure/1',
}
FIELDS = {
    'beaker': set('diameter height wall bottom spout_length spout_width spout_depth outer_radius inner_radius'.split()),
    'funnel': set('diameter bowl_height stem_length stem_diameter wall outer_radius inner_radius stem_radius outlet_radius height'.split()),
    'bottle': set('diameter body_height shoulder_height neck_height neck_diameter wall bottom cap_skirt cap_wall cap_clearance seal_gap stopper_depth stopper_grip_height outer_radius inner_radius neck_radius mouth_radius shoulder_top height cap_radius'.split()),
}


def finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite numeric value required: ' + name)
    return value


def load(path=SOURCE):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    fields = {'format', 'id', 'units', 'status', 'material', 'references', 'families', 'items', 'limitations'}
    if set(catalog) != fields or catalog['format'] != 'solidcraftbot.lab-glassware/1':
        raise ValueError('Unsupported glassware catalog fields or format')
    if catalog['units'] != {'length': 'mm', 'angle': 'deg', 'volume': 'mL'}:
        raise ValueError('Glassware requires explicit mm, deg and mL')
    if (catalog['material'] != {'family': 'borosilicate_glass', 'measured_density_g_per_ml': None,
                               'measured_empty_mass_g': None}
            or not catalog['status'] or not catalog['limitations']):
        raise ValueError('Unmeasured glassware material and limitations required')
    if set(catalog['families']) != set(RECIPES) or not catalog['items']:
        raise ValueError('Exactly the implemented glassware families are supported')
    for family, definition in catalog['families'].items():
        if set(definition) != {'recipe', 'parameters'} or definition['recipe'] != RECIPES[family]:
            raise ValueError('Unsupported glassware recipe: ' + family)
        if set(definition['parameters']) != FIELDS[family]:
            raise ValueError('Only implemented family parameters are supported: ' + family)
        for name, parameter in definition['parameters'].items():
            if (set(parameter) != {'expression', 'unit', 'range', 'description'}
                    or parameter['unit'] != 'mm' or not parameter['description']):
                raise ValueError('Explicit length parameter definition required: ' + name)
            bounds = parameter['range']
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError('Parameter range required: ' + name)
            lo, hi = (finite(v, name) for v in bounds)
            if lo <= 0 or hi < lo:
                raise ValueError('Positive ordered parameter range required: ' + name)
    for identity, reference in catalog['references'].items():
        expected = {'url', 'accessed', 'manufacturer', 'part', 'description', 'nominal_volume_ml',
                    'reference_graduations_ml', 'outer_dimensions_mm'}
        if (set(reference) != expected or not reference['url'].startswith('https://')
                or reference['outer_dimensions_mm'] is not None):
            raise ValueError('Documentary product reference without measured dimensions required: ' + identity)
        nominal = finite(reference['nominal_volume_ml'], identity)
        marks = reference['reference_graduations_ml']
        if set(marks) != {'first', 'last', 'step'}:
            raise ValueError('Reference graduation interval required')
        first, last, step = (finite(marks[k], k) for k in ('first', 'last', 'step'))
        if not 0 < first <= last <= nominal or step <= 0:
            raise ValueError('Reference graduations must lie within the nominal volume')
    for identity, item in catalog['items'].items():
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', identity):
            raise ValueError('Stable glassware item ID required')
        if set(item) != {'family', 'label', 'nominal_volume_ml', 'closure', 'reference', 'overrides'}:
            raise ValueError('Unsupported glassware item fields: ' + identity)
        if item['family'] not in RECIPES or not item['label']:
            raise ValueError('Implemented family and label required')
        allowed = {'screw_cap', 'glass_stopper'} if item['family'] == 'bottle' else {'none'}
        if item['closure'] not in allowed:
            raise ValueError('Closure does not match the vessel family: ' + identity)
        if (item['family'] == 'funnel') != (item['nominal_volume_ml'] is None):
            raise ValueError('Funnels have a diameter, not a nominal storage volume')
        if item['reference'] is not None:
            if item['reference'] not in catalog['references']:
                raise ValueError('Unknown product reference: ' + identity)
            ref = catalog['references'][item['reference']]
            if ref['nominal_volume_ml'] != item['nominal_volume_ml']:
                raise ValueError('Nominal volume differs from its documentary reference')
        if any(type(v) not in (int, float) for v in item['overrides'].values()):
            raise ValueError('Catalog variants require numeric dimensions')
        materialize(catalog, identity)
    return catalog


def materialize(catalog, identity, state=None, overrides=None, context=None):
    """Instantiate a family once; variants contain only driving dimension overrides."""
    if identity not in catalog['items']:
        raise ValueError('Unknown glassware item: ' + identity)
    item = catalog['items'][identity]
    state = ('closed' if item['family'] == 'bottle' else 'open') if state is None else state
    if type(state) is not str or state not in ({'open', 'closed'} if item['family'] == 'bottle' else {'open'}):
        raise ValueError('Unsupported glassware configuration: ' + str(state))
    spec = {'id': identity + '_' + state, 'item_id': identity, 'item': copy.deepcopy(item),
            'state': state, 'status': catalog['status'],
            'parameters': copy.deepcopy(catalog['families'][item['family']]['parameters'])}
    spec = assembly.parameter_variant(spec, item['overrides'])
    spec = assembly.parameter_variant(spec, overrides, context)
    if item['family'] == 'bottle':
        # These offsets describe two static configurations, not a removal trajectory.
        closed_bottom = ('height-cap_skirt+seal_gap' if item['closure'] == 'screw_cap'
                         else 'height-stopper_depth')
        for name, expression in {
            'closure_x': 'outer_radius+cap_radius+20' if state == 'open' else 0,
            'closure_z': '-(' + closed_bottom + ')' if state == 'open' else 0,
        }.items():
            spec['parameters'][name] = {'expression': expression, 'unit': 'mm', 'range': [-300, 300],
                                        'description': 'Derived static closure configuration offset'}
    parameters(spec)
    return spec


def parameters(spec, overrides=None):
    if overrides:
        # State offsets must never become a second, independently edited state.
        if set(overrides) - FIELDS[spec['item']['family']]:
            raise ValueError('Only declared family dimensions may be overridden')
        spec = assembly.parameter_variant(spec, overrides)
    p = robot.parameters(spec)
    for name, definition in spec['parameters'].items():
        lo, hi = definition['range']
        if definition['unit'] != 'mm' or not lo <= p[name] <= hi:
            raise ValueError('Parameter outside its declared mm range: ' + name)
    family = spec['item']['family']
    if p['inner_radius'] <= 0:
        raise ValueError('Glassware requires a positive clear interior')
    if family == 'beaker':
        if (p['bottom'] >= p['height'] - p['spout_depth'] or p['spout_width'] <= 2*p['wall']
                or p['spout_depth'] <= 2*p['wall'] or p['spout_width'] >= p['diameter']):
            raise ValueError('Beaker requires a bottom and a genuinely open pouring trough')
    elif family == 'funnel':
        if p['outlet_radius'] <= 0 or p['inner_radius'] <= p['outlet_radius']:
            raise ValueError('Funnel requires an open stem below a wider inlet')
    else:
        if (p['mouth_radius'] <= 1 or p['inner_radius'] <= p['neck_radius']
                or p['bottom'] >= p['body_height']
                or max(p['cap_skirt'], p['stopper_depth']) >= p['neck_height']
                or p['mouth_radius'] <= p['cap_clearance'] + 0.3):
            raise ValueError('Bottle shoulder, neck, bottom and closure must leave a real cavity')
    nominal = spec['item']['nominal_volume_ml']
    if nominal is not None:
        if finite(nominal, 'nominal_volume_ml') <= 0 or nominal > cavity_volume_ml(spec, p):
            raise ValueError('Nominal volume does not fit below the modeled access/spout region')
    return p


def cavity_segments(spec, p):
    """Axial clear-space frustums; the beaker core ends below its spout root."""
    family = spec['item']['family']
    if family == 'beaker':
        return [(p['bottom'], p['height']-p['spout_depth'], p['inner_radius'], p['inner_radius'])]
    if family == 'funnel':
        return [(0, p['stem_length'], p['outlet_radius'], p['outlet_radius']),
                (p['stem_length'], p['height'], p['outlet_radius'], p['inner_radius'])]
    return [(p['bottom'], p['body_height'], p['inner_radius'], p['inner_radius']),
            (p['body_height'], p['shoulder_top'], p['inner_radius'], p['mouth_radius']),
            (p['shoulder_top'], p['height'], p['mouth_radius'], p['mouth_radius'])]


def cavity_volume_ml(spec, p, z=None):
    if z is not None:
        finite(z, 'height_mm')
    total = 0
    for lo, hi, r0, r1 in cavity_segments(spec, p):
        top = hi if z is None else min(hi, max(lo, z))
        radius = r0 + (r1-r0)*(top-lo)/(hi-lo)
        total += math.pi*(top-lo)*(r0*r0+r0*radius+radius*radius)/3
    return total / 1000  # 1 mL = 1000 mm³, distinct from 1 µL = 1 mm³.


def fill_height_mm(spec, p, volume_ml):
    volume = finite(volume_ml, 'volume_ml')
    if not 0 <= volume <= cavity_volume_ml(spec, p):
        raise ValueError('Volume is outside the modeled clear space')
    lo, hi = cavity_segments(spec, p)[0][0], cavity_segments(spec, p)[-1][1]
    for _ in range(64):
        middle = (lo+hi)/2
        if cavity_volume_ml(spec, p, middle) < volume:
            lo = middle
        else:
            hi = middle
    return (lo+hi)/2


def interfaces(spec, p):
    def frame(point, diameter=None, axis=(0, 0, 1)):
        value = {'origin_mm': list(point), 'z_axis': list(axis), 'x_axis': [1, 0, 0]}
        if axis == (1, 0, 0):
            value['x_axis'] = [0, 1, 0]
        if diameter is not None:
            value['clear_diameter_mm'] = diameter
        return value
    family = spec['item']['family']
    mouth_radius = p.get('mouth_radius', p['inner_radius'])
    result = {'mouth': {**frame([0, 0, p['height']], 2*mouth_radius),
                        'accessible': spec['state'] == 'open'}}
    if family == 'funnel':
        result['outlet'] = frame([0, 0, 0], 2*p['outlet_radius'], (0, 0, -1))
        result['stem_grip_axis'] = frame([0, 0, p['stem_length']/2])
    else:
        result['support'] = frame([0, 0, 0])
        result['body_grip_axis'] = frame([0, 0, p.get('body_height', p['height'])/2])
        nominal = spec['item']['nominal_volume_ml']
        result['nominal_fill_plane'] = frame([0, 0, fill_height_mm(spec, p, nominal)])
        if family == 'beaker':
            result['pour_lip'] = frame([p['outer_radius']+p['spout_length'], 0, p['height']], axis=(1, 0, 0))
        else:
            top = (p['height']+p['seal_gap']+p['cap_wall'] if spec['item']['closure'] == 'screw_cap'
                   else p['height']+p['seal_gap']+p['stopper_grip_height'])
            result['closure_grip_axis'] = frame([p['closure_x'], 0, top+p['closure_z']])
    return result


def accessible_mouth(spec, p):
    frame = interfaces(spec, p)['mouth']
    if not frame['accessible']:
        raise ValueError('Remove the closure before requesting pipette access')
    return frame


def expanded(spec, p):
    """Lower semantic vessel/closure operations once for both native CAD targets."""
    family = spec['item']['family']
    result = {'id': spec['id'], 'status': spec['status'], 'parameters': spec['parameters'],
              'components': [{'id': 'Glass', 'grounded': True}], 'bodies': [], 'operations': [], 'joints': []}

    def body(name, component='Glass', color='#91b8c4', opacity=0.58, role='glass_vessel'):
        result['bodies'].append({'id': name, 'component': component, 'role': role,
                                 'appearance': {'color': color, 'opacity': opacity}})

    def profile(name, points, target='Vessel', center=0):
        result['operations'].append({'id': name, 'body': target, 'action': 'create',
                                    'shape': {'kind': 'revolved_profile', 'center_x': center, 'points_rz': points}})

    body('Vessel', role='glass_funnel' if family == 'funnel' else 'glass_vessel')
    if family == 'beaker':
        profile('HollowBeaker', [[0, 0], ['outer_radius', 0], ['outer_radius', 'height'],
                                 ['inner_radius', 'height'], ['inner_radius', 'bottom'], [0, 'bottom']])
        for name, action, offset, depth, points in [
            ('PourSpoutOuter', 'join', '-spout_width/2', 'spout_width',
             [['inner_radius-1', 'height-spout_depth'], ['outer_radius+spout_length', 'height-2*wall'],
              ['outer_radius+spout_length', 'height'], ['inner_radius-1', 'height']]),
            ('PourSpoutChannel', 'cut', '-spout_width/2+wall', 'spout_width-2*wall',
             [['inner_radius-2', 'height-spout_depth+wall'], ['outer_radius+spout_length+1', 'height-wall'],
              ['outer_radius+spout_length+1', 'height+1'], ['inner_radius-2', 'height+1']]),
        ]:
            result['operations'].append({'id': name, 'body': 'Vessel', 'action': action,
                                        'shape': {'kind': 'polygon_prism', 'plane': 'XZ', 'offset': offset,
                                                  'depth': depth, 'points': points}})
    elif family == 'funnel':
        profile('ThroughFunnel', [['stem_radius', 0], ['stem_radius', 'stem_length'],
                                  ['outer_radius', 'height'], ['inner_radius', 'height'],
                                  ['outlet_radius', 'stem_length'], ['outlet_radius', 0]])
    else:
        profile('HollowBottle', [[0, 0], ['outer_radius', 0], ['outer_radius', 'body_height'],
                                 ['neck_radius', 'shoulder_top'], ['neck_radius', 'height'],
                                 ['mouth_radius', 'height'], ['mouth_radius', 'shoulder_top'],
                                 ['inner_radius', 'body_height'], ['inner_radius', 'bottom'], [0, 'bottom']])
        result['components'].append({'id': 'ClosureGroup', 'grounded': True})
        screw = spec['item']['closure'] == 'screw_cap'
        body('Closure', component='ClosureGroup', color='#346a91' if screw else '#a6c8cf',
             opacity=1 if screw else .7, role='screw_cap_envelope' if screw else 'glass_stopper_envelope')
        if screw:
            points = [['neck_radius+cap_clearance', 'height-cap_skirt+seal_gap'],
                      ['cap_radius', 'height-cap_skirt+seal_gap'],
                      ['cap_radius', 'height+seal_gap+cap_wall'], [0, 'height+seal_gap+cap_wall'],
                      [0, 'height+seal_gap'], ['neck_radius+cap_clearance', 'height+seal_gap']]
        else:
            points = [[0, 'height-stopper_depth'], ['mouth_radius-cap_clearance-0.3', 'height-stopper_depth'],
                      ['mouth_radius-cap_clearance', 'height+seal_gap'],
                      ['neck_radius+2', 'height+seal_gap'], ['neck_radius+2', 'height+seal_gap+stopper_grip_height'],
                      [0, 'height+seal_gap+stopper_grip_height']]
        profile('RemovableClosure', [[r, '('+str(z)+')+closure_z'] for r, z in points],
                target='Closure', center='closure_x')
    return result


def pose(spec, p):
    return {}  # Static open/closed configurations, intentionally no fabricated motion joint.


def samples(spec, p):
    return []


def solidcraft_commands(spec, p, provider=None):
    if provider is None:
        class Provider:
            SOURCE = SOURCE
            expanded = staticmethod(expanded)
            pose = staticmethod(pose)
            samples = staticmethod(samples)
        provider = Provider
    commands = portable.solidcraft_commands(spec, p, provider)
    for command in commands:
        if command['command'] == 'document.metadata.set':
            command['params'] = {'values': {'org.solidcraftbot.lab-glassware': {
                'source': str(SOURCE.relative_to(ROOT)), 'source_sha256': digest(SOURCE),
                'item': spec.get('item_id'), 'configuration': spec.get('state'), 'status': spec['status']}}}
    commands.append({'command': 'browser.visibility', 'params': {'folder': 'sketches', 'visible': False}})
    return commands


def cases(catalog):
    return [(identity, state) for identity, item in catalog['items'].items()
            for state in (('closed', 'open') if item['family'] == 'bottle' else ('open',))]


def case_id(identity, state):
    return identity + '_' + state


def resolve_reference(ref, overrides=None, context=None):
    path = assembly.validate_reference(ref)
    catalog = load(path)
    candidates = [(identity, state) for identity, state in cases(catalog)
                  if case_id(identity, state) == ref.get('case')]
    if len(candidates) != 1:
        raise ValueError('Select an explicit glassware item/configuration through its report case')
    return materialize(catalog, *candidates[0], overrides=overrides, context=context)


def overview(catalog):
    """Derived contact sheet; item geometry is compiled from catalog references."""
    selected = [('beaker_250', 'open'), ('funnel_60', 'open'),
                ('screw_bottle_250', 'closed'), ('screw_bottle_250', 'open'),
                ('stopper_bottle_250', 'open')]
    spec = {'id': 'LaboratoryGlasswareOverview', 'status': catalog['status'], 'parameters': {}}
    result = {'id': spec['id'], 'status': spec['status'], 'parameters': {}, 'components': [],
              'bodies': [], 'operations': [], 'joints': []}
    placements, cursor = [], 0
    for index, (identity, state) in enumerate(selected):
        item = materialize(catalog, identity, state)
        p = parameters(item)
        prefix = 'Item' + str(index) + '_'
        x = cursor + p['outer_radius']
        placements.append({'reference': {'source': str(SOURCE.relative_to(ROOT)), 'case': case_id(identity, state)},
                           'translation_mm': [x, 0, 0], 'label': item['item']['label'], 'state': state})
        source = expanded(item, p)
        for component in source['components']:
            result['components'].append({**component, 'id': prefix+component['id']})
        for b in source['bodies']:
            result['bodies'].append({**b, 'id': prefix+b['id'], 'component': prefix+b['component']})
        for operation in source['operations']:
            shape = copy.deepcopy(operation['shape'])
            if shape['kind'] == 'revolved_profile':
                shape['center_x'] = evaluate(shape['center_x'], p) + x
                shape['points_rz'] = [[evaluate(v, p) for v in point] for point in shape['points_rz']]
            else:
                shape['offset'] = evaluate(shape['offset'], p)
                shape['depth'] = evaluate(shape['depth'], p)
                shape['points'] = [[evaluate(a, p)+x, evaluate(b, p)] for a, b in shape['points']]
            result['operations'].append({**operation, 'id': prefix+operation['id'],
                                         'body': prefix+operation['body'], 'shape': shape})
        right = max(p['outer_radius']+p.get('spout_length', 0), p.get('closure_x', 0)+p.get('cap_radius', 0))
        cursor = x + right + 28
    return spec, result, placements
